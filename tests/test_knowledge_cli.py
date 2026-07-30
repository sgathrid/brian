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
    completed = _run("query", "What is Brian?", "--limit", "3")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(
        server.query_knowledge("What is Brian?", limit=3)
    )
    assert completed.stderr == ""


def test_structured_cli_read_matches_mcp_adapter_and_rejects_escape() -> None:
    completed = _run("read", "wiki/entities/brian-overview.md")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(server.read_page("wiki/entities/brian-overview.md"))

    escaped = _run("read", "../README")
    assert escaped.returncode == 2
    assert escaped.stdout == ""
    assert "invalid knowledge page reference" in json.loads(escaped.stderr)["error"]["message"]


def test_structured_cli_read_accepts_page_references() -> None:
    expected = asdict(server.read_page("wiki/entities/brian-overview.md"))

    for ref in ("wiki://page/entities/brian-overview", "Brian Overview", "[[Brian Overview]]", "brian-overview"):
        completed = _run("read", ref)

        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == expected


def test_structured_cli_update_reads_json_from_stdin() -> None:
    completed = _run("update", "--input", "-", input_text="not-json")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error"]["type"] == "invalid_request"


def test_structured_cli_source_inventory_matches_mcp_adapter() -> None:
    completed = _run("sources")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(server.list_sources())


def test_structured_cli_rejects_out_of_range_source_inspection_limit() -> None:
    completed = _run("sources", "raw/missing.md", "--max-chars", "-1")

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error"] == {
        "type": "invalid_request",
        "message": "max_chars must be a non-negative integer",
    }
