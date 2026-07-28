<!-- brian-wiki:start -->
## Company knowledge base

My Org keeps company, product, clinical and research context in a central knowledge base
located at `$(wiki root)`. It is **not** code documentation — it holds business, product, clinical and research
knowledge that no repository contains. The CLI is on your PATH.

- Context for where you are: `wiki context "$PWD"`
- Query curated knowledge: `wiki knowledge query "<question>"`
- Read a returned page: `wiki knowledge read "wiki/<scope>/<page>.md"`
- Catalog: `wiki/index.md` inside `$(wiki root)`

Cite pages as `[[Wikilink]]`, and never invent wiki facts — query first.

For durable source-backed knowledge, prepare one JSON update payload and run
`wiki knowledge update --input <payload.json>` to preview it without writes. Show the proposed changes to the
user and wait for explicit approval. Then apply the unchanged payload with
`wiki knowledge update --input <payload.json> --approve <approval_digest>`. The command owns raw capture,
source accounting, retrieval cases, generated files, validation, and rollback; it never commits or pushes.
The complete payload contract and source placeholder are documented in
`$(wiki root)/internal/skills/wiki-context/SKILL.md`.

When a functionality-changing PR goes up, or you author or substantially revise a company-facing
document (`.md`, `.html`, `.pdf`), say which knowledge-base page should be added or updated and why,
then let the user decide. Never commit or push the wiki yourself. Refactors, dependency bumps, tests
and formatting need nothing — "already current" is a valid answer.
<!-- brian-wiki:end -->
