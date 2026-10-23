"""FOREACH iteration-bundle CAAS helpers for local and DB engines.

Local scheduler probes/commits ``.caas/foreach_bundle/{content_key}/``.
DB engines mirror hits into ``wf.foreach_bundle_entry`` (see sql_pg/08_foreach_support.sql)
so ``wf_try_bind_foreach_body`` can skip BODY fan-out without claiming leaf ACTIONs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


def _foreach_bundle_plugin() -> Any:
    eps = entry_points().select(group="goliath.foreach_bundle")
    for ep in eps:
        return ep.load()
    return None

# Same scope key the product bundle uses so nested FOREACH identity survives
# a platform-only local run.
FOREACH_ANCESTRY_SCOPE_KEY = "__foreach_ancestry__"


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint_foreach_ancestry(ancestry: Sequence[Any] | None) -> Optional[str]:
    """Hash parent FOREACH chain for nested iteration-bundle keys."""
    if not ancestry:
        return None
    return hashlib.sha256(_canonical_json(list(ancestry)).encode("utf-8")).hexdigest()


def foreach_ancestry_from_scope(scope_values: Mapping[str, Any] | None) -> List[Any]:
    """Return a copy of the parent FOREACH ancestry stack from scope."""
    if not scope_values:
        return []
    raw = scope_values.get(FOREACH_ANCESTRY_SCOPE_KEY)
    if not isinstance(raw, list):
        return []
    return list(raw)


def extend_foreach_ancestry(
    parent_ancestry: Sequence[Any],
    *,
    foreach_node_key: str,
    collection_var: str,
    iteration_index: int,
    item_payload: Any,
) -> List[Any]:
    """Append the current FOREACH frame for nested children to close over."""
    return list(parent_ancestry) + [
        {
            "foreach_node_key": foreach_node_key,
            "collection_var": collection_var,
            "iteration_index": iteration_index,
            "item": item_payload,
        }
    ]


def resolve_study_root(scope_values: Mapping[str, Any]) -> Optional[Path]:
    """Study root for iteration bundles, when a descendant app registers FOREACH CAAS."""
    plugin = _foreach_bundle_plugin()
    if plugin is None:
        return None
    resolver = getattr(plugin, "resolve_study_root_from_scope", None)
    if resolver is None:
        return None
    return resolver(scope_values)


def foreach_caas_enabled(scope_values: Mapping[str, Any] | None = None) -> bool:
    if scope_values and scope_values.get("foreachCaasEnabled") is False:
        return False
    if scope_values and scope_values.get("forceRerun") is True:
        return False
    env = os.environ.get("METHYL_FOREACH_CAAS_ENABLED", "").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    return True


def collect_body_action_names(graph: Any, body_key: Optional[str]) -> List[str]:
    """DFS collect ACTION names under a FOREACH BODY (stable order)."""
    if not body_key:
        return []
    names: List[str] = []
    seen: set[str] = set()

    def walk(key: str) -> None:
        if key in seen:
            return
        seen.add(key)
        node = graph.nodes.get(key)
        if node is None:
            return
        if node.node_type == "ACTION" and node.action_name:
            names.append(str(node.action_name))
        for branch in ("SEQUENCE", "BODY", "THEN", "ELSE", "PARALLEL", "CASE", "DEFAULT"):
            for child in graph.child_keys(key, branch):
                walk(child)

    walk(body_key)
    return names


def child_action_revisions(action_names: Sequence[str]) -> List[str]:
    from goliath_app.actions.registry import action_revision_for, find_action

    revisions: List[str] = []
    for name in action_names:
        entry = find_action(name)
        if entry is None:
            revisions.append(f"{name}:unknown")
            continue
        revisions.append(f"{name}:{action_revision_for(entry)}")
    return revisions


def canonical_item_payload(element: Any) -> Any:
    """JSON-stable form of a FOREACH item for content keys."""
    if isinstance(element, (str, int, float, bool)) or element is None:
        return element
    if isinstance(element, Mapping):
        # Prefer path-like keys remapped later by study signatures; keep structure.
        return {str(k): canonical_item_payload(v) for k, v in sorted(element.items())}
    if isinstance(element, (list, tuple)):
        return [canonical_item_payload(v) for v in element]
    return str(element)


def probe_iteration_bundle(
    project_root: Optional[Path],
    *,
    foreach_node_key: str,
    collection_var: str,
    iteration_index: int,
    item_payload: Any,
    child_revisions: Sequence[str],
    enabled: bool = True,
    extra_input_fingerprint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not enabled or project_root is None:
        return None
    plugin = _foreach_bundle_plugin()
    if plugin is None:
        return None
    short_circuit = getattr(plugin, "try_short_circuit_foreach_iteration", None)
    if short_circuit is None:
        return None

    return short_circuit(
        project_root,
        foreach_node_key=foreach_node_key,
        collection_var=collection_var,
        iteration_index=iteration_index,
        item_payload=item_payload,
        child_action_revisions=list(child_revisions),
        extra_input_fingerprint=extra_input_fingerprint,
        enabled=True,
    )


def commit_iteration_bundle_local(
    project_root: Optional[Path],
    *,
    foreach_node_key: str,
    collection_var: str,
    iteration_index: int,
    item_payload: Any,
    child_revisions: Sequence[str],
    enabled: bool = True,
    extra_input_fingerprint: Optional[str] = None,
) -> Optional[Path]:
    if not enabled or project_root is None:
        return None
    plugin = _foreach_bundle_plugin()
    if plugin is None:
        return None
    compute_iteration_bundle_key = getattr(plugin, "compute_iteration_bundle_key", None)
    commit_iteration_bundle = getattr(plugin, "commit_iteration_bundle", None)
    if compute_iteration_bundle_key is None or commit_iteration_bundle is None:
        return None

    key = compute_iteration_bundle_key(
        foreach_node_key=foreach_node_key,
        collection_var=collection_var,
        iteration_index=iteration_index,
        item_payload=item_payload,
        child_action_revisions=list(child_revisions),
        extra_input_fingerprint=extra_input_fingerprint,
    )
    path = commit_iteration_bundle(
        project_root,
        key,
        foreach_node_key=foreach_node_key,
        collection_var=collection_var,
        iteration_index=iteration_index,
        item_payload=item_payload,
        child_content_keys={},
        status="completed",
    )
    logger.debug(
        "FOREACH CAAS commit node=%s iter=%s key=%s",
        foreach_node_key,
        iteration_index,
        key[:12],
    )
    return path


def db_bundle_row_payload(
    *,
    content_key: str,
    foreach_node_key: str,
    collection_var: str,
    iteration_index: int,
    status: str = "completed",
) -> Dict[str, Any]:
    """Payload shape for ``wf.foreach_bundle_entry`` upserts (gateway/DB path)."""
    return {
        "content_key": content_key,
        "foreach_node_key": foreach_node_key,
        "collection_var": collection_var,
        "iteration_index": int(iteration_index),
        "status": status,
        "manifest_json": json.dumps(
            {
                "schema_version": "foreach_bundle_v1",
                "content_key": content_key,
                "foreach_node_key": foreach_node_key,
                "collection_var": collection_var,
                "iteration_index": int(iteration_index),
                "status": status,
            },
            sort_keys=True,
        ),
    }
