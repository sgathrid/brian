"""Hot-path guardrails.

The SessionStart hook runs at the start of every session, in every repo, for every developer. Two
independent things can degrade as the knowledge base grows from ~30 pages to years of company
history, and they bind at very different points:

* **Latency** — measured, not guessed. On a realistic corpus (~2.9KB/page, 12 wikilinks, 5 tags,
  `repo:` + `context_keys`) resolution costs roughly:

      pages     load     context
         30    0.004s    0.0002s
        500    0.056s    0.003s
      1,000    0.109s    0.006s
      5,000    0.563s    0.030s

  So latency is a non-issue well past 1,000 pages — even 5,000 pages is ~4x faster than the bash
  implementation was at 31. A page count is a poor trigger anyway, because one 27KB page costs what
  ten stubs do. Trigger on measured latency instead.

* **Injected payload** — this binds FIRST, and much sooner. The catalog is one line per page, so at
  500 pages it is ~26KB (~6,500 tokens) paid on every session start by every agent. That consumes
  context window, which degrades answer quality silently — nobody files a bug for a slightly worse
  answer. `test_hook.py` enforces the size budget; `wikicli/hook.py` bounds the catalog so the cost
  is O(1) rather than O(pages).

These tests are deliberately generous. They exist to catch an ORDER-OF-MAGNITUDE regression — an
accidental O(n²), or re-introducing eager body reads — not to police milliseconds. If one fails on
slow CI hardware, confirm the trend before loosening it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from wikicli.core.page import WikiDatabase
from wikicli.core.resolve import ContextResolver

BODY = "This page describes a subsystem in detail. " * 60  # ~2.6KB, matches the real median


def build_corpus(root: Path, count: int) -> None:
    for i in range(count):
        directory = root / ("entities" if i % 2 else "concepts")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"page-{i}.md").write_text(
            f'---\ntitle: "Page {i}"\ntype: concept\nscope: project\n'
            f'summary: "Summary of page {i}."\n'
            f"context_keys: [key-{i}, alt-{i}]\ntags: [t{i % 40}, shared]\n"
            f"repo: git@github.com:Brian-Overview/repo-{i}.git\nupdated: 2026-01-01\n---\n\n{BODY}\n",
            encoding="utf-8",
        )


@pytest.fixture(scope="module")
def corpus_500(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("corpus500") / "wiki"
    build_corpus(root, 500)
    return root


class TestHotPathLatency:
    def test_load_of_500_pages_is_fast(self, corpus_500: Path):
        start = time.perf_counter()
        db = WikiDatabase(corpus_500)
        elapsed = time.perf_counter() - start
        assert len(db.pages) == 500
        # Measured ~0.056s locally. 2s allows ~35x headroom for slow CI runners and cold caches
        # while still catching an accidental O(n²) or a return to eager body parsing.
        assert elapsed < 2.0, f"loading 500 pages took {elapsed:.2f}s"

    def test_context_resolution_is_fast(self, corpus_500: Path):
        resolver = ContextResolver(WikiDatabase(corpus_500))
        start = time.perf_counter()
        for _ in range(10):
            resolver.resolve_context("/Users/me/Repos/repo-42", limit=3)
        per_call = (time.perf_counter() - start) / 10
        # Measured ~0.003s. This is the number the scaling guardrail should key on; when it exceeds
        # ~150ms in real use, build the SQLite/FTS5 sidecar (sqlite3 and FTS5 are BOTH stdlib, so
        # that does not violate the zero-dependency rule).
        assert per_call < 0.15, f"context resolution took {per_call * 1000:.0f}ms per call"

    def test_resolution_stays_correct_at_scale(self, corpus_500: Path):
        """Speed is worthless if the answer is wrong — 500 near-identical pages must still rank."""
        resolver = ContextResolver(WikiDatabase(corpus_500))
        result = resolver.resolve_context("/Users/me/Repos/repo-42", limit=3)
        assert [p.stem for p in result][:1] == ["page-42"]


class TestLazyBodyLoading:
    def test_loading_does_not_read_page_bodies(self, corpus_500: Path):
        """The invariant behind the 3.7x speedup, asserted structurally rather than by timing.

        Eager body parsing is an easy accidental regression: any `page.body` reference inside the
        load path silently restores it, and nothing else would notice.
        """
        db = WikiDatabase(corpus_500)
        assert all(page._body is None for page in db.pages.values()), "no body should be read at load"

    def test_context_resolution_does_not_read_bodies(self, corpus_500: Path):
        db = WikiDatabase(corpus_500)
        ContextResolver(db).resolve_context("/Users/me/Repos/repo-42", limit=3)
        untouched = sum(page._body is None for page in db.pages.values())
        assert untouched == len(db.pages), "context must not touch prose"

    def test_body_is_available_on_demand(self, corpus_500: Path):
        db = WikiDatabase(corpus_500)
        page = next(iter(db.pages.values()))
        assert "subsystem" in page.body
        assert page._body is not None, "body should be cached after first access"

    def test_find_reads_bodies_because_it_must(self, corpus_500: Path):
        """`find` searches prose — the lazy split must not break search."""
        db = WikiDatabase(corpus_500)
        assert ContextResolver(db).find_keywords("subsystem", limit=5), "prose search must still work"


class TestPayloadScaling:
    def test_catalog_injection_is_bounded(self, corpus_500: Path, tmp_path: Path):
        """The payload must not grow linearly with page count.

        At 500 pages an unbounded catalog is ~26KB (~6,500 tokens) per session; at 2,000 it is
        ~107KB. This is the constraint that actually binds, long before latency does.
        """
        from wikicli.core.generate import generate_index

        index_file = generate_index(WikiDatabase(corpus_500), corpus_500)
        full_catalog = index_file.read_text(encoding="utf-8")
        # ~19KB here with short synthetic summaries; the real corpus averages longer ones, so this
        # understates the production cost. Either way it dwarfs the 12KB payload budget.
        assert len(full_catalog) > 15_000, "sanity: 500 pages really does produce a large catalog"

        from wikicli.lifecycle.hook import _bounded_catalog

        bounded = _bounded_catalog(full_catalog)
        assert len(bounded) < 12_000, f"injected catalog must stay bounded, got {len(bounded)}"
        assert "wiki find" in bounded, "a truncated catalog must tell the agent how to reach the rest"
