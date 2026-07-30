"""Unit tests for wikicli.lifecycle.init module."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from wikicli.core.config import WikiConfig
from wikicli.lifecycle.hook import run_session_start_hook
from wikicli.lifecycle.init import (
    ALL_AGENT_RULES,
    RULE_HELP_TEXT,
    USE_CASE_PRESETS,
    _clean_company_rel_path,
    _normalize_rules,
    run_init,
)
from wikicli.lifecycle.sync import SyncResult, SyncState


def test_clean_company_rel_path():
    assert _clean_company_rel_path("acme-overview", "default") == "wiki/entities/acme-overview.md"
    assert _clean_company_rel_path("wiki/entities/acme-overview.md", "default") == "wiki/entities/acme-overview.md"
    assert _clean_company_rel_path("acme-overview.md", "default") == "wiki/entities/acme-overview.md"
    assert _clean_company_rel_path("", "default-slug") == "wiki/entities/default-slug.md"


def test_normalize_rules_filters_unknown_and_dupes():
    assert _normalize_rules("people_tracking, no_such_rule, people_tracking, adrs") == [
        "people_tracking",
        "adrs",
    ]
    assert _normalize_rules([]) == []
    assert _normalize_rules(None) == []


def test_company_preset_does_not_force_people_tracking():
    """Generic company brains should not opt everyone into people-on-entities tracking."""
    assert USE_CASE_PRESETS["company"]["default_rules"] == []
    assert "people_tracking" in USE_CASE_PRESETS["it_service_desk"]["default_rules"]


def test_rule_help_text_is_plain_english():
    assert "people_tracking" in RULE_HELP_TEXT
    assert "people" in RULE_HELP_TEXT.lower()
    for key in ALL_AGENT_RULES:
        assert key in RULE_HELP_TEXT


def test_run_init_non_interactive_company_defaults(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    ok = run_init(
        tmp_path,
        name="Acme Corp Knowledge Base",
        short_name="Acme Wiki",
        description="Acme team brain",
        company_file_slug="acme-overview",
        non_interactive=True,
    )
    assert ok is True

    toml_file = tmp_path / "wiki.toml"
    assert toml_file.is_file()

    with open(toml_file, "rb") as f:
        data = tomllib.load(f)

    assert data["wiki"]["name"] == "Acme Corp Knowledge Base"
    assert data["wiki"]["short_name"] == "Acme Wiki"
    assert data["wiki"]["use_case"] == "company"
    assert data["wiki"]["agent_rules"] == []
    assert data["paths"]["company_file"] == "wiki/entities/acme-overview.md"
    assert "edit freely in plain English" in toml_file.read_text(encoding="utf-8")

    overview = tmp_path / "wiki" / "entities" / "acme-overview.md"
    assert overview.is_file()
    text = overview.read_text(encoding="utf-8")
    assert "Acme Corp Knowledge Base Overview" in text
    assert "title:" in text
    assert "scope: global" in text

    pointer = tmp_path / "_templates" / "agent-pointer.md"
    assert pointer.is_file()
    pointer_text = pointer.read_text(encoding="utf-8")
    assert "Acme Corp Knowledge Base" in pointer_text
    # Company default: no people-tracking prompt injected.
    assert "People & Team Directory" not in pointer_text


def test_run_init_it_service_desk_preset(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    ok = run_init(
        tmp_path,
        use_case="it_service_desk",
        name="Acme IT Knowledge Base",
        short_name="Acme IT Wiki",
        description="IT Helpdesk and Hardware tracking",
        company_file_slug="acme-it-overview",
        non_interactive=True,
    )
    assert ok is True

    toml_file = tmp_path / "wiki.toml"
    with open(toml_file, "rb") as f:
        data = tomllib.load(f)

    assert data["wiki"]["use_case"] == "it_service_desk"
    assert "people_tracking" in data["wiki"]["agent_rules"]
    assert "asset_tracking" in data["wiki"]["agent_rules"]
    assert "security_notice" in data["wiki"]["agent_rules"]

    overview = tmp_path / "wiki" / "entities" / "acme-it-overview.md"
    text = overview.read_text(encoding="utf-8")
    assert "IT & Service Desk knowledge base" in text
    assert "People & Role Directory" in text

    pointer = tmp_path / "_templates" / "agent-pointer.md"
    pointer_text = pointer.read_text(encoding="utf-8")
    assert "People & Team Directory" in pointer_text
    assert "IT Asset & Access SOPs" in pointer_text


def test_run_init_engineering_preset_with_custom_rules(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    ok = run_init(
        tmp_path,
        use_case="engineering",
        agent_rules="adrs,strict_sources",
        name="Tech Brain",
        short_name="Tech Wiki",
        non_interactive=True,
    )
    assert ok is True

    toml_file = tmp_path / "wiki.toml"
    with open(toml_file, "rb") as f:
        data = tomllib.load(f)

    assert data["wiki"]["use_case"] == "engineering"
    assert "adrs" in data["wiki"]["agent_rules"]
    assert "strict_sources" in data["wiki"]["agent_rules"]


def test_run_init_preserves_overview_and_upkeep_on_rerun(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        name="Acme Knowledge Base",
        short_name="Acme",
        company_file_slug="acme-overview",
        non_interactive=True,
    )

    overview = tmp_path / "wiki" / "entities" / "acme-overview.md"
    custom_body = overview.read_text(encoding="utf-8") + "\n\n## Hand edit\nDo not clobber me.\n"
    overview.write_text(custom_body, encoding="utf-8")

    toml_path = tmp_path / "wiki.toml"
    text = toml_path.read_text(encoding="utf-8")
    text = text.replace(
        'instructions = """',
        'instructions = """\nCUSTOM_UPKEEP_MARKER: keep this hand edit.\n',
        1,
    )
    toml_path.write_text(text, encoding="utf-8")

    assert run_init(
        tmp_path,
        name="Acme Knowledge Base Renamed",
        short_name="Acme",
        company_file_slug="acme-overview",
        agent_rules="people_tracking",
        non_interactive=True,
    )

    assert "Do not clobber me." in overview.read_text(encoding="utf-8")
    new_toml = toml_path.read_text(encoding="utf-8")
    assert "CUSTOM_UPKEEP_MARKER" in new_toml
    assert "Acme Knowledge Base Renamed" in new_toml

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["wiki"]["agent_rules"] == ["people_tracking"]


