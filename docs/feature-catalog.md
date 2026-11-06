# Feature catalog

Use this page as a **map**: short intent for each major capability, when to adopt it, and where it is documented in this repository. Everything here is **platform-neutral**; domain semantics live in descendant repositories.

| Capability | What it is | When to use | Read more |
|------------|------------|-------------|-----------|
| **Platform stack & boundaries** | Database-governed workflows, portal, RBAC, Meta, optional inventory; HTTP gateway and worker protocol; no upstream imports of product repos | Ground rules before any design | [platform.md](platform.md), [architecture.md](architecture.md), [decoupling-plan.md](decoupling-plan.md) |
| **Repository layout** | Where gateway, SQL, `goliath_app`, worker client, contracts, and docs live | Orient new contributors | [workspace-index.md](workspace-index.md) |
| **Workflow compiler** | DomainProgram JSON → `WorkflowDefinitionSpec` | Author or verify graphs offline | [workflow-compiler.md](workflow-compiler.md) |
| **Workflow engine** | PostgreSQL runtime: instances, ACTION nodes, leases, event plane | Understand execution and failure behavior | [workflow-engine.md](workflow-engine.md) |
| **User-defined actions** | Rows in `wf.workflow_action` + `wf.data_type`; Pydantic `ActionSpec` in Python for catalog/export | Define work units workers claim | [actions.md](actions.md), `goliath_app/actions/spec.py`, `goliath_app/actions/registry.py` |
| **Action catalog entry points** | `goliath.action_catalogs` merges `ActionSpec` lists and typed overrides | Ship domain actions in a separate installable package | `workflow_engine/pyproject.toml`, `goliath_app/actions/registry.py`, [inventory-module.md](inventory-module.md) |
| **Distributed workers** | Enroll → session → claim → heartbeat/submit/fail against `goliath-gateway` | Run compute on pooled machines | [workers.md](workers.md), `workers/WORKER_PROTOCOL.md`, `contracts/openapi.yaml` |
| **Dual activation** | Push wake hints + unchanged claim for single-winner leases | Reduce latency after events or starts | [dual-activation.md](dual-activation.md), `goliath_worker/wake.py` |
| **RBAC & portal** | Users, roles, scopes, NavTree entitlements | Control who sees operators and navigation | [rbac.md](rbac.md), `workflow_engine/sql_pg/portal_shell_schema.sql` |
| **Meta object model** | Classes, fields, links, ObjValues JSONB, generated JSON Schema, `V<Class>` views | Model documents with inheritance and typed validation | [meta-model.md](meta-model.md), `goliath_app/meta/validation.py` |
| **Semantic layer** | `portal` registry + `portal.sp_run_semantic_request` + optional Exograph | Stable entity vocabulary for UIs and agents | [semantic-layer.md](semantic-layer.md), `workflow_engine/sql_pg/portal_semantic_schema.sql` |
| **Semantic extensions** | Namespaces, registration procs, overrides, permissions | Add entities/requests from a descendant app | [semantic-extensions.md](semantic-extensions.md), `goliath_app/semantic/catalog.py` |
| **Semantic export** | Pydantic → SQL composites + `schemas/semantic/catalog.json` | Keep DB, Python, and CI in sync | `goliath_app/semantic/export.py`, `.github/workflows/pr.yml` |
| **Portal client** | Python caller for `portal.sp_*` (including semantic runner) | Backend BFF without GraphQL | [semantic-layer.md](semantic-layer.md#python-portal-client), `goliath_app/portal/client.py` |
| **Inventory module (`inv`)** | Optional stock/purchasing schema + semantic namespace + core `ActionSpec`s | Reuse supply-chain mechanics without forking | [inventory-module.md](inventory-module.md), `goliath_app/inv/` |
| **Pipeline profiles** | `cfg` documents + `seed_pipeline_scope_flags` merge into instance context | Drive `IF` branches from profile/modality | [pipeline-profiles.md](pipeline-profiles.md), `workflow_engine/domain/pipeline_profiles.py` |
| **Application profile entry point** | `goliath.application_profiles` supplies profile/procedure loaders | Resolve named presets when not DB-only | `workflow_engine/domain/application_extension.py`, [pipeline-profiles.md](pipeline-profiles.md) |
| **Config CLI** | `goliath-cfg` file-backed registry (`cfg` kinds) | Import/materialize site + program artifacts | [platform.md](platform.md#config-cli), `workflow_engine/cfg/` |
| **Schema apply** | Ordered, re-runnable `workflow_engine/sql_pg` apply | Deploy and upgrade PostgreSQL | [schema-apply.md](schema-apply.md), `workflow_engine/sql_pg/apply_schema.sh` |
| **Deployment (Exograph target)** | Optional read/query façade over the same portal entry points | GraphQL/MCP alongside portal | [deployment.md](deployment.md), `exo/` |
| **HTTP / ASGI** | uvicorn-hosted gateway; health routes | Operate gateway behind a reverse proxy | [platform.md](platform.md#gateway-and-database-defaults), `workflow_engine/rest/gateway.py` |
| **Contract & export checks** | `validate_contract.py`, JSON schema exports for actions/semantics | CI parity for catalogs | `.github/workflows/pr.yml`, `workflow_engine/contract/` |

## Adoption path (summary)

1. **Read** [architecture.md](architecture.md) and [platform.md](platform.md).  
2. **Apply** schema with [schema-apply.md](schema-apply.md).  
3. **Register** semantics ([semantic-extensions.md](semantic-extensions.md)) and **actions** ([actions.md](actions.md)) — Python specs + SQL seeds.  
4. **Wire** `goliath.action_catalogs` (and optional `goliath.application_profiles`) in **your** `pyproject.toml`.  
5. **Enroll** workers ([workers.md](workers.md)); optionally enable **dual activation** ([dual-activation.md](dual-activation.md)).  

For a narrative walkthrough, see [adopter-guide.md](adopter-guide.md).
