# GoliathApp

**GoliathApp** is a general-purpose enterprise platform. Specialized applications extend it. The platform does not depend on those applications.

It keeps application behavior in a database: a Meta object model, RBAC, portal SQL, a workflow engine, and user-defined actions. A REST gateway enrolls distributed workers that carry out the actions. This repository ships the engine, the compiler, and the claim client.

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

The distribution name in `workflow_engine/pyproject.toml` is `methyl-gateway`. Python is `>=3.10,<3.15`. These console scripts point at modules in this tree:

| Script | Entry |
|--------|--------|
| `goliath-gateway`, `methyl-gateway` | `rest.gateway:main` |
| `goliath-workflow-run`, `methyl-workflow-run` | `local.runner:main` |
| `goliath-cfg`, `methyl-cfg` | `cfg.cli:main` |

The same file also lists `methyl-study-start`, `methyl-study-init`, `methyl-study-validate-manifest`, and `methyl-reclaim-leases`. Those entry points import `admin` and `ops`, and those packages are not in this tree.

The shared worker HTTP client is `goliath_worker/` (stdlib only). It claims and submits tasks. It does not execute an action.

## Databases

PostgreSQL objects are applied by [`workflow_engine/sql_pg/apply_schema.sh`](workflow_engine/sql_pg/apply_schema.sh). Set `PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` (or `PGPASSFILE`) before running. The Python gateway reads the same libpq-style variables (or `POSTGRES_*` aliases); see [`workflow_engine/rest/connection.py`](workflow_engine/rest/connection.py).

## Type checking

[Pyrefly](https://pyrefly.org) checks `workflow_engine/`, `scripts/`, and `goliath_worker/` as Python 3.12, which is the version CI runs.

```bash
python -m pip install -e "workflow_engine/[dev]"
pyrefly check
```
