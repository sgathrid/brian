"""Typed boundary for optional checkout-specific personalization."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from types import ModuleType
from typing import cast

InitRunner = Callable[..., bool]
SettingsRestoreRunner = Callable[..., bool]
AgentRuleCatalog = dict[str, dict[str, str]]


def _load_optional_module(module_name: str) -> ModuleType | None:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None


def _load_init_module() -> ModuleType | None:
    return _load_optional_module(f"{__package__}.init")


def load_init_capabilities() -> tuple[str, InitRunner | None]:
    """Load the optional init command without making it a static package dependency."""
    module = _load_init_module()
    if module is None:
        return "", None
    help_text = getattr(module, "RULE_HELP_TEXT", None)
    runner = getattr(module, "run_init", None)
    if not isinstance(help_text, str) or not callable(runner):
        raise TypeError("lifecycle.init must define string RULE_HELP_TEXT and callable run_init")
    return help_text, cast(InitRunner, runner)


def load_settings_restore() -> SettingsRestoreRunner | None:
    """Load Brian-only settings restore (absent in private no-init checkouts)."""
    module = _load_optional_module(f"{__package__}.settings_restore")
    if module is None:
        return None
    runner = getattr(module, "run_settings_restore", None)
    if runner is None:
        return None
    if not callable(runner):
        raise TypeError("lifecycle.settings_restore must define callable run_settings_restore")
    return cast(SettingsRestoreRunner, runner)


def load_agent_rule_catalog() -> AgentRuleCatalog:
    """Load optional prompt rules while surfacing malformed personalization modules."""
    module = _load_init_module()
    if module is None:
        return {}
    catalog = getattr(module, "ALL_AGENT_RULES", None)
    if not isinstance(catalog, dict) or any(
        not isinstance(key, str) or not isinstance(metadata, dict) or not isinstance(metadata.get("prompt_rule"), str)
        for key, metadata in catalog.items()
    ):
        raise TypeError("lifecycle.init ALL_AGENT_RULES must map strings to prompt-rule metadata")
    return cast(AgentRuleCatalog, catalog)
