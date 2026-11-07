-- NavTree → Meta bridge — POST-DEPLOY VERIFY (read-only)
-- Path: workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__99_verify_readonly.sql
-- Run after backfill (or on greenfield after sp_nav_register_node smoke).
-- Does not mutate data.

\echo '=== NavTree Meta verify (read-only) ==='

SELECT count(*) AS navtree_missing_metaobjid
FROM portal."NavTree"
WHERE "MetaObjID" IS NULL;

SELECT count(*) AS orphan_metaobj
FROM portal."NavTree" n
WHERE n."MetaObjID" IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM "Meta"."Objs" o WHERE o."ID" = n."MetaObjID");

SELECT count(*) AS nav_without_treenode
FROM portal."NavTree" n
WHERE n."MetaObjID" IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM "Meta"."TreeNodes" tn
    WHERE tn."ObjID" = n."MetaObjID"
      AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
  );

SELECT count(*) AS treenode_nav_mismatch
FROM portal."NavTree" n
JOIN "Meta"."TreeNodes" tn
  ON tn."ObjID" = n."MetaObjID"
 AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
WHERE n."MetaObjID" IS NULL;

SELECT n."ID", n."Caption", n."MetaObjID", tn."Path"::text AS meta_path
FROM portal."NavTree" n
LEFT JOIN "Meta"."TreeNodes" tn
  ON tn."ObjID" = n."MetaObjID"
 AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
ORDER BY n."Seq", n."ID"
LIMIT 50;
