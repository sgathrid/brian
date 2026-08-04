"""Agent integration status and health verification module."""

from __future__ import annotations

import time
from pathlib import Path

from ..core.config import WikiConfig
from .integrations import AGENT_REGISTRY, SUPPORTED_AGENTS, gemini_trust_decision, integration_state
from .personalization import load_agent_rule_catalog
from .sync import get_sync_status

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_ORANGE = "\033[38;5;208m"
C_RED = "\033[31m"

S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"
S_TRIANGLE_ORANGE = f"{C_ORANGE}▲{C_RESET}"
S_CIRCLE_DIM = f"{C_DIM}○{C_RESET}"
S_CROSS_RED = f"{C_RED}✕{C_RESET}"

AGENT_STATUS = {
    agent_id: (spec.status_heading, spec.active_msg, spec.absent_msg) for agent_id, spec in AGENT_REGISTRY.items()
}


def _agent_behavior_lines(repo_root: Path) -> list[str]:
    """Compact new-session upkeep summary from wiki.toml.

    Mirrors session-start honesty: only catalog-resolved rules count as active,
    and proactivity is shown as its configured label.
    """
    cfg = WikiConfig(repo_root)
    proactivity = (cfg.upkeep_proactivity or "").strip().lower() or "(unset)"

    n_triggers = len([t for t in cfg.upkeep_triggers if str(t).strip()])
    trigger_summary = f"{n_triggers} trigger{'s' if n_triggers != 1 else ''}"

    if not cfg.agent_rules:
        rule_summary = "no additional rules"
    else:
        catalog = load_agent_rule_catalog()
        if not catalog:
            # Same gate as format_rules_block: empty catalog ⇒ nothing injected.
            rule_summary = "additional rules unavailable"
        else:
            labels: list[str] = []
            for rid in cfg.agent_rules:
                meta = catalog.get(rid) if isinstance(catalog, dict) else None
                if isinstance(meta, dict) and isinstance(meta.get("label"), str) and meta["label"].strip():
                    labels.append(meta["label"].strip())
            n_rules = len(labels)
            rule_summary = (
                f"{n_rules} additional rule{'s' if n_rules != 1 else ''}"
                if n_rules
                else "no additional rules"
            )

    return [
        "Agent upkeep for new sessions",
        f"    {proactivity} · {trigger_summary} · {rule_summary}",
        (
            f"    {C_DIM}TIP: Edit wiki.toml, run `wiki status`, then start a new session.{C_RESET}"
        ),
    ]


def run_status(repo_root: Path) -> None:
    """Report the shared CLI separately and count only active agent integrations."""
    home = Path.home()
    local_bin = home / ".local" / "bin" / "wiki"
    source_wiki = repo_root / "bin" / "wiki"
    cfg = WikiConfig(repo_root)
    title = f"{cfg.short_name} Agent Status"

    print(f"┌  {C_BOLD}{title}{C_RESET}")
    print("│")
    print(f"│  repo: {repo_root}")
    print("│")
    sync = get_sync_status(repo_root)
    age = ""
    if sync.checked_at is not None:
        age_minutes = max(0, int((time.time() - sync.checked_at) // 60))
        age = f"; checked {age_minutes}m ago"
    marker = S_CHECK_GREEN if sync.fresh is True else S_TRIANGLE_ORANGE
    print("│  Knowledge Freshness")
    print(f"│    {marker} {sync.detail}{age}")
    print("│")
    for line in _agent_behavior_lines(repo_root):
        print(f"│  {line}" if not line.startswith("  ") else f"│{line}")
    print("│")
    print("│  CLI Binary on PATH")
    if local_bin.is_symlink() and local_bin.resolve() == source_wiki.resolve():
        print(f"│    {S_CHECK_GREEN} linked → {local_bin}")
    elif local_bin.exists() or local_bin.is_symlink():
        print(f"│    {S_CROSS_RED} path exists but is not linked to this repo")
    else:
        print(f"│    {S_CIRCLE_DIM} not linked in ~/.local/bin")
    print("│")

    agent_states = [(agent, integration_state(agent, home, repo_root)) for agent in SUPPORTED_AGENTS]

    state_rank = {"active": 0, "stale": 1, "absent": 2}
    sorted_agents = sorted(agent_states, key=lambda item: state_rank.get(item[1], 2))

    active_count = 0
    for idx, (agent, state) in enumerate(sorted_agents):
        heading, active_message, absent_message = AGENT_STATUS[agent]
        print(f"│  {heading}")
        if state == "active":
            print(f"│    {S_CHECK_GREEN} {active_message}")
            active_count += 1
        elif state == "stale":
            print(
                f"│    {S_TRIANGLE_ORANGE} stale or incomplete wiki integration; "
                f"run `wiki uninstall {agent}` or `wiki install {agent}`"
            )
        else:
            print(f"│    {S_CIRCLE_DIM} {absent_message}")
        # Shown whether or not Gemini is configured: a trust rule blocks it here either way, and
        # gemini_trust_decision is already silent on machines with no rule covering this repo.
        if agent == "gemini":
            trust_decision, blocking_rule = gemini_trust_decision(repo_root, home)
            if blocking_rule:
                # gemini-cli 0.53 starts in restricted mode rather than exiting, and skips the hooks
                # from settings, so no wiki context loads here.
                print(f"│    {S_TRIANGLE_ORANGE} Gemini runs restricted in this folder: untrusted via {blocking_rule}")
                # This is the standing reminder for a folder the installer no longer asks about, so
                # the reversal stays visible instead of the integration failing silently.
                if trust_decision == "declined":
                    print("│      you declined trust for this folder, so `wiki install` stopped asking")
                    print("│      ask again with `wiki install gemini --ask-trust`")
                elif trust_decision == "gemini":
                    print("│      this exact folder is marked DO_NOT_TRUST in Gemini's own trust file")
                print("│      allow it with `wiki install gemini --trust-folder`, or add this line")
                print(f'│      to ~/.gemini/trustedFolders.json:  "{repo_root.resolve()}": "TRUST_FOLDER"')
        if idx < len(sorted_agents) - 1:
            print("│")

    print("│")
    print(f"└  {C_BOLD}Done. {active_count}/{len(SUPPORTED_AGENTS)} agent integrations active.{C_RESET}")
