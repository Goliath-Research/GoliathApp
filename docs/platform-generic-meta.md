# Platform generic Meta hierarchy

GoliathApp ships a **small, product-neutral class hierarchy** in `workflow_engine/sql_pg/platform_generic_meta_baseline.sql` (applied by `apply_schema.sh`). Child applications **subclass** these FQNs in their own namespace (for example `your_app/Customer` extends `platform/Organization`). The official generic baseline database stays clean; product classes live on **your deployment** or a **forked copy** — see [Operator portal guide](operator-portal-guide.md).

## Classes (baseline)

| FQN | Role |
|-----|------|
| `platform/Entity` | Abstract root for platform-modeled things |
| `platform/Party` | Party abstraction |
| `platform/Organization` | Org / customer / sponsor style party |
| `platform/Person` | Individual party |
| `platform/Item` | Abstract item |
| `platform/Material` | Physical or logical material / sample-style item |
| `platform/Location` | Location abstraction |
| `platform/Site` | Facility or site under location |
| `platform/Document` | Document / record header |
| `platform/Event` | Event abstraction |
| `platform/Activity` | Activity under event |
| `platform/Batch` | Batch / run group |
| `platform/Lot` | Lot under batch |
| `platform/Measurement` | Measurement abstraction |
| `platform/Observation` | Single observation / measurement row |

Each concrete leaf above includes a required **`Label`** field (`portal/nav/Caption`).

Security modeling (users, roles, grants) is documented in [Platform security Meta](platform-security-meta.md) — classes `platform/User`, `platform/Role`, `platform/Permission`, `platform/RoleGrant`, `platform/ExternalIdentity`, `platform/Invitation`.

## How child apps should extend

1. Sign in to the operator portal → **Meta class hierarchy** or **Semantic layer**.
2. **Create subclass** under the nearest platform parent (session API `sp_session_meta_class_create`).
3. **Add fields**, register **semantic entity** mapped to the Meta class, and expose **views** on the new class or semantic request.
4. Use **Export as package SQL** to download idempotent snippets for a child repository migration.

### Documentation examples (not product names in code)

| Child product concept | Subclass of |
|----------------------|-------------|
| Customer | `platform/Organization` |
| Patient | `platform/Person` |
| Sample | `platform/Material` |
| Lab batch | `platform/Batch` |
| Disease term | `platform/Entity` or a dedicated classification child you define |

The [inventory module](inventory-module.md) (`inv` schema + semantic namespace) remains the reference for **Item**-style relational inventory; Meta `platform/Material` is the cross-domain OOP anchor for semantic registration.

## Permissions

Model authoring requires **`platform.model.author`** (granted to `organization_admin` via `seed_platform_nav_tree.sql`) plus `meta.schema.read` and an **active organization scope** on the session.

## SQL entry points

Session-bound authoring: `workflow_engine/sql_pg/portal_session_model_authoring_api.sql` (`portal.sp_session_meta_class_create`, `portal.sp_session_semantic_register_entity`, NavTree and RBAC grants, `portal.sp_session_export_model_package`).
