"""Initialization lifecycle module — configures wiki.toml, custom agent rules, and entity overview page."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from ..core.generate import generate_backlinks, generate_index, generate_registry, generate_tags
from ..core.page import WikiDatabase
from ..ui.menu import run_confirm, run_menu

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
S_CHECK_GREEN = f"{C_GREEN}✓{C_RESET}"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", slug) or "organization"


def _clean_company_rel_path(raw: str, default_slug: str) -> str:
    if not raw:
        return f"wiki/entities/{default_slug}.md"
    p = Path(raw)
    name = p.name if p.name.endswith(".md") else f"{p.name}.md"
    raw_str = str(p)
    if raw_str.startswith("wiki/"):
        return raw_str if raw_str.endswith(".md") else f"{raw_str}.md"
    else:
        return f"wiki/entities/{name}"


def _prompt(prompt_text: str, default_val: str) -> str:
    if not sys.stdin.isatty():
        return default_val
    try:
        val = input(prompt_text).strip()
        return val or default_val
    except EOFError:
        return default_val


USE_CASE_PRESETS: dict[str, dict] = {
    "company": {
        "title": "Company knowledge base",
        "hint": "Products, decisions, policies, client context",
        "default_name_suffix": "Knowledge Base",
        "default_short_suffix": "Wiki",
        "default_desc_template": "Company knowledge base — business, product, and operational context for {org}",
        # Opt-in: most company brains don't need people-on-entities tracking forced on.
        "default_rules": [],
        "triggers": [
            "A functionality-changing PR — new or renamed abstraction, changed architecture or data flow, a decision worth remembering",
            "Authoring or substantially revising a company-facing document (.md, .html, .pdf) — pitch, RFC, spec, application, report",
        ],
        "instructions": (
            "Then say which page to add or update and why, and let the user decide. Never commit or push the wiki yourself.\n"
            "Refactors, dependency bumps, tests and formatting need nothing — 'already current' is a valid answer; do not invent work."
        ),
    },
    "it_service_desk": {
        "title": "IT helpdesk & infrastructure",
        "hint": "People, hardware assets, access SOPs",
        "default_name_suffix": "IT Knowledge Base",
        "default_short_suffix": "IT Wiki",
        "default_desc_template": "IT & Helpdesk knowledge base — hardware assets, personnel/people directory, software access, and infra SOPs for {org}",
        "default_rules": ["people_tracking", "asset_tracking", "security_notice"],
        "triggers": [
            "Hardware asset allocation or hardware policy update",
            "Personnel changes, role updates, or employee onboarding/offboarding workflows",
            "Software access, credential policy, or network/infrastructure SOP modification",
            "Vendor contract, software license, or IT support escalation change",
        ],
        "instructions": (
            "Update or create people, asset, or SOP entity pages when IT details change. "
            "Never store plain-text passwords or secret keys in wiki pages."
        ),
    },
    "engineering": {
        "title": "Engineering & architecture",
        "hint": "ADRs, system design, API contracts",
        "default_name_suffix": "Engineering Knowledge Base",
        "default_short_suffix": "Tech Wiki",
        "default_desc_template": "Technical & engineering knowledge base — system architecture, ADRs, API contracts, and infrastructure decisions for {org}",
        "default_rules": ["adrs"],
        "triggers": [
            "Architectural decision, design pattern choice, or system boundary change",
            "Database schema migration, breaking API contract change, or new service dependency",
            "Infrastructure, deployment pipeline, or security model modification",
        ],
        "instructions": (
            "Record major architectural choices as Architectural Decision Records (ADRs). "
            "Ensure system relationships and dependencies are cited with [[Wikilinks]]."
        ),
    },
    "research": {
        "title": "Clinical & research",
        "hint": "Protocols, papers, datasets, ontologies",
        "default_name_suffix": "Research Knowledge Base",
        "default_short_suffix": "Research Wiki",
        "default_desc_template": "Scientific & clinical knowledge base — trial protocols, research preprints, study datasets, and domain concepts for {org}",
        "default_rules": ["strict_sources"],
        "triggers": [
            "Ingesting or citing a new research paper, clinical protocol, or study dataset",
            "Revising domain terminology, ontology definitions, or experimental methodology",
            "Updating study status, trial milestones, or safety/efficacy findings",
        ],
        "instructions": (
            "Ensure every clinical/scientific assertion cites its raw source document under raw/. "
            "Define domain terms precisely and maintain bidirectional links."
        ),
    },
    "personal": {
        "title": "Personal second brain",
        "hint": "Projects, notes, workflows",
        "default_name_suffix": "Brain",
        "default_short_suffix": "Notes",
        "default_desc_template": "Personal knowledge base — projects, learning notes, workflow automation, and reference context for {org}",
        "default_rules": ["quick_capture"],
        "triggers": [
            "New personal project milestone, strategic idea, or key decision",
            "Workflow automation, tool setup change, or reference notes update",
        ],
        "instructions": (
            "Keep notes concise, organized by topic or project. "
            "Capture new ideas fast and connect related concepts via [[Wikilinks]]."
        ),
    },
}

# Keys are stable IDs written to wiki.toml; labels/hints are what humans see in init.
# Optional page_guidance is soft shape advice for agents (not an ingest schema).
ALL_AGENT_RULES: dict[str, dict[str, str]] = {
    "people_tracking": {
        "label": "Track people & roles",
        "hint": "Keep pages for teammates, roles, and who owns what (optional for most companies)",
        "prompt_rule": (
            "• People & Team Directory: You are explicitly configured to track people, team roles, "
            "manager hierarchies, contact channels, and personnel assignments. Create and update "
            "entity pages for team members under wiki/entities/ or wiki/people/."
        ),
        "page_guidance": (
            "Person page shape: name/title, role, team, manager [[link]], contact channel; "
            "owns/collaborates-on wikilinks; type entity; tag people."
        ),
    },
    "asset_tracking": {
        "label": "Track IT assets & access",
        "hint": "Laptops, asset tags, licenses, and how people request access",
        "prompt_rule": (
            "• IT Asset & Access SOPs: Track hardware assets, serial/asset IDs, software license "
            "assignments, and access request SOPs. Keep hardware and access procedures up to date."
        ),
        "page_guidance": (
            "Asset page shape: asset tag/serial, type, assignee [[person]], status; "
            "link access-request SOPs; never store secrets."
        ),
    },
    "security_notice": {
        "label": "Never store secrets in the wiki",
        "hint": "Remind agents not to write passwords, API keys, or tokens into pages",
        "prompt_rule": (
            "• Security & Secrets Policy: NEVER place raw passwords, API secret keys, access tokens, "
            "or private keys into wiki pages. Reference secure vault locations or access request "
            "procedures instead."
        ),
    },
    "adrs": {
        "label": "Record architecture decisions",
        "hint": "Write ADRs (context → decision → consequences) when design choices stick",
        "prompt_rule": (
            "• Architectural Decision Records: Document system design choices, trade-offs, and "
            "architectural changes as structured ADR pages with Context, Decision, and Consequences."
        ),
        "page_guidance": (
            "ADR shape: Context → Decision → Consequences; link related systems; tag adr."
        ),
    },
    "strict_sources": {
        "label": "Require source citations",
        "hint": "Every new claim should point at a file under raw/",
        "prompt_rule": (
            "• Source Provenance: Every new or modified knowledge page must cite its original source "
            "document in raw/ and include complete provenance metadata."
        ),
    },
    "quick_capture": {
        "label": "Fast note capture",
        "hint": "Turn messy meeting notes and ideas into linked topic pages quickly",
        "prompt_rule": (
            "• Fast Note Capture: Help synthesize raw thoughts, meeting notes, and informal ideas "
            "into structured topic pages with clear tags and links."
        ),
    },
}

# How aggressively agents offer saves. triggers/instructions None → use-case preset.
UPKEEP_POSTURES: dict[str, dict] = {
    "selective": {
        "title": "Selective",
        "hint": "Durable, high-signal changes only (recommended default)",
        "triggers": None,
        "instructions": None,
    },
    "active": {
        "title": "Active",
        "hint": "Offer updates often; still ask before writing",
        "triggers": [
            "Any durable decision, policy, product, or process change worth remembering later",
            "Shipping user-visible work, API/contract changes, or architecture shifts",
            "Authoring or substantially revising docs that others will rely on",
        ],
        "instructions": (
            "When in doubt, offer a concise wiki update. Say which page and why, then wait. "
            "Never commit or push. Skip pure refactors, dependency bumps, tests, and formatting."
        ),
    },
    "capture": {
        "title": "Capture everything durable",
        "hint": "Prefer logging; treat most durable context as worth saving",
        "triggers": [
            "Any fact, decision, relationship, or procedure someone might need later",
            "Meeting outcomes, ownership changes, customer context, and operational details",
            "Docs, plans, and status changes that would otherwise live only in chat or memory",
        ],
        "instructions": (
            "Prefer capturing durable context in the wiki over leaving it only in conversation. "
            "Propose concrete page adds/updates often; still ask before writing and never commit or push. "
            "Treat 'already current' as uncommon — only when the wiki already reflects the same facts."
        ),
    },
    "silent": {
        "title": "Silent",
        "hint": "Only update the wiki when the user asks",
        "triggers": [
            "The user explicitly asks to update, save, or log something in the wiki",
        ],
        "instructions": (
            "Do not proactively offer wiki updates. When the user asks, propose the change, "
            "wait for approval, and never commit or push."
        ),
    },
}


def _normalize_proactivity(raw: object) -> str:
    key = str(raw or "").strip().lower()
    return key if key in UPKEEP_POSTURES else ""


def _normalize_upkeep_pair(triggers: list[str], instructions: str) -> tuple[tuple[str, ...], str]:
    """Canonical form for comparing stock packs vs hand-edited text."""
    cleaned = tuple(str(t).strip() for t in triggers if str(t).strip())
    return cleaned, str(instructions or "").strip()


def _upkeep_for_posture(use_case: str, proactivity: str) -> tuple[list[str], str]:
    """Resolve triggers/instructions for a posture (selective → use-case preset)."""
    posture = UPKEEP_POSTURES.get(proactivity) or UPKEEP_POSTURES["selective"]
    if posture.get("triggers") is not None:
        return list(posture["triggers"]), str(posture.get("instructions") or "").strip()
    preset = USE_CASE_PRESETS.get(use_case) or USE_CASE_PRESETS["company"]
    return list(preset["triggers"]), str(preset["instructions"]).strip()


def _existing_upkeep_pair(existing_upkeep: dict) -> tuple[list[str], str] | None:
    """Return preserved triggers/instructions when the manifest already has upkeep text."""
    triggers: list[str] = []
    raw_t = existing_upkeep.get("triggers")
    if isinstance(raw_t, list):
        triggers = [str(t) for t in raw_t if str(t).strip()]
    elif isinstance(raw_t, str) and raw_t.strip():
        triggers = [raw_t.strip()]
    instructions = str(existing_upkeep.get("instructions") or "").strip()
    if not triggers and not instructions:
        return None
    return triggers, instructions


def _matches_stock_pack(
    pair: tuple[list[str], str],
    use_case: str,
    proactivity: str,
) -> bool:
    """True when pair equals the stock pack for this use_case + posture."""
    stock = _upkeep_for_posture(use_case, proactivity)
    return _normalize_upkeep_pair(*pair) == _normalize_upkeep_pair(*stock)


def _resolve_upkeep(
    existing_upkeep: dict,
    use_case: str,
    proactivity: str,
    custom: tuple[list[str], str] | None,
    *,
    prior_use_case: str = "",
) -> tuple[list[str], str]:
    """Resolve triggers/instructions for write + preview.

    Order:
      1. this-run custom edit
      2. same posture + existing text that is still stock for the *prior* use case
         and use case changed → apply pack for the *new* use case (selective packs)
      3. same posture + any other existing text → preserve (hand edits win)
      4. posture pack for the chosen use case

    Missing/invalid prior proactivity is treated as selective (legacy manifests).
    Non-selective postures are use-case-independent; only selective packs vary by use case.
    """
    if custom is not None:
        return custom

    prior = _normalize_proactivity(existing_upkeep.get("proactivity")) or "selective"
    chosen = proactivity if proactivity in UPKEEP_POSTURES else "selective"
    preserved = _existing_upkeep_pair(existing_upkeep)

    if preserved is not None and prior == chosen:
        prior_uc = (prior_use_case or "").strip()
        if (
            prior_uc
            and prior_uc != use_case
            and prior_uc in USE_CASE_PRESETS
            and use_case in USE_CASE_PRESETS
            and _matches_stock_pack(preserved, prior_uc, chosen)
        ):
            # Stock text from the old preset — refresh to the new use-case pack.
            return _upkeep_for_posture(use_case, chosen)
        return preserved

    return _upkeep_for_posture(use_case, chosen)

RULE_HELP_TEXT = (
    "Optional agent behavior rules (comma-separated). "
    "people_tracking=keep pages for people & roles; "
    "asset_tracking=laptops/licenses/access SOPs; "
    "security_notice=never write secrets into pages; "
    "adrs=record architecture decisions; "
    "strict_sources=require raw/ citations; "
    "quick_capture=fast personal note synthesis. "
    "Example: --rules people_tracking,security_notice"
)


def _format_rules_toml(rules: list[str]) -> str:
    if not rules:
        return "[]"
    return "[\n" + ",\n".join(f'    "{r}"' for r in rules) + "\n]"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_wiki_toml(
    toml_path: Path,
    *,
    org_name: str,
    org_short: str,
    org_desc: str,
    use_case: str,
    agent_rules: list[str],
    company_rel_path: str,
    proactivity: str,
    triggers: list[str],
    instructions: str,
) -> None:
    """Write wiki.toml — natural-language [upkeep] is the durable settings surface."""
    triggers_toml = "[\n" + ",\n".join(f'    "{_toml_escape(str(t))}"' for t in triggers) + "\n]"
    rules_toml = _format_rules_toml(agent_rules)
    toml_content = f'''# wiki.toml — edit freely in plain English.
# agent_rules  = optional behaviors (see README → Customize)
# [upkeep]     = proactivity + when agents should offer to update the wiki
# Re-run `wiki init` anytime to change settings interactively
# (overview page & hand-edited upkeep text are preserved).
# Restore stock packs/names: `wiki reset settings` (does not delete pages).

[wiki]
name = "{_toml_escape(str(org_name))}"
short_name = "{_toml_escape(str(org_short))}"
description = "{_toml_escape(str(org_desc))}"
version = "0.1.0"
use_case = "{use_case}"
agent_rules = {rules_toml}

[paths]
data_dir = "wiki"
raw_dir = "raw"
company_file = "{company_rel_path}"
registry_file = "internal/registry.md"

[upkeep]
proactivity = "{proactivity}"
triggers = {triggers_toml}
instructions = """
{str(instructions).strip()}
"""
'''
    toml_path.write_text(toml_content, encoding="utf-8")


def _load_existing_manifest(toml_path: Path) -> dict:
    """Best-effort read of an existing wiki.toml for re-run defaults."""
    if not toml_path.is_file():
        return {}
    try:
        with open(toml_path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _normalize_rules(raw: list[str] | str | None) -> list[str]:
    if isinstance(raw, str):
        items = [r.strip().lower() for r in raw.split(",") if r.strip()]
    elif isinstance(raw, list):
        items = [str(r).strip().lower() for r in raw if str(r).strip()]
    else:
        items = []
    # Preserve order, drop unknowns and duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for key in items:
        if key in ALL_AGENT_RULES and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _prompt_multiline(header: str, *, blank_keeps_current: bool = True) -> list[str] | None:
    """Read lines until a blank line. Returns None if the user keeps current (first line empty)."""
    print("│")
    print(f"│  {header}")
    if blank_keeps_current:
        print(f"│  {C_DIM}One item per line. Empty line finishes. First line empty = keep current.{C_RESET}")
    else:
        print(f"│  {C_DIM}One item per line. Empty line finishes.{C_RESET}")
    print("│")
    lines: list[str] = []
    while True:
        try:
            line = input("│  > ").rstrip()
        except EOFError:
            break
        if not line:
            break
        lines.append(line)
    if not lines and blank_keeps_current:
        return None
    return lines


def _select_rules_interactively(default_rules: list[str], existing_rules: list[str] | None = None) -> list[str]:
    """Optional step: multi-select agent behaviors with space toggles."""
    seed = list(existing_rules) if existing_rules is not None else list(default_rules)
    seed_set = set(seed)

    print("│")
    print(f"│  {C_BOLD}Optional agent behavior{C_RESET}")
    print("│  These change what agents try to remember.")
    print(f"│  {C_DIM}Space toggles · edit later in wiki.toml → agent_rules, or re-run init.{C_RESET}")
    print("│")

    options = [
        (key, meta["label"], meta["hint"], key in seed_set)
        for key, meta in ALL_AGENT_RULES.items()
    ]
    sel = run_menu(
        "Which optional behaviors should agents use?",
        options=options,
        title="Brian setup",
        single_select=False,
    )
    if not sel.strip():
        return []
    return _normalize_rules(sel.split())


UPKEEP_EXAMPLES: dict[str, list[str]] = {
    "company": [
        "Shipping a user-visible feature or API change",
        "Updating a customer-facing policy or pricing doc",
        "Closing a decision in a design review",
    ],
    "it_service_desk": [
        "Assigning or retiring a hardware asset",
        "Changing an access-request or offboarding SOP",
        "Updating a vendor license or escalation path",
    ],
    "engineering": [
        "Landing an architectural decision (ADR-worthy)",
        "Breaking API contract or schema migration",
        "Changing deploy pipeline or security model",
    ],
    "research": [
        "Ingesting a new paper, protocol, or dataset",
        "Revising domain terminology or methodology",
        "Updating trial status or key findings",
    ],
    "personal": [
        "Hitting a project milestone or key decision",
        "Changing a workflow, tool setup, or reference note",
    ],
}


def _select_proactivity_interactively(seed: str) -> str:
    """Always-on short step: how aggressively agents offer saves."""
    pre = seed if seed in UPKEEP_POSTURES else "selective"
    print("│")
    print(f"│  {C_BOLD}How proactive should agents be?{C_RESET} {C_DIM}([upkeep].proactivity){C_RESET}")
    print(f"│  {C_DIM}Still always ask before writing · never auto-commit. Edit later in wiki.toml.{C_RESET}")
    print("│")
    options = [
        (key, meta["title"], meta["hint"], key == pre)
        for key, meta in UPKEEP_POSTURES.items()
    ]
    sel = run_menu(
        "Upkeep proactivity",
        options=options,
        title="Brian setup",
        single_select=True,
    )
    return sel if sel in UPKEEP_POSTURES else pre


def _customize_upkeep_interactively(
    use_case: str,
    current_triggers: list[str],
    current_instructions: str,
) -> tuple[list[str], str]:
    """Optional NL step: review/edit upkeep triggers and instructions."""
    examples = UPKEEP_EXAMPLES.get(use_case, UPKEEP_EXAMPLES["company"])
    triggers = list(current_triggers)
    instructions = str(current_instructions or "").strip()

    print("│")
    print(f"│  {C_BOLD}What agents offer to save{C_RESET} {C_DIM}([upkeep] in wiki.toml){C_RESET}")
    print("│  Triggers = when agents should offer a wiki update.")
    print("│  Instructions = how they should phrase the offer.")
    print("│")
    print(f"│  {C_DIM}Examples:{C_RESET}")
    for ex in examples:
        print(f"│    • {ex}")
    print("│")
    print(f"│  {C_BOLD}Current triggers:{C_RESET}")
    if triggers:
        for i, t in enumerate(triggers, 1):
            print(f"│    {i}. {t}")
    else:
        print("│    (none)")
    print("│")

    keep_triggers = run_confirm(
        "Keep these triggers?",
        default=True,
        title="Brian setup",
        confirm_label="keep triggers",
        cancel_label="edit triggers",
    )
    if not keep_triggers:
        edited = _prompt_multiline("Enter triggers (plain English):")
        if edited is not None:
            triggers = edited

    print("│")
    print(f"│  {C_BOLD}Current instructions:{C_RESET}")
    for line in (instructions or "(none)").splitlines() or ["(none)"]:
        print(f"│    {line}")
    print("│")

    edit_instr = run_confirm(
        "Edit instructions?",
        default=False,
        title="Brian setup",
        confirm_label="edit instructions",
        cancel_label="keep instructions",
    )
    if edit_instr:
        edited_lines = _prompt_multiline(
            "Enter instructions (plain English):",
            blank_keeps_current=True,
        )
        if edited_lines is not None:
            instructions = "\n".join(edited_lines).strip()

    return triggers, instructions


def _generate_overview_content(
    use_case: str, org_name: str, org_short: str, company_rel_path: str, repo_root: Path
) -> str:
    overview_title = f"{org_name} Overview"
    slug = _slugify(org_name.replace("Knowledge Base", "").replace("Wiki", ""))
    stem = Path(company_rel_path).stem

    if use_case == "it_service_desk":
        return f"""---
