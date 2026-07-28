"""The knowledge graph: backlinks, dead links, and orphans.

The wiki's value is the graph, not the pages. These tests pin the two properties that make it
trustworthy:

- Link resolution is by TITLE, consistently, everywhere. When the auditor resolved by filename while
  the generator resolved by title, the same page was reported as both a dead link and an orphan.
- Generated navigation files are never counted as link SOURCES. Otherwise `backlinks.md` lists every
  page, so nothing is ever an orphan and the orphan check becomes decorative.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_page

from wikicli.core.audit import audit_wiki
from wikicli.core.generate import generate_backlinks, generate_tags
from wikicli.core.page import WikiDatabase


class TestBacklinks:
    def test_backlinks_record_incoming_edges(self, db: WikiDatabase, wiki_dir: Path):
        out = generate_backlinks(db, wiki_dir)
        content = out.read_text(encoding="utf-8")
        # Pulsar is linked from Compass UI, My Org, ThemaRS and Lonely.
        assert "[[Pulsar]]" in content
        for source in ("Compass UI", "My Org", "ThemaRS Pipeline", "Lonely Concept"):
            assert source in content, f"{source} links to Pulsar and should appear as a backlink"

    def test_backlink_target_resolved_by_title_not_filename(self, db: WikiDatabase, wiki_dir: Path):
        """`themars.md` is titled "ThemaRS Pipeline" and Pulsar links to it by title."""
        content = generate_backlinks(db, wiki_dir).read_text(encoding="utf-8")
        assert "[[ThemaRS Pipeline]]" in content
        assert "Pulsar" in content

    def test_generated_banner_present(self, db: WikiDatabase, wiki_dir: Path):
        for gen in (generate_backlinks, generate_tags):
            assert "Auto-generated" in gen(db, wiki_dir).read_text(encoding="utf-8")


class TestTagIndex:
    def test_every_declared_tag_appears(self, db: WikiDatabase, wiki_dir: Path):
        content = generate_tags(db, wiki_dir).read_text(encoding="utf-8")
        for tag in ("python", "rust", "topology", "nextjs", "healthcare-ai", "clinical-ai", "safety"):
            assert tag in content, f"tag {tag!r} missing from tags index"

    def test_tag_groups_list_their_pages(self, db: WikiDatabase, wiki_dir: Path):
        content = generate_tags(db, wiki_dir).read_text(encoding="utf-8")
        python_section = content.split("python", 1)[1][:200]
        assert "Pulsar" in python_section


class TestDeadLinks:
    def test_dead_link_is_reported(self, db: WikiDatabase):
        ok, report = audit_wiki(db)
        assert not ok, "a wiki containing a dead link must not pass audit"
        assert any("No Such Page" in line for line in report)

    def test_valid_links_are_not_reported_as_dead(self, db: WikiDatabase):
        _, report = audit_wiki(db)
        dead = [line for line in report if "Dead wikilink" in line]
        assert len(dead) == 1, f"expected exactly one dead link, got: {dead}"

    def test_title_filename_mismatch_is_not_a_dead_link(self, db: WikiDatabase):
        """The self-contradiction regression: [[ThemaRS Pipeline]] lives in `themars.md`."""
        _, report = audit_wiki(db)
        assert not any("ThemaRS" in line and "Dead" in line for line in report)


class TestOrphans:
    def test_orphan_is_detected(self, db: WikiDatabase):
        _, report = audit_wiki(db)
        assert any("lonely.md" in line for line in report), "a page with no incoming links is an orphan"

    def test_linked_page_is_not_an_orphan(self, db: WikiDatabase):
        _, report = audit_wiki(db)
        orphan_block = "\n".join(report).split("Orphan pages", 1)[-1]
        assert "pulsar.md" not in orphan_block, "Pulsar has several incoming links"

    def test_page_linked_only_from_nav_is_still_an_orphan(self, db: WikiDatabase):
        """`index.md` links to Lonely Concept, but navigation files are not real relationships.

        If nav files counted as sources, `backlinks.md` alone would make every page look connected.
        """
        _, report = audit_wiki(db)
        assert any("lonely.md" in line for line in report)


class TestSchema:
    def test_missing_required_frontmatter_is_reported(self, db: WikiDatabase):
        ok, report = audit_wiki(db)
        assert not ok
        assert any("broken.md" in line and "scope" in line for line in report)

    def test_complete_page_passes_schema(self, db: WikiDatabase):
        _, report = audit_wiki(db)
        assert not any("pulsar.md" in line and "Missing frontmatter" in line for line in report)

    def test_clean_wiki_passes_audit(self, tmp_path: Path):
        """A wiki with no dead links and complete frontmatter must return ok=True.

        Guards the inverse failure: an auditor that always reports problems is ignored, and an
        auditor that always passes is worthless.
        """
        wiki = tmp_path / "wiki"
        write_page(wiki / "e", "a.md", 'title: "A"\ntype: entity\nscope: project', "Links to [[B]].")
        write_page(wiki / "e", "b.md", 'title: "B"\ntype: entity\nscope: project', "Links to [[A]].")
        ok, report = audit_wiki(WikiDatabase(wiki))
        assert ok, f"clean wiki should pass, got: {report}"
