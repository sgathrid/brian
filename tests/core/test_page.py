"""Page parsing: frontmatter, list fields, wikilinks, tags, and malformed input.

`page.py` is the single parser every other module depends on. Five divergent bash parsers used to
disagree about what a page's title was, which is how the auditor came to report the same page as
both a dead link and an orphan. These tests pin the contract so that cannot recur.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_page

from wikicli.core.page import WikiPage, is_nav


class TestFrontmatter:
    def test_scalar_fields(self, tmp_path: Path):
        p = write_page(
            tmp_path,
            "a.md",
            """
            title: "Quoted Title"
            type: entity
            scope: project
            summary: "One-line summary."
            repo: git@github.com:Org/repo.git
            """,
        )
        page = WikiPage(p)
        assert page.title == "Quoted Title", "surrounding quotes must be stripped"
        assert page.frontmatter["type"] == "entity"
        assert page.frontmatter["scope"] == "project"
        assert page.summary == "One-line summary."
        assert page.repo == "git@github.com:Org/repo.git"

    def test_title_defaults_to_stem_when_absent(self, tmp_path: Path):
        p = write_page(tmp_path, "my-page.md", "type: concept")
        assert WikiPage(p).title == "my-page"

    def test_list_fields_keep_every_value(self, tmp_path: Path):
        """The final element must survive.

        The bash implementation dropped the last value of every list, because its read loop exited
        on the unterminated final line — so `compass-platform` silently never matched anything.
        """
        p = write_page(
            tmp_path,
            "a.md",
            """
            title: "A"
            context_keys: [first, middle, last]
            aliases: [alt-one, alt-two]
            tags: [t1, t2, t3]
            """,
        )
        page = WikiPage(p)
        assert page.context_keys == ["first", "middle", "last"]
        assert page.aliases == ["alt-one", "alt-two"]
        assert page.tags == ["t1", "t2", "t3"]

    def test_quoted_list_values_are_unquoted(self, tmp_path: Path):
        p = write_page(tmp_path, "a.md", 'title: "A"\ncontext_keys: ["one", \'two\']')
        assert WikiPage(p).context_keys == ["one", "two"]

    def test_missing_frontmatter_is_not_fatal(self, tmp_path: Path):
        p = tmp_path / "plain.md"
        p.write_text("# Just a heading\n\nSome prose.\n", encoding="utf-8")
        page = WikiPage(p)
        assert page.title == "plain"
        assert page.frontmatter == {}
        assert "Just a heading" in page.body

    def test_unreadable_file_is_not_fatal(self, tmp_path: Path):
        page = WikiPage(tmp_path / "does-not-exist.md")
        assert page.title == "does-not-exist"
        assert page.body == ""


class TestWikilinks:
    def test_links_extracted_and_deduplicated(self, tmp_path: Path):
        p = write_page(tmp_path, "a.md", 'title: "A"', "See [[One]], [[Two]], and [[One]] again.")
        assert WikiPage(p).wikilinks == ["One", "Two"]

    def test_frontmatter_is_not_scanned_for_links(self, tmp_path: Path):
        """A `[[link]]` inside frontmatter is metadata, not a graph edge."""
        p = write_page(tmp_path, "a.md", 'title: "A"\nnote: "[[NotALink]]"', "Real [[Link]].")
        assert WikiPage(p).wikilinks == ["Link"]

    def test_no_links_yields_empty_list(self, tmp_path: Path):
        p = write_page(tmp_path, "a.md", 'title: "A"', "No links here.")
        assert WikiPage(p).wikilinks == []


class TestTags:
    def test_tags_is_frontmatter_only(self, tmp_path: Path):
        """`tags` must not require reading the body.

        `resolve_context` scores tags and runs on every session start. If `tags` folded in inline
        `#hashtags` it would force a body read for every page — measured at 3.7x slower — for a
        one-point signal.
        """
        p = write_page(tmp_path, "a.md", 'title: "A"\ntags: [alpha, beta]', "Inline #gamma here.")
        assert WikiPage(p).tags == ["alpha", "beta"]

    def test_inline_hashtags_are_not_metadata(self, tmp_path: Path):
        p = write_page(tmp_path, "a.md", 'title: "A"\ntags: [alpha, beta]', "Inline #gamma and color #FFFFFF.")
        assert WikiPage(p).tags == ["alpha", "beta"]

    def test_markdown_headings_are_not_tags(self, tmp_path: Path):
        """`## Section` must not become a tag — headings are structure, not metadata."""
        p = write_page(tmp_path, "a.md", 'title: "A"', "# Heading One\n\n## Section Two\n\nProse.")
        assert WikiPage(p).tags == []


class TestIsNav:
    def test_navigation_files_detected_case_insensitively(self):
        for name in ("index.md", "log.md", "tags.md", "backlinks.md", "CONVENTIONS.md", "SCALING.md"):
            assert is_nav(Path("/w") / name), f"{name} should be treated as nav"

    def test_content_pages_are_not_nav(self):
        for name in ("pulsar.md", "compass-ui.md", "graves-disease.md"):
            assert not is_nav(Path("/w/entities") / name)
