"""Multi-agent uninstaller module with dry-run and backup purge options."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

from ..ui.menu import run_menu
from .integrations import (
    AGENT_REGISTRY,
    SUPPORTED_AGENTS,
    _restore_codex_features_hooks,
    _restore_codex_writable_root,
    _strip_codex_wiki_hooks,
    _strip_json_wiki_hooks,
    antigravity_import_line,
    atomic_write_json,
    backup_path,
    clear_owned_values,
    get_claude_desktop_config_path,
    integration_state,
    is_repo_symlink,
    load_install_state,
    remove_antigravity_import,
    remove_json_list,
)

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_ORANGE = "\033[38;5;208m"
C_RED = "\033[31m"

S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"
S_DOT_RED = f"{C_RED}●{C_RESET}"
S_CIRCLE_DIM = f"{C_DIM}○{C_RESET}"
S_CROSS_RED = f"{C_RED}✕{C_RESET}"


def _is_agent_installed(agent: str, home: Path, repo_root: Path) -> bool:
    """Include stale owned configuration so interactive uninstall can repair it."""
    return integration_state(agent, home, repo_root) != "absent"


def _remove_json_wiki_hooks(settings_path: Path, dry_run: bool) -> int:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        hooks = data.get("hooks", {}).get("SessionStart", [])
    except (AttributeError, OSError, json.JSONDecodeError):
        return 0
    if not isinstance(hooks, list):
        return 0

    kept, removed = _strip_json_wiki_hooks(hooks)
    if removed and not dry_run:
        shutil.copy2(settings_path, backup_path(settings_path))
        if kept:
            data["hooks"]["SessionStart"] = kept
        else:
            data["hooks"].pop("SessionStart", None)
            if not data["hooks"]:
                data.pop("hooks")
        settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return removed


def _remove_owned_json_settings(
    path: Path, owned: dict[str, list[str]], settings: dict[str, tuple[str, ...]], dry_run: bool
) -> bool:
    if not owned or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    changed = False
    for name, values in owned.items():
        if name in settings:
            changed = remove_json_list(data, settings[name], values) or changed
    if changed and not dry_run:
        shutil.copy2(path, backup_path(path))
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changed


def _remove_repo_links(paths: list[Path], repo_root: Path, dry_run: bool) -> int:
    owned = [path for path in paths if is_repo_symlink(path, repo_root)]
    if not dry_run:
        for path in owned:
            path.unlink()
    return len(owned)


def _remove_created_file_if_empty(path: Path, owned: dict[str, list[str]], dry_run: bool) -> None:
    """Remove a now-empty config only when this installer created the file."""
    if dry_run or str(path) not in owned.get("createdFiles", []) or not path.is_file():
        return
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        def empty(value: object) -> bool:
            if isinstance(value, dict):
                return all(empty(item) for item in value.values())
            return isinstance(value, list) and not value

        if not empty(data):
            return
    elif path.read_text(encoding="utf-8").strip():
        return
    path.unlink()


def run_uninstall(
    repo_root: Path,
    targets: list[str],
    dry_run: bool = False,
    purge_backups: bool = False,
    non_interactive: bool = False,
) -> None:
    """Executes uninstallation for specified agent targets."""
    home = Path.home()
    local_bin = home / ".local" / "bin"
    target_link = local_bin / "wiki"

    if targets and "all" in targets:
        selected_targets = list(SUPPORTED_AGENTS)
    elif targets:
        selected_targets = [t.lower() for t in targets if t.lower() in SUPPORTED_AGENTS]
    elif non_interactive:
        selected_targets = [a for a in SUPPORTED_AGENTS if _is_agent_installed(a, home, repo_root)]
    else:
        # Interactive TTY menu selection — pre-select only active or stale integrations
        options = []
        agent_names = [(spec.id, spec.name) for spec in AGENT_REGISTRY.values()]
        for agent, name in agent_names:
            state = integration_state(agent, home, repo_root)
            if state == "active":
                hint = f"{C_GREEN}✓ active{C_RESET}"
            elif state == "stale":
                hint = f"{C_ORANGE}▲ stale{C_RESET}"
            else:
                hint = "not configured"
            options.append((agent, name, hint, state != "absent"))

        sel_str = run_menu("Which agent integrations do you want to uninstall?", options)
        selected_targets = sel_str.split() if sel_str else []

    if not selected_targets:
        print("No integrations selected for removal.")
        return

    mode_label = " (DRY RUN — PREVIEW ONLY, NO CHANGES MADE)" if dry_run else ""
    print(f"┌  {C_BOLD}Brian Wiki Uninstall{mode_label}{C_RESET}")
    print("│")
    print(f"│  repo: {repo_root}")
    print("│")

    prefix = "[dry run] would remove" if dry_run else "removed"
    install_state = load_install_state(home)

    # Process selected agents
    for agent in selected_targets:
        if agent == "claude":
            settings_path = home / ".claude" / "settings.json"
            print("│  Claude Code (~/.claude)")
            removed = _remove_json_wiki_hooks(settings_path, dry_run)
            access_removed = _remove_owned_json_settings(
                settings_path,
                install_state.get("claude", {}),
                {"permissions.additionalDirectories": ("permissions", "additionalDirectories")},
                dry_run,
            )
            links = _remove_repo_links(
                [home / ".claude/skills/wiki-context", *sorted((home / ".claude/commands").glob("wiki-*.md"))],
                repo_root,
                dry_run,
            )
            if removed:
                print(f"│    {S_DOT_RED} {prefix} {removed} SessionStart hook(s) from ~/.claude/settings.json")
            else:
                print(f"│    {S_CIRCLE_DIM} no wiki hooks found in ~/.claude/settings.json")
            if access_removed or links:
                print(f"│    {S_DOT_RED} {prefix} owned access and {links} artifact link(s)")
            if not dry_run:
                _remove_created_file_if_empty(settings_path, install_state.get("claude", {}), dry_run)
                clear_owned_values(home, "claude")
            print("│")

        elif agent == "claude-desktop":
            c_desktop_config = get_claude_desktop_config_path(home)
            print(f"│  Claude Desktop App ({c_desktop_config})")
            if c_desktop_config.is_file():
                try:
                    data = json.loads(c_desktop_config.read_text(encoding="utf-8"))
                    mcp_servers = data.get("mcpServers", {})
                    if isinstance(mcp_servers, dict) and "brian-wiki" in mcp_servers:
                        mcp_servers.pop("brian-wiki")
                        if not dry_run:
                            created = str(c_desktop_config) in install_state.get("claude-desktop", {}).get(
                                "createdFiles", []
                            )
                            if created and data == {"mcpServers": {}}:
                                c_desktop_config.unlink()
                            else:
                                atomic_write_json(c_desktop_config, data, create_backup=False)
                        print(f"│    {S_DOT_RED} {prefix} brian-wiki MCP server from {c_desktop_config}")
                    else:
                        print(f"│    {S_CIRCLE_DIM} no brian-wiki MCP server found in {c_desktop_config}")
                except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                    print(f"│    {S_CROSS_RED} failed to process {c_desktop_config}: {e}")
            else:
                print(f"│    {S_CIRCLE_DIM} no config file found at {c_desktop_config}")

            if not dry_run:
                clear_owned_values(home, "claude-desktop")
            print("│")

        elif agent == "codex":
            config_toml = home / ".codex" / "config.toml"
            print("│  Codex CLI (~/.codex)")
            if config_toml.is_file():
                try:
                    text = config_toml.read_text(encoding="utf-8")
                    new_text = _restore_codex_writable_root(
                        _restore_codex_features_hooks(_strip_codex_wiki_hooks(text)), repo_root
                    )
                    if new_text != text:
                        # Validate TOML before modifying
                        tomllib.loads(new_text)
                        if not dry_run:
                            shutil.copy2(config_toml, backup_path(config_toml))
                            config_toml.write_text(new_text, encoding="utf-8")
                        print(f"│    {S_DOT_RED} {prefix} wiki hook configuration from ~/.codex/config.toml")
                    else:
                        print(f"│    {S_CIRCLE_DIM} no wiki configuration found in ~/.codex/config.toml")
                except (tomllib.TOMLDecodeError, OSError) as e:
                    print(f"│    {S_CROSS_RED} failed to process ~/.codex/config.toml: {e}")
            else:
                print(f"│    {S_CIRCLE_DIM} no wiki configuration found in ~/.codex/config.toml")
            links = _remove_repo_links([home / ".codex/skills/wiki-context"], repo_root, dry_run)
            if links:
                print(f"│    {S_DOT_RED} {prefix} {links} skill link(s)")
            if not dry_run:
                _remove_created_file_if_empty(config_toml, install_state.get("codex", {}), dry_run)
                clear_owned_values(home, "codex")
            print("│")

        elif agent == "gemini":
            gsettings = home / ".gemini" / "settings.json"
            print("│  Gemini CLI (~/.gemini)")
            removed = _remove_json_wiki_hooks(gsettings, dry_run)
            access_removed = _remove_owned_json_settings(
                gsettings,
                install_state.get("gemini", {}),
                {
                    "context.includeDirectories": ("context", "includeDirectories"),
                    "tools.sandboxAllowedPaths": ("tools", "sandboxAllowedPaths"),
                },
                dry_run,
            )
            links = _remove_repo_links([home / ".gemini/skills/wiki-context"], repo_root, dry_run)
            if removed:
                print(f"│    {S_DOT_RED} {prefix} {removed} SessionStart hook(s) from ~/.gemini/settings.json")
            else:
                print(f"│    {S_CIRCLE_DIM} no wiki hooks found in ~/.gemini/settings.json")
            if access_removed or links:
                print(f"│    {S_DOT_RED} {prefix} owned access and {links} skill link(s)")
            if not dry_run:
                _remove_created_file_if_empty(gsettings, install_state.get("gemini", {}), dry_run)
                clear_owned_values(home, "gemini")
            print("│")

        elif agent == "copilot":
            instructions_file = home / ".copilot" / "copilot-instructions.md"
            print("│  GitHub Copilot CLI (~/.copilot)")
            if instructions_file.is_file():
                text = instructions_file.read_text(encoding="utf-8")
                marker_start = "<!-- brian-wiki:start -->"
                marker_end = "<!-- brian-wiki:end -->"
                if marker_start in text and marker_end in text:
                    before = text.split(marker_start)[0]
                    after = text.split(marker_end)[1]
                    new_text = (before.rstrip() + "\n" + after.lstrip()).strip() + "\n"
                    if not dry_run:
                        shutil.copy2(instructions_file, backup_path(instructions_file))
                        if new_text.strip():
                            instructions_file.write_text(new_text, encoding="utf-8")
                        else:
                            instructions_file.unlink()
                    print(f"│    {S_DOT_RED} {prefix} instruction block from ~/.copilot/copilot-instructions.md")
                else:
                    print(f"│    {S_CIRCLE_DIM} no wiki instruction block found in ~/.copilot/copilot-instructions.md")
            else:
                print(f"│    {S_CIRCLE_DIM} no wiki instruction block found in ~/.copilot/copilot-instructions.md")
            if not dry_run:
                _remove_created_file_if_empty(instructions_file, install_state.get("copilot", {}), dry_run)
                clear_owned_values(home, "copilot")
            print("│")

        elif agent == "skills":
            skills_dir = home / ".agents" / "skills" / "wiki-context"
            print("│  Cursor & VS Code (~/.agents/skills)")
            if integration_state("skills", home, repo_root) == "active":
                if not dry_run:
                    skills_dir.unlink()
                print(f"│    {S_DOT_RED} {prefix} skill symlink at {skills_dir}")
            else:
                print(f"│    {S_CIRCLE_DIM} no skill symlink found at {skills_dir}")
            cursor_config = home / ".cursor/cli-config.json"
            if _remove_owned_json_settings(
                cursor_config,
                install_state.get("skills", {}),
                {"permissions.allow": ("permissions", "allow")},
                dry_run,
            ):
                print(f"│    {S_DOT_RED} {prefix} owned Cursor CLI permission rules")
            if not dry_run:
                _remove_created_file_if_empty(cursor_config, install_state.get("skills", {}), dry_run)
                clear_owned_values(home, "skills")
            print("│")

        elif agent == "antigravity":
            gemini_md = home / ".gemini" / "GEMINI.md"
            print("│  Google Antigravity (~/.gemini/GEMINI.md)")
            if gemini_md.is_file():
                text = gemini_md.read_text(encoding="utf-8")
                import_line = antigravity_import_line(repo_root)
                updated, removed = remove_antigravity_import(text, import_line)
                if removed:
                    if not dry_run:
                        shutil.copy2(gemini_md, backup_path(gemini_md))
                        gemini_md.write_text(updated, encoding="utf-8")
                    print(f"│    {S_DOT_RED} {prefix} @import line from ~/.gemini/GEMINI.md")
                else:
                    print(f"│    {S_CIRCLE_DIM} no wiki @import line found in ~/.gemini/GEMINI.md")
            else:
                print(f"│    {S_CIRCLE_DIM} no wiki @import line found in ~/.gemini/GEMINI.md")
            agy_settings = home / ".gemini/antigravity-cli/settings.json"
            if _remove_owned_json_settings(
                agy_settings,
                install_state.get("antigravity", {}),
                {"permissions.allow": ("permissions", "allow")},
                dry_run,
            ):
                print(f"│    {S_DOT_RED} {prefix} owned Antigravity CLI permission rules")
            if not dry_run:
                owned = install_state.get("antigravity", {})
                _remove_created_file_if_empty(gemini_md, owned, dry_run)
                _remove_created_file_if_empty(agy_settings, owned, dry_run)
                clear_owned_values(home, "antigravity")
            print("│")

    # The CLI is shared: remove it only after the last integration is gone.
    remaining = any(integration_state(agent, home, repo_root) != "absent" for agent in SUPPORTED_AGENTS)
    if not remaining:
        print("│  CLI Binary on PATH")
        source_wiki = (repo_root / "bin" / "wiki").resolve()
        if target_link.is_symlink() and target_link.resolve() == source_wiki:
            if not dry_run:
                target_link.unlink()
            print(f"│    {S_DOT_RED} {prefix} wiki binary symlink at {target_link}")
        else:
            print(f"│    {S_CIRCLE_DIM} no binary symlink found at {target_link}")
        print("│")

    # Purge backup files if requested
    if purge_backups and not dry_run:
        print("│  Purging backup files...")
        backups = [
            backup_path(path)
            for path in (
                home / ".claude/settings.json",
                get_claude_desktop_config_path(home),
                home / ".codex/config.toml",
                home / ".gemini/settings.json",
                home / ".copilot/copilot-instructions.md",
                home / ".cursor/cli-config.json",
                home / ".gemini/GEMINI.md",
                home / ".gemini/antigravity-cli/settings.json",
            )
        ]
        for b in backups:
            if b.is_file():
                b.unlink()
                print(f"│    {S_CHECK_GREEN} removed backup: {b}")
        print("│")

    if dry_run:
        print(f"└  {C_BOLD}Done. (Dry run mode — no files or settings were modified){C_RESET}")
    else:
        print(f"└  {C_BOLD}Done. Start a new session in each configured agent to load context.{C_RESET}")