title: {overview_title}
name: {overview_title}
summary: IT & Helpdesk knowledge base for tracking hardware assets, personnel directory, software access SOPs, and infrastructure.
type: entity
scope: global
tags: [it, service-desk, hardware, directory, sop]
aliases: [{org_short}, {stem}]
context_keys: [{slug}, it-helpdesk, assets, personnel]
---

# {overview_title}

**{org_name}** is the IT & Service Desk knowledge base for tracking hardware assets, personnel/people profiles, software access SOPs, and infrastructure procedures.

## Core Operations & Directory Rules
1. **People & Role Directory**: Tracks team members, roles, contact channels, manager hierarchies, and hardware assignments.
2. **Asset & SOP Directory**: Documents hardware asset tags/serials, software license provisioning, and access request SOPs.
3. **Security Policy**: Enforces credential safety and IT troubleshooting guides without storing plain-text secrets in wiki pages.
"""
    elif use_case == "engineering":
        return f"""---
title: {overview_title}
name: {overview_title}
summary: Engineering knowledge base for system design, ADRs, API contracts, and infrastructure decisions.
type: entity
scope: global
tags: [engineering, architecture, adr, api, infrastructure]
aliases: [{org_short}, {stem}]
context_keys: [{slug}, engineering, architecture, adrs]
---

