# Platform host operator portal (plan)

This page tracks the **signed-in operator portal** for `apps/platform-host` and lists **required deliverables**, including end-user documentation. Implementation status refers to the GoliathApp repository on `main` plus open work in PRs (for example operator chrome, Meta hierarchy, views/dashboards).

## Goals

1. **Official NavTree chrome** for authenticated `/app` (nested tree, `node_path` routing, session identity, sign-out).
2. **Meta / OOP first** — class hierarchy and existing Meta workbench (`SchemaPropertyGrid`, nested inspector) as the primary workspace, not a side screen.
3. **Full inheritable platform** — administration, workflows, semantic layer, configuration, operations, inventory, and views reachable where APIs exist.
4. **Views and dashboards** — operators can **define views** on semantic/Meta entities and **arrange dashboards** from those views (same data paths as list editors).
5. **End-user documentation** — **required**, not optional: [Operator portal guide (end users)](../operator-portal-guide.md) explains both starting paths and portal workflows.

## Required deliverables

| Deliverable | Status | Location |
|-------------|--------|----------|
| Session NavTree + `node_path` in `sp_session_operator_nav_tree` | Shipped (apply SQL on deploy) | `workflow_engine/sql_pg/portal_session_nav_api.sql` |
| Operator portal shell (no fixture chrome on `/app`) | Shipped in PR #66+ | `apps/platform-host` `(operator)/app` |
| Meta hierarchy + workbench routing | Shipped | `MetaClassHierarchyList`, `MetaWorkbenchPanel` |
| Platform list surfaces (session wrappers) | Shipped | `portal_session_platform_api.sql` |
| Operator views + dashboards persistence | Shipped | `portal_operator_views_api.sql` |
| **End-user operator guide (two starting paths)** | **Required** | [operator-portal-guide.md](../operator-portal-guide.md) |
| **Platform generic Meta baseline** | **Required** — `platform_generic_meta_baseline.sql` | [platform-generic-meta.md](../platform-generic-meta.md) |
| **Model authoring (session APIs + portal UI)** | **Required** — `portal_session_model_authoring_api.sql` | `/app/semantic`, Meta authoring, `/app/admin/navigation` |
| **Layered security (class/object ACL + admin)** | **Required** — `portal_layered_security_*.sql` | `/app/admin/users`, Meta **Security** tab — [platform-layered-security.md](../platform-layered-security.md) |
| Engineer deploy/auth docs | Existing | [platform-host.md](platform-host.md), [platform-host-p1-auth.md](platform-host-p1-auth.md) |

## Phased UI roadmap (visualization)

| Phase | Scope | Notes |
|-------|--------|--------|
| P0 | Packages, fixture, icons | Done — [visualization.md](../visualization.md) |
| P1 | BFF, session, OIDC | Done |
| P2 | Meta hierarchy browser + editors | In portal PR |
| P3 | Workflow designer / monitor depth | Partial lists; designer TBD |
| P4 | Semantic + admin screens | Lists via session platform API |
| P5 | Views/dashboards | **Define + arrange** in portal PR; widget layout refinements follow |
| P6 | Multi-child adoption | In progress — [multi-product platform host](multi-product-platform-host.md) |

Updating [visualization.md](../visualization.md) and this plan together is mandatory when portal scope changes.

## SQL apply (operator features)

### Existing database upgrade

Apply on databases that already have `portal.sp_session_operator_nav_tree` **without** the `node_path` column (pre–operator portal host) and on databases already at the new shape.

Do **not** hand-drop `portal.sp_session_operator_nav_tree` in production. Run the **full** official apply:

```bash
export PGHOST=… PGDATABASE=… PGUSER=… PGPASSWORD=… PGSSLMODE=…
bash workflow_engine/sql_pg/apply_schema.sh
```

`apply_schema.sh` is ordered and idempotent:

1. Applies all SQL through `portal_session_nav_api.sql` (uses `portal._drop_if_proc` when `RETURNS TABLE` shape changes, e.g. adding `node_path`).
2. Applies `portal_session_platform_api.sql`, `portal_operator_views_api.sql`, and the rest of the tree.
3. Finishes with **`database_gateway_roles.sql`**, which runs `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA portal TO goliath_portal` (required after any `DROP FUNCTION` / recreate).

Re-running `apply_schema.sh` on a database **already** at the new shape is safe (no manual steps).

`seed_platform_nav_tree.sql` is **not** part of `apply_schema.sh`. After apply, if the operator menu is empty, run it on the [database population](../database-population.md) path (after catalog seeds, and again after new organization scopes when needed).

### What ships in apply (operator portal)

- `portal_session_nav_api.sql` — `node_path` on `sp_session_operator_nav_tree`
- `portal_session_platform_api.sql` — `fn_session_operator_require`, session list wrappers
- `portal_operator_views_api.sql` — `portal.operator_view`, `portal.operator_dashboard`, `portal.operator_dashboard_widget`

## Product rules (documentation must state)

- The **official GoliathApp generic baseline database** stays clean; **product/domain evolution** belongs on **your deployment** (Path A) or on a **duplicated database / child app** (Path B). See [Operator portal guide](../operator-portal-guide.md#two-starting-paths-choose-deliberately).
- **Goliath-portal** (separate repository) is a **read-only UX reference** for chrome; it does not cap what GoliathApp operators can define or arrange.

## Tests (minimum bar)

- Client: `buildOperatorNavTree` / `nodePath` hrefs
- Host: `portal-node-registry` mapping
- Playwright: unauthenticated `/app` → login; `/api/navigation` 401 without session
- `mkdocs build --strict` includes operator guide in nav

## Related

- [Operator portal guide (end users)](../operator-portal-guide.md)
- [Platform visualization](../visualization.md)
- [Platform UI host](platform-host.md)
