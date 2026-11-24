/*
  Electronic signatures (H4).

  platform/ElectronicSignature binds a signer, a meaning, a time and a SHA-256 hash of the signed
  content to one record (a Meta object or a workflow run). Signatures are Meta objects, so they are
  also kept in "Meta"."ObjValuesHistory"; once written they cannot be changed or deleted.

  platform/SignatureMeaning lists what a signature may mean (for example review or approval). The
  platform seeds no meanings: God Architect creates the ones an installation uses.

  Signing requires a recent authentication (RBAC.Sessions.AuthenticatedAtUtc within
  portal_signature_reauth_seconds, default 300). Signed records cannot be deleted or purged.

  See docs/history-and-audit.md (section 7).
*/

BEGIN;

DO $signature_classes$
DECLARE
  v_text bigint;
  v_int bigint;
  v_ts bigint;
  v_class int;
BEGIN
  SELECT id INTO v_text FROM wf.data_type WHERE name = 'platform/security/Text' AND version = '1.0';
  SELECT id INTO v_int FROM wf.data_type WHERE name = 'platform/security/Integer' AND version = '1.0';
  SELECT id INTO v_ts FROM wf.data_type WHERE name = 'platform/security/Timestamp' AND version = '1.0';

  INSERT INTO "Meta"."Classes" ("Name", "ParentID")
  SELECT v.name, (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Entity')
  FROM (VALUES ('platform/SignatureMeaning'), ('platform/ElectronicSignature')) AS v(name)
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = v.name);
  PERFORM "Meta".sp_backfill_all_class_hierarchies();

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/SignatureMeaning';
  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
  SELECT v_class, f.name, f.type_id, f.req, f.descr
  FROM (VALUES
    ('Label', v_text, true, 'Display label, shown with every signature'),
    ('Meaning', v_text, true, 'Stable code used when signing'),
    ('Description', v_text, false, 'What the signer attests')
  ) AS f(name, type_id, req, descr)
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ElectronicSignature';
  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
  SELECT v_class, f.name, f.type_id, f.req, f.descr
  FROM (VALUES
    ('Label', v_text, true, 'Display label'),
    ('TargetKind', v_text, true, 'meta.object or wf.instance'),
    ('TargetKey', v_text, true, 'Id of the signed record'),
    ('Meaning', v_text, true, 'Meaning code'),
    ('MeaningLabel', v_text, true, 'Meaning label at signing time'),
    ('MeaningObjID', v_int, true, 'platform/SignatureMeaning object'),
    ('SignerUserID', v_int, true, 'Signer user id'),
    ('SignerFullName', v_text, true, 'Signer full name at signing time'),
    ('SignerEmail', v_text, true, 'Signer email at signing time'),
    ('SignedAtUtc', v_ts, true, 'When the signature was made'),
    ('ContentSha256', v_text, true, 'SHA-256 of the canonical signed content'),
    ('Comment', v_text, false, 'Signer comment'),
    ('SessionID', v_int, true, 'Portal session used to sign')
  ) AS f(name, type_id, req, descr)
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);

  EXECUTE format(
    'CREATE INDEX IF NOT EXISTS "IX_Meta_ObjValues_SignatureTarget" ON "Meta"."ObjValues" '
    '(("Data" ->> ''TargetKind''), ("Data" ->> ''TargetKey'')) WHERE "ClassID" = %s',
    v_class
  );
END
$signature_classes$;

SELECT portal.sp_platform_god_architect_class_acl_sync();

CREATE OR REPLACE FUNCTION portal.fn_signature_class_id()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", pg_temp
AS $$
  SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ElectronicSignature';
$$;

CREATE OR REPLACE FUNCTION portal.fn_signature_exists_for_target(p_target_kind text, p_target_key text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = "Meta", portal, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM "Meta"."ObjValues" v
    WHERE v."ClassID" = portal.fn_signature_class_id()
      AND v."Data" ->> 'TargetKind' = p_target_kind
      AND v."Data" ->> 'TargetKey' = p_target_key
  );
$$;

