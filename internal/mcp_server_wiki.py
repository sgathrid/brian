"""Local MCP interface for querying and curating the Brian company wiki."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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
from wikicli.core.ingest import (
    apply_knowledge_update as apply_update_request,
)

SERVER_INSTRUCTIONS = """Brian Wiki is curated company knowledge, not code documentation or a raw archive.
For company, product, clinical, partner, or research questions, call query_company_knowledge first.
Read only the most relevant pages when their summaries are insufficient, and cite answers as [[Page Title]].
Never present raw source material as curated truth.

Before apply_knowledge_update:
1. Call list_company_sources / inspect_company_source when the evidence may already live under raw/.
2. Search existing coverage, then propose page changes and claim dispositions to the user.
3. Preview with no approval_digest (or confirmed=false). Valid-but-failing proposals return
   status=needs_revision with structured diagnostics — fix and retry; do not treat that as a hard tool crash.
4. After explicit user approval, resend the same payload with approval_digest from the ready preview.

Provide exactly one source: existing_source_path for an immutable file under raw/, or source_content for new
user-confirmed context. Exact content matches reuse an existing raw path automatically. Page content may cite
`{{SOURCE_PATH}}`; the engine also renders missing provenance citations. Retrieval relevance accepts page stems,
wiki/... paths, or wiki://page/... URIs. Unrelated unclassified raw files are reported as repository debt and do
not block an otherwise valid update. This server never commits or pushes changes."""

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
def query_company_knowledge(question: str, limit: int = 5) -> knowledge.KnowledgeQueryResult:
    """Find curated company knowledge for a natural-language question.

    Use this for questions about Brian, its products, projects, partners, clinical work, or research.
    The result contains ranked canonical pages; it does not search raw source archives.
    """
    return knowledge.query_company_knowledge(REPO_ROOT, question, limit)


@mcp.tool(
    title="Read company knowledge page",
    annotations=READ_ONLY,
)
def read_company_page(path: str) -> knowledge.KnowledgePageResult:
    """Read one curated page returned by query_company_knowledge.

    Accepts either its `wiki/...` path or canonical `wiki://page/...` URI. Raw sources are intentionally
    excluded because they have not necessarily been verified or incorporated into company knowledge.
    """
    return knowledge.read_company_page(REPO_ROOT, path)


@mcp.tool(
    title="List company raw sources",
    annotations=READ_ONLY,
)
def list_company_sources() -> RawSourceListResult:
    """List classified and unclassified raw sources available for curation.

    Results are inventory metadata for evidence selection. They are not curated company knowledge.
    Use inspect_company_source before citing content from an unclassified file.
    """
    return RawSourceListResult(sources=list_raw_sources(REPO_ROOT))


@mcp.tool(
    title="Inspect company raw source",
    annotations=READ_ONLY,
)
def inspect_company_source(path: str, max_chars: int = 20000) -> RawSourceInspectResult:
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
    description="A curated Brian Wiki page selected from query_company_knowledge results.",
    mime_type="text/markdown",
)
def company_knowledge_page(folder: str, slug: str) -> str:
    return knowledge.read_company_page(REPO_ROOT, f"{folder}/{slug}").content


@mcp.tool(
    title="Preview or apply company knowledge update",
    annotations=CURATION,
)
def apply_knowledge_update(
    source_title: str,
    page_changes: list[PageChange],
    retrieval_cases: list[RetrievalCase],
    source_content: str | None = None,
    existing_source_path: str | None = None,
    source_type: str = "user-confirmed context",
    confirmed: bool | None = None,
    approval_digest: str | None = None,
) -> KnowledgeUpdateResult:
    """Validate and optionally apply a source-backed update to curated company knowledge.

    First call without approval_digest (or with confirmed=false) to preview. status=ready means the
    complete update passes every ingestion gate without writing. status=needs_revision returns structured
    diagnostics the agent should fix. After explicit user approval, call the same payload with
    approval_digest from the ready preview (confirmed=true remains accepted for compatibility).
    Provide exactly one source: existing_source_path for an immutable file already under raw/, or
    source_content for new user-confirmed context. Exact duplicates reuse existing raw paths.
    Use `{{SOURCE_PATH}}` in page provenance sections; missing citations are rendered by the engine.
    Retrieval relevance accepts stems, wiki paths, or wiki:// URIs. The server writes no partial update
    and never commits.
    """
    if confirmed is False:
        approval_digest = None
        apply_flag = False
    elif confirmed is True:
        apply_flag = True
    else:
        apply_flag = None
    request = KnowledgeUpdateRequest(
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=page_changes,
        retrieval_cases=retrieval_cases,
        approval_digest=approval_digest,
    )
    return apply_update_request(REPO_ROOT, request, apply=apply_flag)


if __name__ == "__main__":
    mcp.run()
