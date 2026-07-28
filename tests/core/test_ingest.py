from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikicli.core import ingest
from wikicli.core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from wikicli.core.ingest import PageChange, RetrievalCase, check_ingestion, update_knowledge
from wikicli.core.page import WikiDatabase


def _page(path: Path, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}\n", encoding="utf-8")


def _valid_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "raw").mkdir(parents=True)
    (root / "raw" / "one.md").write_text("alpha source", encoding="utf-8")
    (root / "raw" / "two.md").write_text("synthesis source", encoding="utf-8")
    _page(
        root / "wiki/entities/alpha.md",
        """
        title: Alpha
        type: entity
        scope: company
        summary: Primary company entity.
        tags: [company]
        aliases: [first company]
        context_keys: [company identity]
        updated: 2026-07-25
        verified: false
        """,
        "# Alpha\n\nSee [[Source Synthesis]].\n\n## Provenance and status\n\nCompiled from `raw/one.md`.",
    )
    _page(
        root / "wiki/syntheses/source-synthesis.md",
        """
        title: Source Synthesis
        type: synthesis
        scope: company
        summary: Combines the source material into a user-facing answer.
        tags: [synthesis]
        aliases: [combined answer]
        context_keys: [how sources fit together]
        updated: 2026-07-25
        verified: false
        """,
        "# Source Synthesis\n\nExplains [[Alpha]].\n\n## Provenance and status\n\nCompiled from `raw/one.md` and `raw/two.md`.",
    )
    registry = {
        "version": 1,
        "sources": {
            "raw/one.md": {
                "status": "incorporated",
                "pages": ["wiki/entities/alpha.md", "wiki/syntheses/source-synthesis.md"],
                "note": "Split entity facts from the cross-source answer.",
            },
            "raw/two.md": {
                "status": "incorporated",
                "pages": ["wiki/syntheses/source-synthesis.md"],
                "note": "Combined with the first source.",
            },
        },
    }
    (root / "wiki/sources.json").write_text(json.dumps(registry), encoding="utf-8")
    (root / "benchmarks").mkdir()
    (root / "benchmarks/cold_start_cases.json").write_text(
        json.dumps(
            [
                {"query": "alpha", "relevance": {"alpha": 3}},
                {"query": "source synthesis", "relevance": {"source-synthesis": 3}},
            ]
        ),
        encoding="utf-8",
    )
    (root / "internal").mkdir(parents=True)
    (root / "internal/skills").mkdir()
    (root / "internal/prompts").mkdir()
    db = WikiDatabase(root / "wiki")
    generate_index(db, root / "wiki")
    generate_backlinks(db, root / "wiki")
    generate_tags(db, root / "wiki")
    generate_registry(root)
    return root


def test_valid_ingestion_proves_sources_became_connected_knowledge(tmp_path: Path):
    report = check_ingestion(_valid_repo(tmp_path), base=None)

    assert report.ok, report.errors
    assert "2 knowledge pages; 2 registered sources" in report.facts
    assert any("cold-start hit@1 100.0%" in fact for fact in report.facts)


def test_unclassified_raw_source_fails_coverage(tmp_path: Path):
    root = _valid_repo(tmp_path)
    (root / "raw/unclassified.md").write_text("forgotten", encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert "raw/unclassified.md: raw source is not classified in sources.json" in report.errors


def test_source_mapping_requires_page_level_provenance(tmp_path: Path):
    root = _valid_repo(tmp_path)
    synthesis = root / "wiki/syntheses/source-synthesis.md"
    synthesis.write_text(synthesis.read_text(encoding="utf-8").replace(" and `raw/two.md`", ""), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert "raw/two.md: wiki/syntheses/source-synthesis.md does not cite this source in provenance" in report.errors
    assert "no synthesis page combines evidence from multiple sources" in report.errors


def test_every_page_needs_a_novice_language_question(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases = [{"query": "alpha", "relevance": {"alpha": 3}}]
    (root / "benchmarks/cold_start_cases.json").write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert "source-synthesis: no novice-language cold-start question targets this page" in report.errors


def _knowledge_update(root: Path, source_content: str, confirmed: bool, approval_digest: str | None = None):
    source_placeholder = "{{SOURCE_PATH}}"
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Beta]].")
    )
    beta = f"""---
title: Beta
type: concept
scope: company
summary: Preserves complex source nuance for retrieval.
tags: [company, nuance]
aliases: [second concept]
context_keys: [complex nuanced source]
updated: 2026-07-26
verified: false
---

# Beta

Beta retains headings, Unicode, and exact source material while linking to [[Alpha]].

## Provenance and status

Compiled from `{source_placeholder}`.
"""
    return update_knowledge(
        root,
        source_title="Complex context",
        source_content=source_content,
        existing_source_path=None,
        source_type="user-confirmed context",
        page_changes=[
            PageChange(
                "wiki/entities/alpha.md", alpha.replace("`raw/one.md`", f"`raw/one.md` and `{source_placeholder}`")
            ),
            PageChange("wiki/concepts/beta.md", beta),
        ],
        retrieval_cases=[RetrievalCase("where is the complex nuanced source", {"beta": 3})],
        confirmed=confirmed,
        approval_digest=approval_digest,
    )


