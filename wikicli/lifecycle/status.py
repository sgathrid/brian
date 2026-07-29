"""Agent integration status and health verification module."""

from __future__ import annotations

import time
from pathlib import Path

from ..core.config import WikiConfig
from .brief import PROACTIVITY_LABELS
from .integrations import AGENT_REGISTRY, SUPPORTED_AGENTS, integration_state
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
    agent_id: (spec.status_heading, spec.active_msg, spec.absent_msg)
    for agent_id, spec in AGENT_REGISTRY.items()
}


def _agent_behavior_lines(repo_root: Path) -> list[str]:
    """Short 'what agents will do' card from wiki.toml."""
    cfg = WikiConfig(repo_root)
    key = (cfg.upkeep_proactivity or "selective").strip().lower()
    if key not in PROACTIVITY_LABELS:
        key = "selective"
    n_triggers = len([t for t in cfg.upkeep_triggers if str(t).strip()])
    labels: list[str] = []
    if cfg.agent_rules:
        catalog = load_agent_rule_catalog()
        for rid in cfg.agent_rules:
            meta = catalog.get(rid) if isinstance(catalog, dict) else None
            if isinstance(meta, dict) and isinstance(meta.get("label"), str):
                labels.append(meta["label"])
            else:
                labels.append(rid)
    rules = ", ".join(labels) if labels else "none"
    return [
        "What agents will do",
        f"  proactivity: {key}",
        f"  rules: {rules}",
        f"  triggers: {n_triggers}",
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

    agent_states = [
        (agent, integration_state(agent, home, repo_root)) for agent in SUPPORTED_AGENTS
    ]

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
        if idx < len(sorted_agents) - 1:
            print("│")

    print("│")
    print(
        f"└  {C_BOLD}Done. {active_count}/{len(SUPPORTED_AGENTS)} agent integrations active.{C_RESET}"
    )
