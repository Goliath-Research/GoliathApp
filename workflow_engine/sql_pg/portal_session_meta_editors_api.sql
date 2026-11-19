/*
  Session-gated record editors for the Meta model: classes, fields and relations (MetaLinks).
  Callable by goliath_portal only. Every writer:
    - requires the page entitlement and platform.model.author (record-editor gate),
    - requires God Architect when the class is platform/... (for relations: the source class),
    - writes one row to portal.record_editor_audit.

  Deletes never remove instance data: a class is deleted only when it has no subclasses,
  objects, fields, methods or relations; a field only when no object holds a value for it;
  a relation only when no instance link or tree node uses it. Applied after
  platform_god_architect.sql.
*/

CREATE OR REPLACE FUNCTION portal.fn_meta_editor_require(
  p_session_token text,
  p_node_path text,
  p_class_name text
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY[p_node_path])
  LIMIT 1;
  IF COALESCE(p_class_name, '') LIKE 'platform/%' THEN
    PERFORM 1 FROM portal.fn_session_model_author_require_god(p_session_token, NULL);
  END IF;
  RETURN QUERY SELECT v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_editor_class_id(p_class_name text)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_id integer;
BEGIN
  SELECT c."ID" INTO v_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(coalesce(p_class_name, ''));
  IF v_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', format('meta class %s not found', coalesce(p_class_name, '')));
  END IF;
  RETURN v_id;
END;
$$;

