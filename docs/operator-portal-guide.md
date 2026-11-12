# Operator portal guide (end users)

This guide is for **operators and application owners** who sign in to the GoliathApp **platform host** (`apps/platform-host`) at `/app`. It explains how to grow your application using the signed-in portal, and how that relates to the two supported **starting paths** for any GoliathApp-based product.

Engineers implementing SQL, workers, and packaging should still read the [Adopter guide](adopter-guide.md). This page is written for people who work in the UI: classes, entities, views, and dashboards.

## What you see after sign-in

After Microsoft (or another registered) sign-in, you land in the **operator portal**:

| Area | What it is |
|------|------------|
| **Navigate (left)** | Official **NavTree** from `portal.sp_session_operator_nav_tree` — permission-filtered, nested, clickable (`node_path` routes). |
| **Main workspace** | Depends on the node you opened (see below). |
| **Header / footer** | Your name and email, sign out, active organization **scope**, and the **active role** for this session. |

### One role per session

A person may hold **multiple role grants** in an organization scope, but each portal session acts as **exactly one** selected role:

- **One grant** — the platform auto-selects that role when the session opens.
- **Several grants** — you choose a role on `/app/onboarding/select-role` before the NavTree loads.
- **No grants** — you see **No role assigned** (`/app/onboarding/no-role`) instead of an empty menu.

The active role is stored **server-side** in `RBAC.Session_Roles` via `portal.sp_session_set_active_role` (the host never trusts a browser-supplied role without verifying an active scoped grant). NavTree, semantic permissions, Meta class/object checks, and layered security evaluate **only that role**, not the union of all grants.

Use **Switch role** in the header to open the picker again; role changes are written to `portal.session_active_role_audit`.

The default home (`/app`) foregrounds the **Meta class hierarchy**: inherited GoliathApp classes plus any **semantic** classes your application added. Selecting a class opens the **Meta workbench** (class lineage, fields, **SchemaPropertyGrid**, nested property inspector, instance create/update when permitted).

Other NavTree sections (Administration, Workflows, Semantic layer, Configuration, Operations, Inventory, **Views & dashboards**) open **list screens**, **semantic views**, or **Meta** where the platform already has APIs. The same entities appear in **editors**, **list views**, and **dashboard widgets** — not separate products.

Public routes `/`, `/login`, and `/fixture` stay outside this shell; they are not the signed-in operator experience.

## Two starting paths (choose deliberately)

Every GoliathApp deployment should follow **one** of these patterns. Mixing product-specific evolution into the **shared clean baseline** database breaks the platform contract.

### Path A — Start from GoliathApp and extend in place

**When to use:** You already run (or will run) a GoliathApp database and portal host for **your** organization. You add **your** semantic namespaces, Meta classes, objects, NavTree nodes, views, and dashboards **on your deployment**, not on a communal “generic” reference database.

| Step | What you do | Where in the portal |
|------|-------------|---------------------|
| 1 | Sign in; confirm scope and NavTree | `/app` |
| 2 | Explore **inherited** platform classes | **Meta model** → hierarchy on `/app`, or **Classes** |
| 3 | Inspect or edit schema and instances | Open a class → Meta workbench + property grid |
| 4 | Register **your** semantic entities and map to Meta | **Semantic layer** (`/app/semantic`) — browse, register namespaces/entities/attributes; session APIs wrap the registry — see [Platform generic Meta](platform-generic-meta.md) |
| 5 | **Define views** on entities you care about | **Views** (`/app/views/list`) — save a view on a semantic request or Meta class |
| 6 | **Arrange dashboards** from saved views | **Dashboards** (`/app/views/dashboards`) |
| 7 | Subclass platform parents, add fields, NavTree, grants | **Meta** home authoring panel; **Administration → Navigation** for nodes and role grants; **Export as package SQL** for child repos — see [NavTree on Meta](nav-tree-meta.md) |
| 8 | Users, roles, class/object security | **Administration → Users** (sign-in status, invitations, scoped roles); **Roles**; Meta **Security** tab; [Layered security model](platform-layered-security.md) |

