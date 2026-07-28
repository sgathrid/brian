# Brian: Agentic Context & Knowledge Base Engine
_Your AI agents' shared long-term memory_

> [!IMPORTANT]
> **This is a structured agentic knowledge base — not source code documentation.**
> Brian holds decision logs, architecture notes, product concepts, and domain context across all your AI tools: what your projects do, why decisions were made, and how systems fit together. It is human-curated context that no code repository contains.

Install once per machine. Afterwards every session, in every repo, starts with your AI agents already knowing your project context and architecture.

---

## Contents

- [Install](#install)
- [Supported Integrations](#supported-integrations)
- [Using it Day to Day](#using-it-day-to-day)
- [Engine Architecture](#engine-architecture)
- [Syncing Engine Updates](#syncing-engine-updates)

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

## Using it Day to Day

### Context Resolution
```bash
wiki context "$PWD"
```
Ranks and resolves knowledge base pages relevant to your current working directory, git remote, or task.

### Querying Knowledge
```bash
wiki knowledge query "How does authentication work?"
```
Returns deterministic JSON with ranked pages from your knowledge base.

### Governed Source-Backed Updates
```bash
wiki knowledge update --input payload.json
```
Preview proposed additions or edits to the knowledge base before applying. Ensures source attribution and zero hallucinated context updates.

---

## Engine Architecture

Brian separates **Engine** (CLI logic, installers, MCP server, integration hooks) from **Knowledge Base Content** (`wiki/` directory):

```text
brian/
├── bin/                 # CLI entry points
├── wikicli/             # Core Python engine & integrations
├── commands/            # Slash command prompts for agents
├── _templates/          # Agent instructions & prompt templates
├── internal/
│   ├── mcp_server_wiki.py  # Claude Desktop MCP Server
│   └── skills/          # Cross-agent skill definitions
├── wiki/                # Structured Markdown knowledge base
│   ├── CONVENTIONS.md
│   ├── SCALING.md
│   ├── entities/
│   ├── concepts/
│   ├── projects/
│   └── syntheses/
└── raw/                 # Ingested source documents
```

---

## License

MIT
