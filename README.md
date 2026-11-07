# GoliathApp

**GoliathApp** is a general-purpose enterprise platform. Specialized applications extend it. The platform does not depend on those applications.

It keeps application behavior in a database: a Meta object model (see [docs/meta-model.md](docs/meta-model.md)), RBAC, portal SQL, a workflow engine, and user-defined actions. A REST gateway enrolls distributed workers that carry out the actions. This repository ships the engine, the compiler, and the claim client.

**Documentation for adopters:** the full site lives under `docs/` and publishes to <https://goliath-research.github.io/GoliathApp/>. Start with [docs/adopter-guide.md](docs/adopter-guide.md) (building a descendant application), [docs/architecture.md](docs/architecture.md) (diagrams and layers), and [docs/feature-catalog.md](docs/feature-catalog.md) (capability map with links).

Repository layout: [docs/workspace-index.md](docs/workspace-index.md). A catalog site can read [`.goliath/product.json`](.goliath/product.json) at build time.

## Read next

| Topic | Page |
|-------|------|
| What lives in this repository | [docs/platform.md](docs/platform.md) |
| DomainProgram compiler | [docs/workflow-compiler.md](docs/workflow-compiler.md) |
| Database workflow engine | [docs/workflow-engine.md](docs/workflow-engine.md) |
| User-defined actions | [docs/actions.md](docs/actions.md) |
| Worker enrollment and dispatch | [docs/workers.md](docs/workers.md) |
| RBAC | [docs/rbac.md](docs/rbac.md) |
| Pipeline profiles | [docs/pipeline-profiles.md](docs/pipeline-profiles.md) |
| Schema apply (`sql_pg`) | [docs/schema-apply.md](docs/schema-apply.md) |
| Database population (seeds, bootstrap) | [docs/database-population.md](docs/database-population.md) |
| PostgreSQL deploy script | [workflow_engine/sql_pg/README.md](workflow_engine/sql_pg/README.md) |
| HTTP contract | [contracts/openapi.yaml](contracts/openapi.yaml) |
| Worker protocol | [workers/WORKER_PROTOCOL.md](workers/WORKER_PROTOCOL.md) |

The MkDocs Material site is built from `docs/` (`mkdocs.yml`) and published to <https://goliath-research.github.io/GoliathApp/> on every push to `main`. Pull requests build the site and do not deploy it.

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve
```

## Package

```bash
python -m pip install -e "workflow_engine/[dev]"
```

The installable distribution is **`goliath-gateway`** (see `workflow_engine/pyproject.toml`). Python is `>=3.10,<3.15`. Console scripts that point at modules in this tree:

| Script | Entry |
|--------|--------|
| `goliath-gateway` | `rest.gateway:main` |
| `goliath-workflow-run` | `local.runner:main` |
| `goliath-cfg` | `cfg.cli:main` |

The same file also lists legacy study and ops console entry points. Those entry points import `admin` and `ops`, and those packages are not in this tree. Extension application repositories document one-release console and environment aliases still used on deployed targets.

The shared worker HTTP client is `goliath_worker/` (stdlib only). It claims and submits tasks. It does not execute an action.

## Databases

PostgreSQL objects are applied by [`workflow_engine/sql_pg/apply_schema.sh`](workflow_engine/sql_pg/apply_schema.sh). Set `PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` (or `PGPASSFILE`) before running. The Python gateway reads the same libpq-style variables (or `POSTGRES_*` aliases); see [`workflow_engine/rest/connection.py`](workflow_engine/rest/connection.py).

## Type checking

[Pyrefly](https://pyrefly.org) checks `workflow_engine/`, `scripts/`, and `goliath_worker/` as Python 3.12, which is the version CI runs.

```bash
python -m pip install -e "workflow_engine/[dev]"
pyrefly check
```
