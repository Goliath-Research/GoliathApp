# GoliathApp self-modeling plan

GoliathApp must **dogfood** the same Meta class hierarchy child apps use: every Goliath-owned concept becomes a **`platform/*` (or engine) Meta class** with objects, links, generic editors, and class/object security—except the Meta engine’s own tables and **derived caches** rebuilt from Meta.

## Modeling principle

| Allowed outside `Meta.Objs` | Notes |
|-----------------------------|--------|
| Meta engine tables | `Classes`, `Fields`, `Objs`, `ObjValues`, `Links`, `LinkTypes`, closure, methods, collections |
| Derived caches / MVs | e.g. `portal.security_grant_cache`, `portal.mv_security_effective_grants`, hierarchy closure, compiled semantic views |
| Runtime execution stores | Workflow **instance** state (until Phase W); session token hashes |
| Everything else | Target: Meta class + objects |

**Authority:** `platform/*` **definitions** and platform-owned catalog objects are **`god_architect`** only ([God Architect role](platform-god-architect.md)). Tenants manage **instance data** (users, grants, invitations) via `platform.security.admin` in scope.

## Inventory (current → target)

Legend: **Risk** = migration difficulty (L/M/H). **Cache** = needs materialized / hot path.

### RBAC & onboarding (Phase S — in flight)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `RBAC.Users` | `platform/User` | `platform/Person` | Grant MV | M — PR B/C |
| `RBAC.Roles` | `platform/Role` | `platform/Entity` | Permission join → Meta links | M |
| `RBAC.Permissions` | `platform/Permission` | `platform/Entity` | — | M |
| `RBAC.UserRoleGrants` | `platform/RoleGrant` | `platform/Entity` | `mv_security_effective_grants` | H |
| `RBAC.ExternalIdentities` | `platform/ExternalIdentity` | `platform/Entity` | — | M |
| `Onboarding.Invitations` | `platform/Invitation` | `platform/Entity` | — | M |
| `RBAC.IdentityProviders` | `platform/IdentityProvider` | `platform/Entity` | — | M |
| `RBAC.ScopeIdentityProviders` | link objects | — | — | M |
| `RBAC.Scopes` | extend `platform/Organization` scope facet | `platform/Party` | — | H |
| `RBAC.Sessions` / `SessionTokens` | `platform/Session` (runtime) | — | token cache | H |
| `RBAC.Session_Roles` | session facet on `platform/Session` | — | — | M |
| `god_architect` (global role) | `platform/Role` + GLOBAL grant; operator perms/nav = `organization_admin` ⊕ `platform.model.architect` (`sp_sync_god_architect_operator_entitlements`) | — | MV | L — shipped |

### Portal shell & navigation (Phase N)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `portal.NavTree` | `portal/NavNode` instances + tree links | existing Meta | Nav presentation MV | H |
| `portal.NodeInfos` | fields on `portal/NavNode` | — | — | M |
| `portal.Role2Node` | `platform/NavGrant` or link type | — | role-nav join MV | H |
| `portal.Organizations` | `platform/Organization` | `platform/Party` | — | M |
| `portal.OrganizationMembers` | link `MemberOf` | — | — | L |

### Operator views (Phase V)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `portal.operator_view` | `platform/OperatorView` | `platform/Document` | — | M |
| `portal.operator_dashboard` | `platform/Dashboard` | `platform/Document` | — | M |
| `portal.operator_dashboard_widget` | child objects / collection | — | — | M |

### Semantic layer (Phase E)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `portal.semantic_namespace` | `platform/SemanticNamespace` | `platform/Entity` | catalog MV | M |
| `portal.semantic_entity` | `platform/SemanticEntity` | — | — | M |
| `portal.semantic_attribute` | collection on entity | — | — | M |
| `portal.semantic_request` | `platform/SemanticRequest` | — | — | M |
| `portal.semantic_action_binding` | link | — | — | L |
| `portal.semantic_nav_binding` | link | — | — | L |

### Workflow engine (Phase W)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `wf.workflow_def` / `workflow_version` | `platform/WorkflowDefinition` | `platform/Entity` | — | H |
| `wf.workflow_node` / `workflow_edge` | graph via Links | — | compiler cache | H |
| `wf.workflow_action` | `platform/WorkflowAction` | — | dispatch index | H |
| `wf.data_type` | already mirrored in Meta | — | — | M |
| `wf.workflow_instance` | **runtime** (optional Meta mirror) | — | execution hot path | H |
| `wf.node_execution` | runtime | — | H |
| Event plane tables | `platform/EventType`, `platform/Event` | — | ingest index | H |

### Configuration & operations (Phase C)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `cfg.site`, `cfg.study`, `cfg.pipeline_profile` | `platform/Site`, etc. | product baseline | — | M |
| `cfg.credential`, `cfg.storage_*` | `platform/Credential`, `platform/StorageProfile` | — | secret cache (not Meta) | H |
| `cfg.study_start_request` | `platform/StudyStartRequest` | — | queue index | M |
| `Contract.*` | `platform/Contract` family | `platform/Entity` | — | M |

### Inventory module (Phase I)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| `inv.item`, `inv.stock_lot`, `inv.purchase_order`, … | `platform/Item`, `platform/Lot`, … | existing generic baseline | semantic + stock MVs | M |

### Security overlays (stay derived)

| Store | Role |
|-------|------|
| `portal.MetaClassRoleAccess` / `MetaObjectAccess` | Rules; migrate to Meta policy objects later |
| `portal.security_grant_cache` | Derived from `platform/RoleGrant` |
| Layered security audit tables | Append-only audit (may become `platform/AuditEvent`) |

### IoT / device adapters (Phase D)

| Legacy | Target class | Parent | Cache | Risk |
|--------|--------------|--------|-------|------|
| Worker enrollment, device bindings | `platform/DeviceAdapter`, `platform/WorkerBinding` | — | wake hints | H |

## PR sequencing (after security PR B/C)

| PR | Scope | Deploy / CI |
|----|--------|-------------|
| **S** (B/C) | Security Meta + enforcement + God Architect | `verify_security_meta_migration.sh`, upgrade-path pytest |
| **N1** | NavTree + Role2Node as Meta; god_architect-only platform nav writes | `seed_platform_nav_tree` idempotent + nav pytest |
| **V1** | Operator views/dashboards as Meta documents | host e2e |
| **E1** | Semantic catalog as Meta; platform namespace god-only | semantic pytest |
| **W1** | Workflow **definitions** as Meta; instances remain runtime | compiler + worker tests |
| **C1** | cfg / contract catalog migration | study pipeline tests |
| **I1** | inv alignment to generic baseline views | inv module tests |
| **D1** | Device adapter catalog | adapter integration tests |
| **X** | Legacy table archive + documented drops | full stack apply twice on Neon branch clone |

Each phase: **Neon backup branch → `apply_schema.sh` only → idempotent migrate proc → verify script → pytest upgrade path**.

## Legacy drop order (high level)

1. Stop dual-write to RBAC security tables (enforcement PR C).
2. Archive `RBAC.UserRoleGrants`, `ExternalIdentities`, `Onboarding.Invitations` (see [Platform security Meta](platform-security-meta.md)).
3. Nav / semantic / wf **catalog** tables after Meta read paths are sole source.
4. Retain execution and session runtime tables until replaced or proven redundant.

## Related

- [Platform security Meta](platform-security-meta.md)
- [God Architect role](platform-god-architect.md)
- [Platform generic Meta](platform-generic-meta.md)
- [Database population](database-population.md)
