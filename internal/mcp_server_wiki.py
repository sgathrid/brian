"""Local MCP interface for querying and curating the Brian company wiki."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

REPO_ROOT = Path(os.environ.get("WIKI_ROOT", Path(__file__).resolve().parent.parent)).resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wikicli.core import knowledge
from wikicli.core.ingest import (
    KnowledgeUpdateResult,
    PageChange,
    RetrievalCase,
    update_knowledge,
)

SERVER_INSTRUCTIONS = """Brian Wiki is curated company knowledge, not code documentation or a raw archive.
For company, product, clinical, partner, or research questions, call query_company_knowledge first.
Read only the most relevant pages when their summaries are insufficient, and cite answers as [[Page Title]].
Never present raw source material as curated truth.
Before apply_knowledge_update, search for existing coverage, propose the page changes and claim dispositions
to the user, preview with confirmed=false, and call with confirmed=true plus the returned approval_digest
only after explicit approval. Page content may cite
`{{SOURCE_PATH}}`; the server substitutes the exact immutable source path. The update is applied only if
source accounting, provenance, graph connectivity, retrieval cases, and generated files all validate.
This server never commits or pushes changes."""

mcp = FastMCP("Brian Wiki", instructions=SERVER_INSTRUCTIONS)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CURATION = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


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
    confirmed: bool = False,
    approval_digest: str | None = None,
) -> KnowledgeUpdateResult:
    """Validate and optionally apply a source-backed update to curated company knowledge.

    First call with `confirmed=false` to prove the complete update passes every ingestion gate without writing.
    Present that plan to the user. Call the same payload with `confirmed=true` and the returned
    `approval_digest` only after explicit approval. Changed payloads and repository state are rejected.
    Provide exactly one source: `existing_source_path` for an immutable file already under `raw/`, or
    `source_content` for new user-confirmed context that must be captured verbatim under `raw/inbox/`.
    Use `{{SOURCE_PATH}}` in page provenance sections. The server writes no partial update and never commits.
    """
    return update_knowledge(
        REPO_ROOT,
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=page_changes,
        retrieval_cases=retrieval_cases,
        confirmed=confirmed,
        approval_digest=approval_digest,
    )


if __name__ == "__main__":
    mcp.run()
