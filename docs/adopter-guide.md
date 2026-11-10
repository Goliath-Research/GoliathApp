# Adopter guide: building a descendant application

This guide is for engineers **evaluating** GoliathApp or **starting** a new specialized application that extends the platform. It sticks to **neutral** platform concepts: anything domain-specific (science, industry verticals, geography) belongs in **your** repository, not in GoliathApp.

**Operators** who use the signed-in portal (`/app`) should read the [Operator portal guide](operator-portal-guide.md) instead. It describes the two supported starting paths — **extend your deployment in place** vs **duplicate GoliathApp as your base** — and how class hierarchy, views, and dashboards appear in the UI. Product data must not accumulate on the shared **clean generic baseline** database; use your tenant database or a forked copy.

## What you are extending

GoliathApp provides:

- PostgreSQL schemas and procedures for **workflows** (`wf`), **portal** operators and semantic registry (`portal`), **RBAC**, **Meta**, **`cfg`** documents, and optional **`inv`** (inventory).
- The **`goliath-gateway`** REST service (`workflow_engine/rest/`) and a stdlib **`goliath_worker`** HTTP client.
- **Python packages** under `goliath_app/` for typed **`ActionSpec`**, semantic **`Semantic*Spec`** models, portal client helpers, and Meta validation.
- **Entry-point groups** (see `workflow_engine/pyproject.toml`) so installed packages merge **action catalogs** and optional **application profile** loaders without the platform importing your code by name.

The platform **never** embeds your domain. That boundary is enforced in development by repository guard tests (see `workflow_engine/tests/test_goliathapp_no_child_app_tokens.py` and [decoupling-plan.md](decoupling-plan.md)).

### Workers and the database

**Worker processes must not open PostgreSQL** — not for claims, not for wakes. They call **`goliath-gateway`** only (`contracts/openapi.yaml`). The gateway holds database credentials, runs `wf.sp_*` and `portal.sp_*` on behalf of trusted callers, and publishes **wakes** after event ingest and workflow start. Workers receive wakes **through gateway-authenticated HTTP** (long-poll / SSE / WebSocket or equivalent — **required design**; wire format follow-up until it appears in OpenAPI). **Do not** adopt worker-side Postgres `LISTEN` or `WORKER_WAKE_PG_DSN`; that path is **superseded** ([dual-activation.md](dual-activation.md)).

## Child application vs standalone utility

| Build | Depends on `goliath-gateway` / platform DB? | Typical artifact |
|-------|---------------------------------------------|------------------|
| **Descendant application** | Yes — enrolls workers, ships SQL + seeds, may add semantic namespaces and `ActionLevel.DOMAIN` actions | Product database + worker fleet + BFF |
| **Standalone utility** | No — general CLI or library (alignment, extraction, conversion, etc.) | Executable used upstream or by workers off-line |

If the tool only needs files and CPUs and never talks to **`goliath-gateway`**, keep it **outside** the platform dependency graph. Workflows can still **invoke** such tools from a worker host without making the tool a “child” of GoliathApp.

## Recommended repository layout (descendant)

A typical layout **inherits** this repository as a library + SQL baseline and adds **your** packages:

```text
your-repo/
  pyproject.toml              # depends on goliath-gateway (see below)
  sql/                        # append-only migrations + seeds after GoliathApp apply
  your_app/                   # domain: ActionSpec lists, semantic specs, handlers
  your_worker/                # enroll + claim loop (uses goliath_worker)
  docs/                       # your operator + science docs
```

You apply GoliathApp’s scripts first ([schema-apply.md](schema-apply.md)), then your migrations that register **new** `portal`/`wf`/`Meta` rows. Keep platform upgrade paths explicit: fork or pin the GoliathApp revision you tested.

For **how to run `psql` / seeds / bootstrap vs descendant rows**, see [database-population.md](database-population.md) (workers still never hold SQL credentials).

## Packaging: depend on `goliath-gateway`

The installable name on PyPI / in this tree is **`goliath-gateway`** (`workflow_engine/pyproject.toml`). Console scripts include `goliath-gateway`, `goliath-workflow-run`, and `goliath-cfg`. Your package should list `goliath-gateway` as a dependency and expose entry points into the groups below.

## Entry points the platform discovers

