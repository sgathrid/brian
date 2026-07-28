Run a mechanical health audit of the wiki and fix all issues found.

**Step 1 — Regenerate derived artifacts, then audit:**
- Run: `wiki gen` (rebuilds `wiki/index.md`, `wiki/tags.md`, `wiki/backlinks.md`, and `internal/registry.md`).
- Run: `wiki audit`

Display the full report to the user.

**Step 2 — Heal (fix each category):**
- Run: `wiki gen` (rebuilds `wiki/index.md`, `wiki/tags.md`, and `wiki/backlinks.md`).
- Run: `wiki audit`
- If dead links or schema errors are reported, fix them.

---

## Autonomous Protocol

1. **Rebuild**: run `wiki gen`
2. **Audit**: run `wiki audit`
3. **Classify and heal errors**:
   - **Dead wikilinks**: find candidate target page with `wiki find "<target>"`. If found, fix link; if not, create target page or remove dangling link.
   - **Missing frontmatter**: add required fields (`title`, `type`, `scope`, `tags`, `updated`).
   - **Scope vocabulary**: enforce `global | company | project | engineering | research | branding`.
4. **Final check**:
   - Re-run `wiki audit` → verify exit code 0.
   - Re-run `wiki gen` if any links/scopes changed.
   - Commit: `git -C "$(wiki root)" add wiki/ && git -C "$(wiki root)" commit -m "lint: automated health check"`

Report a before/after summary: how many issues were found vs. resolved.
