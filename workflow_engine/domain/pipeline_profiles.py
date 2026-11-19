"""Platform pipeline profile hooks (neutral; no product presets, modalities or flags).

Pipeline profiles and procedures are application documents. The application that owns them
registers a ``goliath.application_profiles`` entry point (see ``application_extension``); every
function here delegates to that module when it provides the function. Without one, the
platform applies only generic rules: a profile or procedure contributes its ``actionConfig``
and its scalar keys the instance does not already set, and no scope flags are seeded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

#: Generic profile keys that are never copied into scope as plain values.
_STRUCTURAL_KEYS = frozenset({"pipelineProfile", "actionConfig", "step_config_overrides", "catalog"})

_active_hooks: set[str] = set()


def _application_profiles():
    from .application_extension import get_application_profiles_module

    return get_application_profiles_module()


def _hook(name: str) -> Optional[Callable[..., Any]]:
    """The application's implementation of ``name``, unless it is this module's own function."""
    fn = getattr(_application_profiles(), name, None)
    if not callable(fn) or name in _active_hooks:
        return None
    if getattr(fn, "__module__", None) == __name__:
        return None
    return fn


def _delegate(name: str, *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    fn = _hook(name)
    if fn is None:
        return False, None
    _active_hooks.add(name)
    try:
        return True, fn(*args, **kwargs)
    finally:
        _active_hooks.discard(name)


def pipeline_flag_defaults() -> Dict[str, bool]:
    """Scope flag defaults declared by the application (empty on a platform-only install)."""
    defaults = getattr(_application_profiles(), "PIPELINE_FLAG_DEFAULTS", None)
    return dict(defaults) if isinstance(defaults, Mapping) else {}


# Kept for importers; the application module owns the actual defaults.
PIPELINE_FLAG_DEFAULTS: Dict[str, bool] = {}


def cfg_status_for_catalog(catalog: Mapping[str, Any] | None) -> Optional[str]:
    """Map catalog metadata to cfg status; see ``cfg.process_pack_catalog``."""
    from cfg.process_pack_catalog import cfg_status_for_catalog as _impl

    return _impl(catalog)


def catalog_meta_for(name_or_doc: str | Mapping[str, Any]) -> Dict[str, Any]:
    """Return catalog metadata for a profile name or document (empty if absent)."""
    if isinstance(name_or_doc, Mapping):
        cat = name_or_doc.get("catalog")
        return dict(cat) if isinstance(cat, Mapping) else {}
    key = str(name_or_doc).strip()
    if not key:
        return {}
    try:
        data = load_profile(key)
    except FileNotFoundError:
        return {}
    cat = data.get("catalog")
    return dict(cat) if isinstance(cat, Mapping) else {}


def load_profile(name_or_path: str | Path) -> Dict[str, Any]:
    return _application_profiles().load_profile(name_or_path)


def load_procedure(name_or_path: str | Path) -> Dict[str, Any]:
    return _application_profiles().load_procedure(name_or_path)


def profile_action_config(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return _application_profiles().profile_action_config(profile)


def load_profile_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: Dict[str, Any], overlay: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge overlay onto base; overlay ``None`` deletes the key (JSON null = clear)."""
    out = dict(base)
    for key, val in overlay.items():
        if val is None:
            out.pop(key, None)
            continue
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(dict(out[key]), val)
        else:
            out[key] = val
    return out


def _merge_document(context: Dict[str, Any], document: Mapping[str, Any]) -> Dict[str, Any]:
    """Generic merge: scalar keys the instance does not set, and actionConfig under the instance."""
    out = dict(context)
    for key, val in document.items():
        if key in _STRUCTURAL_KEYS or val is None or key in out:
            continue
        if isinstance(val, (str, int, float, bool)):
            out[key] = val
    ac = document.get("actionConfig") or document.get("step_config_overrides") or {}
    if isinstance(ac, dict) and ac:
        out["actionConfig"] = _deep_merge(dict(ac), dict(out.get("actionConfig") or {}))
    return out


def context_modality(context: Mapping[str, Any]) -> Optional[str]:
    """The application's modality for this context (None on a platform-only install)."""
    handled, result = _delegate("context_modality", context)
    return result if handled else None


def seed_pipeline_scope_flags(
    context: Dict[str, Any],
    *,
    action_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Application scope flags; without an application hook no flags are seeded."""
    handled, result = _delegate("seed_pipeline_scope_flags", context, action_config=action_config)
    return dict(result) if handled else dict(context)


def apply_pipeline_procedure(context: Dict[str, Any], procedure: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge a procedure pack under instance context (instance wins on conflicts)."""
    handled, result = _delegate("apply_pipeline_procedure", context, procedure)
    if handled:
        return dict(result)
    out = _merge_document(context, procedure)
    if procedure.get("pipelineProcedure"):
        out["pipelineProcedure"] = str(procedure["pipelineProcedure"])
    return out


def validate_procedure_analyte(context: Mapping[str, Any]) -> None:
    """Application check that the study matches the procedure (no-op without a hook)."""
    _delegate("validate_procedure_analyte", context)


def apply_pipeline_profile(
    context: Dict[str, Any],
    profile: Mapping[str, Any],
    *,
    action_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge a profile dict into workflow instance context (actionConfig, then app flags)."""
    handled, result = _delegate("apply_pipeline_profile", context, profile, action_config=action_config)
    if handled:
        return dict(result)
    out = _merge_document(context, profile)
    if profile.get("pipelineProfile"):
        out["pipelineProfile"] = profile["pipelineProfile"]
    effective: Dict[str, Any] = dict(action_config or {})
    ctx_ac = out.get("actionConfig")
    if isinstance(ctx_ac, dict):
        effective = _deep_merge(effective, ctx_ac)
    return seed_pipeline_scope_flags(out, action_config=effective)


def apply_profile_by_name(context: Dict[str, Any], profile_name: str) -> Dict[str, Any]:
    return apply_pipeline_profile(context, load_profile(profile_name))
