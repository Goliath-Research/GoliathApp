/*
  Meta object history (H2): "Meta"."ObjValuesHistory".

  Every change to a Meta object is recorded, for every class (history is not opt-in):
    object.create / object.delete / object.reclass   rows of "Meta"."Objs"
    values.insert / values.update / values.delete    rows of "Meta"."ObjValues" (one per class level)
    link.create / link.update / link.delete          instance rows of "Meta"."Links" (ObjID1 set)
    object.scope / object.unscope                    portal."ScopedMetaObjects" (tenant scope of the object)
    *.baseline                                       state captured when history was first installed

  The table is a platform ledger (platform_history_ledger.sql): append-only, hash-chained, verifiable.
  It has no foreign keys, so history outlives the objects it describes.

  Attribution: portal.fn_session_resolve stores the resolved session and user in the transaction
  settings goliath.actor_session_id / goliath.actor_user_id; every history row also carries txid,
  which joins to the audit ledgers written in the same transaction.

  See docs/history-and-audit.md (section 5).
*/

BEGIN;

CREATE TABLE IF NOT EXISTS "Meta"."ObjValuesHistory" (
  "HistoryID" bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "ChangeKind" text NOT NULL,
  "ObjID" integer NOT NULL,
  "ClassID" integer NULL,
  "LevelClassID" integer NULL,
  "LinkID" integer NULL,
  "MetaLinkID" integer NULL,
  "ObjID2" integer NULL,
  "ScopeID" integer NULL,
  "DataBefore" jsonb NULL,
  "DataAfter" jsonb NULL,
  "ActorUserID" integer NULL,
  "ActorSessionID" integer NULL,
  "DbRole" text NOT NULL DEFAULT current_user,
  "ChangedAtUtc" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "CK_Meta_ObjValuesHistory_Kind" CHECK ("ChangeKind" IN (
    'object.create', 'object.delete', 'object.reclass', 'object.baseline',
    'values.insert', 'values.update', 'values.delete', 'values.baseline',
    'link.create', 'link.update', 'link.delete', 'link.baseline',
    'object.scope', 'object.unscope', 'scope.baseline'
  ))
);

CREATE INDEX IF NOT EXISTS "IX_Meta_ObjValuesHistory_Obj"
  ON "Meta"."ObjValuesHistory" ("ObjID", "HistoryID");
CREATE INDEX IF NOT EXISTS "IX_Meta_ObjValuesHistory_Changed"
  ON "Meta"."ObjValuesHistory" ("ChangedAtUtc");

REVOKE ALL ON "Meta"."ObjValuesHistory" FROM PUBLIC;

CREATE OR REPLACE FUNCTION "Meta".fn_history_actor_user_id()
RETURNS integer
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('goliath.actor_user_id', true), '')::integer;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_history_actor_session_id()
RETURNS integer
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('goliath.actor_session_id', true), '')::integer;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_history_capture()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = "Meta", portal, pg_temp
AS $$
DECLARE
  v_kind text;
  v_uid integer := "Meta".fn_history_actor_user_id();
  v_sid integer := "Meta".fn_history_actor_session_id();
  v_class integer;
