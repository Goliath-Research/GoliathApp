-- Optional one-shot migration: backfill portal."NavTree".MetaObjID from Meta portal/NavNode + Parent link.
-- Not run by apply_schema.sh; safe to re-run (skips rows that already have MetaObjID).
-- Prerequisites: apply_schema.sh through portal_nav_meta.sql (or full SCRIPTS list on this branch).
--
-- Verify (report mode):
--   SELECT * FROM portal.sp_nav_backfill_meta(true);
-- Apply:
--   SELECT * FROM portal.sp_nav_backfill_meta(false);
-- Post-check:
--   SELECT count(*) AS missing FROM portal."NavTree" WHERE "MetaObjID" IS NULL;
--   SELECT count(*) AS nodes FROM "Meta"."TreeNodes" tn
--     JOIN portal."NavTree" n ON n."MetaObjID" = tn."ObjID";

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

SELECT action, count(*) FROM portal.sp_nav_backfill_meta(false) GROUP BY action ORDER BY action;

COMMIT;
