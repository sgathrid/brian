"""Generator determinism.

Generated files are committed, so a non-deterministic generator produces a spurious diff on every
run and trains everyone to ignore `wiki gen` output. CI enforces `wiki gen && git diff --exit-code`,
which only works if these hold.

The `updated:`-stamp trap: the registry writes today's date, so a naive overwrite dirties the working
tree once a day forever. It must compare substance and skip the write when nothing changed.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write_page

from wikicli.core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from wikicli.core.page import WikiDatabase


class TestIdempotency:
    def test_generated_dates_follow_knowledge_not_the_wall_clock(self, db: WikiDatabase, wiki_dir: Path):
        outputs = (
            generate_index(db, wiki_dir),
            generate_backlinks(db, wiki_dir),
            generate_tags(db, wiki_dir),
        )

        assert all("updated: 2026-01-01" in output.read_text(encoding="utf-8") for output in outputs)

    def test_backlinks_stable_across_runs(self, db: WikiDatabase, wiki_dir: Path):
        first = generate_backlinks(db, wiki_dir).read_text(encoding="utf-8")
        second = generate_backlinks(db, wiki_dir).read_text(encoding="utf-8")
        assert first == second

    def test_tags_stable_across_runs(self, db: WikiDatabase, wiki_dir: Path):
        first = generate_tags(db, wiki_dir).read_text(encoding="utf-8")
        second = generate_tags(db, wiki_dir).read_text(encoding="utf-8")
        assert first == second

    def test_output_is_order_independent(self, db: WikiDatabase, wiki_dir: Path):
        """Same content must yield byte-identical output regardless of filesystem iteration order."""
        first = generate_tags(db, wiki_dir).read_text(encoding="utf-8")
        reloaded = WikiDatabase(wiki_dir)
        assert generate_tags(reloaded, wiki_dir).read_text(encoding="utf-8") == first

    def test_tags_index_uses_declared_metadata_only(self, wiki_dir: Path):
        write_page(
            wiki_dir / "concepts",
            "colors.md",
            'title: "Colors"\ntype: concept\nscope: research\ntags: [design]',
            "#FFFFFF and #draft",
        )

        content = generate_tags(WikiDatabase(wiki_dir), wiki_dir).read_text(encoding="utf-8")

        assert "## #design" in content
        assert "#FFFFFF" not in content
        assert "#draft" not in content


class TestIndex:
    """`index.md` is what the session brief injects, and it is fully generated.

    It shipped once with the generator in place but no page carrying `summary:`, which silently
    destroyed 25 hand-curated one-line descriptions and halved the useful content of every session
    brief. A bare list of titles tells an agent nothing: `[[Criterion 4]]` is not self-describing.
    """

    def test_every_page_appears(self, db: WikiDatabase, wiki_dir: Path):
        content = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        for page in db.pages.values():
            assert f"[[{page.title}]]" in content, f"{page.title} missing from the catalog"

    def test_summaries_are_emitted(self, db: WikiDatabase, wiki_dir: Path):
        """The regression guard: a catalog of bare titles is near-useless to an agent."""
        content = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        assert "[[Pulsar]] — Topological data analysis pipeline." in content

    def test_pages_without_summary_still_listed(self, wiki_dir: Path):
        """Degrade gracefully — a missing summary must not drop the page from the catalog."""
        write_page(wiki_dir / "concepts", "nosum.md", 'title: "No Summary"\ntype: concept\nscope: research')
        db = WikiDatabase(wiki_dir)
        assert "[[No Summary]]" in generate_index(db, wiki_dir).read_text(encoding="utf-8")

    def test_hand_maintained_backlog_survives_regeneration(self, db: WikiDatabase, wiki_dir: Path):
        """`## Backlog` is the one hand-written part of a generated file."""
        index = wiki_dir / "index.md"
        generate_index(db, wiki_dir)
        index.write_text(
            index.read_text(encoding="utf-8") + "\n## Backlog\n\n- **Something deferred** — because reasons.\n",
            encoding="utf-8",
        )
        again = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        assert "## Backlog" in again
        assert "Something deferred" in again, "regeneration must not eat the backlog"

    def test_is_idempotent(self, db: WikiDatabase, wiki_dir: Path):
        first = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        second = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        assert first == second

    def test_carries_frontmatter(self, db: WikiDatabase, wiki_dir: Path):
        """CONVENTIONS.md states generated nav files carry `type: index`."""
        content = generate_index(db, wiki_dir).read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "type: index" in content
        assert "Auto-generated" in content

    def test_generated_index_is_not_loaded_as_content(self, db: WikiDatabase, wiki_dir: Path):
        generate_index(db, wiki_dir)
        assert len(WikiDatabase(wiki_dir).pages) == len(db.pages)


class TestRegistry:
    def test_registry_does_not_rewrite_when_unchanged(self, tmp_path: Path):
        """The `updated:` date is regenerated every run; the file must not be touched anyway.

        Otherwise every installer run dirties git, and the README's promise that a no-op install
        writes nothing inside the repo becomes false.
        """
        (tmp_path / "internal" / "skills").mkdir(parents=True)

        out = generate_registry(tmp_path)
        first_mtime = out.stat().st_mtime_ns
        first_text = out.read_text(encoding="utf-8")

        generate_registry(tmp_path)
        assert out.stat().st_mtime_ns == first_mtime, "unchanged registry must not be rewritten"
        assert out.read_text(encoding="utf-8") == first_text

    def test_registry_rebuilds_when_content_changes(self, tmp_path: Path):
        (tmp_path / "internal").mkdir(parents=True)
        out = generate_registry(tmp_path)
        before = out.read_text(encoding="utf-8")

        (tmp_path / "internal" / "prompts").mkdir(parents=True)
        (tmp_path / "internal" / "prompts" / "new.md").write_text(
            '---\ntitle: "New Prompt"\n---\nx\n', encoding="utf-8"
        )
        generate_registry(tmp_path)
        assert out.read_text(encoding="utf-8") != before
        assert "New Prompt" in out.read_text(encoding="utf-8")

    def test_registry_has_generated_banner(self, tmp_path: Path):
        (tmp_path / "internal").mkdir(parents=True)
        assert "Auto-generated" in generate_registry(tmp_path).read_text(encoding="utf-8")

    def test_registry_does_not_duplicate_curated_company_knowledge(self, tmp_path: Path):
        company = tmp_path / "internal/company"
        company.mkdir(parents=True)
        (company / "mission.md").write_text('---\ntitle: "Duplicate Mission"\n---\nBody\n', encoding="utf-8")

        content = generate_registry(tmp_path).read_text(encoding="utf-8")

        assert "Duplicate Mission" not in content
        assert "Company Context" not in content


class TestNavFilesAreOverwritable:
    def test_generators_write_into_the_wiki_dir(self, db: WikiDatabase, wiki_dir: Path):
        assert generate_backlinks(db, wiki_dir) == wiki_dir / "backlinks.md"
        assert generate_tags(db, wiki_dir) == wiki_dir / "tags.md"

    def test_regenerating_does_not_add_pages_to_the_database(self, wiki_dir: Path):
        """Generated nav output must never be picked up as content on the next load."""
        db = WikiDatabase(wiki_dir)
        generate_backlinks(db, wiki_dir)
        generate_tags(db, wiki_dir)
        assert len(WikiDatabase(wiki_dir).pages) == len(db.pages)
