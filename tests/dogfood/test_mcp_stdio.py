from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from wikicli.core.ingest import check_ingestion
from wikicli.lifecycle.integrations import claude_desktop_server_config

ROOT = Path(__file__).resolve().parents[2]


def _copy_dogfood_repo(tmp_path: Path) -> Path:
    dogfood_root = tmp_path / "wiki-repo"
    for name in ("wiki", "internal", "benchmarks", "wikicli", "bin"):
        shutil.copytree(ROOT / name, dogfood_root / name)
    sources = json.loads((dogfood_root / "wiki/sources.json").read_text(encoding="utf-8"))["sources"]
    for source_path in sources:
        placeholder = dogfood_root / source_path
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        placeholder.write_text("Dogfood source placeholder.\n", encoding="utf-8")
    return dogfood_root


def test_claude_desktop_launch_command_initializes_real_server() -> None:
    config = claude_desktop_server_config(ROOT)

    async def exercise() -> None:
        environment = os.environ.copy()
        environment.update(config["env"])
        parameters = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=environment,
        )
        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "Brian Wiki"
            result = await session.call_tool("query_company_knowledge", {"question": "wiki company info"})
            assert not result.isError
            assert result.structuredContent["hits"][0]["title"] == "Brian Labs"
            cli = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(ROOT / "bin/wiki"), "knowledge", "query", "wiki company info"],
                text=True,
                capture_output=True,
                check=False,
            )
            assert cli.returncode == 0, cli.stderr
            assert json.loads(cli.stdout) == result.structuredContent

            product = await session.call_tool(
                "query_company_knowledge", {"question": "Explain Erdos simply to a new colleague"}
            )
            assert product.structuredContent["hits"][0]["title"] == "Erdos"

            customers = await session.call_tool("query_company_knowledge", {"question": "Who are Brian customers?"})
            assert customers.structuredContent["hits"][0]["title"] == "Brian Labs"
            assert all(hit["title"] != "Erdos" for hit in customers.structuredContent["hits"])

            unsupported = await session.call_tool(
                "query_company_knowledge", {"question": "Who founded Brian and how many employees are there?"}
            )
            assert unsupported.structuredContent["no_results"] is True
            assert unsupported.structuredContent["hits"] == []
            cli_unsupported = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable,
                    str(ROOT / "bin/wiki"),
                    "knowledge",
                    "query",
                    "Who founded Brian and how many employees are there?",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            assert cli_unsupported.returncode == 0, cli_unsupported.stderr
            assert json.loads(cli_unsupported.stdout) == unsupported.structuredContent

    asyncio.run(exercise())


