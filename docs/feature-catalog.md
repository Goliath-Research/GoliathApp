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
| **Device adapters** | Enrolled workers POST `POST /v1/events` (`wf.sp_worker_ingest_event`); MQTT / HA reference adapters; no worker SQL | Ingest telemetry from brokers or Home Assistant into the event plane | [device-adapters.md](device-adapters.md), `goliath_app/device_adapter/` |
| **Dual activation** | Gateway publishes wake hints; workers subscribe **via gateway** (auth); **`POST /v1/workers/tasks/request`** still grants the lease | Reduce latency after events or starts; **never** worker `LISTEN` / wake DSN | [dual-activation.md](dual-activation.md), `goliath_worker/wake.py` |
| **RBAC & portal** | Users, roles, scopes, NavTree entitlements | Control who sees operators and navigation | [rbac.md](rbac.md), `workflow_engine/sql_pg/portal_shell_schema.sql` |
| **Meta object model** | Classes, fields, links, ObjValues JSONB, generated JSON Schema, `V<Class>` views | Model documents with inheritance and typed validation | [meta-model.md](meta-model.md), `goliath_app/meta/validation.py` |
| **Semantic layer** | `portal` registry + `portal.sp_run_semantic_request` + optional Exograph | Stable entity vocabulary for UIs and agents | [semantic-layer.md](semantic-layer.md), `workflow_engine/sql_pg/portal_semantic_schema.sql` |
| **Semantic extensions** | Namespaces, registration procs, overrides, permissions | Add entities/requests from a descendant app | [semantic-extensions.md](semantic-extensions.md), `goliath_app/semantic/catalog.py` |
| **Semantic export** | Pydantic → SQL composites + `schemas/semantic/catalog.json` | Keep DB, Python, and CI in sync | `goliath_app/semantic/export.py`, `.github/workflows/pr.yml` |
| **Portal client** | Python caller for `portal.sp_*` (including semantic runner) | Backend BFF without GraphQL | [semantic-layer.md](semantic-layer.md#python-portal-client), `goliath_app/portal/client.py` |
| **Operator portal (host)** | Signed-in `/app`: NavTree, Meta hierarchy, platform lists, define views, arrange dashboards | Day-to-day operators on your deployment | [operator-portal-guide.md](operator-portal-guide.md), [deploy/platform-host-operator-portal.md](deploy/platform-host-operator-portal.md) |
| **Inventory module (`inv`)** | Optional stock/purchasing schema + semantic namespace + core `ActionSpec`s | Reuse supply-chain mechanics without forking | [inventory-module.md](inventory-module.md), `goliath_app/inv/` |
| **Pipeline profiles** | `cfg` documents + `seed_pipeline_scope_flags` merge into instance context | Drive `IF` branches from profile/modality | [pipeline-profiles.md](pipeline-profiles.md), `workflow_engine/domain/pipeline_profiles.py` |
| **Application profile entry point** | `goliath.application_profiles` supplies profile/procedure loaders | Resolve named presets when not DB-only | `workflow_engine/domain/application_extension.py`, [pipeline-profiles.md](pipeline-profiles.md) |
| **Config CLI** | `goliath-cfg` file-backed registry (`cfg` kinds) | Import/materialize site + program artifacts | [platform.md](platform.md#config-cli), `workflow_engine/cfg/` |
| **Schema apply** | Ordered, re-runnable `workflow_engine/sql_pg` apply | Deploy and upgrade PostgreSQL | [schema-apply.md](schema-apply.md), `workflow_engine/sql_pg/apply_schema.sh` |
| **Database population** | DDL vs seeds vs org bootstrap vs descendant registration (`psql`, `seed_*.py`) | Know what runs as DBA vs runtime | [database-population.md](database-population.md) |
| **Deployment (Exograph target)** | Optional read/query façade over the same portal entry points | GraphQL/MCP alongside portal | [deployment.md](deployment.md), `exo/` |
| **HTTP / ASGI** | uvicorn-hosted gateway; health routes | Operate gateway behind a reverse proxy | [platform.md](platform.md#gateway-and-database-defaults), `workflow_engine/rest/gateway.py` |
| **Contract & export checks** | `validate_contract.py`, JSON schema exports for actions/semantics | CI parity for catalogs | `.github/workflows/pr.yml`, `workflow_engine/contract/` |
| **Operator portal editors** | Generic data grids (Add / View / Edit), typed property grid, and tree editor, all driven by Meta schemas and catalog types. No JSON typing. Child apps seed classes, data, and programs; they do not ship UI. | Day-to-day authoring on the platform host | [operator-portal-guide.md](operator-portal-guide.md) |
| **Typed config documents** | Child apps register a catalog data type for `cfg` kinds (`site`, `pipeline_profile`) with `cfg.sp_register_kind_document_type`. The typed inspector edits field by field; unregistered kinds are view-only. | Site parameters and pipeline profiles | [operator-portal-guide.md](operator-portal-guide.md#organizations-and-config-documents), [pipeline-profiles.md](pipeline-profiles.md) |
| **Published site document** | `portal.fn_published_site_document` returns a published `cfg.site` document (by id, or the published `default` site). Generic: no key interpretation. | Resolve site parameters for workers | [pipeline-profiles.md](pipeline-profiles.md), [operator-portal-guide.md](operator-portal-guide.md) |
| **Workflow designer** | Versioned graph editor for definitions and steps; ACTION parameters come from class methods; save as a new inactive version, then activate. | Author workflow graphs in the portal | [operator-portal-guide.md](operator-portal-guide.md#editing-workflow-records) |
| **Domain program compile / publish** | Edit draft steps in a record grid; compile on the server with the generic compile service; publish an inactive workflow version. | Change a DomainProgram without a file-store deploy | [workflow-compiler.md](workflow-compiler.md), [operator-portal-guide.md](operator-portal-guide.md#editing-and-compiling-domain-programs) |
| **Actions as class methods** | Every action is a method on exactly one owning Meta class. `"Meta".sp_derive_action_methods` types parameters from the input schema. `"Meta".fn_check_action_owners` enforces the one-owner rule. | Bind and type actions from a child-app seed | [actions.md](actions.md) |
| **History and audit ledgers** | Append-only, hash-chained audit and event tables; verification and exportable checkpoints | Prove what happened and that nothing was changed or removed | [history-and-audit.md](history-and-audit.md), `workflow_engine/sql_pg/platform_history_ledger.sql` |
| **Catalogs as Meta classes** | 38 catalog kinds (semantic, workflow, and cfg) projected as Meta classes; tables remain the indexed read surface. `verify_meta_catalogs.sh` checks drift. | Inspect or repair catalog projection | [meta-catalogs.md](meta-catalogs.md) |

## Adoption path (summary)

1. **Read** [architecture.md](architecture.md) and [platform.md](platform.md).  
2. **Apply** schema with [schema-apply.md](schema-apply.md).  
2b. **Populate** seeds and know bootstrap order — [database-population.md](database-population.md).  
3. **Register** semantics ([semantic-extensions.md](semantic-extensions.md)) and **actions** ([actions.md](actions.md)) — Python specs + SQL seeds.  
4. **Wire** `goliath.action_catalogs` (and optional `goliath.application_profiles`) in **your** `pyproject.toml`.  
5. **Enroll** workers ([workers.md](workers.md)); optionally enable **dual activation** ([dual-activation.md](dual-activation.md)).  

For a narrative walkthrough, see [adopter-guide.md](adopter-guide.md).