def test_run_init_can_clear_rules_with_empty_list(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    run_init(tmp_path, use_case="it_service_desk", name="IT", non_interactive=True)
    run_init(
        tmp_path,
        use_case="company",
        name="IT",
        agent_rules=[],
        non_interactive=True,
    )
    with open(tmp_path / "wiki.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["wiki"]["agent_rules"] == []


def test_select_rules_interactively_uses_multi_select(monkeypatch):
    from wikicli.lifecycle import init as init_mod

    calls: list[dict] = []

    def fake_menu(prompt, options=None, title="Brian setup", non_interactive=False, single_select=False):
        calls.append({"prompt": prompt, "options": options, "single_select": single_select})
        assert single_select is False
        assert options is not None
        # Seed should pre-check people_tracking
        selected = {o[0]: o[3] for o in options}
        assert selected["people_tracking"] is True
        assert selected["adrs"] is False
        return "people_tracking security_notice"

    monkeypatch.setattr(init_mod, "run_menu", fake_menu)
    chosen = init_mod._select_rules_interactively(["adrs"], existing_rules=["people_tracking"])
    assert chosen == ["people_tracking", "security_notice"]
    assert len(calls) == 1


def test_select_rules_interactively_empty_selection(monkeypatch):
    from wikicli.lifecycle import init as init_mod

    monkeypatch.setattr(init_mod, "run_menu", lambda *a, **k: "")
    assert init_mod._select_rules_interactively(["adrs"], existing_rules=["adrs"]) == []


def test_customize_upkeep_interactively_keep_defaults(monkeypatch):
    from wikicli.lifecycle import init as init_mod

    # Keep triggers (True), skip editing instructions (False)
    answers = iter([True, False])
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(answers))

    triggers = ["Trigger A", "Trigger B"]
    instructions = "Leave the user in charge."
    out_t, out_i = init_mod._customize_upkeep_interactively("company", triggers, instructions)
    assert out_t == triggers
    assert out_i == instructions


def test_customize_upkeep_interactively_edits_both(monkeypatch):
    from wikicli.lifecycle import init as init_mod

    answers = iter([False, True])  # edit triggers, edit instructions
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(
        init_mod,
        "_prompt_multiline",
        lambda header, blank_keeps_current=True: (
            ["New trigger one", "New trigger two"]
            if "triggers" in header.lower()
            else ["Offer updates only when asked."]
        ),
    )

    out_t, out_i = init_mod._customize_upkeep_interactively(
        "engineering",
        ["Old trigger"],
        "Old instructions",
    )
    assert out_t == ["New trigger one", "New trigger two"]
    assert out_i == "Offer updates only when asked."


def _fake_init_menu(prompt, options=None, title="Brian setup", non_interactive=False, single_select=False):
    """Interactive init uses single-select for use-case and proactivity."""
    if single_select:
        ids = [o[0] for o in (options or [])]
        if "selective" in ids:
            return "selective"
        if "company" in ids:
            return "company"
        return ids[0] if ids else ""
    return "adrs strict_sources"


def test_run_init_interactive_custom_upkeep_and_rules(tmp_path: Path, monkeypatch):
    """Interactive path: multi-select rules + custom upkeep write through to wiki.toml."""
    from wikicli.lifecycle import init as init_mod

    (tmp_path / "wiki").mkdir()

    # Sequence of run_confirm: customize rules? Y, customize upkeep? Y, keep triggers? N,
    # edit instructions? Y, save? Y  (proactivity is a menu, not confirm)
    confirm_answers = iter([True, True, False, True, True])
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(confirm_answers))
    monkeypatch.setattr(init_mod, "run_menu", _fake_init_menu)
    monkeypatch.setattr(init_mod, "_prompt", lambda text, default: "Interactive Co")
    monkeypatch.setattr(
        init_mod,
        "_prompt_multiline",
        lambda header, blank_keeps_current=True: (
            ["Ship a user-facing change", "Update a policy doc"]
            if "triggers" in header.lower()
            else ["Ask before writing. Never push."]
        ),
    )
    # Force interactive branch even without a real TTY.
    monkeypatch.setattr(init_mod.sys.stdin, "isatty", lambda: True)

    ok = run_init(tmp_path, non_interactive=False)
    assert ok is True

    with open(tmp_path / "wiki.toml", "rb") as f:
        data = tomllib.load(f)

    assert data["wiki"]["name"] == "Interactive Co"
    assert data["wiki"]["use_case"] == "company"
    assert data["wiki"]["agent_rules"] == ["adrs", "strict_sources"]
    assert data["upkeep"]["proactivity"] == "selective"
    assert data["upkeep"]["triggers"] == ["Ship a user-facing change", "Update a policy doc"]
    assert "Ask before writing" in data["upkeep"]["instructions"]

    toml_text = (tmp_path / "wiki.toml").read_text(encoding="utf-8")
    assert "edit freely in plain English" in toml_text
    assert "[upkeep]" in toml_text

    pointer = (tmp_path / "_templates" / "agent-pointer.md").read_text(encoding="utf-8")
    assert "Ship a user-facing change" in pointer
    assert "Ask before writing" in pointer


