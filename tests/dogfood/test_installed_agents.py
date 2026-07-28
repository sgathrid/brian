from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from wikicli.lifecycle.install import run_install
from wikicli.lifecycle.integrations import SUPPORTED_AGENTS, integration_state
from wikicli.lifecycle.status import run_status
from wikicli.lifecycle.uninstall import run_uninstall

ROOT = Path(__file__).resolve().parents[2]


def test_all_installed_agents_share_one_live_cli_and_cleanly_uninstall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert run_install(ROOT, ["all"])
    assert all(integration_state(agent, home, ROOT) == "active" for agent in SUPPORTED_AGENTS)
    capsys.readouterr()
    run_status(ROOT)
    assert "Done. 7/7 agent integrations active." in capsys.readouterr().out

    environment = os.environ.copy()
    environment["HOME"] = str(home)
    cli = subprocess.run(
        [str(home / ".local/bin/wiki"), "knowledge", "query", "What is Erdos?"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["hits"][0]["title"] == "Erdos"

    run_uninstall(ROOT, ["all"], purge_backups=True)
    assert all(integration_state(agent, home, ROOT) == "absent" for agent in SUPPORTED_AGENTS)
    assert not (home / ".local/bin/wiki").exists()
