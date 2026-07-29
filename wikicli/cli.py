"""wikicli.cli: Entry point for the wiki command line interface."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .core.audit import audit_wiki
from .core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from .core.ingest import PageChange, RetrievalCase, check_ingestion, update_knowledge
from .core.knowledge import query_company_knowledge, read_company_page
from .core.page import WikiDatabase
from .core.resolve import find_literal, find_tags, resolve_context, search_keywords
from .lifecycle.hook import run_session_start_hook
from .lifecycle.install import run_install
from .lifecycle.personalization import load_init_capabilities
from .lifecycle.reset import run_reset
from .lifecycle.status import run_status
from .lifecycle.sync import SyncState, sync_wiki
from .lifecycle.uninstall import run_uninstall

# Optional personalization module (present in public Brian checkouts only).
RULE_HELP_TEXT, run_init = load_init_capabilities()
_HAS_INIT = run_init is not None

C_GREEN = "\033[32m"
C_RESET = "\033[0m"
S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"


def _print_json(value: object, *, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=stream)


def _load_update_payload(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"update input is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise TypeError("update input must be a JSON object")
    allowed = {
        "source_title",
        "source_content",
        "existing_source_path",
        "source_type",
        "page_changes",
        "retrieval_cases",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown update field(s): {', '.join(unknown)}")
    return payload


def _run_knowledge_update(repo_root: Path, payload: dict[str, Any], approval_digest: str | None) -> object:
    try:
        raw_pages = payload["page_changes"]
        raw_cases = payload["retrieval_cases"]
        source_title = payload["source_title"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid update payload: {exc}") from exc
    if not isinstance(source_title, str):
        raise TypeError("source_title must be a string")
    if not isinstance(raw_pages, list) or not all(
        isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("content"), str)
        for item in raw_pages
    ):
        raise TypeError("page_changes must contain objects with string path and content fields")
    if not isinstance(raw_cases, list) or not all(
        isinstance(item, dict) and isinstance(item.get("query"), str) and isinstance(item.get("relevance"), dict)
        for item in raw_cases
    ):
        raise TypeError("retrieval_cases must contain objects with query and relevance fields")
    page_changes = [PageChange(path=item["path"], content=item["content"]) for item in raw_pages]
    retrieval_cases = [RetrievalCase(query=item["query"], relevance=item["relevance"]) for item in raw_cases]
    source_content = payload.get("source_content")
    existing_source_path = payload.get("existing_source_path")
    source_type = payload.get("source_type", "user-confirmed context")
    if source_content is not None and not isinstance(source_content, str):
        raise TypeError("source_content must be a string or null")
    if existing_source_path is not None and not isinstance(existing_source_path, str):
        raise TypeError("existing_source_path must be a string or null")
    if not isinstance(source_type, str):
        raise TypeError("source_type must be a string")
    return update_knowledge(
        repo_root,
        source_title=source_title,
        source_content=source_content,
        existing_source_path=existing_source_path,
        source_type=source_type,
        page_changes=page_changes,
        retrieval_cases=retrieval_cases,
        confirmed=approval_digest is not None,
        approval_digest=approval_digest,
    )


def main():
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        prog="wiki",
        description="Company knowledge base CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # wiki context [DIR]
    p_context = subparsers.add_parser("context", help="Resolve working context pages for a directory")
    p_context.add_argument("cwd", nargs="?", default="", help="Directory path (defaults to current dir)")
    p_context.add_argument("--limit", type=int, default=3, help="Max results")

    # wiki find <QUERY>
    p_find = subparsers.add_parser("find", help="Find wiki pages matching keywords")
    p_find.add_argument("query", help="Search query string")
    p_find.add_argument("--limit", type=int, default=10, help="Max results")
    p_find.add_argument("--explain", action="store_true", help="Show score and ranking signals")

    # wiki grep <QUERY>
    p_grep = subparsers.add_parser("grep", help="Find an exact character sequence in content pages")
    p_grep.add_argument("query", help="Literal text to find")
    p_grep.add_argument("-i", "--ignore-case", action="store_true", help="Ignore character case")
    p_grep.add_argument("--limit", type=int, help="Stop after this many matching lines")

    # wiki tags [TAG]
    p_tags = subparsers.add_parser("tags", help="List or search pages by tag")
    p_tags.add_argument("tag", nargs="?", default="", help="Optional tag filter")

    # wiki root
    subparsers.add_parser("root", help="Print repository root path")

    # wiki graph <PATH>
    p_graph = subparsers.add_parser("graph", help="Print a page's frontmatter without its body")
    p_graph.add_argument("path", type=Path, help="Markdown page path")

    # wiki gen
    subparsers.add_parser("gen", help="Generate index.md, backlinks.md, tags.md, and internal/registry.md")

    # wiki audit / wiki lint
    subparsers.add_parser("audit", help="Audit wiki consistency, links, and schema")
    subparsers.add_parser("lint", help="Alias for audit")

    # wiki ingest check
    p_ingest = subparsers.add_parser("ingest", help="Compile raw sources into curated knowledge")
    ingest_commands = p_ingest.add_subparsers(dest="ingest_command", required=True)
    p_ingest_check = ingest_commands.add_parser("check", help="Validate construction quality and source coverage")
    p_ingest_check.add_argument("--base", default="HEAD", help="Git revision used to detect deletions")
    p_ingest_check.add_argument(
        "--allow-deletions",
        action="store_true",
        help="Confirm that removed knowledge pages were intentionally reviewed",
    )

    # wiki knowledge query|read|update
    p_knowledge = subparsers.add_parser("knowledge", help="Structured agent interface for company knowledge")
    knowledge_commands = p_knowledge.add_subparsers(dest="knowledge_command", required=True)
    p_knowledge_query = knowledge_commands.add_parser("query", help="Query curated company knowledge as JSON")
    p_knowledge_query.add_argument("question", help="Natural-language company question")
    p_knowledge_query.add_argument("--limit", type=int, default=5, help="Maximum results (1-10)")
    p_knowledge_read = knowledge_commands.add_parser("read", help="Read one curated company page as JSON")
    p_knowledge_read.add_argument("path", help="Path or wiki:// URI returned by query")
    p_knowledge_update = knowledge_commands.add_parser(
        "update", help="Preview or apply one source-backed knowledge update from JSON"
    )
    p_knowledge_update.add_argument("--input", default="-", help="JSON payload path, or - for stdin")
    p_knowledge_update.add_argument(
        "--approve", metavar="DIGEST", help="Apply only the exact repository state and payload previously previewed"
    )

    # wiki hook session-start
    p_hook = subparsers.add_parser("hook", help="Execute agent hooks")
    p_hook.add_argument("event", choices=["session-start"], help="Hook event type")

    # wiki init — full setup when lifecycle/init.py is present; stub otherwise
    # so operators never hit a bare argparse "invalid choice" dead-end.
    if _HAS_INIT:
        p_init = subparsers.add_parser(
            "init",
            help="Set up wiki.toml and your overview page (name, use case, optional agent rules)",
            description=(
                "Configure this checkout for your organization. "
                "Interactive mode asks for org name and use case, then optionally lets you "
                "toggle agent behaviors in plain English. Non-interactive: pass -y with flags. "
                "Edit wiki.toml anytime, or re-run wiki init. See README → Customize."
            ),
        )
        p_init.add_argument(
            "-c",
            "--use-case",
            choices=["company", "it_service_desk", "engineering", "research", "personal"],
            default="",
            help=(
                "Preset: company (general KB; no people tracking by default), "
                "it_service_desk (people+assets+no-secrets), engineering (ADRs), "
                "research (strict sources), personal (fast notes)"
            ),
        )
        p_init.add_argument("--rules", default="", help=RULE_HELP_TEXT)
        p_init.add_argument("--name", default="", help="Organization or knowledge-base name")
        p_init.add_argument("--short-name", default="", help="Short display name (e.g. Acme Wiki)")
        p_init.add_argument("--description", default="", help="One-line description shown to agents")
        p_init.add_argument(
            "--company-file",
            default="",
            help="Overview page slug or path (default: wiki/entities/<org>-overview.md)",
        )
        p_init.add_argument(
            "-y",
            "--yes",
            action="store_true",
            help="Non-interactive: accept flags/defaults, no prompts",
        )
    else:
        subparsers.add_parser(
            "init",
            help="Not available in this checkout — edit wiki.toml instead",
            description=(
                "Interactive init is not shipped in this checkout. "
                "Edit wiki.toml ([wiki], [upkeep]) directly, then start a new agent session "
                "or run wiki status to verify. See README → Customize agent upkeep."
            ),
        )

    # wiki install [targets...]
    p_install = subparsers.add_parser("install", help="Install agent integrations")
    p_install.add_argument(
        "targets",
        nargs="*",
        help="Target agents (claude, claude-desktop, codex, gemini, copilot, skills, antigravity, all)",
    )
    p_install.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode")

    # wiki uninstall [targets...]
    p_uninstall = subparsers.add_parser("uninstall", help="Uninstall agent integrations")
    p_uninstall.add_argument("targets", nargs="*", help="Target agents to remove")
    p_uninstall.add_argument("--dry-run", action="store_true", help="Preview removal without modifying files")
    p_uninstall.add_argument("--purge-backups", action="store_true", help="Purge rollback backup files")
    p_uninstall.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode")

    # wiki status
    subparsers.add_parser("status", help="Verify health and integration status across all agent platforms")

    # wiki sync
    p_sync = subparsers.add_parser("sync", help="Safely refresh the local company wiki from origin/main")
    p_sync.add_argument("--force", action="store_true", help="Bypass the session sync throttle")

    # wiki reset [type...] — pages, or (Brian) user settings via optional module
    p_reset = subparsers.add_parser(
        "reset",
        help="Reset wiki pages or restore stock user settings",
        description=(
            "Page modes: full / scope / orphans (delete knowledge pages). "
            "User settings (when available): wiki reset settings — restores stock "
            "wiki.toml packs/names without deleting pages. "
            "Natural-language triggers/instructions live under [upkeep] in wiki.toml."
        ),
    )
    p_reset.add_argument(
        "targets",
        nargs="*",
        help="Mode: full | scope | orphans | settings [upkeep|identity|all]",
    )
    p_reset.add_argument("--scope", default="", help="Target scope for scope reset")
    p_reset.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    p_reset.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Confirm (required non-interactively for page delete or settings restore)",
    )
    p_reset.add_argument(
        "--include-raw",
        action="store_true",
        help="With full: also delete raw/ source documents (git-ignored — IRREVERSIBLE)",
    )
    p_reset.add_argument(
        "--use-case-stock",
        action="store_true",
        help="With settings all: also force use_case=company",
    )


    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    wiki_dir = repo_root / "wiki"

    if args.subcommand == "root":
        print(repo_root)
        sys.exit(0)

    elif args.subcommand == "graph":
        try:
            lines = args.path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            parser.error(str(e))
        if lines[:1] == ["---"]:
            try:
                end = lines.index("---", 1)
            except ValueError:
                end = 0
            if end:
                print("\n".join(lines[1:end]))

    elif args.subcommand == "context":
        cwd_target = args.cwd or str(Path.cwd())
        db = WikiDatabase(wiki_dir)
        matches = resolve_context(db, cwd_target, limit=args.limit)
        for m in matches:
            print(m)

    elif args.subcommand == "find":
        db = WikiDatabase(wiki_dir)
        results = search_keywords(db, args.query, limit=args.limit)
        for hit in results:
            detail = f" score={hit.score:.3f} ({'; '.join(hit.reasons)})" if args.explain else ""
            print(f"[[{hit.page.title}]]{detail} — {hit.page.filepath}")

    elif args.subcommand == "grep":
        db = WikiDatabase(wiki_dir)
        for match in find_literal(db, args.query, ignore_case=args.ignore_case, limit=args.limit):
            print(f"{match.page.filepath}:{match.line_number}:{match.line}")

    elif args.subcommand == "tags":
        db = WikiDatabase(wiki_dir)
        tag_groups = find_tags(db, args.tag)
        for tag, pages in tag_groups:
            print(f"#{tag}:")
            for p in pages:
                print(f"  - [[{p.title}]]")

    elif args.subcommand == "gen":
        db = WikiDatabase(wiki_dir)
        generate_index(db, wiki_dir)
        generate_backlinks(db, wiki_dir)
        generate_tags(db, wiki_dir)
        generate_registry(repo_root)
        print(f"{S_CHECK_GREEN} Generated index.md, backlinks.md, tags.md, and internal/registry.md")

    elif args.subcommand in ("audit", "lint"):
        db = WikiDatabase(wiki_dir)
        success, lines = audit_wiki(db)
        for line in lines:
            print(line)
        if success:
            print(f"{S_CHECK_GREEN} Wiki audit passed: schema valid, links resolved, no errors.")
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.subcommand == "ingest":
        report = check_ingestion(repo_root, base=args.base, allow_deletions=args.allow_deletions)
        for line in report.facts:
            print(f"  • {line}")
        for line in report.warnings:
            print(f"  ▲ {line}")
        for line in report.errors:
            print(f"  ✕ {line}")
        if report.ok:
            print(f"{S_CHECK_GREEN} Ingestion check passed: sources became connected, queryable knowledge.")
        else:
            sys.exit(1)

    elif args.subcommand == "knowledge":
        try:
            if args.knowledge_command == "query":
                result = query_company_knowledge(repo_root, args.question, args.limit)
            elif args.knowledge_command == "read":
                result = read_company_page(repo_root, args.path)
            else:
                result = _run_knowledge_update(repo_root, _load_update_payload(args.input), args.approve)
            _print_json(asdict(result))
        except (FileNotFoundError, TypeError, ValueError) as exc:
            _print_json({"error": {"type": "invalid_request", "message": str(exc)}}, stream=sys.stderr)
            sys.exit(2)
        except OSError as exc:
            _print_json({"error": {"type": "operation_failed", "message": str(exc)}}, stream=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "rotate-log":
        log_dir = repo_root / "logs"
        log_dir.mkdir(exist_ok=True)
        print(f"{S_CHECK_GREEN} Session logs rotated.")

    elif args.subcommand == "hook":
        if args.event == "session-start":
            stdin_data = sys.stdin.read() if not sys.stdin.isatty() else ""
            output = run_session_start_hook(repo_root, stdin_data)
            print(output)

    elif args.subcommand == "init":
        if not _HAS_INIT or run_init is None:
            print("wiki init is not available in this checkout.", file=sys.stderr)
            print(
                "Edit wiki.toml instead:\n"
                "  [wiki]   name, short_name, description, agent_rules\n"
                "  [upkeep] proactivity (label), triggers, instructions\n"
                "Then run `wiki status` or start a new agent session.\n"
                "See README → Customize agent upkeep.",
                file=sys.stderr,
            )
            sys.exit(2)
        if not run_init(
            repo_root,
            use_case=args.use_case,
            agent_rules=args.rules,
            name=args.name,
            short_name=args.short_name,
            description=args.description,
            company_file_slug=args.company_file,
            non_interactive=args.yes,
        ):
            sys.exit(1)

    elif args.subcommand == "install":
        if not run_install(repo_root, args.targets, non_interactive=args.yes):
            sys.exit(1)

    elif args.subcommand == "uninstall":
        run_uninstall(
            repo_root,
            args.targets,
            dry_run=args.dry_run,
            purge_backups=args.purge_backups,
            non_interactive=args.yes,
        )

    elif args.subcommand == "status":
        run_status(repo_root)

    elif args.subcommand == "sync":
        result = sync_wiki(repo_root, force=args.force)
        marker = S_CHECK_GREEN if result.fresh is True else "▲"
        print(f"{marker} {result.detail}")
        if result.state not in {SyncState.CURRENT, SyncState.UPDATED}:
            sys.exit(1)

    elif args.subcommand == "reset":
        run_reset(
            repo_root,
            args.targets,
            scope=args.scope,
            dry_run=args.dry_run,
            non_interactive=args.yes,
            confirmed=args.yes,
            include_raw=args.include_raw,
            stock_use_case=bool(getattr(args, "use_case_stock", False)),
        )


if __name__ == "__main__":
    main()
