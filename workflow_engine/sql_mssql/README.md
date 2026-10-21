# Azure SQL engine (`sql_mssql/`)

Azure SQL twin of the workflow engine. Apply order is the `SCRIPTS` array in [`deploy_azure.sh`](deploy_azure.sh). The PostgreSQL twin is [`../sql_pg/deploy_azure.sh`](../sql_pg/deploy_azure.sh). [`scripts/check_sql_deploy_twins.py`](../../scripts/check_sql_deploy_twins.py) fails when a SQL basename that exists in both trees is listed on only one side. The two arrays are not identical. T-SQL files use names such as `wf_sql_runtime_parity.sql` and `rbac_api.sql` where PostgreSQL uses `05_runtime_parity.sql` and `rbac_api_parity.sql`.

```bash
export AZURE_SQL_SERVER=your-server.database.windows.net
export AZURE_SQL_DB=goliath
export AZURE_SQL_USER=sql-admin
export AZURE_SQL_PASSWORD='...'
export SQLCMD_TRUST_SERVER_CERTIFICATE=1   # optional

./workflow_engine/sql_mssql/deploy_azure.sh
```

Optional cluster IP columns:

```bash
./workflow_engine/sql_mssql/deploy_azure.sh --with-cluster-security
```

The script applies the engine, portal, RBAC, Meta, contract, onboarding, and `cfg` files in `SCRIPTS`. It does not apply `deprecated/` or `migrations/`.

Action rows and data types are inserted after the schema exists. See [`docs/actions.md`](../../docs/actions.md). `wf_repo_upsert_workflow_action.sql` is the 3-argument bootstrap. Later files in the array widen it: dispatch metadata, concurrency (`max_per_worker`, `exclusive_worker`), and affinity (`affinity_key_field`, `prefer_previous_worker`, `prefer_continue_group`, `require_previous_worker`).

`workflow_seed_examples.sql` and `workflow_tree_seed_example.sql` are example graphs. They are not in `SCRIPTS`.

Gateway environment for this backend:

```bash
export BACKEND_DB=mssql
export AZURE_SQL_SERVER=your-server.database.windows.net
export AZURE_SQL_DB=goliath
export AZURE_SQL_USER=...
export AZURE_SQL_PASSWORD=...
goliath-gateway --host 0.0.0.0 --port 8080
```

PostgreSQL apply steps: [`../sql_pg/README.md`](../sql_pg/README.md) and [`docs/schema-apply.md`](../../docs/schema-apply.md).