-- ── Classes ───────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_list_classes(p_session_token text)
RETURNS TABLE (
  class_id integer, class_name text, parent_class_name text, is_abstract boolean, depth integer,
  field_count integer, method_count integer, link_count integer, subclass_count integer,
  object_count integer, is_platform boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/classes']);
  RETURN QUERY
  SELECT c."ID", c."Name"::text, p."Name"::text, c."IsAbstract", c."Depth",
         (SELECT count(*)::int FROM "Meta"."Fields" f WHERE f."ClassID" = c."ID"),
         (SELECT count(*)::int FROM "Meta"."Methods" m WHERE m."ClassID" = c."ID"),
         (SELECT count(*)::int FROM "Meta"."MetaLinks" l WHERE l."ClassID" = c."ID" OR l."TargetClassID" = c."ID"),
         (SELECT count(*)::int FROM "Meta"."Classes" s WHERE s."ParentID" = c."ID"),
         (SELECT count(*)::int FROM "Meta"."Objs" o WHERE o."ClassID" = c."ID"),
         c."Name" LIKE 'platform/%'
  FROM "Meta"."Classes" c
  LEFT JOIN "Meta"."Classes" p ON p."ID" = c."ParentID"
  ORDER BY c."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_get_class(p_session_token text, p_class_name text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/classes']);
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'class_name', c."Name", 'parent_class_name', p."Name", 'is_abstract', c."IsAbstract"
  ))
  INTO v
  FROM "Meta"."Classes" c
  LEFT JOIN "Meta"."Classes" p ON p."ID" = c."ParentID"
  WHERE c."Name" = p_class_name;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_save_class(
  p_session_token text,
  p_class_name text,
  p_doc jsonb
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_name text := COALESCE(NULLIF(btrim(p_class_name), ''), btrim(coalesce(p_doc->>'class_name', '')));
  v_parent text := portal.fn_doc_text(p_doc, 'parent_class_name');
  v_abstract boolean := COALESCE((p_doc->>'is_abstract')::boolean, false);
  v_id integer;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/classes', v_name) LIMIT 1;
  IF p_class_name IS NULL THEN
    IF v_name !~ '^[a-z][a-z0-9_]*(/[A-Za-z][A-Za-z0-9_]*)+$' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'class name must look like namespace/ClassName');
    END IF;
    IF v_parent IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'pick a parent class');
    END IF;
    -- Existing writer: hierarchy, class type and views.
    SELECT r.class_id INTO v_id FROM portal.sp_session_meta_class_create(p_session_token, v_name, v_parent) r;
    IF v_abstract THEN
      UPDATE "Meta"."Classes" SET "IsAbstract" = true WHERE "ID" = v_id;
    END IF;
  ELSE
    v_id := portal.fn_meta_editor_class_id(v_name);
    PERFORM 1 FROM "Meta"."Classes" c WHERE c."ID" = v_id FOR UPDATE;
    IF v_parent IS DISTINCT FROM (
      SELECT p."Name"::text FROM "Meta"."Classes" c JOIN "Meta"."Classes" p ON p."ID" = c."ParentID" WHERE c."ID" = v_id
    ) AND p_doc ? 'parent_class_name' THEN
      PERFORM portal.fn_semantic_raise('GS409', 'a class is not re-parented here');
    END IF;
    IF v_abstract AND EXISTS (SELECT 1 FROM "Meta"."Objs" o WHERE o."ClassID" = v_id) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'class has objects; it cannot become abstract');
    END IF;
    UPDATE "Meta"."Classes" SET "IsAbstract" = v_abstract WHERE "ID" = v_id;
  END IF;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_class',
    CASE WHEN p_class_name IS NULL THEN 'create' ELSE 'update' END, v_name,
    jsonb_strip_nulls(jsonb_build_object('parent', v_parent, 'is_abstract', v_abstract))
  );
  RETURN v_name;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_delete_class(p_session_token text, p_class_name text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_id integer;
  v_view text;
  v_constraint text;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/classes', p_class_name) LIMIT 1;
  v_id := portal.fn_meta_editor_class_id(p_class_name);
  PERFORM 1 FROM "Meta"."Classes" c WHERE c."ID" = v_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM "Meta"."Classes" s WHERE s."ParentID" = v_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'class has subclasses; delete them first');
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."Objs" o WHERE o."ClassID" = v_id)
     OR EXISTS (SELECT 1 FROM "Meta"."ObjValues" ov WHERE ov."ClassID" = v_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'class has objects; it is not deleted');
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_id)
     OR EXISTS (SELECT 1 FROM "Meta"."Methods" m WHERE m."ClassID" = v_id)
     OR EXISTS (SELECT 1 FROM "Meta"."MetaLinks" l WHERE l."ClassID" = v_id OR l."TargetClassID" = v_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'class still declares fields, methods or relations; remove them first');
  END IF;
  IF EXISTS (SELECT 1 FROM portal.semantic_entity e WHERE e.meta_class_id = v_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'class is mapped to a semantic entity');
  END IF;

  v_view := "Meta".fn_class_view_name(v_id);
  BEGIN
    -- The class's own published type goes with it (only when nothing else uses that type).
    UPDATE "Meta"."Classes" SET "TypeID" = NULL WHERE "ID" = v_id;
    DELETE FROM wf.data_type t WHERE t.class_id = v_id;
    DELETE FROM portal."MetaClassRoleAccess" a WHERE a."ClassID" = v_id;
    DELETE FROM "Meta"."Classes" c WHERE c."ID" = v_id;
  EXCEPTION WHEN foreign_key_violation THEN
    GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
    PERFORM portal.fn_semantic_raise('GS409', format('class is still referenced (%s)', coalesce(v_constraint, 'foreign key')));
  END;
  IF v_view IS NOT NULL THEN
    EXECUTE format('DROP VIEW IF EXISTS "Meta".%I', v_view);
  END IF;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_class', 'delete', p_class_name, '{}'::jsonb
  );
  RETURN 'deleted';
END;
$$;

