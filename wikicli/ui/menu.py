"""TTY-aware Vercel/Clack-style terminal multi-select menu renderer for wiki install/uninstall."""

from __future__ import annotations

import json
import os
import select
import sys
from collections.abc import Sequence
from typing import Any

# ANSI escape sequences
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"

C_BLUE = "\033[38;5;39m"

S_RAIL = f"{C_DIM}│{C_RESET}"
S_TOP = f"{C_DIM}┌{C_RESET}"
S_BOT = f"{C_DIM}└{C_RESET}"
S_STEP_SUBMIT = f"{C_GREEN}◇{C_RESET}"
S_STEP_CANCEL = f"{C_RED}■{C_RESET}"
S_RADIO_BLUE = f"{C_BLUE}●{C_RESET}"
S_RADIO_GREEN = f"{C_GREEN}●{C_RESET}"
S_RADIO_INACTIVE = f"{C_DIM}○{C_RESET}"


def is_tty() -> bool:
    """Returns True if running in an interactive terminal TTY environment."""
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
        res = os.isatty(fd)
        os.close(fd)
        return res
    except OSError:
        return False


def read_key(tty_fd: int) -> str:
    """Read a single keypress or escape sequence from tty_fd."""
    import termios
    import tty

    old_settings = termios.tcgetattr(tty_fd)
    try:
        tty.setraw(tty_fd)
        ch = os.read(tty_fd, 1).decode("utf-8", errors="ignore")
        if ch == "\x1b":
            r, _, _ = select.select([tty_fd], [], [], 0.05)
            if r:
                ch2 = os.read(tty_fd, 1).decode("utf-8", errors="ignore")
                if ch2 == "[":
                    r2, _, _ = select.select([tty_fd], [], [], 0.05)
                    if r2:
                        ch3 = os.read(tty_fd, 1).decode("utf-8", errors="ignore")
                        if ch3 == "A":
                            return "UP"
                        if ch3 == "B":
                            return "DOWN"
                        if ch3 == "C":
                            return "RIGHT"
                        if ch3 == "D":
                            return "LEFT"
                        if ch3 in ("5", "6"):
                            r3, _, _ = select.select([tty_fd], [], [], 0.05)
                            if r3:
                                ch4 = os.read(tty_fd, 1).decode("utf-8", errors="ignore")
                                if ch4 == "~":
                                    return "PAGE_UP" if ch3 == "5" else "PAGE_DOWN"
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == " ":
            return "SPACE"
        if ch in ("\x03", "\x04"):
            return "CANCEL"
        return ch
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_settings)


def run_scroll_viewer(
    header: str,
    items: Sequence[str],
    max_visible: int = 20,
    title: str = "Wiki Reset",
    non_interactive: bool = False,
) -> None:
    """Renders an interactive scrollable list box for stdout items via /dev/tty."""
    if not items:
        return

    is_interactive = not non_interactive
    tty_fd = None
    tty_out = None

    if is_interactive:
        try:
            tty_fd = os.open("/dev/tty", os.O_RDWR)
            if os.isatty(tty_fd):
                tty_out = open("/dev/tty", "w")  # noqa: SIM115
            else:
                is_interactive = False
        except OSError:
            is_interactive = False

    # Non-interactive or small list fallback
    if not is_interactive or tty_fd is None or tty_out is None or len(items) <= max_visible:
        print(f"│  {header}")
        visible_count = min(len(items), max_visible) if not is_interactive else len(items)
        for item in items[:visible_count]:
            print(f"│    {item}")
        if len(items) > visible_count:
            remaining = len(items) - visible_count
            print(f"│    {C_DIM}... and {remaining} more files{C_RESET}")
        print("│")
        return

    scroll_offset = 0
    max_offset = max(0, len(items) - max_visible)
    last_rendered_lines = 0

    def render(submit_state: str | None = None):
        nonlocal last_rendered_lines
        lines = []

        if submit_state == "submit":
            lines.append(f"{S_STEP_SUBMIT}  {C_BOLD}{header}{C_RESET} {C_DIM}({len(items)} files total){C_RESET}")
            lines.append(f"{S_RAIL}")
        else:
            lines.append(f"{S_TOP}  {C_BOLD}{title}{C_RESET}")
            lines.append(f"{S_RAIL}")
            lines.append(f"{S_RAIL}  {C_BOLD}{header}{C_RESET}")
            lines.append(f"{S_RAIL}  {C_DIM}(↑↓ / PgUp PgDn scroll, enter to continue){C_RESET}")
            lines.append(f"{S_RAIL}")

            if scroll_offset > 0:
                lines.append(f"{S_RAIL}  {C_DIM}▲ ({scroll_offset} more above){C_RESET}")

            visible_slice = items[scroll_offset : scroll_offset + max_visible]
            for item in visible_slice:
                lines.append(f"{S_RAIL}    {item}")

            remaining_below = len(items) - (scroll_offset + len(visible_slice))
            if remaining_below > 0:
                lines.append(f"{S_RAIL}  {C_DIM}▼ ({remaining_below} more below){C_RESET}")

            lines.append(f"{S_BOT}")

        clear_seq = f"\033[{last_rendered_lines}A\033[J" if last_rendered_lines > 0 else ""
        tty_out.write(clear_seq + "\n".join(lines) + "\n")
        tty_out.flush()
        last_rendered_lines = len(lines)

    # Hide cursor
    tty_out.write("\033[?25l")
    tty_out.flush()

    try:
        render()
        while True:
            key = read_key(tty_fd)

            if key == "UP":
                if scroll_offset > 0:
                    scroll_offset -= 1
                    render()
            elif key == "DOWN":
                if scroll_offset < max_offset:
                    scroll_offset += 1
                    render()
            elif key == "PAGE_UP":
                if scroll_offset > 0:
                    scroll_offset = max(0, scroll_offset - max_visible)
                    render()
            elif key == "PAGE_DOWN":
                if scroll_offset < max_offset:
                    scroll_offset = min(max_offset, scroll_offset + max_visible)
                    render()
            elif key in ("ENTER", "SPACE", "q", "Q", "ESC", "CANCEL"):
                render(submit_state="submit")
                break
    finally:
        tty_out.write("\033[?25h")
        tty_out.flush()
        tty_out.close()
        os.close(tty_fd)


