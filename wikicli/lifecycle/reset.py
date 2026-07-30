"""Wiki reset and maintenance module."""

from __future__ import annotations

import sys
from pathlib import Path

from ..core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from ..core.page import WikiDatabase
from ..ui.menu import is_tty, run_confirm, run_menu, run_scroll_viewer
from .personalization import load_settings_restore

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"

S_DOT_RED = f"{C_RED}●{C_RESET}"
S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"
S_CIRCLE_DIM = f"{C_DIM}○{C_RESET}"

PAGE_MODES = ("full", "scope", "orphans")
SETTINGS_ALIASES = frozenset({"settings", "user-settings", "user_settings"})


def _settings_runner():
    return load_settings_restore()


def _print_mode_help(*, has_settings: bool) -> None:
    print("wiki reset: refusing to run without an explicit mode.", file=sys.stderr)
    print("  wiki reset full --yes              # delete all pages (raw/ needs --include-raw)", file=sys.stderr)
    print("  wiki reset scope --scope X         # delete one scope", file=sys.stderr)
    print("  wiki reset orphans                 # delete unlinked pages", file=sys.stderr)
    if has_settings:
        print(
            "  wiki reset settings                # restore stock wiki.toml (not pages)",
            file=sys.stderr,
        )
        print(
            "  wiki reset settings upkeep|identity|all|factory [--dry-run] [-y]",
            file=sys.stderr,
        )
    print("  add --dry-run to preview any of the above.", file=sys.stderr)


