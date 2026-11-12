/*
  Operator-defined views and dashboards (scope-scoped).
  Views reference the same entities as semantic requests and Meta classes.
  Dashboards arrange views for multi-widget presentation.
*/

CREATE TABLE IF NOT EXISTS portal.operator_view (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope_id integer NOT NULL,
  created_by_user_id integer NOT NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  semantic_request_code text NULL,
  semantic_request_version text NOT NULL DEFAULT '1',
  meta_class_name text NULL,
  params_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  visibility text NOT NULL DEFAULT 'scope',
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT ck_operator_view_source CHECK (
    semantic_request_code IS NOT NULL OR meta_class_name IS NOT NULL
  )
);

ALTER TABLE portal.operator_view
  ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'scope';

DO $ck$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_operator_view_visibility'
  ) THEN
    ALTER TABLE portal.operator_view
      ADD CONSTRAINT ck_operator_view_visibility
      CHECK (visibility IN ('scope', 'organization', 'private'));
  END IF;
END
$ck$;

CREATE INDEX IF NOT EXISTS ix_operator_view_scope
  ON portal.operator_view (scope_id, updated_at_utc DESC);

CREATE TABLE IF NOT EXISTS portal.operator_dashboard (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope_id integer NOT NULL,
  created_by_user_id integer NOT NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  layout_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  visibility text NOT NULL DEFAULT 'scope',
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

ALTER TABLE portal.operator_dashboard
  ADD COLUMN IF NOT EXISTS layout_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE portal.operator_dashboard
  ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'scope';

DO $ckd$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_operator_dashboard_visibility'
  ) THEN
    ALTER TABLE portal.operator_dashboard
      ADD CONSTRAINT ck_operator_dashboard_visibility
      CHECK (visibility IN ('scope', 'organization', 'private'));
  END IF;
END
$ckd$;

CREATE INDEX IF NOT EXISTS ix_operator_dashboard_scope
  ON portal.operator_dashboard (scope_id, updated_at_utc DESC);

CREATE TABLE IF NOT EXISTS portal.operator_dashboard_widget (
  dashboard_id bigint NOT NULL REFERENCES portal.operator_dashboard (id) ON DELETE CASCADE,
  view_id bigint NOT NULL REFERENCES portal.operator_view (id) ON DELETE CASCADE,
  sort_order smallint NOT NULL DEFAULT 10,
  column_span smallint NOT NULL DEFAULT 1 CHECK (column_span BETWEEN 1 AND 2),
  grid_x smallint NOT NULL DEFAULT 0,
  grid_y smallint NOT NULL DEFAULT 0,
  grid_w smallint NOT NULL DEFAULT 4,
  grid_h smallint NOT NULL DEFAULT 2,
  widget_title text NOT NULL DEFAULT '',
  viz_override_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (dashboard_id, view_id)
);

ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS grid_x smallint NOT NULL DEFAULT 0;
ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS grid_y smallint NOT NULL DEFAULT 0;
ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS grid_w smallint NOT NULL DEFAULT 4;
ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS grid_h smallint NOT NULL DEFAULT 2;
ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS widget_title text NOT NULL DEFAULT '';
ALTER TABLE portal.operator_dashboard_widget
  ADD COLUMN IF NOT EXISTS viz_override_json jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS ix_operator_dashboard_widget_dashboard
  ON portal.operator_dashboard_widget (dashboard_id, sort_order);

