# Repository layout

This repository is the platform. Specialized applications extend it with actions, profiles, and handlers. Those applications are not documented here.

| Path | Role |
|------|------|
| `workflow_engine/rest/` | REST gateway (`goliath-gateway`) |
| `workflow_engine/local/` | In-process workflow runner (`goliath-workflow-run`) |
| `workflow_engine/domain/` | DomainProgram compiler, verifier, pipeline-profile scope flags |
| `workflow_engine/cfg/` | File-backed configuration CLI (`goliath-cfg`) |
| `workflow_engine/contract/` | Database object contract and workflow spec models |
| `workflow_engine/sql_pg/` | PostgreSQL engine. Apply with `deploy_azure.sh` |
| `workflow_engine/sql_mssql/` | Azure SQL twin of the engine |
| `workflow_engine/delphi/` | Frozen Windows gateway reference |
| `workflow_engine/tests/` | Gateway, compiler, and parity tests |
| `goliath_worker/` | Claim and submit HTTP client, optional shared-storage helpers |
| `workers/WORKER_PROTOCOL.md` | Worker HTTP protocol |
| `contracts/openapi.yaml` | Published HTTP contract |
| `scripts/` | Layout init, SQL twin check, schema inventory |
| `docs/` | This documentation set |
| `.goliath/product.json` | Machine-readable product summary |

Console scripts that resolve to modules in this tree are `goliath-gateway`, `goliath-workflow-run`, and `goliath-cfg`, plus the `methyl-gateway`, `methyl-workflow-run`, and `methyl-cfg` aliases of those three. The distribution name is `methyl-gateway`.
