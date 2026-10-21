# Schema apply

PostgreSQL schema changes ship as ordered SQL files under `workflow_engine/sql_pg/`. [`deploy_azure.sh`](https://github.com/Goliath-Research/GoliathApp/blob/main/workflow_engine/sql_pg/deploy_azure.sh) applies that list every time it runs. The files are written so the same ordered run can be repeated on a database that already has the objects: `CREATE … IF NOT EXISTS`, `CREATE OR REPLACE`, and `DROP FUNCTION IF EXISTS` / `DROP VIEW IF EXISTS` before a return row type changes. `CREATE OR REPLACE` cannot change a `RETURNS TABLE` row type (SQLSTATE 42P13) or replace a function with a narrower definition. Each function is defined in one place in the list. A later file drops the earlier overload when it widens an argument list.

An application that ships this engine applies the list once per release, to the existing database. The shell script has no release-version table and no skip-if-applied marker. One invocation applies every file in `SCRIPTS`.

## What the script runs

`deploy_azure.sh` requires `psql` (PostgreSQL 15+; 17+ is what `00_schema.sql` recommends for SQL/JSON). It exports:

| Variable | Default |
|----------|---------|
| `PGHOST` | `goliath.postgres.database.azure.com` |
| `PGPORT` | `5432` |
| `PGDATABASE` | `POSTGRES_DB`, then `goliath` |
| `PGUSER` | `POSTGRES_USER`, then `dba` |
| `PGSSLMODE` | `require` |
| `PGPASSWORD` | `POSTGRES_PASSWORD`, or an Entra access token from `az account get-access-token` when `az` is on `PATH` |

It checks `current_user` and `version()`, applies each file with `psql -q -v ON_ERROR_STOP=1 -f`, then runs `workflow_engine/contract/validate_contract.py` when `python3` or `.venv/bin/python` is available. It does not set `check_function_bodies`.

`LANGUAGE sql` functions in the later portal and RBAC scripts mention `portal."Customers"`, `portal."Diseases"`, `portal."Role2Node"`, `portal."NavTree"`, and `cfg.analyte`. This tree does not create those tables. PostgreSQL validates `LANGUAGE sql` bodies at creation time when `check_function_bodies` is on, so a database without the referenced tables can fail on those files. `legacy_cross_schema_fks.sql` guards some of its foreign keys with `to_regclass` and skips a constraint when the table is absent.

## Order

The authoritative order is the `SCRIPTS` array. Grouped as that array stands:

1. Workflow core: `00_schema.sql`, `wf_instance_extension.sql`, `wf_json_column_alignment.sql`, `03_engine_core.sql`, `05_runtime_parity.sql`, `06_scope_writepath_parity.sql`, `07_scope_encoding_parity.sql`, `08_foreach_support.sql`, `wf_reclaim_expired_leases.sql`, `wf_worker_desired_state.sql`.
2. Actions and repository: `02_repository_api.sql`, `wf_action_schema.sql`, `wf_repo_upsert_workflow_action.sql`, `wf_action_dispatch_metadata.sql`, `wf_action_dispatch_concurrency.sql`, `wf_action_dispatch_affinity.sql`, `wf_data_type.sql`.
3. Workers: `01_worker_api.sql`, `wf_cluster_security_columns.sql`, `wf_worker_enrollment.sql`, `portal_worker_enrollment_api.sql`.
4. Graph and admin: `wf_apply_validation_plan.sql`, `wf_execution_scope.sql`, `04_admin.sql`, `wf_repo_create_workflow_graph.sql`, `wf_sql_collection_bindings.sql`, `portal_workflow_api.sql`, `wf_drop_platform_sample_storage.sql`.
5. Meta, RBAC, contract, onboarding: `meta_schema.sql`, `rbac_schema.sql`, `contract_schema.sql`, `onboarding_schema.sql`, `legacy_cross_schema_fks.sql`.
6. Config and portal: `cfg_schema.sql`, `cfg_registry_tables.sql`, `cfg_wf_relationships.sql`, `cfg_repo_api.sql`, `portal_resource_profile.sql`, `cfg_portal_api.sql`, `portal_sample_extras_schema.sql`, `cfg_process_pack_catalog.sql`, `cfg_assay_procedure_links.sql`, `cfg_hyperparameter_search.sql`, `portal_modern_api_parity.sql`, `rbac_api_parity.sql`, `meta_api_parity.sql`, `contract_api_parity.sql`, `onboarding_api_parity.sql`, `portal_study_pipeline_api.sql`, `portal_ops_recovery_api.sql`, `portal_rbac_api.sql`, `portal_contract_api.sql`, `portal_study_ops_api.sql`, `portal_guardrails_editor.sql`, `cfg_study_start_request.sql`, `wf_event_plane.sql`.

Files on disk that the array does not apply:

- `wf_test_bed_schema.sql`, `wf_test_bed_worker.sql`, `wf_test_bed_run.sql` (see `deploy_test_bed.sh` and [workflow-engine.md](workflow-engine.md))
- `migrations/20260822_drop_e_portal.sql`
- `migrations/20260824_data_type_schema_json.sql`

## Azure SQL twin

`workflow_engine/sql_mssql/deploy_azure.sh` is a different file list (T-SQL names such as `wf_sql_runtime_parity.sql` and `rbac_api.sql`). `scripts/check_sql_deploy_twins.py` checks three things: no duplicate entries, every listed name exists on disk, and any basename that exists in both directories and is listed on one side is listed on the other. It does not require the two arrays to be equal.

CI parity (`workflow_engine/tests/parity/run_parity.py`) applies the PostgreSQL engine slice to database `methylpipeline_parity` and exercises claim, enrollment, scope resolution, and the REST gateway.

## PL/pgSQL name clashes

`RETURNS TABLE` columns are variables. An unqualified column of the same name fails at call time with SQLSTATE 42702. Functions in this tree put `#variable_conflict use_column` as the first line of the body when that clash would happen. `workflow_engine/tests/test_pg_plpgsql_variable_conflict.py` fails the build if a new function reintroduces it.
