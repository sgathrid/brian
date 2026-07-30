"""Restore wiki.toml personalization to stock defaults (Brian product only).

Does not delete wiki pages — that remains `wiki reset` (full/scope/orphans).
Natural-language triggers/instructions live in [upkeep]; this rewrites those
fields (and optionally identity / rules) from init presets.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

from ..core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from ..core.page import WikiDatabase
from ..ui.menu import is_tty, run_confirm, run_menu
from .init import (
    USE_CASE_PRESETS,
    _clean_company_rel_path,
    _load_existing_manifest,
    _normalize_proactivity,
    _normalize_rules,
    _slugify,
    _update_pointer_templates,
    _upkeep_for_posture,
    write_wiki_toml,
)

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"

RESTORE_TARGETS = ("upkeep", "identity", "all", "factory")

TARGET_LABELS = {
    "upkeep": "Upkeep text",
    "identity": "Org identity",
    "all": "All settings (this use case)",
    "factory": "Factory defaults",
}


class SettingsSnapshot(TypedDict):
    """Normalized settings consumed by preview and apply paths."""

    use_case: str
    name: str
    short_name: str
    description: str
    agent_rules: list[str]
    company_rel_path: str
    proactivity: str
    triggers: list[str]
    instructions: str


def _repo_base_name(repo_root: Path) -> str:
    return repo_root.name.replace("-", " ").replace("_", " ").title() or "Organization"


def _clip(text: str, width: int = 48) -> str:
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _current_snapshot(existing: dict, repo_root: Path) -> SettingsSnapshot:
    wiki = existing.get("wiki", {}) if isinstance(existing.get("wiki"), dict) else {}
    paths = existing.get("paths", {}) if isinstance(existing.get("paths"), dict) else {}
    upkeep = existing.get("upkeep", {}) if isinstance(existing.get("upkeep"), dict) else {}

    use_case = str(wiki.get("use_case") or "company").strip()
    if use_case not in USE_CASE_PRESETS:
        use_case = "company"
    preset = USE_CASE_PRESETS[use_case]
    base = _repo_base_name(repo_root)

    triggers: list[str] = []
    raw_t = upkeep.get("triggers")
    if isinstance(raw_t, list):
        triggers = [str(t) for t in raw_t if str(t).strip()]
    elif isinstance(raw_t, str) and raw_t.strip():
        triggers = [raw_t.strip()]

    proactivity = _normalize_proactivity(upkeep.get("proactivity")) or "selective"
    rules = _normalize_rules(wiki.get("agent_rules", []))
    company_rel = str(paths.get("company_file") or "").strip()
    if not company_rel:
        slug = _slugify(str(wiki.get("name") or base).replace("Knowledge Base", "").replace("Wiki", ""))
        company_rel = f"wiki/entities/{slug}-overview.md"

    return {
        "use_case": use_case,
        "name": str(wiki.get("name") or f"{base} {preset['default_name_suffix']}"),
        "short_name": str(wiki.get("short_name") or f"{base} {preset['default_short_suffix']}"),
        "description": str(
            wiki.get("description") or preset["default_desc_template"].format(org=wiki.get("name") or base)
        ),
        "agent_rules": rules,
        "company_rel_path": company_rel,
        "proactivity": proactivity,
        "triggers": triggers,
        "instructions": str(upkeep.get("instructions") or "").strip(),
    }


def _planned_snapshot(
    current: SettingsSnapshot,
    target: str,
    repo_root: Path,
    *,
    stock_use_case: bool,
) -> SettingsSnapshot:
    planned = current.copy()
    use_case = str(current["use_case"])
    if stock_use_case and target == "all":
        use_case = "company"
        planned["use_case"] = use_case

    preset = USE_CASE_PRESETS[use_case]
    base = _repo_base_name(repo_root)
    proactivity = (
        str(current["proactivity"])
        if str(current["proactivity"]) in ("selective", "active", "capture", "silent")
        else "selective"
    )

    if target in ("identity", "all"):
        name = f"{base} {preset['default_name_suffix']}"
        planned["name"] = name
        planned["short_name"] = f"{base} {preset['default_short_suffix']}"
        planned["description"] = preset["default_desc_template"].format(org=name)

    if target in ("upkeep", "all"):
        if target == "all":
            proactivity = "selective"
            planned["proactivity"] = proactivity
        triggers, instructions = _upkeep_for_posture(use_case, proactivity)
        planned["triggers"] = triggers
        planned["instructions"] = instructions

    if target == "all":
        planned["agent_rules"] = list(preset["default_rules"])

    planned["company_rel_path"] = _clean_company_rel_path(
        str(current.get("company_rel_path") or ""),
        _slugify(str(planned["name"]).replace("Knowledge Base", "").replace("Wiki", "")) + "-overview",
    )
    return planned


def _preview_rows(before: SettingsSnapshot, after: SettingsSnapshot) -> list[tuple[str, str]]:
    """Return (label, change summary) rows for fields that differ."""
    rows: list[tuple[str, str]] = []

    def add_scalar(key: str, label: str) -> None:
        b, a = before.get(key), after.get(key)
        if b == a:
            return
        rows.append((label, f"{_clip(str(b), 36)}  →  {_clip(str(a), 36)}"))

    add_scalar("use_case", "use_case")
    add_scalar("name", "name")
    add_scalar("short_name", "short_name")

    if before.get("description") != after.get("description"):
        rows.append(("description", "rewritten to use-case default"))

    b_rules = before["agent_rules"]
    a_rules = after["agent_rules"]
    if b_rules != a_rules:
        rows.append(("agent_rules", f"{len(b_rules)} selected  →  {len(a_rules)} defaults"))

    add_scalar("proactivity", "proactivity")

    b_t = before["triggers"]
    a_t = after["triggers"]
    if b_t != a_t:
        rows.append(("triggers", f"{len(b_t)} custom  →  {len(a_t)} stock"))

    if str(before.get("instructions") or "").strip() != str(after.get("instructions") or "").strip():
        rows.append(("instructions", "restored to stock pack"))

    return rows


def _print_preview(
    display_target: str,
    plan_target: str,
    rows: list[tuple[str, str]],
    *,
    dry_run: bool,
    stock_use_case: bool,
) -> None:
    label = TARGET_LABELS.get(display_target, display_target)
    suffix = " · dry run" if dry_run else ""
    print(f"┌  {C_BOLD}wiki reset · user settings{suffix}{C_RESET}")
    print("│")
    print(
        f"│  {C_BOLD}Target{C_RESET}  {C_CYAN}{label}{C_RESET}  "
        f"{C_DIM}→ wiki.toml + generated defaults{C_RESET}"
    )
    if stock_use_case and plan_target == "all":
        print(f"│  {C_YELLOW}Forces use_case = company (fresh-checkout defaults){C_RESET}")
    print("│")
    if not rows:
        print(f"│  {C_DIM}Already at stock defaults for this target.{C_RESET}")
    else:
        print(f"│  {C_BOLD}Will change{C_RESET}")
        width = max(len(name) for name, _ in rows)
        for name, summary in rows:
            print(f"│    {C_DIM}{name.ljust(width)}{C_RESET}  {summary}")
    print("│")
    print(f"│  {C_DIM}Keeps wiki pages, raw/, and overview body.{C_RESET}")
    print("└")
    print()


def run_settings_restore(
    repo_root: Path,
    target: str = "",
    *,
    dry_run: bool = False,
    non_interactive: bool = False,
    confirmed: bool = False,
    stock_use_case: bool = False,
) -> bool:
    """Restore selected wiki.toml personalization. Returns False if cancelled."""
    target = (target or "").strip().lower()

    if not target and not non_interactive and is_tty():
        sel = run_menu(
            "Which user settings?",
            options=[
                (
                    "upkeep",
                    "Upkeep text",
                    "stock triggers + instructions (keep use case & posture)",
                    True,
                ),
                (
                    "identity",
                    "Org identity",
                    "name, short_name, description (keep use case)",
                    False,
                ),
                (
                    "all",
                    "All settings (this use case)",
                    "identity + selective pack + default rules — keeps use_case",
                    False,
                ),
                (
                    "factory",
                    "Factory defaults",
                    "use_case=company + company packs + empty rules (fresh checkout)",
                    False,
                ),
            ],
            title="wiki reset · user settings",
            single_select=True,
        )
        target = sel.strip().lower()
        print()  # separate menu chrome (tty) from the preview (stdout)

    display_target = target
    # factory ≡ all + force company use_case (same as --use-case-stock)
    if target == "factory":
        target = "all"
        stock_use_case = True
        display_target = "factory"
    elif stock_use_case and target == "all":
        display_target = "factory"

    if target not in ("upkeep", "identity", "all"):
        print("wiki reset settings: choose a target.", file=sys.stderr)
        print("  wiki reset settings upkeep     # stock triggers + instructions", file=sys.stderr)
        print("  wiki reset settings identity   # name / short_name / description", file=sys.stderr)
        print("  wiki reset settings all        # identity + upkeep + default rules (keeps use_case)", file=sys.stderr)
        print("  wiki reset settings factory    # company use_case + factory packs (fresh checkout)", file=sys.stderr)
        print("  add --dry-run to preview; -y to confirm non-interactively.", file=sys.stderr)
        print("  page delete remains: wiki reset full|scope|orphans", file=sys.stderr)
        raise SystemExit(2)

    toml_path = repo_root / "wiki.toml"
    if not toml_path.is_file():
        print("wiki reset settings: no wiki.toml found. Run `wiki init` first.", file=sys.stderr)
        raise SystemExit(2)

    existing = _load_existing_manifest(toml_path)
    before = _current_snapshot(existing, repo_root)
    after = _planned_snapshot(before, target, repo_root, stock_use_case=stock_use_case)
    rows = _preview_rows(before, after)
    if display_target == "factory" and not rows:
        rows.append(("generated defaults", "refresh stock pointer + indexes"))

    _print_preview(
        display_target,
        target,
        rows,
        dry_run=dry_run,
        stock_use_case=stock_use_case,
    )

    apply_token = display_target if display_target in RESTORE_TARGETS else target

    if not rows:
        print(f"{S_CHECK_GREEN} Nothing to restore.")
        return True

    if dry_run:
        print(f"{C_DIM}Dry run only — wiki.toml not modified.{C_RESET}")
        print(f"Apply:  {C_CYAN}wiki reset settings {apply_token} -y{C_RESET}")
        return True

    if not confirmed:
        if not non_interactive and is_tty():
            confirm_prompt = (
                "Write factory defaults (use_case=company) to wiki.toml?"
                if stock_use_case and target == "all"
                else "Write these stock defaults to wiki.toml?"
            )
            confirmed = run_confirm(
                confirm_prompt,
                default=False,
                title="wiki reset · user settings",
                confirm_label="write stock defaults",
                cancel_label="keep my settings",
            )
            if not confirmed:
                print("Cancelled — nothing changed.")
                return False
        if not confirmed:
            print(
                f"wiki reset settings: needs confirmation.\n"
                f"  preview:  wiki reset settings {apply_token} --dry-run\n"
                f"  apply:    wiki reset settings {apply_token} -y",
                file=sys.stderr,
            )
            raise SystemExit(2)

    write_wiki_toml(
        toml_path,
        org_name=str(after["name"]),
        org_short=str(after["short_name"]),
        org_desc=str(after["description"]),
        use_case=str(after["use_case"]),
        agent_rules=after["agent_rules"],
        company_rel_path=str(after["company_rel_path"]),
        proactivity=str(after["proactivity"]),
        triggers=after["triggers"],
        instructions=str(after["instructions"]),
    )

    _update_pointer_templates(
        repo_root,
        str(after["name"]),
        str(after["short_name"]),
        str(after["use_case"]),
        after["agent_rules"],
        upkeep_triggers=after["triggers"],
        upkeep_instructions=str(after["instructions"]),
        upkeep_proactivity=str(after["proactivity"]),
    )

    wiki_dir = repo_root / "wiki"
    if wiki_dir.is_dir():
        db = WikiDatabase(wiki_dir)
        generate_index(db, wiki_dir)
        generate_backlinks(db, wiki_dir)
        generate_tags(db, wiki_dir)
        generate_registry(repo_root)

    label = TARGET_LABELS.get(display_target, display_target)
    print()
    print(f"{S_CHECK_GREEN} Restored {C_BOLD}{label}{C_RESET} → {C_CYAN}wiki.toml{C_RESET}")
    print(f"   {C_DIM}pointer updated · pages untouched{C_RESET}")
    print()
    print(f"   Edit anytime   {C_CYAN}wiki.toml{C_RESET}  [upkeep]")
    print(f"   Check          {C_CYAN}wiki status{C_RESET}")
    print(f"   Pages only     {C_CYAN}wiki reset full|scope|orphans{C_RESET}")
    return True
