---
name: llm-wiki
description: Ground work in Brian's curated company knowledge. Use at the start of work and for questions about Brian, its products, partners, customers, commercial or clinical work, strategy, or research.
---

# Brian LLM Wiki Protocol

The Brian wiki at `$(wiki root)` is curated company knowledge, not code documentation or a raw archive.

Use the injected company context as the starting point. Query the wiki proactively, without waiting for the user,
when the requested specificity or freshness exceeds the available evidence, or when a citation is requested. Treat
partner, legal, and financial status, along with answers that will be acted on or repeated externally, as
freshness-sensitive. When curated evidence is unverified or explicitly requires source verification, querying is
only the first step: verify the owning record or repository before consequential use. Otherwise, do not query
ritualistically.

```bash
wiki context "$PWD"
wiki knowledge query "<question>"
wiki knowledge read "<path, URI, title, [[Wikilink]], or stem>"
```

When grounding is needed, search, read relevant pages, and follow wikilinks until the evidence is sufficient. Cite pages as `[[Wikilink]]`.
If curated knowledge does not support an answer, say so.

For source-backed updates:

1. Query and read existing coverage.
2. Inspect evidence with `wiki knowledge sources [raw/path]`.
3. Preview one complete payload with `wiki knowledge update --input <payload.json>`.
4. Repair `needs_revision` diagnostics until the preview is `ready`.
5. Explain the substantive changes and wait for explicit user approval.
6. Apply the unchanged payload with
   `wiki knowledge update --input <payload.json> --approve <approval_digest>`.

The engine owns lossless source capture, source accounting, generated files, validation, and rollback. It never
commits or pushes.