/*
  Canonical content of a signable record. Timestamps are rendered in UTC so the hash does not depend
  on the session time zone.
*/
CREATE OR REPLACE FUNCTION portal.fn_signature_content(p_target_kind text, p_target_key text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
SET "TimeZone" = 'UTC'
AS $$
DECLARE
  v_id bigint;
  v_doc jsonb;
BEGIN
  IF p_target_key IS NULL OR p_target_key !~ '^[0-9]+$' THEN
    RETURN NULL;
  END IF;
  v_id := p_target_key::bigint;

  IF p_target_kind = 'meta.object' THEN
    SELECT jsonb_build_object(
      'kind', 'meta.object',
      'obj_id', o."ID",
      'class', c."Name",
      'document', "Meta".fn_merged_obj_document(o."ID")
    ) INTO v_doc
    FROM "Meta"."Objs" o
    JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
    WHERE o."ID" = v_id;
    RETURN v_doc;
  END IF;

  IF p_target_kind = 'wf.instance' THEN
    SELECT jsonb_build_object(
      'kind', 'wf.instance',
      'workflow_instance_id', wi.id,
      'workflow', wd.name,
      'workflow_version_id', wi.workflow_version_id,
      'status', wi.status,
      'completed_at_utc', wi.completed_at_utc,
      'nodes', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
          'node_execution_id', ne.id,
          'workflow_node_id', ne.workflow_node_id,
          'status', ne.status,
          'attempt_no', ne.attempt_no,
          'result_code', ne.result_code,
          'output', ne.output_json
        ) ORDER BY ne.id)
        FROM wf.node_execution ne
        WHERE ne.workflow_instance_id = wi.id
      ), '[]'::jsonb)
    ) INTO v_doc
    FROM wf.workflow_instance wi
    JOIN wf.workflow_version wv ON wv.id = wi.workflow_version_id
    JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
    WHERE wi.id = v_id;
    RETURN v_doc;
  END IF;

  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_signature_content_sha256(p_target_kind text, p_target_key text)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT encode(sha256(convert_to(c::text, 'UTF8')), 'hex')
  FROM (SELECT portal.fn_signature_content(p_target_kind, p_target_key) AS c) x
  WHERE x.c IS NOT NULL;
$$;