def _preview_and_apply(root: Path, source_content: str):
    preview = _knowledge_update(root, source_content, confirmed=False)
    return _knowledge_update(root, source_content, confirmed=True, approval_digest=preview.approval_digest)


def test_knowledge_update_preview_is_lossless_and_does_not_write(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "# Exact heading\n\nUnicode: naïve → β\n\n```sql\nselect  *  from x;\n```\nNo trailing newline"

    result = _knowledge_update(root, source, confirmed=False)

    assert result.status == "ready"
    assert not (root / result.source_path).exists()
    assert not (root / "wiki/concepts/beta.md").exists()


def test_knowledge_update_requires_the_exact_preview_digest(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "Approval-bound source"
    preview = _knowledge_update(root, source, confirmed=False)

    with pytest.raises(ValueError, match="approval digest"):
        _knowledge_update(root, source, confirmed=True)

    changed = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("Primary company entity.", "Primary company entity with a concurrent edit.")
    )
    (root / "wiki/entities/alpha.md").write_text(changed, encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        _knowledge_update(root, source, confirmed=True, approval_digest=preview.approval_digest)


def test_knowledge_update_applies_complete_validated_graph_and_preserves_source(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "# Exact heading\n\nUnicode: naïve → β\n\n```sql\nselect  *  from x;\n```\nNo trailing newline"

    result = _preview_and_apply(root, source)

    assert result.status == "applied"
    assert (root / result.source_path).read_text(encoding="utf-8") == source
    assert check_ingestion(root, base=None).ok
    assert "wiki/concepts/beta.md" in result.pages


def test_invalid_knowledge_update_leaves_repository_unchanged(tmp_path: Path):
    root = _valid_repo(tmp_path)
    registry_before = (root / "wiki/sources.json").read_bytes()

    with pytest.raises(ValueError, match="failed validation"):
        update_knowledge(
            root,
            source_title="Broken context",
            source_content="Exact source",
            existing_source_path=None,
            source_type="conversation",
            page_changes=[PageChange("wiki/concepts/broken-update.md", "# Missing required structure")],
            retrieval_cases=[RetrievalCase("broken update", {"broken-update": 3})],
            confirmed=False,
        )

    assert (root / "wiki/sources.json").read_bytes() == registry_before
    assert not (root / "wiki/concepts/broken-update.md").exists()
    assert not (root / "raw/inbox").exists()


def test_knowledge_update_can_reference_existing_raw_source_without_copying(tmp_path: Path):
    root = _valid_repo(tmp_path)
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]].")
    )

    preview = update_knowledge(
        root,
        source_title="Existing alpha source",
        source_content=None,
        existing_source_path="raw/one.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        confirmed=False,
    )
    result = update_knowledge(
        root,
        source_title="Existing alpha source",
        source_content=None,
        existing_source_path="raw/one.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        confirmed=True,
        approval_digest=preview.approval_digest,
    )

    assert result.source_path == "raw/one.md"
    assert (root / "raw/one.md").read_text(encoding="utf-8") == "alpha source"
    assert check_ingestion(root, base=None).ok


def test_knowledge_update_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _valid_repo(tmp_path)
    source = "Stable source"

    first = _preview_and_apply(root, source)
    raw_source = root / first.source_path
    written: list[Path] = []
    real_atomic_write = ingest._atomic_write

    def record_write(path: Path, content: bytes) -> None:
        written.append(path)
        real_atomic_write(path, content)

    monkeypatch.setattr(ingest, "_atomic_write", record_write)
    second = _preview_and_apply(root, source)

    assert first.source_path == second.source_path
    assert raw_source not in written, "an existing immutable source must not be replaced"
    registry = json.loads((root / "wiki/sources.json").read_text(encoding="utf-8"))
    assert list(registry["sources"]).count(first.source_path) == 1
    cases = json.loads((root / "benchmarks/cold_start_cases.json").read_text(encoding="utf-8"))
    assert sum(case["query"] == "where is the complex nuanced source" for case in cases) == 1
    assert check_ingestion(root, base=None).ok


def test_knowledge_update_rolls_back_if_apply_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _valid_repo(tmp_path)
    before = {
        path: (root / path).read_bytes()
        for path in (
            "wiki/entities/alpha.md",
            "wiki/sources.json",
            "benchmarks/cold_start_cases.json",
            "wiki/index.md",
            "wiki/backlinks.md",
            "wiki/tags.md",
            "internal/registry.md",
        )
    }
    real_atomic_write = ingest._atomic_write
    writes = 0

    def fail_once(path: Path, content: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 3:
            raise OSError("simulated write failure")
        real_atomic_write(path, content)

    preview = _knowledge_update(root, "Rollback source", confirmed=False)
    monkeypatch.setattr(ingest, "_atomic_write", fail_once)

    with pytest.raises(OSError, match="simulated write failure"):
        _knowledge_update(root, "Rollback source", confirmed=True, approval_digest=preview.approval_digest)

    assert not (root / "wiki/concepts/beta.md").exists()
    assert not (root / "raw/inbox").exists()
    assert all((root / path).read_bytes() == content for path, content in before.items())
