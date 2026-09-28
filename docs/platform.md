# Platform overview

GoliathApp is the database-governed application platform. GoliathOmics, and any later product, stores its behavior as data in this engine. The engine does not encode methylation, disease, or aligner semantics.

The live map of repositories is [workspace-index.md](workspace-index.md). Engine deploy steps are in [workflow_engine/sql_pg/README.md](../workflow_engine/sql_pg/README.md) and [workflow_engine/sql_mssql/README.md](../workflow_engine/sql_mssql/README.md). The HTTP contract is [contracts/openapi.yaml](../contracts/openapi.yaml).

## Engine versus content

| Layer | Owner | What it is |
|-------|--------|------------|
| Engine DDL | GoliathApp | Schemas and procedures that run any workflow |
| Content seeds | GoliathOmics | Action catalogs, analytes, reference assets, study graphs, clinical columns |
| Tool binaries | GoliathAlign, MethylExtractor | Image and binary pins consumed by Omics workers |

One database, named `goliath`. App migrations own engine DDL. Omics contributes content migrations and does not fork the engine.

## Schemas

| Schema | Role |
|--------|------|
| `Meta` | OOP model of application information. There is no separate `obj` schema. Instances are `Meta.Objs` and related Meta tables. |
| `RBAC` | Roles over Meta classes and concrete objects |
| `portal` | UI objects. The portal is generated from rows in this schema (`portal.sp_*`), not from a hardcoded screen tree. |
| `wf` | Workflow definitions, instances, and actions for portal users or remote workers |
| `cfg` | Sites, profiles, programs, storage endpoints, and reference-asset registry tables |
| `Contract`, `Onboarding` | Platform contracts and onboarding |

Portal clinical and disease columns are Omics content. The portal *engine* stays here.

## How a custom entity attaches to a workflow

A product does not subclass the engine in Python to add a domain. It registers data:

1. **Action definition.** A row in `wf.workflow_action` names an action, its capability, and a JSON Schema for inputs and outputs. Schemas are stored with the action (`wf_action_schema`). Operators edit those schemas; workers receive the resolved payload.
2. **Data type.** `wf` data-type rows describe values the engine can carry. The table is platform. The rows that mean "sample" or "analyte" are product content.
3. **DomainProgram.** A portable workflow graph. The compiler and IR checker in this repo (`workflow_engine/domain/compiler.py`, `verify_workflow.py`) check the graph. The programs, profiles, and analytes are GoliathOmics files.
4. **Worker handler.** GoliathApp owns claim and submit (`goliath_worker/`). The product owns the function that performs the action.

The gateway (`goliath-gateway` in `workflow_engine/rest/`) bakes `resolvedConfig` onto each task. Workers read that payload. They do not re-read a study manifest for tool parameters.

## Shared storage

`scripts/init_work_layout.sh` defines an optional `/work` layout. A workflow that never calls the storage helpers runs with no mount. The environment name is `GOLIATH_WORK_ROOT`.
