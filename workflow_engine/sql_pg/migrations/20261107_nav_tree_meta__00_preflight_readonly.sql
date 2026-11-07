-- NavTree → Meta bridge — PREFLIGHT (read-only)
-- Path: workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__00_preflight_readonly.sql
-- Run after apply_schema.sh on the target database; before any backfill.
-- Does not BEGIN a write transaction; SELECT only.

\echo '=== NavTree Meta preflight (read-only) ==='

SELECT
  CASE WHEN portal.fn_nav_node_class_id() IS NOT NULL THEN 'ok' ELSE 'MISSING' END
    AS portal_navnode_class,
  CASE WHEN portal.fn_nav_parent_metalink_id() IS NOT NULL THEN 'ok' ELSE 'MISSING' END
    AS parent_metalink,
  to_regclass('portal."NavTree"') IS NOT NULL AS navtree_table,
  EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'portal'
      AND table_name = 'NavTree'
      AND column_name = 'MetaObjID'
  ) AS metobjid_column;

SELECT count(*) AS navtree_total FROM portal."NavTree";

SELECT count(*) AS navtree_missing_metaobjid
FROM portal."NavTree"
WHERE "MetaObjID" IS NULL;

SELECT count(*) AS role2node_grants FROM portal."Role2Node";

SELECT "ID", "ParentID", "Caption", "MetaObjID"
FROM portal."NavTree"
ORDER BY "Seq", "ID"
LIMIT 25;
