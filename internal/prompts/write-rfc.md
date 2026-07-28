---
title: "Prompt — Write an RFC"
type: prompt
scope: company
context_keys: [rfc, prompt, design-doc]
tags: [prompt, rfc, template]
updated: 2026-06-02
---

# Prompt — Write an RFC

Reusable template. Pull with `/wiki-query` or read directly. Fill the angle-bracket slots and hand the result to an agent.

```
Write an RFC for <CHANGE/FEATURE> in <REPO/PROJECT>.

First, resolve context: run `wiki context <repo path>` and read the top pages so the RFC
reflects existing architecture and conventions (cite them as [[wikilinks]]).

Structure the RFC as:
1. Context & problem — what prompts this, what breaks today, intended outcome.
2. Goals / non-goals — explicit, verifiable.
3. Proposed approach — the ONE recommended design (not a survey). Name files to touch.
4. Alternatives considered — and why rejected (one line each).
5. Risks & mitigations — including clinical-safety / PHI / compliance impact where relevant.
6. Verification plan — how we prove it works end-to-end.
7. Rollout — phasing, thresholds, backout.

Apply karpathy discipline: simplest design that works, surface assumptions, no speculative scope.
```
