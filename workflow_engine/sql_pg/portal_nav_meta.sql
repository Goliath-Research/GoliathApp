-- Portal navigation on Meta hierarchical Tree links (platform NavNode class).
-- Legacy portal."NavTree" + Role2Node remain the RBAC compatibility surface; MetaObjID bridges rows.

ALTER TABLE portal."NavTree"
  ADD COLUMN IF NOT EXISTS "MetaObjID" integer NULL;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_NavTree_MetaObj') THEN
    ALTER TABLE portal."NavTree"
      ADD CONSTRAINT "FK_NavTree_MetaObj"
      FOREIGN KEY ("MetaObjID") REFERENCES "Meta"."Objs" ("ID")
      ON DELETE SET NULL;
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$fk$;

CREATE UNIQUE INDEX IF NOT EXISTS "UX_NavTree_MetaObjID"
  ON portal."NavTree" ("MetaObjID")
  WHERE "MetaObjID" IS NOT NULL;

CREATE OR REPLACE FUNCTION portal.fn_nav_node_class_id()
RETURNS int
LANGUAGE sql
STABLE
AS $$
  SELECT c."ID"
  FROM "Meta"."Classes" c
  WHERE c."Name" = 'portal/NavNode'
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_nav_parent_metalink_id()
RETURNS int
LANGUAGE sql
STABLE
AS $$
  SELECT ml."ID"
  FROM "Meta"."MetaLinks" ml
  JOIN "Meta"."Classes" c ON c."ID" = ml."ClassID"
  WHERE c."Name" = 'portal/NavNode'
    AND ml."Name" = 'Parent'
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_nav_hierarchy_link_type_id()
RETURNS smallint
LANGUAGE sql
STABLE
AS $$
  SELECT lt."ID"
  FROM "Meta"."LinkTypes" lt
  WHERE lt."Name" = 'portal.NavHierarchy'
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.sp_nav_ensure_meta_catalog()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_class_id int;
  v_link_type_id smallint;
  v_type_str bigint;
  v_type_int bigint;
  v_type_path bigint;
  v_meta_link_id int;
BEGIN
  SELECT c."ID" INTO v_class_id
  FROM "Meta"."Classes" c
  WHERE c."Name" = 'portal/NavNode';

  IF v_class_id IS NULL THEN
    INSERT INTO "Meta"."Classes" ("Name")
    VALUES ('portal/NavNode')
    RETURNING "ID" INTO v_class_id;
  END IF;

  INSERT INTO wf.data_type (name, version, status, kind, schema_json)
  VALUES (
    'portal/nav/Caption',
    '1.0',
    'published',
    'string',
    '{"type":"string","maxLength":50}'::jsonb
  )
  ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO NOTHING;

  INSERT INTO wf.data_type (name, version, status, kind, schema_json)
  VALUES (
    'portal/nav/Seq',
    '1.0',
    'published',
    'int',
    '{"type":"integer"}'::jsonb
  )
  ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO NOTHING;

  INSERT INTO wf.data_type (name, version, status, kind, schema_json)
  VALUES (
    'portal/nav/NodePath',
    '1.0',
    'published',
    'string',
    '{"type":"string","maxLength":2048}'::jsonb
  )
  ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO NOTHING;

  INSERT INTO wf.data_type (name, version, status, kind, schema_json)
  VALUES (
    'portal/nav/SortPath',
    '1.0',
    'published',
    'string',
    '{"type":"string","maxLength":2048}'::jsonb
  )
  ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO NOTHING;

  INSERT INTO wf.data_type (name, version, status, kind, schema_json)
  VALUES (
    'portal/nav/InfoID',
    '1.0',
    'published',
    'int',
    '{"type":"integer"}'::jsonb
  )
  ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO NOTHING;

  SELECT id INTO v_type_str FROM wf.data_type WHERE name = 'portal/nav/Caption' AND version = '1.0';
  SELECT id INTO v_type_int FROM wf.data_type WHERE name = 'portal/nav/Seq' AND version = '1.0';
  SELECT id INTO v_type_path FROM wf.data_type WHERE name = 'portal/nav/NodePath' AND version = '1.0';

  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  SELECT v_class_id, 'Caption', v_type_str, true
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'Caption'
  );

  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  SELECT v_class_id, 'Seq', v_type_int, true
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'Seq'
  );

  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  SELECT v_class_id, 'NodePath', v_type_path, false
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'NodePath'
  );

  SELECT id INTO v_type_path FROM wf.data_type WHERE name = 'portal/nav/SortPath' AND version = '1.0';
  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  SELECT v_class_id, 'SortPath', v_type_path, false
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'SortPath'
  );

  SELECT id INTO v_type_int FROM wf.data_type WHERE name = 'portal/nav/InfoID' AND version = '1.0';
  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  SELECT v_class_id, 'InfoID', v_type_int, false
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'InfoID'
  );

  SELECT ml."ID" INTO v_meta_link_id
  FROM "Meta"."MetaLinks" ml
  WHERE ml."ClassID" = v_class_id AND ml."Name" = 'Parent';

  IF v_meta_link_id IS NULL THEN
    INSERT INTO "Meta"."MetaLinks" (
      "ClassID", "Name", "TargetClassID", "MinCard", "MaxCard", "IsHierarchical"
    )
    VALUES (v_class_id, 'Parent', v_class_id, 0, 1, true);
  END IF;

  SELECT lt."ID" INTO v_link_type_id
  FROM "Meta"."LinkTypes" lt
  WHERE lt."Name" = 'portal.NavHierarchy';

  IF v_link_type_id IS NULL THEN
    INSERT INTO "Meta"."LinkTypes" ("Name")
    VALUES ('portal.NavHierarchy')
    RETURNING "ID" INTO v_link_type_id;
  END IF;

  PERFORM "Meta".sp_meta_publish_class_type(v_class_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);
