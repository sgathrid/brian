"""Unit tests for wiki reset and purge functionality."""

from __future__ import annotations

from pathlib import Path

from conftest import write_page

from wikicli.lifecycle.reset import run_reset


def test_full_reset_dry_run(wiki_dir: Path):
    (wiki_dir.parent / "raw").mkdir(exist_ok=True)
    (wiki_dir.parent / "raw" / "sample.txt").write_text("hello", encoding="utf-8")
    write_page(
        wiki_dir / "concepts", "sample.md", 'title: "Sample"\ntype: concept\nscope: research\nupdated: 2026-01-01'
    )

    run_reset(wiki_dir.parent, targets=["full"], dry_run=True, non_interactive=True)

    assert (wiki_dir / "concepts" / "sample.md").is_file()
    assert (wiki_dir.parent / "raw" / "sample.txt").is_file()


def test_full_reset_execution(wiki_dir: Path):
    raw_dir = wiki_dir.parent / "raw"
    raw_dir.mkdir(exist_ok=True)
    raw_file = raw_dir / "sample.txt"
    raw_file.write_text("hello", encoding="utf-8")

    page_file = write_page(
        wiki_dir / "concepts", "sample.md", 'title: "Sample"\ntype: concept\nscope: research\nupdated: 2026-01-01'
    )

    run_reset(wiki_dir.parent, targets=["full"], dry_run=False, non_interactive=True, confirmed=True, include_raw=True)

    assert not page_file.exists()
    assert not raw_file.exists()
    assert (wiki_dir / "index.md").is_file()


def test_scope_reset(wiki_dir: Path):
    p_research = write_page(
        wiki_dir / "concepts",
        "research-page.md",
        'title: "Research Page"\ntype: concept\nscope: research\nupdated: 2026-01-01',
    )
    p_company = write_page(
        wiki_dir / "entities",
        "company-page.md",
        'title: "Company Page"\ntype: entity\nscope: company\nupdated: 2026-01-01',
    )

    run_reset(wiki_dir.parent, targets=["scope"], scope="research", dry_run=False, non_interactive=True, confirmed=True)

    assert not p_research.exists()
    assert p_company.is_file()