| Group | Purpose | Declared in |
|-------|---------|-------------|
| `goliath.action_catalogs` | Merge typed `ActionSpec` lists (engine/core/domain); optional **overrides** of core actions | `workflow_engine/pyproject.toml`; loader `goliath_app/actions/registry.py` |
| `goliath.application_profiles` | Optional module for **pipeline profile** file resolution when not using platform-only defaults | `workflow_engine/domain/application_extension.py` |
| `goliath.auth_providers` | Portal auth provider plugins | `goliath_app/auth/providers.py` |
| `goliath.execution_scope_hooks` | Workflow execution scope hooks | `workflow_engine/rest/execution_scope.py` |

Namespace **`goliath.application_profiles`** is how `goliath-workflow-run` and profile helpers resolve named profiles when the platform wheel is installed alone ([pipeline-profiles.md](pipeline-profiles.md)): without your entry point, loading named presets that lived in a product tree raises `FileNotFoundError` with a message pointing at that group.

## 1. Semantic entities and requests (Exograph / portal)

**Source of truth** is PostgreSQL: `portal.semantic_*` tables, registered with:

- `portal.sp_semantic_register_entity`
- `portal.sp_semantic_register_attribute`
- `portal.sp_semantic_register_request`

Author in Python using **`SemanticEntitySpec`** / **`SemanticRequestSpec`** (`goliath_app/semantic/spec.py`), export with **`goliath-semantic-export`**, then apply generated SQL + seed ([semantic-extensions.md](semantic-extensions.md), [semantic-layer.md](semantic-layer.md)).

**Namespaces** such as `core`, `inv`, and `engine` are reserved platform areas; descendant apps add **`your_namespace.*`** rows in apply scripts.

## 2. Typed actions (`ActionSpec`)

Actions are **database rows** on `wf.workflow_action`; the **catalog** you ship in Python documents names, capabilities, Pydantic input/output models, and handler entry points ([actions.md](actions.md), `goliath_app/actions/spec.py`).

- Register **`ActionLevel.DOMAIN`** specs in **your** `goliath.action_catalogs` entry point.
- Merge order and **override** rules (same `action_name`, `overrides="namespace_of_base"`) are implemented in `goliath_app/actions/registry.py`.
- Export JSON Schemas for CI with **`goliath-export-action-schemas`** (see `.github/workflows/pr.yml`).

Your worker executable matches **`capability`** strings to claimable tasks ([workers.md](workers.md)).

## 3. NavTree menu nodes

**Platform baseline (do not reimplement):** GoliathApp seeds the inherited administrative NavTree with **`workflow_engine/sql_pg/seed_platform_nav_tree.sql`** on every database (empty or upgraded) — see [database-population.md](database-population.md). Your deployment should run that script after `apply_schema.sh` and the Python catalog seeds; `organization_admin` receives baseline Role2Node grants when organization scopes exist.

**Your domain nodes:** use **`portal.sp_nav_register_node`** (creates Meta `portal/NavNode` + legacy `portal."NavTree"` row; grant **`portal."Role2Node"`** for RBAC) — see [nav-tree-meta.md](nav-tree-meta.md), `workflow_engine/sql_pg/portal_nav_meta.sql`, and [rbac.md](rbac.md).

## 4. Meta classes and validation

When instances should be **schema-validated** document payloads:

- Declare **classes/fields** in `Meta`; published types align with `wf.data_type` ([meta-model.md](meta-model.md)).
- Validate at write time with **Pydantic** (`goliath_app/meta/validation.py`) in application code, and optionally with **`pg_jsonschema`** triggers in the database (same document §4–§5).

## 5. Pipeline profiles and `cfg` documents

`cfg.pipeline_profile` and related **`goliath-cfg`** kinds hold JSON documents; **`seed_pipeline_scope_flags`** in `workflow_engine/domain/pipeline_profiles.py` maps profile + modality into **scope flags** for `IF` nodes. A descendant application either ships JSON files reachable from a **`goliath.application_profiles`** module or keeps profiles entirely in the database via **`goliath-cfg`** ([pipeline-profiles.md](pipeline-profiles.md)).

## 6. Worker enrollment and handlers

1. **Allowlist** enrollment (`portal.sp_upsert_cluster`, `portal.sp_upsert_worker_enrollment`).
2. Worker calls **`POST /v1/workers/enroll`** on `goliath-gateway` ([workers.md](workers.md), `contracts/openapi.yaml`).
3. After claim, **your** handler runs (CLI, in-process import, etc.); `goliath_worker` only performs HTTP.

**No DSN on worker hosts** — fleet machines must not receive credentials for the primary database; wakes are not an exception ([dual-activation.md](dual-activation.md)).

