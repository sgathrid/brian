"""Quality gate for compiling raw sources into a connected knowledge graph."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

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
_PROVENANCE_HEADING = "## Provenance and status"
_SOURCE_PLACEHOLDER = "{{SOURCE_PATH}}"


@dataclass(frozen=True)
class KnowledgeDiagnostic:
    """Structured, repairable validation finding for agents and CLIs."""

    code: str
    message: str
    path: str | None = None
    query: str | None = None
    expected: str | None = None
    observed: list[str] = field(default_factory=list)
    fix: str | None = None


@dataclass
class IngestionReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    diagnostics: list[KnowledgeDiagnostic] = field(default_factory=list)

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
class RetrievalRegression:
    """A judged query whose best acceptable target moved down in search results."""

    query: str
    targets: list[str]
    before_rank: int
    after_rank: int | None


@dataclass(frozen=True)
class KnowledgeUpdateRequest:
    """Canonical source-backed knowledge update request shared by CLI and MCP."""

    source_title: str
    page_changes: list[PageChange]
    retrieval_cases: list[RetrievalCase]
    source_content: str | None = None
    existing_source_path: str | None = None
    source_type: str = "user-confirmed context"
    approval_digest: str | None = None


@dataclass(frozen=True)
class KnowledgeUpdateResult:
    """Validated outcome of a previewed, revised, or applied knowledge update."""

    status: Literal["needs_revision", "ready", "applied"]
    source_path: str
    pages: list[str]
    facts: list[str]
    approval_digest: str
    diagnostics: list[KnowledgeDiagnostic] = field(default_factory=list)
    debt: list[str] = field(default_factory=list)
    created_pages: list[str] = field(default_factory=list)
    updated_pages: list[str] = field(default_factory=list)
    metadata_changes: dict[str, list[str]] = field(default_factory=dict)
    links_added: dict[str, list[str]] = field(default_factory=dict)
    links_removed: dict[str, list[str]] = field(default_factory=dict)
    retrieval_regressions: list[RetrievalRegression] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def knowledge_update_request_from_dict(
    payload: dict[str, Any], *, approval_digest: str | None = None
) -> KnowledgeUpdateRequest:
    """Parse the canonical update request used by structured transports."""
    allowed = {
        "source_title",
        "source_content",
        "existing_source_path",
        "source_type",
        "page_changes",
        "retrieval_cases",
        "approval_digest",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown update field(s): {', '.join(unknown)}")
    try:
        raw_pages = payload["page_changes"]
        raw_cases = payload["retrieval_cases"]
        source_title = payload["source_title"]
    except KeyError as exc:
        raise ValueError(f"invalid update payload: missing {exc.args[0]}") from exc
    if not isinstance(source_title, str):
        raise TypeError("source_title must be a string")
    if not isinstance(raw_pages, list) or not all(
        isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("content"), str)
        for item in raw_pages
    ):
        raise TypeError("page_changes must contain objects with string path and content fields")
    if not isinstance(raw_cases, list) or not all(
        isinstance(item, dict) and isinstance(item.get("query"), str) and isinstance(item.get("relevance"), dict)
        for item in raw_cases
    ):
        raise TypeError("retrieval_cases must contain objects with query and relevance fields")
    source_content = payload.get("source_content")
    existing_source_path = payload.get("existing_source_path")
    source_type = payload.get("source_type", "user-confirmed context")
    payload_approval = payload.get("approval_digest")
    if source_content is not None and not isinstance(source_content, str):
        raise TypeError("source_content must be a string or null")
    if existing_source_path is not None and not isinstance(existing_source_path, str):
        raise TypeError("existing_source_path must be a string or null")
    if not isinstance(source_type, str):
        raise TypeError("source_type must be a string")
    if payload_approval is not None and not isinstance(payload_approval, str):
        raise TypeError("approval_digest must be a string or null")
    if approval_digest and payload_approval and approval_digest != payload_approval:
        raise ValueError("approval digest in --approve does not match approval_digest in the payload")
    return KnowledgeUpdateRequest(
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=[PageChange(path=item["path"], content=item["content"]) for item in raw_pages],
        retrieval_cases=[RetrievalCase(query=item["query"], relevance=item["relevance"]) for item in raw_cases],
        approval_digest=approval_digest or payload_approval,
    )


def update_knowledge(
    repo_root: Path,
    request: KnowledgeUpdateRequest,
    *,
    apply: bool | None = None,
) -> KnowledgeUpdateResult:
    """Validate a source-backed graph update, then atomically apply an approved request.

    A request without an approval digest is previewed. Applying requires the digest returned by a
    ready preview of the same request and governed repository state. Valid-but-failing proposals
    return ``status="needs_revision"``; schema-invalid requests raise ``ValueError``.
    """
    repo_root = repo_root.resolve()
    source_title = request.source_title
    source_content = request.source_content
    existing_source_path = request.existing_source_path
    source_type = request.source_type
    approval_digest = request.approval_digest
    should_apply = approval_digest is not None if apply is None else apply

    if not source_title.strip():
        raise ValueError("source_title must be non-empty")
    if bool(source_content) == bool(existing_source_path):
        raise ValueError("provide exactly one of source_content or existing_source_path")
    if not request.page_changes:
        raise ValueError("at least one page change is required")

    captured_source = False
    if source_content is not None:
        exact = find_exact_raw_source(repo_root, source_content)
        if exact is not None:
            source_path = exact
        else:
            captured_source = True
            source_slug = _filename_slug(source_title)
            source_kind = _filename_slug(source_type) or "context"
            digest = hashlib.sha256(source_content.encode("utf-8")).hexdigest()[:12]
            source_path = f"raw/inbox/{source_kind}-{source_slug}-{digest}.txt"
    else:
        source_path = _validate_existing_source(repo_root, existing_source_path or "")

    normalized_pages = _validate_page_changes(request.page_changes)
    normalized_cases = _validate_retrieval_cases(request.retrieval_cases)
    expected_approval = _approval_digest(
        repo_root,
        source_title=source_title,
        source_content=source_content if captured_source else None,
        existing_source_path=source_path if not captured_source else None,
        source_type=source_type,
        page_changes=normalized_pages,
        retrieval_cases=normalized_cases,
    )
    if should_apply and approval_digest != expected_approval:
        detail = "missing" if approval_digest is None else "stale or does not match this payload"
        raise ValueError(f"approval digest is {detail}; preview this exact update again")

    with tempfile.TemporaryDirectory(prefix="wiki-ingest-") as tmp:
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
            content = _render_page_content(change.content, source_path)
            page_file.write_text(content, encoding="utf-8")
            rendered_pages.append(change.path)

        created_pages, updated_pages, metadata_changes, links_added, links_removed = _page_deltas(
            repo_root, candidate, rendered_pages
        )

        registry_path = candidate / "wiki/sources.json"
        if registry_path.is_file():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        else:
            registry = {"version": 1, "sources": {}}
        sources = registry.get("sources")
        if registry.get("version") != 1 or not isinstance(sources, dict):
            raise ValueError("wiki/sources.json must contain version 1 and a sources object")
        existing_source = sources.get(source_path, {})
        prior_pages = existing_source.get("pages", []) if isinstance(existing_source, dict) else []
        sources[source_path] = {
            "status": "incorporated",
            "pages": prior_pages if isinstance(prior_pages, list) else [],
            "note": f"{source_type.strip() or 'context'} source: {source_title.strip()}",
        }
        _reconcile_source_mappings(candidate, sources, rendered_pages)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        cases_path = candidate / "benchmarks/cold_start_cases.json"
        if cases_path.is_file():
            cases = json.loads(cases_path.read_text(encoding="utf-8"))
        else:
            cases = []
        if not isinstance(cases, list):
            raise ValueError("cold_start_cases.json must contain an array")  # noqa: TRY004
        by_query = {case.get("query"): case for case in cases if isinstance(case, dict)}
        for case in normalized_cases:
            by_query[case.query] = {"query": case.query, "relevance": case.relevance}
        merged_cases = list(by_query.values())
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        cases_path.write_text(_format_cases(merged_cases), encoding="utf-8")

        retrieval_regressions = _retrieval_regressions(repo_root, candidate)

        db = WikiDatabase(candidate / "wiki")
        generate_index(db, candidate / "wiki")
        generate_backlinks(db, candidate / "wiki")
        generate_tags(db, candidate / "wiki")
        generate_registry(candidate)
        report = check_ingestion(
            candidate,
            base=None,
            ignore_unrelated_unclassified_raw=True,
            transaction_sources={source_path},
            transaction_retrieval_queries={case.query for case in normalized_cases},
        )
        debt = [warning for warning in report.warnings if "repository debt" in warning or "unclassified raw" in warning]
        if not report.ok:
            return KnowledgeUpdateResult(
                status="needs_revision",
                source_path=source_path,
                pages=rendered_pages,
                facts=list(report.facts),
                approval_digest="",
                diagnostics=_diagnostics_from_report(report),
                debt=debt,
                created_pages=created_pages,
                updated_pages=updated_pages,
                metadata_changes=metadata_changes,
                links_added=links_added,
                links_removed=links_removed,
                retrieval_regressions=retrieval_regressions,
            )

        if not should_apply:
            return KnowledgeUpdateResult(
                status="ready",
                source_path=source_path,
                pages=rendered_pages,
                facts=list(report.facts),
                approval_digest=expected_approval,
                diagnostics=[],
                debt=debt,
                created_pages=created_pages,
                updated_pages=updated_pages,
                metadata_changes=metadata_changes,
                links_added=links_added,
                links_removed=links_removed,
                retrieval_regressions=retrieval_regressions,
            )

        current_approval = _approval_digest(
            repo_root,
            source_title=source_title,
            source_content=source_content if captured_source else None,
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
            applied_report = check_ingestion(
                repo_root,
                base=None,
                ignore_unrelated_unclassified_raw=True,
                transaction_sources={source_path},
                transaction_retrieval_queries={case.query for case in normalized_cases},
            )
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

    return KnowledgeUpdateResult(
        status="applied",
        source_path=source_path,
        pages=rendered_pages,
        facts=list(applied_report.facts),
        approval_digest=expected_approval,
        diagnostics=[],
        debt=[w for w in applied_report.warnings if "repository debt" in w or "unclassified raw" in w],
        created_pages=created_pages,
        updated_pages=updated_pages,
        metadata_changes=metadata_changes,
        links_added=links_added,
        links_removed=links_removed,
        retrieval_regressions=retrieval_regressions,
    )


def find_exact_raw_source(repo_root: Path, source_content: str) -> str | None:
    """Return an existing raw path whose bytes exactly match UTF-8 ``source_content``."""
    raw_root = repo_root / "raw"
    if not raw_root.is_dir():
        return None
    expected = source_content.encode("utf-8")
    for path in sorted(raw_root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if content == expected:
            return path.relative_to(repo_root).as_posix()
    return None


def _load_source_registry_strict(repo_root: Path) -> dict[str, dict[str, Any]]:
    report = IngestionReport()
    registry = _load_source_registry(repo_root / "wiki/sources.json", report)
    if report.errors:
        raise ValueError("invalid source registry: " + "; ".join(report.errors))
    return registry


def list_raw_sources(repo_root: Path) -> list[dict[str, Any]]:
    """List classified and unclassified raw sources for curation discovery."""
    repo_root = repo_root.resolve()
    registry = _load_source_registry_strict(repo_root)
    raw_root = repo_root / "raw"
    rows: list[dict[str, Any]] = []
    if raw_root.is_dir():
        on_disk = sorted(
            path.relative_to(repo_root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        )
    else:
        on_disk = []
    seen: set[str] = set()
    for path in on_disk:
        seen.add(path)
        entry = registry.get(path, {})
        rows.append(
            {
                "path": path,
                "status": entry.get("status", "unclassified"),
                "pages": list(entry.get("pages", [])) if isinstance(entry.get("pages"), list) else [],
                "note": entry.get("note", ""),
                "exists": True,
            }
        )
    for path, entry in sorted(registry.items()):
        if path in seen:
            continue
        rows.append(
            {
                "path": path,
                "status": entry.get("status", "missing"),
                "pages": list(entry.get("pages", [])) if isinstance(entry.get("pages"), list) else [],
                "note": entry.get("note", ""),
                "exists": False,
            }
        )
    return rows


def inspect_raw_source(repo_root: Path, source_path: str, *, max_chars: int = 20000) -> dict[str, Any]:
    """Read one raw source as evidence for curation. Not curated truth."""
    if type(max_chars) is not int or max_chars < 0:
        raise ValueError("max_chars must be a non-negative integer")
    repo_root = repo_root.resolve()
    rel = _validate_existing_source(repo_root, source_path)
    raw_bytes = (repo_root / rel).read_bytes()
    text = raw_bytes.decode("utf-8")
    registry = _load_source_registry_strict(repo_root)
    entry = registry.get(rel, {})
    truncated = len(text) > max_chars
    return {
        "path": rel,
        "status": entry.get("status", "unclassified"),
        "pages": list(entry.get("pages", [])) if isinstance(entry.get("pages"), list) else [],
        "note": entry.get("note", ""),
        "content": text[:max_chars],
        "truncated": truncated,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "label": "raw evidence — not curated company knowledge",
    }


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


def _normalize_relevance_key(key: str) -> str:
    """Accept stems, wiki paths, or wiki:// URIs; store canonical page stems."""
    value = key.strip()
    if value.startswith("wiki://page/"):
        value = value.removeprefix("wiki://page/")
    if value.startswith("wiki/"):
        value = value.removeprefix("wiki/")
    value = value.removesuffix(".md")
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError(f"invalid retrieval relevance key: {key}")
    return value