/* valid | content_changed | target_missing */
CREATE OR REPLACE FUNCTION portal.fn_signature_verify(p_signature_obj_id integer)
RETURNS TABLE (signature_obj_id integer, status text, stored_sha256 text, current_sha256 text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_data jsonb;
  v_now text;
BEGIN
  SELECT v."Data" INTO v_data
  FROM "Meta"."ObjValues" v
  WHERE v."ObjID" = p_signature_obj_id AND v."ClassID" = portal.fn_signature_class_id();
  IF v_data IS NULL THEN
    RETURN;
  END IF;
  v_now := portal.fn_signature_content_sha256(v_data ->> 'TargetKind', v_data ->> 'TargetKey');
  RETURN QUERY SELECT
    p_signature_obj_id,
    CASE
      WHEN v_now IS NULL THEN 'target_missing'
      WHEN v_now = v_data ->> 'ContentSha256' THEN 'valid'
      ELSE 'content_changed'
    END,
    v_data ->> 'ContentSha256',
    v_now;
END;
$$;

/* Signatures are immutable, and a signed Meta object cannot be deleted. */
CREATE OR REPLACE FUNCTION portal.fn_signature_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_sig_class integer := portal.fn_signature_class_id();
  v_obj integer;
  v_class integer;
BEGIN
  IF TG_TABLE_NAME = 'ObjValues' THEN
    IF OLD."ClassID" = v_sig_class THEN
      RAISE EXCEPTION 'electronic signature % cannot be changed or removed', OLD."ObjID" USING ERRCODE = 'GS409';
    END IF;
  ELSE
    v_obj := OLD."ID";
    v_class := OLD."ClassID";
    IF v_class = v_sig_class THEN
      RAISE EXCEPTION 'electronic signature % cannot be changed or removed', v_obj USING ERRCODE = 'GS409';
    END IF;
    IF TG_OP = 'DELETE' AND portal.fn_signature_exists_for_target('meta.object', v_obj::text) THEN
      RAISE EXCEPTION 'object % is electronically signed and cannot be deleted', v_obj USING ERRCODE = 'GS409';
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_signature_guard_values ON "Meta"."ObjValues";
CREATE TRIGGER trg_signature_guard_values
  BEFORE UPDATE OR DELETE ON "Meta"."ObjValues"
  FOR EACH ROW EXECUTE FUNCTION portal.fn_signature_guard();
DROP TRIGGER IF EXISTS trg_signature_guard_objs ON "Meta"."Objs";
CREATE TRIGGER trg_signature_guard_objs
  BEFORE UPDATE OR DELETE ON "Meta"."Objs"
  FOR EACH ROW EXECUTE FUNCTION portal.fn_signature_guard();

/* Session context allowed to read the target; raises otherwise. */
CREATE OR REPLACE FUNCTION portal.fn_session_signature_target_require(
  p_session_token text,
  p_target_kind text,
  p_target_key text
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_obj integer;
BEGIN
  IF p_target_key IS NULL OR p_target_key !~ '^[0-9]+$' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'target key must be a record id');
  END IF;

  IF p_target_kind = 'meta.object' THEN
    v_obj := p_target_key::integer;
    SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance(p_session_token, 'meta.object.read') LIMIT 1;
    IF NOT EXISTS (SELECT 1 FROM "Meta"."Objs" o WHERE o."ID" = v_obj) THEN
      PERFORM portal.fn_semantic_raise('GS404', 'object not found');
    END IF;
    PERFORM portal.fn_session_meta_assert_obj_in_active_scope(v_obj, v_ctx.active_scope_id);
    PERFORM portal.fn_meta_assert_object_action(v_ctx.user_id, v_ctx.active_scope_id, v_obj, 'read', v_ctx.session_id);
  ELSIF p_target_kind = 'wf.instance' THEN
    SELECT * INTO v_ctx FROM portal.fn_session_operator_require(p_session_token, '/app/workflows/runs') LIMIT 1;
    IF NOT EXISTS (SELECT 1 FROM wf.workflow_instance wi WHERE wi.id = p_target_key::bigint) THEN
      PERFORM portal.fn_semantic_raise('GS404', 'workflow run not found');
    END IF;
  ELSE
    PERFORM portal.fn_semantic_raise('GS400', 'target kind must be meta.object or wf.instance');
  END IF;

  RETURN QUERY SELECT v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id;
END;
$$;

/*
  Sign a record. The session must have authenticated within portal_signature_reauth_seconds
  (default 300): the portal asks the user to sign in again before calling this.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_sign(
  p_session_token text,
  p_target_kind text,
  p_target_key text,
  p_meaning text,
  p_comment text DEFAULT NULL
)
RETURNS TABLE (signature_obj_id integer, content_sha256 text, signed_at_utc timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", cfg, pg_temp
SET "TimeZone" = 'UTC'
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  v_auth timestamptz;
  v_window integer := cfg.fn_portal_auth_int('portal_signature_reauth_seconds', 300);
  v_meaning_obj integer;
  v_meaning_doc jsonb;
  v_user record;
  v_hash text;
  v_now timestamptz := now();
  v_sig integer;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_signature_target_require(p_session_token, p_target_kind, p_target_key) LIMIT 1;

  IF p_target_kind = 'meta.object' AND EXISTS (
    SELECT 1 FROM "Meta"."Objs" o WHERE o."ID" = p_target_key::integer AND o."ClassID" = portal.fn_signature_class_id()
  ) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'a signature cannot itself be signed');
  END IF;

  SELECT s."AuthenticatedAtUtc" INTO v_auth FROM "RBAC"."Sessions" s WHERE s."ID" = v_ctx.session_id;
  IF v_auth IS NULL OR v_auth < v_now - make_interval(secs => v_window) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'recent sign-in required to sign');
  END IF;

  SELECT o."ID", "Meta".fn_merged_obj_document(o."ID") INTO v_meaning_obj, v_meaning_doc
  FROM "Meta"."Objs" o
  JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
  WHERE c."Name" = 'platform/SignatureMeaning'
    AND "Meta".fn_merged_obj_document(o."ID") ->> 'Meaning' = p_meaning
  ORDER BY o."ID"
  LIMIT 1;
  IF v_meaning_obj IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'unknown signature meaning');
  END IF;

  SELECT u."FullName", u.email INTO v_user FROM "RBAC"."Users" u WHERE u."ID" = v_ctx.user_id;
  v_hash := portal.fn_signature_content_sha256(p_target_kind, p_target_key);

  v_sig := "Meta".sp_obj_insert(
    portal.fn_signature_class_id(),
    jsonb_strip_nulls(jsonb_build_object(
      'Label', format('%s: %s', v_meaning_doc ->> 'Label', v_user."FullName"),
      'TargetKind', p_target_kind,
      'TargetKey', p_target_key,
      'Meaning', p_meaning,
      'MeaningLabel', v_meaning_doc ->> 'Label',
      'MeaningObjID', v_meaning_obj,
      'SignerUserID', v_ctx.user_id,
      'SignerFullName', v_user."FullName",
      'SignerEmail', v_user.email,
      'SignedAtUtc', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      'ContentSha256', v_hash,
      'Comment', NULLIF(btrim(p_comment), ''),
      'SessionID', v_ctx.session_id
    ))
  );
  IF v_ctx.active_scope_id IS NOT NULL THEN
    INSERT INTO portal."ScopedMetaObjects" ("ObjID", "ScopeID") VALUES (v_sig, v_ctx.active_scope_id);
  END IF;

  RETURN QUERY SELECT v_sig, v_hash, v_now;
END;
$$;

/* Signatures on a record, each with its verification status. */
CREATE OR REPLACE FUNCTION portal.sp_session_signatures(
  p_session_token text,
  p_target_kind text,
  p_target_key text
)
RETURNS TABLE (
  signature_obj_id integer,
  meaning text,
  meaning_label text,
  signer_user_id integer,
  signer_full_name text,
  signed_at_utc text,
  comment text,
  content_sha256 text,
  status text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
#variable_conflict use_column
BEGIN
  PERFORM portal.fn_session_signature_target_require(p_session_token, p_target_kind, p_target_key);
  RETURN QUERY
  SELECT v."ObjID",
         v."Data" ->> 'Meaning',
         v."Data" ->> 'MeaningLabel',
         (v."Data" ->> 'SignerUserID')::integer,
         v."Data" ->> 'SignerFullName',
         v."Data" ->> 'SignedAtUtc',
         v."Data" ->> 'Comment',
         v."Data" ->> 'ContentSha256',
         (SELECT f.status FROM portal.fn_signature_verify(v."ObjID") f)
  FROM "Meta"."ObjValues" v
  WHERE v."ClassID" = portal.fn_signature_class_id()
    AND v."Data" ->> 'TargetKind' = p_target_kind
    AND v."Data" ->> 'TargetKey' = p_target_key
  ORDER BY v."ObjID";
END;
$$;

COMMIT;