-- ── Fields ────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_list_fields(p_session_token text)
RETURNS TABLE (
  field_id integer, class_name text, field_name text, type_id bigint, type_name text,
  required boolean, description text, value_count integer, is_platform boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/fields']);
  RETURN QUERY
  SELECT f."ID", c."Name"::text, f."Name", f."TypeID", t.name || '@' || t.version, f."Required", f."Description",
         (SELECT count(*)::int FROM "Meta"."ObjValues" ov WHERE ov."ClassID" = c."ID" AND ov."Data" ? f."Name"),
         c."Name" LIKE 'platform/%'
  FROM "Meta"."Fields" f
  JOIN "Meta"."Classes" c ON c."ID" = f."ClassID"
  JOIN wf.data_type t ON t.id = f."TypeID"
  ORDER BY c."Name", f."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_get_field(p_session_token text, p_field_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/fields']);
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'class_name', c."Name", 'field_name', f."Name", 'type_id', f."TypeID",
    'required', f."Required", 'description', f."Description"
  ))
  INTO v
  FROM "Meta"."Fields" f JOIN "Meta"."Classes" c ON c."ID" = f."ClassID"
  WHERE f."ID" = p_field_id;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta field not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_save_field(
  p_session_token text,
  p_field_id integer,
  p_doc jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id integer;
  v_class text;
  v_name text;
  v_old_type bigint;
  v_type_id bigint := NULLIF(p_doc->>'type_id', '')::bigint;
  v_required boolean := COALESCE((p_doc->>'required')::boolean, false);
  v_desc text := portal.fn_doc_text(p_doc, 'description');
  v_id integer;
BEGIN
  IF p_field_id IS NOT NULL THEN
    SELECT f."ClassID", f."Name", f."TypeID", c."Name"::text
    INTO v_class_id, v_name, v_old_type, v_class
    FROM "Meta"."Fields" f JOIN "Meta"."Classes" c ON c."ID" = f."ClassID"
    WHERE f."ID" = p_field_id
    FOR UPDATE OF f;
    IF v_class_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'meta field not found');
    END IF;
  ELSE
    v_class := btrim(coalesce(p_doc->>'class_name', ''));
    v_name := btrim(coalesce(p_doc->>'field_name', ''));
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/fields', v_class) LIMIT 1;
  IF p_field_id IS NULL THEN
    v_class_id := portal.fn_meta_editor_class_id(v_class);
    IF v_name !~ '^[A-Za-z][A-Za-z0-9_]{0,62}$' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'field name must be letters, digits and underscores');
    END IF;
    -- A field name is unique along the inheritance line (no shadowing).
    IF EXISTS (
      SELECT 1 FROM "Meta"."Fields" f
      JOIN "Meta"."ClassClosure" cc
        ON (cc."AncestorID" = f."ClassID" AND cc."DescendantID" = v_class_id)
        OR (cc."DescendantID" = f."ClassID" AND cc."AncestorID" = v_class_id)
      WHERE f."Name" = v_name
    ) THEN
      PERFORM portal.fn_semantic_raise('GS409', format('field %s already exists on this class, an ancestor or a subclass', v_name));
    END IF;
  END IF;
  IF v_type_id IS NULL OR NOT EXISTS (
    SELECT 1 FROM wf.data_type t WHERE t.id = v_type_id AND t.status IS DISTINCT FROM 'retired'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick a data type');
  END IF;

  IF p_field_id IS NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    VALUES (v_class_id, v_name, v_type_id, v_required, v_desc)
    RETURNING "ID" INTO v_id;
  ELSE
    UPDATE "Meta"."Fields"
    SET "TypeID" = v_type_id, "Required" = v_required, "Description" = v_desc
    WHERE "ID" = p_field_id;
    v_id := p_field_id;
  END IF;
  -- A type change with stored values is a breaking change of the class type.
  PERFORM "Meta".sp_meta_publish_class_type(
    v_class_id,
    p_field_id IS NOT NULL AND v_old_type IS DISTINCT FROM v_type_id
      AND EXISTS (SELECT 1 FROM "Meta"."ObjValues" ov WHERE ov."ClassID" = v_class_id AND ov."Data" ? v_name)
  );
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_field',
    CASE WHEN p_field_id IS NULL THEN 'create' ELSE 'update' END, v_id::text,
    jsonb_build_object('class_name', v_class, 'field_name', v_name, 'type_id', v_type_id, 'required', v_required)
  );
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_delete_field(p_session_token text, p_field_id integer)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id integer;
  v_class text;
  v_name text;
