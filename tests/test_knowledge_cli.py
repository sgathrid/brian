from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import internal.mcp_server_wiki as server

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "bin/wiki"), "knowledge", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_structured_cli_query_matches_mcp_adapter() -> None:
    completed = _run("query", "Explain Erdos simply to a new colleague", "--limit", "3")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(
        server.query_company_knowledge("Explain Erdos simply to a new colleague", limit=3)
    )
    assert completed.stderr == ""


def test_structured_cli_read_matches_mcp_adapter_and_rejects_escape() -> None:
    completed = _run("read", "wiki/entities/brian-overview.md")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(server.read_company_page("wiki/entities/brian-overview.md"))

    escaped = _run("read", "../README")
    assert escaped.returncode == 2
    assert escaped.stdout == ""
    assert "invalid company wiki path" in json.loads(escaped.stderr)["error"]["message"]


def test_structured_cli_update_reads_json_from_stdin() -> None:
    completed = _run("update", "--input", "-", input_text="not-json")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error"]["type"] == "invalid_request"