**Users workflow:** Create the person with their work email (no password — Entra/OIDC only). Grant a **scoped role** so NavTree and permissions apply; the table flags **None — grant role** until then. **Awaiting first … sign-in** means they should use **Copy sign-in link** and authenticate with the org provider; invitations are fulfilled on that first login when the verified email matches.

**Database rule:** Product and domain data for Path A live on **your** PostgreSQL instance (or your Neon branch / dedicated database). The official GoliathApp **reference** database used only to ship the platform stays a **clean generic baseline** — do not use it as your production tenant store.

### Path B — Define first, then duplicate GoliathApp as your base

**When to use:** You want a **fork or copy** of the platform (schema + seeds + host) as **your** application repository and database, then add everything you designed.

| Step | What you do | Notes |
|------|-------------|--------|
| 1 | Design Meta classes, semantic entities, workflows, and NavTree **on paper or in a dev copy** | Use a **throwaway** or team database, not the shared clean baseline |
| 2 | **Duplicate** GoliathApp: new repo fork or new DB from `apply_schema.sh` + platform seeds | See [Database population](database-population.md), [Schema apply](schema-apply.md) |
| 3 | Apply **your** SQL seeds (semantic namespace, Meta classes, actions, nav) | Layer 4 in population guide |
| 4 | Deploy **your** platform host (same packages, your `GoliathUiManifest`) | [Platform UI host](deploy/platform-host.md) |
| 5 | Sign in to **your** host `/app` and operate as in Path A | Views/dashboards stored per **scope** in `portal.operator_view` / `portal.operator_dashboard` |

**Database rule:** After duplication, **all** product work happens on the **copy** or **child database**. The upstream GoliathApp generic baseline remains unchanged for other adopters.

```mermaid
flowchart LR
  subgraph pathA["Path A: extend in place"]
    A1["Your GoliathApp DB"]
    A2["Portal /app"]
    A3["Add classes, views, dashboards"]
    A1 --> A2 --> A3
  end

  subgraph pathB["Path B: duplicate then extend"]
    B1["Design on dev copy"]
    B2["Fork repo + new DB"]
    B3["Portal on your base"]
    B1 --> B2 --> B3
  end

  BASE["Shared clean generic baseline DB"]
  BASE -.->|"do not put product data here"| pathA
  BASE -->|"copy schema + seeds"| B2
```

## Working with the class hierarchy (primary surface)

Child applications extend GoliathApp mainly by adding **semantic classes** and the **lower-level Meta classes** underneath them.

1. Open **Meta model** or the home hierarchy.
2. Find your namespace (child classes often use a prefix such as `your_app/…`).
3. Click a class to open the **workbench** — same editors as API-backed Meta routes (`/app/meta?class=…`).
4. Use **Objects**, **Fields**, **Relations**, and related NavTree leaves when you need a focused entry; they open the same workbench with sensible defaults.

Semantic entities registered in the portal layer link to Meta when `meta_class_id` is set. On **Semantic layer → Entities**, open the **Meta class** link to jump into the workbench for that backing class.

## Picking existing records (reference fields)

Fields that point at an existing record are never typed by hand. A JSON Schema property
annotated with `x-goliath-ref` renders as a **reference picker**: a search box plus a list of
matching rows. Pick a row to set the value.

```json
{ "type": "string",  "x-goliath-ref": "action" }
{ "type": "integer", "x-goliath-ref": { "kind": "workflow_version" } }
```

Built-in kinds: `action`, `meta_method`, `workflow_def`, `workflow_version`, `event_type`,
`cluster` (stores the cluster key), `cluster_id` (stores the numeric id), `worker`, `data_type`,
`meta_class`, `study`. Search runs server-side through `portal.sp_session_search_references`,
which checks the session's NavTree entitlements for each kind; the Meta catalog kinds
(`meta_class`, `meta_method`, `data_type`) also require `meta.schema.read`. Pickers work at every nesting depth. Nested inspectors show the full property path
as a breadcrumb, and Escape or **Back to …** closes only the innermost inspector.

