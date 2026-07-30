"""Shared session-brief formatters."""

from __future__ import annotations

from wikicli.lifecycle.brief import format_rules_block, format_upkeep_block


def test_format_upkeep_includes_triggers_and_instructions():
    block = format_upkeep_block(
        ["Ship a feature", "Update a policy"],
        "Ask before writing. Never commit.",
        "capture",
    )
    assert block.startswith("## Keeping it current\n")
    assert "Proactivity:" in block
    assert "- Ship a feature" in block
    assert "- Update a policy" in block
    assert "Ask before writing" in block


def test_format_upkeep_empty():
    assert format_upkeep_block([], "", "") == ""
    assert format_upkeep_block(None, None, "") == ""


def test_format_rules_includes_page_guidance():
    catalog = {
        "people_tracking": {
            "prompt_rule": "• People rule",
            "page_guidance": "Person page shape: role + manager",
        },
        "security_notice": {
            "prompt_rule": "• Security rule",
        },
    }
    block = format_rules_block(["people_tracking", "security_notice", "unknown"], catalog)
    assert "## Active agent rules" in block
    assert "• People rule" in block
    assert "  Person page shape" in block
    assert "• Security rule" in block
    assert "unknown" not in block
