/*
  Session-bound Meta APIs (P2).
  Callable by goliath_portal only — platform host BFF forwards session cookie server-side.

  Authorization: valid session is necessary but not sufficient — Meta permissions are enforced.
*/

DO $meta_perm_seed$
DECLARE
  v_class_id int;
  v_obj_id int;
  v_op_id int;
  v_perm_name text;
BEGIN
  SELECT c."ID" INTO v_class_id
  FROM "Meta"."Classes" c
  WHERE c."Name" = 'portal/NavNode'
  LIMIT 1;

  IF v_class_id IS NULL THEN
    RAISE NOTICE 'meta permission seed skipped — portal/NavNode class missing';
    RETURN;
  END IF;

  SELECT o."ID" INTO v_obj_id FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1;
  IF v_obj_id IS NULL THEN
    INSERT INTO "Meta"."Objs" ("ClassID") VALUES (v_class_id)
    RETURNING "ID" INTO v_obj_id;
  END IF;

  SELECT op."ID" INTO v_op_id
  FROM "Meta"."Operations" op
  WHERE op."Name" = 'meta.permission_anchor'
  LIMIT 1;

  IF v_op_id IS NULL THEN
    INSERT INTO "Meta"."Operations" ("Name", "ClassID")
    VALUES ('meta.permission_anchor', v_class_id)
    RETURNING "ID" INTO v_op_id;
  END IF;

  FOREACH v_perm_name IN ARRAY ARRAY[
    'meta.schema.read',
    'meta.object.read',
    'meta.object.write'
  ]
  LOOP
    INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
    SELECT v_perm_name, v_obj_id, v_op_id
    WHERE NOT EXISTS (
      SELECT 1 FROM "RBAC"."Permissions" p WHERE p."Name" = v_perm_name
    );
  END LOOP;
