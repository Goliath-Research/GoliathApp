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

1. Apply schema through `portal_nav_meta.sql`.
2. Report: `SELECT * FROM portal.sp_nav_backfill_meta(true);`
3. Apply: `SELECT * FROM portal.sp_nav_backfill_meta(false);`  
   Or run `workflow_engine/sql_pg/migrations/20261107_nav_tree_meta_backfill.sql`.
4. Verify:

```sql
SELECT count(*) AS missing_meta FROM portal."NavTree" WHERE "MetaObjID" IS NULL;
SELECT n."ID", n."Caption", n."MetaObjID", v.meta_tree_path::text
FROM portal."vNavTreeMeta" v
JOIN portal."NavTree" n ON n."ID" = v."ID"
ORDER BY n."Seq", n."ID"
LIMIT 50;
```

## Inheritance and population

- **Platform** owns `portal/NavNode`, tree maintenance, and the bridge; apply order is in [schema-apply.md](schema-apply.md).
- **Descendants** extend navigation only via `portal.sp_nav_register_node` and Role2Node (see [adopter-guide.md](adopter-guide.md), [database-population.md](database-population.md)).
- **Semantic** `portal.semantic_nav_binding.nav_tree_id` still references `portal."NavTree"."ID"`.

## Downstream apps

Descendant application plans assume **additive** NavTree nodes and Role2Node grants. No framework rebuild is required in child repositories after this platform change; adopt the new apply list and run backfill once per environment.

## Workers

Workers remain **gateway-only**; navigation is portal/DB only.
