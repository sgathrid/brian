"""Context resolution, search, and tag query engine."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .page import WikiDatabase, WikiPage

_TOKEN = re.compile(r"[a-z0-9]+")
_QUERY_SCAFFOLDING = (
    re.compile(r"\bin plain english\b", re.IGNORECASE),
    re.compile(r"\btell me about\b", re.IGNORECASE),
    re.compile(r"\bi know nothing about\b", re.IGNORECASE),
    re.compile(r"\bi just joined\b", re.IGNORECASE),
)
_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "before",
    "but",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "into",
    "info",
    "information",
    "is",
    "just",
    "may",
    "might",
    "s",
    "no",
    "of",
    "on",
    "or",
    "our",
    "should",
    "the",
    "they",
    "this",
    "through",
    "to",
    "us",
    "we",
    "what",
    "where",
    "which",
    "who",
    "wiki",
    "with",
    "would",
}
_FIELD_WEIGHTS = {"title": 6.0, "keys": 5.0, "tags": 4.0, "summary": 2.0, "body": 1.0}


@dataclass(frozen=True)
class SearchHit:
    page: WikiPage
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LiteralMatch:
    page: WikiPage
    line_number: int
    line: str


@dataclass
class _SearchDocument:
    page: WikiPage
    fields: dict[str, Counter[str]]
    lengths: dict[str, int]
    normalized: dict[str, str]


def _norm(text: str) -> str:
    """Normalizes a string to lower-case dash-separated alphanumerics.

    EVERY non-alphanumeric run collapses to a single dash. Enumerating a few separators is not
    enough: a path like `/Repos/Front Ends/example.com` kept its dot, so the declared key `brian` no
    longer appeared as `-brian-` and the page failed to resolve. Dots, `@`, `:`, `+`, and brackets
    all show up in real repo names and git remotes.
    """
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return "-".join(filter(None, s.split("-")))


def _repo_basename(repo: str) -> str:
    """Extracts the repo name from a git remote or path.

    `repo:` holds a portable remote such as `git@github.com:Brian-Overview/pulsar.git`, but the session
    only ever knows a local cwd. Matching the whole remote can therefore never succeed — the
    resolver must compare the basename (`pulsar`), which is what CONVENTIONS.md documents.
    """
    cleaned = repo.strip().removesuffix(".git")
    for sep in ("/", ":"):
        if sep in cleaned:
            cleaned = cleaned.rsplit(sep, 1)[-1]
    return cleaned


def _padded(text: str) -> str:
    """Returns a string padded with leading and trailing dashes for exact value matching."""
    norm = _norm(text)
    return f"-{norm}-" if norm else ""


class ContextResolverProtocol(Protocol):
    """Protocol interface for wiki context resolution."""

    def resolve_context(self, cwd: str, limit: int = 3) -> list[Path]: ...

    def find_keywords(self, query: str, limit: int = 10) -> list[WikiPage]: ...

    def search_keywords(self, query: str, limit: int = 10) -> list[SearchHit]: ...

    def find_tags(self, target_tag: str = "") -> list[tuple[str, list[WikiPage]]]: ...


class ContextResolver:
    """Standard in-memory context resolver implementation."""

    def __init__(self, db: WikiDatabase):
        self.db = db
        self._documents: list[_SearchDocument] | None = None
        self._document_frequency: Counter[str] = Counter()
        self._average_lengths: dict[str, float] = {}

    def resolve_context(self, cwd: str, limit: int = 3) -> list[Path]:
        """Resolves the most relevant wiki pages for a given working directory path."""
        if not cwd:
            return []

        haystack_padded = _padded(cwd)
        if not haystack_padded or haystack_padded == "--":
            return []

        scores: list[tuple[int, WikiPage]] = []

        for page in self.db.pages.values():
            score = 0

            # 1. context_keys and aliases (+5)
            keys = page.context_keys + page.aliases
            for k in keys:
                p_k = _padded(k)
                if p_k and p_k in haystack_padded:
                    score += 5

            # 2. repo basename matching (+6) — strongest and most portable signal
            if page.repo:
                p_repo = _padded(_repo_basename(page.repo))
                if p_repo and p_repo in haystack_padded:
                    score += 6

            # 3. title matching (+2)
            p_title = _padded(page.title)
            if p_title and p_title in haystack_padded:
                score += 2

            # 4. stem matching (+2) if different from title
            p_stem = _padded(page.stem)
            if p_stem and p_stem != p_title and p_stem in haystack_padded:
                score += 2

            # 5. tags matching (+1) — frontmatter tags ONLY.
            # Using `all_tags` here would pull in inline `#hashtags`, which forces a read of every
            # page body and makes this hot path 3.7x slower for a signal worth a single point.
            for t in page.tags:
                p_t = _padded(t)
                if p_t and p_t in haystack_padded:
                    score += 1

            if score > 0:
                scores.append((score, page))

        # Sort by score descending, then title length ascending (prefer specific pages), then title alphabetically
        scores.sort(key=lambda x: (-x[0], len(x[1].title), x[1].title.lower()))
        return [page.filepath for _, page in scores[:limit]]

    def _build_search_index(self) -> None:
        documents: list[_SearchDocument] = []
        document_frequency: Counter[str] = Counter()
        total_lengths: Counter[str] = Counter()
        for page in self.db.pages.values():
            texts = {
                "title": page.title,
                "keys": " ".join([page.stem, *page.context_keys, *page.aliases]),
                "tags": " ".join(page.tags),
                "summary": page.summary,
                "body": page.body,
            }
            tokenized = {name: _tokenize(text) for name, text in texts.items()}
            fields = {name: Counter(tokens) for name, tokens in tokenized.items()}
            lengths = {name: sum(counts.values()) for name, counts in fields.items()}
            normalized = {name: " ".join(tokens) for name, tokens in tokenized.items()}
            documents.append(_SearchDocument(page, fields, lengths, normalized))
            total_lengths.update(lengths)
            document_frequency.update(set().union(*(counts.keys() for counts in fields.values())))
        self._documents = documents
        self._document_frequency = document_frequency
        count = max(len(documents), 1)
        self._average_lengths = {field: total_lengths[field] / count for field in _FIELD_WEIGHTS}

    def search_keywords(self, query: str, limit: int = 10) -> list[SearchHit]:
        """Rank pages with field-weighted BM25, phrase boosts, and query-coverage gating."""
        tokens = _tokenize(_strip_query_scaffolding(query))
        query_terms = list(dict.fromkeys(token for token in tokens if token not in _STOPWORDS))
        if not query_terms:
            return []
        if self._documents is None:
            self._build_search_index()

        results: list[tuple[SearchHit, bool, bool]] = []
        phrase = " ".join(tokens)
        minimum_matches = 1 if len(query_terms) <= 2 else 2
        document_count = len(self._documents or [])
        # Discovery metadata is curated for retrieval. A term present on at most a third of pages
        # is specific enough to establish corpus support; common body prose is not.
        specific_frequency = max(2, math.ceil(document_count / 3))
        for document in self._documents or []:
            score = 0.0
            reasons: list[str] = []
            matched = 0
            normalized_title = document.normalized["title"]
            normalized_stem = _normalized_stem(document.page.stem)
            name_anchor = _contains_tokens(tokens, normalized_title.split())
            for term in query_terms:
                weighted_frequency = 0.0
                for field, weight in _FIELD_WEIGHTS.items():
                    frequency = document.fields[field][term]
                    if not frequency:
                        continue
                    length_ratio = document.lengths[field] / max(self._average_lengths[field], 1)
                    weighted_frequency += weight * frequency / (0.25 + 0.75 * length_ratio)
                if not weighted_frequency:
                    continue
                matched += 1
                frequency = self._document_frequency[term]
                inverse_frequency = math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
                score += inverse_frequency * (weighted_frequency * 2.2) / (weighted_frequency + 1.2)

            if matched < minimum_matches and not name_anchor:
                continue

            discovery_fields = ("title", "keys", "tags", "summary")
            name_terms = set(_tokenize(f"{document.page.title} {document.page.stem}"))
            title_matches = sum(bool(document.fields["title"][term]) for term in query_terms)
            non_name_terms = set(query_terms) - name_terms
            discovery_matches = {
                term for term in non_name_terms if any(document.fields[field][term] for field in discovery_fields)
            }
            specific_discovery_matches = {
                term for term in discovery_matches if self._document_frequency[term] <= specific_frequency
            }
            has_specific_discovery_match = bool(specific_discovery_matches)
            has_distinct_discovery_match = name_anchor or any(
                self._document_frequency[term] <= math.ceil(document_count / 2) for term in discovery_matches
            )
            supported = (
                len(query_terms) == 1
                or name_anchor
                or title_matches >= 2
                or (
                    has_specific_discovery_match
                    and (
                        len(query_terms) <= 3
                        or len(specific_discovery_matches) >= 2
                        or matched / len(query_terms) >= 2 / 3
                    )
                )
            )

            normalized_keys = document.normalized["keys"]
            if title_matches:
                score += title_matches * 2
                reasons.append(f"{title_matches} title terms")
            if phrase == normalized_title or phrase == normalized_stem:
                score += 12
                reasons.append("exact title")
            elif name_anchor:
                score += 4
                reasons.append("named title")
            elif phrase and phrase in normalized_title:
                score += 6
                reasons.append("title phrase")
            if phrase and phrase in normalized_keys:
                score += 5
                reasons.append("alias/context phrase")
            if phrase and phrase in document.normalized["tags"]:
                score += 3
                reasons.append("tag phrase")
            if phrase and phrase in document.normalized["summary"]:
                score += 2
                reasons.append("summary phrase")
            if phrase and phrase in document.normalized["body"]:
                score += 0.75
                reasons.append("body phrase")

            coverage = matched / len(query_terms)
            score *= 0.25 + 0.75 * coverage**2
            reasons.append(f"{matched}/{len(query_terms)} query terms")
            if has_specific_discovery_match:
                reasons.append("specific discovery metadata")
            results.append((SearchHit(document.page, score, tuple(reasons)), supported, has_distinct_discovery_match))

        if not any(supported for _, supported, _ in results):
            return []
        results.sort(key=lambda item: (-item[0].score, item[0].page.title.lower()))
        # Two-term questions are especially vulnerable to one useful term plus one incidental
        # body match. Once the query is supported, retain only pages with a distinguishing field.
        if len(query_terms) == 2:
            results = [item for item in results if item[2]]
        return [hit for hit, _, _ in results[:limit]]

    def find_keywords(self, query: str, limit: int = 10) -> list[WikiPage]:
        return [hit.page for hit in self.search_keywords(query, limit)]

    def find_tags(self, target_tag: str = "") -> list[tuple[str, list[WikiPage]]]:
        """Returns pages grouped by tag, or pages matching a specific tag."""
        tag_map: dict[str, list[WikiPage]] = {}

        for page in self.db.pages.values():
            for t in page.tags:
                tag_map.setdefault(t, []).append(page)

        if target_tag:
            target_clean = target_tag.lstrip("#").lower()
            filtered = {k: v for k, v in tag_map.items() if k.lower() == target_clean}
            return sorted(filtered.items())

        return sorted(tag_map.items())


def resolve_context(db: WikiDatabase, cwd: str, limit: int = 3) -> list[Path]:
    """Convenience helper for context resolution."""
    return ContextResolver(db).resolve_context(cwd, limit)


def find_keywords(db: WikiDatabase, query: str, limit: int = 10) -> list[WikiPage]:
    """Convenience helper for keyword search."""
    return ContextResolver(db).find_keywords(query, limit)


def search_keywords(db: WikiDatabase, query: str, limit: int = 10) -> list[SearchHit]:
    return ContextResolver(db).search_keywords(query, limit)


def find_literal(
    db: WikiDatabase, query: str, *, ignore_case: bool = False, limit: int | None = None
) -> list[LiteralMatch]:
    """Return exact line matches without ranking, expansion, or generated navigation pages."""
    if not query:
        return []
    needle = query.casefold() if ignore_case else query
    matches: list[LiteralMatch] = []
    for page in sorted(db.pages.values(), key=lambda item: str(item.filepath)):
        try:
            lines = page.filepath.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            haystack = line.casefold() if ignore_case else line
            if needle in haystack:
                matches.append(LiteralMatch(page, line_number, line))
                if limit is not None and len(matches) >= limit:
                    return matches
    return matches


def find_tags(db: WikiDatabase, target_tag: str = "") -> list[tuple[str, list[WikiPage]]]:
    """Convenience helper for tag queries."""
    return ContextResolver(db).find_tags(target_tag)


def _tokenize(text: str) -> list[str]:
    return [_stem(token) for token in _TOKEN.findall(text.casefold())]


def _strip_query_scaffolding(query: str) -> str:
    for pattern in _QUERY_SCAFFOLDING:
        query = pattern.sub(" ", query)
    return query


def _contains_tokens(haystack: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(haystack[index : index + len(needle)] == needle for index in range(len(haystack)))


@lru_cache(maxsize=4096)
def _stem(token: str) -> str:
    """Normalize common English inflections without introducing a search dependency."""
    if token.endswith("ying") and len(token) > 5:
        return token[:-3]
    if len(token) <= 4:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in ("ations", "ation", "ating", "ated", "ments", "ment", "ing", "ed"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    if token.endswith(("ches", "shes", "xes", "zes", "sses")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _normalized_stem(stem: str) -> str:
    return " ".join(_tokenize(stem))
