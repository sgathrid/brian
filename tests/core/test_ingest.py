from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from wikicli.core import ingest
from wikicli.core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from wikicli.core.ingest import (
    KnowledgeUpdateRequest,
    PageChange,
    RetrievalCase,
    check_ingestion,
    inspect_raw_source,
    list_raw_sources,
    update_knowledge,
)
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


def _run_update(
    root: Path,
    *,
    source_title: str,
    source_content: str | None,
    existing_source_path: str | None,
    source_type: str,
    page_changes: list[PageChange],
    retrieval_cases: list[RetrievalCase],
    apply: bool,
    approval_digest: str | None = None,
):
    request = KnowledgeUpdateRequest(
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=page_changes,
        retrieval_cases=retrieval_cases,
        approval_digest=approval_digest,
    )
    return update_knowledge(root, request, apply=apply)


def test_valid_ingestion_proves_sources_became_connected_knowledge(tmp_path: Path):
    report = check_ingestion(_valid_repo(tmp_path), base=None)

    assert report.ok, report.errors
    assert "2 knowledge pages; 2 registered sources" in report.facts
    assert any("cold-start hit@1 100.0%" in fact for fact in report.facts)


def test_retrieval_gate_accepts_any_highest_grade_target(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases_path = root / "benchmarks/cold_start_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases[1]["relevance"] = {"alpha": 3, "source-synthesis": 3}
    cases_path.write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert report.ok, report.errors
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


def test_source_citation_outside_provenance_does_not_satisfy_mapping(tmp_path: Path):
    root = _valid_repo(tmp_path)
    synthesis = root / "wiki/syntheses/source-synthesis.md"
    content = synthesis.read_text(encoding="utf-8")
    content = content.replace(" and `raw/two.md`", "")
    content = content.replace(
        "## Provenance and status",
        "Evidence path mentioned outside provenance: `raw/two.md`.\n\n## Provenance and status",
    )
    synthesis.write_text(content, encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert "raw/two.md: wiki/syntheses/source-synthesis.md does not cite this source in provenance" in report.errors


def test_every_page_needs_a_novice_language_question(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases = [{"query": "alpha", "relevance": {"alpha": 3}}]
    (root / "benchmarks/cold_start_cases.json").write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert "source-synthesis: no novice-language cold-start question targets this page" in report.errors


@pytest.mark.parametrize("grade", ["3", 0, -1, True, 1.5])
def test_cold_start_rejects_invalid_relevance_grades_before_scoring(tmp_path: Path, grade: object):
    root = _valid_repo(tmp_path)
    cases = [
        {"query": "alpha", "relevance": {"alpha": grade}},
        {"query": "source synthesis", "relevance": {"source-synthesis": 3}},
    ]
    (root / "benchmarks/cold_start_cases.json").write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert any("alpha: relevance grade for alpha must be a positive integer" in error for error in report.errors)
    assert not any(fact.startswith("cold-start ") for fact in report.facts)


def test_nonblocking_retrieval_misses_are_quiet_when_global_floor_passes(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases_path = root / "benchmarks/cold_start_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases.extend({"query": f"alpha company question {index}", "relevance": {"alpha": 3}} for index in range(20))
    cases.append({"query": "office parking badge replacement policy", "relevance": {"alpha": 3}})
    cases_path.write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert report.ok, report.errors
    assert all(item.code != "RETRIEVAL_MISS" for item in report.diagnostics)


def test_retrieval_misses_explain_failed_global_hit_at_three_floor(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases_path = root / "benchmarks/cold_start_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases.extend(
        {"query": f"unrelated parking policy question {index}", "relevance": {"alpha": 3}} for index in range(9)
    )
    cases_path.write_text(json.dumps(cases), encoding="utf-8")

    report = check_ingestion(root, base=None)

    assert not report.ok
    assert any("cold-start hit@3" in error for error in report.errors)
    assert sum(item.code == "RETRIEVAL_MISS" for item in report.diagnostics) == 9


def _knowledge_update(root: Path, source_content: str, apply: bool, approval_digest: str | None = None):
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
    return _run_update(
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
        apply=apply,
        approval_digest=approval_digest,
    )


def _preview_and_apply(root: Path, source_content: str):
    preview = _knowledge_update(root, source_content, apply=False)
    return _knowledge_update(root, source_content, apply=True, approval_digest=preview.approval_digest)


def test_knowledge_update_preview_is_lossless_and_does_not_write(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "# Exact heading\n\nUnicode: naïve → β\n\n```sql\nselect  *  from x;\n```\nNo trailing newline"

    result = _knowledge_update(root, source, apply=False)

    assert result.status == "ready"
    assert not (root / result.source_path).exists()
    assert not (root / "wiki/concepts/beta.md").exists()


def test_knowledge_update_preview_reports_concise_page_deltas(tmp_path: Path):
    root = _valid_repo(tmp_path)

    result = _knowledge_update(root, "Preview delta source", apply=False)

    assert result.created_pages == ["wiki/concepts/beta.md"]
    assert result.updated_pages == ["wiki/entities/alpha.md"]
    assert result.metadata_changes == {}
    assert result.links_added == {
        "wiki/concepts/beta.md": ["Alpha"],
        "wiki/entities/alpha.md": ["Beta"],
    }
    assert result.links_removed == {}


def test_knowledge_update_preview_reports_only_worsened_judged_query_ranks(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases_path = root / "benchmarks/cold_start_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases[0]["query"] = "primary company entity"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("title: Alpha", "title: Primary Company")
        .replace("summary: Primary company entity.", "summary: Organization overview.")
        .replace("# Alpha", "# Primary Company")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Primary Company Entity Guide]].")
    )
    guide = """---
title: Primary Company Entity Guide
type: concept
scope: company
summary: Guide for primary company entity questions.
tags: [company]
aliases: [entity overview]
context_keys: [company entity guide]
updated: 2026-07-30
verified: false
---

# Primary Company Entity Guide

The guide links to [[Primary Company]].

## Provenance and status

Compiled from `{{SOURCE_PATH}}`.
"""

    result = _run_update(
        root,
        source_title="Ranking change",
        source_content="ranking source",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[
            PageChange("wiki/entities/alpha.md", alpha),
            PageChange("wiki/concepts/alpha-guide.md", guide),
        ],
        retrieval_cases=[RetrievalCase("where is the company entity guide", {"alpha-guide": 3})],
        apply=False,
    )

    assert result.status == "ready", result.diagnostics
    assert [item.query for item in result.retrieval_regressions] == ["primary company entity"]
    regression = result.retrieval_regressions[0]
    assert regression.targets == ["alpha"]
    assert regression.before_rank == 1
    assert regression.after_rank == 2
    assert result.metadata_changes["wiki/entities/alpha.md"] == ["summary", "title"]


def test_knowledge_update_requires_the_exact_preview_digest(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "Approval-bound source"
    preview = _knowledge_update(root, source, apply=False)

    with pytest.raises(ValueError, match="approval digest"):
        _knowledge_update(root, source, apply=True)

    changed = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("Primary company entity.", "Primary company entity with a concurrent edit.")
    )
    (root / "wiki/entities/alpha.md").write_text(changed, encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        _knowledge_update(root, source, apply=True, approval_digest=preview.approval_digest)


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

    result = _run_update(
        root,
        source_title="Broken context",
        source_content="Exact source",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/concepts/broken-update.md", "# Missing required structure")],
        retrieval_cases=[RetrievalCase("broken update", {"broken-update": 3})],
        apply=False,
    )

    assert result.status == "needs_revision"
    assert result.diagnostics
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

    preview = _run_update(
        root,
        source_title="Existing alpha source",
        source_content=None,
        existing_source_path="raw/one.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )
    result = _run_update(
        root,
        source_title="Existing alpha source",
        source_content=None,
        existing_source_path="raw/one.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=True,
        approval_digest=preview.approval_digest,
    )

    assert result.source_path == "raw/one.md"
    assert (root / "raw/one.md").read_text(encoding="utf-8") == "alpha source"
    assert check_ingestion(root, base=None).ok


def test_update_reconciles_changed_page_mappings_from_all_provenance_sources(tmp_path: Path):
    root = _valid_repo(tmp_path)
    alpha = (root / "wiki/entities/alpha.md").read_text(encoding="utf-8").replace("raw/one.md", "raw/two.md")

    preview = _run_update(
        root,
        source_title="Second source",
        source_content=None,
        existing_source_path="raw/two.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics

    applied = _run_update(
        root,
        source_title="Second source",
        source_content=None,
        existing_source_path="raw/two.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=True,
        approval_digest=preview.approval_digest,
    )

    assert applied.status == "applied"
    registry = json.loads((root / "wiki/sources.json").read_text(encoding="utf-8"))["sources"]
    assert registry["raw/one.md"]["pages"] == ["wiki/syntheses/source-synthesis.md"]
    assert registry["raw/two.md"]["pages"] == [
        "wiki/entities/alpha.md",
        "wiki/syntheses/source-synthesis.md",
    ]


def test_update_rejects_provenance_citation_to_unknown_source(tmp_path: Path):
    root = _valid_repo(tmp_path)
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("`raw/one.md`", "`raw/one.md` and `raw/missing.md`")
    )

    result = _run_update(
        root,
        source_title="Existing alpha source",
        source_content=None,
        existing_source_path="raw/one.md",
        source_type="existing file",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )

    assert result.status == "needs_revision"
    assert any(
        "raw/missing.md: cited by a page but absent from sources.json" in item.message for item in result.diagnostics
    )


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

    preview = _knowledge_update(root, "Rollback source", apply=False)
    monkeypatch.setattr(ingest, "_atomic_write", fail_once)

    with pytest.raises(OSError, match="simulated write failure"):
        _knowledge_update(root, "Rollback source", apply=True, approval_digest=preview.approval_digest)

    assert not (root / "wiki/concepts/beta.md").exists()
    assert not (root / "raw/inbox").exists()
    assert all((root / path).read_bytes() == content for path, content in before.items())


def test_update_reuses_exact_existing_raw_content(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = (root / "raw/one.md").read_text(encoding="utf-8")
    alpha = (root / "wiki/entities/alpha.md").read_text(encoding="utf-8")

    preview = _run_update(
        root,
        source_title="Alpha source again",
        source_content=source,
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )

    assert preview.status == "ready"
    assert preview.source_path == "raw/one.md"
    assert not (root / "raw/inbox").exists()


def test_exact_source_reuse_and_inspection_hash_original_bytes(tmp_path: Path):
    root = _valid_repo(tmp_path)
    raw_bytes = b"alpha\r\nsource"
    (root / "raw/one.md").write_bytes(raw_bytes)
    alpha = (root / "wiki/entities/alpha.md").read_text(encoding="utf-8")

    preview = _run_update(
        root,
        source_title="Different newline bytes",
        source_content="alpha\nsource",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )

    assert preview.status == "ready"
    assert preview.source_path != "raw/one.md"
    inspected = inspect_raw_source(root, "raw/one.md")
    assert inspected["sha256"] == hashlib.sha256(raw_bytes).hexdigest()


@pytest.mark.parametrize("max_chars", [-1, True])
def test_source_inspection_rejects_invalid_character_limits(tmp_path: Path, max_chars: int):
    root = _valid_repo(tmp_path)

    with pytest.raises(ValueError, match="max_chars must be a non-negative integer"):
        inspect_raw_source(root, "raw/one.md", max_chars=max_chars)


def test_source_inspection_allows_empty_preview(tmp_path: Path):
    root = _valid_repo(tmp_path)

    inspected = inspect_raw_source(root, "raw/one.md", max_chars=0)

    assert inspected["content"] == ""
    assert inspected["truncated"] is True


def test_source_discovery_rejects_invalid_registry(tmp_path: Path):
    root = _valid_repo(tmp_path)
    (root / "wiki/sources.json").write_text('{"version": 2}', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid source registry"):
        list_raw_sources(root)


def test_update_normalizes_path_style_relevance_keys(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "Normalized relevance source"
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Beta]].")
    )
    beta = """---
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

Compiled from `{{SOURCE_PATH}}`.
"""
    preview = _run_update(
        root,
        source_title="Path keys",
        source_content=source,
        existing_source_path=None,
        source_type="conversation",
        page_changes=[
            PageChange("wiki/entities/alpha.md", alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`")),
            PageChange("wiki/concepts/beta.md", beta),
        ],
        retrieval_cases=[
            RetrievalCase("where is the complex nuanced source", {"entities/beta": 3, "wiki://page/concepts/beta": 2})
        ],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics


def test_update_renders_missing_provenance_citation(tmp_path: Path):
    root = _valid_repo(tmp_path)
    source = "Provenance repair source"
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Beta]].")
    )
    beta = """---
title: Beta
type: concept
scope: company
summary: Engine should cite the source path automatically.
tags: [company, nuance]
aliases: [second concept]
context_keys: [complex nuanced source]
updated: 2026-07-26
verified: false
---

# Beta

Beta links to [[Alpha]].

## Provenance and status

Needs a citation from the engine.
"""
    preview = _run_update(
        root,
        source_title="Provenance repair",
        source_content=source,
        existing_source_path=None,
        source_type="conversation",
        page_changes=[
            PageChange("wiki/entities/alpha.md", alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`")),
            PageChange("wiki/concepts/beta.md", beta),
        ],
        retrieval_cases=[RetrievalCase("where is the complex nuanced source", {"beta": 3})],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics
    applied = _run_update(
        root,
        source_title="Provenance repair",
        source_content=source,
        existing_source_path=None,
        source_type="conversation",
        page_changes=[
            PageChange("wiki/entities/alpha.md", alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`")),
            PageChange("wiki/concepts/beta.md", beta),
        ],
        retrieval_cases=[RetrievalCase("where is the complex nuanced source", {"beta": 3})],
        apply=True,
        approval_digest=preview.approval_digest,
    )
    assert applied.status == "applied"
    body = (root / "wiki/concepts/beta.md").read_text(encoding="utf-8")
    assert f"`{applied.source_path}`" in body


def test_update_renders_source_citation_inside_provenance_section(tmp_path: Path):
    root = _valid_repo(tmp_path)
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace(
            "See [[Source Synthesis]].",
            "See [[Source Synthesis]]. Evidence is also mentioned as `{{SOURCE_PATH}}`.",
        )
    )

    preview = _run_update(
        root,
        source_title="Section-scoped provenance",
        source_content="section-scoped evidence",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics

    applied = _run_update(
        root,
        source_title="Section-scoped provenance",
        source_content="section-scoped evidence",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[],
        apply=True,
        approval_digest=preview.approval_digest,
    )
    body = (root / "wiki/entities/alpha.md").read_text(encoding="utf-8")
    provenance = body.split("## Provenance and status", 1)[1]
    assert f"`{applied.source_path}`" in provenance


def test_transaction_retrieval_miss_blocks_even_above_global_floor(tmp_path: Path):
    root = _valid_repo(tmp_path)
    cases_path = root / "benchmarks/cold_start_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases.extend({"query": f"alpha company question {index}", "relevance": {"alpha": 3}} for index in range(20))
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    alpha = (root / "wiki/entities/alpha.md").read_text(encoding="utf-8")

    result = _run_update(
        root,
        source_title="Bad transaction query",
        source_content="transaction retrieval evidence",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/entities/alpha.md", alpha)],
        retrieval_cases=[RetrievalCase("office parking badge replacement policy", {"alpha": 3})],
        apply=False,
    )

    assert result.status == "needs_revision"
    miss = next(item for item in result.diagnostics if item.code == "RETRIEVAL_MISS")
    assert miss.expected == "alpha"
    assert miss.query == "office parking badge replacement policy"
    assert all(item.code != "RETRIEVAL_FLOOR" for item in result.diagnostics)


def test_update_ignores_unrelated_unclassified_raw_as_debt(tmp_path: Path):
    root = _valid_repo(tmp_path)
    (root / "raw/My Org QL EL July 22 2026 (1).md").write_text("unrelated letter", encoding="utf-8")
    source = "Transaction source"
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Beta]].")
    )
    beta = """---
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

Beta links to [[Alpha]].

## Provenance and status

Compiled from `{{SOURCE_PATH}}`.
"""
    preview = _run_update(
        root,
        source_title="Debt tolerant",
        source_content=source,
        existing_source_path=None,
        source_type="conversation",
        page_changes=[
            PageChange("wiki/entities/alpha.md", alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`")),
            PageChange("wiki/concepts/beta.md", beta),
        ],
        retrieval_cases=[RetrievalCase("where is the complex nuanced source", {"beta": 3})],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics
    assert any("repository debt" in item for item in preview.debt)


def test_update_can_incorporate_parenthesized_existing_source(tmp_path: Path):
    root = _valid_repo(tmp_path)
    letter = root / "raw/My Org QL EL July 22 2026 (1).md"
    letter.write_text("QuickLaunch engagement letter body", encoding="utf-8")
    alpha = (
        (root / "wiki/entities/alpha.md")
        .read_text(encoding="utf-8")
        .replace("See [[Source Synthesis]].", "See [[Source Synthesis]] and [[Corporate]].")
    )
    corporate = """---
title: Corporate
type: entity
scope: company
summary: Corporate structure captured from counsel engagement terms.
tags: [company, legal]
aliases: [cap table, QuickLaunch]
context_keys: [founder vesting, fee deferral]
updated: 2026-07-29
verified: false
---

# Corporate

Corporate terms for [[Alpha]].

## Provenance and status

Compiled from `{{SOURCE_PATH}}`.
"""
    preview = _run_update(
        root,
        source_title="WilmerHale letter",
        source_content=None,
        existing_source_path="raw/My Org QL EL July 22 2026 (1).md",
        source_type="engagement letter",
        page_changes=[
            PageChange(
                "wiki/entities/alpha.md",
                alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`"),
            ),
            PageChange("wiki/entities/corporate.md", corporate),
        ],
        retrieval_cases=[RetrievalCase("what is the QuickLaunch fee deferral", {"corporate": 3})],
        apply=False,
    )
    assert preview.status == "ready", preview.diagnostics
    applied = _run_update(
        root,
        source_title="WilmerHale letter",
        source_content=None,
        existing_source_path="raw/My Org QL EL July 22 2026 (1).md",
        source_type="engagement letter",
        page_changes=[
            PageChange(
                "wiki/entities/alpha.md",
                alpha.replace("`raw/one.md`", "`raw/one.md` and `{{SOURCE_PATH}}`"),
            ),
            PageChange("wiki/entities/corporate.md", corporate),
        ],
        retrieval_cases=[RetrievalCase("what is the QuickLaunch fee deferral", {"corporate": 3})],
        apply=True,
        approval_digest=preview.approval_digest,
    )
    assert applied.status == "applied"
    registry = json.loads((root / "wiki/sources.json").read_text(encoding="utf-8"))
    assert "raw/My Org QL EL July 22 2026 (1).md" in registry["sources"]


def test_orphan_update_returns_repairable_diagnostics(tmp_path: Path):
    root = _valid_repo(tmp_path)
    orphan = """---
title: Orphan Concept
type: concept
scope: company
summary: Intentionally disconnected page for diagnostic coverage.
tags: [company]
aliases: [lonely concept]
context_keys: [lonely concept]
updated: 2026-07-29
verified: false
---

# Orphan Concept

No links here.

## Provenance and status

Compiled from `{{SOURCE_PATH}}`.
"""
    result = _run_update(
        root,
        source_title="Orphan",
        source_content="orphan source",
        existing_source_path=None,
        source_type="conversation",
        page_changes=[PageChange("wiki/concepts/orphan-concept.md", orphan)],
        retrieval_cases=[RetrievalCase("lonely concept", {"orphan-concept": 3})],
        apply=False,
    )
    assert result.status == "needs_revision"
    codes = {item.code for item in result.diagnostics}
    assert "ORPHAN_PAGE" in codes or "NO_OUTBOUND_LINKS" in codes
