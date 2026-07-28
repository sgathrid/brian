---
title: "Wiki Conventions"
type: reference
scope: global
tags: [meta, conventions, scope, context-engine, agentic-os]
updated: 2026-06-02
---

# Wiki Conventions

This wiki is the company's **centralized context engine**: a single brain that any agent — in any repo, reviewing any pitch — can consult to instantly resolve company, project, and related context. It is not a document catalogue. Optimize every page for *situated, lean, reachable* context.

## Scope vocabulary (controlled)

`scope:` partitions the brain. It is an **optional narrowing** for retrieval (default search spans all scopes), not a wall. Use exactly one value from this list; extend the list here before introducing a new scope.

| scope | use for |
| :--- | :--- |
| `global` | meta / navigation only: index, conventions, context-cascade |
| `company` | company identity, mission, org-wide knowledge (e.g. My Org) |
| `project` | a specific named project/product/repo (Pulsar, Topos, Compass, Pasteur) and its engineering internals |
| `engineering` | cross-cutting engineering standards, patterns, and internal skills not tied to one project |
| `research` | research / reference / domain knowledge (clinical, regulatory, scientific) |
| `branding` | brand, voice, marketing, and external-facing identity |

## Context-engine binding

Pages that correspond to a repo or a recurring work surface carry binding frontmatter so a foreign session can resolve *where it is* → *what the brain knows*:

```yaml
repo: git@github.com:Brian-Labs/pulsar.git   # git remote (portable), optional
context_keys: [pulsar, themars, mcp]        # aliases an agent's cwd or task text may match
```

Use the **git remote**, not a local path — the resolver matches the repo *basename* (`pulsar`) against the session cwd, so it works on any machine's checkout regardless of where it lives. The `wiki context <cwd-or-text>` resolver and the SessionStart hook use `repo:`, `context_keys:`, and `tags:` to surface the right page first.

## Page frontmatter

```yaml
---
title: "Page Title"
type: entity|concept|synthesis|reference|skill|prompt|project|workflow
scope: <one of the vocabulary above>
tags: [tag1, tag2]
repo: <optional>            # project/company pages
context_keys: [optional]    # project/company pages
updated: YYYY-MM-DD
review_by: YYYY-MM-DD        # optional; supersedes mtime as the staleness signal
verified: true|false         # optional; true once claims are checked against primary sources
---
```

`project` and `workflow` are part of the vocabulary because pages already use them meaningfully
(`pasteur-sbir-phase-i`, `compass-ui`, `pulsar-graves-dataset-analysis`). Generated navigation
files use `type: index` and are exempt from schema checks.

## Construction contract

The wiki is compiled knowledge, not a document archive. An ingestion may split one source across
several atomic nodes or combine several sources into one synthesis. Every content page must include
`summary`, `aliases`, `context_keys`, `tags`, `updated`, and `verified`, plus a
`## Provenance and status` section citing exact backticked `raw/...` paths.

`wiki/sources.json` is the durable coverage registry. Every local raw source is classified as
`incorporated`, `deferred`, or `rejected`; incorporated sources list all pages they support. Every
page must also be targeted by a realistic newcomer question in
`benchmarks/cold_start_cases.json`. Run `wiki gen` followed by `wiki ingest check` before committing.

- Link related pages inline using double-bracket wikilink syntax (link to a page by its title). Backlinks and tag-clusters are generated into `backlinks.md` and `tags.md` by `wiki gen` — do not hand-maintain them.
- Filenames are hyphenated-lowercase (`graves-disease.md`), never spaces.

## Agentic OS (`internal/`)

The `internal/` tree is the agent operating layer, not a second knowledge store:

- `internal/skills/` — internal skills (SKILL.md-compatible); source-of-truth in the repo, synced into each agent's skills directory by `wiki install`.
- `internal/prompts/` — reusable prompt templates, pulled on request.
- `internal/registry.md` — generated catalog of all OS capabilities (`wiki gen`).

Canonical company facts belong under `wiki/` and follow the full source, provenance, and retrieval contract. The
SessionStart company summary is derived from [[My Org]] rather than maintained independently under `internal/`.

### External skills

There is no vendoring wrapper. To adopt an external skill, add it under `internal/skills/`
yourself and re-run `wiki install`, which re-syncs the directory to every configured agent.
