Compile source material into the company knowledge graph through the canonical CLI: $ARGUMENTS

The output is knowledge, not a Markdown copy of the source. Never edit governed files independently.

## 1. Inventory and discover

- Resolve `WIKI_ROOT` with `wiki root`; never hardcode it.
- Confirm every supplied source exists under `raw/` and do not modify it.
- Extract the entities, projects, concepts, decisions, and questions in the source.
- Search with several plain-language questions using `wiki knowledge query "<question>"`.
- Read the closest results with `wiki knowledge read "<path>"`. Prefer updating an existing node over creating a synonym.

## 2. Plan the knowledge operations before writing

State the proposed operations explicitly:

- pages to update;
- atomic entity, project, or concept pages to create;
- cross-source synthesis pages needed to answer a user question;
- links that express each relationship;
- novice-language questions that should retrieve every new page; and
- claims to keep, correct, drop, or mark unverified.

Do not use one source file as the blueprint for one wiki page. A source may feed several nodes, and a useful node may combine several sources.

## 3. Verify and triage claims

- **Keep:** authoritative or independently verified facts.
- **Correct:** close-but-wrong claims, using a primary source and a citation.
- **Drop:** unsupported, contradictory, or irrelevant claims.
- **Unverified:** useful internal or time-sensitive context that is clearly labeled as such.

Never convert a proposal, forecast, negotiation position, or intended capability into an accomplished fact.

## 4. Construct one update payload

Prepare JSON containing `source_title`, exactly one of `existing_source_path` or lossless `source_content`,
complete `page_changes`, and `retrieval_cases`. Page paths belong under `wiki/entities/`, `wiki/projects/`,
`wiki/concepts/`, or `wiki/syntheses/`. Every page requires:

```yaml
---
title: "Page Title"
type: entity|project|concept|reference|workflow|synthesis
scope: company|project|engineering|research|branding
summary: "The answer this page gives in one sentence."
aliases: [plain-language synonym]
context_keys: [phrases a newcomer might use]
tags: [tag1, tag2]
updated: YYYY-MM-DD
verified: true|false
---
```

- Link related nodes inline with `[[Wikilinks]]` and explain the relationship in prose.
- Add `## Provenance and status`; use `` `{{SOURCE_PATH}}` `` for this update's exact source.
- Include at least one realistic novice-language retrieval case for every new page.
- Do not retain personal contact details, boilerplate, or formatting noise unless they are themselves durable knowledge.

## 5. Preview, approve, and apply

```bash
wiki knowledge update --input <payload.json>
```

The preview performs every source-accounting, provenance, connectivity, retrieval, generation, and audit gate
without persistent writes. Present its complete plan and facts to the user. After explicit approval, apply the
unchanged payload with the returned digest:

```bash
wiki knowledge update --input <payload.json> --approve <approval_digest>
```

A changed payload or governed repository state invalidates approval. Failed applies roll back completely.

## 6. Persist deliberately

The command never commits or pushes. Commit only for a wiki-focused task or when the user asks. Report:

- sources incorporated, deferred, or rejected;
- pages created and updated;
- important claims corrected or dropped;
- cold-start quality from the check; and
- any unresolved evidence gaps.
