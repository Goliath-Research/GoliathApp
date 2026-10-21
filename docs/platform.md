# Platform

GoliathApp is a database-governed application platform. A specialized application stores its workflow as data: action rows, data types, and a graph. The engine activates nodes, leases ACTION nodes to workers, and continues the graph from result codes. Domain meaning stays in the application that extends the platform.

The repository map is [workspace-index.md](workspace-index.md). Apply order is [schema-apply.md](schema-apply.md). The HTTP contract is [`contracts/openapi.yaml`](https://github.com/Goliath-Research/GoliathApp/blob/main/contracts/openapi.yaml).

## Schemas

| Schema | What the SQL in this tree defines |
|--------|-----------------------------------|
| `Meta` | Class model. Instances are `"Meta"."Objs"`. |
| `RBAC` | Users, groups, roles, permissions, scopes, sessions, external identities. Quoted PascalCase identifiers. |
| `portal` | Portal functions (`portal.sp_*`) for workflow definitions, worker enrollment, RBAC administration, studies, and related operator calls. |
| `wf` | Workflow definitions, instances, actions, data types, worker registry, leases, and the event plane. |
| `cfg` | Sites, pipeline profiles, assay procedures, domain programs, studies, credentials, storage, and reference-asset registry tables. |
| `Contract`, `Onboarding` | Contract and onboarding tables and parity APIs. |

`cfg.analyte` is referenced by repository and portal SQL. `cfg_registry_tables.sql` does not create that table. `portal."Customers"`, `portal."Diseases"`, `portal."NavTree"`, and `portal."Role2Node"` are referenced by later functions and are not created by a script in this tree.

There is no separate `obj` schema. Object identity is `"Meta"."Objs"`.

## Processes in this repository

| Piece | Where | What it does |
|-------|--------|----------------|
| REST gateway | `workflow_engine/rest/` | `goliath-gateway` / `methyl-gateway`. Worker enroll, claim, submit, heartbeat, fail, and `POST /v1/events`. |
| Local runner | `workflow_engine/local/` | `goliath-workflow-run`. Compiles a DomainProgram and can execute the graph in-process. |
| Compiler | `workflow_engine/domain/` | Lowers DomainProgram JSON to `WorkflowDefinitionSpec`. |
| Config CLI | `workflow_engine/cfg/` | `goliath-cfg`. File-backed registry under `$METHYL_CFG_STORE` or `$METHYL_WORK_ROOT/goliath/cfg-store` (default `/work/goliath/cfg-store`). |
| Claim client | `goliath_worker/` | HTTP client for the worker routes. No database connection. |
| Shared storage helpers | `goliath_worker/work_share.py`, `scripts/init_work_layout.sh` | Optional `/work` layout and cross-host permissions. |
| Contract check | `workflow_engine/contract/validate_contract.py` | Requires the objects in `db_objects.yaml` to appear in both SQL trees. |
| Delphi gateway | `workflow_engine/delphi/` | Frozen Windows reference. The Python gateway is the middle tier that ships here. |

`publish-program --deploy-db` imports `ops.workflow_deploy`, which is not in this tree. `sync-actions` runs `workflow_engine/sql_mssql/seed_action_catalog.py`, which is not in this tree. `sync-library-presets` imports `methyl_enricher.preset_registry`, which is not in this tree.

## Gateway and database defaults

`BACKEND_DB` selects the gateway backend and defaults to `mssql`. PostgreSQL is `postgres`, `postgresql`, or `pg`.

PostgreSQL connection fields are `POSTGRES_HOST` (default `localhost`), `POSTGRES_PORT` (default `5432`), `POSTGRES_DB` (default `methylpipeline`), `POSTGRES_USER` (default `postgres`), `POSTGRES_PASSWORD`, and `PGSSLMODE` (default `require`). `METHYLPIPELINE_DB` replaces the built connection string. `WF_USE_MANAGED_IDENTITY=1` omits the password so an Entra token can be supplied at connect time. `WF_SCHEMA` defaults to `wf`.

Azure SQL uses `AZURE_SQL_SERVER`, `AZURE_SQL_DB`, `AZURE_SQL_USER`, and `AZURE_SQL_PASSWORD`.

The gateway listens on `WF_GATEWAY_HOST` or `REST_HOST` (default `127.0.0.1`) and `WF_GATEWAY_PORT` or `REST_PORT` (default `8080`). Health is `GET /`, `GET /v1`, and `GET /v1/health`. The health body reports `service` as `methyl-workflow-gateway`.

The gateway does not load an action catalog and does not resolve study configuration when a worker claims a task. `input_json` on the claim is whatever the database function returns.

## Config CLI

`goliath-cfg` (alias `methyl-cfg`) subcommands that call code in this tree:

`import-fs`, `upsert`, `materialize`, `publish-program`, `scaffold-action`, `verify-workflow`, `link-site-assets`, `provision-assets`, `expand-endpoint`, `list`, `get`, and the study-group commands (`set-study-group`, `set-study-group-members`, `list-study-groups`, `list-study-group-members`, `materialize-study-lists`).

`import-fs` reads JSON under `workflow_engine/domain/` when that layout is present, or under `domain/` when the checkout is a flattened runtime bundle. This repository's `workflow_engine/domain/` contains the compiler modules and no fixture directory, so an import of this tree records no domain documents.

Kinds accepted by the file store are `site`, `pipeline_profile`, `assay_procedure`, `analyte`, `domain_program`, `study`, `credential`, `storage_endpoint`, `storage_profile`, `reference_asset`, and `enrichment_library_preset`. Credential documents stay in the store. `materialize` does not write them under `/work`.

## Shared storage

`scripts/init_work_layout.sh` creates a layout under `METHYL_WORK_ROOT`, or `WORK_ROOT`, or `/work`. The mount must already exist. Writable directories (`0777`, with a default ACL when `setfacl` works): `samples/`, `projects/`, `cache/`. Directories created mode `0755`: `genomes/`, `site/`, `goliath/`. If `site/methyl_site.json` is absent, the script copies `scripts/default_methyl_site.json`. An existing site file is left in place.

`goliath_worker.work_share` treats `/work` as optional. It also honors `METHYL_WORK_ROOT` and an existing `/lambda/nfs/Work`. A workflow that never calls those helpers has no dependency on the mount.

## Local workflow run

```bash
goliath-workflow-run --program path/to/program.json --compile-only
goliath-workflow-run --program path/to/program.json --stub-external
goliath-workflow-run --workflow path/to/spec.json --dry-run
```

`--compile-only` writes `WorkflowDefinitionSpec` JSON and does not execute. Execution without `--stub-external` imports `methyl_worker` handlers. That package is not in this tree. `--stub-external` sets `WORKER_STUB_EXTERNAL=1` and returns a stub payload per action. A checked-in program used by tests is `workflow_engine/tests/fixtures/sample_prep.program.json`.

`finalize_instance_context` enriches a run from `methyl_utils` (project file, site manifest, modality gate). The local engine logs and continues when that import or the project file fails.
