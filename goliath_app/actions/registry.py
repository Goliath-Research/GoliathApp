"""Discover and merge action catalogs from entry-point plugins."""

from __future__ import annotations

import hashlib
import importlib
import json
from importlib.metadata import entry_points
from typing import Dict, Iterable, List, Optional, Sequence, Set

from goliath_app.actions.compatibility import assert_override_compatible
from goliath_app.actions.spec import ActionSpec

_ENTRY_GROUP = "goliath.action_catalogs"


def _load_catalog_from_entrypoint(ep) -> Sequence[ActionSpec]:
    loaded = ep.load()
    if isinstance(loaded, ActionSpec):
        return (loaded,)
    if isinstance(loaded, Sequence) and loaded and isinstance(loaded[0], ActionSpec):
        return tuple(loaded)
    if callable(loaded):
        value = loaded()
        if isinstance(value, ActionSpec):
            return (value,)
        return tuple(value)
    if isinstance(loaded, str):
        module = importlib.import_module(loaded)
        catalog = getattr(module, "ACTION_CATALOG", None)
        if catalog is None:
            raise TypeError(f"entry point {ep.name} module {loaded} has no ACTION_CATALOG")
        return tuple(catalog)
    raise TypeError(f"unsupported entry point payload for {ep.name!r}: {type(loaded)}")


def _merge_catalogs(specs: Iterable[ActionSpec]) -> List[ActionSpec]:
    by_name: Dict[str, ActionSpec] = {}
    overrides_pending: List[ActionSpec] = []

    for spec in specs:
        if spec.overrides is not None:
            overrides_pending.append(spec)
            continue
        existing = by_name.get(spec.action_name)
        if existing is not None:
            raise ValueError(
                f"duplicate action_name {spec.action_name!r} from namespaces "
                f"{existing.namespace!r} and {spec.namespace!r}"
            )
        by_name[spec.action_name] = spec

    for override in overrides_pending:
        base = by_name.get(override.action_name)
        if base is None:
            raise ValueError(
                f"override {override.action_name!r} has no base action in namespace "
                f"{override.overrides!r}"
            )
        assert_override_compatible(base, override)
        by_name[override.action_name] = override

    return sorted(by_name.values(), key=lambda s: s.action_name)


def load_action_catalog() -> List[ActionSpec]:
    """Load all ``goliath.action_catalogs`` entry points and merge overrides."""
    specs: List[ActionSpec] = []
    eps = entry_points().select(group=_ENTRY_GROUP)
    for ep in sorted(eps, key=lambda e: e.name):
        specs.extend(_load_catalog_from_entrypoint(ep))
    return _merge_catalogs(specs)


def _catalog_singleton() -> List[ActionSpec]:
    global _CACHED_CATALOG
    if _CACHED_CATALOG is None:
        _CACHED_CATALOG = load_action_catalog()
    return _CACHED_CATALOG


_CACHED_CATALOG: Optional[List[ActionSpec]] = None


def reload_action_catalog() -> List[ActionSpec]:
    """Clear cache and reload entry points (tests)."""
    global _CACHED_CATALOG
    _CACHED_CATALOG = None
    return _catalog_singleton()


# Module-level list API (compiler imports ACTION_CATALOG from methyl_worker historically).
def __getattr__(name: str):
    if name == "ACTION_CATALOG":
        return _catalog_singleton()
    raise AttributeError(name)


def find_action(action_name: str) -> Optional[ActionSpec]:
    for entry in _catalog_singleton():
        if entry.action_name == action_name:
            return entry
    return None


def catalog_action_names() -> Set[str]:
    return {entry.action_name for entry in _catalog_singleton()}


def action_revision_for(spec: ActionSpec) -> str:
    """Stable revision token for CAAS / foreach bundle fingerprints."""
    payload = {
        "action_name": spec.action_name,
        "schema_version": spec.schema_version,
        "input": spec.input_model.model_json_schema(mode="serialization"),
        "output": spec.output_model.model_json_schema(mode="serialization"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{spec.schema_version}:{digest}"
