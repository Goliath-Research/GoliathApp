/*
  Generic admin and config editors (session-gated, goliath_portal EXECUTE only).

  Config documents (cfg.site, cfg.pipeline_profile)
    Documents are edited only through a typed schema: the app that owns a config kind registers
    a catalog data type for its document (cfg.sp_register_kind_document_type). GoliathApp knows
    no document keys. Kinds without a registered type are listed and viewed, and can be published
    or retired, but their documents are not editable (no free-form JSON).
    Saving a draft updates it in place; saving a published version creates the next version as a
    draft. Retired versions are not edited.

  Organizations
    List for organization admins; create, rename and activate/deactivate for the God Architect only.
    Organizations are never deleted here.

  Every write is audited in portal.record_editor_audit.
*/

CREATE TABLE IF NOT EXISTS cfg.kind_document_type (
  kind text PRIMARY KEY,
  type_id bigint NOT NULL REFERENCES wf.data_type (id),
  updated_at_utc timestamptz NOT NULL DEFAULT (now())
);

/* Owner-only: an app registers the catalog data type that types its documents of one kind. */
CREATE OR REPLACE FUNCTION cfg.sp_register_kind_document_type(p_kind text, p_type_name text)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = cfg, wf, pg_temp
AS $$
DECLARE
  v_type_id bigint;
BEGIN
  IF p_kind NOT IN ('site', 'pipeline_profile') THEN
    RAISE EXCEPTION 'kind % has no document editor', p_kind;
  END IF;
  SELECT t.id INTO v_type_id
  FROM wf.data_type t
  WHERE t.name = p_type_name AND t.status <> 'retired'
  ORDER BY
    CASE WHEN t.version ~ '^[0-9]+\.[0-9]+$' THEN split_part(t.version, '.', 1)::int ELSE 0 END DESC,
    CASE WHEN t.version ~ '^[0-9]+\.[0-9]+$' THEN split_part(t.version, '.', 2)::int ELSE 0 END DESC,
    t.id DESC
  LIMIT 1;
  IF v_type_id IS NULL THEN
    RAISE EXCEPTION 'data type % not found', p_type_name;
  END IF;
  INSERT INTO cfg.kind_document_type (kind, type_id)
  VALUES (p_kind, v_type_id)
  ON CONFLICT (kind) DO UPDATE SET type_id = EXCLUDED.type_id, updated_at_utc = now();
  RETURN v_type_id;
END;
$$;

