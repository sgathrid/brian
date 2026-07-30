"""Local MCP interface for querying and curating the Brian company wiki."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

REPO_ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent)).resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wikicli.core import knowledge
from wikicli.core.ingest import (
    KnowledgeUpdateRequest,
    KnowledgeUpdateResult,
    PageChange,
    RetrievalCase,
    inspect_raw_source,
    list_raw_sources,
)
from wikicli.core.ingest import update_knowledge as run_knowledge_update

SERVER_INSTRUCTIONS = """Brian Wiki is curated company knowledge, not code documentation or a raw archive.
Use available company context as the starting point. Call query_knowledge proactively, without waiting for the user,
when the requested specificity or freshness exceeds the available evidence, or when a citation is requested. Treat
partner, legal, and financial status, along with answers that will be acted on or repeated externally, as
freshness-sensitive. When curated evidence is unverified or explicitly requires source verification, querying is
only the first step: verify the owning record or repository before consequential use. Otherwise, do not query
ritualistically. When grounding is needed, search, read relevant pages, and follow wikilinks until the evidence is
sufficient. Cite answers as [[Page Title]]. If the curated pages do not support an answer, say so. Never present raw
source material as curated truth.

For updates, query existing coverage and use list_sources / inspect_source to find evidence. Call
update_knowledge without approval_digest to preview, repair any needs_revision diagnostics, explain the
substantive changes, and wait for explicit user approval. Then resend the unchanged payload with the ready
preview's approval_digest. Provide exactly one source: existing_source_path for an immutable file under raw/,
or source_content for new user-confirmed context. This server never commits or pushes changes."""

mcp = FastMCP("Brian Wiki", instructions=SERVER_INSTRUCTIONS)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CURATION = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


@dataclass(frozen=True)
class RawSourceListResult:
    sources: list[dict[str, Any]]


@dataclass(frozen=True)
class RawSourceInspectResult:
    path: str
    status: str
    pages: list[str]
    note: str
    content: str
    truncated: bool
    sha256: str
    label: str


@mcp.tool(
    title="Query company knowledge",
    annotations=READ_ONLY,
)
def query_knowledge(question: str, limit: int = 5) -> knowledge.KnowledgeQueryResult:
    """Find curated company knowledge for a natural-language question.

    Use this for questions about Brian, its products, projects, partners, clinical work, or research.
    The result contains ranked canonical pages; it does not search raw source archives.
    """
    return knowledge.query_knowledge(REPO_ROOT, question, limit)


@mcp.tool(
    title="Read company knowledge page",
    annotations=READ_ONLY,
)
def read_page(ref: str) -> knowledge.KnowledgePageResult:
    """Read one curated page returned by query_knowledge.

    Accepts a `wiki/...` path, canonical `wiki://page/...` URI, page title, wikilink, or page stem. Raw
    sources are excluded because they have not necessarily been incorporated into company knowledge.
    """
    return knowledge.read_page(REPO_ROOT, ref)


@mcp.tool(
    title="List company raw sources",
    annotations=READ_ONLY,
)
def list_sources() -> RawSourceListResult:
    """List classified and unclassified raw sources available for curation.

    Results are inventory metadata for evidence selection. They are not curated company knowledge.
    Use inspect_source before relying on content from an unclassified file.
    """
    return RawSourceListResult(sources=list_raw_sources(REPO_ROOT))


@mcp.tool(
    title="Inspect company raw source",
    annotations=READ_ONLY,
)
def inspect_source(path: str, max_chars: int = 20000) -> RawSourceInspectResult:
    """Read one raw source as evidence for curation.

    Path must be under raw/ and max_chars must be non-negative. The payload is labeled evidence,
    not curated truth. Prefer sources discovered here via existing_source_path when applying an update.
    """
    payload = inspect_raw_source(REPO_ROOT, path, max_chars=max_chars)
    return RawSourceInspectResult(
        path=payload["path"],
        status=payload["status"],
        pages=list(payload["pages"]),
        note=str(payload.get("note") or ""),
        content=payload["content"],
        truncated=bool(payload["truncated"]),
        sha256=payload["sha256"],
        label=payload["label"],
    )


@mcp.resource(
    "wiki://page/{folder}/{slug}",
    name="company-knowledge-page",
    title="Company knowledge page",
    description="A curated Brian Wiki page selected from query_knowledge results.",
    mime_type="text/markdown",
)
def company_knowledge_page(folder: str, slug: str) -> str:
    return knowledge.read_page(REPO_ROOT, f"{folder}/{slug}").content


@mcp.tool(
    title="Preview or apply company knowledge update",
    annotations=CURATION,
)
def update_knowledge(
    source_title: str,
    page_changes: list[PageChange],
    retrieval_cases: list[RetrievalCase],
    source_content: str | None = None,
    existing_source_path: str | None = None,
    source_type: str = "user-confirmed context",
    approval_digest: Annotated[
        str | None,
        Field(
            description=(
                "Omit for preview. After explicit user approval, pass the digest returned by status=ready for "
                "the exact unchanged payload and repository state to apply."
            )
        ),
    ] = None,
) -> KnowledgeUpdateResult:
    """Validate and optionally apply a source-backed update to curated company knowledge.

    Omit approval_digest to preview. status=ready means the complete update
    passes every ingestion gate without writing; status=needs_revision returns structured diagnostics the
    agent should fix. After explicit user approval, call the same unchanged payload with approval_digest from
    that ready preview.
    Provide exactly one source: existing_source_path for an immutable file already under raw/, or
    source_content for new user-confirmed context. Exact duplicates reuse existing raw paths.
    Use `{{SOURCE_PATH}}` in page provenance sections; missing citations are rendered by the engine.
    Retrieval relevance accepts stems, wiki paths, or wiki:// URIs. The server writes no partial update
    and never commits.
    """
    request = KnowledgeUpdateRequest(
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=page_changes,
        retrieval_cases=retrieval_cases,
        approval_digest=approval_digest,
    )
    return run_knowledge_update(REPO_ROOT, request)


if __name__ == "__main__":
    mcp.run()
