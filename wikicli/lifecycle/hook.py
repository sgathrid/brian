"""SessionStart hook runner — emits situated context payload driven by wiki.toml manifest."""

import json
from pathlib import Path

from ..core.config import WikiConfig
from ..core.page import WikiDatabase, WikiPage
from ..core.resolve import resolve_context
from .brief import format_rules_block, format_upkeep_block
from .personalization import load_agent_rule_catalog
from .sync import SyncState, sync_wiki

CATALOG_BUDGET_CHARS = 8_000


def _bounded_catalog(catalog: str, budget: int = CATALOG_BUDGET_CHARS) -> str:
    """Caps the injected catalog so payload size is O(1), not O(pages).

    The catalog carries one line per page, so it grows without limit: ~1.5KB at 30 pages, ~26KB
    (~6,500 tokens) at 500, ~107KB at 2,000 — paid on EVERY session start, in every repo, by every
    developer. Latency was never the binding constraint (500 pages resolve in ~0.06s); this is. And
    the failure is silent: an over-stuffed preamble eats context window and quietly degrades answers
    rather than throwing anything.

    Truncation keeps whole section headings and whole entries so the fragment stays readable, then
    says plainly that it is partial and how to reach the rest. Agents have `wiki find` and the
    situated block, so a bounded catalog costs discovery breadth, not capability.
    """
    if len(catalog) <= budget:
        return catalog

    kept: list[str] = []
    used = 0
    for line in catalog.splitlines():
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1

    # Never end mid-section with a dangling heading.
    while kept and kept[-1].lstrip().startswith("#"):
        kept.pop()

    kept.append("")
    kept.append(
        "_Catalog truncated to keep the session brief bounded. "
        'Search the full knowledge base with `wiki find "<keywords>"`, '
        "or read `wiki/index.md` for the complete catalog._"
    )
    return "\n".join(kept) + "\n"


def run_session_start_hook(repo_root: Path, input_data: str = "") -> str:
    """Executes SessionStart hook logic and returns the formatted JSON payload."""
    config = WikiConfig(repo_root)
    wiki_dir = config.data_dir

    if not wiki_dir.is_dir():
        return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ""}})

    sync_result = sync_wiki(repo_root)
    if sync_result.state is SyncState.UPDATED:
        config = WikiConfig(repo_root)
        wiki_dir = config.data_dir

    # Extract CWD from stdin JSON if present
    cwd_str = ""
    if input_data:
        try:
            parsed = json.loads(input_data)
            cwd_str = parsed.get("cwd", "")
        except (json.JSONDecodeError, AttributeError):
            # Malformed hook stdin: fall back to $PWD rather than breaking session start.
            pass

    if not cwd_str:
        cwd_str = str(Path.cwd())

    db = WikiDatabase(wiki_dir)
    index_file = wiki_dir / "index.md"
    index_content = index_file.read_text(encoding="utf-8") if index_file.is_file() else ""

    # 1. Situated Working Context
    situated_block = ""
    matched_paths = resolve_context(db, cwd_str, limit=3)
    if matched_paths:
        lines = [f"## Working context\nDetected location: `{cwd_str}` — most relevant brain pages:"]
        for p in matched_paths:
            page = db.pages.get(p)
            if not page:
                continue
            title = page.title
            desc = ""
            if index_content:
                for line in index_content.splitlines():
                    if f'[["{title}"]]' in line or f"[[{title}]]" in line:
                        if "—" in line:
                            desc = line.split("—", 1)[1].strip()
                        break
            desc_str = f" — {desc}" if desc else ""
            lines.append(f"- [[{title}]]{desc_str}")
        situated_block = "\n".join(lines) + "\n\n"

    # 2. Company Pointer
    company_file = config.company_file
    company_block = ""
    if company_file.is_file():
        try:
            company_page = WikiPage(company_file)
            if company_page.summary:
                rel_company = (
                    company_file.relative_to(repo_root) if company_file.is_relative_to(repo_root) else company_file
                )
                rel_reg = (
                    config.registry_file.relative_to(repo_root)
                    if config.registry_file.is_relative_to(repo_root)
                    else config.registry_file
                )
                company_block = (
                    f"## Company\n{company_page.summary}\n"
                    f"_Detail: [[{company_page.title}]] (`{rel_company}`) • capabilities: {rel_reg}_\n\n"
                )
        except OSError:
            # Unreadable company file: the brief degrades gracefully, the session still starts.
            pass

    # 3. Knowledge Base Catalog from index.md
    catalog_block = ""
    if index_content:
        lines = index_content.splitlines()
        cat_lines = []
        capture = False
        for line in lines:
            if line.strip() == "---":
                continue
            if line.startswith("## Backlog"):
                break
            if line.startswith("## "):
                capture = True
            if capture:
                if line.startswith("## "):
                    cat_lines.append("### " + line[3:])
                else:
                    cat_lines.append(line)
        if cat_lines:
            catalog_block = _bounded_catalog("## Knowledge base catalog\n\n" + "\n".join(cat_lines) + "\n")

    # 4. Preamble & Upkeep instructions
    # "NOT code documentation" is deliberate and load-bearing, not decoration. Agents conflate this
    # with repo-generated docs: asked for the most relevant knowledge-base page, Codex sitting in a
    # repo that also had an `openwiki/` directory answered with that repo's generated quickstart
    # instead of the company page. It stays in the preamble rather than in wiki.toml's description
    # so every adopter of the engine inherits the distinction.
    preamble = (
        f"{config.name} — {config.description}. "
        f"This is a company knowledge base, NOT code documentation: it holds knowledge no repository "
        f'contains. Repo: {repo_root} (CLI on PATH). Pull more with `wiki find "<keywords>"` or '
        f"/wiki-query; cite pages as [[Wikilink]].\n"
        "Use the injected company context as the starting point. Query the knowledge base proactively, "
        "without waiting for the user, when the requested specificity or freshness exceeds the available "
        "evidence, or when a citation is requested. Treat partner, legal, and financial status, along with answers "
        "that will be acted on or repeated externally, as freshness-sensitive. When curated evidence is "
        "unverified or explicitly requires source verification, querying is only the first step: verify the "
        "owning record or repository before consequential use. Otherwise, do not query ritualistically. "
        "Follow relevant links until the evidence is sufficient; if it is not supported, say so.\n\n"
    )

    upkeep = format_upkeep_block(
        config.upkeep_triggers,
        config.upkeep_instructions,
        config.upkeep_proactivity,
    )

    # Optional agent_rules from wiki.toml. No-op when empty or when init catalog
    # (lifecycle/init.py) is not present in this checkout.
    rules_block = ""
    if config.agent_rules:
        rules_block = format_rules_block(config.agent_rules, load_agent_rule_catalog())

    freshness = ""
    if sync_result.fresh is not True:
        freshness = f"## Wiki freshness\nLocal company context may not match `origin/main`: {sync_result.detail}.\n\n"

    full_payload = f"{preamble}{freshness}{rules_block}{upkeep}{situated_block}{company_block}{catalog_block}"

    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": full_payload,
            }
        }
    )
