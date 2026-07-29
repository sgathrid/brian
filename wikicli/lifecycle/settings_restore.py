"""Restore wiki.toml personalization to stock defaults (Brian product only).

Does not delete wiki pages — that remains `wiki reset` (full/scope/orphans).
Natural-language triggers/instructions live in [upkeep]; this rewrites those
fields (and optionally identity / rules) from init presets.
"""

from __future__ import annotations

import sys
from pathlib import Path

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

RESTORE_TARGETS = ("upkeep", "identity", "all")


def _repo_base_name(repo_root: Path) -> str:
    return repo_root.name.replace("-", " ").replace("_", " ").title() or "Organization"


def _current_snapshot(existing: dict, repo_root: Path) -> dict[str, object]:
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
    current: dict[str, object],
    target: str,
    repo_root: Path,
    *,
    stock_use_case: bool,
) -> dict[str, object]:
    planned = dict(current)
    use_case = str(current["use_case"])
    if stock_use_case and target == "all":
        use_case = "company"
        planned["use_case"] = use_case

    preset = USE_CASE_PRESETS[use_case]
    base = _repo_base_name(repo_root)
    proactivity = str(current["proactivity"]) if str(current["proactivity"]) in ("selective", "active", "capture", "silent") else "selective"

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

    # Keep company_file path stable unless missing.
    planned["company_rel_path"] = _clean_company_rel_path(
        str(current.get("company_rel_path") or ""),
        _slugify(str(planned["name"]).replace("Knowledge Base", "").replace("Wiki", "")) + "-overview",
    )
    return planned


def _preview_lines(before: dict[str, object], after: dict[str, object]) -> list[str]:
    lines: list[str] = []
    keys = (
        ("use_case", "use_case"),
        ("name", "name"),
        ("short_name", "short_name"),
        ("description", "description"),
        ("agent_rules", "agent_rules"),
        ("proactivity", "proactivity"),
        ("triggers", "triggers"),
        ("instructions", "instructions"),
    )
    for key, label in keys:
        b, a = before.get(key), after.get(key)
        if b == a:
            continue
        if key == "triggers":
            lines.append(f"  triggers: {len(b or [])} item(s) → {len(a or [])} stock item(s)")
        elif key == "instructions":
            b_s = str(b or "").strip().replace("\n", " ")
            a_s = str(a or "").strip().replace("\n", " ")
            if len(b_s) > 60:
                b_s = b_s[:57] + "…"
            if len(a_s) > 60:
                a_s = a_s[:57] + "…"
            lines.append(f"  instructions: {b_s!r} → {a_s!r}")
        elif key == "agent_rules":
            lines.append(f"  agent_rules: {b or []} → {a or []}")
        else:
            lines.append(f"  {label}: {b!r} → {a!r}")
    if not lines:
        lines.append("  (no changes — already at target defaults)")
    return lines


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
            "Restore which settings? (does not delete wiki pages)",
            options=[
                (
                    "upkeep",
                    "Upkeep text",
                    "stock triggers + instructions for current proactivity/use case",
                    True,
                ),
                (
                    "identity",
                    "Org identity",
                    "name, short_name, description from repo + use case",
                    False,
                ),
                (
                    "all",
                    "All settings",
                    "identity + selective upkeep pack + default agent_rules",
                    False,
                ),
            ],
            title="Brian Wiki Reset",
            single_select=True,
        )
        target = sel.strip().lower()

    if target not in RESTORE_TARGETS:
        print("wiki reset settings: choose a target.", file=sys.stderr)
        print("  wiki reset settings upkeep     # stock triggers + instructions", file=sys.stderr)
        print("  wiki reset settings identity   # name / short_name / description", file=sys.stderr)
        print("  wiki reset settings all        # identity + upkeep + default rules", file=sys.stderr)
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
    preview = _preview_lines(before, after)

    print(f"┌  {C_BOLD}Brian reset · user settings{' (DRY RUN)' if dry_run else ''}{C_RESET}")
    print("│")
    print(f"│  target: {C_CYAN}{target}{C_RESET}")
    print(f"│  file:   {C_CYAN}wiki.toml{C_RESET}  {C_DIM}(natural-language [upkeep] is the source of truth){C_RESET}")
    if stock_use_case and target == "all":
        print(f"│  {C_YELLOW}also forcing use_case = company{C_RESET}")
    print("│")
    print(f"│  {C_BOLD}Planned changes:{C_RESET}")
    for line in preview:
        print(f"│{line}")
    print("│")
    print(f"│  {C_DIM}Does not delete wiki pages or raw/. Overview page body is kept.{C_RESET}")
    print("│")

    unchanged = preview == ["  (no changes — already at target defaults)"]
    if unchanged:
        print(f"└  {C_BOLD}Done.{C_RESET} Nothing to restore.")
        return True

    if not dry_run and not confirmed:
        if not non_interactive and is_tty():
            confirmed = run_confirm(
                f"Restore {target} settings to defaults?",
                default=False,
                title="Brian Wiki Reset",
                confirm_label=f"restore {target}",
                cancel_label="keep current",
            )
            if not confirmed:
                print("wiki reset settings: cancelled.", file=sys.stderr)
                return False
        if not confirmed:
            print(
                f"wiki reset settings: needs confirmation.\n"
                f"  preview:  wiki reset settings {target} --dry-run\n"
                f"  apply:    wiki reset settings {target} -y",
                file=sys.stderr,
            )
            raise SystemExit(2)

    if dry_run:
        print(f"└  {C_BOLD}Dry run only — wiki.toml not modified.{C_RESET}")
        return True

    write_wiki_toml(
        toml_path,
        org_name=str(after["name"]),
        org_short=str(after["short_name"]),
        org_desc=str(after["description"]),
        use_case=str(after["use_case"]),
        agent_rules=list(after["agent_rules"]),  # type: ignore[arg-type]
        company_rel_path=str(after["company_rel_path"]),
        proactivity=str(after["proactivity"]),
        triggers=list(after["triggers"]),  # type: ignore[arg-type]
        instructions=str(after["instructions"]),
    )

    _update_pointer_templates(
        repo_root,
        str(after["name"]),
        str(after["short_name"]),
        str(after["use_case"]),
        list(after["agent_rules"]),  # type: ignore[arg-type]
        upkeep_triggers=list(after["triggers"]),  # type: ignore[arg-type]
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

    print(f"│  {S_CHECK_GREEN} Wrote {C_CYAN}wiki.toml{C_RESET}")
    print(f"│  {S_CHECK_GREEN} Updated {C_CYAN}_templates/agent-pointer.md{C_RESET}")
    print("│")
    print(f"└  {C_BOLD}Done.{C_RESET} Restored {target} defaults.")
    print()
    print(f"   Edit anytime:  open {C_CYAN}wiki.toml{C_RESET}  ([upkeep] triggers & instructions)")
    print(f"   Verify:        {C_CYAN}wiki status{C_RESET}  · start a new agent session")
    print(f"   Pages only:    {C_CYAN}wiki reset full|scope|orphans{C_RESET}")
    return True