BEGIN
  SELECT f."ClassID", f."Name", c."Name"::text INTO v_class_id, v_name, v_class
  FROM "Meta"."Fields" f JOIN "Meta"."Classes" c ON c."ID" = f."ClassID"
  WHERE f."ID" = p_field_id
  FOR UPDATE OF f;
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta field not found');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/fields', v_class) LIMIT 1;
  IF EXISTS (SELECT 1 FROM "Meta"."ObjValues" ov WHERE ov."ClassID" = v_class_id AND ov."Data" ? v_name) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'objects hold values for this field; it is not deleted');
  END IF;
  DELETE FROM "Meta"."Fields" f WHERE f."ID" = p_field_id;
  PERFORM "Meta".sp_meta_publish_class_type(v_class_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_field', 'delete', p_field_id::text,
    jsonb_build_object('class_name', v_class, 'field_name', v_name)
  );
  RETURN 'deleted';
END;
$$;

/* The older field retire API: same God Architect rule for platform/... classes. */
CREATE OR REPLACE FUNCTION portal.sp_session_meta_field_retire(
  p_session_token text,
  p_class_name text,
  p_field_name text
)
RETURNS TABLE (ok boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
BEGIN
  IF btrim(coalesce(p_class_name, '')) LIKE 'platform/%' THEN
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/meta/classes') LIMIT 1;
  ELSE
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/classes') LIMIT 1;
  END IF;
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;
  DELETE FROM "Meta"."Fields" f
  WHERE f."ClassID" = v_class_id AND f."Name" = btrim(p_field_name);

  PERFORM "Meta".sp_meta_publish_class_type(v_class_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);
  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'meta.field.retire',
    jsonb_build_object('class_name', p_class_name, 'field_name', p_field_name)
  );
  RETURN QUERY SELECT true;
END;
$$;

-- ── Relations (MetaLinks) ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_list_links(p_session_token text)
RETURNS TABLE (
  link_id integer, class_name text, link_name text, target_class_name text, min_card integer,
  max_card integer, is_hierarchical boolean, inverse_name text, instance_count integer, is_platform boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/relations']);
  RETURN QUERY
  SELECT l."ID", c."Name"::text, l."Name", t."Name"::text, l."MinCard", l."MaxCard", l."IsHierarchical",
         i."Name",
         (SELECT count(*)::int FROM "Meta"."Links" x WHERE x."MetaLinkID" = l."ID")
           + (SELECT count(*)::int FROM "Meta"."TreeNodes" n WHERE n."MetaLinkID" = l."ID"),
         c."Name" LIKE 'platform/%'
  FROM "Meta"."MetaLinks" l
  JOIN "Meta"."Classes" c ON c."ID" = l."ClassID"
  JOIN "Meta"."Classes" t ON t."ID" = l."TargetClassID"
  LEFT JOIN "Meta"."MetaLinks" i ON i."ID" = l."InverseID"
  ORDER BY c."Name", l."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_get_link(p_session_token text, p_link_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/meta/relations']);
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'class_name', c."Name", 'link_name', l."Name", 'target_class_name', t."Name",
    'min_card', l."MinCard", 'max_card', l."MaxCard", 'is_hierarchical', l."IsHierarchical"
  ))
  INTO v
  FROM "Meta"."MetaLinks" l
  JOIN "Meta"."Classes" c ON c."ID" = l."ClassID"
  JOIN "Meta"."Classes" t ON t."ID" = l."TargetClassID"
  WHERE l."ID" = p_link_id;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'relation not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_save_link(
  p_session_token text,
  p_link_id integer,
  p_doc jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_row "Meta"."MetaLinks"%ROWTYPE;
  v_class text;
  v_class_id integer;
  v_target_id integer;
  v_name text;
  v_min integer := COALESCE(NULLIF(p_doc->>'min_card', '')::integer, 0);
  v_max integer := NULLIF(p_doc->>'max_card', '')::integer;
  v_hier boolean := COALESCE((p_doc->>'is_hierarchical')::boolean, false);
  v_id integer;