def run_confirm(
    prompt: str,
    default: bool = False,
    title: str = "Wiki Setup",
    confirm_label: str = "proceed with setup",
    cancel_label: str = "cancel setup",
    non_interactive: bool = False,
) -> bool:
    """Renders an interactive confirmation prompt (Yes/No) with default choice."""
    if non_interactive or not is_tty():
        return default
    options = [
        ("no", "No", cancel_label, not default),
        ("yes", "Yes", confirm_label, default),
    ]
    res = run_menu(prompt, options=options, title=title, single_select=True)
    return res == "yes"


def run_menu(
    prompt_or_json: str,
    options: Sequence[tuple[Any, ...]] | None = None,
    title: str = "Wiki Setup",
    non_interactive: bool = False,
    single_select: bool = False,
) -> str:
    """Renders interactive menu via /dev/tty and outputs selected item IDs as space-separated string."""
    if options is not None:
        prompt = prompt_or_json
        subtitle = ""
        items: list[dict[str, Any]] = [
            {
                "id": str(o[0]),
                "label": str(o[1]),
                "hint": str(o[2]) if len(o) > 2 else "",
                "selected": bool(o[3]) if len(o) > 3 else False,
                "is_active": bool(o[4]) if len(o) > 4 else False,
            }
            for o in options
        ]
    else:
        try:
            data = json.loads(prompt_or_json)
            title = data.get("title", title)
            subtitle = data.get("subtitle", "")
            prompt = data.get("prompt", "Select options:")
            items = data.get("items", [])
            if "single_select" in data:
                single_select = bool(data["single_select"])
        except (json.JSONDecodeError, TypeError):
            prompt = prompt_or_json
            subtitle = ""
            items = []

    if not items:
        return ""

    if single_select:
        sel_idx = next((i for i, item in enumerate(items) if item.get("selected")), 0)
        cursor = sel_idx
        for i, item in enumerate(items):
            item["selected"] = i == cursor
    else:
        cursor = 0

    is_interactive = not non_interactive
    tty_fd = None
    tty_out = None

    if is_interactive:
        try:
            tty_fd = os.open("/dev/tty", os.O_RDWR)
            if os.isatty(tty_fd):
                # Deliberately not a context manager: this handle must outlive the block and stay
                # open for the whole interactive render loop. It is closed in the finally below.
                tty_out = open("/dev/tty", "w")  # noqa: SIM115
            else:
                is_interactive = False
        except OSError:
            is_interactive = False

    # Non-interactive / fallback behavior
    if not is_interactive or tty_fd is None or tty_out is None:
        selected_ids = [item["id"] for item in items if item.get("selected", False)]
        if not selected_ids and not single_select:
            selected_ids = [item["id"] for item in items]
        elif not selected_ids and single_select and items:
            selected_ids = [items[cursor]["id"]]
        return " ".join(selected_ids)

    last_rendered_lines = 0

    def render(submit_state: str | None = None):
        nonlocal last_rendered_lines
        lines = []

        if submit_state == "submit":
            selected_labels = [item["label"] for item in items if item.get("selected", False)]
            summary = ", ".join(selected_labels) if selected_labels else "(none)"
            lines.append(f"{S_STEP_SUBMIT}  {C_BOLD}{prompt}{C_RESET} {C_CYAN}{summary}{C_RESET}")
            lines.append(f"{S_RAIL}")
        elif submit_state == "cancel":
            lines.append(f"{S_STEP_CANCEL}  {C_BOLD}{prompt}{C_RESET} {C_DIM}Cancelled{C_RESET}")
            lines.append(f"{S_RAIL}")
        else:
            lines.append(f"{S_TOP}  {C_BOLD}{title}{C_RESET}")
            if subtitle:
                lines.append(f"{S_RAIL}  {C_DIM}{subtitle}{C_RESET}")
            lines.append(f"{S_RAIL}")
            lines.append(f"{S_RAIL}  {prompt}")
            if single_select:
                lines.append(f"{S_RAIL}  {C_DIM}(↑↓ move, enter select){C_RESET}")
            else:
                lines.append(f"{S_RAIL}  {C_DIM}(↑↓ move, space select, a toggle all, enter confirm){C_RESET}")
            lines.append(f"{S_RAIL}")

            for i, item in enumerate(items):
                is_cursor = i == cursor
                is_selected = item.get("selected", False)
                is_active = item.get("is_active", False)

                if is_selected:
                    radio = S_RADIO_BLUE if is_active else S_RADIO_GREEN
                else:
                    radio = S_RADIO_INACTIVE

                prefix = f"{C_CYAN}❯{C_RESET}" if is_cursor else " "
                label = f"{C_BOLD}{item['label']}{C_RESET}" if is_cursor else item["label"]
                hint = f" {C_DIM}({item['hint']}){C_RESET}" if item.get("hint") else ""

                lines.append(f"{S_RAIL} {prefix} {radio} {label}{hint}")

            lines.append(f"{S_BOT}")

        # Clear previous frame using relative line moves
        clear_seq = f"\033[{last_rendered_lines}A\033[J" if last_rendered_lines > 0 else ""
        tty_out.write(clear_seq + "\n".join(lines) + "\n")
        tty_out.flush()
        last_rendered_lines = len(lines)

    # Hide cursor
    tty_out.write("\033[?25l")
    tty_out.flush()

    try:
        render()
        while True:
            key = read_key(tty_fd)

            if key == "UP":
                cursor = (cursor - 1) % len(items)
                if single_select:
                    for i, item in enumerate(items):
                        item["selected"] = i == cursor
                render()
            elif key == "DOWN":
                cursor = (cursor + 1) % len(items)
                if single_select:
                    for i, item in enumerate(items):
                        item["selected"] = i == cursor
                render()
            elif single_select and key in ("y", "Y"):
                for idx, item in enumerate(items):
                    if item["id"] in ("yes", "y"):
                        cursor = idx
                        break
                for i, item in enumerate(items):
                    item["selected"] = i == cursor
                render()
            elif single_select and key in ("n", "N"):
                for idx, item in enumerate(items):
                    if item["id"] in ("no", "n"):
                        cursor = idx
                        break
                for i, item in enumerate(items):
                    item["selected"] = i == cursor
                render()
            elif not single_select and key == "SPACE":
                items[cursor]["selected"] = not items[cursor].get("selected", False)
                render()
            elif not single_select and key in ("a", "A"):
                all_sel = all(item.get("selected", False) for item in items)
                for item in items:
                    item["selected"] = not all_sel
                render()
            elif key == "ENTER":
                if single_select:
                    for i, item in enumerate(items):
                        item["selected"] = i == cursor
                render(submit_state="submit")
                selected_ids = [item["id"] for item in items if item.get("selected", False)]
                break
            elif key in ("ESC", "CANCEL", "q", "Q"):
                render(submit_state="cancel")
                sys.exit(1)
    finally:
        # Restore cursor
        tty_out.write("\033[?25h")
        tty_out.flush()
        tty_out.close()
        os.close(tty_fd)

    return " ".join(selected_ids)
