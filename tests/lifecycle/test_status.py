"""wiki status behavior card."""

from __future__ import annotations

from pathlib import Path

from wikicli.lifecycle.status import _agent_behavior_lines, run_status


def test_agent_behavior_lines_from_manifest(tmp_path: Path):
    (tmp_path / "wiki.toml").write_text(
        """
[wiki]
name = "Status Co"
short_name = "StatusWiki"
agent_rules = ["adrs"]

[upkeep]
proactivity = "capture"
triggers = ["One", "Two"]
instructions = \"\"\"Ask first.\"\"\"
""",
        encoding="utf-8",
    )
    lines = _agent_behavior_lines(tmp_path)
    joined = "\n".join(lines)
    assert "What agents will do" in joined
    assert "capture" in joined
    assert "triggers: 2" in joined
    # Catalog present (Brian init) → label; absent (KOS) → raw id
    assert (
        "adrs" in joined
        or "architecture" in joined.lower()
        or "Record" in joined
    )


def test_run_status_prints_behavior_card(tmp_path: Path, capsys):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki.toml").write_text(
        '[wiki]\nname = "S"\nshort_name = "S Wiki"\n\n'
        '[upkeep]\nproactivity = "silent"\ntriggers = ["Ask"]\n',
        encoding="utf-8",
    )
    run_status(tmp_path)
    out = capsys.readouterr().out
    assert "What agents will do" in out
    assert "silent" in out
    assert "S Wiki Agent Status" in out
