# Portal navigation on Meta Tree links

Platform navigation is modeled as **Meta `portal/NavNode`** objects connected by the hierarchical **`Parent`** meta link (`IsHierarchical = true`). Tree paths live in `"Meta"."TreeNodes"` (ltree, maintained by `meta_model_tree_maintenance.sql`). Legacy **`portal."NavTree"`** and **`portal."Role2Node"`** remain the compatibility surface for RBAC and descendant applications: each shell row stores **`MetaObjID`** after registration or backfill.

## Contract (do not duplicate)

| Piece | Source |
| --- | --- |
| Catalog types `meta/Tree`, `meta/TreeRef` | `meta_model_phase_c.sql` |
| Path maintenance, cycle rejection | `meta_model_tree_maintenance.sql` |
| Platform class `portal/NavNode`, fields, `Parent` link | `portal_nav_meta.sql` (`portal.sp_nav_ensure_meta_catalog`) |
| Descendant registration API (unchanged signature) | `portal.sp_nav_register_node` → Meta + legacy row |
| RBAC nav query | `RBAC.spgetusernavtree` (still reads `portal."NavTree"`) |
| Entitlement APIs | `portal.sp_grant_role_nav_node`, etc. (`portal_rbac_api.sql`) |

**Child apps** keep calling `portal.sp_nav_register_node` and RBAC grants on **`NodeId`** (`portal."NavTree"."ID"`). They do not insert into `Meta` directly unless defining new Meta classes.

## Registration (greenfield)

After `apply_schema.sh`:

```sql
SELECT node_id FROM portal.sp_nav_register_node(
  NULL::integer,           -- parent NavTree.ID, or NULL for root
  'My module'::text,
  10::smallint,
  NULL::integer,           -- InfoID (optional)
  '/my-module'::text,
  '0010'::text
);
-- Then grant: CALL portal.sp_grant_role_nav_node(...);
```

Each call creates a `portal/NavNode` object, a `Parent` link when `p_parent_id` is set, a `TreeNodes` path, and a `portal."NavTree"` row with `MetaObjID`.

## Upgrades / backfill (non-destructive)

Legacy rows without `MetaObjID` continue to work until backfilled. **`portal."NavTree"` is not dropped.**

Operator script index (exact repo paths): `workflow_engine/sql_pg/migrations/README.md`. Backup-first deploy order: [deploy-nav-tree-migration.md](deploy-nav-tree-migration.md).

| Order | File (under repo root) | Read-only? |
| --- | --- | --- |
| DDL | `workflow_engine/sql_pg/apply_schema.sh` | DDL only |
| 1 | `workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__00_preflight_readonly.sql` | **Yes** (`SELECT` only) |
| 2 | `SELECT * FROM portal.sp_nav_backfill_meta(true);` | **No** — see below |
| 3 | `workflow_engine/sql_pg/migrations/20261107_nav_tree_meta_backfill.sql` | No (nav backfill; idempotent) |
| 4 | `workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__99_verify_readonly.sql` | **Yes** (`SELECT` only) |

**Dry-run vs read-only SQL:** `sp_nav_backfill_meta(true)` returns a `would_create` report and does **not** assign `MetaObjID` or insert navigation `Meta.Objs`/links. It always calls `portal.sp_nav_ensure_meta_catalog()` first, which may **write** the platform `portal/NavNode` catalog (`Meta`, `wf.data_type`, related views). Treat it like a **mutation-authorized** step (backup first), not a substitute for the `*_preflight_readonly.sql` / `*_verify_readonly.sql` scripts.

Quick ad-hoc checks:

```sql
SELECT count(*) AS missing_meta FROM portal."NavTree" WHERE "MetaObjID" IS NULL;
SELECT n."ID", n."Caption", n."MetaObjID", v.meta_tree_path::text
FROM portal."vNavTreeMeta" v
JOIN portal."NavTree" n ON n."ID" = v."ID"
ORDER BY n."Seq", n."ID"
LIMIT 50;
```

## Inheritance and population

- **Platform** owns `portal/NavNode`, tree maintenance, the bridge, and the **baseline NavTree** seed `workflow_engine/sql_pg/seed_platform_nav_tree.sql` (run after `apply_schema.sh` and Python catalog seeds — see [database-population.md](database-population.md)). That script registers administration (users, RBAC, organizations), Meta/OOP (classes, objects, fields, relations, methods, data types, trees), workflows, semantic layer, configuration, operations, views/dashboards, and optional inventory — all under `/app/…` paths aligned with the platform host.
- **Descendants** **extend** navigation only: additional `portal.sp_nav_register_node` calls and Role2Node grants for domain modules (see [adopter-guide.md](adopter-guide.md)). They do not own the baseline tree.
- **Semantic** `portal.semantic_nav_binding.nav_tree_id` still references `portal."NavTree"."ID"`.

## Downstream apps

Descendant application plans assume **additive** NavTree nodes and Role2Node grants. No framework rebuild is required in child repositories after this platform change; adopt the new apply list and run backfill once per environment.

### Meta object screens (generic host fallback)

Child apps register NavTree leaves that open the platform host **Meta instance workbench** (list / create / edit via SchemaPropertyGrid) without shipping React code:

| Field | Value |
| --- | --- |
| `portal."NodeInfos"."FrameKey"` | `meta_object` |
| `portal."NodeInfos"."Name"` | `platform.nav.meta_object:<MetaClassName>` (e.g. `platform.nav.meta_object:childapp/Sample`) |
| `portal."NavTree"."NodePath"` | App-chosen URL under `/app/...` |

Explicit routes in the platform host registry (baseline `/app/meta/*`, admin, workflows, …) **take precedence** over this fallback. The host resolves the screen from the signed-in operator NavTree row for the current `node_path`.

## Workers

Workers remain **gateway-only**; navigation is portal/DB only.
