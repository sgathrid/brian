<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian_dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian.svg">
    <img src="https://raw.githubusercontent.com/sgathrid/brian/main/resources/brian.svg" alt="Brian" width="400">
  </picture>
</p>

# Brian: Agentic Context & Knowledge Base Engine
_Your AI agents' shared long-term memory_

> [!IMPORTANT]
> **This is an AI-managed knowledge base — not source code documentation.**
> Brian holds decision logs, architecture notes, product concepts, and cross-project domain context across all your AI tools. You don't write or manage raw markdown files manually: your AI agents continuously query, synthesize, and curate context as you work, while you remain in control of approving changes and pushing to Git.

---

## Contents

- [Contents](#contents)
- [How It Works](#how-it-works)
- [Install](#install)
- [Supported Integrations](#supported-integrations)
- [Day-to-Day Workflow](#day-to-day-workflow)
- [Engine Architecture](#engine-architecture)
- [CLI Reference (For Debugging \& Agent Tooling)](#cli-reference-for-debugging--agent-tooling)
- [License](#license)

---

## How It Works

1. **Automated Context Ingestion**: When you open a coding session in any project repository, your AI tools (Claude Code, Gemini CLI, Cursor, Antigravity, etc.) automatically load situated context from Brian without manual effort.
2. **LLM-Driven Knowledge Curation**: As you make architectural decisions, write specs, or discuss project context during agent chats, your LLM automatically drafts, structures, and validates updates to the knowledge base.
3. **Governed Human Approval**: Before any change is written to disk, the LLM previews the exact changes and requests your approval. Upon approval, Brian's engine transactionally applies the update with full provenance, cross-linking, and index generation.
4. **Git Sync & Team Sharing**: All updates are saved to your local `brian` repository. The engine automatically fetches and fast-forwards upstream changes (`origin/main`) in the background. When ready, you simply `git push` your local `brian` repository to share the updated brain with your team.

---

## Install

Clone the Repo + Initialize Environment
```bash
git clone git@github.com:<your-username>/brian.git
cd brian
uv sync
```

Install Brian in your AI Code Tools:
```bash
wiki install

# OR via uv without virtualenv setup:
uv run bin/wiki install
```

The interactive installer auto-detects installed AI tools on your system:

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

---

## Supported Integrations

| Agent / Environment | Delivery Flavor | Mechanism |
|---|---|---|
| **Claude Code** | Live context + governed read/write | `SessionStart`, shared CLI skill, and `/wiki-*` commands |
| **Claude Desktop** | On-demand read/write | Local MCP server in `claude_desktop_config.json` |
| **Codex CLI** | Live context + governed read/write | `SessionStart` + shared CLI skill |
| **Gemini CLI** | Live context + governed read/write | `SessionStart` + shared CLI skill |
| **Copilot CLI** | Static pointer | Instructions block in `~/.copilot/copilot-instructions.md` |
| **Cursor & VS Code** | Static pointer | Skill symlink in `~/.agents/skills/wiki-context` |
| **Google Antigravity** | Governed read/write | Shared CLI pointer via `@import` in `~/.gemini/GEMINI.md` |

---

## Day-to-Day Workflow

### 1. Agents Know Your Context Automatically
In any project repo, your AI assistant starts sessions with a situated catalog of your company's projects, architectural decisions, and domain knowledge already injected.

When you ask questions like:
> *"What microservices handle user authentication and how are sessions invalidated?"*

The LLM queries Brian in the background using its `wiki-context` skill and returns authoritative, source-backed answers without hallucinating from code alone.

### 2. LLMs Update the Brain as You Work
When a conversation produces new architecture choices, product context, or technical decisions:

1. **LLM Drafts Payload**: The agent extracts entities, decisions, and retrieval keywords, structuring them into a governed JSON update payload.
2. **Ingestion Gates & Preview**: The agent runs `wiki knowledge update --input payload.json` to validate link integrity, check provenance, update navigation indexes, and generate a preview.
3. **User Approval**: The agent asks you: *"I've drafted a knowledge update for Brian (3 pages modified, 1 created). Should I apply it?"*
4. **Transactional Apply**: Upon your approval, the agent executes the update with the generated approval digest.

### 3. Review & Push to Git
Brian's engine updates the local `brian` repository worktree. To share updates with your team or remote repo:

```bash
cd path/to/brian
git status
git commit -m "docs: add authentication session-invalidation architecture decision"
git push origin main
```

Clean local checkouts automatically fetch and fast-forward upstream changes in the background via `wiki sync`.

---

## Engine Architecture

Brian separates **Engine** (CLI logic, installers, MCP server, integration hooks) from **Knowledge Base Content** (`wiki/` directory):

```text
brian/
├── bin/                 # CLI entry points (wiki, wiki-sync-engine, wiki-leak-check)
├── wikicli/             # Core Python engine & integrations
├── commands/            # Slash command prompts for agents (/wiki-ingest, /wiki-query, /wiki-lint)
├── _templates/          # Agent instructions & prompt templates
├── internal/
│   ├── mcp_server_wiki.py  # Claude Desktop MCP Server
│   └── skills/          # Cross-agent skill definitions (wiki-context)
├── wiki/                # Structured Markdown knowledge base
│   ├── CONVENTIONS.md
│   ├── SCALING.md
│   ├── entities/
│   ├── concepts/
│   ├── projects/
│   └── syntheses/
└── raw/                 # Ingested source documents & inbox
```

---

## CLI Reference (For Debugging & Agent Tooling)

While LLMs drive reading and writing during normal usage, human users and agent scripts can use the CLI directly:

- `wiki context "$PWD"` — Resolves and ranks knowledge pages relevant to a directory or task.
- `wiki knowledge query "<question>"` — Returns deterministic JSON with ranked curated pages.
- `wiki knowledge read "<path>"` — Reads structured content for a specific wiki page.
- `wiki knowledge update --input <payload.json>` — Previews/applies governed source-backed updates.
- `wiki sync` — Fetches upstream `origin/main` and fast-forwards clean local checkouts.
- `wiki status` — Displays integration hook health and git sync status.

---

## License

MIT