def _validate_retrieval_cases(retrieval_cases: list[RetrievalCase]) -> list[RetrievalCase]:
    normalized: list[RetrievalCase] = []
    for case in retrieval_cases:
        if not case.query.strip() or not case.relevance:
            raise ValueError("retrieval cases require a query and at least one relevant page")
        relevance: dict[str, int] = {}
        for stem, grade in case.relevance.items():
            if type(grade) is not int or grade < 1:
                raise ValueError(f"invalid retrieval relevance for query: {case.query}")
            normalized_stem = _normalize_relevance_key(str(stem))
            relevance[normalized_stem] = max(relevance.get(normalized_stem, 0), grade)
        normalized.append(RetrievalCase(case.query.strip(), relevance))
    return normalized


def _provenance_section(content: str) -> tuple[int, int] | None:
    heading = re.search(rf"(?m)^{re.escape(_PROVENANCE_HEADING)}\s*$", content)
    if heading is None:
        return None
    next_heading = re.search(r"(?m)^##\s+", content[heading.end() :])
    end = heading.end() + next_heading.start() if next_heading else len(content)
    return heading.end(), end


def _provenance_references(content: str) -> set[str]:
    bounds = _provenance_section(content)
    if bounds is None:
        return set()
    start, end = bounds
    return set(_SOURCE_REFERENCE.findall(content[start:end]))


