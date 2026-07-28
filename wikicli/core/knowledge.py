"""Transport-neutral query and read operations for curated company knowledge."""

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


def query_company_knowledge(repo_root: Path, question: str, limit: int = 5) -> KnowledgeQueryResult:
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


def read_company_page(repo_root: Path, path: str) -> KnowledgePageResult:
    """Read one curated page while rejecting paths outside ``wiki/``."""
    repo_root = repo_root.resolve()
    requested = path.strip()
    if requested.startswith("wiki://page/"):
        requested = requested.removeprefix("wiki://page/")
    elif requested.startswith("wiki/"):
        requested = requested.removeprefix("wiki/")
    requested = requested.removesuffix(".md")
    wiki_root = (repo_root / "wiki").resolve()
    page_file = (wiki_root / f"{requested}.md").resolve()
    if not page_file.is_relative_to(wiki_root):
        raise ValueError(f"invalid company wiki path: {path}")
    if not page_file.is_file():
        raise FileNotFoundError(f"company wiki page not found: {path}")
    page = WikiPage(page_file)
    canonical_path, uri = _page_location(repo_root, page)
    return KnowledgePageResult(page.title, canonical_path, uri, page_file.read_text(encoding="utf-8"))