## Views and dashboards (same entities as editors)

**Views** are saved presentation definitions on top of:

- A **semantic request** (`portal.sp_run_semantic_request`) — tabular read of organizations, inventory, or your registered requests, or  
- A **Meta class** — opens the workbench for inspect/edit.

**Dashboards** compose **saved views** in your organization scope (reorder, save arrangement). Widget previews use the same semantic runner as list screens; Meta-linked views point you to the workbench for edits.

| Task | NavTree | Route |
|------|---------|--------|
| Define a new view | Views → **Views** | `/app/views/list` |
| Run a saved view | Views list | Select view → preview |
| Create a dashboard | Views → **Dashboards** | `/app/views/dashboards` |
| Arrange widgets | Dashboard editor | Add views, reorder, **Save arrangement** |

Platform-shipped semantic requests (for example `core.list_organizations`, `inv.item.list`) appear in the view catalog; your application adds more via the semantic registry ([Semantic extensions](semantic-extensions.md)).

## Administration and platform surfaces

Under **Administration**, **Workflows**, **Configuration**, **Operations**, and **Inventory**, the portal opens **read/list** surfaces backed by existing `portal.sp_session_*` wrappers where implemented. These are the same PostgreSQL APIs operators have always had through stored procedures; the host does not bypass RBAC.

If a leaf has no host screen yet, the UI states that clearly — the NavTree node remains part of the inherited menu for child apps to extend.

## What this guide does not cover

- **Worker enrollment and claims** — gateway HTTP only; see [Workers](workers.md).
- **Applying SQL migrations** — privileged roles and CI; see [Database population](database-population.md).
- **OIDC and session configuration** — [Platform host P1 auth](deploy/platform-host-p1-auth.md).

## Related documentation

| Topic | Page |
|-------|------|
| Portal implementation plan and deliverables | [Platform host operator portal (plan)](deploy/platform-host-operator-portal.md) |
| Visualization packages and phases | [Platform visualization](visualization.md) |
| Engineer adoption | [Adopter guide](adopter-guide.md) |
| NavTree and Meta bridge | [Portal nav (Meta Tree)](nav-tree-meta.md) |
| Semantic registration | [Semantic extensions](semantic-extensions.md) |

## Editing workflow records

The Workflows pages **Actions**, **Domain programs**, **Workers and clusters** and **Event subscriptions**
open a typed property-grid inspector when you choose **Edit** on a row (or **New …**). Every field is a
typed control: references to existing rows use the searchable reference picker, lists and nested objects
open nested inspectors, and no field accepts typed or pasted JSON. Saving requires the page's navigation
entitlement plus the `platform.model.author` permission, and every save is recorded in
`portal.record_editor_audit`.

- **Actions are class methods.** The Actions page lists the effective methods of each Meta class, with
  inherited methods marked *inherited from …* and overriding methods marked *override*. Editing a method
  edits the Meta method and its typed parameters (each parameter type is picked from the existing data
  types); the bound `wf.workflow_action` catalog row is synchronised on save (capability, execution
  settings, output type, and — when the method declares parameters — the published parameters type and the
  action input schema). Choose **Override here** on an inherited method to give a subclass its own
  implementation. Parameter defaults are edited in a second grid generated from each parameter's data type
  (class-backed types open the class's own grid).
- **Domain programs** edit draft metadata only; the program body is preserved, and a new version starts
  from the body of the latest version. Published versions are immutable — save under a new version, then
  **Publish**.
- **Workers and clusters** edit cluster settings and worker enrollments (create, change IP, revoke).
  Starting or stopping workers is not available here.
- **Event subscriptions** pick the event type and workflow version from existing records and describe the
  payload filter as a list of key/value conditions.