## 7. Dual activation (optional fast path)

Use **wake then claim** so idle workers react sooner after events or workflow starts: the **gateway** publishes `WorkerWakeMessage` hints; workers **subscribe via the gateway** (same session as claim), then call **`POST /v1/workers/tasks/request`** as today. See [dual-activation.md](dual-activation.md) for the DTO, logical channel names, and the **superseded** worker `LISTEN` / `WORKER_WAKE_POSTGRES` pattern (do **not** inherit). **`WF_WAKE_POSTGRES`** applies to **gateway-side** internal `NOTIFY` when used; it does **not** grant workers a database connection.

## 8. Schema apply and CI parity

Ship migrations as ordered SQL following [schema-apply.md](schema-apply.md). CI in this repo runs **`mkdocs build --strict`**, contract validation, **Pyrefly**, and gateway tests (`.github/workflows/pr.yml`); mirror the pieces that matter for your fork.

## Worked mini-examples (neutral names)

The snippets below are **shapes from this repository**, not a runnable product.

### `ActionSpec` (inventory stock receive)

```python
from goliath_app.actions.spec import ActionExposure, ActionLevel, ActionSpec
from goliath_app.inv.models import ReceiveStockInput, ReceiveStockOutput

inventory_demo_receive = ActionSpec(
    action_name="inv.stock.receive",
    namespace="inv",
    level=ActionLevel.CORE,
    entity_code="stock_lot",
    display_name="Receive stock",
    description="Receive a purchase order line into a bin lot.",
    exposure=ActionExposure.RBAC,
    required_permission="inv.stock.receive",
    input_model=ReceiveStockInput,
    output_model=ReceiveStockOutput,
    schema_version="1",
    capability="inv.stock",
    tool="inv.stock.receive",
    in_process_handler="goliath_app.inv.handlers:handle_receive_stock",
)
```

(Source: `goliath_app/inv/catalog.py`.)

### Semantic entity + request (`core` organization)

```python
from goliath_app.semantic.models import OrganizationRow, ListOrganizationsParams
from goliath_app.semantic.spec import SemanticAttributeSpec, SemanticEntitySpec, SemanticRequestSpec

acme_demo_org_entity = SemanticEntitySpec(
    namespace="core",
    code="organization",
    display_name="Organization",
    description="Generic GoliathApp organization tenancy record.",
    schema_version="1",
    row_model=OrganizationRow,
    storage_relation='portal."Organizations"',
    attributes=(
        SemanticAttributeSpec("organization_id", "ID", "integer", "key", ()),
        SemanticAttributeSpec("name", "Name", "string", "filter", ()),
        SemanticAttributeSpec("active", "Active", "boolean", "list", ()),
    ),
)

acme_demo_list_orgs = SemanticRequestSpec(
    request_code="core.list_organizations",
    version="1",
    namespace="core",
    entity_code="organization",
    target_kind="function",
    target_name="portal.fn_semantic_core_list_organizations",
    params_model=ListOrganizationsParams,
    result_row_model=OrganizationRow,
)
```

(Source: `goliath_app/semantic/catalog.py`.)

### NavTree registration (SQL)

```sql
SELECT portal.sp_nav_register_node(
  p_parent_id := NULL,
  p_caption := 'AcmeChild Home',
  p_seq := 10,
  p_info_id := NULL,
  p_node_path := '/acme-child',
  p_sort_path := '0010'
);
```

(Source: `workflow_engine/sql_pg/portal_shell_schema.sql` — function signature and table names.)

### `pyproject.toml` entry points (pattern)

```toml
[project.entry-points."goliath.action_catalogs"]
acme_child = "acme_child.catalog:ACTION_CATALOG"

[project.entry-points."goliath.application_profiles"]
acme_child = "acme_child.profiles"
```

(Source: groups mirror `workflow_engine/pyproject.toml`; module names are illustrative.)

## Reference implementations

Public repositories in the **Goliath-Research** GitHub organization include specialized stacks that combine this platform with domain-specific SQL, workers, and profiles. This documentation intentionally **does not** enumerate those product names in-repo (CI guard: `test_goliathapp_no_child_app_tokens.py`). Browse the org’s open-source projects alongside this repository when you need a full worked system.

## See also

- [feature-catalog.md](feature-catalog.md) — one-page map of capabilities → docs  
- [architecture.md](architecture.md) — diagrams and layer overview  
- [platform.md](platform.md) — processes, env vars, and schema map  