REVOKE ALL ON FUNCTION cfg.sp_register_kind_document_type(text, text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION portal.fn_cfg_editor_path(p_kind text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE p_kind
    WHEN 'site' THEN '/app/config/site'
    WHEN 'pipeline_profile' THEN '/app/config/pipeline-profiles'
  END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_cfg_editor_path_or_raise(p_kind text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = portal, pg_temp
AS $$
BEGIN
  IF portal.fn_cfg_editor_path(p_kind) IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', format('kind %s has no editor', COALESCE(p_kind, '')));
  END IF;
  RETURN portal.fn_cfg_editor_path(p_kind);
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_cfg_document_schema(p_kind text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = cfg, wf, pg_temp
AS $$
  SELECT t.schema_json
  FROM cfg.kind_document_type k
  JOIN wf.data_type t ON t.id = k.type_id
  WHERE k.kind = p_kind;
$$;

REVOKE ALL ON FUNCTION portal.fn_cfg_document_schema(text) FROM PUBLIC;

/* Keys and basic JSON types of a document must match the registered schema's properties. */
CREATE OR REPLACE FUNCTION portal.fn_cfg_document_check(p_schema jsonb, p_document jsonb)
RETURNS void
LANGUAGE plpgsql
IMMUTABLE
SET search_path = portal, pg_temp
AS $$
DECLARE
  r record;
  v_prop jsonb;
  v_want text;
  v_have text;
BEGIN
  IF jsonb_typeof(p_document) <> 'object' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'document must be an object');
  END IF;
  FOR r IN SELECT key, value FROM jsonb_each(p_document)
  LOOP
    v_prop := p_schema->'properties'->r.key;
    IF v_prop IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', format('unknown document field %s', r.key));
    END IF;
    v_want := v_prop->>'type';
    v_have := jsonb_typeof(r.value);
    CONTINUE WHEN v_want IS NULL OR v_have = 'null';
    IF NOT (
      v_want = v_have
      OR (v_want = 'integer' AND v_have = 'number' AND (r.value #>> '{}') ~ '^-?[0-9]+$')
      OR (v_want = 'number' AND v_have = 'number')
    ) THEN
      PERFORM portal.fn_semantic_raise('GS400', format('field %s must be %s', r.key, v_want));
    END IF;
  END LOOP;
  FOR r IN SELECT value #>> '{}' AS name FROM jsonb_array_elements(COALESCE(p_schema->'required', '[]'::jsonb))
  LOOP
    IF NOT p_document ? r.name OR jsonb_typeof(p_document->r.name) = 'null' THEN
      PERFORM portal.fn_semantic_raise('GS400', format('field %s is required', r.name));
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_cfg_document_list(p_session_token text, p_kind text)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  updated_at_utc timestamptz,
  editable boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_editable boolean;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY[portal.fn_cfg_editor_path_or_raise(p_kind)]);
  v_editable := portal.fn_cfg_document_schema(p_kind) IS NOT NULL;
  IF p_kind = 'site' THEN
    RETURN QUERY
    SELECT s.id, s.name, s.version, s.status::text, COALESCE(s.updated_at_utc, s.created_at_utc),
           v_editable AND s.status <> 'retired'
    FROM cfg.site s ORDER BY s.name, s.id;
  ELSE
    RETURN QUERY
    SELECT s.id, s.name, s.version, s.status::text, COALESCE(s.updated_at_utc, s.created_at_utc),
           v_editable AND s.status <> 'retired'
    FROM cfg.pipeline_profile s ORDER BY s.name, s.id;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_cfg_document_get(p_session_token text, p_kind text, p_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_row record;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY[portal.fn_cfg_editor_path_or_raise(p_kind)]);
  IF p_kind = 'site' THEN
    SELECT s.id, s.name, s.version, s.status, s.document_json INTO v_row FROM cfg.site s WHERE s.id = p_id;
  ELSE
    SELECT s.id, s.name, s.version, s.status, s.document_json INTO v_row FROM cfg.pipeline_profile s WHERE s.id = p_id;
  END IF;
  IF v_row.id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'document not found');
  END IF;
  RETURN jsonb_build_object(
    'id', v_row.id,
    'name', v_row.name,
    'version', v_row.version,
    'status', v_row.status,
    'document', v_row.document_json,
    'document_schema', portal.fn_cfg_document_schema(p_kind)
  );
END;
$$;

/* Save (create when p_id is NULL). Document: { name, document }. Returns the saved row id. */
CREATE OR REPLACE FUNCTION portal.sp_session_cfg_document_save(
  p_session_token text,
  p_kind text,
  p_id bigint,
  p_document jsonb
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_schema jsonb;
  v_doc jsonb := COALESCE(p_document->'document', '{}'::jsonb);
  v_name text := portal.fn_doc_text(p_document, 'name');
  v_row record;
  v_next text;
  v_id bigint;
  v_action text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY[portal.fn_cfg_editor_path_or_raise(p_kind)])
  LIMIT 1;
  v_schema := portal.fn_cfg_document_schema(p_kind);
  IF v_schema IS NULL THEN
    PERFORM portal.fn_semantic_raise(
      'GS409', format('no document type is registered for %s; documents are view-only', p_kind)
    );
  END IF;
  PERFORM portal.fn_cfg_document_check(v_schema, v_doc);

  IF p_id IS NULL THEN
    IF v_name IS NULL OR v_name !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'name is required (letters, digits, _ . : -; max 128)');
    END IF;
    IF p_kind = 'site' THEN
      IF EXISTS (SELECT 1 FROM cfg.site s WHERE s.name = v_name) THEN
        PERFORM portal.fn_semantic_raise('GS409', format('%s already exists', v_name));
      END IF;
      INSERT INTO cfg.site (name, version, status, content_hash, document_json)
      VALUES (v_name, '1', 'draft', md5(v_doc::text), v_doc) RETURNING id INTO v_id;
    ELSE
      IF EXISTS (SELECT 1 FROM cfg.pipeline_profile s WHERE s.name = v_name) THEN
        PERFORM portal.fn_semantic_raise('GS409', format('%s already exists', v_name));
      END IF;
      INSERT INTO cfg.pipeline_profile (name, version, status, content_hash, document_json)
      VALUES (v_name, '1', 'draft', md5(v_doc::text), v_doc) RETURNING id INTO v_id;
    END IF;
    v_action := 'create';
  ELSE
    IF p_kind = 'site' THEN
      SELECT s.id, s.name, s.status INTO v_row FROM cfg.site s WHERE s.id = p_id;
    ELSE
      SELECT s.id, s.name, s.status INTO v_row FROM cfg.pipeline_profile s WHERE s.id = p_id;
    END IF;
    IF v_row.id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'document not found');
    END IF;
    IF v_row.status = 'retired' THEN
      PERFORM portal.fn_semantic_raise('GS409', 'retired versions are not edited');
    END IF;
    IF v_row.status = 'draft' THEN
      IF p_kind = 'site' THEN
        UPDATE cfg.site s SET document_json = v_doc, content_hash = md5(v_doc::text),
               updated_at_utc = now() WHERE s.id = p_id;
      ELSE
        UPDATE cfg.pipeline_profile s SET document_json = v_doc, content_hash = md5(v_doc::text),
               updated_at_utc = now() WHERE s.id = p_id;
      END IF;
      v_id := p_id;
      v_action := 'save_draft';
    ELSE
      IF p_kind = 'site' THEN
        SELECT (COALESCE(max(CASE WHEN s.version ~ '^[0-9]+$' THEN s.version::int END), 0) + 1)::text
        INTO v_next FROM cfg.site s WHERE s.name = v_row.name;
        INSERT INTO cfg.site (name, version, status, content_hash, document_json)
        VALUES (v_row.name, v_next, 'draft', md5(v_doc::text), v_doc) RETURNING id INTO v_id;
      ELSE
        SELECT (COALESCE(max(CASE WHEN s.version ~ '^[0-9]+$' THEN s.version::int END), 0) + 1)::text
        INTO v_next FROM cfg.pipeline_profile s WHERE s.name = v_row.name;
        INSERT INTO cfg.pipeline_profile (name, version, status, content_hash, document_json)
        VALUES (v_row.name, v_next, 'draft', md5(v_doc::text), v_doc) RETURNING id INTO v_id;
      END IF;
      v_action := 'save_new_version';
    END IF;
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'cfg_' || p_kind, v_action, v_id::text,
    jsonb_build_object('base_id', p_id)
  );
  RETURN v_id;
