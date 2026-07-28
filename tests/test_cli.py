from __future__ import annotations

import sys
from pathlib import Path

import pytest

from wikicli.cli import main
from wikicli.core.page import WikiPage
from wikicli.core.resolve import LiteralMatch
from wikicli.lifecycle.sync import SyncResult, SyncState


def test_root_self_locates_outside_the_checkout(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["wiki", "root"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == str(Path(__file__).resolve().parent.parent)


def test_graph_prints_frontmatter_only(tmp_path: Path, monkeypatch, capsys):
    page = tmp_path / "page.md"
    page.write_text("---\ntitle: Example\ntags: [one]\n---\n# Body\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["wiki", "graph", str(page)])

    main()

    assert capsys.readouterr().out == "title: Example\ntags: [one]\n"


def test_install_failure_is_a_nonzero_cli_exit(monkeypatch):
    monkeypatch.setattr("wikicli.cli.run_install", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sys, "argv", ["wiki", "install", "codex"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1


def test_find_explain_prints_score_reasons(monkeypatch, capsys, db):
    """Synthetic fixture + monkeypatch so this never depends on live demo content."""
    from wikicli.core.resolve import SearchHit

    page = next(p for p in db.pages.values() if p.stem == "pulsar")
    ranked = SearchHit(page, score=12.0, reasons=["title"])
    monkeypatch.setattr("wikicli.cli.search_keywords", lambda *_a, **_k: [ranked])
    monkeypatch.setattr(sys, "argv", ["wiki", "find", "Pulsar", "--limit", "1", "--explain"])

    main()

    output = capsys.readouterr().out
    assert "[[Pulsar]]" in output
    assert "score=" in output
    assert "title" in output


def test_grep_prints_literal_file_line_matches(tmp_path: Path, monkeypatch, capsys):
    path = tmp_path / "example.md"
    path.write_text("---\ntitle: Example\n---\n\nstats_failures records failures.\n", encoding="utf-8")
    match = LiteralMatch(WikiPage(path), 5, "stats_failures records failures.")
    monkeypatch.setattr("wikicli.cli.find_literal", lambda *_args, **_kwargs: [match])
    monkeypatch.setattr(sys, "argv", ["wiki", "grep", "stats_failures", "--limit", "1"])

    main()

    output = capsys.readouterr().out
    assert "example.md:5:" in output
    assert "stats_failures" in output


def test_sync_force_refreshes_and_reports_success(monkeypatch, capsys):
    calls: list[bool] = []

    def fake_sync(_repo_root: Path, *, force: bool = False) -> SyncResult:
        calls.append(force)
        return SyncResult(SyncState.UPDATED, "wiki main fast-forwarded to origin/main", True, 1000)

    monkeypatch.setattr("wikicli.cli.sync_wiki", fake_sync)
    monkeypatch.setattr(sys, "argv", ["wiki", "sync", "--force"])

    main()

    assert calls == [True]
    assert "fast-forwarded" in capsys.readouterr().out


def test_sync_returns_nonzero_when_the_worktree_cannot_be_updated(monkeypatch):
    monkeypatch.setattr(
        "wikicli.cli.sync_wiki",
        lambda *_args, **_kwargs: SyncResult(SyncState.DIRTY, "wiki main has local changes", False, 1000),
    )
    monkeypatch.setattr(sys, "argv", ["wiki", "sync"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
