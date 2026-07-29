<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian_dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian.svg">
    <img src="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian.svg" alt="Brian" width="400">
  </picture>
</p>

<h1 align="center"></h1>

<p align="center">
  <strong>Stop copy-pasting context between chats.</strong><br>
  One company knowledge base your AI tools actually use.
</p>

<p align="center">
  Plain English · Works with the agents you already have · You approve every change · No vector DB
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#day-to-day">Day-to-day</a> ·
  <a href="#customize-in-plain-english">Customize</a> ·
  <a href="#works-with-your-tools">Integrations</a> ·
  <a href="#faq">FAQ</a>
</p>

<p align="center">
  <sub>Inspired by <a href="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f">Karpathy’s LLM Wiki</a> pattern</sub>
</p>

> [!IMPORTANT]
> **A living company brain — not a code docs site.**
> Brian holds decisions, product truth, policies, client context, and the stuff that usually lives in Slack threads and people's heads. Agents read and draft updates as you work. You approve writes, then `git push` when you're ready to share.


## Why Brian

Every AI session starts from zero. So you paste the same briefs, policies, and “remember when we decided…” notes into Claude, Cursor, ChatGPT, and email drafts — again and again.

**Brian is where that context lives once.**

- One git-backed knowledge base in plain English
- Wired into your coding agents (or copy-pasted into any chat)
- Updated as you work — only when you say yes

Not a RAG platform. Not another chatbot. A persistent company brain your tools can finally remember.

