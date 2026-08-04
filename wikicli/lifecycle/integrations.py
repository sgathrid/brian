from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    status_heading: str
    active_msg: str
    absent_msg: str
    get_config_path: Callable[[Path], Path]


def get_claude_desktop_config_path(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        roaming = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return roaming / "Claude" / "claude_desktop_config.json"
    # Claude Desktop is not currently distributed for Linux. Retain the conventional location so
    # status/uninstall can clean configurations created by earlier versions of this installer.
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def get_detection_path(agent: str, home: Path) -> Path:
    """Return the application directory used by the interactive installer."""
    directories = {
        "claude": home / ".claude",
        "claude-desktop": get_claude_desktop_config_path(home).parent,
        "codex": home / ".codex",
        "gemini": home / ".gemini",
        "copilot": home / ".copilot",
        "skills": home / ".agents" / "skills",
        "antigravity": home / ".gemini",
    }
    return directories.get(agent, AGENT_REGISTRY[agent].get_config_path(home))


def claude_desktop_server_config(repo_root: Path) -> dict[str, object]:
    """Build the complete launch configuration shared by install and status."""
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv is required to install the Claude Desktop MCP server")
    root = repo_root.resolve()
    server = (root / "internal" / "mcp_server_wiki.py").resolve()
    return {
        "command": str(Path(uv).resolve()),
        "args": ["run", "--project", str(root), "--no-dev", "python", str(server)],
        "env": {"WIKI_ROOT": str(root)},
    }


AGENT_SPECS: list[AgentSpec] = [
    AgentSpec(
        id="claude",
        name="Claude Code",
        status_heading="Claude Code (~/.claude)",
        active_msg="SessionStart hook configured in ~/.claude/settings.json",
        absent_msg="not configured in ~/.claude/settings.json",
        get_config_path=lambda home: home / ".claude" / "settings.json",
    ),
    AgentSpec(
        id="claude-desktop",
        name="Claude Desktop App",
        status_heading="Claude Desktop App",
        active_msg="brian-wiki MCP server configured in claude_desktop_config.json",
        absent_msg="brian-wiki MCP server not found in claude_desktop_config.json",
        get_config_path=get_claude_desktop_config_path,
    ),
    AgentSpec(
        id="codex",
        name="Codex CLI",
        status_heading="Codex CLI (~/.codex)",
        active_msg="hook configured and enabled in ~/.codex/config.toml",
        absent_msg="not configured in ~/.codex/config.toml",
        get_config_path=lambda home: home / ".codex" / "config.toml",
    ),
    AgentSpec(
        id="gemini",
        name="Gemini CLI",
        status_heading="Gemini CLI (~/.gemini)",
        active_msg="SessionStart hook configured in ~/.gemini/settings.json",
        absent_msg="not configured in ~/.gemini/settings.json",
        get_config_path=lambda home: home / ".gemini" / "settings.json",
    ),
    AgentSpec(
        id="copilot",
        name="GitHub Copilot CLI",
        status_heading="GitHub Copilot CLI (~/.copilot)",
        active_msg="instruction block present in ~/.copilot/copilot-instructions.md",
        absent_msg="instruction block not found in ~/.copilot/copilot-instructions.md",
        get_config_path=lambda home: home / ".copilot" / "copilot-instructions.md",
    ),
    AgentSpec(
        id="skills",
        name="Cursor & VS Code",
        status_heading="Cursor & VS Code (~/.agents/skills)",
        active_msg="skill symlink present in ~/.agents/skills",
        absent_msg="skill symlink not found in ~/.agents/skills",
        get_config_path=lambda home: home / ".agents" / "skills" / "wiki-context",
    ),
    AgentSpec(
        id="antigravity",
        name="Google Antigravity",
        status_heading="Google Antigravity (~/.gemini/GEMINI.md)",
        active_msg="import and read/write permissions configured",
        absent_msg="import and read/write permissions not configured",
        get_config_path=lambda home: home / ".gemini" / "GEMINI.md",
    ),
]

AGENT_REGISTRY: dict[str, AgentSpec] = {spec.id: spec for spec in AGENT_SPECS}
SUPPORTED_AGENTS = [spec.id for spec in AGENT_SPECS]


def backup_path(path: Path) -> Path:
    """Return the installer-owned rollback path without claiming generic user backups."""
    return path.with_name(path.name + ".brian-wiki.backup")


def atomic_write_json(path: Path, data: Any, create_backup: bool = True, indent: int = 2) -> None:
    """Safely write JSON data using a temporary file and optional snapshot backup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if create_backup and path.is_file():
        shutil.copy2(path, backup_path(path))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.brian-wiki.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=indent) + "\n")
        Path(temporary).replace(path)
    except (OSError, TypeError):
        Path(temporary).unlink(missing_ok=True)
        raise


# Current and retired commands. These exact markers let upgrades remove their own stale entries
# without claiming unrelated settings that merely mention the word "wiki".
WIKI_HOOK_MARKERS = ("wiki-wake-up.sh", "wiki hook session-start", "wiki-wake-up")

_CODEX_RESTORE_FALSE = "# brian-wiki: restore to false on uninstall"
_CODEX_REMOVE = "# brian-wiki: remove on uninstall"
_CODEX_WRITABLE_ROOT = "# brian-wiki: remove wiki root on uninstall"
_CODEX_HOOK_BLOCK = re.compile(
    r"(?:^[ \t]*#[^\n]*\n)*^\[\[?hooks\.SessionStart(?:\.[A-Za-z0-9_-]+)*\]\]?"
    r".*?(?=^\[\[?hooks\.SessionStart\]\]?[ \t]*(?:#.*)?$|"
    r"^\[(?!\[?hooks\.SessionStart\.)[^\n]*\][ \t]*(?:#.*)?$|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _is_wiki_hook_text(text: str) -> bool:
    return any(marker in text for marker in WIKI_HOOK_MARKERS)


def _is_wiki_hook(entry: object) -> bool:
    """True when a JSON hook group/entry is owned by this tool, including retired forms."""
    return _is_wiki_hook_text(json.dumps(entry))


def _strip_json_wiki_hooks(groups: list[object]) -> tuple[list[object], int]:
    """Remove owned commands from JSON hook groups without dropping foreign siblings."""
    kept_groups: list[object] = []
    removed = 0
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            if _is_wiki_hook(group):
                removed += 1
            else:
                kept_groups.append(group)
            continue

        hooks = group["hooks"]
        kept_hooks = [hook for hook in hooks if not _is_wiki_hook(hook)]
        removed += len(hooks) - len(kept_hooks)
        if kept_hooks:
            kept_groups.append({**group, "hooks": kept_hooks})
        elif not _is_wiki_hook(group):
            kept_groups.append(group)
    return kept_groups, removed


def _codex_wiki_blocks(text: str) -> list[re.Match[str]]:
    return [match for match in _CODEX_HOOK_BLOCK.finditer(text) if _is_wiki_hook_text(match.group(0))]


def _strip_codex_wiki_hooks(text: str) -> str:
    """Remove owned Codex hook blocks while preserving adjacent foreign SessionStart entries."""
    blocks = _codex_wiki_blocks(text)
    for match in reversed(blocks):
        text = text[: match.start()] + text[match.end() :]
    return re.sub(r"\n{3,}", "\n\n", text) if blocks else text


def _set_codex_features_hooks(text: str) -> str:
    """Enable Codex hooks and record the exact reversal required by uninstall."""
    features = re.search(r"^\[features\].*?(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if not features:
        return text.rstrip("\n") + f"\n\n[features]\nhooks = true  {_CODEX_REMOVE}\n"

    block = features.group(0)
    existing = re.search(r"^hooks\s*=.*$", block, re.MULTILINE)
    if existing:
        line = existing.group(0)
        if "brian-wiki:" in line or re.match(r"^hooks\s*=\s*true", line.strip()):
            return text
        new_block = re.sub(
            r"^hooks\s*=.*$", f"hooks = true  {_CODEX_RESTORE_FALSE}", block, count=1, flags=re.MULTILINE
        )
    else:
        new_block = block.rstrip("\n") + f"\nhooks = true  {_CODEX_REMOVE}\n"
    return text.replace(block, new_block, 1)


def _restore_codex_features_hooks(text: str) -> str:
    """Reverse only the feature flag change recorded by this installer."""
    restore = re.compile(rf"^hooks\s*=.*{re.escape(_CODEX_RESTORE_FALSE)}.*$", re.MULTILINE)
    remove = re.compile(rf"^hooks\s*=.*{re.escape(_CODEX_REMOVE)}.*\n?", re.MULTILINE)
    if restore.search(text):
        return restore.sub("hooks = false", text, count=1)
    if remove.search(text):
        text = remove.sub("", text, count=1)
        return re.sub(r"^\[features\][ \t]*\n(?=\s*(?:\[|\Z))", "", text, count=1, flags=re.MULTILINE)
    return text


def _set_codex_writable_root(text: str, repo_root: Path) -> str:
    """Add the documented Codex writable root, marking only values we own."""
    data = tomllib.loads(text) if text.strip() else {}
    roots = data.get("sandbox_workspace_write", {}).get("writable_roots", [])
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise TypeError("sandbox_workspace_write.writable_roots must be an array of strings")
    root = str(repo_root.resolve())
    if root in roots:
        return text

    line = f"writable_roots = {json.dumps([*roots, root])}  {_CODEX_WRITABLE_ROOT}"
    section = re.search(r"^\[sandbox_workspace_write\].*?(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        return text.rstrip("\n") + f"\n\n[sandbox_workspace_write]\n{line}\n"

    block = section.group(0)
    existing = re.search(r"^writable_roots\s*=\s*\[[^]]*\].*$", block, re.MULTILINE)
    new_block = (
        block[: existing.start()] + line + block[existing.end() :] if existing else block.rstrip("\n") + f"\n{line}\n"
    )
    return text[: section.start()] + new_block + text[section.end() :]


def _restore_codex_writable_root(text: str, repo_root: Path) -> str:
    """Remove the wiki root only when this installer marked the writable-roots assignment."""
    pattern = re.compile(rf"^writable_roots\s*=\s*\[[^]]*\].*{re.escape(_CODEX_WRITABLE_ROOT)}.*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return text
    roots = tomllib.loads(text).get("sandbox_workspace_write", {}).get("writable_roots", [])
    remaining = [root for root in roots if root != str(repo_root.resolve())]
    if remaining:
        replacement = f"writable_roots = {json.dumps(remaining)}"
    else:
        replacement = ""
    text = text[: match.start()] + replacement + text[match.end() :]
    return re.sub(r"^\[sandbox_workspace_write\][ \t]*\n(?=\s*(?:\[|\Z))", "", text, count=1, flags=re.MULTILINE)


def is_repo_symlink(path: Path, repo_root: Path) -> bool:
    """True only for symlinks whose resolved target lives in this checkout."""
    try:
        return path.is_symlink() and path.resolve().is_relative_to(repo_root.resolve())
    except OSError:
        return False


def link_repo_artifact(source: Path, target: Path, repo_root: Path) -> bool:
    """Create or refresh an owned link without replacing real or foreign paths."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if not is_repo_symlink(target, repo_root):
            return False
        target.unlink()
    elif target.exists():
        return False
    target.symlink_to(source)
    return True


def install_state_path(home: Path) -> Path:
    return home / ".local" / "state" / "brian-wiki" / "install.json"


def load_install_state(home: Path) -> dict[str, dict[str, list[str]]]:
    try:
        data = json.loads(install_state_path(home).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def record_owned_values(home: Path, agent: str, setting: str, values: list[str]) -> None:
    """Persist ownership only for list entries that this install actually appended."""
    if not values:
        return
    state = load_install_state(home)
    owned = state.setdefault(agent, {}).setdefault(setting, [])
    owned.extend(value for value in values if value not in owned)
    path = install_state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def clear_owned_values(home: Path, agent: str) -> dict[str, list[str]]:
    """Return and forget the entries owned by one integration."""
    state = load_install_state(home)
    owned = state.pop(agent, {})
    path = install_state_path(home)
    if state:
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return owned


def forget_owned_setting(home: Path, agent: str, setting: str) -> list[str]:
    """Return and forget the entries owned for one setting, leaving other settings intact."""
    state = load_install_state(home)
    owned = state.get(agent, {}).pop(setting, [])
    if not state.get(agent):
        state.pop(agent, None)
    path = install_state_path(home)
    if state:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return owned


def forget_owned_value(home: Path, agent: str, setting: str, value: str) -> bool:
    """Forget one recorded entry, leaving the other entries for that setting intact.

    The state file is shared by every checkout on the machine, so a decision recorded for this repo
    must be dropped by value: `forget_owned_setting` would discard another checkout's entry too.
    """
    state = load_install_state(home)
    owned = state.get(agent, {}).get(setting)
    if not isinstance(owned, list) or value not in owned:
        return False
    remaining = [entry for entry in owned if entry != value]
    if remaining:
        state[agent][setting] = remaining
    else:
        state[agent].pop(setting, None)
        if not state[agent]:
            state.pop(agent, None)
    path = install_state_path(home)
    if state:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return True


def discard_json_list(data: dict, keys: tuple[str, ...], values: list[str]) -> list[str]:
    """Remove strings from an existing nested JSON list and return only the entries dropped."""
    parent = data
    for key in keys[:-1]:
        child = parent.get(key)
        if not isinstance(child, dict):
            return []
        parent = child
    current = parent.get(keys[-1])
    if not isinstance(current, list):
        return []
    removed = [value for value in values if value in current]
    parent[keys[-1]] = [value for value in current if value not in removed]
    return removed


def _normalize_trust_path(path: Path | str) -> str:
    """Normalize a path the way gemini-cli compares trust rules: realpath, case-folded per platform."""
    resolved = os.path.realpath(str(path))
    return resolved.lower() if sys.platform in ("darwin", "win32") else resolved


def gemini_folder_trust(repo_root: Path, home: Path) -> tuple[bool | None, str | None]:
    """Resolve Gemini folder trust for a path, returning (trust, deciding rule).

    Mirrors `isPathTrusted` in gemini-cli 0.53: every rule whose (parent, for TRUST_PARENT)
    directory contains the path is a candidate, and the longest rule key decides. `None`
    means no rule matched, so Gemini prompts on first use.
    """
    try:
        rules = json.loads((home / ".gemini" / "trustedFolders.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(rules, dict):
        return None, None

    target = _normalize_trust_path(repo_root)
    winner: tuple[str, str] | None = None
    for rule_path, trust_level in rules.items():
        if not isinstance(rule_path, str) or trust_level not in ("TRUST_FOLDER", "TRUST_PARENT", "DO_NOT_TRUST"):
            continue
        scope = _normalize_trust_path(Path(rule_path).parent if trust_level == "TRUST_PARENT" else rule_path)
        contains = target == scope or target.startswith(scope.rstrip(os.sep) + os.sep)
        if contains and (winner is None or len(rule_path) > len(winner[0])):
            winner = (rule_path, trust_level)
    if winner is None:
        return None, None
    return winner[1] != "DO_NOT_TRUST", winner[0]


def prunable_dirs(home: Path) -> list[Path]:
    """Directories this installer creates for its own artifacts, in child-before-parent order.

    Never includes a directory an agent owns (`~/.claude`, `~/.gemini`, ...): those stay even when
    empty. Uninstall removes only the entries it recorded as created, and only while empty.
    """
    return [
        home / ".claude/commands",
        home / ".claude/skills",
        home / ".codex/skills",
        home / ".gemini/skills",
        home / ".gemini/antigravity-cli",
        home / ".agents/skills",
        home / ".local/state/brian-wiki",
    ]


def gemini_trust_advice(repo_root: Path, home: Path) -> str | None:
    """Return the rule that would stop Gemini from starting in this repo, or None when it may start.

    Mirrors `checkPathTrust` precedence in gemini-cli 0.53: the GEMINI_CLI_TRUST_WORKSPACE override
    first, then security.folderTrust.enabled (on by default), then the trust file.
    """
    if os.environ.get("GEMINI_CLI_TRUST_WORKSPACE") == "true":
        return None
    try:
        settings = json.loads((home / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}
    security = settings.get("security") if isinstance(settings, dict) else None
    folder_trust = security.get("folderTrust") if isinstance(security, dict) else None
    if isinstance(folder_trust, dict) and folder_trust.get("enabled", True) is False:
        return None
    trusted, rule = gemini_folder_trust(repo_root, home)
    return rule if trusted is False else None


TRUST_DECLINED = "trustDeclined"


def gemini_trust_decision(repo_root: Path, home: Path) -> tuple[str, str | None]:
    """Classify what to do about Gemini folder trust here, as (decision, blocking rule).

    "clear"    — nothing blocks Gemini in this folder, so there is no question to ask.
    "gemini"   — the blocking rule names this exact folder: the user already answered Gemini's own
                 trust dialog, and an installer must not re-ask what `/permissions` decided.
    "declined" — a previous run recorded a decline for this folder; advise, never prompt.
    "prompt"   — the block is inherited from a parent rule and nobody has decided for this folder.
    """
    rule = gemini_trust_advice(repo_root, home)
    if rule is None:
        return "clear", None
    if _normalize_trust_path(rule) == _normalize_trust_path(repo_root):
        return "gemini", rule
    declined = load_install_state(home).get("gemini", {}).get(TRUST_DECLINED, [])
    if isinstance(declined, list) and str(repo_root.resolve()) in declined:
        return "declined", rule
    return "prompt", rule


def gemini_trust_folder(repo_root: Path, home: Path) -> str:
    """Mark one folder TRUST_FOLDER in Gemini's trust file, preserving every other rule.

    Returns "added", "present" when the rule was already there, or "failed". Gemini keeps this
    file owner-readable only, so a file created here matches that mode.
    """
    trust_file = home / ".gemini" / "trustedFolders.json"
    key = str(repo_root.resolve())
    try:
        rules = json.loads(trust_file.read_text(encoding="utf-8")) if trust_file.is_file() else {}
        if not isinstance(rules, dict):
            return "failed"
        if rules.get(key) == "TRUST_FOLDER":
            return "present"
        rules[key] = "TRUST_FOLDER"
        trust_file.parent.mkdir(parents=True, exist_ok=True)
        existed = trust_file.is_file()
        if existed:
            shutil.copy2(trust_file, backup_path(trust_file))
        trust_file.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
        if not existed:
            trust_file.chmod(0o600)
    except (OSError, json.JSONDecodeError):
        return "failed"
    return "added"


def gemini_distrust_folder(repo_root: Path, home: Path) -> bool:
    """Drop one TRUST_FOLDER rule this installer added, leaving rules it did not write."""
    trust_file = home / ".gemini" / "trustedFolders.json"
    key = str(repo_root.resolve())
    try:
        rules = json.loads(trust_file.read_text(encoding="utf-8")) if trust_file.is_file() else {}
        if not isinstance(rules, dict) or rules.get(key) != "TRUST_FOLDER":
            return False
        del rules[key]
        trust_file.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return False
    return True


def add_json_list(data: dict, keys: tuple[str, ...], values: list[str]) -> list[str]:
    """Append unique strings at a nested JSON setting and return only new entries."""
    parent = data
    for key in keys[:-1]:
        child = parent.setdefault(key, {})
        if not isinstance(child, dict):
            raise TypeError(f"{key} must be an object")
        parent = child
    current = parent.setdefault(keys[-1], [])
    if not isinstance(current, list):
        raise TypeError(f"{'.'.join(keys)} must be an array")
    added = [value for value in values if value not in current]
    current.extend(added)
    return added


def antigravity_import_line(repo_root: Path) -> str:
    return "@import " + str(repo_root / "_templates" / "agent-pointer.md")


def antigravity_permission_rules(repo_root: Path) -> list[str]:
    root = str(repo_root.resolve())
    return [f"read_file({root})", f"write_file({root})"]


def _antigravity_pointer_state(text: str, expected: str) -> str:
    occurrences = text.count(expected)
    if occurrences == 0:
        return "absent"
    return "active" if occurrences == 1 and text.splitlines().count(expected) == 1 else "stale"


def remove_antigravity_import(text: str, expected: str) -> tuple[str, bool]:
    """Remove exact wiki imports, including the concatenated form shipped by older installers."""
    if expected not in text:
        return text, False

    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if body == expected:
            continue
        kept.append(body.replace(expected, "") + ending)
    return "".join(kept), True


def ensure_antigravity_import(text: str, expected: str) -> tuple[str, bool]:
    """Ensure one standalone import without changing surrounding agent rules."""
    if _antigravity_pointer_state(text, expected) == "active":
        return text, False
    cleaned, _ = remove_antigravity_import(text, expected)
    separator = "" if not cleaned or cleaned.endswith(("\n", "\r")) else "\n"
    return cleaned + separator + expected + "\n", True


def remove_json_list(data: dict, keys: tuple[str, ...], values: list[str]) -> bool:
    parent = data
    for key in keys[:-1]:
        child = parent.get(key)
        if not isinstance(child, dict):
            return False
        parent = child
    current = parent.get(keys[-1])
    if not isinstance(current, list):
        return False
    kept = [value for value in current if value not in values]
    if kept == current:
        return False
    if kept:
        parent[keys[-1]] = kept
    else:
        parent.pop(keys[-1])
    return True


def _json_hook_state(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "absent"
    try:
        data = json.loads(text)
        groups = data.get("hooks", {}).get("SessionStart", [])
    except (AttributeError, json.JSONDecodeError):
        return "stale" if _is_wiki_hook_text(text) else "absent"
    if isinstance(groups, list):
        for group in groups:
            if (
                isinstance(group, dict)
                and isinstance(group.get("hooks"), list)
                and any(_is_wiki_hook(hook) for hook in group["hooks"])
            ):
                return "active"
    return "stale" if _is_wiki_hook_text(text) else "absent"


def _codex_hook_state(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "absent"
    if not _codex_wiki_blocks(text):
        return "absent"
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return "stale"
    entries = data.get("hooks", {}).get("SessionStart", [])
    enabled = data.get("features", {}).get("hooks") is True
    if enabled and isinstance(entries, list) and any(_is_wiki_hook(entry) for entry in entries):
        return "active"
    return "stale"


def _claude_desktop_state(home: Path, repo_root: Path) -> str:
    path = get_claude_desktop_config_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "absent"
    try:
        data = json.loads(text)
        mcp_servers = data.get("mcpServers", {})
        if not isinstance(mcp_servers, dict):
            return "stale" if "brian-wiki" in text else "absent"
        wiki_server = mcp_servers.get("brian-wiki")
        if isinstance(wiki_server, dict):
            try:
                expected = claude_desktop_server_config(repo_root)
            except OSError:
                return "stale"
            command = wiki_server.get("command")
            if wiki_server != expected or not isinstance(command, str) or not Path(command).is_file():
                return "stale"
            server = repo_root.resolve() / "internal" / "mcp_server_wiki.py"
            return "active" if server.is_file() else "stale"
    except (AttributeError, json.JSONDecodeError, TypeError):
        return "stale" if "brian-wiki" in text else "absent"
    return "stale" if "brian-wiki" in text else "absent"


def _antigravity_permissions_state(path: Path, repo_root: Path) -> str:
    expected = set(antigravity_permission_rules(repo_root))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "absent"
    try:
        data = json.loads(text)
        allowed = data.get("permissions", {}).get("allow", [])
    except (AttributeError, json.JSONDecodeError):
        return "stale" if any(rule in text for rule in expected) else "absent"
    if not isinstance(allowed, list):
        return "absent"
    present = {rule for rule in allowed if isinstance(rule, str)}
    if expected <= present:
        return "active"
    return "stale" if expected & present else "absent"


def _antigravity_state(home: Path, repo_root: Path) -> str:
    expected_import = antigravity_import_line(repo_root)
    try:
        pointer_text = (home / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")
    except OSError:
        pointer_state = "absent"
    else:
        pointer_state = _antigravity_pointer_state(pointer_text, expected_import)
    permissions_state = _antigravity_permissions_state(
        home / ".gemini" / "antigravity-cli" / "settings.json", repo_root
    )
    if pointer_state == permissions_state == "active":
        return "active"
    if pointer_state != "absent" or permissions_state != "absent":
        return "stale"
    return "absent"


def integration_state(agent: str, home: Path, repo_root: Path) -> str:
    """Return ``active``, ``stale``, or ``absent`` using the integration's real schema."""
    if agent == "claude":
        return _json_hook_state(home / ".claude" / "settings.json")
    if agent == "claude-desktop":
        return _claude_desktop_state(home, repo_root)
    if agent == "codex":
        return _codex_hook_state(home / ".codex" / "config.toml")
    if agent == "gemini":
        return _json_hook_state(home / ".gemini" / "settings.json")
    if agent == "copilot":
        path = home / ".copilot" / "copilot-instructions.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return "absent"
        start, end = "<!-- brian-wiki:start -->", "<!-- brian-wiki:end -->"
        return "active" if start in text and end in text else ("stale" if start in text or end in text else "absent")
    if agent == "skills":
        path = home / ".agents" / "skills" / "wiki-context"
        expected = (repo_root / "internal" / "skills" / "wiki-context").resolve()
        return "active" if path.is_symlink() and path.resolve() == expected else "absent"
    if agent == "antigravity":
        return _antigravity_state(home, repo_root)
    return "absent"
