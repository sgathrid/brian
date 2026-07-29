"""Tests for Brian-only wiki settings restore (wiki.toml personalization)."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from wikicli.lifecycle.init import USE_CASE_PRESETS, _upkeep_for_posture, run_init, write_wiki_toml
from wikicli.lifecycle.settings_restore import run_settings_restore


def _seed_custom(tmp_path: Path) -> Path:
    """Engineering checkout with hand-edited upkeep + custom identity."""
    (tmp_path / "wiki").mkdir()
    assert run_init(
        tmp_path,
        use_case="engineering",
        name="Custom Co",
        short_name="Custom",
        description="custom desc",
        agent_rules="adrs,security_notice",
        company_file_slug="custom-overview",
        non_interactive=True,
    )
    toml_path = tmp_path / "wiki.toml"
    write_wiki_toml(
        toml_path,
        org_name="Custom Co",
        org_short="Custom",
        org_desc="custom desc",
        use_case="engineering",
        agent_rules=["adrs", "security_notice"],
        company_rel_path="wiki/entities/custom-overview.md",
        proactivity="active",
        triggers=["CUSTOM TRIGGER ONLY"],
        instructions="HAND EDITED INSTRUCTIONS",
    )
    return toml_path


def test_restore_upkeep_stock_pack(tmp_path: Path):
    toml_path = _seed_custom(tmp_path)
    ok = run_settings_restore(
        tmp_path, "upkeep", dry_run=False, non_interactive=True, confirmed=True
    )
    assert ok is True
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["wiki"]["name"] == "Custom Co"
    assert data["upkeep"]["proactivity"] == "active"
    stock_t, stock_i = _upkeep_for_posture("engineering", "active")
    assert data["upkeep"]["triggers"] == stock_t
    assert data["upkeep"]["instructions"].strip() == stock_i.strip()
    assert "HAND EDITED" not in data["upkeep"]["instructions"]
    assert data["wiki"]["agent_rules"] == ["adrs", "security_notice"]


def test_restore_identity_keeps_upkeep(tmp_path: Path):
    toml_path = _seed_custom(tmp_path)
    before = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    ok = run_settings_restore(
        tmp_path, "identity", dry_run=False, non_interactive=True, confirmed=True
    )
    assert ok is True
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["wiki"]["name"] != "Custom Co"
    assert data["upkeep"]["instructions"].strip() == before["upkeep"]["instructions"].strip()
    assert data["upkeep"]["triggers"] == before["upkeep"]["triggers"]
    assert data["wiki"]["agent_rules"] == before["wiki"]["agent_rules"]


def test_restore_all_selective_and_default_rules(tmp_path: Path):
    toml_path = _seed_custom(tmp_path)
    ok = run_settings_restore(
        tmp_path, "all", dry_run=False, non_interactive=True, confirmed=True
    )
    assert ok is True
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["upkeep"]["proactivity"] == "selective"
    stock_t, stock_i = _upkeep_for_posture("engineering", "selective")
    assert data["upkeep"]["triggers"] == stock_t
    assert data["upkeep"]["instructions"].strip() == stock_i.strip()
    assert data["wiki"]["agent_rules"] == list(USE_CASE_PRESETS["engineering"]["default_rules"])
    assert data["wiki"]["use_case"] == "engineering"


def test_restore_all_use_case_stock(tmp_path: Path):
    toml_path = _seed_custom(tmp_path)
    ok = run_settings_restore(
        tmp_path,
        "all",
        dry_run=False,
        non_interactive=True,
        confirmed=True,
        stock_use_case=True,
    )
    assert ok is True
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["wiki"]["use_case"] == "company"
    assert data["wiki"]["agent_rules"] == []
    stock_t, stock_i = _upkeep_for_posture("company", "selective")
    assert data["upkeep"]["triggers"] == stock_t
    assert data["upkeep"]["instructions"].strip() == stock_i.strip()


def test_restore_dry_run_no_write(tmp_path: Path):
    toml_path = _seed_custom(tmp_path)
    before = toml_path.read_text(encoding="utf-8")
    ok = run_settings_restore(
        tmp_path, "upkeep", dry_run=True, non_interactive=True, confirmed=False
    )
    assert ok is True
    assert toml_path.read_text(encoding="utf-8") == before


def test_restore_requires_confirm_noninteractive(tmp_path: Path):
    _seed_custom(tmp_path)
    with pytest.raises(SystemExit) as ei:
        run_settings_restore(
            tmp_path, "upkeep", dry_run=False, non_interactive=True, confirmed=False
        )
    assert ei.value.code == 2


def test_restore_unknown_target(tmp_path: Path):
    _seed_custom(tmp_path)
    with pytest.raises(SystemExit) as ei:
        run_settings_restore(
            tmp_path, "pages", dry_run=True, non_interactive=True, confirmed=True
        )
    assert ei.value.code == 2


def test_cli_settings_restore_help():
    from wikicli.cli import main

    old = sys.argv
    try:
        sys.argv = ["wiki", "settings", "restore", "-h"]
        with pytest.raises(SystemExit) as ei:
            main()
        assert ei.value.code == 0
    finally:
        sys.argv = old
