"""Optional product action catalog.

The platform compiler and local runner enrich action templates when a worker
catalog is installed. GoliathOmics provides that catalog as
``methyl_worker.action_catalog``. A platform-only install compiles and stubs
without it.
"""

from __future__ import annotations

from typing import Any, Optional, Set

try:
    from methyl_worker.action_catalog import ACTION_CATALOG as _ACTION_CATALOG
    from methyl_worker.action_catalog import find_catalog_entry as _find_catalog_entry
except ImportError:  # product worker is not installed
    _ACTION_CATALOG = None
    _find_catalog_entry = None


def catalog_available() -> bool:
    return _find_catalog_entry is not None


def find_action(action_name: str) -> Any:
    """Return the catalog row, or None when the catalog is absent or has no match."""
    if _find_catalog_entry is None:
        return None
    return _find_catalog_entry(action_name)


def catalog_action_names() -> Optional[Set[str]]:
    """Action names from the installed catalog, or None when no catalog is installed."""
    if _ACTION_CATALOG is None:
        return None
    return {str(entry.action_name) for entry in _ACTION_CATALOG}
