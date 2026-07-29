"""Multi-agent installer module with grouped visual output."""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

from ..ui.menu import run_menu
from .integrations import (
    AGENT_REGISTRY,
    SUPPORTED_AGENTS,
    _set_codex_features_hooks,
    _set_codex_writable_root,
    _strip_codex_wiki_hooks,
    _strip_json_wiki_hooks,
    add_json_list,
    antigravity_import_line,
    antigravity_permission_rules,
    atomic_write_json,
    backup_path,
    claude_desktop_server_config,
    ensure_antigravity_import,
    get_claude_desktop_config_path,
    get_detection_path,
    integration_state,
    link_repo_artifact,
    record_owned_values,
)

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_ORANGE = "\033[38;5;208m"
C_RED = "\033[31m"

S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"
S_TRIANGLE_ORANGE = f"{C_ORANGE}▲{C_RESET}"
S_DOT_ORANGE = f"{C_ORANGE}●{C_RESET}"
S_CROSS_RED = f"{C_RED}✕{C_RESET}"


def run_install(repo_root: Path, targets: list[str], non_interactive: bool = False) -> bool:
    """Executes installation for specified agent targets."""
    home = Path.home()
    if targets and "all" in targets:
        selected_targets = list(SUPPORTED_AGENTS)
    elif targets:
        selected_targets = [t.lower() for t in targets if t.lower() in SUPPORTED_AGENTS]
    elif non_interactive:
        selected_targets = list(SUPPORTED_AGENTS)
    else:
        # Interactive TTY menu selection
        options = []
        agent_meta = [(spec.id, spec.name) for spec in AGENT_REGISTRY.values()]
        for agent, name in agent_meta:
            state = integration_state(agent, home, repo_root)
            is_active = state == "active"
            if is_active:
                hint = f"{C_GREEN}✓ active{C_RESET}"
                selected = True
            elif state == "stale":
                hint = f"{C_ORANGE}▲ stale{C_RESET}"
                selected = True
            else:
                detected = get_detection_path(agent, home).exists()
                hint = "detected" if detected else "not configured"
                selected = detected
            options.append((agent, name, hint, selected, is_active))

        sel_str = run_menu("Which agent integrations do you want to configure?", options)
        selected_targets = sel_str.split() if sel_str else []

    if not selected_targets:
        print("No integrations selected.")
        return True

    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    source_wiki = repo_root / "bin" / "wiki"
    target_link = local_bin / "wiki"
    link_existed = target_link.exists() or target_link.is_symlink()
    success = True

    print(f"┌  {C_BOLD}Brian Wiki Setup{C_RESET}")
    print("│")
    print(f"│  repo: {repo_root}")
    print("│")

    # 1. Link bin/wiki to ~/.local/bin/wiki
    print(f"│  CLI Binary on PATH ({local_bin})")
    try:
        if link_repo_artifact(source_wiki, target_link, repo_root):
            print(f"│    {S_CHECK_GREEN} linked wiki CLI → {target_link}")
        else:
            success = False
            print(f"│    {S_CROSS_RED} preserved existing non-wiki path at {target_link}")
    except OSError as e:
        print(f"│    {S_CROSS_RED} failed to link wiki CLI: {e}")
        success = False
    print("│")

    hook_script = str(source_wiki)

    # 2. Configure selected agents
    for agent in selected_targets:
        if agent == "claude":
            c_dir = home / ".claude"
            c_dir.mkdir(parents=True, exist_ok=True)
            settings_path = c_dir / "settings.json"
            settings_existed = settings_path.is_file()

            hook_cmd = f"{hook_script} hook session-start"
            print("│  Claude Code (~/.claude)")

            try:
                settings_data = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}
                if not isinstance(settings_data, dict):
                    raise TypeError("top-level value must be an object")
                groups = settings_data.setdefault("hooks", {}).setdefault("SessionStart", [])
                if not isinstance(groups, list):
                    raise TypeError("hooks.SessionStart must be an array")
                kept, replaced = _strip_json_wiki_hooks(groups)
                kept.append({"matcher": "*", "hooks": [{"type": "command", "command": hook_cmd}]})
                settings_data["hooks"]["SessionStart"] = kept
                added_access = add_json_list(
                    settings_data, ("permissions", "additionalDirectories"), [str(repo_root.resolve())]
                )
            except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid ~/.claude/settings.json: {e}")
                success = False
                print("│")
                continue

            if settings_path.is_file():
                shutil.copy2(settings_path, backup_path(settings_path))
            settings_path.write_text(json.dumps(settings_data, indent=2), encoding="utf-8")
            record_owned_values(home, "claude", "permissions.additionalDirectories", added_access)
            if not settings_existed:
                record_owned_values(home, "claude", "createdFiles", [str(settings_path)])
            verb = f"replaced {replaced} stale" if replaced else "added"
            print(f"│    {S_CHECK_GREEN} {verb} SessionStart hook in ~/.claude/settings.json")
            artifacts = [
                (repo_root / "internal/skills/wiki-context", c_dir / "skills/wiki-context"),
                *(
                    (source, c_dir / "commands" / source.name)
                    for source in sorted((repo_root / "commands").glob("wiki-*.md"))
                ),
            ]
            for source, target in artifacts:
                if not link_repo_artifact(source, target, repo_root):
                    success = False
                    print(f"│    {S_CROSS_RED} preserved existing non-wiki path at {target}")
            print("│")

        elif agent == "claude-desktop":
            c_desktop_config = get_claude_desktop_config_path(home)
            print(f"│  Claude Desktop App ({c_desktop_config})")

            try:
                server_config = claude_desktop_server_config(repo_root)
                config_existed = c_desktop_config.is_file()
                data = json.loads(c_desktop_config.read_text(encoding="utf-8")) if c_desktop_config.is_file() else {}
                if not isinstance(data, dict):
                    raise TypeError("top-level value must be an object")
                mcp_servers = data.setdefault("mcpServers", {})
                if not isinstance(mcp_servers, dict):
                    raise TypeError("mcpServers must be an object")

                if mcp_servers.get("brian-wiki") != server_config:
                    mcp_servers["brian-wiki"] = server_config
                    atomic_write_json(c_desktop_config, data)
            except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid {c_desktop_config}: {e}")
                success = False
                print("│")
                continue

            record_owned_values(home, "claude-desktop", "mcpServers", ["brian-wiki"])
            if not config_existed:
                record_owned_values(home, "claude-desktop", "createdFiles", [str(c_desktop_config)])
            print(f"│    {S_CHECK_GREEN} configured brian-wiki MCP server in {c_desktop_config}")
            print("│")

        elif agent == "codex":
            codex_dir = home / ".codex"
            codex_dir.mkdir(parents=True, exist_ok=True)
            config_toml = codex_dir / "config.toml"
            config_existed = config_toml.is_file()

            print("│  Codex CLI (~/.codex)")
            try:
                existing_text = config_toml.read_text(encoding="utf-8") if config_toml.is_file() else ""
                tomllib.loads(existing_text) if existing_text.strip() else None
            except (tomllib.TOMLDecodeError, OSError) as e:
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid ~/.codex/config.toml: {e}")
                success = False
                print("│")
                continue

            # Codex's documented shape is an array of tables with a NESTED hooks array — a bare
            # `command` under [[hooks.SessionStart]] is not the schema Codex reads.
            hook_block = (
                "\n# Brian wiki knowledge base — injects situated company context at session start.\n"
                "[[hooks.SessionStart]]\n"
                'matcher = "startup|resume|clear|compact"\n'
                "\n[[hooks.SessionStart.hooks]]\n"
                'type = "command"\n'
                f"command = '{hook_script} hook session-start'\n"
                'statusMessage = "Loading wiki context"\n'
            )

            # Drop any hook block we previously owned before re-adding. The old guard was
            # `if hook_script not in existing_text`, and `…/bin/wiki` is a SUBSTRING of a stale
            # `…/bin/wiki-wake-up.sh` line — so an upgrade concluded "already installed", changed
            # nothing, and reported success while every session got no context at all.
            try:
                new_text = _strip_codex_wiki_hooks(existing_text)
                new_text = _set_codex_features_hooks(new_text)
                new_text = _set_codex_writable_root(new_text, repo_root)
                new_text = new_text.rstrip("\n") + "\n" + hook_block
                tomllib.loads(new_text)
                if config_toml.is_file():
                    shutil.copy2(config_toml, backup_path(config_toml))
                config_toml.write_text(new_text, encoding="utf-8")
                if not config_existed:
                    record_owned_values(home, "codex", "createdFiles", [str(config_toml)])
                print(f"│    {S_CHECK_GREEN} updated ~/.codex/config.toml (validated TOML)")
            except (tomllib.TOMLDecodeError, OSError, TypeError) as e:
                print(f"│    {S_CROSS_RED} failed to update ~/.codex/config.toml (TOML validation failed: {e})")
                success = False
            if not link_repo_artifact(
                repo_root / "internal/skills/wiki-context", codex_dir / "skills/wiki-context", repo_root
            ):
                success = False
                print(f"│    {S_CROSS_RED} preserved existing non-wiki path at ~/.codex/skills/wiki-context")
            print("│")

        elif agent == "gemini":
            g_dir = home / ".gemini"
            g_dir.mkdir(parents=True, exist_ok=True)
            gsettings = g_dir / "settings.json"
            settings_existed = gsettings.is_file()

            hook_cmd = f"{hook_script} hook session-start"
            print("│  Gemini CLI (~/.gemini)")

            try:
                gdata = json.loads(gsettings.read_text(encoding="utf-8")) if gsettings.is_file() else {}
                if not isinstance(gdata, dict):
                    raise TypeError("top-level value must be an object")
                ggroups = gdata.setdefault("hooks", {}).setdefault("SessionStart", [])
                if not isinstance(ggroups, list):
                    raise TypeError("hooks.SessionStart must be an array")
                gkept, greplaced = _strip_json_wiki_hooks(ggroups)
                gkept.append(
                    {"hooks": [{"name": "brian-wiki", "type": "command", "command": hook_cmd, "timeout": 10000}]}
                )
                gdata["hooks"]["SessionStart"] = gkept
                root = str(repo_root.resolve())
                context_added = add_json_list(gdata, ("context", "includeDirectories"), [root])
                sandbox_added = add_json_list(gdata, ("tools", "sandboxAllowedPaths"), [root])
            except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid ~/.gemini/settings.json: {e}")
                success = False
                print("│")
                continue

            if gsettings.is_file():
                shutil.copy2(gsettings, backup_path(gsettings))
            gsettings.write_text(json.dumps(gdata, indent=2), encoding="utf-8")
            record_owned_values(home, "gemini", "context.includeDirectories", context_added)
            record_owned_values(home, "gemini", "tools.sandboxAllowedPaths", sandbox_added)
            if not settings_existed:
                record_owned_values(home, "gemini", "createdFiles", [str(gsettings)])
            gverb = f"replaced {greplaced} stale" if greplaced else "added"
            print(f"│    {S_CHECK_GREEN} {gverb} SessionStart hook in ~/.gemini/settings.json")
            if not link_repo_artifact(
                repo_root / "internal/skills/wiki-context", g_dir / "skills/wiki-context", repo_root
            ):
                success = False
                print(f"│    {S_CROSS_RED} preserved existing non-wiki path at ~/.gemini/skills/wiki-context")
            print("│")

        elif agent == "copilot":
            copilot_dir = home / ".copilot"
            copilot_dir.mkdir(parents=True, exist_ok=True)
            instructions_file = copilot_dir / "copilot-instructions.md"

            print("│  GitHub Copilot CLI (~/.copilot)")
            pointer_src = repo_root / "_templates" / "agent-pointer.md"
            if pointer_src.is_file():
                pointer_text = pointer_src.read_text(encoding="utf-8")
                marker_start = "<!-- brian-wiki:start -->"
                marker_end = "<!-- brian-wiki:end -->"
                block = f"\n{marker_start}\n{pointer_text}\n{marker_end}\n"

                existing = instructions_file.read_text(encoding="utf-8") if instructions_file.is_file() else ""
                if marker_start not in existing:
                    instructions_existed = instructions_file.is_file()
                    if instructions_file.is_file():
                        shutil.copy2(instructions_file, backup_path(instructions_file))
                    instructions_file.write_text(existing + block, encoding="utf-8")
                    if not instructions_existed:
                        record_owned_values(home, "copilot", "createdFiles", [str(instructions_file)])
                    print(f"│    {S_CHECK_GREEN} added instructions to ~/.copilot/copilot-instructions.md")
                else:
                    print(f"│    {S_CHECK_GREEN} instructions already present in ~/.copilot/copilot-instructions.md")
                print(f'│    {S_DOT_ORANGE} write access is per session: copilot --add-dir="{repo_root.resolve()}"')
            print("│")

        elif agent == "skills":
            skills_dir = home / ".agents" / "skills" / "wiki-context"
            skills_dir.parent.mkdir(parents=True, exist_ok=True)

            print("│  Cursor & VS Code (~/.agents/skills)")
            skill_src = repo_root / "internal" / "skills" / "wiki-context"
            if skill_src.is_dir():
                if link_repo_artifact(skill_src, skills_dir, repo_root):
                    print(f"│    {S_CHECK_GREEN} linked skill → {skills_dir}")
                else:
                    success = False
                    print(f"│    {S_CROSS_RED} preserved existing non-wiki path at {skills_dir}")
            cursor_config = home / ".cursor/cli-config.json"
            try:
                cursor_existed = cursor_config.is_file()
                cursor_data = json.loads(cursor_config.read_text()) if cursor_config.is_file() else {}
                root = str(repo_root.resolve())
                added = add_json_list(cursor_data, ("permissions", "allow"), [f"Read({root}/**)", f"Write({root}/**)"])
                cursor_config.parent.mkdir(parents=True, exist_ok=True)
                cursor_config.write_text(json.dumps(cursor_data, indent=2), encoding="utf-8")
                record_owned_values(home, "skills", "permissions.allow", added)
                if not cursor_existed:
                    record_owned_values(home, "skills", "createdFiles", [str(cursor_config)])
            except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                success = False
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid ~/.cursor/cli-config.json: {e}")
            print(f"│    {S_DOT_ORANGE} VS Code write access remains workspace/profile scoped")
            print("│")

        elif agent == "antigravity":
            gemini_md = home / ".gemini" / "GEMINI.md"
            gemini_md.parent.mkdir(parents=True, exist_ok=True)
            gemini_md_existed = gemini_md.is_file()

            print("│  Google Antigravity (~/.gemini/GEMINI.md)")
            import_line = antigravity_import_line(repo_root)

            existing = gemini_md.read_text(encoding="utf-8") if gemini_md.is_file() else ""
            updated, changed = ensure_antigravity_import(existing, import_line)
            if changed:
                if gemini_md.is_file():
                    shutil.copy2(gemini_md, backup_path(gemini_md))
                gemini_md.write_text(updated, encoding="utf-8")
                if not gemini_md_existed:
                    record_owned_values(home, "antigravity", "createdFiles", [str(gemini_md)])
                print(f"│    {S_CHECK_GREEN} configured import → ~/.gemini/GEMINI.md")
            else:
                print(f"│    {S_CHECK_GREEN} import line already present in ~/.gemini/GEMINI.md")
            agy_settings = home / ".gemini/antigravity-cli/settings.json"
            try:
                agy_settings_existed = agy_settings.is_file()
                agy_data = json.loads(agy_settings.read_text()) if agy_settings.is_file() else {}
                added = add_json_list(agy_data, ("permissions", "allow"), antigravity_permission_rules(repo_root))
                if added or not agy_settings_existed:
                    atomic_write_json(agy_settings, agy_data, create_backup=agy_settings_existed)
                record_owned_values(home, "antigravity", "permissions.allow", added)
                if not agy_settings_existed:
                    record_owned_values(home, "antigravity", "createdFiles", [str(agy_settings)])
            except (AttributeError, OSError, TypeError, json.JSONDecodeError) as e:
                success = False
                print(f"│    {S_CROSS_RED} preserved unreadable or invalid Antigravity CLI settings: {e}")
            print(f"│    {S_DOT_ORANGE} add the wiki folder to an Antigravity IDE project for IDE write access")
            print("│")

    active_selected = any(integration_state(agent, home, repo_root) == "active" for agent in selected_targets)
    if not success and not active_selected and not link_existed and target_link.is_symlink():
        target_link.unlink()

    if success:
        print(f"└  {C_BOLD}Done. Start a new session in each configured agent to load context.{C_RESET}")
    else:
        print(f"└  {C_BOLD}Incomplete. Existing files were preserved; review the errors above.{C_RESET}")
    return success