BEGIN
  IF TG_TABLE_NAME = 'Objs' THEN
    IF TG_OP = 'INSERT' THEN
      INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ClassID", "ActorUserID", "ActorSessionID")
      VALUES ('object.create', NEW."ID", NEW."ClassID", v_uid, v_sid);
    ELSIF TG_OP = 'DELETE' THEN
      INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ClassID", "ActorUserID", "ActorSessionID")
      VALUES ('object.delete', OLD."ID", OLD."ClassID", v_uid, v_sid);
    ELSIF NEW."ClassID" IS DISTINCT FROM OLD."ClassID" THEN
      INSERT INTO "Meta"."ObjValuesHistory" (
        "ChangeKind", "ObjID", "ClassID", "DataBefore", "DataAfter", "ActorUserID", "ActorSessionID"
      ) VALUES (
        'object.reclass', NEW."ID", NEW."ClassID",
        jsonb_build_object('ClassID', OLD."ClassID"), jsonb_build_object('ClassID', NEW."ClassID"),
        v_uid, v_sid
      );
    END IF;
    RETURN NULL;
  END IF;

  IF TG_TABLE_NAME = 'ObjValues' THEN
    IF TG_OP = 'UPDATE' AND NEW."Data" IS NOT DISTINCT FROM OLD."Data"
       AND NEW."ClassID" IS NOT DISTINCT FROM OLD."ClassID" THEN
      RETURN NULL;
    END IF;
    v_kind := CASE TG_OP WHEN 'INSERT' THEN 'values.insert' WHEN 'UPDATE' THEN 'values.update' ELSE 'values.delete' END;
    SELECT o."ClassID" INTO v_class
    FROM "Meta"."Objs" o
    WHERE o."ID" = CASE WHEN TG_OP = 'DELETE' THEN OLD."ObjID" ELSE NEW."ObjID" END;
    INSERT INTO "Meta"."ObjValuesHistory" (
      "ChangeKind", "ObjID", "ClassID", "LevelClassID", "DataBefore", "DataAfter", "ActorUserID", "ActorSessionID"
    ) VALUES (
      v_kind,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."ObjID" ELSE NEW."ObjID" END,
      v_class,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."ClassID" ELSE NEW."ClassID" END,
      CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD."Data" END,
      CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE NEW."Data" END,
      v_uid, v_sid
    );
    RETURN NULL;
  END IF;

  IF TG_TABLE_NAME = 'Links' THEN
    IF (TG_OP = 'DELETE' AND OLD."ObjID1" IS NULL) OR (TG_OP <> 'DELETE' AND NEW."ObjID1" IS NULL) THEN
      RETURN NULL;  -- class-level link definition, not an instance link
    END IF;
    IF TG_OP = 'UPDATE' AND to_jsonb(NEW) IS NOT DISTINCT FROM to_jsonb(OLD) THEN
      RETURN NULL;
    END IF;
    v_kind := CASE TG_OP WHEN 'INSERT' THEN 'link.create' WHEN 'UPDATE' THEN 'link.update' ELSE 'link.delete' END;
    INSERT INTO "Meta"."ObjValuesHistory" (
      "ChangeKind", "ObjID", "LinkID", "MetaLinkID", "ObjID2", "DataBefore", "DataAfter", "ActorUserID", "ActorSessionID"
    ) VALUES (
      v_kind,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."ObjID1" ELSE NEW."ObjID1" END,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."ID" ELSE NEW."ID" END,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."MetaLinkID" ELSE NEW."MetaLinkID" END,
      CASE WHEN TG_OP = 'DELETE' THEN OLD."ObjID2" ELSE NEW."ObjID2" END,
      CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) END,
      CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) END,
      v_uid, v_sid
    );
    RETURN NULL;
  END IF;

  IF TG_TABLE_NAME = 'ScopedMetaObjects' THEN
    IF TG_OP = 'UPDATE' AND NEW."ScopeID" IS NOT DISTINCT FROM OLD."ScopeID" THEN
      RETURN NULL;
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
      INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ScopeID", "ActorUserID", "ActorSessionID")
      VALUES ('object.unscope', OLD."ObjID", OLD."ScopeID", v_uid, v_sid);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
      INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ScopeID", "ActorUserID", "ActorSessionID")
      VALUES ('object.scope', NEW."ObjID", NEW."ScopeID", v_uid, v_sid);
    END IF;
    RETURN NULL;
  END IF;

  RETURN NULL;
END;
$$;

-- First install: capture the current state as a baseline so point-in-time reads start complete.
DO $baseline$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM "Meta"."ObjValuesHistory") THEN
    INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ClassID")
    SELECT 'object.baseline', o."ID", o."ClassID" FROM "Meta"."Objs" o ORDER BY o."ID";

    INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ClassID", "LevelClassID", "DataAfter")
    SELECT 'values.baseline', v."ObjID", o."ClassID", v."ClassID", v."Data"
    FROM "Meta"."ObjValues" v
    JOIN "Meta"."Objs" o ON o."ID" = v."ObjID"
    ORDER BY v."ObjID", v."ClassID";

    INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "LinkID", "MetaLinkID", "ObjID2", "DataAfter")
    SELECT 'link.baseline', l."ObjID1", l."ID", l."MetaLinkID", l."ObjID2", to_jsonb(l)
    FROM "Meta"."Links" l
    WHERE l."ObjID1" IS NOT NULL
    ORDER BY l."ID";

    INSERT INTO "Meta"."ObjValuesHistory" ("ChangeKind", "ObjID", "ScopeID")
    SELECT 'scope.baseline', s."ObjID", s."ScopeID" FROM portal."ScopedMetaObjects" s ORDER BY s."ObjID";
  END IF;
