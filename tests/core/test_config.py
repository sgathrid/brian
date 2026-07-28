"""wiki.toml manifest loading.

`wiki.toml` is what makes the engine reusable beyond this repo, so its parsing must be exact. The
values that matter most — `upkeep.triggers` (a multi-line array) and `upkeep.instructions` (a
triple-quoted string) — are precisely the two a hand-rolled line-based TOML reader gets wrong, and
did: triggers became the string `"["` and instructions became `""`, silently deleting the
keep-the-wiki-current rule from every session.

Python 3.11+ is required so `tomllib` is always available. There must be no fallback parser.
"""

from __future__ import annotations

import sys
from pathlib import Path

from wikicli.core.config import WikiConfig

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestRuntimeRequirement:
    def test_python_is_at_least_3_11(self):
        """`tomllib` entered the stdlib in 3.11; the floor exists so no fallback parser is needed."""
        assert sys.version_info >= (3, 11)

    def test_tomllib_is_importable(self):
        import tomllib  # noqa: F401


class TestRealManifest:
    def test_metadata_loaded(self):
        cfg = WikiConfig(REPO_ROOT)
        assert cfg.name in ("Brian Knowledge Base", "My Org Knowledge Base")
        assert cfg.short_name
        assert "knowledge base" in cfg.description.lower()

    def test_paths_resolved_relative_to_repo_root(self):
        cfg = WikiConfig(REPO_ROOT)
        assert cfg.data_dir == REPO_ROOT / "wiki"
        assert cfg.data_dir.is_dir()
        assert cfg.company_file == REPO_ROOT / "wiki/entities/brian-overview.md"
        assert cfg.company_file.is_file()

    def test_multiline_array_parses_as_a_list(self):
        """The exact shape the fallback parser destroyed."""
        triggers = WikiConfig(REPO_ROOT).upkeep_triggers
        assert isinstance(triggers, list)
        assert len(triggers) >= 2
        assert all(isinstance(t, str) and len(t) > 20 for t in triggers)
        assert triggers != ["["], "triggers collapsed to a bracket — TOML parsing is broken"

    def test_triple_quoted_string_parses(self):
        instructions = WikiConfig(REPO_ROOT).upkeep_instructions
        assert isinstance(instructions, str)
        assert len(instructions) > 40
        assert "never commit" in instructions.lower()


class TestDefaultsAndOverrides:
    def test_missing_manifest_falls_back_to_defaults(self, tmp_path: Path):
        cfg = WikiConfig(tmp_path)
        assert cfg.data_dir == tmp_path / "wiki"
        assert cfg.upkeep_triggers == []

    def test_custom_paths_are_honoured(self, tmp_path: Path):
        (tmp_path / "wiki.toml").write_text(
            '[wiki]\nname = "Other KB"\n\n[paths]\ndata_dir = "kb"\nraw_dir = "sources"\n',
            encoding="utf-8",
        )
        cfg = WikiConfig(tmp_path)
        assert cfg.name == "Other KB"
        assert cfg.data_dir == tmp_path / "kb"
        assert cfg.raw_dir == tmp_path / "sources"

    def test_malformed_manifest_does_not_crash(self, tmp_path: Path):
        """A typo in wiki.toml must degrade to defaults, not break every agent session."""
        (tmp_path / "wiki.toml").write_text("[wiki\nname = broken", encoding="utf-8")
        cfg = WikiConfig(tmp_path)
        assert cfg.data_dir == tmp_path / "wiki"

    def test_use_case_and_rules_loaded(self, tmp_path: Path):
        (tmp_path / "wiki.toml").write_text(
            '[wiki]\nname = "IT KB"\nuse_case = "it_service_desk"\nagent_rules = ["people_tracking", "asset_tracking"]\n',
            encoding="utf-8",
        )
        cfg = WikiConfig(tmp_path)
        assert cfg.use_case == "it_service_desk"
        assert cfg.agent_rules == ["people_tracking", "asset_tracking"]
