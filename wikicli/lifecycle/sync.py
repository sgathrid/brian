"""Best-effort synchronization for the local company-wiki checkout."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix platforms
    fcntl = None  # type: ignore[assignment]

SYNC_INTERVAL_SECONDS = 15 * 60
SYNC_TIMEOUT_SECONDS = 5


class SyncState(str, Enum):
    CURRENT = "current"
    UPDATED = "updated"
    BEHIND = "behind"
    DIRTY = "dirty"
    BRANCH = "branch"
    AHEAD = "ahead"
    DIVERGED = "diverged"
    UNAVAILABLE = "unavailable"
    BUSY = "busy"


@dataclass(frozen=True)
class SyncResult:
    state: SyncState
    detail: str
    fresh: bool | None
    checked_at: float | None = None


@dataclass(frozen=True)
class _SyncCache:
    attempted_at: float | None = None
    successful_at: float | None = None
    error: str | None = None


def _default_state_dir() -> Path:
    return Path.home() / ".local" / "state" / "brian-wiki"


def _run_git(repo_root: Path, *args: str, timeout: int = SYNC_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = _run_git(repo_root, *args)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _read_cache(state_file: Path, repo_root: Path) -> _SyncCache:
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        if payload.get("repo_root") != str(repo_root.resolve()):
            return _SyncCache()
        attempted_at = payload.get("attempted_at")
        successful_at = payload.get("successful_at")
        error = payload.get("error")
        return _SyncCache(
            float(attempted_at) if isinstance(attempted_at, int | float) else None,
            float(successful_at) if isinstance(successful_at, int | float) else None,
            error if isinstance(error, str) else None,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return _SyncCache()


def _write_cache(state_file: Path, repo_root: Path, cache: _SyncCache) -> None:
    temporary = state_file.with_suffix(f".{os.getpid()}.tmp")
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                {
                    "repo_root": str(repo_root.resolve()),
                    "attempted_at": cache.attempted_at,
                    "successful_at": cache.successful_at,
                    "error": cache.error,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(state_file)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _acquire_lock(lock_path: Path) -> IO[str] | None:
    """Non-blocking exclusive lock. Uses flock when available."""
    if fcntl is None:
        return None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
    except OSError:
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_lock(handle: IO[str] | None) -> None:
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


def _should_fetch(cache: _SyncCache, *, force: bool, now: float) -> bool:
    if force or cache.attempted_at is None:
        return True
    return now - cache.attempted_at >= SYNC_INTERVAL_SECONDS


def _fetch_origin(repo_root: Path, state_file: Path, cache: _SyncCache, now: float) -> _SyncCache:
    """Attempt network fetch; always records attempted_at. Returns updated cache."""
    try:
        fetched = _run_git(repo_root, "fetch", "--quiet", "origin", "main")
    except subprocess.TimeoutExpired:
        detail = "wiki sync timed out; using local context"
        updated = _SyncCache(now, cache.successful_at, detail)
        _write_cache(state_file, repo_root, updated)
        return updated
    except OSError as exc:
        detail = f"wiki sync unavailable: {exc}"
        updated = _SyncCache(now, cache.successful_at, detail)
        _write_cache(state_file, repo_root, updated)
        return updated

    if fetched.returncode:
        detail = "wiki fetch failed; using local context"
        updated = _SyncCache(now, cache.successful_at, detail)
        _write_cache(state_file, repo_root, updated)
        return updated

    updated = _SyncCache(now, now)
    _write_cache(state_file, repo_root, updated)
    return updated


def _relation(repo_root: Path, checked_at: float | None) -> SyncResult:
    branch = _git_output(repo_root, "branch", "--show-current")
    if branch is None:
        return SyncResult(SyncState.UNAVAILABLE, "wiki checkout is not readable by git", None, checked_at)
    if branch != "main":
        name = branch or "detached HEAD"
        return SyncResult(SyncState.BRANCH, f"wiki is on {name}; only clean main is auto-updated", False, checked_at)

    dirty = _git_output(repo_root, "status", "--porcelain", "--untracked-files=normal")
    if dirty is None:
        return SyncResult(SyncState.UNAVAILABLE, "wiki worktree status could not be read", None, checked_at)
    if dirty:
        return SyncResult(SyncState.DIRTY, "wiki main has local changes; worktree was not updated", False, checked_at)

    counts = _git_output(repo_root, "rev-list", "--left-right", "--count", "HEAD...origin/main")
    if counts is None:
        return SyncResult(
            SyncState.UNAVAILABLE, "origin/main is unavailable; run `wiki sync --force`", None, checked_at
        )
    try:
        ahead, behind = (int(value) for value in counts.split())
    except ValueError:
        return SyncResult(SyncState.UNAVAILABLE, "wiki revision state could not be read", None, checked_at)

    if ahead and behind:
        return SyncResult(
            SyncState.DIVERGED, "wiki main diverged from origin/main; resolve it manually", False, checked_at
        )
    if ahead:
        return SyncResult(
            SyncState.AHEAD, "wiki main has unpushed commits; worktree was not updated", False, checked_at
        )
    if behind:
        return SyncResult(SyncState.BEHIND, f"wiki main is {behind} commit(s) behind origin/main", False, checked_at)
    if checked_at is None:
        return SyncResult(
            SyncState.UNAVAILABLE,
            "wiki matches cached origin/main, but network freshness has not been checked",
            None,
        )
    return SyncResult(SyncState.CURRENT, "wiki main matches the last fetched origin/main", True, checked_at)


def _fast_forward(repo_root: Path, checked_at: float | None) -> SyncResult:
    try:
        fast_forwarded = _run_git(repo_root, "merge", "--ff-only", "origin/main")
    except (OSError, subprocess.TimeoutExpired):
        fast_forwarded = None
    if fast_forwarded is None or fast_forwarded.returncode:
        return SyncResult(
            SyncState.UNAVAILABLE,
            "wiki fast-forward failed; using local context",
            None,
            checked_at,
        )
    return SyncResult(SyncState.UPDATED, "wiki main fast-forwarded to origin/main", True, checked_at)


def get_sync_status(
    repo_root: Path,
    *,
    state_dir: Path | None = None,
) -> SyncResult:
    """Report local freshness against the most recently fetched ``origin/main`` without network access."""
    repo_root = repo_root.resolve()
    state_root = state_dir or _default_state_dir()
    cache = _read_cache(state_root / "sync.json", repo_root)
    if cache.error:
        return SyncResult(SyncState.UNAVAILABLE, cache.error, None, cache.successful_at)
    return _relation(repo_root, cache.successful_at)


def sync_wiki(
    repo_root: Path,
    *,
    state_dir: Path | None = None,
    force: bool = False,
    now: float | None = None,
) -> SyncResult:
    """Fetch ``origin/main`` and fast-forward only a clean local ``main`` checkout.

    Network fetch is throttled; local fast-forward of an already-fetched ``origin/main`` is not.
    Network, worktree, and divergence failures are returned as status instead of raising so agent
    session startup can continue with explicit stale-context guidance.
    """
    repo_root = repo_root.resolve()
    state_root = state_dir or _default_state_dir()
    state_file = state_root / "sync.json"
    lock_path = state_root / "sync.lockfile"
    cache = _read_cache(state_file, repo_root)
    current_time = time.time() if now is None else now

    lock = _acquire_lock(lock_path)
    if lock is None:
        return SyncResult(SyncState.BUSY, "another wiki sync is already running", None, cache.successful_at)

    try:
        if _should_fetch(cache, force=force, now=current_time):
            cache = _fetch_origin(repo_root, state_file, cache, current_time)

        relation = _relation(repo_root, cache.successful_at)
        if relation.state is SyncState.BEHIND:
            return _fast_forward(repo_root, cache.successful_at)

        if cache.error:
            return SyncResult(SyncState.UNAVAILABLE, cache.error, None, cache.successful_at)
        return relation
    finally:
        _release_lock(lock)
