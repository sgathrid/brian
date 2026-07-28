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
    assert "Edit freely" in toml_file.read_text(encoding="utf-8")

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
