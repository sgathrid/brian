"""Contract tests against the REAL wiki content.

Everything else uses synthetic fixtures so assertions can be exact. These few run against the
committed knowledge base, because content rots in ways code tests cannot see.

Assert structural health for the demo scaffold — never a private corpus size.
"""

from __future__ import annotations

from pathlib import Path

from wikicli.core.audit import audit_wiki
from wikicli.core.ingest import check_ingestion
from wikicli.core.page import WikiDatabase, is_nav
from wikicli.core.resolve import ContextResolver

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = REPO_ROOT / "wiki"


class TestContentLoads:
    def test_content_pages_load_from_subdirectories(self, live_db: WikiDatabase):
        """Guards the non-recursive-glob regression against real content."""
        assert len(live_db.pages) >= 1, f"only {len(live_db.pages)} pages loaded — check the glob"
        assert any(
            page.filepath.parent.name in {"entities", "concepts", "projects", "syntheses"}
            for page in live_db.pages.values()
        )

    def test_most_markdown_files_are_indexed(self, live_db: WikiDatabase):
        on_disk = [p for p in WIKI_DIR.rglob("*.md") if not is_nav(p)]
        assert len(live_db.pages) == len(on_disk), "every non-nav page should be indexed"

    def test_no_title_collisions(self, live_db: WikiDatabase):
        assert live_db.collisions == [], f"duplicate titles make pages unreachable: {live_db.collisions}"


class TestContentHealth:
    def test_wiki_passes_the_construction_gate(self):
        """Scaffold-friendly: cold-start benchmarks and dense source maps are optional."""
        report = check_ingestion(REPO_ROOT, base=None)
        assert report.ok, "ingestion construction failures:\n" + "\n".join(report.errors)

    def test_wiki_passes_audit(self, live_db: WikiDatabase):
        ok, report = audit_wiki(live_db)
        dead = [line for line in report if "Dead wikilink" in line]
        schema = [line for line in report if "Missing frontmatter" in line]
        assert not dead, "dangling wikilinks:\n" + "\n".join(dead)
        assert not schema, "schema violations:\n" + "\n".join(schema)
        assert ok

    def test_every_page_declares_a_summary_or_title(self, live_db: WikiDatabase):
        for page in live_db.pages.values():
            assert page.title, f"{page.filepath.name} has no title"

    def test_scope_values_come_from_the_controlled_vocabulary(self, live_db: WikiDatabase):
        allowed = {"global", "company", "project", "engineering", "research", "branding"}
        for page in live_db.pages.values():
            scope = page.frontmatter.get("scope")
            if scope:
                assert scope in allowed, f"{page.filepath.name}: scope {scope!r} not in {sorted(allowed)}"

    def test_type_values_come_from_the_controlled_vocabulary(self, live_db: WikiDatabase):
        allowed = {
            "entity", "concept", "synthesis", "reference", "skill", "prompt",
            "project", "workflow", "index", "log",
        }
        for page in live_db.pages.values():
            page_type = page.frontmatter.get("type")
            if page_type:
                assert page_type in allowed, f"{page.filepath.name}: type {page_type!r} not in {sorted(allowed)}"


class TestResolutionAgainstRealRepos:
    def test_every_declared_repo_resolves_to_something(self, live_db: WikiDatabase):
        declared = [page for page in live_db.pages.values() if page.repo]
        assert declared, "the live knowledge base should bind at least one page to a repository"
        for page in declared:
            repo_name = page.repo.removesuffix(".git").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            result = ContextResolver(live_db).resolve_context(f"/Users/anyone/Repos/{repo_name}", limit=3)
            assert result, f"{page.filepath.name} declares {page.repo!r} but that repo resolves to nothing"

    def test_an_unrelated_directory_resolves_to_nothing(self, live_db: WikiDatabase):
        assert ContextResolver(live_db).resolve_context("/tmp/zzz-unrelated-xyz", limit=3) == []

    def test_pages_declaring_a_repo_use_a_remote_not_a_local_path(self, live_db: WikiDatabase):
        for page in live_db.pages.values():
            if page.repo:
                assert not page.repo.startswith("/"), f"{page.filepath.name}: repo must be a remote, not a local path"
