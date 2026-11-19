"""Export versioned JSON Schema documents for registered actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel

from goliath_app.actions.registry import load_action_catalog
from goliath_app.actions.spec import ActionSpec


@dataclass(frozen=True)
class ExportedSchema:
    action_name: str
    direction: str
    schema_version: str
    schema_id: str
    schema_json: dict[str, Any]
    content_hash: str


def _canonical_schema_bytes(schema: dict[str, Any]) -> bytes:
    return json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash_for_schema(schema: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_schema_bytes(schema)).hexdigest()


def _schema_id(spec: ActionSpec, direction: str) -> str:
    return f"goliath.actions/{spec.namespace}/{spec.action_name}/{direction}/{spec.schema_version}"


def export_action_schemas(spec: ActionSpec) -> List[ExportedSchema]:
    out: List[ExportedSchema] = []
    for direction, model in (("input", spec.input_model), ("output", spec.output_model)):
        schema_json = model.model_json_schema(mode="serialization")
        out.append(
            ExportedSchema(
                action_name=spec.action_name,
                direction=direction,
                schema_version=spec.schema_version,
                schema_id=_schema_id(spec, direction),
                schema_json=schema_json,
                content_hash=content_hash_for_schema(schema_json),
            )
        )
    return out


def export_all_schemas(catalog: Optional[Sequence[ActionSpec]] = None) -> List[ExportedSchema]:
    specs = list(catalog) if catalog is not None else load_action_catalog()
    rows: List[ExportedSchema] = []
    for spec in specs:
        rows.extend(export_action_schemas(spec))
    return rows


def export_catalog_document(catalog: Optional[Sequence[ActionSpec]] = None) -> Dict[str, Any]:
    specs = list(catalog) if catalog is not None else load_action_catalog()
    actions: Dict[str, Any] = {}
    for spec in specs:
        actions[spec.action_name] = {
            "namespace": spec.namespace,
            "level": spec.level.value,
            "entity_code": spec.entity_code,
            "display_name": spec.display_name,
            "description": spec.description,
            "exposure": spec.resolved_exposure.value,
            "required_permission": spec.required_permission,
            "schema_version": spec.schema_version,
            "base_namespace": spec.overrides,
            "capability": spec.resolved_capability,
            "schemas": {
                row.direction: {
                    "schema_id": row.schema_id,
                    "schema_version": row.schema_version,
                    "content_hash": row.content_hash,
                    "schema_json": row.schema_json,
                }
                for row in export_action_schemas(spec)
            },
        }
    return {"actions": actions}


def _check_mode(committed_path: str) -> int:
    path = committed_path
    with open(path, encoding="utf-8") as fh:
        committed = json.load(fh)
    live = export_catalog_document()
    if committed != live:
        print("schema export drift: regenerate committed catalog JSON", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export Goliath action JSON Schemas")
    parser.add_argument("--check", metavar="PATH", help="Compare export to committed JSON")
    parser.add_argument("-o", "--output", metavar="PATH", help="Write catalog JSON document")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.check:
        return _check_mode(args.check)

    document = export_catalog_document()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
