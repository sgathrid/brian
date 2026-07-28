"""Guardrails on the only command that can destroy knowledge.

`wiki reset` shipped able to delete the entire knowledge base with no confirmation:

* Called with no arguments in a non-TTY — which is how agents and scripts invoke commands — it fell
  through to `mode = "full"`.
* "full" deleted every wiki page **and everything under `raw/`**.
* `raw/` is git-ignored by design, so unlike pages, that deletion is **permanent**.
* There was no confirmation prompt anywhere in the module.

Everything else in this project is built so that nothing deletes knowledge: `wiki uninstall` only
removes symlinks and hook entries, and defaults to reporting. `reset` is the exception and needs the
strictest tests in the suite. Do not relax these.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_page

from wikicli.lifecycle.reset import run_reset


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A throwaway repo with pages and an unrecoverable raw/ payload."""
    wiki = tmp_path / "wiki"
    write_page(wiki / "entities", "a.md", 'title: "A"\ntype: entity\nscope: project', "Links [[B]].")
    write_page(wiki / "concepts", "b.md", 'title: "B"\ntype: concept\nscope: research', "Links [[A]].")
    write_page(wiki / "concepts", "orphan.md", 'title: "Orphan"\ntype: concept\nscope: research', "Alone.")
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "source.txt").write_text("irreplaceable source document", encoding="utf-8")
    return tmp_path


def pages_of(root: Path) -> set[str]:
    return {p.name for p in (root / "wiki").rglob("*.md")}


class TestRefusesToGuess:
    def test_no_mode_and_no_tty_refuses(self, sandbox: Path):
        """The original behaviour here was total, silent, irreversible destruction."""
        before = pages_of(sandbox)
        with pytest.raises(SystemExit) as exc:
            run_reset(sandbox, [], non_interactive=True)
        assert exc.value.code == 2
        assert pages_of(sandbox) == before, "nothing may be deleted without an explicit mode"
        assert (sandbox / "raw" / "source.txt").exists()

    def test_unknown_mode_refuses(self, sandbox: Path):
        with pytest.raises(SystemExit):
            run_reset(sandbox, ["nuke"], non_interactive=True, confirmed=True)
        assert pages_of(sandbox)


class TestRequiresConfirmation:
    @pytest.mark.parametrize("mode", ["full", "scope", "orphans"])
    def test_destructive_modes_need_explicit_confirmation(self, sandbox: Path, mode: str):
        before = pages_of(sandbox)
        with pytest.raises(SystemExit) as exc:
            run_reset(sandbox, [mode], scope="research", non_interactive=True)
        assert exc.value.code == 2
        assert pages_of(sandbox) == before, f"{mode} deleted files without --yes"

    def test_dry_run_never_needs_confirmation_and_deletes_nothing(self, sandbox: Path):
        before = pages_of(sandbox)
        run_reset(sandbox, ["full"], dry_run=True, non_interactive=True)
        assert pages_of(sandbox) == before
        assert (sandbox / "raw" / "source.txt").exists()

    def test_interactive_confirmation_rejected_cancels(self, sandbox: Path, monkeypatch):
        before = pages_of(sandbox)
        monkeypatch.setattr("wikicli.lifecycle.reset.is_tty", lambda: True)
        monkeypatch.setattr("wikicli.lifecycle.reset.run_confirm", lambda prompt, **kwargs: False)

        run_reset(sandbox, ["full"], non_interactive=False)
        assert pages_of(sandbox) == before, "Reset must cancel if user selects No"

    def test_interactive_confirmation_accepted_proceeds(self, sandbox: Path, monkeypatch):
        monkeypatch.setattr("wikicli.lifecycle.reset.is_tty", lambda: True)
        monkeypatch.setattr("wikicli.lifecycle.reset.run_confirm", lambda prompt, **kwargs: True)

        run_reset(sandbox, ["full"], non_interactive=False)
        assert not (sandbox / "wiki" / "entities" / "a.md").exists(), "Reset must proceed if user selects Yes"


class TestRawIsProtected:
    def test_full_reset_does_not_touch_raw_by_default(self, sandbox: Path):
        """raw/ is git-ignored, so its loss cannot be undone. It needs its own opt-in."""
        run_reset(sandbox, ["full"], non_interactive=True, confirmed=True)
        assert (sandbox / "raw" / "source.txt").exists(), "raw/ must survive a page reset"
        assert not (sandbox / "wiki" / "entities" / "a.md").exists(), "pages should be gone"

    def test_include_raw_is_required_to_delete_sources(self, sandbox: Path):
        run_reset(sandbox, ["full"], non_interactive=True, confirmed=True, include_raw=True)
        assert not (sandbox / "raw" / "source.txt").exists()


class TestScopeAndOrphans:
    def test_scope_reset_only_removes_that_scope(self, sandbox: Path):
        run_reset(sandbox, ["scope"], scope="research", non_interactive=True, confirmed=True)
        remaining = pages_of(sandbox)
        assert "a.md" in remaining, "a different scope must be untouched"
        assert "b.md" not in remaining

    def test_orphan_sweep_spares_linked_pages(self, sandbox: Path):
        run_reset(sandbox, ["orphans"], non_interactive=True, confirmed=True)
        remaining = pages_of(sandbox)
        assert "orphan.md" not in remaining
        assert {"a.md", "b.md"} <= remaining, "pages with incoming links must survive"


class TestPostResetState:
    def test_log_md_is_not_resurrected(self, sandbox: Path):
        """`log.md` was deliberately retired — git is the log. Reset must not recreate it."""
        run_reset(sandbox, ["full"], non_interactive=True, confirmed=True)
        assert not (sandbox / "wiki" / "log.md").exists()

    def test_index_is_regenerated(self, sandbox: Path):
        run_reset(sandbox, ["full"], non_interactive=True, confirmed=True)
        index = (sandbox / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "Auto-generated" in index, "index.md should be regenerated, not left stale"
