"""Agent integration install/uninstall.

There were no tests here, and the cost was severe: after the bash→Python refactor, `wiki install`
printed success for all three agents while every one of them still pointed at the deleted
`bin/wiki-wake-up.sh`. Every session on the machine silently received no company context, and
re-running the installer did not repair it.

Root cause worth remembering: the guard was `if hook_script not in existing_text`, and
`…/bin/wiki` is a SUBSTRING of `…/bin/wiki-wake-up.sh`. The installer concluded it was already
installed. Substring matching has now caused four separate defects in this project.

These tests never touch the real `$HOME` — every case gets a temp home.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from wikicli.lifecycle.install import _set_codex_features_hooks, _strip_codex_wiki_hooks, run_install
from wikicli.lifecycle.integrations import (
    _is_wiki_hook,
    integration_state,
)
from wikicli.lifecycle.status import run_status
from wikicli.lifecycle.uninstall import run_uninstall

STALE_CMD = "bash /Users/gathrid/Repos/wiki/bin/wiki-wake-up.sh"


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    for sub in (".claude", ".codex", ".gemini", ".copilot", ".agents/skills", ".local/bin"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class TestHookOwnership:
    def test_recognises_current_and_legacy_hooks(self):
        assert _is_wiki_hook({"hooks": [{"command": "/x/bin/wiki hook session-start"}]})
        assert _is_wiki_hook({"hooks": [{"command": STALE_CMD}]}), "legacy entries must be recognised"

    def test_does_not_claim_foreign_hooks(self):
        assert not _is_wiki_hook({"hooks": [{"command": "/usr/local/bin/some-other-tool"}]})


class TestClaude:
    def test_installs_a_correctly_nested_group(self, fake_home: Path):
        run_install(repo_root(), ["claude"])
        groups = json.loads((fake_home / ".claude/settings.json").read_text())["hooks"]["SessionStart"]
        assert len(groups) == 1
        # Claude requires a GROUP with its own nested `hooks` array; a bare {"type","command"} at
        # group level is silently ignored, which is exactly what shipped.
        assert "hooks" in groups[0], "hook must be nested inside a group"
        assert groups[0]["hooks"][0]["command"].endswith("wiki hook session-start")

    def test_replaces_a_stale_hook_instead_of_appending(self, fake_home: Path):
        settings = fake_home / ".claude/settings.json"
        settings.write_text(
            json.dumps(
                {"hooks": {"SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": STALE_CMD}]}]}}
            ),
            encoding="utf-8",
        )
        run_install(repo_root(), ["claude"])
        groups = json.loads(settings.read_text())["hooks"]["SessionStart"]
        blob = json.dumps(groups)
        assert "wiki-wake-up.sh" not in blob, "the dead command must be removed, not left beside the new one"
        assert len(groups) == 1

    def test_is_idempotent(self, fake_home: Path):
        run_install(repo_root(), ["claude"])
        run_install(repo_root(), ["claude"])
        groups = json.loads((fake_home / ".claude/settings.json").read_text())["hooks"]["SessionStart"]
        assert len(groups) == 1, "re-running must not accumulate duplicate hooks"

    def test_preserves_foreign_settings_and_hooks(self, fake_home: Path):
        settings = fake_home / ".claude/settings.json"
        settings.write_text(
            json.dumps(
                {
                    "model": "opus",
                    "hooks": {
                        "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "/other/tool"}]}],
                        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/audit"}]}],
                    },
                }
            ),
            encoding="utf-8",
        )
        run_install(repo_root(), ["claude"])
        data = json.loads(settings.read_text())
        assert data["model"] == "opus"
        assert "PreToolUse" in data["hooks"], "unrelated hook events must survive"
        assert any("/other/tool" in json.dumps(g) for g in data["hooks"]["SessionStart"])

    def test_installs_commands_skill_and_wiki_access(self, fake_home: Path):
        assert run_install(repo_root(), ["claude"])
        settings = json.loads((fake_home / ".claude/settings.json").read_text())
        assert str(repo_root()) in settings["permissions"]["additionalDirectories"]
        assert (fake_home / ".claude/skills/wiki-context").resolve() == repo_root() / "internal/skills/wiki-context"
        for command in ("wiki-query.md", "wiki-ingest.md", "wiki-lint.md"):
            assert (fake_home / ".claude/commands" / command).resolve() == repo_root() / "commands" / command

    def test_invalid_settings_shape_is_preserved_and_install_fails(self, fake_home: Path):
        settings = fake_home / ".claude/settings.json"
        settings.write_text(json.dumps({"hooks": []}), encoding="utf-8")

        assert not run_install(repo_root(), ["claude"])
        assert json.loads(settings.read_text()) == {"hooks": []}


class TestClaudeDesktop:
    def test_installs_mcp_server_config(self, fake_home: Path):
        assert run_install(repo_root(), ["claude-desktop"])
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)

        assert config_path.is_file()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "mcpServers" in data
        assert "brian-wiki" in data["mcpServers"]

        wiki_mcp = data["mcpServers"]["brian-wiki"]
        assert Path(wiki_mcp["command"]).is_file()
        assert wiki_mcp["args"] == [
            "run",
            "--project",
            str(repo_root().resolve()),
            "--no-dev",
            "python",
            str((repo_root() / "internal/mcp_server_wiki.py").resolve()),
        ]
        assert wiki_mcp["env"]["WIKI_ROOT"] == str(repo_root().resolve())

    def test_preserves_foreign_mcp_servers(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {
            "mcpServers": {
                "pulsar": {
                    "command": "pulsar-mcp",
                    "args": ["--port", "8080"],
                }
            }
        }
        config_path.write_text(json.dumps(initial_data), encoding="utf-8")

        assert run_install(repo_root(), ["claude-desktop"])
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "pulsar" in data["mcpServers"]
        assert "brian-wiki" in data["mcpServers"]

    def test_replaces_stale_mcp_server(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {
            "mcpServers": {
                "brian-wiki": {
                    "command": "old-python",
                    "args": ["/old/path/server.py"],
                    "env": {"WIKI_ROOT": "/old/root"},
                }
            }
        }
        config_path.write_text(json.dumps(initial_data), encoding="utf-8")

        assert run_install(repo_root(), ["claude-desktop"])
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["brian-wiki"]["env"]["WIKI_ROOT"] == str(repo_root().resolve())

    def test_is_idempotent(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        assert run_install(repo_root(), ["claude-desktop"])
        config_path = get_claude_desktop_config_path(fake_home)
        first_content = config_path.read_text(encoding="utf-8")

        assert run_install(repo_root(), ["claude-desktop"])
        second_content = config_path.read_text(encoding="utf-8")

        assert first_content == second_content
        assert not config_path.with_name(config_path.name + ".brian-wiki.backup").exists()

    def test_uninstall_removes_only_owned_mcp_server(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {
            "mcpServers": {
                "pulsar": {"command": "pulsar-mcp"},
                "brian-wiki": {"command": "python", "env": {"WIKI_ROOT": str(repo_root().resolve())}},
            }
        }
        config_path.write_text(json.dumps(initial_data), encoding="utf-8")

        run_uninstall(repo_root(), ["claude-desktop"])
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "pulsar" in data["mcpServers"]
        assert "brian-wiki" not in data["mcpServers"]

    def test_invalid_json_is_preserved_and_install_fails(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        invalid_content = '{\n  "mcpServers": {\n    // trailing comma or comment\n  }\n}'
        config_path.write_text(invalid_content, encoding="utf-8")

        assert not run_install(repo_root(), ["claude-desktop"])
        assert config_path.read_text(encoding="utf-8") == invalid_content

    def test_roundtrip_from_active_to_absent(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path, integration_state

        assert integration_state("claude-desktop", fake_home, repo_root()) == "absent"
        run_install(repo_root(), ["claude-desktop"])
        assert integration_state("claude-desktop", fake_home, repo_root()) == "active"
        run_uninstall(repo_root(), ["claude-desktop"])
        assert integration_state("claude-desktop", fake_home, repo_root()) == "absent"
        assert not get_claude_desktop_config_path(fake_home).exists()
        assert not (fake_home / ".local/bin/wiki").exists()

    def test_install_fails_without_uv_instead_of_writing_broken_config(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        monkeypatch.setattr("wikicli.lifecycle.integrations.shutil.which", lambda _name: None)

        assert not run_install(repo_root(), ["claude-desktop"])
        assert not get_claude_desktop_config_path(fake_home).exists()
        assert not (fake_home / ".local/bin/wiki").exists()

    @pytest.mark.parametrize(
        ("platform", "relative"),
        [
            ("darwin", "Library/Application Support/Claude/claude_desktop_config.json"),
            ("linux", ".config/Claude/claude_desktop_config.json"),
        ],
    )
    def test_uses_platform_specific_config_location(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch, platform: str, relative: str
    ):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        monkeypatch.setattr("wikicli.lifecycle.integrations.sys.platform", platform)

        assert get_claude_desktop_config_path(fake_home) == fake_home / relative

    def test_windows_config_honors_redirected_appdata(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        roaming = fake_home / "redirected-roaming"
        monkeypatch.setattr("wikicli.lifecycle.integrations.sys.platform", "win32")
        monkeypatch.setenv("APPDATA", str(roaming))

        assert get_claude_desktop_config_path(fake_home) == roaming / "Claude/claude_desktop_config.json"

    def test_uninstall_preserves_original_backup_without_managed_server(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        config_path = get_claude_desktop_config_path(fake_home)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original = {"theme": "dark", "mcpServers": {"pulsar": {"command": "pulsar"}}}
        config_path.write_text(json.dumps(original), encoding="utf-8")

        assert run_install(repo_root(), ["claude-desktop"])
        run_uninstall(repo_root(), ["claude-desktop"])

        assert json.loads(config_path.read_text(encoding="utf-8")) == original
        backup = config_path.with_name(config_path.name + ".brian-wiki.backup")
        assert json.loads(backup.read_text(encoding="utf-8")) == original

    @pytest.mark.parametrize(
        "changed",
        [
            {"command": "/missing/uv"},
            {"args": ["run", "/wrong/server.py"]},
            {"env": {"WIKI_ROOT": "/wrong/root"}},
        ],
    )
    def test_status_requires_complete_launch_configuration(self, fake_home: Path, changed: dict[str, object]):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        assert run_install(repo_root(), ["claude-desktop"])
        config_path = get_claude_desktop_config_path(fake_home)
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["mcpServers"]["brian-wiki"].update(changed)
        config_path.write_text(json.dumps(data), encoding="utf-8")

        assert integration_state("claude-desktop", fake_home, repo_root()) == "stale"


class TestCodex:
    def test_writes_the_documented_nested_schema(self, fake_home: Path):
        run_install(repo_root(), ["codex"])
        data = tomllib.loads((fake_home / ".codex/config.toml").read_text())
        entries = data["hooks"]["SessionStart"]
        assert isinstance(entries, list), "must be an array of tables ([[hooks.SessionStart]])"
        assert entries[0]["hooks"][0]["command"].endswith("wiki hook session-start")

    def test_enables_the_hooks_feature(self, fake_home: Path):
        """Codex ships hooks as a stable feature defaulting OFF — the hook is inert without this."""
        run_install(repo_root(), ["codex"])
        data = tomllib.loads((fake_home / ".codex/config.toml").read_text())
        assert data["features"]["hooks"] is True

    def test_replaces_a_stale_hook_block(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text(
            'model = "gpt-5"\n\n[hooks.SessionStart]\nhooks = [{ type = "command", command = "' + STALE_CMD + '" }]\n',
            encoding="utf-8",
        )
        run_install(repo_root(), ["codex"])
        text = config.read_text()
        assert "wiki-wake-up.sh" not in text, "substring guard bug: upgrade left the dead command in place"
        assert tomllib.loads(text)["model"] == "gpt-5", "unrelated config must survive"

    def test_is_idempotent(self, fake_home: Path):
        run_install(repo_root(), ["codex"])
        run_install(repo_root(), ["codex"])
        data = tomllib.loads((fake_home / ".codex/config.toml").read_text())
        assert len(data["hooks"]["SessionStart"]) == 1

    def test_output_is_always_valid_toml(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text(
            'model = "gpt-5"\n\n[mcp_servers.topos]\ncommand = "/x/topos"\n\n'
            '[projects."/Users/me/repo"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )
        run_install(repo_root(), ["codex"])
        data = tomllib.loads(config.read_text())
        assert "topos" in data["mcp_servers"], "MCP servers must survive"
        assert data["projects"]["/Users/me/repo"]["trust_level"] == "trusted", "trust entries must survive"

    def test_adds_wiki_writable_root_and_skill(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text('[sandbox_workspace_write]\nwritable_roots = ["/keep"]\n', encoding="utf-8")

        assert run_install(repo_root(), ["codex"])

        data = tomllib.loads(config.read_text())
        assert data["sandbox_workspace_write"]["writable_roots"] == ["/keep", str(repo_root())]
        assert (fake_home / ".codex/skills/wiki-context").resolve() == repo_root() / "internal/skills/wiki-context"

    def test_invalid_config_is_preserved_and_install_fails(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text("not = [valid", encoding="utf-8")

        assert not run_install(repo_root(), ["codex"])

        assert config.read_text() == "not = [valid"

    def test_invalid_writable_roots_shape_is_preserved_and_install_fails(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        original = '[sandbox_workspace_write]\nwritable_roots = "not-an-array"\n'
        config.write_text(original, encoding="utf-8")

        assert not run_install(repo_root(), ["codex"])
        assert config.read_text() == original


class TestGemini:
    def test_installs_nested_group_and_replaces_stale(self, fake_home: Path):
        settings = fake_home / ".gemini/settings.json"
        settings.write_text(
            json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": STALE_CMD}]}]}}), encoding="utf-8"
        )
        run_install(repo_root(), ["gemini"])
        groups = json.loads(settings.read_text())["hooks"]["SessionStart"]
        assert len(groups) == 1
        assert "wiki-wake-up.sh" not in json.dumps(groups)
        assert groups[0]["hooks"][0]["command"].endswith("wiki hook session-start")

    def test_preserves_other_settings(self, fake_home: Path):
        settings = fake_home / ".gemini/settings.json"
        settings.write_text(json.dumps({"mcpServers": {"x": {}}, "ui": {"theme": "dark"}}), encoding="utf-8")
        run_install(repo_root(), ["gemini"])
        data = json.loads(settings.read_text())
        assert "mcpServers" in data and data["ui"]["theme"] == "dark"

    def test_installs_skill_and_documented_workspace_access(self, fake_home: Path):
        assert run_install(repo_root(), ["gemini"])
        data = json.loads((fake_home / ".gemini/settings.json").read_text())
        assert str(repo_root()) in data["context"]["includeDirectories"]
        assert str(repo_root()) in data["tools"]["sandboxAllowedPaths"]
        assert (fake_home / ".gemini/skills/wiki-context").resolve() == repo_root() / "internal/skills/wiki-context"


class TestAntigravity:
    @staticmethod
    def import_line() -> str:
        return f"@import {repo_root() / '_templates/agent-pointer.md'}"

    @staticmethod
    def permission_rules() -> list[str]:
        root = repo_root().resolve()
        return [f"read_file({root})", f"write_file({root})"]

    def test_foreign_rules_without_final_newline_do_not_clobber_import(self, fake_home: Path):
        gemini_md = fake_home / ".gemini/GEMINI.md"
        foreign_rules = "<!-- lean-ctx-rules -->\nKeep this foreign rule.\n<!-- /lean-ctx-rules -->"
        gemini_md.write_text(foreign_rules, encoding="utf-8")

        assert run_install(repo_root(), ["antigravity"])

        assert gemini_md.read_text(encoding="utf-8") == f"{foreign_rules}\n{self.import_line()}\n"
        assert integration_state("antigravity", fake_home, repo_root()) == "active"

        installed = gemini_md.read_text(encoding="utf-8")
        assert run_install(repo_root(), ["antigravity"])
        assert gemini_md.read_text(encoding="utf-8") == installed

    def test_reinstall_repairs_legacy_concatenated_import(self, fake_home: Path):
        gemini_md = fake_home / ".gemini/GEMINI.md"
        gemini_md.write_text(f"Keep this rule.{self.import_line()}\n", encoding="utf-8")

        assert run_install(repo_root(), ["antigravity"])

        assert gemini_md.read_text(encoding="utf-8") == f"Keep this rule.\n{self.import_line()}\n"
        assert integration_state("antigravity", fake_home, repo_root()) == "active"

    @pytest.mark.parametrize(
        ("has_pointer", "has_permissions", "expected"),
        [
            (False, False, "absent"),
            (True, False, "stale"),
            (False, True, "stale"),
            (True, True, "active"),
        ],
    )
    def test_state_requires_pointer_and_permissions(
        self, fake_home: Path, has_pointer: bool, has_permissions: bool, expected: str
    ):
        if has_pointer:
            (fake_home / ".gemini/GEMINI.md").write_text(self.import_line() + "\n", encoding="utf-8")
        if has_permissions:
            settings = fake_home / ".gemini/antigravity-cli/settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps({"permissions": {"allow": self.permission_rules()}}), encoding="utf-8")

        assert integration_state("antigravity", fake_home, repo_root()) == expected

    def test_pointer_with_invalid_permission_settings_is_stale(self, fake_home: Path):
        (fake_home / ".gemini/GEMINI.md").write_text(self.import_line() + "\n", encoding="utf-8")
        settings = fake_home / ".gemini/antigravity-cli/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("not json", encoding="utf-8")

        assert integration_state("antigravity", fake_home, repo_root()) == "stale"

    def test_uninstall_repairs_legacy_concatenated_import(self, fake_home: Path):
        gemini_md = fake_home / ".gemini/GEMINI.md"
        gemini_md.write_text(f"Keep this rule.{self.import_line()}\n", encoding="utf-8")

        run_uninstall(repo_root(), ["antigravity"])

        assert gemini_md.read_text(encoding="utf-8") == "Keep this rule.\n"


class TestPathLinks:
    def test_links_the_single_cli_entrypoint(self, fake_home: Path):
        run_install(repo_root(), ["claude"])
        link = fake_home / ".local/bin/wiki"
        assert link.is_symlink() and link.resolve() == repo_root() / "bin" / "wiki"

    def test_does_not_remove_live_foreign_symlinks(self, fake_home: Path, tmp_path: Path):
        real = tmp_path / "wiki-other-tool.sh"
        real.write_text("#!/bin/sh\n", encoding="utf-8")
        link = fake_home / ".local/bin/wiki-other-tool.sh"
        link.symlink_to(real)
        run_install(repo_root(), ["claude"])
        assert link.exists(), "only DANGLING links may be pruned"

    def test_preserves_real_skill_directory_and_reports_failure(self, fake_home: Path):
        skill = fake_home / ".agents/skills/wiki-context"
        skill.mkdir()
        sentinel = skill / "custom.md"
        sentinel.write_text("keep", encoding="utf-8")

        assert not run_install(repo_root(), ["skills"])

        assert sentinel.read_text() == "keep"

    def test_preserves_foreign_cli_file_and_reports_failure(self, fake_home: Path):
        cli = fake_home / ".local/bin/wiki"
        cli.write_text("foreign", encoding="utf-8")

        assert not run_install(repo_root(), ["claude"])

        assert cli.read_text() == "foreign"

    def test_cursor_and_antigravity_cli_get_documented_write_permissions(self, fake_home: Path):
        assert run_install(repo_root(), ["skills", "antigravity"])
        cursor = json.loads((fake_home / ".cursor/cli-config.json").read_text())
        antigravity = json.loads((fake_home / ".gemini/antigravity-cli/settings.json").read_text())
        assert f"Write({repo_root()}/**)" in cursor["permissions"]["allow"]
        assert f"write_file({repo_root()})" in antigravity["permissions"]["allow"]

    @pytest.mark.parametrize(
        ("agent", "instructions"),
        [
            ("claude", ".claude/skills/wiki-context/SKILL.md"),
            ("codex", ".codex/skills/wiki-context/SKILL.md"),
            ("gemini", ".gemini/skills/wiki-context/SKILL.md"),
        ],
    )
    def test_shell_agents_receive_the_canonical_knowledge_interface(
        self, fake_home: Path, agent: str, instructions: str
    ):
        assert run_install(repo_root(), [agent])

        text = (fake_home / instructions).read_text(encoding="utf-8")
        assert "wiki knowledge query" in text
        assert "wiki knowledge read" in text
        assert "wiki knowledge update" in text
        assert "--approve" in text

    def test_antigravity_pointer_describes_the_canonical_knowledge_interface(self, fake_home: Path):
        assert run_install(repo_root(), ["antigravity"])

        pointer = repo_root() / "_templates/agent-pointer.md"
        assert (fake_home / ".gemini/GEMINI.md").read_text(encoding="utf-8").splitlines() == [f"@import {pointer}"]
        text = pointer.read_text(encoding="utf-8")
        assert "wiki knowledge query" in text
        assert "wiki knowledge read" in text
        assert "wiki knowledge update" in text
        assert "--approve" in text


class TestCodexHelpers:
    def test_strip_removes_only_our_blocks(self):
        text = (
            'model = "x"\n\n[[hooks.SessionStart]]\nmatcher = "startup"\n\n'
            '[[hooks.SessionStart.hooks]]\ncommand = "' + STALE_CMD + '"\n\n'
            '[[hooks.PreToolUse]]\ncommand = "/keep/me"\n'
        )
        out = _strip_codex_wiki_hooks(text)
        assert "wiki-wake-up.sh" not in out
        assert "/keep/me" in out, "other hook events must survive"
        assert 'model = "x"' in out

    def test_strip_removes_an_orphaned_nested_child(self):
        """A real state found on a live machine, and unrecoverable without this.

        An interrupted uninstall deleted the parent `[[hooks.SessionStart]]` and left the nested
        `[[hooks.SessionStart.hooks]]` behind. Re-installing then appended a fresh parent, which
        collided with the stray child — TOML validation rejected the write, so the installer
        reported failure every time and Codex could never be repaired.
        """
        text = (
            'model = "x"\n\n'
            "# Wiki context engine\n"
            "[[hooks.SessionStart.hooks]]\n"
            'type = "command"\n'
            f"command = '{STALE_CMD}'\n\n"
            "[sandbox_workspace_write]\n"
            'writable_roots = ["/x"]\n'
        )
        out = _strip_codex_wiki_hooks(text)
        assert "wiki-wake-up" not in out
        assert "hooks.SessionStart" not in out, "the orphaned child must go too"
        assert "writable_roots" in out, "following tables must survive"
        tomllib.loads(out)

    def test_reinstall_repairs_an_orphaned_child(self, fake_home: Path):
        """End-to-end version of the above: install must fix the config, not fail on it."""
        config = fake_home / ".codex/config.toml"
        config.write_text(
            f"model = \"x\"\n\n[[hooks.SessionStart.hooks]]\ncommand = '{STALE_CMD}'\n\n[features]\nhooks = false\n",
            encoding="utf-8",
        )
        run_install(repo_root(), ["codex"])
        data = tomllib.loads(config.read_text())
        assert data["features"]["hooks"] is True
        assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("wiki hook session-start")
        assert "wiki-wake-up" not in config.read_text()

    def test_strip_leaves_foreign_sessionstart_hooks(self):
        text = '[[hooks.SessionStart]]\n\n[[hooks.SessionStart.hooks]]\ncommand = "/other/thing"\n'
        assert "/other/thing" in _strip_codex_wiki_hooks(text)

    def test_features_marker_records_prior_state(self):
        out = _set_codex_features_hooks("[features]\nhooks = false\n")
        assert "hooks = true" in out
        assert "brian-wiki:" in out, "uninstall needs the marker to know it may revert this"

    def test_features_leaves_user_enabled_flag_untouched(self):
        text = "[features]\nhooks = true\n"
        assert "brian-wiki:" not in _set_codex_features_hooks(text), "must not claim a flag the user set"

    def test_features_section_created_when_absent(self):
        out = _set_codex_features_hooks('model = "x"\n')
        assert tomllib.loads(out)["features"]["hooks"] is True


class TestUninstall:
    @pytest.mark.parametrize(("agent", "config_dir"), [("claude", ".claude"), ("gemini", ".gemini")])
    def test_removes_nested_json_hook_and_preserves_foreign_config(self, fake_home: Path, agent: str, config_dir: str):
        run_install(repo_root(), [agent])
        settings = fake_home / config_dir / "settings.json"
        data = json.loads(settings.read_text())
        data["theme"] = "dark"
        data["hooks"]["SessionStart"][0]["hooks"].append({"type": "command", "command": "/other/tool"})
        settings.write_text(json.dumps(data), encoding="utf-8")

        run_uninstall(repo_root(), [agent])

        data = json.loads(settings.read_text())
        assert data["theme"] == "dark"
        assert json.dumps(data).count("/other/tool") == 1
        assert "wiki hook session-start" not in json.dumps(data)

    def test_codex_removes_only_owned_hook_and_restores_feature_state(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text(
            'model = "gpt-5"\n\n[features]\nhooks = false\n\n'
            '[[hooks.SessionStart]]\nmatcher = "startup"\n\n'
            '[[hooks.SessionStart.hooks]]\ncommand = "/other/tool"\n',
            encoding="utf-8",
        )
        run_install(repo_root(), ["codex"])

        run_uninstall(repo_root(), ["codex"])

        text = config.read_text()
        data = tomllib.loads(text)
        assert data["model"] == "gpt-5"
        assert data["features"]["hooks"] is False
        assert data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/other/tool"
        assert "wiki hook session-start" not in text

    def test_codex_removes_feature_key_it_created(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text('model = "gpt-5"\n', encoding="utf-8")
        run_install(repo_root(), ["codex"])

        run_uninstall(repo_root(), ["codex"])

        data = tomllib.loads(config.read_text())
        assert data["model"] == "gpt-5"
        assert "hooks" not in data.get("features", {})
        assert "SessionStart" not in data.get("hooks", {})

    def test_codex_removes_only_writable_root_it_added(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text('[sandbox_workspace_write]\nwritable_roots = ["/keep"]\n', encoding="utf-8")
        run_install(repo_root(), ["codex"])

        run_uninstall(repo_root(), ["codex"])

        assert tomllib.loads(config.read_text())["sandbox_workspace_write"]["writable_roots"] == ["/keep"]

    def test_preexisting_wiki_access_is_not_claimed_or_removed(self, fake_home: Path):
        settings = fake_home / ".claude/settings.json"
        settings.write_text(
            json.dumps({"permissions": {"additionalDirectories": [str(repo_root())]}}), encoding="utf-8"
        )
        run_install(repo_root(), ["claude"])

        run_uninstall(repo_root(), ["claude"])

        data = json.loads(settings.read_text())
        assert str(repo_root()) in data["permissions"]["additionalDirectories"]

    def test_codex_preserves_feature_flag_the_user_enabled(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text("[features]\nhooks = true\n", encoding="utf-8")
        run_install(repo_root(), ["codex"])

        run_uninstall(repo_root(), ["codex"])

        assert tomllib.loads(config.read_text())["features"]["hooks"] is True

    def test_codex_cleans_orphan_left_by_previous_uninstaller(self, fake_home: Path):
        config = fake_home / ".codex/config.toml"
        config.write_text(
            "[[hooks.SessionStart.hooks]]\ncommand = '/x/bin/wiki hook session-start'\n",
            encoding="utf-8",
        )
        assert integration_state("codex", fake_home, repo_root()) == "stale"

        run_uninstall(repo_root(), ["codex"])

        assert integration_state("codex", fake_home, repo_root()) == "absent"

    @pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "copilot", "skills", "antigravity"])
    def test_each_agent_round_trips_from_active_to_absent(self, fake_home: Path, agent: str):
        run_install(repo_root(), [agent])
        assert integration_state(agent, fake_home, repo_root()) == "active"

        run_uninstall(repo_root(), [agent])

        assert integration_state(agent, fake_home, repo_root()) == "absent"

    def test_full_uninstall_does_not_remove_foreign_paths(self, fake_home: Path, tmp_path: Path):
        foreign_skill = tmp_path / "foreign-skill"
        foreign_skill.mkdir()
        skill_link = fake_home / ".agents/skills/wiki-context"
        skill_link.symlink_to(foreign_skill)
        cli_path = fake_home / ".local/bin/wiki"
        cli_path.write_text("foreign executable", encoding="utf-8")

        run_uninstall(repo_root(), ["all"])

        assert skill_link.is_symlink() and skill_link.resolve() == foreign_skill
        assert cli_path.read_text() == "foreign executable"

    @pytest.mark.parametrize(
        ("agent", "artifacts"),
        [
            ("claude", [".claude/skills/wiki-context", ".claude/commands/wiki-query.md"]),
            ("codex", [".codex/skills/wiki-context"]),
            ("gemini", [".gemini/skills/wiki-context"]),
        ],
    )
    def test_removes_only_repo_owned_legacy_artifacts(self, fake_home: Path, agent: str, artifacts: list[str]):
        run_install(repo_root(), [agent])

        run_uninstall(repo_root(), [agent])

        assert all(not (fake_home / artifact).exists() for artifact in artifacts)

    @pytest.mark.parametrize("agent", ["claude", "gemini", "skills", "antigravity"])
    def test_removes_owned_json_access_entries(self, fake_home: Path, agent: str):
        run_install(repo_root(), [agent])

        run_uninstall(repo_root(), [agent])

        state = fake_home / ".local/state/brian-wiki/install.json"
        assert not state.exists() or agent not in json.loads(state.read_text())

    def test_full_lifecycle_leaves_only_selected_integrations_active(self, fake_home: Path, capsys):
        run_install(repo_root(), ["claude", "codex"])
        run_uninstall(repo_root(), ["claude", "codex"])
        run_install(repo_root(), ["gemini", "antigravity"])
        capsys.readouterr()

        run_status(repo_root())

        out = capsys.readouterr().out
        assert "Done. 2/7 agent integrations active." in out
        assert "stale wiki" not in out

    def test_all_destinations_install_status_and_clean_uninstall(self, fake_home: Path, capsys):
        assert run_install(repo_root(), ["all"])
        assert all(
            integration_state(agent, fake_home, repo_root()) == "active"
            for agent in (
                "claude",
                "claude-desktop",
                "codex",
                "gemini",
                "copilot",
                "skills",
                "antigravity",
            )
        )
        capsys.readouterr()
        run_status(repo_root())
        assert "Done. 7/7 agent integrations active." in capsys.readouterr().out

        run_uninstall(repo_root(), ["all"], purge_backups=True)

        assert all(
            integration_state(agent, fake_home, repo_root()) == "absent"
            for agent in (
                "claude",
                "claude-desktop",
                "codex",
                "gemini",
                "copilot",
                "skills",
                "antigravity",
            )
        )
        assert not (fake_home / ".local/bin/wiki").exists()
        assert not list(fake_home.rglob("*.brian-wiki.backup"))
        assert not list(fake_home.rglob("*.tmp"))
        assert not [path for path in fake_home.rglob("*") if path.is_file() or path.is_symlink()]

    def test_uninstall_preserves_preexisting_empty_config_files(self, fake_home: Path):
        claude = fake_home / ".claude/settings.json"
        claude.write_text("{}", encoding="utf-8")

        run_install(repo_root(), ["claude"])
        run_uninstall(repo_root(), ["claude"], purge_backups=True)

        assert claude.is_file()
        assert json.loads(claude.read_text(encoding="utf-8")) == {"permissions": {}}
        assert "wiki" not in claude.read_text(encoding="utf-8")

    def test_full_roundtrip_preserves_every_foreign_setting_and_user_backup(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path

        claude = fake_home / ".claude/settings.json"
        claude.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "permissions": {"additionalDirectories": ["/keep"]},
                    "hooks": {
                        "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "/other/tool"}]}],
                        "PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "/audit"}]}],
                    },
                }
            ),
            encoding="utf-8",
        )
        user_backup = claude.with_name("settings.json.backup")
        user_backup.write_text("user-owned backup", encoding="utf-8")

        desktop = get_claude_desktop_config_path(fake_home)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text(
            json.dumps({"theme": "dark", "mcpServers": {"foreign": {"command": "/foreign/server"}}}),
            encoding="utf-8",
        )

        codex = fake_home / ".codex/config.toml"
        codex.write_text(
            'model = "gpt-5"\n\n[features]\nhooks = true\n\n'
            '[sandbox_workspace_write]\nwritable_roots = ["/keep"]\n\n'
            '[[hooks.SessionStart]]\nmatcher = "startup"\n\n'
            '[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = "/other/tool"\n',
            encoding="utf-8",
        )

        gemini = fake_home / ".gemini/settings.json"
        gemini.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "context": {"includeDirectories": ["/keep"]},
                    "tools": {"sandboxAllowedPaths": ["/keep"]},
                    "hooks": {"SessionStart": [{"hooks": [{"command": "/other/tool"}]}]},
                }
            ),
            encoding="utf-8",
        )
        copilot = fake_home / ".copilot/copilot-instructions.md"
        copilot.write_text("Keep this instruction.\n", encoding="utf-8")
        cursor = fake_home / ".cursor/cli-config.json"
        cursor.parent.mkdir(parents=True, exist_ok=True)
        cursor.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["Read(/keep/**)"]}}), encoding="utf-8")
        gemini_md = fake_home / ".gemini/GEMINI.md"
        gemini_md.write_text("Keep this import.\n", encoding="utf-8")
        antigravity = fake_home / ".gemini/antigravity-cli/settings.json"
        antigravity.parent.mkdir(parents=True, exist_ok=True)
        antigravity.write_text(
            json.dumps({"theme": "dark", "permissions": {"allow": ["read_file(/keep)"]}}), encoding="utf-8"
        )

        assert run_install(repo_root(), ["all"])
        run_uninstall(repo_root(), ["all"], purge_backups=True)

        claude_data = json.loads(claude.read_text(encoding="utf-8"))
        assert claude_data["theme"] == "dark"
        assert claude_data["permissions"]["additionalDirectories"] == ["/keep"]
        assert json.dumps(claude_data).count("/other/tool") == 1
        assert "PreToolUse" in claude_data["hooks"]
        assert json.loads(desktop.read_text(encoding="utf-8")) == {
            "theme": "dark",
            "mcpServers": {"foreign": {"command": "/foreign/server"}},
        }
        codex_data = tomllib.loads(codex.read_text(encoding="utf-8"))
        assert codex_data["model"] == "gpt-5"
        assert codex_data["features"]["hooks"] is True
        assert codex_data["sandbox_workspace_write"]["writable_roots"] == ["/keep"]
        assert codex_data["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "/other/tool"
        gemini_data = json.loads(gemini.read_text(encoding="utf-8"))
        assert gemini_data["theme"] == "dark"
        assert gemini_data["context"]["includeDirectories"] == ["/keep"]
        assert gemini_data["tools"]["sandboxAllowedPaths"] == ["/keep"]
        assert "/other/tool" in json.dumps(gemini_data)
        assert copilot.read_text(encoding="utf-8") == "Keep this instruction.\n"
        assert json.loads(cursor.read_text(encoding="utf-8")) == {
            "theme": "dark",
            "permissions": {"allow": ["Read(/keep/**)"]},
        }
        assert gemini_md.read_text(encoding="utf-8") == "Keep this import.\n"
        assert json.loads(antigravity.read_text(encoding="utf-8")) == {
            "theme": "dark",
            "permissions": {"allow": ["read_file(/keep)"]},
        }
        assert user_backup.read_text(encoding="utf-8") == "user-owned backup"

    def test_interactive_uninstall_preselects_active_integrations(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        run_install(repo_root(), ["claude", "claude-desktop"])
        captured: list[tuple[str, str, str, bool]] = []

        def menu(_prompt: str, options: list[tuple[str, str, str, bool]]) -> str:
            captured.extend(options)
            return ""

        monkeypatch.setattr("wikicli.lifecycle.uninstall.run_menu", menu)

        run_uninstall(repo_root(), [])

        selected = {agent: is_selected for agent, _name, _hint, is_selected in captured}
        assert selected["claude"]
        assert selected["claude-desktop"]
        assert not selected["codex"]


class TestStatus:
    def test_reports_knowledge_freshness_separately_from_integrations(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        from wikicli.lifecycle.sync import SyncResult, SyncState

        monkeypatch.setattr(
            "wikicli.lifecycle.status.get_sync_status",
            lambda _repo_root: SyncResult(SyncState.CURRENT, "wiki main matches origin/main", True, 1000),
        )

        run_status(repo_root())

        out = capsys.readouterr().out
        assert "Knowledge Freshness" in out
        assert "wiki main matches origin/main" in out
        assert "Done. 0/7 agent integrations active." in out

    def test_does_not_treat_unrelated_wiki_text_as_an_active_hook(self, fake_home: Path, capsys):
        (fake_home / ".claude/settings.json").write_text(json.dumps({"note": "wiki docs"}), encoding="utf-8")

        run_status(repo_root())

        out = capsys.readouterr().out
        assert "Done. 0/7 agent integrations active." in out

    def test_reports_orphaned_codex_child_as_stale_not_active(self, fake_home: Path, capsys):
        (fake_home / ".codex/config.toml").write_text(
            "[[hooks.SessionStart.hooks]]\ncommand = '/x/bin/wiki hook session-start'\n",
            encoding="utf-8",
        )

        run_status(repo_root())

        out = capsys.readouterr().out
        assert "stale or incomplete wiki integration" in out
        assert "Done. 0/7 agent integrations active." in out

    def test_reports_partial_antigravity_setup_as_stale_not_active(self, fake_home: Path, capsys):
        pointer = repo_root() / "_templates/agent-pointer.md"
        (fake_home / ".gemini/GEMINI.md").write_text(f"@import {pointer}\n", encoding="utf-8")

        run_status(repo_root())

        out = capsys.readouterr().out
        assert "Google Antigravity" in out
        assert "stale or incomplete wiki integration" in out
        assert "Done. 0/7 agent integrations active." in out


class TestRegistryAndAtomicWriter:
    def test_agent_registry_contains_all_supported_agents(self):
        from wikicli.lifecycle.integrations import AGENT_REGISTRY, SUPPORTED_AGENTS

        for agent in SUPPORTED_AGENTS:
            assert agent in AGENT_REGISTRY
            spec = AGENT_REGISTRY[agent]
            assert spec.id == agent
            assert spec.name
            assert spec.status_heading
            assert spec.active_msg
            assert spec.absent_msg

    def test_atomic_write_json_creates_backup_and_writes_atomically(self, tmp_path: Path):
        from wikicli.lifecycle.integrations import atomic_write_json

        target = tmp_path / "config.json"
        initial_data = {"key": "value1"}
        target.write_text(json.dumps(initial_data), encoding="utf-8")

        new_data = {"key": "value2"}
        atomic_write_json(target, new_data)

        backup = target.with_name(target.name + ".brian-wiki.backup")
        assert backup.is_file()
        assert json.loads(backup.read_text(encoding="utf-8")) == initial_data
        assert json.loads(target.read_text(encoding="utf-8")) == new_data

    @pytest.mark.parametrize(
        ("agent", "directory"),
        [
            ("claude", ".claude"),
            ("codex", ".codex"),
            ("gemini", ".gemini"),
            ("copilot", ".copilot"),
            ("skills", ".agents/skills"),
            ("antigravity", ".gemini"),
        ],
    )
    def test_application_directory_counts_as_detected_before_config_exists(
        self, fake_home: Path, agent: str, directory: str
    ):
        from wikicli.lifecycle.integrations import get_detection_path

        assert get_detection_path(agent, fake_home) == fake_home / directory
        assert get_detection_path(agent, fake_home).is_dir()

    def test_interactive_install_preselects_detected_application_directories(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        captured: list[tuple[str, str, str, bool, bool]] = []

        def menu(_prompt: str, options: list[tuple[str, str, str, bool, bool]]) -> str:
            captured.extend(options)
            return ""

        monkeypatch.setattr("wikicli.lifecycle.install.run_menu", menu)

        assert run_install(repo_root(), [])
        selected = {agent: is_selected for agent, _name, _hint, is_selected, _active in captured}
        assert selected["claude"]
        assert selected["copilot"]
        assert selected["skills"]
        assert selected["antigravity"]
        assert selected["codex"]
        assert selected["gemini"]

    def test_claude_desktop_directory_is_detected_before_config_exists(self, fake_home: Path):
        from wikicli.lifecycle.integrations import get_claude_desktop_config_path, get_detection_path

        application_directory = get_claude_desktop_config_path(fake_home).parent
        application_directory.mkdir(parents=True, exist_ok=True)

        assert get_detection_path("claude-desktop", fake_home) == application_directory
        assert get_detection_path("claude-desktop", fake_home).is_dir()