END;
$$;

/* publish (draft → published) or retire (draft/published → retired). */
CREATE OR REPLACE FUNCTION portal.sp_session_cfg_document_action(
  p_session_token text,
  p_kind text,
  p_id bigint,
  p_action text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_status text;
  v_new text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY[portal.fn_cfg_editor_path_or_raise(p_kind)])
  LIMIT 1;
  IF p_kind = 'site' THEN
    SELECT s.status INTO v_status FROM cfg.site s WHERE s.id = p_id;
  ELSE
    SELECT s.status INTO v_status FROM cfg.pipeline_profile s WHERE s.id = p_id;
  END IF;
  IF v_status IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'document not found');
  END IF;
  IF p_action = 'publish' AND v_status = 'draft' THEN
    v_new := 'published';
  ELSIF p_action = 'retire' AND v_status IN ('draft', 'published') THEN
    v_new := 'retired';
  ELSE
    PERFORM portal.fn_semantic_raise('GS409', format('cannot %s a %s version', COALESCE(p_action, ''), v_status));
  END IF;
  IF p_kind = 'site' THEN
    UPDATE cfg.site s SET status = v_new, updated_at_utc = now() WHERE s.id = p_id;
  ELSE
    UPDATE cfg.pipeline_profile s SET status = v_new, updated_at_utc = now() WHERE s.id = p_id;
  END IF;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'cfg_' || p_kind, p_action, p_id::text,
    jsonb_build_object('from', v_status, 'to', v_new)
  );
  RETURN v_new;