# {overview_title}

**{org_name}** is the engineering & technical architecture knowledge base for tracking system design, ADRs, API contracts, and infrastructure decisions.

## Engineering Architecture Rules
1. **Architectural Decision Records (ADRs)**: Documents major system design choices, trade-offs, and consequences.
2. **API & Data Contracts**: Maintains canonical specifications for internal and external service boundaries.
3. **Infrastructure & Dependencies**: Maps service relationships, deployment pipelines, and technical debt.
"""
    elif use_case == "research":
        return f"""---
title: {overview_title}
name: {overview_title}
summary: Scientific & research knowledge base for trial protocols, preprints, datasets, and domain ontologies.
type: entity
scope: global
tags: [research, clinical, science, datasets, ontologies]
aliases: [{org_short}, {stem}]
context_keys: [{slug}, research, clinical, science]
---

# {overview_title}

**{org_name}** is the scientific & research knowledge base for managing trial protocols, research preprints, study datasets, and domain concepts.

## Research & Knowledge Rules
1. **Source Provenance**: Every page links directly to raw source documents under `raw/`.
2. **Domain Terminology**: Defines key scientific and domain ontologies with precision.
3. **Evidence-Backed**: Tracks study findings, trial milestones, and analytical protocols.
"""
    elif use_case == "personal":
        return f"""---
