"""SessionStart hook payload contract.

This output is injected into every session of every agent in every repo. Three agents (Claude Code,
Codex, Gemini CLI) consume the same JSON shape, so a malformed payload breaks all of them at once and
does so silently — the session simply starts with no company context and nobody notices.

Two real incidents these tests guard:
- A TOML fallback parser turned the upkeep triggers into the single character `[`, so the brief read
  `Triggers: [` and the keep-the-wiki-current rule vanished from every session.
- The resolver returned nothing, so the "Working context" block disappeared while the payload stayed
  valid JSON and every test still passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikicli.lifecycle.hook import run_session_start_hook
from wikicli.lifecycle.sync import SyncResult, SyncState

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def current_wiki_sync(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "wikicli.lifecycle.hook.sync_wiki",
        lambda _repo_root: SyncResult(SyncState.CURRENT, "wiki main is current", True, 1000),
    )


def payload(repo_root: Path = REPO_ROOT, cwd: str | None = None) -> str:
    raw = run_session_start_hook(repo_root, json.dumps({"cwd": cwd}) if cwd else "")
    data = json.loads(raw)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return data["hookSpecificOutput"]["additionalContext"]


class TestEnvelope:
    def test_output_is_valid_json(self):
        json.loads(run_session_start_hook(REPO_ROOT))

    def test_envelope_shape_matches_all_three_agents(self):
        """Claude Code, Codex and Gemini CLI all require this exact nesting."""
        data = json.loads(run_session_start_hook(REPO_ROOT))
        assert set(data) == {"hookSpecificOutput"}
        inner = data["hookSpecificOutput"]
        assert inner["hookEventName"] == "SessionStart"
        assert isinstance(inner["additionalContext"], str)

    def test_missing_repo_yields_valid_empty_payload(self, tmp_path: Path):
        """A broken install must not emit malformed JSON — that would break session startup."""
        data = json.loads(run_session_start_hook(tmp_path / "nope"))
        assert data["hookSpecificOutput"]["additionalContext"] == ""

    def test_malformed_stdin_does_not_crash(self):
        json.loads(run_session_start_hook(REPO_ROOT, "not json at all"))


class TestContent:
    def test_identifies_the_knowledge_base_and_not_code_docs(self):
        text = payload()
        assert "knowledge base" in text.lower()
        assert "not code documentation" in text.lower(), "the framing is load-bearing; agents conflate the two"

    def test_includes_company_context(self):
        from wikicli.core.config import WikiConfig

        cfg = WikiConfig(REPO_ROOT)
        text = payload()
        assert "knowledge base" in text.lower()
        rel = cfg.company_file.relative_to(REPO_ROOT).as_posix()
        assert f"(`{rel}`)" in text

    def test_includes_the_catalog(self):
        assert "[[" in payload(), "the brief must list pages as wikilinks"

    def test_upkeep_rule_is_present_and_not_corrupted(self):
        """Regression: a bad TOML reader rendered this as the literal string `Triggers: [`."""
        text = payload()
        assert "Triggers: [" not in text, "upkeep triggers failed to parse into a list"
        assert "wiki" in text.lower()

    def test_situated_block_present_for_a_known_repo(self):
        """The whole value proposition. Its absence is invisible without this assertion."""
        text = payload(cwd="/Users/anyone/Repos/pulsar")
        assert (
            "Working context" in text
            or "[[Context Cascade]]" in text
            or "Overview" in text
        )

    def test_backlog_is_not_injected(self):
        """`## Backlog` is maintenance bookkeeping for `wiki lint`, not session context."""
        assert "## Backlog" not in payload()

    def test_sync_failure_keeps_context_and_adds_a_freshness_warning(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "wikicli.lifecycle.hook.sync_wiki",
            lambda _repo_root: SyncResult(SyncState.UNAVAILABLE, "wiki fetch failed; using local context", None),
        )

        text = payload()

        assert "Wiki freshness" in text
        assert "may not match `origin/main`" in text
        assert "knowledge base" in text.lower()

    def test_empty_agent_rules_omits_rules_block(self):
        """Default company preset must not inject people-tracking prompts."""
        text = payload()
        assert "## Active agent rules" not in text


class TestBudget:
    def test_payload_stays_within_a_sane_size_budget(self):
        """Paid on every session start by every agent.

        index.md warns against unbounded growth. 12KB is generous; crossing it means the catalog or
        the upkeep prose has grown and should be trimmed deliberately, not by accident.
        """
        size = len(payload())
        assert 500 < size < 12_000, f"payload is {size} chars — review what grew"
