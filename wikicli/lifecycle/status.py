"""Agent integration status and health verification module."""

from __future__ import annotations

import time
from pathlib import Path

from .integrations import AGENT_REGISTRY, SUPPORTED_AGENTS, integration_state
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


def run_status(repo_root: Path) -> None:
    """Report the shared CLI separately and count only active agent integrations."""
    home = Path.home()
    local_bin = home / ".local" / "bin" / "wiki"
    source_wiki = repo_root / "bin" / "wiki"

    print(f"┌  {C_BOLD}Brian Wiki Agent Status{C_RESET}")
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
                f"│    {S_TRIANGLE_ORANGE} stale wiki hook configuration; run `wiki uninstall {agent}` or `wiki install {agent}`"
            )
        else:
            print(f"│    {S_CIRCLE_DIM} {absent_message}")
        if idx < len(sorted_agents) - 1:
            print("│")

    print("│")
    print(f"└  {C_BOLD}Done. {active_count}/{len(SUPPORTED_AGENTS)} agent integrations active.{C_RESET}")