title: {overview_title}
name: {overview_title}
summary: Personal second brain for projects, learning notes, workflow automation, and reference context.
type: entity
scope: global
tags: [personal, brain, projects, notes, workflow]
aliases: [{org_short}, {stem}]
context_keys: [{slug}, personal-brain, notes, projects]
---

# {overview_title}

**{org_name}** is a personal second brain for organizing projects, learning notes, workflow automation, and reference context.

## Personal Knowledge System
1. **Fast Capture**: Quickly records unstructured ideas, notes, and milestones.
2. **Interconnected Topics**: Connects projects and concepts seamlessly with `[[Wikilinks]]`.
3. **Actionable Reference**: Serves as a personal context engine for AI assistants.
"""
    else:
        # Default 'company'
        return f"""---
title: {overview_title}
name: {overview_title}
summary: Central company knowledge base holding organizational strategy, product context, and operational decisions.
type: entity
scope: global
tags: [architecture, overview, organization]
aliases: [{org_short}, {stem}]
context_keys: [{slug}, wiki, knowledge-base]
---

# {overview_title}

**{org_name}** is the central company knowledge base holding organizational strategy, product context, and operational decisions.

## Core Principles & Architecture
1. **Business & Product Context**: Holds high-level architecture, decision logs, and domain concepts that code search alone cannot uncover.
2. **Cross-Agent Parity**: Interoperable across all major LLM agents (Claude Code, Gemini CLI, Codex, Cursor, Antigravity, Copilot).
3. **Governed Ingestion**: Governed updates ensure source attribution, link verification, and zero hallucinated context updates.
"""


def run_init(
    repo_root: Path,
    *,
    use_case: str = "",
    agent_rules: list[str] | str | None = None,
    name: str = "",
    short_name: str = "",
    description: str = "",
    company_file_slug: str = "",
    non_interactive: bool = False,
) -> bool:
    """Initializes wiki.toml, optional agent rules, and overview entity page.

    Interactive flow keeps the happy path short:
      1. Use case (always shown; current value pre-selected on re-run)
      2. Org name
      3. Optional agent-behavior multi-select (space toggles)
      4. Proactivity posture (always shown: selective/active/capture/silent)
      5. Fine-tune triggers/instructions when selective, or same-posture re-run
    Re-runs preserve custom upkeep text and existing overview pages unless the
    posture changes (pack swap) or the user opts into editing again.
    """
    repo_root = repo_root.resolve()
    toml_path = repo_root / "wiki.toml"
    existing = _load_existing_manifest(toml_path)
    existing_wiki = existing.get("wiki", {}) if isinstance(existing.get("wiki"), dict) else {}
    existing_paths = existing.get("paths", {}) if isinstance(existing.get("paths"), dict) else {}
    existing_upkeep = existing.get("upkeep", {}) if isinstance(existing.get("upkeep"), dict) else {}
    is_rerun = toml_path.is_file()

    interactive = not non_interactive and sys.stdin.isatty()
    rules_explicit = agent_rules is not None and agent_rules != ""

    raw_base_name = repo_root.name.replace("-", " ").replace("_", " ").title() or "Organization"

    # Flag wins; otherwise seed from existing so re-run can pre-select in the menu.
    flag_use_case = use_case.lower() if use_case and use_case.lower() in USE_CASE_PRESETS else ""
    existing_use_case = (
        str(existing_wiki["use_case"])
        if existing_wiki.get("use_case") in USE_CASE_PRESETS
        else ""
    )
    selected_use_case = flag_use_case or existing_use_case

    parsed_rules = _normalize_rules(agent_rules) if rules_explicit else []
    existing_rules = _normalize_rules(existing_wiki.get("agent_rules", []))
    # True once the user (or --rules) has chosen a rules list, including an empty one.
    rules_resolved = rules_explicit
    # Interactive upkeep overrides; None means "resolve from preset/existing later".
    custom_upkeep: tuple[list[str], str] | None = None
    existing_proactivity = _normalize_proactivity(existing_upkeep.get("proactivity"))
    selected_proactivity = existing_proactivity or "selective"
    # True when interactive path chose proactivity (or non-interactive keeps existing/default).
    proactivity_resolved = False

    if interactive:
        print(f"┌  {C_BOLD}Brian setup{C_RESET}")
        print("│")
        print("│  A few questions. Change anything later in wiki.toml or by re-running init.")
        if is_rerun:
            print(
                f"│  {C_YELLOW}Re-run:{C_RESET} current values are pre-selected. "
                "Overview page & custom upkeep text are kept unless you change them."
            )
        print("│")
        try:
            # Always show use-case menu interactively (pre-select current / company).
            if not flag_use_case:
                preselect = selected_use_case or "company"
                use_case_options = [
                    (k, v["title"], v["hint"], k == preselect, False)
                    for k, v in USE_CASE_PRESETS.items()
                ]
                sel_uc = run_menu(
                    "What kind of knowledge base is this?",
                    use_case_options,
                    title="Brian setup",
                    single_select=True,
                )
                selected_use_case = sel_uc if sel_uc in USE_CASE_PRESETS else preselect

            if not selected_use_case:
                selected_use_case = "company"
            preset = USE_CASE_PRESETS[selected_use_case]

            default_org_name = (
                name
                or existing_wiki.get("name")
                or f"{raw_base_name} {preset['default_name_suffix']}"
            )
            if not name:
                name = _prompt(f"│  Organization name [{default_org_name}]: ", str(default_org_name))

            # Short name + description derived unless already provided via flags.
            default_short = (
                short_name
                or existing_wiki.get("short_name")
                or f"{raw_base_name} {preset['default_short_suffix']}"
            )
            if not short_name:
                short_name = str(default_short)

            default_desc = (
                description
                or existing_wiki.get("description")
                or preset["default_desc_template"].format(org=name)
            )
            if not description:
                description = str(default_desc)

            default_slug = (
                _slugify(str(name).replace("Knowledge Base", "").replace("Wiki", "")) + "-overview"
            )
            if not company_file_slug:
                existing_cf = str(existing_paths.get("company_file", "") or "")
                if existing_cf:
                    company_file_slug = Path(existing_cf).stem
                else:
                    company_file_slug = default_slug

            # --- Progressive disclosure: optional behavior multi-select ---
            if not rules_explicit:
                want_customize = run_confirm(
                    "Customize agent behavior now?",
                    default=False,
                    title="Brian setup",
                    confirm_label="choose optional behaviors",
                    cancel_label="keep defaults",
                )
                if want_customize:
                    seed = existing_rules if existing_rules else list(preset["default_rules"])
                    parsed_rules = _select_rules_interactively(list(preset["default_rules"]), seed)
                    rules_resolved = True  # empty multi-select is a deliberate "no extra rules"
                else:
                    prior_uc = existing_use_case
                    use_case_changed = bool(prior_uc) and prior_uc != selected_use_case
                    if existing_rules and not use_case_changed:
                        parsed_rules = list(existing_rules)
                    else:
                        parsed_rules = list(preset["default_rules"])
                    rules_resolved = True

            # Proactivity posture (always shown). Keep existing triggers/instructions unless
            # posture changes or the user custom-edits upkeep below.
            selected_proactivity = _select_proactivity_interactively(selected_proactivity)
            proactivity_resolved = True
            upkeep_triggers_preview, upkeep_instructions_preview = _resolve_upkeep(
                existing_upkeep,
                selected_use_case,
                selected_proactivity,
                None,
                prior_use_case=existing_use_case,
            )

            # Fine-tune triggers only when selective (use-case pack) or when re-running
            # the same posture with existing text. active/capture/silent *are* the control.
            prior_proactivity = existing_proactivity or "selective"
            offer_upkeep_edit = selected_proactivity == "selective" or (
                is_rerun
                and prior_proactivity == selected_proactivity
                and _existing_upkeep_pair(existing_upkeep) is not None
            )
            if offer_upkeep_edit:
                want_upkeep = run_confirm(
                    "Fine-tune triggers & instructions?",
                    default=False,
                    title="Brian setup",
                    confirm_label="edit text",
                    cancel_label="keep current",
                )
                if want_upkeep:
                    custom_upkeep = _customize_upkeep_interactively(
                        selected_use_case,
                        upkeep_triggers_preview,
                        upkeep_instructions_preview,
                    )
                    upkeep_triggers_preview, upkeep_instructions_preview = custom_upkeep

            company_rel_path = _clean_company_rel_path(company_file_slug, default_slug)
            enabled_rule_labels = [ALL_AGENT_RULES[r]["label"] for r in parsed_rules if r in ALL_AGENT_RULES]
            rules_summary = ", ".join(enabled_rule_labels) if enabled_rule_labels else "None (sensible defaults)"
            posture_title = UPKEEP_POSTURES[selected_proactivity]["title"]
            upkeep_summary = (
                f"{posture_title} · custom ({len(upkeep_triggers_preview)} triggers)"
                if custom_upkeep is not None
                else f"{posture_title} · {len(upkeep_triggers_preview)} triggers"
            )

            print("│")
            print(f"│  {C_BOLD}About to write:{C_RESET}")
            print(f"│    • Use case: {C_CYAN}{preset['title']}{C_RESET}")
            print(f"│    • Name: {name}")
            print(f"│    • Agent rules: {C_CYAN}{rules_summary}{C_RESET}")
            print(f"│    • Upkeep: {C_CYAN}{upkeep_summary}{C_RESET}")
            print(f"│    • Overview page: {company_rel_path}")
            print("│    • Files: wiki.toml, agent pointer, catalog indexes")
            if is_rerun:
                print(
                    f"│  {C_YELLOW}Re-run:{C_RESET} updates wiki.toml; keeps your overview page "
                    "and custom upkeep text unless you edited them above."
                )
            print("│")

            confirmed = run_confirm(
                "Save this setup?",
                default=True,
                title="Brian setup",
                confirm_label="save setup",
                cancel_label="cancel",
            )
            if not confirmed:
                print("\nInitialization cancelled.")
                return False

        except KeyboardInterrupt:
            print("\nInitialization cancelled.")
            return False

    # Non-interactive / resolved defaults
    if not selected_use_case:
        selected_use_case = "company"
    preset = USE_CASE_PRESETS[selected_use_case]

    if not rules_resolved:
        if rules_explicit:
            parsed_rules = []  # explicit empty list clears rules
        else:
            prior_use_case = str(existing_wiki.get("use_case") or "")
            use_case_changed = bool(use_case and prior_use_case and prior_use_case != selected_use_case)
            if existing_rules and not use_case_changed:
                # Re-run keeps prior rules unless the preset itself changed.
                parsed_rules = existing_rules
            else:
                parsed_rules = list(preset["default_rules"])

    org_name = name or existing_wiki.get("name") or f"{raw_base_name} {preset['default_name_suffix']}"
    org_short = (
        short_name
        or existing_wiki.get("short_name")
        or f"{raw_base_name} {preset['default_short_suffix']}"
    )
    org_desc = (
        description
        or existing_wiki.get("description")
        or preset["default_desc_template"].format(org=org_name)
    )
    default_slug = _slugify(str(org_name).replace("Knowledge Base", "").replace("Wiki", "")) + "-overview"
    if not company_file_slug and existing_paths.get("company_file"):
        company_file_slug = Path(str(existing_paths["company_file"])).stem
    company_rel_path = _clean_company_rel_path(company_file_slug, default_slug)

    if not proactivity_resolved:
        selected_proactivity = existing_proactivity or "selective"

    upkeep_triggers, upkeep_instructions = _resolve_upkeep(
        existing_upkeep,
        selected_use_case,
        selected_proactivity,
        custom_upkeep,
        prior_use_case=existing_use_case,
    )

    write_wiki_toml(
        toml_path,
        org_name=str(org_name),
        org_short=str(org_short),
        org_desc=str(org_desc),
        use_case=selected_use_case,
        agent_rules=parsed_rules,
        company_rel_path=company_rel_path,
        proactivity=selected_proactivity,
        triggers=upkeep_triggers,
        instructions=upkeep_instructions,
    )

    # Overview: create only if missing so re-runs never clobber hand edits.
    company_full_path = repo_root / company_rel_path
    company_full_path.parent.mkdir(parents=True, exist_ok=True)
    overview_created = False
    if not company_full_path.is_file():
        page_content = _generate_overview_content(
            selected_use_case, str(org_name), str(org_short), company_rel_path, repo_root
        )
        company_full_path.write_text(page_content, encoding="utf-8")
        overview_created = True

    _update_pointer_templates(
        repo_root,
        str(org_name),
        str(org_short),
        selected_use_case,
        parsed_rules,
        upkeep_triggers=upkeep_triggers,
        upkeep_instructions=upkeep_instructions,
        upkeep_proactivity=selected_proactivity,
    )

    wiki_dir = repo_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    db = WikiDatabase(wiki_dir)
    generate_index(db, wiki_dir)
    generate_backlinks(db, wiki_dir)
    generate_tags(db, wiki_dir)
    generate_registry(repo_root)

    rule_labels = [ALL_AGENT_RULES[r]["label"] for r in parsed_rules if r in ALL_AGENT_RULES]
    rules_human = ", ".join(rule_labels) if rule_labels else "none"

    print("│")
    print(f"│  {S_CHECK_GREEN} Wrote {C_CYAN}wiki.toml{C_RESET}  ({org_name})")
    if overview_created:
        print(f"│  {S_CHECK_GREEN} Created overview  {C_CYAN}{company_rel_path}{C_RESET}")
    else:
        print(f"│  {S_CHECK_GREEN} Kept existing overview  {C_CYAN}{company_rel_path}{C_RESET}")
    print(f"│  {S_CHECK_GREEN} Updated agent instructions  {C_CYAN}_templates/agent-pointer.md{C_RESET}")
    print(f"│  {S_CHECK_GREEN} Regenerated catalog indexes")
    print(f"│  Active rules: {C_CYAN}{rules_human}{C_RESET}")
    print("│")
    print(f"└  {C_BOLD}Done.{C_RESET}  Preset: {preset['title']}")
    print()
    print(f"   Edit anytime:  open {C_CYAN}wiki.toml{C_RESET}  (agent_rules, name, [upkeep])")
    print(f"   Or re-run:     {C_CYAN}wiki init{C_RESET}  (current values pre-selected)")
    print(f"   Stock restore: {C_CYAN}wiki reset settings{C_RESET}  (upkeep|identity|all|factory)")
    print(f"   How to customize: README → {C_BOLD}Customize in plain English{C_RESET}")
    print()
    print(f"   {C_BOLD}Next:{C_RESET} {C_CYAN}wiki install{C_RESET}  → connect Claude, Cursor, Codex, Gemini, …")
    return True


def _update_pointer_templates(
    repo_root: Path,
    org_name: str,
    org_short: str,
    use_case: str,
    agent_rules: list[str],
    *,
    upkeep_triggers: list[str] | None = None,
    upkeep_instructions: str = "",
    upkeep_proactivity: str = "",
) -> None:
    """Updates _templates/agent-pointer.md and internal/skills/wiki-context/SKILL.md with active config."""
    from .brief import format_rules_block, format_upkeep_block

    pointer_path = repo_root / "_templates" / "agent-pointer.md"

    rules_md = format_rules_block(agent_rules, ALL_AGENT_RULES)
    upkeep_md = format_upkeep_block(upkeep_triggers, upkeep_instructions, upkeep_proactivity)
    # Pointer sits inside agent instruction files — strip top-level ## headings.
    rules_block = ("\n" + rules_md.replace("## Active agent rules\n", "Active agent rules:\n")) if rules_md else ""
    upkeep_block = (
        "\n" + upkeep_md.replace("## Keeping it current\n", "Keeping it current:\n")
    ) if upkeep_md else ""

    pointer_content = f"""<!-- brian-wiki:start -->
