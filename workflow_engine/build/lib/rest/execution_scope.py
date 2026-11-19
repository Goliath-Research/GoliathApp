"""Execution-scope helpers for workflow instance configuration and DB sync.

An "execution scope" is the workflow engine's process-agnostic identity for one
fully-resolved configuration combination. Higher layers (cfg) map the domain
concept of a "hyperparameter" trial onto a scope; wf itself stays agnostic.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from .db.base import GatewayDb


def extract_resolved_config_slices(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return all ``resolvedConfig__*`` entries from an instance context."""
    return {
        str(key): value
        for key, value in context.items()
        if str(key).startswith("resolvedConfig__")
    }


def extract_execution_scope_payload(
    context: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Build arguments for ``wf_apply_execution_scope`` from instance context.

    Reads the canonical ``executionScopeId`` and falls back to the legacy
    ``hyperparamSetId`` alias (one-release compatibility). Returns None when
    neither is present.
    """
    set_key = context.get("executionScopeId") or context.get("hyperparamSetId")
    if not set_key:
        return None
    display_name = (
        context.get("executionScopeName")
        or context.get("executionScopeLabel")
        or context.get("hyperparamSetName")
        or context.get("hyperparamSetLabel")
    )
    return {
        "set_key": str(set_key),
        "display_name": str(display_name) if display_name else None,
        "config_json": extract_resolved_config_slices(context),
    }


def _after_submit_hook():
    eps = entry_points().select(group="goliath.execution_scope_hooks")
    for ep in eps:
        return ep.load()
    return None


def sync_execution_scope_action_entry_after_submit(
    db: GatewayDb,
    node_execution_id: int,
    result_code: int,
) -> None:
    """Mirror CAAS action ledger rows into wf.execution_scope_action_entry."""
    hook = _after_submit_hook()
    if hook is None:
        return
    hook(db=db, node_execution_id=node_execution_id, result_code=result_code)