END;
$$;

SELECT portal.sp_nav_ensure_meta_catalog();

CREATE OR REPLACE FUNCTION portal.sp_nav_meta_create(
  p_parent_nav_id integer,
  p_caption text,
  p_seq smallint,
  p_info_id integer DEFAULT NULL,
  p_node_path text DEFAULT NULL,
  p_sort_path text DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  v_class_id int;
  v_parent_obj int;
  v_meta_link int;
  v_link_type smallint;
  v_doc jsonb;
  v_obj_id int;
  v_nav_id int;
BEGIN
  v_class_id := portal.fn_nav_node_class_id();
  v_meta_link := portal.fn_nav_parent_metalink_id();
  v_link_type := portal.fn_nav_hierarchy_link_type_id();

  IF v_class_id IS NULL OR v_meta_link IS NULL OR v_link_type IS NULL THEN
    RAISE EXCEPTION 'portal NavNode meta catalog is not installed';
  END IF;

  v_parent_obj := NULL;
  IF p_parent_nav_id IS NOT NULL THEN
    SELECT n."MetaObjID" INTO v_parent_obj
    FROM portal."NavTree" n
    WHERE n."ID" = p_parent_nav_id;
    IF v_parent_obj IS NULL THEN
      RAISE EXCEPTION 'parent nav node % has no MetaObjID; run portal.sp_nav_backfill_meta first', p_parent_nav_id;
    END IF;
  END IF;

  v_doc := jsonb_strip_nulls(jsonb_build_object(
    'Caption', p_caption,
    'Seq', p_seq,
    'NodePath', p_node_path,
    'SortPath', p_sort_path,
    'InfoID', p_info_id
  ));

  v_obj_id := "Meta".sp_obj_insert(v_class_id, v_doc);

  IF v_parent_obj IS NULL THEN
    PERFORM "Meta".sp_tree_attach_child(v_obj_id, NULL, v_meta_link);
  ELSE
    INSERT INTO "Meta"."Links" (
      "Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2"
    )
    VALUES (
      'nav-parent-' || v_obj_id::text,
      v_class_id,
      v_class_id,
      v_link_type,
      v_meta_link,
      v_obj_id,
      v_parent_obj
    );
  END IF;

  -- The TreeNodes projection trigger may already have created the NavTree row.
  UPDATE portal."NavTree" n
  SET "ParentID" = p_parent_nav_id, "Caption" = p_caption, "Seq" = p_seq, "InfoID" = p_info_id,
      "NodePath" = p_node_path, "SortPath" = p_sort_path
  WHERE n."MetaObjID" = v_obj_id
  RETURNING n."ID" INTO v_nav_id;
  IF v_nav_id IS NULL THEN
    INSERT INTO portal."NavTree" (
      "ParentID", "Caption", "Seq", "InfoID", "NodePath", "SortPath", "MetaObjID"
    )
    VALUES (
      p_parent_nav_id, p_caption, p_seq, p_info_id, p_node_path, p_sort_path, v_obj_id
    )
    RETURNING "ID" INTO v_nav_id;
  END IF;
  UPDATE "Meta"."TreeNodes" tn SET "Seq" = p_seq
  WHERE tn."ObjID" = v_obj_id AND tn."MetaLinkID" = v_meta_link;

  RETURN v_obj_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_nav_register_node(
  p_parent_id integer,
  p_caption text,
  p_seq smallint,
  p_info_id integer DEFAULT NULL,
  p_node_path text DEFAULT NULL,
  p_sort_path text DEFAULT NULL,
  OUT node_id integer
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_meta_obj int;
BEGIN
  IF p_caption IS NULL OR btrim(p_caption) = '' THEN
    RAISE EXCEPTION 'caption is required';
  END IF;
  IF p_seq IS NULL THEN
    RAISE EXCEPTION 'seq is required';
  END IF;

  IF portal.fn_nav_node_class_id() IS NOT NULL THEN
    v_meta_obj := portal.sp_nav_meta_create(
      p_parent_id, p_caption, p_seq, p_info_id, p_node_path, p_sort_path
    );
    SELECT n."ID" INTO node_id
    FROM portal."NavTree" n
    WHERE n."MetaObjID" = v_meta_obj;
    RETURN;
  END IF;

  INSERT INTO portal."NavTree" (
    "ParentID", "Caption", "Seq", "InfoID", "NodePath", "SortPath"
  )
  VALUES (
    p_parent_id, p_caption, p_seq, p_info_id, p_node_path, p_sort_path
  )
  RETURNING "ID" INTO node_id;
END;
$$;

-- Navigation backfill for legacy NavTree rows. Always runs sp_nav_ensure_meta_catalog() (may
-- INSERT/UPDATE Meta catalog). When p_dry_run is true, returns would_create/skip rows only and
-- does not set MetaObjID or create nav Meta objects; dry-run is NOT read-only.
CREATE OR REPLACE FUNCTION portal.sp_nav_backfill_meta(
  p_dry_run boolean DEFAULT false
)
RETURNS TABLE(
  nav_id integer,
  meta_obj_id integer,
  action text
)
LANGUAGE plpgsql
AS $$
DECLARE
  r record;
  v_obj int;
  v_class_id int;
  v_meta_link int;
  v_link_type smallint;
  v_parent_obj int;
  v_doc jsonb;
  v_existing int;
BEGIN
  PERFORM portal.sp_nav_ensure_meta_catalog();
  v_class_id := portal.fn_nav_node_class_id();
  v_meta_link := portal.fn_nav_parent_metalink_id();
  v_link_type := portal.fn_nav_hierarchy_link_type_id();

  FOR r IN
    WITH RECURSIVE ordered AS (
      SELECT n."ID", n."ParentID", 0 AS depth
      FROM portal."NavTree" n
      WHERE n."ParentID" IS NULL
      UNION ALL
      SELECT c."ID", c."ParentID", o.depth + 1
      FROM portal."NavTree" c
      JOIN ordered o ON c."ParentID" = o."ID"
    )
    SELECT n."ID", n."ParentID", n."Caption", n."Seq", n."InfoID", n."NodePath", n."SortPath", n."MetaObjID"
    FROM portal."NavTree" n
    JOIN ordered o ON o."ID" = n."ID"
    ORDER BY o.depth, n."Seq", n."ID"
  LOOP
    IF r."MetaObjID" IS NOT NULL THEN
      IF EXISTS (
        SELECT 1
        FROM "Meta"."Objs" o
        JOIN "Meta"."ObjValues" ov ON ov."ObjID" = o."ID" AND ov."ClassID" = o."ClassID"
        WHERE o."ID" = r."MetaObjID" AND o."ClassID" = v_class_id
      ) THEN
        nav_id := r."ID";
        meta_obj_id := r."MetaObjID";
        action := 'skip';
        RETURN NEXT;
        CONTINUE;
      END IF;

      IF p_dry_run THEN
        nav_id := r."ID";
        meta_obj_id := r."MetaObjID";
        action := 'would_repair';
        RETURN NEXT;
        CONTINUE;
      END IF;

      UPDATE portal."NavTree" n SET "MetaObjID" = NULL WHERE n."ID" = r."ID";
    END IF;

    IF p_dry_run THEN
      nav_id := r."ID";
      meta_obj_id := NULL;
      action := 'would_create';
      RETURN NEXT;
      CONTINUE;
    END IF;

    v_parent_obj := NULL;
    IF r."ParentID" IS NOT NULL THEN
      SELECT n."MetaObjID" INTO v_parent_obj
      FROM portal."NavTree" n
      WHERE n."ID" = r."ParentID";
      IF v_parent_obj IS NULL THEN
        RAISE EXCEPTION 'nav node % parent % is not backfilled yet', r."ID", r."ParentID";
      END IF;
    END IF;

    v_doc := jsonb_strip_nulls(jsonb_build_object(
      'Caption', r."Caption",
      'Seq', r."Seq",
      'NodePath', r."NodePath",
      'SortPath', r."SortPath",
      'InfoID', r."InfoID"
    ));

    v_obj := "Meta".sp_obj_insert(v_class_id, v_doc);

    IF v_parent_obj IS NULL THEN
      PERFORM "Meta".sp_tree_attach_child(v_obj, NULL, v_meta_link);
    ELSE
      SELECT l."ID" INTO v_existing
      FROM "Meta"."Links" l
      WHERE l."MetaLinkID" = v_meta_link
        AND l."ObjID1" = v_obj
      LIMIT 1;

      IF v_existing IS NULL THEN
        INSERT INTO "Meta"."Links" (
          "Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2"
        )
        VALUES (
          'nav-parent-' || v_obj::text,
          v_class_id,
          v_class_id,
          v_link_type,
          v_meta_link,
          v_obj,
          v_parent_obj
        );
      END IF;
    END IF;

    UPDATE portal."NavTree" n
    SET "MetaObjID" = v_obj
    WHERE n."ID" = r."ID";

    nav_id := r."ID";
    meta_obj_id := v_obj;
    action := 'created';
    RETURN NEXT;
  END LOOP;
END;
$$;

CREATE OR REPLACE VIEW portal."vNavTreeMeta" AS
SELECT
  n."ID",
  n."ParentID",
  n."Caption",
  n."Seq",
  n."InfoID",
  n."NodePath",
  n."SortPath",
  n."MetaObjID",
  tn."Path" AS meta_tree_path,
  tn."MetaLinkID" AS meta_tree_link_id
FROM portal."NavTree" n
LEFT JOIN "Meta"."TreeNodes" tn
  ON tn."ObjID" = n."MetaObjID"
 AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id();


-- portal."NavTree" is the menu projection of the portal/NavNode Meta tree. The generic tree
-- editor (portal_session_meta_tree_api.sql) edits Meta objects, links and TreeNodes.Seq; these
-- triggers keep the projection in step (parent, order, caption, path, new nodes).
CREATE OR REPLACE FUNCTION portal.trg_nav_tree_from_meta_tree()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_parent_obj int;
  v_parent_nav int;
  v_doc jsonb;
BEGIN
  IF NEW."MetaLinkID" IS DISTINCT FROM portal.fn_nav_parent_metalink_id() THEN
    RETURN NEW;
  END IF;
  SELECT l."ObjID2" INTO v_parent_obj
  FROM "Meta"."Links" l
  WHERE l."MetaLinkID" = NEW."MetaLinkID" AND l."ObjID1" = NEW."ObjID"
  ORDER BY l."ID" LIMIT 1;
  IF v_parent_obj IS NOT NULL THEN
    SELECT n."ID" INTO v_parent_nav FROM portal."NavTree" n WHERE n."MetaObjID" = v_parent_obj LIMIT 1;
  END IF;

  UPDATE portal."NavTree" n
  SET "ParentID" = v_parent_nav,
      "Seq" = COALESCE(LEAST(NEW."Seq", 32767)::smallint, n."Seq")
  WHERE n."MetaObjID" = NEW."ObjID";
  IF NOT FOUND THEN
    v_doc := "Meta".fn_merged_obj_document(NEW."ObjID");
    IF NULLIF(btrim(v_doc->>'Caption'), '') IS NOT NULL THEN
      INSERT INTO portal."NavTree" ("ParentID", "Caption", "Seq", "NodePath", "MetaObjID")
      VALUES (
        v_parent_nav,
        left(btrim(v_doc->>'Caption'), 50),
        COALESCE(LEAST(NEW."Seq", 32767), (v_doc->>'Seq')::int, 0)::smallint,
        NULLIF(btrim(v_doc->>'NodePath'), ''),
        NEW."ObjID"
      );
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_TreeNodes_NavTree_Projection" ON "Meta"."TreeNodes";
CREATE TRIGGER "TR_TreeNodes_NavTree_Projection"
  AFTER INSERT OR UPDATE OF "Path", "Seq" ON "Meta"."TreeNodes"
  FOR EACH ROW EXECUTE FUNCTION portal.trg_nav_tree_from_meta_tree();

CREATE OR REPLACE FUNCTION portal.trg_nav_tree_from_meta_values()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM "Meta"."Objs" o
    WHERE o."ID" = NEW."ObjID" AND o."ClassID" = portal.fn_nav_node_class_id()
  ) THEN
    RETURN NEW;
  END IF;
  v_doc := "Meta".fn_merged_obj_document(NEW."ObjID");
  UPDATE portal."NavTree" n
  SET "Caption" = COALESCE(left(NULLIF(btrim(v_doc->>'Caption'), ''), 50), n."Caption"),
      "NodePath" = CASE WHEN v_doc ? 'NodePath' THEN NULLIF(btrim(v_doc->>'NodePath'), '') ELSE n."NodePath" END
  WHERE n."MetaObjID" = NEW."ObjID"
    AND (n."Caption" IS DISTINCT FROM COALESCE(left(NULLIF(btrim(v_doc->>'Caption'), ''), 50), n."Caption")
         OR n."NodePath" IS DISTINCT FROM
            CASE WHEN v_doc ? 'NodePath' THEN NULLIF(btrim(v_doc->>'NodePath'), '') ELSE n."NodePath" END);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_ObjValues_NavTree_Projection" ON "Meta"."ObjValues";
CREATE TRIGGER "TR_ObjValues_NavTree_Projection"
  AFTER INSERT OR UPDATE OF "Data" ON "Meta"."ObjValues"
  FOR EACH ROW EXECUTE FUNCTION portal.trg_nav_tree_from_meta_values();

-- Deleting a NavNode object removes its menu row (refused while roles are granted on it).
CREATE OR REPLACE FUNCTION portal.trg_nav_tree_obj_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD."ClassID" = portal.fn_nav_node_class_id() THEN
    DELETE FROM portal."NavTree" n WHERE n."MetaObjID" = OLD."ID";
  END IF;
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Objs_NavTree_Delete" ON "Meta"."Objs";
CREATE TRIGGER "TR_Objs_NavTree_Delete"
  BEFORE DELETE ON "Meta"."Objs"
  FOR EACH ROW EXECUTE FUNCTION portal.trg_nav_tree_obj_delete();

-- Existing menus: sibling order in the Meta tree starts from NavTree.Seq (only where unset).
UPDATE "Meta"."TreeNodes" tn
SET "Seq" = n."Seq"
FROM portal."NavTree" n
WHERE n."MetaObjID" = tn."ObjID"
  AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
  AND tn."Seq" IS NULL;