def test_run_init_interactive_rerun_preserves_upkeep_when_skipped(tmp_path: Path, monkeypatch):
    from wikicli.lifecycle import init as init_mod

    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        name="Preserve Co",
        company_file_slug="preserve-overview",
        non_interactive=True,
    )
    toml_path = tmp_path / "wiki.toml"
    text = toml_path.read_text(encoding="utf-8")
    text = text.replace(
        'instructions = """',
        'instructions = """\nKEEP_ME_ON_RERUN\n',
        1,
    )
    toml_path.write_text(text, encoding="utf-8")

    # customize rules? N, customize upkeep? N, save? Y
    confirm_answers = iter([False, False, True])
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(confirm_answers))
    monkeypatch.setattr(init_mod, "run_menu", _fake_init_menu)
    monkeypatch.setattr(init_mod, "_prompt", lambda text, default: default)
    monkeypatch.setattr(init_mod.sys.stdin, "isatty", lambda: True)

    assert run_init(tmp_path, non_interactive=False) is True
    assert "KEEP_ME_ON_RERUN" in toml_path.read_text(encoding="utf-8")


def test_run_init_writes_proactivity_and_pointer_upkeep(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        name="Posture Co",
        short_name="PC",
        company_file_slug="posture-overview",
        non_interactive=True,
    )
    with open(tmp_path / "wiki.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["upkeep"]["proactivity"] == "selective"
    assert data["upkeep"]["triggers"]
    pointer = (tmp_path / "_templates" / "agent-pointer.md").read_text(encoding="utf-8")
    assert "Keeping it current" in pointer
    assert str(data["upkeep"]["triggers"][0]) in pointer
    assert "Proactivity:" in pointer or "selective" in pointer


def test_run_init_posture_change_rewrites_upkeep(tmp_path: Path, monkeypatch):
    """Changing proactivity must replace triggers/instructions, not only the label."""
    from wikicli.lifecycle import init as init_mod

    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        name="Posture Flip Co",
        company_file_slug="posture-flip",
        non_interactive=True,
    )
    with open(tmp_path / "wiki.toml", "rb") as f:
        before = tomllib.load(f)
    old_first = before["upkeep"]["triggers"][0]
    capture_first = init_mod.UPKEEP_POSTURES["capture"]["triggers"][0]
    assert old_first != capture_first

    # capture/active/silent skip the fine-tune step — only rules? + save?
    confirm_answers = iter([False, True])  # rules N, save Y
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(confirm_answers))

    def menu(prompt, options=None, title="Brian setup", non_interactive=False, single_select=False):
        if single_select:
            ids = [o[0] for o in (options or [])]
            if "capture" in ids:
                return "capture"
            if "company" in ids:
                return "company"
            return ids[0] if ids else ""
        return ""

    monkeypatch.setattr(init_mod, "run_menu", menu)
    monkeypatch.setattr(init_mod, "_prompt", lambda text, default: default)
    monkeypatch.setattr(init_mod.sys.stdin, "isatty", lambda: True)

    assert run_init(tmp_path, non_interactive=False) is True
    with open(tmp_path / "wiki.toml", "rb") as f:
        after = tomllib.load(f)
    assert after["upkeep"]["proactivity"] == "capture"
    assert after["upkeep"]["triggers"] == list(init_mod.UPKEEP_POSTURES["capture"]["triggers"])
    assert old_first not in after["upkeep"]["triggers"]
    pointer = (tmp_path / "_templates" / "agent-pointer.md").read_text(encoding="utf-8")
    assert capture_first in pointer
    assert "prefer logging" in pointer


