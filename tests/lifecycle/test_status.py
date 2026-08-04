"""wiki status behavior card."""

from __future__ import annotations

import json
from pathlib import Path

from wikicli.lifecycle.status import _agent_behavior_lines, run_status


def test_agent_behavior_lines_empty_catalog_does_not_claim_rules(tmp_path: Path, monkeypatch):
    (tmp_path / "wiki.toml").write_text(
        """
[wiki]
name = "Status Co"
short_name = "StatusWiki"
agent_rules = ["adrs", "people_tracking"]

[upkeep]
proactivity = "capture"
triggers = ["One", "Two"]
instructions = \"\"\"Ask first.\"\"\"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("wikicli.lifecycle.status.load_agent_rule_catalog", dict)
    lines = _agent_behavior_lines(tmp_path)
    joined = "\n".join(lines)
    assert "Agent upkeep for new sessions" in joined
    assert "capture · 2 triggers · additional rules unavailable" in joined
    assert "adrs" not in joined
    assert "people_tracking" not in joined


def test_agent_behavior_lines_with_catalog_counts_resolved_rules(tmp_path: Path, monkeypatch):
    (tmp_path / "wiki.toml").write_text(
        """
[wiki]
name = "Status Co"
short_name = "StatusWiki"
agent_rules = ["adrs", "unknown_rule"]

[upkeep]
proactivity = "selective"
triggers = ["One"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "wikicli.lifecycle.status.load_agent_rule_catalog",
        lambda: {
            "adrs": {
                "label": "Record architecture decisions",
                "prompt_rule": "• ADR",
            }
        },
    )
    joined = "\n".join(_agent_behavior_lines(tmp_path))
    assert "selective · 1 trigger · 1 additional rule" in joined
    assert "unknown_rule" not in joined
    assert "TIP: Edit wiki.toml, run `wiki status`, then start a new session." in joined


def test_agent_behavior_lines_unset_proactivity_not_fake_selective(tmp_path: Path):
    (tmp_path / "wiki.toml").write_text(
        """
[wiki]
name = "S"
short_name = "S"

[upkeep]
proactivity = "yolo"
triggers = ["Ask"]
""",
        encoding="utf-8",
    )
    joined = "\n".join(_agent_behavior_lines(tmp_path))
    # Config clears invalid keys; status must not invent selective.
    assert "(unset)" in joined
    assert "selective" not in joined


def test_run_status_prints_behavior_card(tmp_path: Path, capsys):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki.toml").write_text(
        '[wiki]\nname = "S"\nshort_name = "S Wiki"\n\n[upkeep]\nproactivity = "silent"\ntriggers = ["Ask"]\n',
        encoding="utf-8",
    )
    run_status(tmp_path)
    out = capsys.readouterr().out
    assert "Agent upkeep for new sessions" in out
    assert "silent · 1 trigger · no additional rules" in out
    assert "TIP: Edit wiki.toml, run `wiki status`, then start a new session." in out
    assert "S Wiki Agent Status" in out


def test_run_status_flags_a_gemini_folder_trust_block(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("GEMINI_CLI_TRUST_WORKSPACE", raising=False)
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "wiki").mkdir(parents=True)
    (repo / "wiki.toml").write_text('[wiki]\nname = "S"\nshort_name = "S Wiki"\n', encoding="utf-8")
    (home / ".gemini/trustedFolders.json").write_text(json.dumps({str(tmp_path): "DO_NOT_TRUST"}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    run_status(repo)

    out = capsys.readouterr().out
    # Reported even before the integration is installed: the block applies either way.
    assert "not configured in ~/.gemini/settings.json" in out
    assert f"Gemini runs restricted in this folder: untrusted via {tmp_path}" in out
    assert "wiki install gemini --trust-folder" in out
    assert f'"{repo.resolve()}": "TRUST_FOLDER"' in out


def test_run_status_stays_quiet_without_a_blocking_trust_rule(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("GEMINI_CLI_TRUST_WORKSPACE", raising=False)
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "wiki").mkdir(parents=True)
    (repo / "wiki.toml").write_text('[wiki]\nname = "S"\nshort_name = "S Wiki"\n', encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    run_status(repo)

    assert "refuses to start" not in capsys.readouterr().out