def _render_page_content(content: str, source_path: str) -> str:
    """Substitute the source path and ensure its citation is in provenance."""
    rendered = content.replace(_SOURCE_PLACEHOLDER, source_path)
    citation = f"`{source_path}`"
    bounds = _provenance_section(rendered)
    if bounds is None:
        return rendered.rstrip() + f"\n\n{_PROVENANCE_HEADING}\n\nCompiled from {citation}.\n"
    start, end = bounds
    if source_path in _provenance_references(rendered):
        return rendered
    section = rendered[start:end].rstrip() + f"\n\nCompiled from {citation}.\n"
    return rendered[:start] + section + rendered[end:]


def _page_deltas(
    repo_root: Path, candidate: Path, page_paths: list[str]
) -> tuple[list[str], list[str], dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Return concise, deterministic changes for the pages in one update."""
    created: list[str] = []
    updated: list[str] = []
    metadata: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for rel in page_paths:
        current_path = repo_root / rel
        candidate_path = candidate / rel
        new_page = WikiPage(candidate_path)
        new_links = set(new_page.wikilinks)
        if not current_path.is_file():
            created.append(rel)
            if new_links:
                added[rel] = sorted(new_links, key=str.casefold)
            continue
        if current_path.read_bytes() == candidate_path.read_bytes():
            continue
        updated.append(rel)
        old_page = WikiPage(current_path)
        changed_fields = sorted(
            key
            for key in old_page.frontmatter.keys() | new_page.frontmatter.keys()
            if old_page.frontmatter.get(key) != new_page.frontmatter.get(key)
        )
        if changed_fields:
            metadata[rel] = changed_fields
        old_links = set(old_page.wikilinks)
        if new_links - old_links:
            added[rel] = sorted(new_links - old_links, key=str.casefold)
        if old_links - new_links:
            removed[rel] = sorted(old_links - new_links, key=str.casefold)
    return created, updated, metadata, added, removed


def _reconcile_source_mappings(candidate: Path, sources: dict[str, Any], page_paths: list[str]) -> None:
    """Derive changed-page source mappings from their provenance citations."""
    for rel in page_paths:
        references = _provenance_references((candidate / rel).read_text(encoding="utf-8"))
        for source, entry in sources.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("pages"), list):
                continue
            mapped = {page for page in entry["pages"] if isinstance(page, str)}
            if source in references:
                mapped.add(rel)
            else:
                mapped.discard(rel)
            entry["pages"] = sorted(mapped)


def _best_target_rank(resolver: ContextResolver, query: str, relevance: dict[str, int]) -> tuple[list[str], int | None]:
    if not relevance:
        return [], None
    highest_grade = max(relevance.values())
    targets = sorted(stem for stem, grade in relevance.items() if grade == highest_grade)
    results = [page.stem for page in resolver.find_keywords(query, limit=5)]
    ranks = [results.index(target) + 1 for target in targets if target in results]
    return targets, min(ranks, default=None)


def _retrieval_regressions(repo_root: Path, candidate: Path) -> list[RetrievalRegression]:
    """Compare existing judged queries and report only worse best-target ranks."""
    cases_path = repo_root / "benchmarks/cold_start_cases.json"
    if not cases_path.is_file():
        return []
    try:
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(cases, list):
        return []
    current_resolver = ContextResolver(WikiDatabase(repo_root / "wiki"))
    candidate_resolver = ContextResolver(WikiDatabase(candidate / "wiki"))
    regressions: list[RetrievalRegression] = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("query"), str)
            or not isinstance(case.get("relevance"), dict)
        ):
            continue
        relevance = case["relevance"]
        if not relevance or any(type(grade) is not int or grade < 1 for grade in relevance.values()):
            continue
        try:
            normalized: dict[str, int] = {}
            for stem, grade in relevance.items():
                key = _normalize_relevance_key(str(stem))
                normalized[key] = max(normalized.get(key, 0), grade)
        except ValueError:
            continue
        targets, before_rank = _best_target_rank(current_resolver, case["query"], normalized)
        _, after_rank = _best_target_rank(candidate_resolver, case["query"], normalized)
        if before_rank is not None and (after_rank is None or after_rank > before_rank):
            regressions.append(
                RetrievalRegression(
                    query=case["query"],
                    targets=targets,
                    before_rank=before_rank,
                    after_rank=after_rank,
                )
            )
    return regressions


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


def _diagnostics_from_report(report: IngestionReport) -> list[KnowledgeDiagnostic]:
    if report.diagnostics:
        # Always include error-derived diagnostics for codes not already present.
        existing_messages = {d.message for d in report.diagnostics}
        diagnostics = list(report.diagnostics)
        for error in report.errors:
            if error not in existing_messages:
                diagnostics.append(_diagnostic_from_error(error))
        return diagnostics
    return [_diagnostic_from_error(error) for error in report.errors]


def _diagnostic_from_error(error: str) -> KnowledgeDiagnostic:
    if "raw source is not classified" in error:
        path = error.split(":", 1)[0]
        return KnowledgeDiagnostic(
            code="UNCLASSIFIED_RAW",
            message=error,
            path=path,
            fix="Select this source with existing_source_path or classify it in a dedicated update.",
        )
    if "does not cite this source in provenance" in error or "provenance section cites no" in error:
        return KnowledgeDiagnostic(
            code="MISSING_PROVENANCE_CITE",
            message=error,
            fix="Cite the source path in ## Provenance and status, or rely on engine provenance rendering.",
        )
    if "no outbound links" in error:
        return KnowledgeDiagnostic(
            code="NO_OUTBOUND_LINKS",
            message=error,
            path=error.split(":", 1)[0],
            fix="Add at least one [[wikilink]] from this page to a related knowledge page.",
        )
    if "orphaned" in error:
        return KnowledgeDiagnostic(
            code="ORPHAN_PAGE",
            message=error,
            path=error.split(":", 1)[0],
            fix="Update an existing page in the same payload so it links to this page by title.",
        )
    if "no novice-language cold-start question targets" in error:
        stem = error.split(":", 1)[0]
        return KnowledgeDiagnostic(
            code="MISSING_RETRIEVAL_CASE",
            message=error,
            path=stem,
            fix=f"Add a retrieval_cases entry whose highest-graded target is '{stem}'.",
        )
    if "target missing page" in error:
        stem = error.rsplit(":", 1)[-1].strip()
        return KnowledgeDiagnostic(
            code="UNKNOWN_RETRIEVAL_TARGET",
            message=error,
            expected=stem,
            fix="Point relevance at an existing page stem, wiki path, or wiki:// URI for a page in this update.",
        )
    if "cold-start hit@" in error or "no_result_accuracy" in error:
        return KnowledgeDiagnostic(
            code="RETRIEVAL_FLOOR",
            message=error,
            fix="Inspect per-query ranked hits in diagnostics and strengthen aliases, context_keys, or queries.",
        )
    return KnowledgeDiagnostic(code="VALIDATION_ERROR", message=error)


def check_ingestion(
    repo_root: Path,
    *,
    base: str | None = "HEAD",
    allow_deletions: bool = False,
    ignore_unrelated_unclassified_raw: bool = False,
    transaction_sources: set[str] | None = None,
    transaction_retrieval_queries: set[str] | None = None,
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
    _check_sources(
        repo_root,
        pages,
        registry,
        report,
        ignore_unrelated_unclassified_raw=ignore_unrelated_unclassified_raw,
        transaction_sources=transaction_sources or set(),
    )
    _check_graph(db, pages, report)
    _check_questions(
        repo_root,
        db,
        pages,
        report,
        transaction_retrieval_queries=transaction_retrieval_queries or set(),
    )
    _check_generated_files(repo_root, report)

    report.facts.insert(0, f"{len(pages)} knowledge pages; {len(registry)} registered sources")
    return report


def _load_source_registry(path: Path, report: IngestionReport) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        report.warnings.append("sources.json missing; source coverage checks skipped (scaffold mode)")
        return {}
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
        if _provenance_section(page.body) is None:
            report.errors.append(f"{rel}: missing '## Provenance and status' section")
        if registry and rel not in mapped_pages:
            report.errors.append(f"{rel}: not mapped from any source in sources.json")
        elif not registry:
            report.warnings.append(f"{rel}: scaffold mode — sources.json mapping not enforced")

    ok, audit_lines = audit_wiki(db)
    if not ok:
        report.errors.extend(line for line in audit_lines if line.startswith("✕"))


def _check_sources(
    repo_root: Path,
    pages: list[WikiPage],
    registry: dict[str, dict[str, Any]],
    report: IngestionReport,
    *,
    ignore_unrelated_unclassified_raw: bool = False,
    transaction_sources: set[str] | None = None,
) -> None:
    raw_dir = repo_root / "raw"
    on_disk = {
        path.relative_to(repo_root).as_posix()
        for path in raw_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }
    registered = set(registry)
    touched = set(transaction_sources or ())
    if on_disk:
        for source in sorted(on_disk - registered):
            if ignore_unrelated_unclassified_raw and source not in touched:
                report.warnings.append(
                    f"{source}: unclassified raw source left as repository debt (unchanged by this update)"
                )
            else:
                report.errors.append(f"{source}: raw source is not classified in sources.json")
        for source in sorted(registered - on_disk):
            report.errors.append(f"{source}: registered source does not exist locally")
    else:
        report.warnings.append("raw/ is empty or unavailable; physical source coverage was not checked")

    page_by_path = {page.filepath.relative_to(repo_root).as_posix(): page for page in pages}
    referenced_sources: set[str] = set()
    multi_source_synthesis = False
    for rel, page in page_by_path.items():
        references = _provenance_references(page.body)
        referenced_sources.update(references)
        if page.frontmatter.get("type") == "synthesis" and len(references) >= 2:
            multi_source_synthesis = True
        if not references and registry:
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
                elif source not in _provenance_references(mapped_page.body):
                    report.errors.append(f"{source}: {rel} does not cite this source in provenance")
        elif mapped:
            report.errors.append(f"{source}: {status} sources must not map to knowledge pages")

    if registry:
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


def _check_questions(
    repo_root: Path,
    db: WikiDatabase,
    pages: list[WikiPage],
    report: IngestionReport,
    *,
    transaction_retrieval_queries: set[str] | None = None,
) -> None:
    path = repo_root / "benchmarks" / "cold_start_cases.json"
    if not path.is_file():
        report.warnings.append(
            "benchmarks/cold_start_cases.json absent; cold-start retrieval checks skipped (scaffold mode)"
        )
        return
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"cannot read cold-start questions: {exc}")
        return
    if not isinstance(cases, list) or not cases:
        report.errors.append("cold_start_cases.json must contain at least one question")
        return

    normalized_cases: list[tuple[str, dict[str, int]]] = []
    benchmark_errors: list[str] = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("query"), str)
            or not isinstance(case.get("relevance"), dict)
        ):
            benchmark_errors.append("every cold-start case needs a query string and relevance object")
            continue
        query = case["query"]
        relevance = case["relevance"]
        normalized_relevance: dict[str, int] = {}
        valid_case = True
        for key, grade in relevance.items():
            if type(grade) is not int or grade < 1:
                benchmark_errors.append(f"{query}: relevance grade for {key} must be a positive integer")
                valid_case = False
                continue
            try:
                stem = _normalize_relevance_key(key)
            except ValueError as exc:
                benchmark_errors.append(f"{query}: {exc}")
                valid_case = False
                continue
            normalized_relevance[stem] = max(normalized_relevance.get(stem, 0), grade)
        if valid_case:
            normalized_cases.append((query, normalized_relevance))
    if benchmark_errors:
        report.errors.extend(benchmark_errors)
        return

    resolver = ContextResolver(db)
    covered: set[str] = set()
    hit_at_one: list[bool] = []
    hit_at_three: list[bool] = []
    no_result: list[bool] = []
    nonblocking_misses: list[KnowledgeDiagnostic] = []
    for query, normalized_relevance in normalized_cases:
        covered.update(normalized_relevance)
        results = [page.stem for page in resolver.find_keywords(query, limit=5)]
        if normalized_relevance:
            highest_grade = max(normalized_relevance.values())
            targets = sorted(stem for stem, grade in normalized_relevance.items() if grade == highest_grade)
            hit_at_one.append(any(target in results[:1] for target in targets))
            hit_at_three.append(any(target in results[:3] for target in targets))
            if not any(target in results[:3] for target in targets):
                message = f"query did not rank target in top 3: {query}"
                diagnostic = KnowledgeDiagnostic(
                    code="RETRIEVAL_MISS",
                    message=message,
                    query=query,
                    expected=", ".join(targets),
                    observed=results,
                    fix="Strengthen page aliases/context_keys or rewrite the novice-language query.",
                )
                if query in (transaction_retrieval_queries or set()):
                    report.diagnostics.append(diagnostic)
                    report.errors.append(message)
                else:
                    nonblocking_misses.append(diagnostic)
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
    if metrics["hit@3"] < _QUALITY_FLOORS["hit@3"]:
        report.diagnostics.extend(nonblocking_misses)
    for name, floor in _QUALITY_FLOORS.items():
        if metrics[name] < floor:
            report.errors.append(f"cold-start {name} {metrics[name]:.1%} is below the {floor:.0%} floor")
            report.diagnostics.append(
                KnowledgeDiagnostic(
                    code="RETRIEVAL_FLOOR",
                    message=f"cold-start {name} {metrics[name]:.1%} is below the {floor:.0%} floor",
                    expected=f">={floor:.0%}",
                    observed=[f"{name}={metrics[name]:.1%}"],
                    fix="Review RETRIEVAL_MISS diagnostics for ranked hits on failing queries.",
                )
            )
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