def test_run_init_legacy_manifest_applies_new_posture(tmp_path: Path, monkeypatch):
    """Pre-proactivity wiki.toml treated as selective; picking active rewrites packs."""
    from wikicli.lifecycle import init as init_mod

    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        name="Legacy Co",
        company_file_slug="legacy-overview",
        non_interactive=True,
    )
    toml_path = tmp_path / "wiki.toml"
    text = toml_path.read_text(encoding="utf-8")
    text = text.replace('proactivity = "selective"\n', "")
    toml_path.write_text(text, encoding="utf-8")
    with open(toml_path, "rb") as f:
        legacy = tomllib.load(f)
    assert "proactivity" not in legacy.get("upkeep", {})
    old_first = legacy["upkeep"]["triggers"][0]
    active_first = init_mod.UPKEEP_POSTURES["active"]["triggers"][0]

    # active posture skips fine-tune — only rules? + save?
    confirm_answers = iter([False, True])
    monkeypatch.setattr(init_mod, "run_confirm", lambda *a, **k: next(confirm_answers))

    def menu(prompt, options=None, title="Brian setup", non_interactive=False, single_select=False):
        if single_select:
            ids = [o[0] for o in (options or [])]
            if "active" in ids:
                return "active"
            if "company" in ids:
                return "company"
            return ids[0] if ids else ""
        return ""

    monkeypatch.setattr(init_mod, "run_menu", menu)
    monkeypatch.setattr(init_mod, "_prompt", lambda text, default: default)
    monkeypatch.setattr(init_mod.sys.stdin, "isatty", lambda: True)

    assert run_init(tmp_path, non_interactive=False) is True
    with open(toml_path, "rb") as f:
        after = tomllib.load(f)
    assert after["upkeep"]["proactivity"] == "active"
    assert after["upkeep"]["triggers"][0] == active_first
    assert old_first not in after["upkeep"]["triggers"]


def test_agent_rules_flow_into_session_start_hook(tmp_path: Path, monkeypatch):
    """wiki.toml agent_rules must surface in the SessionStart payload agents actually see."""
    monkeypatch.setattr(
        "wikicli.lifecycle.hook.sync_wiki",
        lambda _repo_root: SyncResult(SyncState.CURRENT, "ok", True, 1000),
    )
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    assert run_init(
        tmp_path,
        name="Rules Hook Co",
        short_name="RHC",
        agent_rules=["people_tracking", "security_notice"],
        company_file_slug="rules-hook-overview",
        non_interactive=True,
    )

    cfg = WikiConfig(tmp_path)
    assert cfg.agent_rules == ["people_tracking", "security_notice"]

    raw = run_session_start_hook(tmp_path, "")
    ctx = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert "Active agent rules" in ctx
    assert "People & Team Directory" in ctx
    assert "Security & Secrets Policy" in ctx
    assert "Person page shape" in ctx
    assert "## Keeping it current" in ctx
    assert cfg.upkeep_triggers
    assert cfg.upkeep_triggers[0] in ctx
    assert "never commit" in ctx.lower() or "Never commit" in ctx

