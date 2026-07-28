---
title: "{{title}}"
type: {{type}}                # entity | concept | synthesis | reference
scope: {{scope}}              # global | company | project | engineering | research | branding
tags: [{{tags}}]
repo: {{repo}}                # optional — git remote, for project/company pages
context_keys: [{{keys}}]      # optional — aliases the context resolver matches (repo names, task terms)
updated: {{date}}
review_by: {{review_by}}      # optional — explicit staleness signal (supersedes mtime)
verified: false              # set true once claims are checked against primary sources
---

# {{title}}

{{content}}