def run_reset(
    repo_root: Path,
    targets: list[str] | None = None,
    scope: str = "",
    dry_run: bool = False,
    non_interactive: bool = False,
    confirmed: bool = False,
    include_raw: bool = False,
    stock_use_case: bool = False,
) -> None:
    """Reset wiki pages, or (when available) restore stock user settings."""
    targets = targets or []
    mode = targets[0].lower() if targets else ""
    settings_target = targets[1].lower() if len(targets) > 1 else ""
    run_settings_restore = _settings_runner()
    has_settings = run_settings_restore is not None

    if not mode and not non_interactive and is_tty():
        options = [
            ("full", "Full reset", "wipe wiki pages (raw/ needs --include-raw)", True),
            ("scope", "Scope reset", "purge pages in one scope", False),
            ("orphans", "Orphan sweep", "purge unlinked orphan pages", False),
        ]
        if has_settings:
            options.append(
                (
                    "settings",
                    "User settings",
                    "restore stock wiki.toml packs/names — does not delete pages",
                    False,
                )
            )
        mode = run_menu(
            "What do you want to reset?",
            options,
            title="Brian Wiki Reset",
            single_select=True,
        )

    # NEVER default to a destructive mode. `wiki reset` with no arguments and no TTY — which is how
    # agents and scripts invoke things — previously fell through to "full" and deleted every wiki
    # page plus all of raw/ with no confirmation. raw/ is git-ignored, so that loss is permanent.
    if not mode:
        _print_mode_help(has_settings=has_settings)
        raise SystemExit(2)

    if mode in SETTINGS_ALIASES:
        if run_settings_restore is None:
            print("wiki reset settings: not available in this checkout.", file=sys.stderr)
            print(
                "Edit wiki.toml instead:\n"
                "  [wiki]   name, short_name, description, agent_rules\n"
                "  [upkeep] proactivity, triggers, instructions",
                file=sys.stderr,
            )
            raise SystemExit(2)
        ok = run_settings_restore(
            repo_root,
            settings_target,
            dry_run=dry_run,
            non_interactive=non_interactive,
            confirmed=confirmed,
            stock_use_case=stock_use_case,
        )
        if not ok:
            raise SystemExit(1)
        return

    if mode not in PAGE_MODES:
        expected = "full, scope, orphans" + (", settings" if has_settings else "")
        print(f"wiki reset: unknown mode {mode!r} (expected {expected})", file=sys.stderr)
        raise SystemExit(2)

    wiki_dir = repo_root / "wiki"
    raw_dir = repo_root / "raw"
    db = WikiDatabase(wiki_dir)

    if mode == "scope" and not scope and not non_interactive and is_tty():
        available_scopes = sorted({p.scope for p in db.pages.values() if p.scope})
        if available_scopes:
            scope_opts = [(s, f"Scope: {s}") for s in available_scopes]
            scope = run_menu("Select scope to purge:", scope_opts, title="Brian Wiki Reset", single_select=True)

    # Destruction requires an explicit acknowledgement. A dry run is always allowed.
    if not dry_run and not confirmed:
        if not non_interactive and is_tty():
            if mode == "scope" and scope:
                prompt = f"Confirm purge of scope '{scope}'?"
            elif mode == "full" and include_raw:
                prompt = "Confirm FULL reset of all wiki pages and raw/ source files?"
            elif mode == "full":
                prompt = "Confirm FULL reset of all wiki pages?"
            else:
                prompt = f"Confirm {mode} reset?"

            confirmed = run_confirm(
                prompt,
                default=False,
                title="Brian Wiki Reset",
                confirm_label="delete matching files",
                cancel_label="keep files",
            )
            if not confirmed:
                print("wiki reset: cancelled by user.", file=sys.stderr)
                return

        if not confirmed:
            print(f"wiki reset: '{mode}' deletes knowledge and needs confirmation.", file=sys.stderr)
            print(f"  preview first:  wiki reset {mode} --dry-run", file=sys.stderr)
            print(f"  then confirm:   wiki reset {mode} --yes", file=sys.stderr)
            raise SystemExit(2)

    print(f"┌  {C_BOLD}Brian Wiki Reset {'(DRY RUN — PREVIEW ONLY, NO CHANGES MADE)' if dry_run else ''}{C_RESET}")
    print("│")
    print(f"│  repo: {repo_root}")
    print(f"│  mode: {mode}")
    print("│")

    files_to_delete: list[Path] = []
    affected_backlinks: dict[str, list[str]] = {}

    if mode == "full":
        for page_path in wiki_dir.rglob("*.md"):
            rel = page_path.relative_to(wiki_dir)
            if rel.name in ("CONVENTIONS.md", "index.md", "log.md", "backlinks.md", "tags.md"):
                continue
            files_to_delete.append(page_path)

        # raw/ is git-ignored by design, so deleting it is IRREVERSIBLE — unlike wiki pages, which
        # git can restore. It therefore requires its own explicit opt-in rather than riding along
        # with a page reset.
        if include_raw and raw_dir.is_dir():
            for raw_path in raw_dir.rglob("*"):
                if raw_path.is_file() and not raw_path.name.startswith("."):
                    files_to_delete.append(raw_path)
        elif raw_dir.is_dir():
            print(f"│  {S_CIRCLE_DIM} raw/ left untouched (git-ignored and unrecoverable; use --include-raw)")
            print("│")

    elif mode == "scope":
        if scope:
            print(f"│  target scope: {scope}")
            print("│")
            for page in db.pages.values():
                if page.scope == scope and page.filepath.name != "CONVENTIONS.md":
                    files_to_delete.append(page.filepath)

                    # Find pages outside this scope that link to this page
                    for other_page in db.pages.values():
                        if other_page.scope != scope and (
                            page.title in other_page.links or page.stem in other_page.links
                        ):
                            affected_backlinks.setdefault(page.title, []).append(other_page.title)

    elif mode == "orphans":
        # Find orphan pages (0 incoming backlinks, not in index.md)
        index_page = db.pages.get(wiki_dir / "index.md")
        index_links = set(index_page.links) if index_page else set()

        for page in db.pages.values():
            if page.stem in ("conventions", "index", "log", "backlinks", "tags"):
                continue
            has_incoming = any(page.title in p.links or page.stem in p.links for p in db.pages.values() if p != page)
            in_index = page.title in index_links or page.stem in index_links
            if not has_incoming and not in_index:
                files_to_delete.append(page.filepath)

    if not files_to_delete:
        print(f"│  {S_CIRCLE_DIM} No matching files found to reset/purge.")
        print("│")
        print(f"└  {C_BOLD}Done. No changes made.{C_RESET}")
        return

    # Print impact & backlink warnings
    if affected_backlinks:
        print(f"│  {C_RED}⚠️  Dangling link warning:{C_RESET}")
        for deleted_title, referrers in affected_backlinks.items():
            print(f"│     [[{deleted_title}]] is referenced by: {', '.join(f'[[{r}]]' for r in referrers)}")
        print("│")

    item_lines: list[str] = []
    for file_path in sorted(files_to_delete):
        rel_str = file_path.relative_to(repo_root)
        if dry_run:
            item_lines.append(f"{S_DOT_RED} [dry run] would delete {rel_str}")
        else:
            file_path.unlink()
            item_lines.append(f"{S_DOT_RED} deleted {rel_str}")

    header = f"Files targeted for removal ({len(files_to_delete)} files):"
    run_scroll_viewer(
        header,
        item_lines,
        max_visible=20,
        title="Brian Wiki Reset",
        non_interactive=non_interactive,
    )

    if not dry_run:
        # index.md is fully generated below, so it needs no baseline. log.md was deliberately
        # retired — git is the log — and recreating it here would resurrect a file no other module
        # maintains or excludes.
        fresh_db = WikiDatabase(wiki_dir)
        generate_index(fresh_db, wiki_dir)
        generate_backlinks(fresh_db, wiki_dir)
        generate_tags(fresh_db, wiki_dir)
        generate_registry(repo_root)
        print(f"│    {S_CHECK_GREEN} regenerated index.md, backlinks.md, tags.md, and internal/registry.md")
        print("│")

    print(
        f"└  {C_BOLD}Done. {'(Dry run — preview only, no files modified)' if dry_run else 'Reset complete.'}{C_RESET}"
    )
