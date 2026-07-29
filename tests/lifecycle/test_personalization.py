from __future__ import annotations

from types import SimpleNamespace

import pytest

from wikicli.lifecycle import personalization


def test_absent_init_module_disables_optional_capabilities(monkeypatch: pytest.MonkeyPatch):
    def missing(module_name: str):
        raise ModuleNotFoundError(name=module_name)

    monkeypatch.setattr(personalization, "import_module", missing)

    assert personalization.load_init_capabilities() == ("", None)
    assert personalization.load_agent_rule_catalog() == {}


def test_dependency_import_failure_is_not_hidden(monkeypatch: pytest.MonkeyPatch):
    def broken(_module_name: str):
        raise ModuleNotFoundError(name="missing_dependency")

    monkeypatch.setattr(personalization, "import_module", broken)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        personalization.load_init_capabilities()
    assert exc_info.value.name == "missing_dependency"


def test_valid_init_module_exposes_typed_capabilities(monkeypatch: pytest.MonkeyPatch):
    def run_init(*_args, **_kwargs) -> bool:
        return True

    module = SimpleNamespace(
        RULE_HELP_TEXT="Available rules",
        run_init=run_init,
        ALL_AGENT_RULES={"adrs": {"prompt_rule": "Record architectural decisions."}},
    )
    monkeypatch.setattr(personalization, "import_module", lambda _name: module)

    help_text, runner = personalization.load_init_capabilities()
    assert help_text == "Available rules"
    assert runner is run_init
    assert personalization.load_agent_rule_catalog() == module.ALL_AGENT_RULES
