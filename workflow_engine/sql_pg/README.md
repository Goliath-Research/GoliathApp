# PostgreSQL engine (`sql_pg/`)

PostgreSQL 15+ scripts for the workflow engine (17+ recommended for SQL/JSON). `00_schema.sql` uses `pg_catalog.sha256` and does not require `pgcrypto`.

Apply order, defaults, and which files are re-runnable are documented in [`docs/schema-apply.md`](../../docs/schema-apply.md). The ordered list is the `SCRIPTS` array in [`deploy_azure.sh`](deploy_azure.sh). Run that script to apply every file. It is safe to run again on a database that already has the objects. One invocation always applies the whole list. There is no skip-if-applied marker.

```bash
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=goliath
export PGUSER=postgres
export PGPASSWORD=...
export PGSSLMODE=require

./workflow_engine/sql_pg/deploy_azure.sh
```

When `PGHOST` is unset the script defaults to `goliath.postgres.database.azure.com`. When `PGDATABASE` is unset it uses `POSTGRES_DB` and then `goliath`. When `PGPASSWORD` is unset and `az` is on `PATH`, the script requests an Entra token for `https://ossrdbms-aad.database.windows.net`.

The Python gateway is a separate process. Its PostgreSQL defaults live in `workflow_engine/rest/connection.py`: `BACKEND_DB` defaults to `mssql`, and `POSTGRES_DB` defaults to `methylpipeline` when unset. Set `BACKEND_DB=postgres` and point `POSTGRES_*` at the database this script just updated.

```bash
export BACKEND_DB=postgres
export POSTGRES_HOST=localhost
export POSTGRES_DB=goliath
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=...
goliath-gateway --host 0.0.0.0 --port 8080
```

`methyl-gateway` is the same entry point.

After SQL, actions are rows in `wf.workflow_action` and types are rows in `wf.data_type`. See [`docs/actions.md`](../../docs/actions.md). This tree does not include a catalog seed script.

## Not applied by `deploy_azure.sh`

| Path | Role |
|------|------|
| `wf_test_bed_schema.sql`, `wf_test_bed_worker.sql`, `wf_test_bed_run.sql` | Test-bed tables and `wf.sp_test_bed_run_workflow` |
| `deploy_test_bed.sh` | Applies the test-bed scripts plus `wf_two_group_test_seed.sql` and `wf_mc_two_group_test_seed.sql`, which are not in this repository, so the script stops at the first missing file |
| `migrations/` | One-off upgrades. Not in `SCRIPTS` |

## Contract check

```bash
python workflow_engine/contract/validate_contract.py
```

`deploy_azure.sh` runs that check at the end when `python3` is available.

## Notes

- Result-returning worker APIs are functions that return `TABLE`. PostgreSQL procedures cannot `RETURN QUERY`.
- In PL/pgSQL, `RETURNS TABLE` columns are variables. `#variable_conflict use_column` on the first line of the body avoids SQLSTATE 42702 when a column has the same name. [`tests/test_pg_plpgsql_variable_conflict.py`](../tests/test_pg_plpgsql_variable_conflict.py) checks this.
- Object names match [`../contract/db_objects.yaml`](../contract/db_objects.yaml).
- The Azure SQL twin is [`../sql_mssql/README.md`](../sql_mssql/README.md).
