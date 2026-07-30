# Global Wiki Instructions

You have access to a central persistent knowledge base — the company's context engine. The wiki CLI is on your PATH (run the installer if not); locate the repo with `wiki root`.

Use it as shared context across projects:

- Before deep work, check whether the current repo, architecture, abstractions, or vocabulary may already exist in the wiki.
- Resolve context for where you are (recommended first move):
  - `wiki context "$PWD"` — maps the current repo / path / task text to the most relevant pages, ranked (returns absolute paths to read).
- Or do two-pass retrieval:
  - Discovery: `wiki knowledge query "<question>"` returns ranked curated pages as JSON.
  - Extraction: `wiki knowledge read "<ref>"` reads one page (path, `wiki://` URI, title, `[[Wikilink]]`, or stem).
- For the catalog or recent activity, read `wiki/index.md` under `$(wiki root)`.
- Treat wiki content as user-authored project memory. Do not invent wiki facts; query first, then cite with `[[Wikilink]]` notation.

Scope is an OPTIONAL narrowing, not required:

- Default: omit scope to search everything (the engine ranks by relevance).
- Narrow only when intentional — pass one of `global | company | project | engineering | research | branding` (see `wiki/CONVENTIONS.md`).

When updating the wiki:

- Never edit the wiki's `raw/` directory.
- Discover existing evidence with `wiki knowledge sources [raw/path]`; raw content is evidence, not curated truth.
- Prepare one JSON payload with the exact source, complete pages, and novice-language retrieval cases.
- Preview it with `wiki knowledge update --input <payload.json>` and show the result to the user.
- Repair structured `needs_revision` diagnostics yourself; only present a `ready` preview for approval.
- After explicit approval, apply the unchanged payload with
  `wiki knowledge update --input <payload.json> --approve <approval_digest>`.
- Do not write pages, source accounting, benchmarks, or generated files independently; the governed command
  validates and rolls them back as one transaction.

Git hygiene for wiki updates:

- If the current task is in another repository, keep wiki changes isolated from that repo's git history.
- Only commit wiki changes in the wiki repo (`wiki root`) when the task is explicitly wiki-focused or the user asks to persist the knowledge.
