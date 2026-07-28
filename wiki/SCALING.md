---
title: "Scaling Playbook"
type: reference
scope: global
context_keys: [scaling, performance, thresholds]
tags: [meta, scaling, performance, context-engine]
updated: 2026-07-25
---

# Scaling Playbook

The wiki is correct and lean at dozens of pages. Build scaling mechanisms only when an observable threshold demands them.

## What is already scale-safe

- `wiki context` reads frontmatter without loading page bodies.
- `wiki find` builds one reusable in-memory index per resolver.
- `wiki gen` builds indices and backlinks in single passes over the corpus.
- The SessionStart catalog has a fixed character budget.
- `wiki ingest check` validates the complete graph and question set before commit.

## Next bottlenecks and triggers

### Hierarchical catalog — trigger: `index.md` exceeds its injection budget

Generate per-scope catalogs and inject only the top-level map plus situated pages. Agents can pull a scope catalog on demand.

### Persisted lexical index — trigger: more than 500 pages or measurable CLI latency

Have `wiki gen` emit a content-hashed search index. Continue falling back to live construction when the index is absent or stale.

### Incremental ingestion checks — trigger: full checks exceed one second

Validate changed pages and their graph neighborhood on the edit loop, while retaining a complete CI check before merge.

### Semantic retrieval — trigger: judged cold-start recall plateaus because vocabulary bridges cannot solve the misses

Add embeddings only with a corpus-sized judged benchmark, an abstention contract, deterministic cache invalidation, and a lexical fallback. The 20-page experiment improved top-rank accuracy but did not justify its runtime and operational cost.

## Principle

Scale the architecture to measured data, not ambition. See [[Wiki Conventions]] for the contracts these mechanisms must preserve.
