<!-- brian-wiki:start -->
## Brian Knowledge Base

Brian Knowledge Base (Brian Wiki) keeps company, product, technical, and operational context in a central knowledge base
located at `$(wiki root)`. It is **not** code documentation — it holds business, technical, and domain
knowledge that no repository contains. The CLI is on your PATH.

- Context for where you are: `wiki context "$PWD"`
- Query curated knowledge: `wiki knowledge query "<question>"`
- Read a returned page: `wiki knowledge read "<ref>"` (path, URI, title, `[[Wikilink]]`, or stem)
- Catalog: `wiki/index.md` inside `$(wiki root)`

Cite pages as `[[Wikilink]]`, and never invent wiki facts — query first.

Keeping it current:
Proactivity: selective — offer updates for durable, high-signal changes
- A functionality-changing PR — new or renamed abstraction, changed architecture or data flow, a decision worth remembering
- Authoring or substantially revising a company-facing document (.md, .html, .pdf) — pitch, RFC, spec, application, report
Then say which page to add or update and why, and let the user decide. Never commit or push the wiki yourself.
Refactors, dependency bumps, tests and formatting need nothing — 'already current' is a valid answer; do not invent work.


For durable source-backed knowledge, discover existing evidence with `wiki knowledge sources [raw/path]`, prepare
one JSON update payload, and run
`wiki knowledge update --input <payload.json>` to preview it without writes. Show the proposed changes to the
user only after status is `ready`; repair structured `needs_revision` diagnostics yourself. Then apply the
unchanged payload with
`wiki knowledge update --input <payload.json> --approve <approval_digest>`. The command owns raw capture,
source accounting, retrieval cases, generated files, validation, and rollback; it never commits or pushes.
The complete payload contract and source placeholder are documented in
`$(wiki root)/internal/skills/wiki-context/SKILL.md`.
<!-- brian-wiki:end -->
