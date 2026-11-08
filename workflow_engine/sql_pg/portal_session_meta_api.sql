/*
  Session-bound Meta class read APIs (P2 foundation).
  Callable by goliath_portal only — platform host BFF forwards session cookie server-side.

  P2 slice: read-only hierarchy, resolved fields, flattened JSON Schema, wrapped data types.
  Fine-grained Meta RBAC permissions are not enforced yet (valid session required).
*/

CREATE OR REPLACE FUNCTION portal.sp_session_meta_resolve_class(
  p_session_token text,
  p_class_name text
)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_class_id int;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  SELECT c."ID"
  INTO v_class_id
  FROM "Meta"."Classes" c
  WHERE c."Name" = p_class_name
  LIMIT 1;

  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;

  RETURN v_class_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_get(
  p_session_token text,
  p_class_name text
)
RETURNS TABLE (
  class_id integer,
  class_name text,
  parent_id integer,
  parent_name text,
  depth integer,
  is_abstract boolean,
  catalog_type_name text,
  schema_flattened_json jsonb,
  schema_bundled_json jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_class_id int;
BEGIN
  v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);

  RETURN QUERY
  SELECT
    c."ID"::integer,
    c."Name"::text,
    c."ParentID"::integer,
    p."Name"::text,
    c."Depth"::integer,
    c."IsAbstract",
    ('meta/class/' || c."Name")::text,
    "Meta".fn_class_json_schema_flattened(v_class_id),
    "Meta".fn_class_json_schema_bundled(v_class_id)
  FROM "Meta"."Classes" c
  LEFT JOIN "Meta"."Classes" p ON p."ID" = c."ParentID"
  WHERE c."ID" = v_class_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_lineage(
  p_session_token text,
  p_class_name text
)
RETURNS TABLE (
  lineage_role text,
  class_id integer,
  class_name text,
  parent_id integer,
  depth integer,
  relation_depth integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_class_id int;
BEGIN
  v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);

  RETURN QUERY
  SELECT
    u.lineage_role,
    u.class_id,
    u.class_name,
    u.parent_id,
    u.depth,
    u.relation_depth
  FROM (
    SELECT
      'ancestor'::text AS lineage_role,
      c."ID"::integer,
      c."Name"::text,
      c."ParentID"::integer,
      c."Depth"::integer,
      cc."Depth"::integer
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."Classes" c ON c."ID" = cc."AncestorID"
  WHERE cc."DescendantID" = v_class_id AND cc."Depth" > 0

    UNION ALL

    SELECT
      'self'::text AS lineage_role,
      c."ID"::integer,
      c."Name"::text,
      c."ParentID"::integer,
      c."Depth"::integer,
      0::integer
    FROM "Meta"."Classes" c
    WHERE c."ID" = v_class_id

    UNION ALL

    SELECT
      'descendant'::text AS lineage_role,
      c."ID"::integer,
      c."Name"::text,
      c."ParentID"::integer,
      c."Depth"::integer,
      cc."Depth"::integer
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."Classes" c ON c."ID" = cc."DescendantID"
    WHERE cc."AncestorID" = v_class_id AND cc."Depth" > 0
  ) AS u(
    lineage_role,
    class_id,
    class_name,
    parent_id,
    depth,
    relation_depth
  )
  ORDER BY
    CASE u.lineage_role WHEN 'ancestor' THEN 0 WHEN 'self' THEN 1 ELSE 2 END,
    u.relation_depth,
    u.class_name;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_fields(
  p_session_token text,
  p_class_name text
)
RETURNS TABLE (
  field_name text,
  type_id bigint,
  type_name text,
  required boolean,
  declared_on_class_id integer,
  declared_on_class_name text,
  defined_at_depth integer,
  is_local boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_class_id int;
BEGIN
  v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);

  RETURN QUERY
  SELECT
    fr."Name"::text,
    fr."TypeID"::bigint,
    dt.name::text,
  COALESCE(fr."Required", false),
    fr."DeclaredOnClassID"::integer,
    dc."Name"::text,
    fr."DefinedAtDepth"::integer,
    (fr."DeclaredOnClassID" = v_class_id)
  FROM "Meta"."VClassFieldsResolved" fr
  JOIN "Meta"."Classes" dc ON dc."ID" = fr."DeclaredOnClassID"
  LEFT JOIN wf.data_type dt ON dt.id = fr."TypeID"
  WHERE fr."ClassID" = v_class_id
  ORDER BY fr."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_data_type(
  p_session_token text,
  p_name text,
  p_version text DEFAULT NULL
)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  kind text,
  element_type_id bigint,
  element_type_name text,
  content_hash text,
  created_at_utc timestamptz,
  updated_at_utc timestamptz,
  schema_json jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  RETURN QUERY
  SELECT * FROM portal.sp_get_data_type(p_name, p_version);
END;
$$;