CREATE OR REPLACE FUNCTION portal.fn_operator_scope_visible(
  p_active_scope_id integer,
  p_row_scope_id integer,
  p_visibility text
)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT
    CASE
      WHEN p_visibility IN ('scope', 'private') THEN p_row_scope_id = p_active_scope_id
      WHEN p_visibility = 'organization' THEN
        p_row_scope_id = p_active_scope_id
        OR EXISTS (
          SELECT 1
          FROM "RBAC"."Scopes" sa
          INNER JOIN "RBAC"."Scopes" so
            ON so."OrganizationID" = sa."OrganizationID"
          WHERE sa."ScopeID" = p_active_scope_id
            AND so."ScopeID" = p_row_scope_id
            AND sa."OrganizationID" IS NOT NULL
        )
      ELSE false
    END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_operator_view_sync_meta(
  p_scope_id integer,
  p_view_id bigint,
  p_title text,
  p_description text,
  p_semantic_request_code text,
  p_meta_class_name text,
  p_params_json jsonb,
  p_visibility text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_class int;
  v_obj int;
  v_doc jsonb;
  v_kind text;
  v_vis text;
BEGIN
  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/OperatorView' LIMIT 1;
  IF v_class IS NULL THEN
    RETURN NULL;
  END IF;

  v_kind := CASE WHEN p_semantic_request_code IS NOT NULL THEN 'semantic' ELSE 'meta' END;
  v_vis := COALESCE(NULLIF(btrim(p_visibility), ''), 'scope');
  IF v_vis = 'private' THEN
    v_doc := jsonb_build_object(
      'Label', '',
      'Description', '',
      'SourceKind', '',
      'DefinitionJson', '{}',
      'Visibility', 'private'
    );
  ELSE
    v_doc := jsonb_build_object(
      'Label', btrim(p_title),
      'Description', COALESCE(p_description, ''),
      'SourceKind', v_kind,
      'SemanticRequestCode', p_semantic_request_code,
      'MetaClassName', p_meta_class_name,
      'DefinitionJson', COALESCE(p_params_json, '{}'::jsonb)::text,
      'Visibility', v_vis,
      'LegacyViewId', p_view_id
    );
  END IF;

  SELECT m.meta_obj_id INTO v_obj
  FROM portal.operator_view_meta_map m
  WHERE m.legacy_view_id = p_view_id;

  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_class, v_doc);
    INSERT INTO portal.operator_view_meta_map (legacy_view_id, meta_obj_id)
    VALUES (p_view_id, v_obj);
  ELSE
    PERFORM "Meta".sp_obj_update(v_obj, v_doc);
  END IF;

  IF v_vis = 'private' THEN
    DELETE FROM portal."ScopedMetaObjects" sm WHERE sm."ObjID" = v_obj;
  ELSE
    INSERT INTO portal."ScopedMetaObjects" ("ObjID", "ScopeID")
    VALUES (v_obj, p_scope_id)
    ON CONFLICT ("ObjID") DO UPDATE SET "ScopeID" = EXCLUDED."ScopeID";
  END IF;

  RETURN v_obj;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_operator_dashboard_sync_meta(
  p_scope_id integer,
  p_dashboard_id bigint,
  p_title text,
  p_description text,
  p_layout_json jsonb,
  p_visibility text
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_class int;
  v_obj int;
  v_doc jsonb;
  v_vis text;
BEGIN
  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Dashboard' LIMIT 1;
  IF v_class IS NULL THEN
    RETURN NULL;
  END IF;

  v_vis := COALESCE(NULLIF(btrim(p_visibility), ''), 'scope');
  IF v_vis = 'private' THEN
    v_doc := jsonb_build_object(
      'Label', '',
      'Description', '',
      'LayoutJson', '{}',
      'Visibility', 'private'
    );
  ELSE
    v_doc := jsonb_build_object(
      'Label', btrim(p_title),
      'Description', COALESCE(p_description, ''),
      'LayoutJson', COALESCE(p_layout_json, '{}'::jsonb)::text,
      'Visibility', v_vis,
      'LegacyDashboardId', p_dashboard_id
    );
  END IF;

  SELECT m.meta_obj_id INTO v_obj
  FROM portal.operator_dashboard_meta_map m
  WHERE m.legacy_dashboard_id = p_dashboard_id;

  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_class, v_doc);
    INSERT INTO portal.operator_dashboard_meta_map (legacy_dashboard_id, meta_obj_id)
    VALUES (p_dashboard_id, v_obj);
  ELSE
    PERFORM "Meta".sp_obj_update(v_obj, v_doc);
  END IF;

  IF v_vis = 'private' THEN
    DELETE FROM portal."ScopedMetaObjects" sm WHERE sm."ObjID" = v_obj;
  ELSE
    INSERT INTO portal."ScopedMetaObjects" ("ObjID", "ScopeID")
    VALUES (v_obj, p_scope_id)
    ON CONFLICT ("ObjID") DO UPDATE SET "ScopeID" = EXCLUDED."ScopeID";
  END IF;

  RETURN v_obj;
END;
$$;

