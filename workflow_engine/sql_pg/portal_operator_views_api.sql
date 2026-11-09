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
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT ck_operator_view_source CHECK (
    semantic_request_code IS NOT NULL OR meta_class_name IS NOT NULL
  )
);

CREATE INDEX IF NOT EXISTS ix_operator_view_scope
  ON portal.operator_view (scope_id, updated_at_utc DESC);

CREATE TABLE IF NOT EXISTS portal.operator_dashboard (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope_id integer NOT NULL,
  created_by_user_id integer NOT NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS ix_operator_dashboard_scope
  ON portal.operator_dashboard (scope_id, updated_at_utc DESC);

CREATE TABLE IF NOT EXISTS portal.operator_dashboard_widget (
  dashboard_id bigint NOT NULL REFERENCES portal.operator_dashboard (id) ON DELETE CASCADE,
  view_id bigint NOT NULL REFERENCES portal.operator_view (id) ON DELETE CASCADE,
  sort_order smallint NOT NULL DEFAULT 10,
  column_span smallint NOT NULL DEFAULT 1 CHECK (column_span BETWEEN 1 AND 2),
  PRIMARY KEY (dashboard_id, view_id)
);

CREATE INDEX IF NOT EXISTS ix_operator_dashboard_widget_dashboard
  ON portal.operator_dashboard_widget (dashboard_id, sort_order);

CREATE OR REPLACE FUNCTION portal.sp_session_list_operator_views(p_session_token text)
RETURNS TABLE (
  view_id bigint,
  title text,
  description text,
  semantic_request_code text,
  semantic_request_version text,
  meta_class_name text,
  params_json jsonb,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
BEGIN
  SELECT active_scope_id INTO v_scope_id
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
    v.updated_at_utc
  FROM portal.operator_view v
  WHERE v.scope_id = v_scope_id
  ORDER BY v.updated_at_utc DESC, v.id DESC;
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
  p_params_json jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (view_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_id bigint;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF p_title IS NULL OR btrim(p_title) = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'title is required');
  END IF;
  IF p_semantic_request_code IS NULL AND p_meta_class_name IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'semantic_request_code or meta_class_name required');
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
      updated_at_utc = now() AT TIME ZONE 'utc'
    WHERE v.id = p_view_id AND v.scope_id = v_sess.active_scope_id
    RETURNING v.id INTO v_id;
    IF v_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'operator view not found');
    END IF;
  ELSE
    INSERT INTO portal.operator_view (
      scope_id, created_by_user_id, title, description,
      semantic_request_code, semantic_request_version, meta_class_name, params_json
    )
    VALUES (
      v_sess.active_scope_id, v_sess.user_id, btrim(p_title), COALESCE(p_description, ''),
      p_semantic_request_code,
      COALESCE(NULLIF(btrim(p_semantic_request_version), ''), '1'),
      NULLIF(btrim(p_meta_class_name), ''),
      COALESCE(p_params_json, '{}'::jsonb)
    )
    RETURNING id INTO v_id;
  END IF;

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
  v_n bigint;
BEGIN
  SELECT active_scope_id INTO v_scope_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  DELETE FROM portal.operator_view v
  WHERE v.id = p_view_id AND v.scope_id = v_scope_id;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN QUERY SELECT v_n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_operator_dashboards(p_session_token text)
RETURNS TABLE (
  dashboard_id bigint,
  title text,
  description text,
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
BEGIN
  SELECT active_scope_id INTO v_scope_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  RETURN QUERY
  SELECT
    d.id,
    d.title,
    d.description,
    (SELECT count(*) FROM portal.operator_dashboard_widget w WHERE w.dashboard_id = d.id),
    d.updated_at_utc
  FROM portal.operator_dashboard d
  WHERE d.scope_id = v_scope_id
  ORDER BY d.updated_at_utc DESC, d.id DESC;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_operator_dashboard(
  p_session_token text,
  p_dashboard_id bigint DEFAULT NULL,
  p_title text DEFAULT NULL,
  p_description text DEFAULT NULL
)
RETURNS TABLE (dashboard_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_id bigint;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF p_title IS NULL OR btrim(p_title) = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'title is required');
  END IF;

  IF p_dashboard_id IS NOT NULL THEN
    UPDATE portal.operator_dashboard d
    SET
      title = btrim(p_title),
      description = COALESCE(p_description, ''),
      updated_at_utc = now() AT TIME ZONE 'utc'
    WHERE d.id = p_dashboard_id AND d.scope_id = v_sess.active_scope_id
    RETURNING d.id INTO v_id;
    IF v_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'dashboard not found');
    END IF;
  ELSE
    INSERT INTO portal.operator_dashboard (scope_id, created_by_user_id, title, description)
    VALUES (v_sess.active_scope_id, v_sess.user_id, btrim(p_title), COALESCE(p_description, ''))
    RETURNING id INTO v_id;
  END IF;

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
  v_count bigint := 0;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_operator_require(p_session_token) LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_dashboard d
    WHERE d.id = p_dashboard_id AND d.scope_id = v_sess.active_scope_id
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

    IF v_view_id IS NULL THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM portal.operator_view v
      WHERE v.id = v_view_id AND v.scope_id = v_sess.active_scope_id
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'view not in active scope');
    END IF;

    INSERT INTO portal.operator_dashboard_widget (dashboard_id, view_id, sort_order, column_span)
    VALUES (p_dashboard_id, v_view_id, v_sort, v_span);
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
  column_span smallint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_scope_id integer;
BEGIN
  SELECT active_scope_id INTO v_scope_id
  FROM portal.fn_session_operator_require(p_session_token)
  LIMIT 1;

  IF NOT EXISTS (
    SELECT 1 FROM portal.operator_dashboard d
    WHERE d.id = p_dashboard_id AND d.scope_id = v_scope_id
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
    w.column_span
  FROM portal.operator_dashboard_widget w
  JOIN portal.operator_view v ON v.id = w.view_id
  WHERE w.dashboard_id = p_dashboard_id
  ORDER BY w.sort_order, v.title;
END;
$$;
