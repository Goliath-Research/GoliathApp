# GoliathApp

**GoliathApp** is the platform. **GoliathOmics** is the genomics product. **GoliathAlign** (formerly mojo-align) aligns reads. **MethylExtractor** calls methylation from linear BAM files. **GoliathWeb** is the public hub.

Index: [docs/workspace-index.md](docs/workspace-index.md).

Generic application platform for Goliath Research: database-governed Meta model, RBAC, object instances, portal UI, workflow engine, middle-tier REST, and remote workers. Genomics content lives in GoliathOmics. Alignment and extraction stay independent tool repositories.

## Schemas

| Schema | Role |
|--------|------|
| `Meta` | OOP model of application information. Instances live in `Meta.Objs`. |
| `RBAC` | Roles over Meta classes and concrete objects |
| `portal` | UI objects that drive the portal |
| `wf` | Event-driven workflows and actions for portal users or remote workers |
| `cfg` | Sites, profiles, programs, storage, and reference-asset registry tables |
| `Contract`, `Onboarding` | Platform contracts and onboarding |

Science rows (analytes, action catalogs, disease columns) are GoliathOmics content loaded into this engine. They are not part of the engine DDL.

## Where to read

- [Platform overview](docs/platform.md)
- [Workspace index](docs/workspace-index.md)
- PostgreSQL engine: [workflow_engine/sql_pg/README.md](workflow_engine/sql_pg/README.md)
- Azure SQL twin: [workflow_engine/sql_mssql/README.md](workflow_engine/sql_mssql/README.md)
- HTTP contract: [contracts/openapi.yaml](contracts/openapi.yaml)
- Shared worker: `goliath_worker/`
- Historical split record: [docs/SEPARATION_PLAN.md](docs/SEPARATION_PLAN.md)
- Public hub wireframe: [docs/SITE_HUB_WIREFRAME.md](docs/SITE_HUB_WIREFRAME.md)

Platform entry points use the `goliath` prefix (`goliath-gateway`, `goliath-cfg`). The database name is `goliath`.