/*
  Return-shape upgrades: CREATE OR REPLACE cannot widen RETURNS TABLE when an older overload exists.
  portal._drop_if_proc drops every overload before create (database_gateway_roles.sql re-grants EXECUTE).
*/
SELECT portal._drop_if_proc('portal', 'sp_session_list_operator_views');
SELECT portal._drop_if_proc('portal', 'sp_session_list_operator_dashboards');
SELECT portal._drop_if_proc('portal', 'sp_session_list_dashboard_widgets');

CREATE OR REPLACE FUNCTION portal.sp_session_list_operator_views(p_session_token text)
RETURNS TABLE (
  view_id bigint,
  title text,
  description text,
  semantic_request_code text,
  semantic_request_version text,
  meta_class_name text,
  params_json jsonb,
  visibility text,
  meta_obj_id integer,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  RETURN QUERY
  SELECT
    v.id,
    v.title,
    v.description,
    v.semantic_request_code,
    v.semantic_request_version,
    v.meta_class_name,
    v.params_json,
    v.visibility,
    m.meta_obj_id,
    v.updated_at_utc
  FROM portal.operator_view v
  LEFT JOIN portal.operator_view_meta_map m ON m.legacy_view_id = v.id
  WHERE portal.fn_operator_scope_visible(v_scope_id, v.scope_id, v.visibility)
    AND (
      v.visibility <> 'private'
      OR v.created_by_user_id = v_user_id
    )
  ORDER BY v.updated_at_utc DESC, v.id DESC;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_operator_view(
  p_session_token text,
  p_view_id bigint
)
RETURNS TABLE (
  view_id bigint,
  title text,
  description text,
  semantic_request_code text,
  semantic_request_version text,
  meta_class_name text,
  params_json jsonb,
  visibility text,
  meta_obj_id integer,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_view v
    WHERE v.id = p_view_id
      AND portal.fn_operator_scope_visible(v_scope_id, v.scope_id, v.visibility)
      AND (
        v.visibility <> 'private'
        OR v.created_by_user_id = v_user_id
      )
  ) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'operator view not found');
  END IF;

  RETURN QUERY
  SELECT
    v.id,
    v.title,
    v.description,
    v.semantic_request_code,
    v.semantic_request_version,
    v.meta_class_name,
    v.params_json,
    v.visibility,
    m.meta_obj_id,
    v.updated_at_utc
  FROM portal.operator_view v
  LEFT JOIN portal.operator_view_meta_map m ON m.legacy_view_id = v.id
  WHERE v.id = p_view_id
  LIMIT 1;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_operator_view(
  p_session_token text,
  p_view_id bigint DEFAULT NULL,
  p_title text DEFAULT NULL,
  p_description text DEFAULT NULL,
  p_semantic_request_code text DEFAULT NULL,
  p_semantic_request_version text DEFAULT '1',
  p_meta_class_name text DEFAULT NULL,
  p_params_json jsonb DEFAULT '{}'::jsonb,
  p_visibility text DEFAULT 'scope'
)
RETURNS TABLE (view_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_id bigint;
  v_vis text;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF p_title IS NULL OR btrim(p_title) = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'title is required');
  END IF;
  IF p_semantic_request_code IS NULL AND p_meta_class_name IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'semantic_request_code or meta_class_name required');
  END IF;
  IF p_visibility IS NOT NULL AND p_visibility NOT IN ('scope', 'organization', 'private') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'invalid visibility');
  END IF;

  IF p_view_id IS NOT NULL THEN
    UPDATE portal.operator_view v
    SET
      title = btrim(p_title),
      description = COALESCE(p_description, ''),
      semantic_request_code = p_semantic_request_code,
      semantic_request_version = COALESCE(NULLIF(btrim(p_semantic_request_version), ''), '1'),
      meta_class_name = NULLIF(btrim(p_meta_class_name), ''),
      params_json = COALESCE(p_params_json, '{}'::jsonb),
      visibility = COALESCE(NULLIF(btrim(p_visibility), ''), v.visibility),
      updated_at_utc = now() AT TIME ZONE 'utc'
    WHERE v.id = p_view_id
      AND v.scope_id = v_sess.active_scope_id
      AND (
        v.created_by_user_id = v_sess.user_id
        OR (
          v.visibility <> 'private'
          AND portal.fn_semantic_session_has_permission(v_sess.user_id, 'meta.object.write')
        )
      )
    RETURNING v.id INTO v_id;
    IF v_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'operator view not found or not authorized');
    END IF;
  ELSE
    INSERT INTO portal.operator_view (
      scope_id, created_by_user_id, title, description,
      semantic_request_code, semantic_request_version, meta_class_name, params_json, visibility
    )
    VALUES (
      v_sess.active_scope_id, v_sess.user_id, btrim(p_title), COALESCE(p_description, ''),
      p_semantic_request_code,
      COALESCE(NULLIF(btrim(p_semantic_request_version), ''), '1'),
      NULLIF(btrim(p_meta_class_name), ''),
      COALESCE(p_params_json, '{}'::jsonb),
      COALESCE(NULLIF(btrim(p_visibility), ''), 'scope')
    )
    RETURNING id INTO v_id;
  END IF;

  SELECT v.visibility INTO v_vis FROM portal.operator_view v WHERE v.id = v_id;

  PERFORM portal.fn_operator_view_sync_meta(
    v_sess.active_scope_id,
    v_id,
    btrim(p_title),
    COALESCE(p_description, ''),
    p_semantic_request_code,
    NULLIF(btrim(p_meta_class_name), ''),
    COALESCE(p_params_json, '{}'::jsonb),
    v_vis
  );

  RETURN QUERY SELECT v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_delete_operator_view(
  p_session_token text,
  p_view_id bigint
)
RETURNS TABLE (deleted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
  v_meta_obj_id integer;
  v_n bigint;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  SELECT m.meta_obj_id INTO v_meta_obj_id
  FROM portal.operator_view_meta_map m
  WHERE m.legacy_view_id = p_view_id;

  DELETE FROM portal.operator_view v
  WHERE v.id = p_view_id
    AND v.scope_id = v_scope_id
    AND (
      v.created_by_user_id = v_user_id
      OR (
        v.visibility <> 'private'
        AND portal.fn_semantic_session_has_permission(v_user_id, 'meta.object.write')
      )
    );
  GET DIAGNOSTICS v_n = ROW_COUNT;

  IF v_n > 0 AND v_meta_obj_id IS NOT NULL THEN
    DELETE FROM "Meta"."Objs" o WHERE o."ID" = v_meta_obj_id;
  END IF;

  RETURN QUERY SELECT v_n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_operator_dashboards(p_session_token text)
RETURNS TABLE (
  dashboard_id bigint,
  title text,
  description text,
  layout_json jsonb,
  visibility text,
  meta_obj_id integer,
  widget_count bigint,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  RETURN QUERY
  SELECT
    d.id,
    d.title,
    d.description,
    d.layout_json,
    d.visibility,
    m.meta_obj_id,
    (SELECT count(*) FROM portal.operator_dashboard_widget w WHERE w.dashboard_id = d.id),
    d.updated_at_utc
  FROM portal.operator_dashboard d
  LEFT JOIN portal.operator_dashboard_meta_map m ON m.legacy_dashboard_id = d.id
  WHERE portal.fn_operator_scope_visible(v_scope_id, d.scope_id, d.visibility)
    AND (
      d.visibility <> 'private'
      OR d.created_by_user_id = v_user_id
    )
  ORDER BY d.updated_at_utc DESC, d.id DESC;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_operator_dashboard(
  p_session_token text,
  p_dashboard_id bigint
)
RETURNS TABLE (
  dashboard_id bigint,
  title text,
  description text,
  layout_json jsonb,
  visibility text,
  meta_obj_id integer,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_dashboard d
    WHERE d.id = p_dashboard_id
      AND portal.fn_operator_scope_visible(v_scope_id, d.scope_id, d.visibility)
      AND (
        d.visibility <> 'private'
        OR d.created_by_user_id = v_user_id
      )
  ) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'dashboard not found');
  END IF;

  RETURN QUERY
  SELECT
    d.id,
    d.title,
    d.description,
    d.layout_json,
    d.visibility,
    m.meta_obj_id,
    d.updated_at_utc
  FROM portal.operator_dashboard d
  LEFT JOIN portal.operator_dashboard_meta_map m ON m.legacy_dashboard_id = d.id
  WHERE d.id = p_dashboard_id
  LIMIT 1;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_delete_operator_dashboard(
  p_session_token text,
  p_dashboard_id bigint
)
RETURNS TABLE (deleted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_meta_obj_id integer;
  v_n bigint;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  SELECT m.meta_obj_id INTO v_meta_obj_id
  FROM portal.operator_dashboard_meta_map m
  WHERE m.legacy_dashboard_id = p_dashboard_id;

  DELETE FROM portal.operator_dashboard d
  WHERE d.id = p_dashboard_id
    AND d.scope_id = v_sess.active_scope_id
    AND (
      d.created_by_user_id = v_sess.user_id
      OR (
        d.visibility <> 'private'
        AND portal.fn_semantic_session_has_permission(v_sess.user_id, 'meta.object.write')
      )
    );
  GET DIAGNOSTICS v_n = ROW_COUNT;

  IF v_n > 0 AND v_meta_obj_id IS NOT NULL THEN
    DELETE FROM "Meta"."Objs" o WHERE o."ID" = v_meta_obj_id;
  END IF;

  RETURN QUERY SELECT v_n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_operator_dashboard(
  p_session_token text,
  p_dashboard_id bigint DEFAULT NULL,
  p_title text DEFAULT NULL,
  p_description text DEFAULT NULL,
  p_layout_json jsonb DEFAULT '{}'::jsonb,
  p_visibility text DEFAULT 'scope'
)
RETURNS TABLE (dashboard_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_id bigint;
  v_vis text;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF p_title IS NULL OR btrim(p_title) = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'title is required');
  END IF;
  IF p_visibility IS NOT NULL AND p_visibility NOT IN ('scope', 'organization', 'private') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'invalid visibility');
  END IF;

  IF p_dashboard_id IS NOT NULL THEN
    UPDATE portal.operator_dashboard d
    SET
      title = btrim(p_title),
      description = COALESCE(p_description, ''),
      layout_json = COALESCE(p_layout_json, d.layout_json),
      visibility = COALESCE(NULLIF(btrim(p_visibility), ''), d.visibility),
      updated_at_utc = now() AT TIME ZONE 'utc'
    WHERE d.id = p_dashboard_id
      AND d.scope_id = v_sess.active_scope_id
      AND (
        d.created_by_user_id = v_sess.user_id
        OR (
          d.visibility <> 'private'
          AND portal.fn_semantic_session_has_permission(v_sess.user_id, 'meta.object.write')
        )
      )
    RETURNING d.id INTO v_id;
    IF v_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'dashboard not found or not authorized');
    END IF;
  ELSE
    INSERT INTO portal.operator_dashboard (
      scope_id, created_by_user_id, title, description, layout_json, visibility
    )
    VALUES (
      v_sess.active_scope_id,
      v_sess.user_id,
      btrim(p_title),
      COALESCE(p_description, ''),
      COALESCE(p_layout_json, '{}'::jsonb),
      COALESCE(NULLIF(btrim(p_visibility), ''), 'scope')
    )
    RETURNING id INTO v_id;
  END IF;

  SELECT d.visibility INTO v_vis FROM portal.operator_dashboard d WHERE d.id = v_id;

  PERFORM portal.fn_operator_dashboard_sync_meta(
    v_sess.active_scope_id,
    v_id,
    btrim(p_title),
    COALESCE(p_description, ''),
    COALESCE(p_layout_json, '{}'::jsonb),
    v_vis
  );

  RETURN QUERY SELECT v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_set_dashboard_widgets(
  p_session_token text,
  p_dashboard_id bigint,
  p_widgets jsonb
)
RETURNS TABLE (widget_count bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_row jsonb;
  v_view_id bigint;
  v_sort smallint;
  v_span smallint;
  v_gx smallint;
  v_gy smallint;
  v_gw smallint;
  v_gh smallint;
  v_wtitle text;
  v_viz jsonb;
  v_count bigint := 0;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_dashboard d
    WHERE d.id = p_dashboard_id
      AND d.scope_id = v_sess.active_scope_id
      AND (
        d.created_by_user_id = v_sess.user_id
        OR (
          d.visibility <> 'private'
          AND portal.fn_semantic_session_has_permission(v_sess.user_id, 'meta.object.write')
        )
      )
  ) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'dashboard not found');
  END IF;

  IF p_widgets IS NULL OR jsonb_typeof(p_widgets) <> 'array' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'widgets must be a JSON array');
  END IF;

  DELETE FROM portal.operator_dashboard_widget w WHERE w.dashboard_id = p_dashboard_id;

  FOR v_row IN SELECT value FROM jsonb_array_elements(p_widgets)
  LOOP
    v_view_id := (v_row->>'view_id')::bigint;
    v_sort := COALESCE((v_row->>'sort_order')::smallint, 10);
    v_span := COALESCE((v_row->>'column_span')::smallint, 1);
    v_gx := COALESCE((v_row->>'grid_x')::smallint, 0);
    v_gy := COALESCE((v_row->>'grid_y')::smallint, 0);
    v_gw := COALESCE((v_row->>'grid_w')::smallint, 4);
    v_gh := COALESCE((v_row->>'grid_h')::smallint, 2);
    v_wtitle := COALESCE(v_row->>'widget_title', '');
    v_viz := COALESCE(v_row->'viz_override', '{}'::jsonb);

    IF v_view_id IS NULL THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM portal.operator_view v
      WHERE v.id = v_view_id
        AND portal.fn_operator_scope_visible(v_sess.active_scope_id, v.scope_id, v.visibility)
        AND (
          v.visibility <> 'private'
          OR v.created_by_user_id = v_sess.user_id
        )
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'view not in active scope');
    END IF;

    INSERT INTO portal.operator_dashboard_widget (
      dashboard_id, view_id, sort_order, column_span,
      grid_x, grid_y, grid_w, grid_h, widget_title, viz_override_json
    )
    VALUES (p_dashboard_id, v_view_id, v_sort, v_span, v_gx, v_gy, v_gw, v_gh, v_wtitle, v_viz);
    v_count := v_count + 1;
  END LOOP;

  UPDATE portal.operator_dashboard d
  SET updated_at_utc = now() AT TIME ZONE 'utc'
  WHERE d.id = p_dashboard_id;

  RETURN QUERY SELECT v_count;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_dashboard_widgets(
  p_session_token text,
  p_dashboard_id bigint
)
RETURNS TABLE (
  view_id bigint,
  title text,
  semantic_request_code text,
  meta_class_name text,
  params_json jsonb,
  sort_order smallint,
  column_span smallint,
  grid_x smallint,
  grid_y smallint,
  grid_w smallint,
  grid_h smallint,
  widget_title text,
  viz_override_json jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_user_id integer;
BEGIN
  SELECT active_scope_id, user_id INTO v_scope_id, v_user_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_dashboard d
    WHERE d.id = p_dashboard_id
      AND portal.fn_operator_scope_visible(v_scope_id, d.scope_id, d.visibility)
      AND (
        d.visibility <> 'private'
        OR d.created_by_user_id = v_user_id
      )
  ) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'dashboard not found');
  END IF;

  RETURN QUERY
  SELECT
    v.id,
    v.title,
    v.semantic_request_code,
    v.meta_class_name,
    v.params_json,
    w.sort_order,
    w.column_span,
    w.grid_x,
    w.grid_y,
    w.grid_w,
    w.grid_h,
    w.widget_title,
    w.viz_override_json
  FROM portal.operator_dashboard_widget w
  JOIN portal.operator_view v ON v.id = w.view_id
  WHERE w.dashboard_id = p_dashboard_id
    AND portal.fn_operator_scope_visible(v_scope_id, v.scope_id, v.visibility)
    AND (
      v.visibility <> 'private'
      OR v.created_by_user_id = v_user_id
    )
  ORDER BY w.grid_y, w.grid_x, w.sort_order, v.title;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_fields_for_request(
  p_session_token text,
  p_request_code text
)
RETURNS TABLE (
  field_code text,
  column_name text,
  json_type text,
  role text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_entity_id integer;
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token);

  SELECT r.entity_id INTO v_entity_id
  FROM portal.semantic_request r
  WHERE r.request_code = p_request_code
  ORDER BY r.version DESC
  LIMIT 1;

  IF v_entity_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic request not found');
  END IF;

  RETURN QUERY
  SELECT a.code, a.column_name, a.json_type, a.role::text
  FROM portal.semantic_attribute a
  WHERE a.entity_id = v_entity_id
  ORDER BY a.code;
END;
$$;
