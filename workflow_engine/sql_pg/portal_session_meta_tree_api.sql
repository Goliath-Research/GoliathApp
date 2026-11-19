/*
  Generic tree editor over Meta hierarchical relations.

  A class is tree-shaped when it (or an ancestor) declares a MetaLink with IsHierarchical = true
  whose target is the class itself or one of its ancestors (portal/NavNode.Parent is the first).
  Instance edges are "Meta"."Links" rows (child ObjID1 -> parent ObjID2); "Meta"."TreeNodes"
  keeps the ltree Path (cycle checks in meta_model_tree_maintenance.sql) and, added here, the
  sibling order "Seq".

  Writers require the page entitlement and platform.model.author (record-editor gate) and the
  God Architect role for platform-owned classes (platform/... and portal/...).
  Callable by goliath_portal only (EXECUTE granted by database_gateway_roles.sql).
*/

-- Pages that host the tree editor.
CREATE OR REPLACE FUNCTION portal.fn_meta_tree_nav_paths()
RETURNS text[]
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT ARRAY['/app/meta/trees', '/app/meta/objects', '/app/admin/navigation']::text[];
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_tree_is_platform_class(p_class_name text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_class_name LIKE 'platform/%' OR p_class_name LIKE 'portal/%';
$$;

/* The hierarchical self relation of a class (declared on the class or an ancestor). */
CREATE OR REPLACE FUNCTION portal.fn_meta_tree_link_id(p_class_id integer)
RETURNS integer
LANGUAGE sql
STABLE
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT ml."ID"
  FROM "Meta"."ClassClosure" anc
  JOIN "Meta"."MetaLinks" ml ON ml."ClassID" = anc."AncestorID"
  WHERE anc."DescendantID" = p_class_id
    AND ml."IsHierarchical"
    AND EXISTS (
      SELECT 1 FROM "Meta"."ClassClosure" t
      WHERE t."DescendantID" = p_class_id AND t."AncestorID" = ml."TargetClassID"
    )
  ORDER BY anc."Depth", ml."ID"
  LIMIT 1;
$$;

/* Tree-shaped classes, for the generic UI (which classes get a tree view). */
CREATE OR REPLACE FUNCTION portal.sp_session_meta_tree_classes(p_session_token text)
RETURNS TABLE (class_name text, link_id integer, link_name text, declared_on text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, portal.fn_meta_tree_nav_paths());
  RETURN QUERY
  SELECT c."Name"::text, ml."ID"::int, ml."Name"::text, d."Name"::text
  FROM "Meta"."Classes" c
  CROSS JOIN LATERAL (SELECT portal.fn_meta_tree_link_id(c."ID") AS id) l
  JOIN "Meta"."MetaLinks" ml ON ml."ID" = l.id
  JOIN "Meta"."Classes" d ON d."ID" = ml."ClassID"
  WHERE NOT COALESCE(c."IsAbstract", false)
  ORDER BY c."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_tree_require(
  p_session_token text,
  p_class_name text,
  p_write boolean
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer, class_id integer, link_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_link int;
BEGIN
  IF p_write THEN
    SELECT * INTO v_ctx FROM portal.fn_session_record_editor_require(p_session_token, portal.fn_meta_tree_nav_paths()) LIMIT 1;
    IF portal.fn_meta_tree_is_platform_class(p_class_name) THEN
      PERFORM 1 FROM portal.fn_session_model_author_require_god(p_session_token, '/app/admin/navigation');
    END IF;
  ELSE
    PERFORM portal.fn_session_require_any_nav(p_session_token, portal.fn_meta_tree_nav_paths());
    SELECT r.session_id, r.user_id, r.active_scope_id INTO v_ctx
    FROM portal.fn_session_resolve(p_session_token) r LIMIT 1;
  END IF;

  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = p_class_name;
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', format('class %s not found', p_class_name));
  END IF;
  PERFORM portal.fn_meta_assert_class_action(
    v_ctx.user_id, v_ctx.active_scope_id, v_class_id, CASE WHEN p_write THEN 'update' ELSE 'read' END, v_ctx.session_id
  );
  v_link := portal.fn_meta_tree_link_id(v_class_id);
  IF v_link IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', format('class %s has no hierarchical self relation', p_class_name));
  END IF;
  RETURN QUERY SELECT v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, v_class_id, v_link;
END;
$$;

/* Objects of the class (and subclasses) visible in the active scope, unscoped platform objects included. */
CREATE OR REPLACE FUNCTION portal.fn_meta_tree_members(p_class_id integer, p_scope_id integer)
RETURNS TABLE (obj_id integer)
LANGUAGE sql
STABLE
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT o."ID"
  FROM "Meta"."Objs" o
  JOIN "Meta"."ClassClosure" cc ON cc."DescendantID" = o."ClassID" AND cc."AncestorID" = p_class_id
  WHERE EXISTS (SELECT 1 FROM portal."ScopedMetaObjects" s WHERE s."ObjID" = o."ID" AND s."ScopeID" = p_scope_id)
     OR NOT EXISTS (SELECT 1 FROM portal."ScopedMetaObjects" s WHERE s."ObjID" = o."ID");
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_tree_list(p_session_token text, p_class_name text)
RETURNS TABLE (
  obj_id integer,
  parent_obj_id integer,
  class_name text,
  display_label text,
  seq integer,
  depth integer,
  child_count integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v record;
BEGIN
  SELECT * INTO v FROM portal.fn_meta_tree_require(p_session_token, p_class_name, false) LIMIT 1;
  RETURN QUERY
  WITH m AS (
    SELECT mm.obj_id FROM portal.fn_meta_tree_members(v.class_id, v.active_scope_id) mm
  ),
  par AS (
    SELECT DISTINCT ON (l."ObjID1") l."ObjID1" AS child, l."ObjID2" AS parent
    FROM "Meta"."Links" l
    WHERE l."MetaLinkID" = v.link_id AND l."ObjID1" IS NOT NULL
    ORDER BY l."ObjID1", l."ID"
  )
  SELECT
    o."ID"::int,
    CASE WHEN p.parent IN (SELECT m2.obj_id FROM m m2) THEN p.parent END::int,
    c."Name"::text,
    COALESCE(
      NULLIF(btrim(doc.d->>'Caption'), ''),
      NULLIF(btrim(doc.d->>'Name'), ''),
      NULLIF(btrim(doc.d->>'name'), ''),
      NULLIF(btrim(doc.d->>'Label'), ''),
      NULLIF(btrim(doc.d->>'title'), ''),
      '#' || o."ID"::text
    )::text,
    tn."Seq"::int,
    COALESCE(nlevel(tn."Path") - 1, 0)::int,
    (SELECT count(*)::int FROM par k WHERE k.parent = o."ID")
  FROM m
  JOIN "Meta"."Objs" o ON o."ID" = m.obj_id
  JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
  LEFT JOIN par p ON p.child = o."ID"
  LEFT JOIN "Meta"."TreeNodes" tn ON tn."ObjID" = o."ID" AND tn."MetaLinkID" = v.link_id
  CROSS JOIN LATERAL (SELECT "Meta".fn_merged_obj_document(o."ID") AS d) doc
  ORDER BY tn."Seq" NULLS LAST, o."ID";
END;
$$;

/*
  Move a node under p_parent_obj_id (NULL = root) at sibling position p_position (0-based;
  NULL = last). Reordering within the same parent is a move to the same parent.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_meta_tree_move(
  p_session_token text,
  p_class_name text,
  p_obj_id integer,
  p_parent_obj_id integer,
  p_position integer DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v record;
  v_obj_class int;
  v_parent_class int;
  v_link_type smallint;
  v_link_row int;
  v_siblings int[];
  v_pos int;
  i int;
BEGIN
  SELECT * INTO v FROM portal.fn_meta_tree_require(p_session_token, p_class_name, true) LIMIT 1;

  IF NOT EXISTS (SELECT 1 FROM portal.fn_meta_tree_members(v.class_id, v.active_scope_id) mm WHERE mm.obj_id = p_obj_id) THEN
    PERFORM portal.fn_semantic_raise('GS404', format('node %s is not in this tree', p_obj_id));
  END IF;
  IF p_parent_obj_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM portal.fn_meta_tree_members(v.class_id, v.active_scope_id) mm WHERE mm.obj_id = p_parent_obj_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS404', format('parent %s is not in this tree', p_parent_obj_id));
  END IF;
  IF p_parent_obj_id = p_obj_id THEN
    PERFORM portal.fn_semantic_raise('GS409', 'a node cannot be its own parent');
  END IF;

  SELECT o."ClassID" INTO v_obj_class FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  SELECT l."ID" INTO v_link_row
  FROM "Meta"."Links" l WHERE l."MetaLinkID" = v.link_id AND l."ObjID1" = p_obj_id
  ORDER BY l."ID" LIMIT 1;

  BEGIN
    IF p_parent_obj_id IS NULL THEN
      DELETE FROM "Meta"."Links" l WHERE l."MetaLinkID" = v.link_id AND l."ObjID1" = p_obj_id;
      PERFORM "Meta".sp_tree_attach_child(p_obj_id, NULL, v.link_id);
    ELSE
      -- The parent must have a path before a child can hang under it.
      IF "Meta".fn_tree_path_for_obj(p_parent_obj_id, v.link_id) IS NULL THEN
        PERFORM "Meta".sp_tree_attach_child(p_parent_obj_id, NULL, v.link_id);
      END IF;
      SELECT o."ClassID" INTO v_parent_class FROM "Meta"."Objs" o WHERE o."ID" = p_parent_obj_id;
      IF v_link_row IS NOT NULL THEN
        UPDATE "Meta"."Links" SET "ObjID2" = p_parent_obj_id, "ClassID2" = v_parent_class WHERE "ID" = v_link_row;
      ELSE
        SELECT l."LinkTypeID" INTO v_link_type FROM "Meta"."Links" l WHERE l."MetaLinkID" = v.link_id LIMIT 1;
        IF v_link_type IS NULL THEN
          SELECT lt."ID" INTO v_link_type FROM "Meta"."LinkTypes" lt WHERE lt."Name" = 'meta.TreeHierarchy';
          IF v_link_type IS NULL THEN
            INSERT INTO "Meta"."LinkTypes" ("Name") VALUES ('meta.TreeHierarchy') RETURNING "ID" INTO v_link_type;
          END IF;
        END IF;
        INSERT INTO "Meta"."Links" ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
        VALUES ('tree-parent-' || p_obj_id::text, v_obj_class, v_parent_class, v_link_type, v.link_id, p_obj_id, p_parent_obj_id);
      END IF;
    END IF;
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM LIKE '%cycle%' THEN
      PERFORM portal.fn_semantic_raise('GS409', 'cannot move a node under its own descendant');
    END IF;
    RAISE;
  END;

  -- Renumber the new siblings with the node at the requested position.
  SELECT array_agg(s.obj_id ORDER BY s.seq NULLS LAST, s.obj_id) INTO v_siblings
  FROM (
    SELECT mm.obj_id, tn."Seq" AS seq
    FROM portal.fn_meta_tree_members(v.class_id, v.active_scope_id) mm
    LEFT JOIN "Meta"."TreeNodes" tn ON tn."ObjID" = mm.obj_id AND tn."MetaLinkID" = v.link_id
    LEFT JOIN LATERAL (
      SELECT l."ObjID2" AS parent FROM "Meta"."Links" l
      WHERE l."MetaLinkID" = v.link_id AND l."ObjID1" = mm.obj_id ORDER BY l."ID" LIMIT 1
    ) p ON true
    WHERE p.parent IS NOT DISTINCT FROM p_parent_obj_id AND mm.obj_id <> p_obj_id
  ) s;
  v_siblings := COALESCE(v_siblings, ARRAY[]::int[]);
  v_pos := LEAST(GREATEST(COALESCE(p_position, cardinality(v_siblings)), 0), cardinality(v_siblings));
  v_siblings := v_siblings[1:v_pos] || p_obj_id || v_siblings[v_pos + 1:];

  FOR i IN 1 .. cardinality(v_siblings) LOOP
    IF "Meta".fn_tree_path_for_obj(v_siblings[i], v.link_id) IS NULL THEN
      PERFORM "Meta".sp_tree_attach_child(v_siblings[i], NULL, v.link_id);
    END IF;
    UPDATE "Meta"."TreeNodes" SET "Seq" = i * 10
    WHERE "ObjID" = v_siblings[i] AND "MetaLinkID" = v.link_id AND "Seq" IS DISTINCT FROM i * 10;
  END LOOP;

  PERFORM portal.fn_record_editor_audit(
    v.session_id, v.user_id, v.active_scope_id, 'meta_tree', 'move', p_obj_id::text,
    jsonb_build_object('class_name', p_class_name, 'parent_obj_id', p_parent_obj_id, 'position', v_pos)
  );
  RETURN v_pos;
END;
$$;

/* Delete a leaf node. Nodes with children, or still referenced elsewhere, are refused. */
CREATE OR REPLACE FUNCTION portal.sp_session_meta_tree_delete(
  p_session_token text,
  p_class_name text,
  p_obj_id integer
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v record;
BEGIN
  SELECT * INTO v FROM portal.fn_meta_tree_require(p_session_token, p_class_name, true) LIMIT 1;
  IF NOT EXISTS (SELECT 1 FROM portal.fn_meta_tree_members(v.class_id, v.active_scope_id) mm WHERE mm.obj_id = p_obj_id) THEN
    PERFORM portal.fn_semantic_raise('GS404', format('node %s is not in this tree', p_obj_id));
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."Links" l WHERE l."MetaLinkID" = v.link_id AND l."ObjID2" = p_obj_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'node has children; move or delete them first');
  END IF;
  IF EXISTS (
    SELECT 1 FROM "Meta"."Links" l
    WHERE l."ObjID2" = p_obj_id AND l."MetaLinkID" IS DISTINCT FROM v.link_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'other objects link to this node');
  END IF;
  BEGIN
    DELETE FROM "Meta"."Links" l WHERE l."ObjID1" = p_obj_id;
    DELETE FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  EXCEPTION WHEN foreign_key_violation THEN
    PERFORM portal.fn_semantic_raise('GS409', 'node is still referenced (' || COALESCE(SQLERRM, '') || ')');
  END;
  PERFORM portal.fn_record_editor_audit(
    v.session_id, v.user_id, v.active_scope_id, 'meta_tree', 'delete', p_obj_id::text,
    jsonb_build_object('class_name', p_class_name)
  );
  RETURN 'deleted';
END;
$$;