## {org_name}

{org_name} ({org_short}) keeps company, product, technical, and operational context in a central knowledge base
located at `$(wiki root)`. It is **not** code documentation — it holds business, technical, and domain
knowledge that no repository contains. The CLI is on your PATH.

- Context for where you are: `wiki context "$PWD"`
- Query curated knowledge: `wiki knowledge query "<question>"`
- Read a returned page: `wiki knowledge read "<ref>"` (path, URI, title, `[[Wikilink]]`, or stem)
- Catalog: `wiki/index.md` inside `$(wiki root)`

Cite pages as `[[Wikilink]]`, and never invent wiki facts — query first.
{rules_block}{upkeep_block}
For durable source-backed knowledge, discover existing evidence with `wiki knowledge sources [raw/path]`, prepare
one JSON update payload, and run
`wiki knowledge update --input <payload.json>` to preview it without writes. Show the proposed changes to the
user only after status is `ready`; repair structured `needs_revision` diagnostics yourself. Then apply the
unchanged payload with
`wiki knowledge update --input <payload.json> --approve <approval_digest>`. The command owns raw capture,
source accounting, retrieval cases, generated files, validation, and rollback; it never commits or pushes.
The complete payload contract and source placeholder are documented in
`$(wiki root)/internal/skills/wiki-context/SKILL.md`.
<!-- brian-wiki:end -->
"""
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(pointer_content, encoding="utf-8")

    skill_path = repo_root / "internal" / "skills" / "wiki-context" / "SKILL.md"
    if skill_path.is_file():
        content = skill_path.read_text(encoding="utf-8")
        new_desc = f"Resolve company, project, and related context from the {org_short} (the company brain) from any repo."
        content = re.sub(
            r"^description:.*$", f"description: {new_desc}", content, flags=re.MULTILINE
        )
        skill_path.write_text(content, encoding="utf-8")