BEGIN
  IF p_link_id IS NOT NULL THEN
    SELECT * INTO v_row FROM "Meta"."MetaLinks" l WHERE l."ID" = p_link_id FOR UPDATE;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'relation not found');
    END IF;
    SELECT c."Name"::text INTO v_class FROM "Meta"."Classes" c WHERE c."ID" = v_row."ClassID";
  ELSE
    v_class := btrim(coalesce(p_doc->>'class_name', ''));
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/relations', v_class) LIMIT 1;

  IF v_min < 0 OR (v_max IS NOT NULL AND v_max < v_min) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'cardinality must satisfy 0 <= min <= max');
  END IF;

  IF p_link_id IS NULL THEN
    v_class_id := portal.fn_meta_editor_class_id(v_class);
    v_target_id := portal.fn_meta_editor_class_id(p_doc->>'target_class_name');
    v_name := btrim(coalesce(p_doc->>'link_name', ''));
    IF v_name !~ '^[A-Za-z][A-Za-z0-9_]{0,62}$' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'relation name must be letters, digits and underscores');
    END IF;
    IF EXISTS (SELECT 1 FROM "Meta"."MetaLinks" l WHERE l."ClassID" = v_class_id AND l."Name" = v_name) THEN
      PERFORM portal.fn_semantic_raise('GS409', format('relation %s already exists on this class', v_name));
    END IF;
    INSERT INTO "Meta"."MetaLinks" ("ClassID", "Name", "TargetClassID", "MinCard", "MaxCard", "IsHierarchical")
    VALUES (v_class_id, v_name, v_target_id, v_min, v_max, v_hier)
    RETURNING "ID" INTO v_id;
  ELSE
    v_id := p_link_id;
    v_name := v_row."Name";
    IF v_hier IS DISTINCT FROM v_row."IsHierarchical"
       AND (EXISTS (SELECT 1 FROM "Meta"."TreeNodes" n WHERE n."MetaLinkID" = v_id)
            OR EXISTS (SELECT 1 FROM "Meta"."Links" x WHERE x."MetaLinkID" = v_id)) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'relation has instances; hierarchical cannot change');
    END IF;
    IF v_max IS NOT NULL AND EXISTS (
      SELECT 1 FROM "Meta"."Links" x WHERE x."MetaLinkID" = v_id
      GROUP BY x."ObjID1" HAVING count(*) > v_max
    ) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'existing links exceed the new maximum');
    END IF;
    UPDATE "Meta"."MetaLinks" SET "MinCard" = v_min, "MaxCard" = v_max, "IsHierarchical" = v_hier
    WHERE "ID" = v_id;
  END IF;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_link',
    CASE WHEN p_link_id IS NULL THEN 'create' ELSE 'update' END, v_id::text,
    jsonb_strip_nulls(jsonb_build_object('class_name', v_class, 'link_name', v_name, 'min', v_min, 'max', v_max))
  );
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_editor_delete_link(p_session_token text, p_link_id integer)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class text;
  v_name text;
BEGIN
  SELECT c."Name"::text, l."Name" INTO v_class, v_name
  FROM "Meta"."MetaLinks" l JOIN "Meta"."Classes" c ON c."ID" = l."ClassID"
  WHERE l."ID" = p_link_id
  FOR UPDATE OF l;
  IF v_class IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'relation not found');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_meta_editor_require(p_session_token, '/app/meta/relations', v_class) LIMIT 1;
  IF EXISTS (SELECT 1 FROM "Meta"."Links" x WHERE x."MetaLinkID" = p_link_id)
     OR EXISTS (SELECT 1 FROM "Meta"."TreeNodes" n WHERE n."MetaLinkID" = p_link_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'relation has instance links; it is not deleted');
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."MetaLinks" l WHERE l."InverseID" = p_link_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'another relation names this one as its inverse');
  END IF;
  DELETE FROM "Meta"."MetaLinks" l WHERE l."ID" = p_link_id;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta_link', 'delete', p_link_id::text,
    jsonb_build_object('class_name', v_class, 'link_name', v_name)
  );
  RETURN 'deleted';
END;
$$;
