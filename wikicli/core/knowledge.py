"""Transport-neutral query and read operations for curated knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .page import WikiDatabase, WikiPage
from .resolve import LiteralMatch, SearchHit, find_literal, search_keywords


@dataclass(frozen=True)
class KnowledgeHit:
    title: str
    path: str
    uri: str
    summary: str
    score: float
    match_reasons: list[str]


@dataclass(frozen=True)
class KnowledgeQueryResult:
    query: str
    hits: list[KnowledgeHit]
    no_results: bool


@dataclass(frozen=True)
class KnowledgePageResult:
    title: str
    path: str
    uri: str
    content: str


def _page_location(repo_root: Path, page: WikiPage) -> tuple[str, str]:
    path = page.filepath.relative_to(repo_root).as_posix()
    resource_path = page.filepath.relative_to(repo_root / "wiki").with_suffix("").as_posix()
    return path, f"wiki://page/{resource_path}"


def query_knowledge(repo_root: Path, question: str, limit: int = 5) -> KnowledgeQueryResult:
    """Return ranked curated pages for one natural-language question."""
    repo_root = repo_root.resolve()
    question = question.strip()
    if not question:
        raise ValueError("question must be non-empty")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")

    db = WikiDatabase(repo_root / "wiki")
    matches: list[SearchHit | LiteralMatch] = list(search_keywords(db, question, limit=limit))
    if not matches:
        matches = list(find_literal(db, question, ignore_case=True, limit=limit))

    hits: list[KnowledgeHit] = []
    for match in matches:
        path, uri = _page_location(repo_root, match.page)
        if isinstance(match, SearchHit):
            summary = match.page.summary
            score = round(match.score, 4)
            reasons = list(match.reasons)
        else:
            summary = match.line.strip()
            score = 0.0
            reasons = [f"literal line {match.line_number}"]
        hits.append(KnowledgeHit(match.page.title, path, uri, summary, score, reasons))
    return KnowledgeQueryResult(question, hits, not hits)


def read_page(repo_root: Path, ref: str) -> KnowledgePageResult:
    """Read one curated page by path, URI, title, wikilink, or stem."""
    repo_root = repo_root.resolve()
    requested = ref.strip()
    is_wikilink = requested.startswith("[[") and requested.endswith("]]")
    if is_wikilink:
        requested = requested[2:-2].strip()
    is_path = not is_wikilink and (
        requested.startswith(("wiki://page/", "wiki/")) or "/" in requested or requested.endswith(".md")
    )
    wiki_root = (repo_root / "wiki").resolve()

    if not is_path:
        page = WikiDatabase(wiki_root).resolve_link(requested)
        if page is None:
            raise FileNotFoundError(f"knowledge page not found: {ref}")
        page_file = page.filepath
    else:
        if requested.startswith("wiki://page/"):
            requested = requested.removeprefix("wiki://page/")
        elif requested.startswith("wiki/"):
            requested = requested.removeprefix("wiki/")
        requested = requested.removesuffix(".md")
        page_file = (wiki_root / f"{requested}.md").resolve()
        if not page_file.is_relative_to(wiki_root):
            raise ValueError(f"invalid knowledge page reference: {ref}")
        if not page_file.is_file():
            raise FileNotFoundError(f"knowledge page not found: {ref}")
    page = WikiPage(page_file)
    canonical_path, uri = _page_location(repo_root, page)
    return KnowledgePageResult(page.title, canonical_path, uri, page_file.read_text(encoding="utf-8"))