END
$baseline$;

DO $register$
BEGIN
  PERFORM portal.sp_ledger_register(
    'meta.obj_values_history', '"Meta"."ObjValuesHistory"', '"HistoryID"',
    'Every Meta object, value, instance link and scope change'
  );
END
$register$;

DROP TRIGGER IF EXISTS trg_meta_history_objs ON "Meta"."Objs";
CREATE TRIGGER trg_meta_history_objs
  AFTER INSERT OR UPDATE OR DELETE ON "Meta"."Objs"
  FOR EACH ROW EXECUTE FUNCTION "Meta".fn_history_capture();

DROP TRIGGER IF EXISTS trg_meta_history_values ON "Meta"."ObjValues";
CREATE TRIGGER trg_meta_history_values
  AFTER INSERT OR UPDATE OR DELETE ON "Meta"."ObjValues"
  FOR EACH ROW EXECUTE FUNCTION "Meta".fn_history_capture();

DROP TRIGGER IF EXISTS trg_meta_history_links ON "Meta"."Links";
CREATE TRIGGER trg_meta_history_links
  AFTER INSERT OR UPDATE OR DELETE ON "Meta"."Links"
  FOR EACH ROW EXECUTE FUNCTION "Meta".fn_history_capture();

DROP TRIGGER IF EXISTS trg_meta_history_scope ON portal."ScopedMetaObjects";
CREATE TRIGGER trg_meta_history_scope
  AFTER INSERT OR UPDATE OR DELETE ON portal."ScopedMetaObjects"
  FOR EACH ROW EXECUTE FUNCTION "Meta".fn_history_capture();

