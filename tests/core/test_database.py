"""Database loading and indexing.

The single highest-impact defect this project has shipped was `glob("*.md")` instead of
`rglob("*.md")`: it loaded 3 of 31 files and ZERO content pages, so every lookup returned empty and
the session brief silently lost its working-context block. The test suite passed throughout, because
it only asserted that results were lists.

`test_loads_pages_from_subdirectories` is the regression test for that. Never weaken it to a
truthiness or type check.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_page

from wikicli.core.page import WikiDatabase


class TestRecursiveLoading:
    def test_loads_pages_from_subdirectories(self, db: WikiDatabase):
        """Content lives in `entities/` and `concepts/`; a non-recursive glob finds none of it."""
        stems = {p.stem for p in db.pages.values()}
        assert stems == {
            "pulsar",
            "compass-ui",
            "brian-overview",
            "themars",
            "lonely",
            "broken",
            "monitoring",
            "prefix-trap",
        }

    def test_page_count_is_non_zero(self, db: WikiDatabase):
        """The cheapest possible guard against the glob regression."""
        assert len(db.pages) > 0

    def test_navigation_files_are_excluded(self, db: WikiDatabase):
        """index/log/tags/backlinks are generated navigation, not content."""
        names = {p.name for p in db.pages}
        for nav in ("index.md", "log.md", "tags.md", "backlinks.md"):
            assert nav not in names, f"{nav} must not be loaded as a content page"

    def test_missing_directory_yields_empty_db(self, tmp_path: Path):
        assert len(WikiDatabase(tmp_path / "nope").pages) == 0


class TestIndexing:
    def test_lookup_by_title_is_case_insensitive(self, db: WikiDatabase):
        for query in ("Compass UI", "compass ui", "COMPASS UI"):
            page = db.resolve_link(query)
            assert page is not None, f"{query!r} should resolve"
            assert page.stem == "compass-ui"

    def test_resolves_by_title_when_filename_differs(self, db: WikiDatabase):
        """`themars.md` is titled "ThemaRS Pipeline".

        Links resolve by TITLE. An auditor that resolved by filename instead reported this page as
        a dead link and simultaneously as an orphan — both cannot be true.
        """
        page = db.resolve_link("ThemaRS Pipeline")
        assert page is not None
        assert page.stem == "themars"

    def test_resolves_by_stem_as_fallback(self, db: WikiDatabase):
        page = db.resolve_link("themars")
        assert page is not None
        assert page.title == "ThemaRS Pipeline"

    def test_unknown_link_returns_none(self, db: WikiDatabase):
        assert db.resolve_link("No Such Page") is None

    def test_quoted_link_text_resolves(self, db: WikiDatabase):
        assert db.resolve_link('"Pulsar"') is not None


class TestCollisions:
    def test_clean_wiki_reports_no_collisions(self, db: WikiDatabase):
        assert db.collisions == []

    def test_duplicate_titles_are_recorded_not_silently_dropped(self, wiki_dir: Path):
        """Two pages sharing a title must be surfaced.

        `by_title` is a dict, so the second page would otherwise overwrite the first and one page
        would become permanently unreachable by link with no warning anywhere.
        """
        write_page(wiki_dir / "entities", "pulsar-copy.md", 'title: "Pulsar"\ntype: entity\nscope: project')
        db = WikiDatabase(wiki_dir)
        assert len(db.collisions) == 1
        assert "Pulsar" in db.collisions[0]
        # Both pages still load; only the title index can hold one.
        assert len([p for p in db.pages.values() if p.title == "Pulsar"]) == 2