END
$meta_perm_seed$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_require(
  p_session_token text,
  p_permission text
)
RETURNS TABLE (
  session_id integer,
  user_id integer,
  active_scope_id integer
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

  IF NOT portal.fn_semantic_session_has_permission(v_sess.user_id, p_permission) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

/*
  Instance data tenancy (generic GoliathApp contract):
  - Meta schema/classes remain global catalog reads (meta.schema.read).
  - Mutable instances created through session APIs are bound to the session active scope.
  - Legacy/catalog Meta.Objs without a portal.ScopedMetaObjects row are not exposed via instance APIs.
*/
CREATE TABLE IF NOT EXISTS portal."ScopedMetaObjects" (
  "ObjID" integer NOT NULL,
  "ScopeID" integer NOT NULL,
  "CreatedAtUtc" timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "PK_portal_ScopedMetaObjects" PRIMARY KEY ("ObjID"),
  CONSTRAINT "FK_portal_ScopedMetaObjects_Obj" FOREIGN KEY ("ObjID")
    REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE,
  CONSTRAINT "FK_portal_ScopedMetaObjects_Scope" FOREIGN KEY ("ScopeID")
    REFERENCES "RBAC"."Scopes" ("ScopeID")
);

CREATE INDEX IF NOT EXISTS "IX_portal_ScopedMetaObjects_ScopeID"
  ON portal."ScopedMetaObjects" ("ScopeID");

CREATE OR REPLACE FUNCTION portal.fn_session_meta_permission_in_active_scope(
  p_user_id integer,
  p_permission text,
  p_active_scope_id integer
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT
    p_active_scope_id IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM "RBAC"."UserRoleGrants" g
      INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
      INNER JOIN "RBAC"."Role_Permissions" rp ON rp."RoleID" = g."RoleID"
      INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
      WHERE g."UserID" = p_user_id
        AND g."Active"
        AND p."Name" = p_permission
        AND (
          COALESCE(r."BypassScope", false)
          OR g."ScopeID" = p_active_scope_id
        )
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_require_instance(
  p_session_token text,
  p_permission text
)
RETURNS TABLE (
  session_id integer,
  user_id integer,
  active_scope_id integer
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

  IF v_sess.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for meta instance access');
  END IF;

  IF NOT portal.fn_session_meta_permission_in_active_scope(
    v_sess.user_id,
    p_permission,
    v_sess.active_scope_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied for active scope');
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

/*
  Identity-independent permissions for instance writes — must run before any ObjID lookup
  (sp_session_meta_obj_update previously checked meta.schema.read after scope assert → oracle).
*/
CREATE OR REPLACE FUNCTION portal.fn_session_meta_require_instance_write(
  p_session_token text
)
RETURNS TABLE (
  session_id integer,
  user_id integer,
  active_scope_id integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_meta_require_instance(p_session_token, 'meta.object.write') LIMIT 1;
  PERFORM portal.fn_session_meta_require(p_session_token, 'meta.schema.read');
  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_strip_tenancy_keys(p_document jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_key text;
BEGIN
  FOREACH v_key IN ARRAY ARRAY[
    'ScopeID', 'scopeId', 'scope_id',
    'OrganizationID', 'organizationId', 'organization_id',
    'OwnerScopeID', 'ownerScopeId', 'owner_scope_id',
    '__scope', '_scope', 'tenantScopeId', 'TenantScopeID'
  ]
  LOOP
    IF v_doc ? v_key THEN
      v_doc := v_doc - v_key;
    END IF;
  END LOOP;
  RETURN v_doc;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_assert_obj_in_active_scope(
  p_obj_id integer,
  p_active_scope_id integer
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_scope_id int;
BEGIN
  SELECT sm."ScopeID"
  INTO v_scope_id
  FROM portal."ScopedMetaObjects" sm
  WHERE sm."ObjID" = p_obj_id;

  IF v_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta object not found');
  END IF;

  IF v_scope_id IS DISTINCT FROM p_active_scope_id THEN
    -- Same SQLSTATE + message as missing/unmapped rows (no cross-tenant existence oracle).
    PERFORM portal.fn_semantic_raise('GS404', 'meta object not found');
  END IF;
END;
$$;

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
  v_class_id int;
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require(p_session_token, 'meta.schema.read') LIMIT 1;

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
#variable_conflict use_column
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

DROP FUNCTION IF EXISTS portal.sp_session_meta_class_fields(text, text);

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_fields(
  p_session_token text,
  p_class_name text
)
RETURNS TABLE (
  field_name text,
  type_id bigint,
  type_name text,
  type_kind text,
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
    dt.kind::text,
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
BEGIN
  PERFORM portal.fn_session_meta_require(p_session_token, 'meta.schema.read');

  RETURN QUERY
  SELECT * FROM portal.sp_get_data_type(p_name, p_version);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_insert(
  p_session_token text,
  p_class_name text,
  p_document jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_obj_id int;
  v_doc jsonb;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance_write(p_session_token) LIMIT 1;

  v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
  v_doc := portal.fn_session_meta_strip_tenancy_keys(p_document);
  v_obj_id := "Meta".sp_obj_insert(v_class_id, COALESCE(v_doc, '{}'::jsonb));

  INSERT INTO portal."ScopedMetaObjects" ("ObjID", "ScopeID")
  VALUES (v_obj_id, v_ctx.active_scope_id);

  RETURN v_obj_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_update(
  p_session_token text,
  p_obj_id integer,
  p_document jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance_write(p_session_token) LIMIT 1;

  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);

  v_doc := portal.fn_session_meta_strip_tenancy_keys(p_document);
  PERFORM "Meta".sp_obj_update(p_obj_id, COALESCE(v_doc, '{}'::jsonb));
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_get(
  p_session_token text,
  p_obj_id integer
)
RETURNS TABLE (
  obj_id integer,
  class_id integer,
  class_name text,
  document jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance(p_session_token, 'meta.object.read') LIMIT 1;

  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);

  RETURN QUERY
  SELECT
    o."ID"::integer,
    o."ClassID"::integer,
    c."Name"::text,
    "Meta".fn_merged_obj_document(o."ID")
  FROM "Meta"."Objs" o
  JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
  WHERE o."ID" = p_obj_id;
END;
$$;
