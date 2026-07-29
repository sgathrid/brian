"""Manifest loader for wiki.toml configuration files."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


class WikiConfig:
    """Configuration loader for wiki.toml manifests."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.config_path = self.repo_root / "wiki.toml"

        self.name: str = "Knowledge Base"
        self.short_name: str = "Wiki"
        self.description: str = "Company knowledge base"
        self.version: str = "0.1.0"

        self.data_dir: Path = self.repo_root / "wiki"
        self.raw_dir: Path = self.repo_root / "raw"
        # Default company page stem; private checkouts override via wiki.toml.
        self.company_file: Path = self.repo_root / "wiki" / "entities" / "brian-overview.md"
        self.registry_file: Path = self.repo_root / "internal" / "registry.md"

        self.upkeep_triggers: list[str] = []
        self.upkeep_instructions: str = ""
        self.upkeep_proactivity: str = ""

        # Optional personalization (wiki.toml). Defaults empty — never force
        # people_tracking or other PII-oriented behaviors.
        self.use_case: str = "company"
        self.agent_rules: list[str] = []

        self._load()

    def _load(self) -> None:
        if not self.config_path.is_file():
            return

        # A typo in wiki.toml must degrade to defaults, never raise. This loader runs inside the
        # SessionStart hook, so an uncaught TOMLDecodeError would break session startup for every
        # agent on the machine — a far worse failure than losing manifest overrides.
        try:
            with open(self.config_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"wiki: ignoring malformed {self.config_path}: {exc}", file=sys.stderr)
            return

        wiki_sec = data.get("wiki", {})
        self.name = wiki_sec.get("name", self.name)
        self.short_name = wiki_sec.get("short_name", self.short_name)
        self.description = wiki_sec.get("description", self.description)
        self.version = wiki_sec.get("version", self.version)
        self.use_case = wiki_sec.get("use_case", self.use_case)
        raw_rules = wiki_sec.get("agent_rules", self.agent_rules)
        if isinstance(raw_rules, str):
            self.agent_rules = [r.strip() for r in raw_rules.split(",") if r.strip()]
        elif isinstance(raw_rules, list):
            self.agent_rules = [str(r).strip() for r in raw_rules if str(r).strip()]
        else:
            self.agent_rules = []

        paths_sec = data.get("paths", {})
        if "data_dir" in paths_sec:
            self.data_dir = self.repo_root / paths_sec["data_dir"]
        if "raw_dir" in paths_sec:
            self.raw_dir = self.repo_root / paths_sec["raw_dir"]
        if "company_file" in paths_sec:
            self.company_file = self.repo_root / paths_sec["company_file"]
        if "registry_file" in paths_sec:
            self.registry_file = self.repo_root / paths_sec["registry_file"]

        upkeep_sec = data.get("upkeep", {})
        self.upkeep_triggers = upkeep_sec.get("triggers", [])
        self.upkeep_instructions = upkeep_sec.get("instructions", "")
        raw_proactivity = str(upkeep_sec.get("proactivity", "")).strip().lower()
        self.upkeep_proactivity = (
            raw_proactivity
            if raw_proactivity in {"selective", "active", "capture", "silent"}
            else ""
        )
