"""Quality gate for compiling raw sources into a connected knowledge graph."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import audit_wiki
from .generate import generate_backlinks, generate_index, generate_registry, generate_tags
from .page import WikiDatabase, WikiPage
from .resolve import ContextResolver

_CONTENT_FOLDERS = {
    "concepts": {"concept", "reference", "workflow"},
    "entities": {"entity"},
    "projects": {"project"},
    "syntheses": {"synthesis"},
}
_REQUIRED_FIELDS = {"title", "type", "scope", "summary", "tags", "aliases", "context_keys", "updated", "verified"}
_SOURCE_REFERENCE = re.compile(r"`(raw/[^`\n]+)`")
_QUALITY_FLOORS = {"hit@1": 0.65, "hit@3": 0.90, "no_result_accuracy": 0.50}


@dataclass
class IngestionReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PageChange:
    """Complete content for one curated page to create or replace."""

    path: str
    content: str


@dataclass(frozen=True)
class RetrievalCase:
    """A newcomer query and graded page-stem relevance mapping."""

    query: str
    relevance: dict[str, int]


@dataclass(frozen=True)
class KnowledgeUpdateResult:
    """Validated outcome of a previewed or applied knowledge update."""

    status: str
    source_path: str
    pages: list[str]
    facts: list[str]
    approval_digest: str


def update_knowledge(
    repo_root: Path,
    *,
    source_title: str,
    source_content: str | None,
    existing_source_path: str | None,
    source_type: str,
    page_changes: list[PageChange],
    retrieval_cases: list[RetrievalCase],
    confirmed: bool,
    approval_digest: str | None = None,
) -> KnowledgeUpdateResult:
    """Validate a source-backed graph update, then apply it atomically when confirmed.

    New ``source_content`` is written verbatim under ``raw/inbox``. Alternatively, an existing
    immutable ``raw/...`` file can be referenced without copying it. Page content may use
    ``{{SOURCE_PATH}}`` so an agent can propose a complete update before the source path is known.
    Applying requires the digest returned by a preview of the same request and repository state.
    """
    repo_root = repo_root.resolve()
    if not source_title.strip():
        raise ValueError("source_title must be non-empty")
    if bool(source_content) == bool(existing_source_path):
        raise ValueError("provide exactly one of source_content or existing_source_path")
    if not page_changes:
        raise ValueError("at least one page change is required")

    if source_content is not None:
        captured_source = True
        source_slug = _filename_slug(source_title)
        source_kind = _filename_slug(source_type) or "context"
        digest = hashlib.sha256(source_content.encode("utf-8")).hexdigest()[:12]
        source_path = f"raw/inbox/{source_kind}-{source_slug}-{digest}.txt"
    else:
        captured_source = False
        source_path = _validate_existing_source(repo_root, existing_source_path or "")
    normalized_pages = _validate_page_changes(page_changes)
    normalized_cases = _validate_retrieval_cases(retrieval_cases)
    expected_approval = _approval_digest(
        repo_root,
        source_title=source_title,
        source_content=source_content,
        existing_source_path=source_path if not captured_source else None,
        source_type=source_type,
        page_changes=normalized_pages,
        retrieval_cases=normalized_cases,
    )
    if confirmed and approval_digest != expected_approval:
        detail = "missing" if approval_digest is None else "stale or does not match this payload"
        raise ValueError(f"approval digest is {detail}; preview this exact update again")

    with tempfile.TemporaryDirectory(prefix="brian-wiki-ingest-") as tmp:
        candidate = Path(tmp)
        for directory in ("wiki", "internal", "benchmarks", "raw"):
            source_dir = repo_root / directory
            if source_dir.is_dir():
                shutil.copytree(source_dir, candidate / directory)

        if captured_source:
            raw_file = candidate / source_path
            raw_file.parent.mkdir(parents=True, exist_ok=True)
            if raw_file.exists() and raw_file.read_text(encoding="utf-8") != source_content:
                raise ValueError(f"source collision at {source_path}")
            raw_file.write_text(source_content or "", encoding="utf-8")

        rendered_pages: list[str] = []
        for change in normalized_pages:
            page_file = candidate / change.path
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(change.content.replace("{{SOURCE_PATH}}", source_path), encoding="utf-8")
            rendered_pages.append(change.path)

        registry_path = candidate / "wiki/sources.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        sources = registry.get("sources")
        if registry.get("version") != 1 or not isinstance(sources, dict):
            raise ValueError("wiki/sources.json must contain version 1 and a sources object")
        prior_pages = sources.get(source_path, {}).get("pages", [])
        mapped_pages = sorted({*prior_pages, *rendered_pages}) if isinstance(prior_pages, list) else rendered_pages
        sources[source_path] = {
            "status": "incorporated",
            "pages": mapped_pages,
            "note": f"{source_type.strip() or 'context'} source: {source_title.strip()}",
        }
        registry_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        cases_path = candidate / "benchmarks/cold_start_cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("cold_start_cases.json must contain an array")  # noqa: TRY004
        by_query = {case.get("query"): case for case in cases if isinstance(case, dict)}
        for case in normalized_cases:
            by_query[case.query] = {"query": case.query, "relevance": case.relevance}
        merged_cases = list(by_query.values())
        cases_path.write_text(_format_cases(merged_cases), encoding="utf-8")

        db = WikiDatabase(candidate / "wiki")
        generate_index(db, candidate / "wiki")
        generate_backlinks(db, candidate / "wiki")
        generate_tags(db, candidate / "wiki")
        generate_registry(candidate)
        report = check_ingestion(candidate, base=None)
        if not report.ok:
            raise ValueError("knowledge update failed validation:\n" + "\n".join(report.errors))

        if not confirmed:
            return KnowledgeUpdateResult("ready", source_path, rendered_pages, report.facts, expected_approval)

        current_approval = _approval_digest(
            repo_root,
            source_title=source_title,
            source_content=source_content,
            existing_source_path=source_path if not captured_source else None,
            source_type=source_type,
            page_changes=normalized_pages,
            retrieval_cases=normalized_cases,
        )
        if current_approval != expected_approval:
            raise ValueError("approval digest is stale because the knowledge repository changed during validation")

        targets = [
            *([source_path] if captured_source and not (repo_root / source_path).exists() else []),
            *rendered_pages,
            "wiki/sources.json",
            "benchmarks/cold_start_cases.json",
            "wiki/index.md",
            "wiki/backlinks.md",
            "wiki/tags.md",
            "internal/registry.md",
        ]
        snapshots = {rel: (repo_root / rel).read_bytes() if (repo_root / rel).is_file() else None for rel in targets}
        try:
            for rel in targets:
                _atomic_write(repo_root / rel, (candidate / rel).read_bytes())
            applied_report = check_ingestion(repo_root, base=None)
            if not applied_report.ok:
                raise ValueError("applied knowledge update failed validation:\n" + "\n".join(applied_report.errors))
        except Exception:  # Every failed transaction must roll back before re-raising.
            for rel, previous in snapshots.items():
                destination = repo_root / rel
                if previous is None:
                    destination.unlink(missing_ok=True)
                    try:
                        destination.parent.rmdir()
                    except OSError:
                        pass
                else:
                    _atomic_write(destination, previous)
            raise

    return KnowledgeUpdateResult("applied", source_path, rendered_pages, applied_report.facts, expected_approval)


def _approval_digest(
    repo_root: Path,
    *,
    source_title: str,
    source_content: str | None,
    existing_source_path: str | None,
    source_type: str,
    page_changes: list[PageChange],
    retrieval_cases: list[RetrievalCase],
) -> str:
    """Bind approval to the normalized request and the governed repository state."""
    state = hashlib.sha256()
    governed = [path for path in (repo_root / "wiki").rglob("*") if path.is_file()]
    governed.extend(
        path
        for path in (repo_root / "benchmarks/cold_start_cases.json", repo_root / "internal/registry.md")
        if path.is_file()
    )
    raw_root = repo_root / "raw"
    raw_paths = sorted(path.relative_to(repo_root).as_posix() for path in raw_root.rglob("*") if path.is_file())
    for path in sorted(governed):
        state.update(path.relative_to(repo_root).as_posix().encode("utf-8"))
        state.update(b"\0")
        state.update(path.read_bytes())
        state.update(b"\0")
    state.update(json.dumps(raw_paths, separators=(",", ":")).encode("utf-8"))
    if existing_source_path:
        state.update((repo_root / existing_source_path).read_bytes())

    request = {
        "source_title": source_title.strip(),
        "source_content": source_content,
        "existing_source_path": existing_source_path,
        "source_type": source_type.strip() or "context",
        "page_changes": [{"path": change.path, "content": change.content} for change in page_changes],
        "retrieval_cases": [
            {"query": case.query, "relevance": dict(sorted(case.relevance.items()))} for case in retrieval_cases
        ],
        "state": state.hexdigest(),
    }
    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _filename_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:60]


def _validate_existing_source(repo_root: Path, source_path: str) -> str:
    raw_root = (repo_root / "raw").resolve()
    candidate = (repo_root / source_path).resolve()
    if not source_path.startswith("raw/") or not candidate.is_relative_to(raw_root) or not candidate.is_file():
        raise ValueError(f"existing source must be a file under raw/: {source_path}")
    try:
        candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"existing source must be UTF-8 text: {source_path}") from exc
    return candidate.relative_to(repo_root).as_posix()


def _validate_page_changes(page_changes: list[PageChange]) -> list[PageChange]:
    normalized: list[PageChange] = []
    seen: set[str] = set()
    for change in page_changes:
        path = Path(change.path)
        rel = path.as_posix()
        if (
            path.is_absolute()
            or len(path.parts) != 3
            or path.parts[0] != "wiki"
            or path.parts[1] not in _CONTENT_FOLDERS
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", path.name)
        ):
            raise ValueError(f"invalid knowledge page path: {change.path}")
        if rel in seen:
            raise ValueError(f"duplicate knowledge page path: {rel}")
        if not change.content.strip():
            raise ValueError(f"knowledge page content is empty: {rel}")
        seen.add(rel)
        normalized.append(PageChange(rel, change.content))
    return normalized


def _validate_retrieval_cases(retrieval_cases: list[RetrievalCase]) -> list[RetrievalCase]:
    normalized: list[RetrievalCase] = []
    for case in retrieval_cases:
        if not case.query.strip() or not case.relevance:
            raise ValueError("retrieval cases require a query and at least one relevant page")
        if any(not stem or not isinstance(grade, int) or grade < 1 for stem, grade in case.relevance.items()):
            raise ValueError(f"invalid retrieval relevance for query: {case.query}")
        normalized.append(RetrievalCase(case.query.strip(), dict(case.relevance)))
    return normalized


def _format_cases(cases: list[dict[str, Any]]) -> str:
    return "[\n" + ",\n".join(f"  {json.dumps(case, ensure_ascii=False)}" for case in cases) + "\n]\n"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        Path(temp_name).replace(path)
    except OSError:
        Path(temp_name).unlink(missing_ok=True)
        raise


def check_ingestion(
    repo_root: Path,
    *,
    base: str | None = "HEAD",
    allow_deletions: bool = False,
) -> IngestionReport:
    """Validate the current wiki as constructed knowledge, not formatted source copies."""
    repo_root = repo_root.resolve()
    wiki_dir = repo_root / "wiki"
    report = IngestionReport()
    db = WikiDatabase(wiki_dir)
    pages = list(db.pages.values())

    _check_git_changes(repo_root, base, allow_deletions, report)
    registry = _load_source_registry(wiki_dir / "sources.json", report)
    _check_pages(repo_root, db, pages, registry, report)
    _check_sources(repo_root, pages, registry, report)
    _check_graph(db, pages, report)
    _check_questions(repo_root, db, pages, report)
    _check_generated_files(repo_root, report)

    report.facts.insert(0, f"{len(pages)} knowledge pages; {len(registry)} registered sources")
    return report


def _load_source_registry(path: Path, report: IngestionReport) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"cannot read {path.name}: {exc}")
        return {}
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("sources"), dict):
        report.errors.append("sources.json must contain version 1 and a sources object")
        return {}
    sources = payload["sources"]
    return {str(name): entry for name, entry in sources.items() if isinstance(entry, dict)}


def _check_git_changes(repo_root: Path, base: str | None, allow_deletions: bool, report: IngestionReport) -> None:
    if not base:
        return
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-status", base, "--", "wiki"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        report.errors.append(f"cannot compare ingestion with {base}: {result.stderr.strip()}")
        return
    changed = [line for line in result.stdout.splitlines() if line]
    deleted = [line.split("\t", 1)[-1] for line in changed if line.startswith("D\t")]
    if deleted and not allow_deletions:
        report.errors.append(
            f"{len(deleted)} knowledge pages deleted since {base}; review and rerun with --allow-deletions"
        )
    report.facts.append(f"{len(changed)} tracked wiki changes relative to {base}")


def _check_pages(
    repo_root: Path,
    db: WikiDatabase,
    pages: list[WikiPage],
    registry: dict[str, dict[str, Any]],
    report: IngestionReport,
) -> None:
    mapped_pages = {
        page_path for entry in registry.values() for page_path in entry.get("pages", []) if isinstance(page_path, str)
    }
    for page in pages:
        rel = page.filepath.relative_to(repo_root).as_posix()
        missing = sorted(field for field in _REQUIRED_FIELDS if not page.frontmatter.get(field))
        if missing:
            report.errors.append(f"{rel}: missing construction field(s): {', '.join(missing)}")
        for metadata_field in ("tags", "aliases", "context_keys"):
            if not isinstance(page.frontmatter.get(metadata_field), list):
                report.errors.append(f"{rel}: {metadata_field} must be a non-empty list")
        folder = page.filepath.parent.name
        page_type = page.frontmatter.get("type")
        if folder not in _CONTENT_FOLDERS or page_type not in _CONTENT_FOLDERS.get(folder, set()):
            report.errors.append(f"{rel}: type {page_type!r} does not belong in wiki/{folder}/")
        if "## Provenance and status" not in page.body:
            report.errors.append(f"{rel}: missing '## Provenance and status' section")
        if rel not in mapped_pages:
            report.errors.append(f"{rel}: not mapped from any source in sources.json")

    ok, audit_lines = audit_wiki(db)
    if not ok:
        report.errors.extend(line for line in audit_lines if line.startswith("✕"))


def _check_sources(
    repo_root: Path,
    pages: list[WikiPage],
    registry: dict[str, dict[str, Any]],
    report: IngestionReport,
) -> None:
    raw_dir = repo_root / "raw"
    on_disk = {
        path.relative_to(repo_root).as_posix()
        for path in raw_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }
    registered = set(registry)
    if on_disk:
        for source in sorted(on_disk - registered):
            report.errors.append(f"{source}: raw source is not classified in sources.json")
        for source in sorted(registered - on_disk):
            report.errors.append(f"{source}: registered source does not exist locally")
    else:
        report.warnings.append("raw/ is empty or unavailable; physical source coverage was not checked")

    page_by_path = {page.filepath.relative_to(repo_root).as_posix(): page for page in pages}
    referenced_sources: set[str] = set()
    multi_source_synthesis = False
    for rel, page in page_by_path.items():
        references = set(_SOURCE_REFERENCE.findall(page.body))
        referenced_sources.update(references)
        if page.frontmatter.get("type") == "synthesis" and len(references) >= 2:
            multi_source_synthesis = True
        if not references:
            report.errors.append(f"{rel}: provenance section cites no `raw/...` source")

    incorporated = 0
    for source, entry in registry.items():
        status = entry.get("status")
        mapped = entry.get("pages")
        note = entry.get("note")
        if status not in {"incorporated", "deferred", "rejected"}:
            report.errors.append(f"{source}: status must be incorporated, deferred, or rejected")
            continue
        if not isinstance(note, str) or not note.strip():
            report.errors.append(f"{source}: note must explain the source disposition")
        if not isinstance(mapped, list) or any(not isinstance(item, str) for item in mapped):
            report.errors.append(f"{source}: pages must be a list of wiki paths")
            continue
        if status == "incorporated":
            incorporated += 1
            if not mapped:
                report.errors.append(f"{source}: incorporated source maps to no knowledge pages")
            for rel in mapped:
                mapped_page = page_by_path.get(rel)
                if mapped_page is None:
                    report.errors.append(f"{source}: mapped page does not exist: {rel}")
                elif source not in _SOURCE_REFERENCE.findall(mapped_page.body):
                    report.errors.append(f"{source}: {rel} does not cite this source in provenance")
        elif mapped:
            report.errors.append(f"{source}: {status} sources must not map to knowledge pages")

    for source in sorted(referenced_sources - registered):
        report.errors.append(f"{source}: cited by a page but absent from sources.json")
    if incorporated > 1 and not multi_source_synthesis:
        report.errors.append("no synthesis page combines evidence from multiple sources")
    report.facts.append(f"{incorporated} sources incorporated; {len(referenced_sources)} cited")


def _check_graph(db: WikiDatabase, pages: list[WikiPage], report: IngestionReport) -> None:
    incoming = {page.filepath: 0 for page in pages}
    for page in pages:
        outgoing = {
            target.filepath
            for link in page.wikilinks
            if (target := db.resolve_link(link)) is not None and target.filepath != page.filepath
        }
        if len(pages) > 1 and not outgoing:
            report.errors.append(f"{page.filepath.name}: no outbound links to other knowledge pages")
        for target_path in outgoing:
            incoming[target_path] += 1
    for path, count in incoming.items():
        if len(pages) > 1 and not count:
            report.errors.append(f"{path.name}: orphaned; no other knowledge page links to it")
    report.facts.append(f"{sum(incoming.values())} resolved relationships")


def _check_questions(repo_root: Path, db: WikiDatabase, pages: list[WikiPage], report: IngestionReport) -> None:
    path = repo_root / "benchmarks" / "cold_start_cases.json"
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"cannot read cold-start questions: {exc}")
        return
    if not isinstance(cases, list) or not cases:
        report.errors.append("cold_start_cases.json must contain at least one question")
        return

    resolver = ContextResolver(db)
    covered: set[str] = set()
    hit_at_one: list[bool] = []
    hit_at_three: list[bool] = []
    no_result: list[bool] = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("query"), str)
            or not isinstance(case.get("relevance"), dict)
        ):
            report.errors.append("every cold-start case needs a query string and relevance object")
            return
        relevance = case["relevance"]
        covered.update(str(stem) for stem in relevance)
        results = [page.stem for page in resolver.find_keywords(case["query"], limit=5)]
        if relevance:
            target = max(relevance, key=relevance.__getitem__)
            hit_at_one.append(results[:1] == [target])
            hit_at_three.append(target in results[:3])
        else:
            no_result.append(not results)

    stems = {page.stem for page in pages}
    for stem in sorted(stems - covered):
        report.errors.append(f"{stem}: no novice-language cold-start question targets this page")
    for stem in sorted(covered - stems):
        report.errors.append(f"cold-start questions target missing page: {stem}")

    metrics = {
        "hit@1": sum(hit_at_one) / len(hit_at_one) if hit_at_one else 0.0,
        "hit@3": sum(hit_at_three) / len(hit_at_three) if hit_at_three else 0.0,
        "no_result_accuracy": sum(no_result) / len(no_result) if no_result else 1.0,
    }
    for name, floor in _QUALITY_FLOORS.items():
        if metrics[name] < floor:
            report.errors.append(f"cold-start {name} {metrics[name]:.1%} is below the {floor:.0%} floor")
    report.facts.append("cold-start " + ", ".join(f"{name} {value:.1%}" for name, value in metrics.items()))


def _check_generated_files(repo_root: Path, report: IngestionReport) -> None:
    expected = ("wiki/index.md", "wiki/backlinks.md", "wiki/tags.md", "internal/registry.md")
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp)
        shutil.copytree(repo_root / "wiki", candidate / "wiki")
        shutil.copytree(repo_root / "internal", candidate / "internal")
        db = WikiDatabase(candidate / "wiki")
        generate_index(db, candidate / "wiki")
        generate_backlinks(db, candidate / "wiki")
        generate_tags(db, candidate / "wiki")
        generate_registry(candidate)
        stale = [rel for rel in expected if (repo_root / rel).read_bytes() != (candidate / rel).read_bytes()]
    if stale:
        report.errors.append(f"generated files are stale: {', '.join(stale)}; run `wiki gen`")
