"""Generic DomainProgram compile service (stdin JSON -> stdout JSON).

Run by the platform host on the server: ``python3 -m domain.compile_service``.

Input:  ``{"program": {...DomainProgram...}, "actions": [{action_name, tool, action_config_key,
          context_vars, domain_effects}, ...]}`` -- the actions are the database's action compile
          profiles (``wf.action_compile_profile``), seeded by the apps that own the actions.
Output: ``{"ok": true, "spec": {...workflow graph spec...}}`` or ``{"ok": false, "error": "..."}``.

The service knows no application: everything application-specific arrives in the input.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

MAX_INPUT_BYTES = 2_000_000


@dataclass(frozen=True)
class ProfileEntry:
    action_name: str
    tool: str
    action_config_key: Optional[str]
    context_vars: Tuple[str, ...]
    domain_effects: Any


def _effects(raw: Any) -> Any:
    if not isinstance(raw, dict) or not raw:
        return None
    from goliath_app.actions.domain_effects import (
        DomainEffects,
        OutputBindingRule,
        TemplateDefaultRule,
        TemplateGroupSideRule,
    )

    return DomainEffects(
        scope_bindings=tuple((str(a), str(b)) for a, b in raw.get("scope_bindings") or ()),
        output_bindings=tuple(
            OutputBindingRule(scope_field=str(r["scope_field"]), output_json_path=str(r["output_json_path"]))
            for r in raw.get("output_bindings") or ()
        ),
        template_defaults=tuple(
            TemplateDefaultRule(
                field=str(r["field"]),
                scope_var=str(r["scope_var"]),
                only_if_absent=bool(r.get("only_if_absent", True)),
                absent_also=tuple(str(x) for x in r.get("absent_also") or ()),
            )
            for r in raw.get("template_defaults") or ()
        ),
        template_group_side_defaults=tuple(
            TemplateGroupSideRule(side=str(r["side"]), field=str(r["field"]), scope_var=str(r["scope_var"]))
            for r in raw.get("template_group_side_defaults") or ()
        ),
    )


def build_catalog(rows: Any) -> Dict[str, ProfileEntry]:
    catalog: Dict[str, ProfileEntry] = {}
    for row in rows or ():
        name = str(row["action_name"])
        catalog[name] = ProfileEntry(
            action_name=name,
            tool=str(row.get("tool") or name),
            action_config_key=row.get("action_config_key") or None,
            context_vars=tuple(str(v) for v in row.get("context_vars") or ()),
            domain_effects=_effects(row.get("domain_effects")),
        )
    return catalog


def compile_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    from contract.workflow_definition_spec import WorkflowDefinitionSpec
    from domain.compiler import compile_domain_program
    from domain.program import DomainProgram

    program = DomainProgram.model_validate(payload.get("program") or {})
    result = compile_domain_program(program, catalog=build_catalog(payload.get("actions")))
    spec = WorkflowDefinitionSpec.model_validate(result.workflow.model_dump(mode="json")).to_db_spec()
    return {"ok": True, "spec": spec}


def main() -> int:
    raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        print(json.dumps({"ok": False, "error": "input too large"}))
        return 0
    try:
        out = compile_payload(json.loads(raw))
    except Exception as exc:  # noqa: BLE001 - reported to the caller as a compile error
        message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        out = {"ok": False, "error": message[:500]}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
