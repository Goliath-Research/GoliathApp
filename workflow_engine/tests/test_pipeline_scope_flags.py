"""Platform pipeline profiles are neutral and delegate to the application hook."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from domain import pipeline_profiles as profiles


def _no_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from domain.application_extension import _MissingApplicationProfiles

    monkeypatch.setattr(profiles, "_application_profiles", lambda: _MissingApplicationProfiles())


def test_profile_without_application_seeds_no_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_app(monkeypatch)
    ctx = {"regulatory": {"primary_modality": "anything"}, "keep": 1}
    assert profiles.seed_pipeline_scope_flags(ctx, action_config={"x": {"y": 1}}) == ctx
    assert profiles.context_modality(ctx) is None
    assert profiles.pipeline_flag_defaults() == {}
    profiles.validate_procedure_analyte({"analyteExpectation": "x"})


def test_generic_profile_and_procedure_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_app(monkeypatch)
    out = profiles.apply_pipeline_profile(
        {"mode": "instance", "actionConfig": {"a": {"n": 2}}},
        {"pipelineProfile": "p1", "mode": "profile", "extra": True, "actionConfig": {"a": {"n": 1, "m": 3}}},
    )
    assert out == {"mode": "instance", "extra": True, "pipelineProfile": "p1", "actionConfig": {"a": {"n": 2, "m": 3}}}
    out = profiles.apply_pipeline_procedure({}, {"pipelineProcedure": "proc", "level": 2, "nested": {"x": 1}})
    assert out == {"pipelineProcedure": "proc", "level": 2}


def test_application_hook_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def seed(context: dict[str, Any], *, action_config: Any = None) -> dict[str, Any]:
        calls.append("seed")
        return {**context, "appFlag": True}

    app = SimpleNamespace(
        seed_pipeline_scope_flags=seed,
        context_modality=lambda ctx: "app-modality",
        PIPELINE_FLAG_DEFAULTS={"appFlag": False},
        profile_action_config=lambda p: dict(p.get("actionConfig") or {}),
    )
    monkeypatch.setattr(profiles, "_application_profiles", lambda: app)
    assert profiles.seed_pipeline_scope_flags({})["appFlag"] is True
    assert profiles.context_modality({}) == "app-modality"
    assert profiles.pipeline_flag_defaults() == {"appFlag": False}
    assert profiles.apply_pipeline_profile({}, {"pipelineProfile": "p"})["appFlag"] is True
    assert calls == ["seed", "seed"]


def test_hook_pointing_back_at_platform_does_not_recurse(monkeypatch: pytest.MonkeyPatch) -> None:
    app = SimpleNamespace(seed_pipeline_scope_flags=profiles.seed_pipeline_scope_flags)
    monkeypatch.setattr(profiles, "_application_profiles", lambda: app)
    assert profiles.seed_pipeline_scope_flags({"a": 1}) == {"a": 1}


def test_platform_module_names_no_application_keys() -> None:
    text = open(profiles.__file__, encoding="utf-8").read().lower()
    for token in ("modality_aliases", "kallisto", "pangenome", "featurecuts", "samd", "dmp", "meth"):
        assert token not in text


def test_pipeline_profiles_importable_from_installed_package() -> None:
    """workflow_context loads pipeline_profiles as part of the domain package."""
    program = """
import domain.pipeline_profiles as profiles
import domain.workflow_context as context
assert context.seed_pipeline_scope_flags is profiles.seed_pipeline_scope_flags
"""
    subprocess.check_call([sys.executable, "-c", program])
