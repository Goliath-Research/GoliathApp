-- Meta hierarchical tree path maintenance (docs/meta-model.md §6).
-- Maintains Meta.TreeNodes.Path (ltree) for instance links whose MetaLink.IsHierarchical = true.
-- Child object = Links.ObjID1; parent object = Links.ObjID2.

CREATE OR REPLACE FUNCTION "Meta".fn_tree_obj_label(p_obj_id int)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT 'n' || p_obj_id::text;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_tree_metalink_hierarchical(p_meta_link_id int)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(ml."IsHierarchical", false)
  FROM "Meta"."MetaLinks" ml
  WHERE ml."ID" = p_meta_link_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_tree_path_for_obj(
  p_obj_id int,
  p_meta_link_id int
)
RETURNS ltree
LANGUAGE sql
STABLE
AS $$
  SELECT tn."Path"
  FROM "Meta"."TreeNodes" tn
  WHERE tn."ObjID" = p_obj_id
    AND tn."MetaLinkID" = p_meta_link_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_tree_attach_child(
  p_child_obj_id int,
  p_parent_obj_id int,
  p_meta_link_id int
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_label text;
  v_parent_path ltree;
  v_new_path ltree;
  v_old_path ltree;
BEGIN
  IF NOT "Meta".fn_tree_metalink_hierarchical(p_meta_link_id) THEN
    RETURN;
  END IF;

  IF p_child_obj_id = p_parent_obj_id THEN
    RAISE EXCEPTION 'tree link cannot point object % to itself', p_child_obj_id;
  END IF;

  v_label := "Meta".fn_tree_obj_label(p_child_obj_id);

  SELECT tn."Path" INTO v_old_path
  FROM "Meta"."TreeNodes" tn
  WHERE tn."ObjID" = p_child_obj_id
    AND tn."MetaLinkID" = p_meta_link_id;

  IF p_parent_obj_id IS NULL THEN
    v_new_path := v_label::ltree;
  ELSE
    v_parent_path := "Meta".fn_tree_path_for_obj(p_parent_obj_id, p_meta_link_id);
    IF v_parent_path IS NULL THEN
      RAISE EXCEPTION 'parent object % has no tree path for MetaLink %', p_parent_obj_id, p_meta_link_id;
    END IF;

    IF v_old_path IS NOT NULL AND v_old_path @> v_parent_path THEN
      RAISE EXCEPTION 'tree move would create cycle: parent % under descendant %',
        p_parent_obj_id, p_child_obj_id;
    END IF;

    IF v_parent_path @> v_label::ltree AND v_parent_path <> v_label::ltree THEN
      RAISE EXCEPTION 'tree path collision for object %', p_child_obj_id;
    END IF;

    v_new_path := v_parent_path || v_label::ltree;
  END IF;

  IF v_old_path IS NOT NULL AND v_old_path = v_new_path THEN
    RETURN;
  END IF;

  IF v_old_path IS NOT NULL THEN
    UPDATE "Meta"."TreeNodes" tn
    SET "Path" = v_new_path || subpath(tn."Path", nlevel(v_old_path))
    WHERE tn."MetaLinkID" = p_meta_link_id
      AND tn."Path" <@ v_old_path
      AND tn."Path" <> v_old_path;
  END IF;

  INSERT INTO "Meta"."TreeNodes" ("ObjID", "MetaLinkID", "Path")
  VALUES (p_child_obj_id, p_meta_link_id, v_new_path)
  ON CONFLICT ("ObjID", "MetaLinkID") DO UPDATE
    SET "Path" = EXCLUDED."Path";
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_tree_detach_child(
  p_child_obj_id int,
  p_meta_link_id int
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_old_path ltree;
  v_child_count int;
BEGIN
  IF NOT "Meta".fn_tree_metalink_hierarchical(p_meta_link_id) THEN
    RETURN;
  END IF;

  SELECT tn."Path" INTO v_old_path
  FROM "Meta"."TreeNodes" tn
  WHERE tn."ObjID" = p_child_obj_id
    AND tn."MetaLinkID" = p_meta_link_id;

  IF v_old_path IS NULL THEN
    RETURN;
  END IF;

  SELECT count(*) INTO v_child_count
  FROM "Meta"."TreeNodes" tn
  WHERE tn."MetaLinkID" = p_meta_link_id
    AND tn."Path" <@ v_old_path
    AND tn."Path" <> v_old_path;

  IF v_child_count > 0 THEN
    RAISE EXCEPTION 'cannot detach object % with % descendant tree node(s); move or delete children first',
      p_child_obj_id, v_child_count;
  END IF;

  DELETE FROM "Meta"."TreeNodes" tn
  WHERE tn."ObjID" = p_child_obj_id
    AND tn."MetaLinkID" = p_meta_link_id;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_links_tree_maintain()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD."ObjID1" IS NOT NULL
       AND OLD."MetaLinkID" IS NOT NULL
       AND "Meta".fn_tree_metalink_hierarchical(OLD."MetaLinkID") THEN
      PERFORM "Meta".sp_tree_detach_child(OLD."ObjID1", OLD."MetaLinkID");
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE'
     AND OLD."ObjID1" IS NOT NULL
     AND OLD."MetaLinkID" IS NOT NULL
     AND "Meta".fn_tree_metalink_hierarchical(OLD."MetaLinkID")
     AND (
       NEW."ObjID1" IS DISTINCT FROM OLD."ObjID1"
       OR NEW."MetaLinkID" IS DISTINCT FROM OLD."MetaLinkID"
     ) THEN
    PERFORM "Meta".sp_tree_detach_child(OLD."ObjID1", OLD."MetaLinkID");
  END IF;

  IF NEW."ObjID1" IS NOT NULL
     AND NEW."MetaLinkID" IS NOT NULL
     AND "Meta".fn_tree_metalink_hierarchical(NEW."MetaLinkID") THEN
    PERFORM "Meta".sp_tree_attach_child(NEW."ObjID1", NEW."ObjID2", NEW."MetaLinkID");
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Links_Tree_Maintain" ON "Meta"."Links";
CREATE TRIGGER "TR_Links_Tree_Maintain"
  AFTER INSERT OR UPDATE OF "MetaLinkID", "ObjID1", "ObjID2" OR DELETE
  ON "Meta"."Links"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_links_tree_maintain();

-- TreeRef: validate document {"node": <obj_id>, "scope": "node"|"branch"} against an existing tree row.
CREATE OR REPLACE FUNCTION "Meta".fn_tree_ref_validate(
  p_meta_link_id int,
  p_tree_ref jsonb
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_node int;
  v_scope text;
  v_path ltree;
BEGIN
  IF p_tree_ref IS NULL THEN
    RETURN true;
  END IF;
  v_node := (p_tree_ref ->> 'node')::int;
  v_scope := p_tree_ref ->> 'scope';
  IF v_scope IS NULL OR v_scope NOT IN ('node', 'branch') THEN
    RETURN false;
  END IF;
  SELECT tn."Path" INTO v_path
  FROM "Meta"."TreeNodes" tn
  WHERE tn."ObjID" = v_node
    AND tn."MetaLinkID" = p_meta_link_id;
  RETURN FOUND;
END;
$$;