def test_real_stdio_server_queries_resources_errors_and_applies_losslessly(tmp_path: Path) -> None:
    dogfood_root = _copy_dogfood_repo(tmp_path)

    async def exercise() -> None:
        environment = os.environ.copy()
        environment["WIKI_ROOT"] = str(dogfood_root)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "internal/mcp_server_wiki.py")],
            env=environment,
        )
        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "Brian Wiki"

            listed = await session.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert set(tools) == {
                "query_company_knowledge",
                "read_company_page",
                "apply_knowledge_update",
            }
            assert all(tool.outputSchema for tool in tools.values())
            assert tools["query_company_knowledge"].annotations.readOnlyHint is True
            assert tools["apply_knowledge_update"].annotations.destructiveHint is True

            query = await session.call_tool("query_company_knowledge", {"question": "wiki company info"})
            assert not query.isError
            assert query.structuredContent["hits"][0]["title"] == "Brian Labs"

            invalid = await session.call_tool("read_company_page", {"path": "../AGENTS"})
            assert invalid.isError

            templates = await session.list_resource_templates()
            assert [str(template.uriTemplate) for template in templates.resourceTemplates] == [
                "wiki://page/{folder}/{slug}"
            ]
            resource = await session.read_resource("wiki://page/entities/brian-org")
            assert "Brian Labs builds continuous safety infrastructure for clinical AI" in resource.contents[0].text

            source = "# Exact heading\n\nUnicode: naïve → β\n\n```sql\nselect  *  from x;\n```\nNo trailing newline"
            placeholder = "{{SOURCE_PATH}}"
            brian_path = dogfood_root / "wiki/entities/brian-overview.md"
            brian_content = brian_path.read_text(encoding="utf-8").replace(
                "## Provenance and status",
                "Dogfood-only validation links [[Dogfood Knowledge]].\n\n## Provenance and status",
            )
            brian_content += f"\nDogfood validation source: `{placeholder}`.\n"
            new_page = f"""---
title: Dogfood Knowledge
type: concept
scope: company
summary: A temporary concept used to verify lossless MCP ingestion.
tags: [company, dogfood]
aliases: [lossless dogfood concept]
context_keys: [exact MCP ingestion dogfood]
updated: 2026-07-26
verified: false
---

# Dogfood Knowledge

This temporary verification node preserves source evidence and links to [[Brian Labs]].

## Provenance and status

Compiled from `{placeholder}`.
"""
            arguments = {
                "source_title": "MCP lossless dogfood",
                "source_content": source,
                "source_type": "dogfood",
                "page_changes": [
                    {"path": "wiki/entities/brian-overview.md", "content": brian_content},
                    {"path": "wiki/concepts/dogfood-knowledge.md", "content": new_page},
                ],
                "retrieval_cases": [
                    {
                        "query": "where is the exact MCP ingestion dogfood",
                        "relevance": {"dogfood-knowledge": 3},
                    }
                ],
                "confirmed": False,
            }
            preview = await session.call_tool("apply_knowledge_update", arguments)
            assert not preview.isError
            assert preview.structuredContent["status"] == "ready"
            source_path = preview.structuredContent["source_path"]
            assert not (dogfood_root / source_path).exists()
            assert not (dogfood_root / "wiki/concepts/dogfood-knowledge.md").exists()

            cli_preview = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(dogfood_root / "bin/wiki"), "knowledge", "update", "--input", "-"],
                input=json.dumps({key: value for key, value in arguments.items() if key != "confirmed"}),
                text=True,
                capture_output=True,
                check=False,
            )
            assert cli_preview.returncode == 0, cli_preview.stderr
            assert json.loads(cli_preview.stdout) == preview.structuredContent

            arguments["confirmed"] = True
            arguments["approval_digest"] = preview.structuredContent["approval_digest"]
            applied = await session.call_tool("apply_knowledge_update", arguments)
            assert not applied.isError
            assert applied.structuredContent["status"] == "applied"
            assert (dogfood_root / source_path).read_text(encoding="utf-8") == source

    asyncio.run(exercise())
    assert check_ingestion(dogfood_root, base=None).ok


def test_real_cli_rejects_changed_approval_then_applies_exact_payload(tmp_path: Path) -> None:
    dogfood_root = _copy_dogfood_repo(tmp_path)
    source = "CLI preserves this source exactly: naïve → β"
    brian_path = dogfood_root / "wiki/entities/brian-overview.md"
    brian_content = brian_path.read_text(encoding="utf-8").replace(
        "## Provenance and status",
        "CLI dogfood links [[CLI Knowledge]].\n\n## Provenance and status",
    )
    brian_content += "\nCLI dogfood source: `{{SOURCE_PATH}}`.\n"
    payload = {
        "source_title": "CLI dogfood",
        "source_content": source,
        "source_type": "dogfood",
        "page_changes": [
            {"path": "wiki/entities/brian-overview.md", "content": brian_content},
            {
                "path": "wiki/concepts/cli-knowledge.md",
                "content": """---
title: CLI Knowledge
type: concept
scope: company
summary: A temporary concept proving safe CLI ingestion.
tags: [company, dogfood]
aliases: [CLI ingestion dogfood]
context_keys: [exact CLI knowledge update]
updated: 2026-07-26
verified: false
---

# CLI Knowledge

This verification node links to [[Brian Labs]].

## Provenance and status

Compiled from `{{SOURCE_PATH}}`.
""",
            },
        ],
        "retrieval_cases": [{"query": "where is the exact CLI knowledge update", "relevance": {"cli-knowledge": 3}}],
    }
    command = [sys.executable, str(dogfood_root / "bin/wiki"), "knowledge", "update", "--input", "-"]
    preview = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True, check=False)
    assert preview.returncode == 0, preview.stderr
    ready = json.loads(preview.stdout)
    assert ready["status"] == "ready"
    assert not (dogfood_root / ready["source_path"]).exists()

    changed = {**payload, "source_title": "Changed after approval"}
    rejected = subprocess.run(
        [*command, "--approve", ready["approval_digest"]],
        input=json.dumps(changed),
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "does not match" in json.loads(rejected.stderr)["error"]["message"]
    assert not (dogfood_root / ready["source_path"]).exists()

    applied = subprocess.run(
        [*command, "--approve", ready["approval_digest"]],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["status"] == "applied"
    assert (dogfood_root / ready["source_path"]).read_text(encoding="utf-8") == source
    assert check_ingestion(dogfood_root, base=None).ok