END;
$$;

/* The active scope's organization only; God Architect sees every organization. */
CREATE OR REPLACE FUNCTION portal.sp_session_org_list(p_session_token text)
RETURNS TABLE (
  organization_id integer,
  name text,
  active boolean,
  created_at_utc timestamptz,
  member_count integer,
  scope_id integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_all boolean;
  v_org_id integer;
BEGIN
  SELECT *
  INTO v_ctx
  FROM portal.fn_session_operator_require(p_session_token, '/app/admin/organizations')
  LIMIT 1;

  v_all := portal.fn_session_is_god_architect(v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id);
  IF NOT v_all THEN
    SELECT s."OrganizationID"
    INTO v_org_id
    FROM "RBAC"."Scopes" s
    WHERE s."ScopeID" = v_ctx.active_scope_id
      AND s."ScopeType" = 'organization';
  END IF;

  RETURN QUERY
  SELECT o."ID", o."Name"::text, o."Active", o."CreatedAtUtc",
         (SELECT count(*)::int FROM portal."OrganizationMembers" m WHERE m."OrganizationID" = o."ID"),
         (SELECT min(s."ScopeID")::int FROM "RBAC"."Scopes" s
           WHERE s."OrganizationID" = o."ID" AND s."ScopeType" = 'organization')
  FROM portal."Organizations" o
  WHERE v_all OR o."ID" = v_org_id
  ORDER BY o."Name", o."ID";
END;
$$;

/* God Architect only. Document: { name, active }. Create when p_id is NULL. */
CREATE OR REPLACE FUNCTION portal.sp_session_org_save(p_session_token text, p_id integer, p_document jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_name text := portal.fn_doc_text(p_document, 'name');
  v_active boolean := COALESCE((p_document->>'active')::boolean, true);
  v_id integer := p_id;
  v_scope integer;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/admin/organizations') LIMIT 1;
  IF v_name IS NULL OR length(v_name) > 200 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'name is required (max 200)');
  END IF;
  IF EXISTS (SELECT 1 FROM portal."Organizations" o WHERE lower(o."Name") = lower(v_name) AND o."ID" IS DISTINCT FROM p_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', format('organization %s already exists', v_name));
  END IF;
  IF p_id IS NULL THEN
    SELECT c.organization_id, c.scope_id INTO v_id, v_scope FROM portal.sp_organization_create(v_name) c;
    IF NOT v_active THEN
      UPDATE portal."Organizations" o SET "Active" = false WHERE o."ID" = v_id;
    END IF;
  ELSE
    UPDATE portal."Organizations" o SET "Name" = v_name, "Active" = v_active WHERE o."ID" = p_id;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'organization not found');
    END IF;
  END IF;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'organization',
    CASE WHEN p_id IS NULL THEN 'create' ELSE 'save' END, v_id::text,
    jsonb_build_object('name', v_name, 'active', v_active)
  );
  RETURN v_id;
END;
$$;

/* The registered document schema of a kind (NULL when none), for the create inspector. */
CREATE OR REPLACE FUNCTION portal.sp_session_cfg_document_type(p_session_token text, p_kind text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY[portal.fn_cfg_editor_path_or_raise(p_kind)]);
  RETURN jsonb_build_object('document_schema', portal.fn_cfg_document_schema(p_kind));
END;
$$;
