---
name: llm-wiki
description: Protocol for Brian's centralized context engine (the LLM Wiki). Triggers on tasks involving wiki context resolution, ingestion, querying, or health checks — and at the start of work in any repo.
---

# Brian LLM Wiki Protocol

The Brian wiki (located at `$(wiki root)`) is a centralized context engine holding company, product, clinical, and research context. It is **not** code documentation.

The wiki CLI is on your PATH (run the installer if not). Locate the repo with `wiki root`; all paths below are relative to that root.

## Architecture

- **`raw/`**: immutable source documents — LOCAL ONLY, never committed.
- **`wiki/`**: the curated knowledge graph (what agents read).
- **`internal/`**: capabilities catalog, agent skills, prompt templates.
- **`_templates/`**: agent pointer files and protocol documents.
- **Tools (on PATH)**: `wiki` (context, find, tags, audit, gen, ingest check).

## Day-to-Day Operations

1. **Resolve Working Context** (run when starting work in any repo):
   ```bash
   wiki context "$PWD"
   ```
2. **Search / Query**:
   ```bash
   wiki knowledge query "<question>"
   wiki knowledge read "<returned-path>"
   ```
   Results are deterministic JSON over curated pages only. Cite answers as `[[Wikilink]]`.

3. **Ingest Source Material**:
   - **Discover** existing coverage with `wiki knowledge query` and `wiki knowledge read`.
   - **Inspect evidence** with `wiki knowledge sources [raw/path]`; prefer an existing source path.
   - **Plan** atomic page updates, syntheses, links, claim dispositions, and novice-language questions.
   - **Preview** one complete JSON payload with `wiki knowledge update --input <payload.json>`.
   - **Repair** structured `needs_revision` diagnostics and preview again until status is `ready`.
   - **Approve**: show the plan to the user and wait for explicit approval.
   - **Apply** the unchanged payload with
     `wiki knowledge update --input <payload.json> --approve <approval_digest>`.
   - The command owns lossless raw capture, source accounting, generated files, validation, and rollback.
   - **Commit** only when the task is wiki-focused or the user asks: `git -C "$(wiki root)" add wiki/ && git -C "$(wiki root)" commit`.
