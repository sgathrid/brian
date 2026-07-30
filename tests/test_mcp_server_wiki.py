from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import internal.mcp_server_wiki as server
from wikicli.core import knowledge
from wikicli.core.ingest import KnowledgeUpdateResult, PageChange, RetrievalCase


def _page(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\ntitle: "{title}"\ntype: concept\nscope: company\nsummary: Test page.\n'
        f"aliases: [{title}]\ncontext_keys: [{title}]\ntags: [test]\nupdated: 2026-07-26\n"
        f"verified: false\n---\n\n# {title}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def mcp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / "wiki").mkdir(parents=True)
    monkeypatch.setattr(server, "REPO_ROOT", root)
    return root


def test_query_loads_only_curated_wiki_and_returns_typed_hits(mcp_repo: Path) -> None:
    _page(mcp_repo / "wiki/concepts/needle.md", "Needle", "A uniquely searchable safety needle.")
    _page(mcp_repo / "outside.md", "Outside", "uniquely searchable safety needle")

    result = server.query_knowledge("safety needle")

    assert result.no_results is False
    assert result.hits[0].title == "Needle"
    assert result.hits[0].path == "wiki/concepts/needle.md"
    assert result.hits[0].uri == "wiki://page/concepts/needle"
    assert all(hit.title != "Outside" for hit in result.hits)


def test_query_formats_literal_matches(mcp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _page(mcp_repo / "wiki/concepts/literal.md", "Literal", "Exact phrase lives here.")
    monkeypatch.setattr(knowledge, "search_keywords", lambda *_args, **_kwargs: [])

    result = server.query_knowledge("Exact phrase")

    assert result.hits[0].summary == "Exact phrase lives here."
    assert result.hits[0].match_reasons[0].startswith("literal line ")


def test_read_accepts_supported_page_references(mcp_repo: Path) -> None:
    _page(mcp_repo / "wiki/concepts/needle.md", "Needle", "Curated content.")

    results = [
        server.read_page(ref)
        for ref in (
            "wiki/concepts/needle.md",
            "wiki://page/concepts/needle",
            "Needle",
            "[[Needle]]",
            "needle",
        )
    ]

    assert all(result == results[0] for result in results)
    assert "Curated content." in results[0].content


@pytest.mark.parametrize("path", ["../outside", "wiki/../outside", "raw/secret", "/tmp/outside"])
def test_read_rejects_paths_outside_curated_wiki(mcp_repo: Path, path: str) -> None:
    (mcp_repo / "outside.md").write_text("secret", encoding="utf-8")

    with pytest.raises((ValueError, FileNotFoundError)):
        server.read_page(path)


def test_mcp_exposes_typed_tools_with_behavior_annotations() -> None:
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}

    assert set(tools) == {
        "query_knowledge",
        "read_page",
        "list_sources",
        "inspect_source",
        "update_knowledge",
    }
    assert tools["query_knowledge"].annotations.readOnlyHint is True
    assert tools["read_page"].annotations.readOnlyHint is True
    assert tools["list_sources"].annotations.readOnlyHint is True
    assert tools["inspect_source"].annotations.readOnlyHint is True
    assert tools["update_knowledge"].annotations.destructiveHint is True
    assert tools["update_knowledge"].annotations.idempotentHint is False
    assert "hits" in tools["query_knowledge"].outputSchema["properties"]
    update_tool = tools["update_knowledge"]
    update_properties = update_tool.inputSchema["properties"]
    assert update_properties["page_changes"]["items"]["$ref"] == "#/$defs/PageChange"
    assert "source_content" in update_properties
    assert "existing_source_path" in update_properties
    assert "confirmed" not in update_properties
    assert "status=ready" in update_properties["approval_digest"]["description"]
    assert "Omit approval_digest to preview" in update_tool.description
    assert update_tool.outputSchema["properties"]["status"]["enum"] == ["needs_revision", "ready", "applied"]


def test_invalid_mcp_read_is_reported_as_tool_error(mcp_repo: Path) -> None:
    with pytest.raises(ToolError, match="invalid knowledge page reference"):
        asyncio.run(server.mcp.call_tool("read_page", {"ref": "../outside"}))


def test_mcp_rejects_out_of_range_source_inspection_limit(mcp_repo: Path) -> None:
    (mcp_repo / "raw").mkdir()
    (mcp_repo / "raw/source.md").write_text("evidence", encoding="utf-8")

    with pytest.raises(ToolError, match="max_chars"):
        asyncio.run(server.mcp.call_tool("inspect_source", {"path": "raw/source.md", "max_chars": -1}))


def test_update_tool_forwards_one_governed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_update(root: Path, request: object, *, apply: bool | None = None) -> KnowledgeUpdateResult:
        captured.update(root=root, request=request, apply=apply)
        return KnowledgeUpdateResult("ready", "raw/one.md", ["wiki/concepts/one.md"], ["validated"], "digest")

    monkeypatch.setattr(server, "run_knowledge_update", fake_update)
    changes = [PageChange("wiki/concepts/one.md", "complete page")]
    cases = [RetrievalCase("what is one", {"one": 3})]

    result = server.update_knowledge(
        "Existing evidence",
        changes,
        cases,
        existing_source_path="raw/one.md",
    )

    assert result.status == "ready"
    request = captured["request"]
    assert request.page_changes == changes
    assert request.existing_source_path == "raw/one.md"
    assert captured["apply"] is None


def test_server_instructions_require_proactive_company_grounding() -> None:
    instructions = " ".join(server.SERVER_INSTRUCTIONS.split())
    assert "without waiting for the user" in instructions
    assert "when the requested specificity or freshness exceeds the available evidence" in instructions
    assert "when a citation is requested" in instructions
    assert "partner, legal, and financial status" in instructions
    assert "answers that will be acted on or repeated externally" in instructions
    assert "verify the owning record or repository before consequential use" in instructions
    assert "Otherwise, do not query ritualistically" in instructions
    assert "follow wikilinks until the evidence is sufficient" in instructions
    assert "If the curated pages do not support an answer, say so" in instructions