def test_resolve_upkeep_refreshes_stock_on_use_case_change():
    """Company stock + selective → engineering applies engineering pack."""
    from wikicli.lifecycle import init as init_mod

    company = init_mod._upkeep_for_posture("company", "selective")
    engineering = init_mod._upkeep_for_posture("engineering", "selective")
    assert company != engineering

    existing = {
        "proactivity": "selective",
        "triggers": list(company[0]),
        "instructions": company[1],
    }
    got = init_mod._resolve_upkeep(
        existing, "engineering", "selective", None, prior_use_case="company"
    )
    assert got == engineering


def test_resolve_upkeep_preserves_custom_on_use_case_change():
    """Hand-edited selective text survives use-case switch."""
    from wikicli.lifecycle import init as init_mod

    custom_t = ["My custom trigger that is not stock"]
    custom_i = "My custom instructions."
    existing = {
        "proactivity": "selective",
        "triggers": custom_t,
        "instructions": custom_i,
    }
    got = init_mod._resolve_upkeep(
        existing, "engineering", "selective", None, prior_use_case="company"
    )
    assert got == (custom_t, custom_i)


def test_resolve_upkeep_same_use_case_preserves_stock():
    """Re-run same use case keeps stock text (no spurious rewrite)."""
    from wikicli.lifecycle import init as init_mod

    company = init_mod._upkeep_for_posture("company", "selective")
    existing = {
        "proactivity": "selective",
        "triggers": list(company[0]),
        "instructions": company[1],
    }
    got = init_mod._resolve_upkeep(
        existing, "company", "selective", None, prior_use_case="company"
    )
    assert got == company


def test_run_init_use_case_change_refreshes_selective_stock(tmp_path: Path):
    """Non-interactive company → engineering swaps selective stock packs."""
    from wikicli.lifecycle import init as init_mod

    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        use_case="company",
        name="Swap Co",
        company_file_slug="swap-overview",
        non_interactive=True,
    )
    with open(tmp_path / "wiki.toml", "rb") as f:
        before = tomllib.load(f)
    assert before["wiki"]["use_case"] == "company"
    company_first = before["upkeep"]["triggers"][0]
    eng_first = init_mod._upkeep_for_posture("engineering", "selective")[0][0]
    assert company_first != eng_first

    assert run_init(
        tmp_path,
        use_case="engineering",
        name="Swap Co",
        company_file_slug="swap-overview",
        non_interactive=True,
    )
    with open(tmp_path / "wiki.toml", "rb") as f:
        after = tomllib.load(f)
    assert after["wiki"]["use_case"] == "engineering"
    assert after["upkeep"]["proactivity"] == "selective"
    assert after["upkeep"]["triggers"][0] == eng_first
    assert company_first not in after["upkeep"]["triggers"]
    assert "adrs" in after["wiki"]["agent_rules"]


def test_run_init_use_case_change_keeps_custom_upkeep(tmp_path: Path):
    """Custom selective text is not wiped when use case changes."""
    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        use_case="company",
        name="Custom Keep Co",
        company_file_slug="custom-keep",
        non_interactive=True,
    )
    toml_path = tmp_path / "wiki.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    # Rewrite with a clearly non-stock first trigger while keeping selective posture.
    triggers = list(data["upkeep"]["triggers"])
    triggers[0] = "CUSTOM_KEEP_TRIGGER"
    data["upkeep"]["triggers"] = triggers
    # Serialize minimally via run path: rewrite TOML triggers block from current file.
    raw = toml_path.read_text(encoding="utf-8")
    old_first = next(iter(tomllib.loads(raw)["upkeep"]["triggers"]))
    raw = raw.replace(old_first, "CUSTOM_KEEP_TRIGGER", 1)
    toml_path.write_text(raw, encoding="utf-8")

    assert run_init(
        tmp_path,
        use_case="engineering",
        name="Custom Keep Co",
        company_file_slug="custom-keep",
        non_interactive=True,
    )
    with open(toml_path, "rb") as f:
        after = tomllib.load(f)
    assert after["wiki"]["use_case"] == "engineering"
    assert after["upkeep"]["triggers"][0] == "CUSTOM_KEEP_TRIGGER"
