from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

import pytest

from wikicli.lifecycle.sync import SyncState, get_sync_status, sync_wiki


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


@pytest.fixture
def shared_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"
    state = tmp_path / "state"

    origin.mkdir()
    git(origin, "init", "--bare", "--initial-branch=main")
    seed.mkdir()
    git(seed, "init", "--initial-branch=main")
    git(seed, "config", "user.name", "Wiki Test")
    git(seed, "config", "user.email", "wiki@example.com")
    (seed / "wiki").mkdir()
    (seed / "wiki/index.md").write_text("one\n", encoding="utf-8")
    git(seed, "add", "wiki/index.md")
    git(seed, "commit", "-m", "initial")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "main")

    git(tmp_path, "clone", str(origin), str(clone))
    git(clone, "config", "user.name", "Wiki Test")
    git(clone, "config", "user.email", "wiki@example.com")
    return clone, seed, state


def push_change(seed: Path, content: str) -> None:
    (seed / "wiki/index.md").write_text(content, encoding="utf-8")
    git(seed, "add", "wiki/index.md")
    git(seed, "commit", "-m", content.strip())
    git(seed, "push", "origin", "main")


def test_current_clean_main_is_reported_fresh(shared_repo: tuple[Path, Path, Path]):
    clone, _seed, state = shared_repo

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.CURRENT
    assert result.fresh is True
    assert get_sync_status(clone, state_dir=state).state is SyncState.CURRENT


def test_behind_clean_main_fast_forwards(shared_repo: tuple[Path, Path, Path]):
    clone, seed, state = shared_repo
    push_change(seed, "two\n")

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.UPDATED
    assert result.fresh is True
    assert (clone / "wiki/index.md").read_text(encoding="utf-8") == "two\n"
    assert git(clone, "rev-parse", "HEAD") == git(clone, "rev-parse", "origin/main")


def test_dirty_main_fetches_but_never_changes_the_worktree(shared_repo: tuple[Path, Path, Path]):
    clone, seed, state = shared_repo
    (clone / "wiki/index.md").write_text("local\n", encoding="utf-8")
    push_change(seed, "remote\n")

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.DIRTY
    assert result.fresh is False
    assert (clone / "wiki/index.md").read_text(encoding="utf-8") == "local\n"
    assert git(clone, "rev-parse", "HEAD") != git(clone, "rev-parse", "origin/main")


def test_diverged_main_is_never_merged_or_rebased(shared_repo: tuple[Path, Path, Path]):
    clone, seed, state = shared_repo
    (clone / "local.txt").write_text("local\n", encoding="utf-8")
    git(clone, "add", "local.txt")
    git(clone, "commit", "-m", "local")
    local_head = git(clone, "rev-parse", "HEAD")
    push_change(seed, "remote\n")

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.DIVERGED
    assert result.fresh is False
    assert git(clone, "rev-parse", "HEAD") == local_head


def test_ahead_main_is_never_pushed_or_rewritten(shared_repo: tuple[Path, Path, Path]):
    clone, _seed, state = shared_repo
    (clone / "local.txt").write_text("local\n", encoding="utf-8")
    git(clone, "add", "local.txt")
    git(clone, "commit", "-m", "local")
    local_head = git(clone, "rev-parse", "HEAD")

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.AHEAD
    assert result.fresh is False
    assert git(clone, "rev-parse", "HEAD") == local_head


def test_feature_branch_fetches_but_is_not_updated(shared_repo: tuple[Path, Path, Path]):
    clone, seed, state = shared_repo
    git(clone, "switch", "-c", "feature")
    feature_head = git(clone, "rev-parse", "HEAD")
    push_change(seed, "remote\n")

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.BRANCH
    assert result.fresh is False
    assert git(clone, "rev-parse", "HEAD") == feature_head
    assert git(clone, "rev-parse", "origin/main") != feature_head


def test_offline_fetch_fails_open(shared_repo: tuple[Path, Path, Path]):
    clone, _seed, state = shared_repo
    git(clone, "remote", "set-url", "origin", str(clone / "missing-origin.git"))

    result = sync_wiki(clone, state_dir=state, force=True, now=1000)

    assert result.state is SyncState.UNAVAILABLE
    assert result.fresh is None
    assert (clone / "wiki/index.md").read_text(encoding="utf-8") == "one\n"

    throttled = sync_wiki(clone, state_dir=state, now=1060)
    status = get_sync_status(clone, state_dir=state)
    assert throttled.state is SyncState.UNAVAILABLE
    assert status.state is SyncState.UNAVAILABLE
    assert "fetch failed" in status.detail


def test_recent_check_throttles_network_work(shared_repo: tuple[Path, Path, Path]):
    clone, seed, state = shared_repo
    assert sync_wiki(clone, state_dir=state, force=True, now=1000).state is SyncState.CURRENT
    push_change(seed, "remote\n")

    throttled = sync_wiki(clone, state_dir=state, now=1060)

    assert throttled.state is SyncState.CURRENT
    assert throttled.checked_at == 1000
    assert (clone / "wiki/index.md").read_text(encoding="utf-8") == "one\n"
    assert sync_wiki(clone, state_dir=state, force=True, now=1061).state is SyncState.UPDATED


def test_throttled_retry_fast_forwards_after_worktree_becomes_clean(
    shared_repo: tuple[Path, Path, Path],
):
    clone, seed, state = shared_repo
    (clone / "wiki/index.md").write_text("local\n", encoding="utf-8")
    push_change(seed, "remote\n")

    dirty = sync_wiki(clone, state_dir=state, force=True, now=1000)
    assert dirty.state is SyncState.DIRTY
    assert git(clone, "rev-parse", "HEAD") != git(clone, "rev-parse", "origin/main")

    git(clone, "checkout", "--", "wiki/index.md")

    result = sync_wiki(clone, state_dir=state, force=False, now=1060)

    assert result.state is SyncState.UPDATED
    assert result.fresh is True
    assert (clone / "wiki/index.md").read_text(encoding="utf-8") == "remote\n"
    assert git(clone, "rev-parse", "HEAD") == git(clone, "rev-parse", "origin/main")


def test_concurrent_session_skips_when_sync_lock_is_held(shared_repo: tuple[Path, Path, Path]):
    clone, _seed, state = shared_repo
    state.mkdir(parents=True)
    lock_path = state / "sync.lockfile"
    handle = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = sync_wiki(clone, state_dir=state, force=True, now=1000)

        assert result.state is SyncState.BUSY
        assert result.fresh is None
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def test_status_without_a_network_check_is_unknown(shared_repo: tuple[Path, Path, Path]):
    clone, _seed, state = shared_repo

    result = get_sync_status(clone, state_dir=state)

    assert result.state is SyncState.UNAVAILABLE
    assert result.fresh is None
    assert "has not been checked" in result.detail
