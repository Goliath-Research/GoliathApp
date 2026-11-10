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
| **End-user operator guide (two starting paths)** | **Required — shipped with portal PR** | [operator-portal-guide.md](../operator-portal-guide.md) |
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
| P6 | Multi-child adoption | Pending |

Updating [visualization.md](../visualization.md) and this plan together is mandatory when portal scope changes.

## SQL apply (operator features)

After pulling portal SQL, run the platform apply path ([schema-apply.md](../schema-apply.md)) so these are present:

- `portal_session_platform_api.sql` — `fn_session_operator_require`, session list wrappers
- `portal_operator_views_api.sql` — `portal.operator_view`, `portal.operator_dashboard`, `portal.operator_dashboard_widget`

Then run **`seed_platform_nav_tree.sql`** on populated databases if not already applied ([database-population.md](../database-population.md)).

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