/* Chronological history of one object (values, lifecycle, links, scope). */
CREATE OR REPLACE FUNCTION "Meta".fn_obj_history(p_obj_id integer)
RETURNS TABLE (
  history_id bigint,
  ledger_seq bigint,
  change_kind text,
  class_id integer,
  level_class_id integer,
  link_id integer,
  obj_id2 integer,
  scope_id integer,
  data_before jsonb,
  data_after jsonb,
  actor_user_id integer,
  actor_session_id integer,
  db_role text,
  changed_at_utc timestamptz,
  txid bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", pg_temp
AS $$
  SELECT h."HistoryID", h.ledger_seq, h."ChangeKind", h."ClassID", h."LevelClassID", h."LinkID", h."ObjID2",
         h."ScopeID", h."DataBefore", h."DataAfter", h."ActorUserID", h."ActorSessionID", h."DbRole",
         h."ChangedAtUtc", h.txid
  FROM "Meta"."ObjValuesHistory" h
  WHERE h."ObjID" = p_obj_id
     OR (h."ObjID2" = p_obj_id AND h."ChangeKind" LIKE 'link.%')
  ORDER BY h."HistoryID";
$$;

/*
  Point-in-time read: each class level's values as they were at p_at_utc.
  Returns no row for a level that did not exist (or had been deleted) at that time.
*/
CREATE OR REPLACE FUNCTION "Meta".fn_obj_values_as_of(p_obj_id integer, p_at_utc timestamptz)
RETURNS TABLE (level_class_id integer, data jsonb, as_of_history_id bigint)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", pg_temp
AS $$
  SELECT x.level_class_id, x.data, x.history_id
  FROM (
    SELECT DISTINCT ON (h."LevelClassID")
      h."LevelClassID" AS level_class_id,
      h."DataAfter" AS data,
      h."ChangeKind" AS kind,
      h."HistoryID" AS history_id
    FROM "Meta"."ObjValuesHistory" h
    WHERE h."ObjID" = p_obj_id
      AND h."LevelClassID" IS NOT NULL
      AND h."ChangedAtUtc" <= p_at_utc
    ORDER BY h."LevelClassID", h."HistoryID" DESC
  ) x
  WHERE x.kind <> 'values.delete'
  ORDER BY x.level_class_id;
$$;

/*
  Merged document as of a time (all class levels), the historical counterpart of
  "Meta".fn_merged_obj_document. Each field is declared on exactly one class level.
*/
CREATE OR REPLACE FUNCTION "Meta".fn_merged_obj_document_as_of(p_obj_id integer, p_at_utc timestamptz)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", pg_temp
AS $$
  SELECT COALESCE(jsonb_object_agg(kv.key, kv.value), '{}'::jsonb)
  FROM "Meta".fn_obj_values_as_of(p_obj_id, p_at_utc) a
  CROSS JOIN LATERAL jsonb_each(COALESCE(a.data, '{}'::jsonb)) kv;
$$;

/* Tenant scope an object had most recently (also after deletion). */
CREATE OR REPLACE FUNCTION "Meta".fn_obj_history_scope_id(p_obj_id integer)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", pg_temp
AS $$
  SELECT h."ScopeID"
  FROM "Meta"."ObjValuesHistory" h
  WHERE h."ObjID" = p_obj_id AND h."ChangeKind" IN ('object.scope', 'object.unscope', 'scope.baseline')
  ORDER BY h."HistoryID" DESC
  LIMIT 1;
$$;

/*
  Session read of an object's history. A live object follows the same read checks as
  sp_session_meta_obj_get. A deleted object's history is readable in the scope it last belonged to
  by a session holding meta.object.read there.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_history(
  p_session_token text,
  p_obj_id integer
)
RETURNS TABLE (
  history_id bigint,
  ledger_seq bigint,
  change_kind text,
  class_name text,
  level_class_name text,
  link_id integer,
  obj_id2 integer,
  data_before jsonb,
  data_after jsonb,
  actor_user_id integer,
  actor_email text,
  changed_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_scope integer;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance(p_session_token, 'meta.object.read') LIMIT 1;

  IF EXISTS (SELECT 1 FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id) THEN
    PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
    PERFORM portal.fn_meta_assert_object_action(
      v_ctx.user_id, v_ctx.active_scope_id, p_obj_id, 'read', v_ctx.session_id
    );
  ELSE
    v_scope := "Meta".fn_obj_history_scope_id(p_obj_id);
    IF v_scope IS NULL OR v_scope IS DISTINCT FROM v_ctx.active_scope_id THEN
      PERFORM portal.fn_semantic_raise('GS404', 'object history not found in active scope');
    END IF;
  END IF;

  RETURN QUERY
  SELECT h.history_id, h.ledger_seq, h.change_kind,
         c."Name"::text, lc."Name"::text,
         h.link_id, h.obj_id2, h.data_before, h.data_after,
         h.actor_user_id, u.email::text, h.changed_at_utc
  FROM "Meta".fn_obj_history(p_obj_id) h
  LEFT JOIN "Meta"."Classes" c ON c."ID" = h.class_id
  LEFT JOIN "Meta"."Classes" lc ON lc."ID" = h.level_class_id
  LEFT JOIN "RBAC"."Users" u ON u."ID" = h.actor_user_id
  ORDER BY h.history_id;
END;
$$;

-- Raw history readers bypass tenant checks; only the owner and session APIs may call them.
REVOKE EXECUTE ON FUNCTION "Meta".fn_obj_history(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION "Meta".fn_obj_values_as_of(integer, timestamptz) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION "Meta".fn_merged_obj_document_as_of(integer, timestamptz) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION "Meta".fn_obj_history_scope_id(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION "Meta".fn_history_capture() FROM PUBLIC;

-- Legacy parity hook: history is platform-wide now.
CREATE OR REPLACE FUNCTION "Meta".spclasscreatehistorysql(p_class_id int)
RETURNS text LANGUAGE plpgsql AS $$
BEGIN
  RETURN '-- History is recorded for every class in "Meta"."ObjValuesHistory" (meta_objvalues_history.sql).';
END;
$$;

COMMENT ON COLUMN "Meta"."Classes"."HasHistory" IS
  'Legacy flag. Object history is always recorded in "Meta"."ObjValuesHistory" regardless of this value.';

COMMIT;
