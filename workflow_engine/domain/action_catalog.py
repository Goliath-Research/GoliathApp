"""Platform action catalog discovery (entry-point plugins; no app imports)."""

from __future__ import annotations

from typing import Optional, Set

from goliath_app.actions.registry import find_action as _find_action, load_action_catalog
from goliath_app.actions.spec import ActionLevel

__all__ = [
    "catalog_available",
    "catalog_action_names",
    "find_action",
    "load_action_catalog",
]


def catalog_available() -> bool:
    """True when a descendant app registered domain-level actions (strict compile)."""
    return any(spec.level == ActionLevel.DOMAIN for spec in load_action_catalog())


def find_action(action_name: str):
    """Return the catalog row, or None when there is no match."""
    return _find_action(action_name)


def catalog_action_names() -> Optional[Set[str]]:
    if not catalog_available():
        return None
    return {spec.action_name for spec in load_action_catalog()}
