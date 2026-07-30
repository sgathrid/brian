Answer the following question by querying the wiki: $ARGUMENTS

Parse the input as: <question> [scope]
- Scope is OPTIONAL. If no scope is given, search ALL scopes — do not narrow. Only pass a scope when the user explicitly restricts the domain (e.g. `research`, `project`, `engineering`, `company`, `branding`, `global`).

Follow this two-pass retrieval procedure using the canonical structured interface:

**Pass 1 — Discovery (token-cheap):**
- Extract 2-4 keywords from the question.
- Run `wiki knowledge query "<question>"` — results are ranked, typed JSON over curated pages only.
- Report the returned paths (top-ranked first). Do NOT read them yet.

**Pass 2 — Extraction:**
- Read only the 3-5 most relevant results with `wiki knowledge read "<ref>"`
  (path, `wiki://` URI, title, `[[Wikilink]]`, or stem from the query hit).

**Answer:**
- Synthesize a direct answer to the question.
- Cite sources using [[Wikilink]] notation.
- If the query returns `"no_results": true`, say so clearly and offer to ingest a source.