The idea follows [Andrej Karpathy’s LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern: don’t re-discover knowledge from raw files on every question — maintain a compounding markdown wiki the LLM keeps current. Brian turns that pattern into a **shared company brain** with installable agent hooks, governed updates, and git sync.

## What you can do

- **Stop re-explaining the business** — agents load relevant context when a session starts
- **Ask in plain English** — “What did we decide about SSO?” → cited answers, not guesses
- **Draft like your company** — emails and docs that match policy and voice
- **Reference real sources** — prior decisions and notes, not reinvented context
- **Copy context anywhere** — same brain in tools that don’t have hooks yet
- **Edit it yourself** — readable markdown you can search and change
- **Stay in control** — every agent write is previewed and approved; git is source of truth

---

## Quickstart

### 1. Clone and install

```bash
git clone git@github.com:<you>/brian.git
cd brian
uv sync
```

<details>
<summary><strong>Don’t have <code>uv</code>?</strong></summary>

<br>

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**macOS (Homebrew)**

```bash
brew install uv
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then continue with `uv sync` above.  
`uv` is a fast Python package manager — [install docs](https://docs.astral.sh/uv/getting-started/installation/).

</details>

### 2. Configure your knowledge base

```bash
wiki init
```

An interactive setup guides you through your **use case** (Company, IT helpdesk, Engineering, Research, or Personal), **organization name**, and optional extras:

- **Agent behavior** — multi-select with ↑↓ / space (people tracking, assets, ADRs, …)
- **What agents offer to save** — plain-English triggers & instructions (`[upkeep]`)

Defaults are fine for most teams; advanced steps are opt-in. Re-run `wiki init` anytime — current values are pre-selected, and your overview page + hand-edited upkeep text are preserved.

*(For automated or non-interactive setups, see [Customize](#customize) below.)*

### 3. Connect your AI tools

```bash
uv run wiki install
# afterward: wiki install
```

The installer detects what’s on your machine and hooks your configured knowledge base into your tools:

```text
┌ Brian Wiki Setup
│
│  Which agent integrations do you want to configure?
│
│ ❯ ○ Claude Code (detected)
│   ○ Codex CLI (detected)
│   ● Gemini CLI (✓ active)
│   ○ GitHub Copilot CLI (detected)
│   ○ Cursor & VS Code (detected)
│   ● Google Antigravity (✓ active)
└
```

### 4. Populate your knowledge base

Start adding knowledge in two ways:

- **Conversational (Quick & Direct):** Tell any connected agent in plain English:
  > “Add our refund policy to the wiki: 30-day money-back guarantee, contact support@acme.com.”
  > “Here is our tech stack: Python, FastAPI, and Postgres. Create our architecture pages.”

- **Document Ingestion (`raw/` Inbox):** Drop existing specs, PDFs, or handbooks into the `raw/` folder (a local, git-ignored inbox), then ask your agent:
  > “Ingest `raw/employee_handbook.pdf` into the wiki.”

  The agent synthesizes raw documents into structured markdown under `wiki/` with source provenance citations (`Compiled from raw/...`).

> [!TIP]
> **Seed 2–3 core docs for better cross-linking:** Ingesting a few foundational documents upfront (e.g., product overview, tech stack spec, team directory) establishes the initial web of `[[Wikilinks]]` and tags. This helps agents automatically connect subsequent notes to the right context.

### 5. Try it

In any connected agent:

> “What should a new hire know about our product and how we work?”

> “Draft a short customer reply using our refund policy. Keep our usual tone.”

<details>
<summary><strong>Copy-paste only</strong> — no agent hooks</summary>

<br>

1. Browse `wiki/index.md` and pages under `wiki/`
2. Paste what you need into ChatGPT, Claude.ai, or any chat
3. Run `wiki install` later when you want auto-loaded context

Hooks just automate finding, citing, and proposing updates.

</details>

---

## Day-to-day

### Coding sessions that already know the company

Connected agents get a short catalog of relevant pages on session start.

> “Which services own authentication, and how do we invalidate sessions?”

The agent queries Brian, reads ranked pages, and answers with `[[Wikilink]]` citations — instead of inventing architecture from the repo alone.

### Draft emails and docs from real context

> “Draft a reply about invoicing. Use our billing policy and customer-comms tone.”

The agent pulls the right pages and can show what it used.

### Capture decisions before they disappear

When a chat produces something durable:

1. Agent drafts a knowledge update
2. You see which pages would change
3. You approve, edit, or reject
4. Brian writes markdown locally (sources tracked)
5. You `git commit` + `git push` when ready

Nothing is committed or pushed for you.

```bash
cd path/to/brian
git status
git commit -m "docs: capture SSO decision and billing policy note"
git push origin main
```

Clean checkouts can fast-forward upstream with `wiki sync`.

---

## How system instructions work

Brian is **English-driven end to end** — setup, daily use, and customization should feel like editing docs, not configuring search infrastructure.

### What `wiki install` does

It adds a short instruction block (and shared skill) to each tool you pick. In plain language:

1. Company knowledge lives in Brian at `$(wiki root)`
2. Need context → `wiki context`, `wiki knowledge query`, `wiki knowledge read`
3. Cite `[[Wikilinks]]` — don’t invent company facts
4. Durable new knowledge → draft an update, show the human, apply only after approval
5. Never commit or push the wiki yourself

No proprietary memory cloud. No embedding pipeline to run.

### What happens in a session

```text
open a repo / start a chat
        ↓
agent loads a short catalog of relevant pages
        ↓
you ask a question or request a draft
        ↓
agent queries/reads more only as needed
        ↓
if something should be remembered → agent proposes a change
        ↓
you approve → Brian writes markdown locally
```

### Why this stays easy

| Piece | What it is | How you change it |
|---|---|---|
| **Knowledge** | Markdown under `wiki/` | Edit like any doc |
| **Org setup** | `wiki.toml` + company overview | `wiki init` or edit files |
| **Agent behavior** | Short system/skill instructions | Re-run `wiki install` |
| **Sharing** | Git | `commit` / `push` / `pull` |

If you can edit a README, you can customize Brian.

---

## Customize in plain English

### Company overview

After `wiki init`, start with the overview under `wiki/entities/`. Write like you’re briefing a sharp new hire:

```markdown
# Acme Overview

Acme builds scheduling software for specialty clinics.

## Product
- Core app: care-team scheduling + patient reminders
- We do not build billing ERPs — we integrate

## Voice
- Clear, calm, no hype
- Short sentences in customer email

## Decisions worth knowing
- SSO is SAML-first for enterprise (2026-03)
- Refunds: 30 days on unused seats; enterprise follows the MSA
```

### Add pages when truth appears

```text
wiki/
├── entities/     # companies, people, teams, products
├── concepts/     # policies, processes, domain ideas
├── projects/     # active work, pitches, engagements
└── syntheses/    # rolled-up summaries
```

Ordinary headings, bullets, and links. Agents follow `wiki/CONVENTIONS.md` when they propose structure — you don’t need a schema to get value.

### Agent behavior rules (`wiki.toml`)

Optional switches that change what agents try to remember. **Off by default** for a general company brain (including people tracking).

**During `wiki init`:** choose **Customize agent behavior**, then multi-select with ↑↓ / **space** / enter. Same control language as Yes/No confirms (enter or space).

Or edit `wiki.toml`:

```toml
[wiki]
# Empty = no extra behaviors (good default for most companies)
agent_rules = []

# Turn people tracking on:
# agent_rules = ["people_tracking"]

# IT-style setup:
# agent_rules = ["people_tracking", "asset_tracking", "security_notice"]
```

| Rule ID | Plain English | Extra |
|---|---|---|
| `people_tracking` | Keep pages for teammates, roles, and who owns what | Soft person-page shape guidance |
| `asset_tracking` | Laptops, asset tags, licenses, access request SOPs | Soft asset-page shape guidance |
| `security_notice` | Never write passwords/API keys into wiki pages | — |
| `adrs` | Record architecture decisions (context → decision → consequences) | Soft ADR shape guidance |
| `strict_sources` | Every new claim should cite a file under `raw/` | — |
| `quick_capture` | Turn messy notes into linked topic pages quickly | — |

Enabled rules ship as session-start bullets; some also add short **page-shape guidance** (still soft — ingest validation stays fixed).

After editing:

1. Save `wiki.toml`
2. Either re-run `wiki init -y` (refreshes agent pointer text) **or** just start a new agent session — the SessionStart hook reads `agent_rules` + `[upkeep]` live
3. Or re-run `wiki init` interactively and multi-select behaviors again (current rules are pre-checked)

```bash
# Same thing from the CLI:
wiki init --rules people_tracking,security_notice -y
```

### What’s worth saving (`[upkeep]`)

Controls **how proactive** agents are, **when** they offer a wiki update, and **how** they phrase it.

During `wiki init` you pick a proactivity posture (always shown):

| `proactivity` | Meaning |
|---|---|
| `selective` | Durable, high-signal changes only (default; use-case trigger preset) |
| `active` | Offer updates often; still ask first |
| `capture` | Prefer logging — treat most durable context as worth saving |
| `silent` | Only update when the user asks |

Session start always injects **both** triggers and instructions (plus the proactivity label). Agents still ask before writing and never auto-commit.

```toml
[upkeep]
proactivity = "selective"  # or active | capture | silent
triggers = [
    "A functionality-changing PR — new or renamed abstraction, changed architecture or data flow, a decision worth remembering",
    "Authoring or substantially revising a project document (.md, .html, .pdf) — spec, application, report",
]
instructions = """
Then say which page to add or update and why, and let the user decide. Never commit or push the wiki yourself.
Refactors, dependency bumps, tests and formatting need nothing — 'already current' is a valid answer; do not invent work.
"""
```

Examples of good triggers (plain English):

- Shipping a user-visible feature or API change
- Updating a customer-facing policy or pricing doc
- Closing a decision in a design review

Want “log everything durable”? set `proactivity = "capture"` (or pick it in init). Want quiet agents? use `silent`.

Hand-edited `[upkeep]` text is **kept** when you re-run `wiki init` unless you change posture or opt into editing triggers/instructions again.

### Other knobs

- **Org name / description** → `wiki.toml` or `wiki init`
- **Connected tools** → `wiki install` / `wiki uninstall`
- **How agents talk about the wiki** → `_templates/agent-pointer.md` + `internal/skills/wiki-context/`

**Re-running `wiki init`:** current values are pre-selected. Overview pages and custom upkeep are preserved; `wiki.toml` is rewritten with your choices; the agent pointer + catalog indexes refresh.

Everything important is text. Fork it and make it yours.

---

## Works with your tools

| Tool | What you get |
|---|---|
| **Claude Code** | Session-start context, skill, `/wiki-*` commands |
| **Claude Desktop** | Read/write via local MCP server |
| **Codex CLI** | Session-start context + shared skill |
| **Gemini CLI** | Session-start context + shared skill |
| **GitHub Copilot CLI** | Instruction pointer in global Copilot instructions |
| **Cursor & VS Code** | Shared `wiki-context` skill |
| **Google Antigravity** | Shared CLI pointer via `@import` |
| **Any other chat** | Copy pages from `wiki/` |

Same brain. Many front doors.

---

## What this is / isn’t

| Brian | Not Brian |
|---|---|
| Central company knowledge agents load | A chatbot with its own UI |
| Plain markdown in git | A hosted RAG / vector-DB platform |
| Memory for drafts, decisions, onboarding | Silent auto-memory that writes without you |
| Works with Claude, Cursor, Codex, Gemini, … | Lock-in to one vendor’s project files |
| You approve writes; you push when ready | A black-box index you can’t read |

---

## For agents & power users

<details>
<summary><strong>CLI cheatsheet</strong></summary>

<br>

Agents use these on your behalf; handy for debugging:

| Command | Purpose |
|---|---|
| `wiki init` | Create `wiki.toml` + company overview |
| `wiki install` / `wiki uninstall` | Manage agent integrations |
| `wiki status` | Hook health + git sync status |
| `wiki context "$PWD"` | Rank pages for a directory or task |
| `wiki knowledge query "<question>"` | Ranked JSON over curated pages |
| `wiki knowledge read "<path>"` | Read one page as structured JSON |
| `wiki knowledge update --input <file.json>` | Preview a governed update |
| `wiki knowledge update --input <file.json> --approve <digest>` | Apply after approval |
| `wiki sync` | Fetch + fast-forward clean checkouts |
| `wiki root` | Print the Brian repo path |

Updates always preview first, need an approval digest, track sources, and never commit or push.

</details>

<details>
<summary><strong>Repo layout</strong></summary>

<br>

```text
brian/
├── bin/                 # CLI entry points
├── wikicli/             # Python engine & integrations
├── commands/            # Agent slash-command prompts
├── _templates/          # Instruction & page templates
├── internal/
│   ├── mcp_server_wiki.py
│   └── skills/wiki-context/
├── wiki/                # Your plain-English knowledge base
│   ├── CONVENTIONS.md
│   ├── entities/
│   ├── concepts/
│   ├── projects/
│   └── syntheses/
├── raw/                 # Source capture / inbox
└── wiki.toml            # Org name, paths, upkeep triggers
```

**Engine** (installers, hooks, CLI, MCP) stays separate from **content** (`wiki/`).

</details>

---

## FAQ

**Do I need embeddings, a vector DB, or a cloud account?**  
No. Local markdown + a small CLI. Git syncs it.

**Who can change the brain?**  
You (and your team). Agent writes need explicit approval. Direct file edits work too.

**Is this only for engineers?**  
No. Anyone who drafts email, answers clients, onboards people, or keeps decisions straight. Coding agents are just the best-integrated clients today.

**What if my tool isn’t supported?**  
Copy from `wiki/`, or point any agent at `_templates/agent-pointer.md`. PRs welcome.

**Will agents invent company policy?**  
They’re told to query first and admit gaps. Writes still need your OK — skim before approving.

**How do teams stay in sync?**  
Normal git: pull, review, push. `wiki sync` helps clean checkouts fast-forward `main`.

**Can I keep this private?**  
Yes. Private remote, no SaaS login required.

---

## Credits

Brian is inspired by [**Andrej Karpathy’s LLM Wiki**](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the pattern of a persistent, LLM-maintained markdown wiki between you and raw sources, so knowledge compounds instead of being re-derived every chat.

Brian builds on that idea for **teams and everyday agent use**: installable integrations, approval-gated writes, and a company knowledge base you customize in plain English.

---

## License

MIT
