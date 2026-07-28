---
name: wiki-context
description: Resolve company, project, and related context from the Brian Wiki (the company brain) from any repo.
---

# Using the Brian Context Engine

The Brian wiki is a centralized context engine. The CLI is on your PATH (find the repo any time with `wiki root`). A compact, situated catalog is already injected at session start; use these tools to pull more.

## Resolve where you are → what the brain knows

```bash
wiki context "$PWD"
```

Maps the current repo / a path / free task text (e.g. "reviewing an SBIR pitch on Graves") to the most relevant pages, ranked. Backed by each page's `repo:`, `context_keys:`, `aliases:`, and `tags:`.

## Query and read

```bash
wiki knowledge query "<question>"             # deterministic JSON with ranked curated pages
wiki knowledge read "wiki/projects/example.md" # deterministic JSON for one returned page
```

Read only the pages needed to answer. Cite them as `[[Page Title]]`. A query with `"no_results": true`
means the curated wiki does not support the question; do not fill the gap from incidental repository text.

## Source-backed updates

When a source or conversation contains durable company knowledge:

1. Query and read existing coverage before proposing changes.
2. Build one JSON payload containing `source_title`, exactly one of `source_content` or
   `existing_source_path`, complete `page_changes`, and `retrieval_cases`.
3. Preview without writing: `wiki knowledge update --input <payload.json>`.
4. Present the proposed changes and validation result to the user. Wait for explicit approval.
5. Apply the unchanged payload with the returned digest:
   `wiki knowledge update --input <payload.json> --approve <approval_digest>`.

```json
{
  "source_title": "User-confirmed product context",
  "source_content": "Exact source text",
  "source_type": "user-confirmed context",
  "page_changes": [{"path": "wiki/projects/example.md", "content": "Complete page Markdown"}],
  "retrieval_cases": [{"query": "What is the example product?", "relevance": {"example": 3}}]
}
```

For a source already under `raw/`, replace `source_content` with `existing_source_path`. Use
`{{SOURCE_PATH}}` in each affected page's provenance section; the command substitutes the exact source path.

The command captures new confirmed context verbatim under `raw/inbox/`, updates source accounting and
generated navigation, runs every ingestion gate, and rolls back failed applies. A changed payload or wiki
state invalidates approval. It never commits or pushes. See `wiki/CONVENTIONS.md` for page construction rules.

## Rules

- Consult the brain before answering questions about company strategy, a project, or a client engagement — don't guess from the repo alone.
- Treat curated pages as source-of-truth context. Use the governed update command rather than writing wiki,
  source-registry, benchmark, or generated files independently.
