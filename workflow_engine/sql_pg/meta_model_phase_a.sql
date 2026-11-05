-- Meta model Phase A (design: docs/meta-model.md §2–§4.1, §3 instance links)
-- Additive alongside legacy typed-table Meta until Phase E.

-- ── Meta.Classes: inheritance columns, FK, cycle trigger, closure ───────────

ALTER TABLE "Meta"."Classes"
  ADD COLUMN IF NOT EXISTS "IsAbstract" boolean NOT NULL DEFAULT false;

ALTER TABLE "Meta"."Classes"
  ADD COLUMN IF NOT EXISTS "AncestorPath" int[] NOT NULL DEFAULT '{}';

ALTER TABLE "Meta"."Classes"
  ADD COLUMN IF NOT EXISTS "Depth" int NOT NULL DEFAULT 0;

ALTER TABLE "Meta"."Classes"
  ADD COLUMN IF NOT EXISTS "TypeID" bigint NULL;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Classes_Parent') THEN
    ALTER TABLE "Meta"."Classes"
      ADD CONSTRAINT "FK_Classes_Parent"
      FOREIGN KEY ("ParentID") REFERENCES "Meta"."Classes" ("ID");
  END IF;
EXCEPTION
  WHEN others THEN
    RAISE NOTICE 'skip FK_Classes_Parent: %', SQLERRM;
END
$fk$;

DO $ck$
BEGIN
  ALTER TABLE "Meta"."Classes"
    ADD CONSTRAINT "CK_Classes_NotSelf" CHECK ("ParentID" IS DISTINCT FROM "ID");
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$ck$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Classes_TypeID') THEN
    ALTER TABLE "Meta"."Classes"
      ADD CONSTRAINT "FK_Classes_TypeID"
      FOREIGN KEY ("TypeID") REFERENCES wf.data_type (id);
  END IF;
EXCEPTION
  WHEN others THEN
    RAISE NOTICE 'skip FK_Classes_TypeID: %', SQLERRM;
END
$fk$;

CREATE TABLE IF NOT EXISTS "Meta"."ClassClosure" (
  "AncestorID" int NOT NULL REFERENCES "Meta"."Classes" ("ID") ON DELETE CASCADE,
  "DescendantID" int NOT NULL REFERENCES "Meta"."Classes" ("ID") ON DELETE CASCADE,
  "Depth" int NOT NULL,
  CONSTRAINT "PK_Meta_ClassClosure" PRIMARY KEY ("AncestorID", "DescendantID")
);

CREATE INDEX IF NOT EXISTS "IX_ClassClosure_Descendant"
  ON "Meta"."ClassClosure" ("DescendantID");

CREATE OR REPLACE FUNCTION "Meta".sp_refresh_class_hierarchy(p_root_id int)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_id int;
  v_parent_path int[];
  v_parent_depth int;
BEGIN
  IF p_root_id IS NULL THEN
    RETURN;
  END IF;

  CREATE TEMP TABLE IF NOT EXISTS _meta_hier_order (
    class_id int PRIMARY KEY,
    ord int NOT NULL
  ) ON COMMIT DROP;
  TRUNCATE _meta_hier_order;

  WITH RECURSIVE sub AS (
    SELECT c."ID", 0 AS ord
    FROM "Meta"."Classes" c
    WHERE c."ID" = p_root_id
    UNION ALL
    SELECT c."ID", sub.ord + 1
    FROM "Meta"."Classes" c
    JOIN sub ON c."ParentID" = sub."ID"
  )
  INSERT INTO _meta_hier_order (class_id, ord)
  SELECT "ID", ord FROM sub;

  FOR v_id IN
    SELECT class_id FROM _meta_hier_order ORDER BY ord
  LOOP
    SELECT
      CASE
        WHEN c."ParentID" IS NULL THEN '{}'::int[]
        ELSE p."AncestorPath" || p."ID"
      END,
      CASE
        WHEN c."ParentID" IS NULL THEN 0
        ELSE p."Depth" + 1
      END
    INTO v_parent_path, v_parent_depth
    FROM "Meta"."Classes" c
    LEFT JOIN "Meta"."Classes" p ON p."ID" = c."ParentID"
    WHERE c."ID" = v_id;

    UPDATE "Meta"."Classes" c
    SET "AncestorPath" = v_parent_path,
        "Depth" = v_parent_depth
    WHERE c."ID" = v_id;
  END LOOP;

  DELETE FROM "Meta"."ClassClosure" cc
  WHERE cc."DescendantID" IN (SELECT class_id FROM _meta_hier_order);

  INSERT INTO "Meta"."ClassClosure" ("AncestorID", "DescendantID", "Depth")
  SELECT anc."ID", d."ID", d."Depth" - anc."Depth"
  FROM "Meta"."Classes" d
  JOIN "Meta"."Classes" anc ON anc."ID" = ANY (d."AncestorPath" || d."ID")
  WHERE d."ID" IN (SELECT class_id FROM _meta_hier_order);
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_backfill_all_class_hierarchies()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_root int;
BEGIN
  FOR v_root IN
    SELECT c."ID"
    FROM "Meta"."Classes" c
    WHERE c."ParentID" IS NULL
    ORDER BY c."ID"
  LOOP
    PERFORM "Meta".sp_refresh_class_hierarchy(v_root);
  END LOOP;

  -- Orphan classes (ParentID set but parent missing) still get a self-row.
  INSERT INTO "Meta"."ClassClosure" ("AncestorID", "DescendantID", "Depth")
  SELECT c."ID", c."ID", 0
  FROM "Meta"."Classes" c
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."ClassClosure" cc WHERE cc."DescendantID" = c."ID"
  )
  ON CONFLICT DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_classes_hierarchy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_parent_path int[];
BEGIN
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;

  IF NEW."ParentID" IS NOT NULL THEN
    SELECT p."AncestorPath" || p."ID"
    INTO v_parent_path
    FROM "Meta"."Classes" p
    WHERE p."ID" = NEW."ParentID";

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Parent class % not found', NEW."ParentID";
    END IF;

    IF NEW."ID" IS NOT NULL AND NEW."ID" = ANY (v_parent_path) THEN
      RAISE EXCEPTION 'ParentID would create a cycle for class %', NEW."ID";
    END IF;
  END IF;

  IF TG_OP = 'UPDATE' AND NEW."ParentID" IS NOT DISTINCT FROM OLD."ParentID"
     AND NEW."ID" = OLD."ID" THEN
    RETURN NEW;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_classes_hierarchy_after()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' AND NEW."ParentID" IS NOT DISTINCT FROM OLD."ParentID" THEN
    RETURN NEW;
  END IF;

  PERFORM "Meta".sp_refresh_class_hierarchy(NEW."ID");
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Classes_Hierarchy_BIU" ON "Meta"."Classes";
CREATE TRIGGER "TR_Classes_Hierarchy_BIU"
  BEFORE INSERT OR UPDATE OF "ParentID"
  ON "Meta"."Classes"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_classes_hierarchy();

DROP TRIGGER IF EXISTS "TR_Classes_Hierarchy_AIU" ON "Meta"."Classes";
CREATE TRIGGER "TR_Classes_Hierarchy_AIU"
  AFTER INSERT OR UPDATE OF "ParentID"
  ON "Meta"."Classes"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_classes_hierarchy_after();

SELECT "Meta".sp_backfill_all_class_hierarchies();

-- ── Meta.Fields, Methods, MethodParams, MetaLinks ───────────────────────────

CREATE TABLE IF NOT EXISTS "Meta"."Fields" (
  "ID" int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "ClassID" int NOT NULL REFERENCES "Meta"."Classes" ("ID") ON DELETE CASCADE,
  "Name" text NOT NULL,
  "TypeID" bigint NOT NULL REFERENCES wf.data_type (id),
  "Required" boolean NOT NULL DEFAULT false,
  "IsHot" boolean NOT NULL DEFAULT false,
  "Description" text,
  CONSTRAINT "UQ_Meta_Fields_Class_Name" UNIQUE ("ClassID", "Name")
);

CREATE TABLE IF NOT EXISTS "Meta"."Methods" (
  "ID" int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "ClassID" int NOT NULL REFERENCES "Meta"."Classes" ("ID") ON DELETE CASCADE,
  "Name" text NOT NULL,
  "Description" text,
  "ReturnTypeID" bigint NULL REFERENCES wf.data_type (id),
  "IsAbstract" boolean NOT NULL DEFAULT false,
  "IsOverride" boolean NOT NULL DEFAULT false,
  "IsFinal" boolean NOT NULL DEFAULT false,
  "ImplKind" text NULL,
  "ImplRef" text NULL,
  CONSTRAINT "UQ_Meta_Methods_Class_Name" UNIQUE ("ClassID", "Name"),
  CONSTRAINT "CK_Meta_Methods_ImplKind"
    CHECK ("ImplKind" IS NULL OR "ImplKind" IN ('sql', 'action', 'python')),
  CONSTRAINT "CK_Meta_Methods_Abstract_Impl"
    CHECK ("IsAbstract" = ("ImplKind" IS NULL))
);

CREATE TABLE IF NOT EXISTS "Meta"."MethodParams" (
  "MethodID" int NOT NULL REFERENCES "Meta"."Methods" ("ID") ON DELETE CASCADE,
  "Ordinal" int NOT NULL,
  "Name" text NOT NULL,
  "TypeID" bigint NOT NULL REFERENCES wf.data_type (id),
  "Required" boolean NOT NULL DEFAULT true,
  "DefaultValue" jsonb NULL,
  CONSTRAINT "PK_Meta_MethodParams" PRIMARY KEY ("MethodID", "Ordinal"),
  CONSTRAINT "UQ_Meta_MethodParams_Method_Name" UNIQUE ("MethodID", "Name")
);

CREATE TABLE IF NOT EXISTS "Meta"."MetaLinks" (
  "ID" int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "ClassID" int NOT NULL REFERENCES "Meta"."Classes" ("ID"),
  "Name" text NOT NULL,
  "TargetClassID" int NOT NULL REFERENCES "Meta"."Classes" ("ID"),
  "MinCard" int NOT NULL DEFAULT 0,
  "MaxCard" int NULL,
  "InverseID" int NULL REFERENCES "Meta"."MetaLinks" ("ID"),
  "IsHierarchical" boolean NOT NULL DEFAULT false,
  CONSTRAINT "UQ_Meta_MetaLinks_Class_Name" UNIQUE ("ClassID", "Name"),
  CONSTRAINT "CK_Meta_MetaLinks_MinCard" CHECK ("MinCard" >= 0),
  CONSTRAINT "CK_Meta_MetaLinks_MaxCard"
    CHECK ("MaxCard" IS NULL OR "MaxCard" >= "MinCard")
);

-- ── Meta.ObjValues (JSONB per class level) ───────────────────────────────────

CREATE TABLE IF NOT EXISTS "Meta"."ObjValues" (
  "ObjID" int NOT NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE,
  "ClassID" int NOT NULL REFERENCES "Meta"."Classes" ("ID"),
  "Data" jsonb NOT NULL DEFAULT '{}',
  CONSTRAINT "PK_Meta_ObjValues" PRIMARY KEY ("ObjID", "ClassID")
);

CREATE INDEX IF NOT EXISTS "IX_ObjValues_ClassID"
  ON "Meta"."ObjValues" ("ClassID");

CREATE INDEX IF NOT EXISTS "IX_ObjValues_Data_gin"
  ON "Meta"."ObjValues" USING gin ("Data" jsonb_path_ops);

-- ── Instance links on Meta.Links (legacy ClassID1/2 rows unchanged) ───────────

ALTER TABLE "Meta"."Links"
  ADD COLUMN IF NOT EXISTS "MetaLinkID" int NULL REFERENCES "Meta"."MetaLinks" ("ID");

ALTER TABLE "Meta"."Links"
  ADD COLUMN IF NOT EXISTS "ObjID1" int NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE;

ALTER TABLE "Meta"."Links"
  ADD COLUMN IF NOT EXISTS "ObjID2" int NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE;

DO $ck$
BEGIN
  ALTER TABLE "Meta"."Links"
    ADD CONSTRAINT "CK_Meta_Links_ObjPair"
    CHECK (
      ("ObjID1" IS NULL AND "ObjID2" IS NULL)
      OR ("ObjID1" IS NOT NULL AND "ObjID2" IS NOT NULL AND "MetaLinkID" IS NOT NULL)
    );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$ck$;

CREATE OR REPLACE FUNCTION "Meta".trg_links_instance_permitted()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_src_class int;
  v_tgt_class int;
  v_link_count int;
  v_max int;
BEGIN
  IF NEW."ObjID1" IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT o."ClassID" INTO v_src_class FROM "Meta"."Objs" o WHERE o."ID" = NEW."ObjID1";
  SELECT o."ClassID" INTO v_tgt_class FROM "Meta"."Objs" o WHERE o."ID" = NEW."ObjID2";

  IF NOT EXISTS (
    SELECT 1
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."MetaLinks" ml ON ml."ClassID" = cc."AncestorID" AND ml."ID" = NEW."MetaLinkID"
    JOIN "Meta"."ClassClosure" cc_tgt
      ON cc_tgt."AncestorID" = ml."TargetClassID"
     AND cc_tgt."DescendantID" = v_tgt_class
    WHERE cc."DescendantID" = v_src_class
  ) THEN
    RAISE EXCEPTION 'instance link not permitted by MetaLink % for source class % target class %',
      NEW."MetaLinkID", v_src_class, v_tgt_class;
  END IF;

  SELECT ml."MaxCard" INTO v_max FROM "Meta"."MetaLinks" ml WHERE ml."ID" = NEW."MetaLinkID";

  IF v_max IS NOT NULL THEN
    SELECT count(*) INTO v_link_count
    FROM "Meta"."Links" l
    WHERE l."MetaLinkID" = NEW."MetaLinkID"
      AND l."ObjID1" = NEW."ObjID1"
      AND (TG_OP = 'INSERT' OR l."ID" <> NEW."ID");

    IF v_link_count >= v_max THEN
      RAISE EXCEPTION 'MaxCard % exceeded for MetaLink % on Obj %',
        v_max, NEW."MetaLinkID", NEW."ObjID1";
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_links_instance_inverse()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_inverse int;
  v_exists int;
BEGIN
  IF current_setting('meta.links.inverse_sync', true) = 'off' THEN
    IF TG_OP = 'DELETE' THEN
      RETURN OLD;
    END IF;
    RETURN NEW;
  END IF;

  IF TG_OP IN ('DELETE', 'UPDATE') AND OLD."ObjID1" IS NOT NULL THEN
    SELECT ml."InverseID" INTO v_inverse
    FROM "Meta"."MetaLinks" ml
    WHERE ml."ID" = OLD."MetaLinkID";

    IF v_inverse IS NOT NULL THEN
      PERFORM set_config('meta.links.inverse_sync', 'off', true);
      DELETE FROM "Meta"."Links" l
      WHERE l."MetaLinkID" = v_inverse
        AND l."ObjID1" = OLD."ObjID2"
        AND l."ObjID2" = OLD."ObjID1";
      PERFORM set_config('meta.links.inverse_sync', 'on', true);
    END IF;
  END IF;

  IF TG_OP IN ('INSERT', 'UPDATE') AND NEW."ObjID1" IS NOT NULL THEN
    SELECT ml."InverseID" INTO v_inverse
    FROM "Meta"."MetaLinks" ml
    WHERE ml."ID" = NEW."MetaLinkID";

    IF v_inverse IS NOT NULL THEN
      SELECT l."ID" INTO v_exists
      FROM "Meta"."Links" l
      WHERE l."ObjID1" = NEW."ObjID2"
        AND l."ObjID2" = NEW."ObjID1"
        AND l."MetaLinkID" = v_inverse
      LIMIT 1;

      IF v_exists IS NULL THEN
        PERFORM set_config('meta.links.inverse_sync', 'off', true);
        INSERT INTO "Meta"."Links" ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
        SELECT
          ml."Name",
          ml."ClassID",
          ml."TargetClassID",
          NEW."LinkTypeID",
          v_inverse,
          NEW."ObjID2",
          NEW."ObjID1"
        FROM "Meta"."MetaLinks" ml
        WHERE ml."ID" = v_inverse;
        PERFORM set_config('meta.links.inverse_sync', 'on', true);
      END IF;
    END IF;
  END IF;

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;

  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_links_instance_mincard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_mincard int;
  v_count int;
BEGIN
  IF TG_OP IN ('DELETE', 'UPDATE') AND OLD."ObjID1" IS NOT NULL AND OLD."MetaLinkID" IS NOT NULL THEN
    SELECT ml."MinCard" INTO v_mincard
    FROM "Meta"."MetaLinks" ml
    WHERE ml."ID" = OLD."MetaLinkID";

    SELECT count(*) INTO v_count
    FROM "Meta"."Links" l
    WHERE l."MetaLinkID" = OLD."MetaLinkID"
      AND l."ObjID1" = OLD."ObjID1";

    IF v_count < v_mincard THEN
      RAISE EXCEPTION 'MinCard % not satisfied for MetaLink % on Obj % (have %)',
        v_mincard, OLD."MetaLinkID", OLD."ObjID1", v_count;
    END IF;
  END IF;

  IF TG_OP IN ('INSERT', 'UPDATE') AND NEW."ObjID1" IS NOT NULL AND NEW."MetaLinkID" IS NOT NULL THEN
    SELECT ml."MinCard" INTO v_mincard
    FROM "Meta"."MetaLinks" ml
    WHERE ml."ID" = NEW."MetaLinkID";

    SELECT count(*) INTO v_count
    FROM "Meta"."Links" l
    WHERE l."MetaLinkID" = NEW."MetaLinkID"
      AND l."ObjID1" = NEW."ObjID1";

    IF v_count < v_mincard THEN
      RAISE EXCEPTION 'MinCard % not satisfied for MetaLink % on Obj % (have %)',
        v_mincard, NEW."MetaLinkID", NEW."ObjID1", v_count;
    END IF;
  END IF;

  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Links_Instance_Permitted" ON "Meta"."Links";
CREATE TRIGGER "TR_Links_Instance_Permitted"
  BEFORE INSERT OR UPDATE OF "MetaLinkID", "ObjID1", "ObjID2"
  ON "Meta"."Links"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_links_instance_permitted();

DROP TRIGGER IF EXISTS "TR_Links_Instance_Inverse" ON "Meta"."Links";
CREATE TRIGGER "TR_Links_Instance_Inverse"
  AFTER INSERT OR UPDATE OR DELETE
  ON "Meta"."Links"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_links_instance_inverse();

DROP TRIGGER IF EXISTS "TR_Links_Instance_MinCard" ON "Meta"."Links";
CREATE CONSTRAINT TRIGGER "TR_Links_Instance_MinCard"
  AFTER INSERT OR UPDATE OR DELETE
  ON "Meta"."Links"
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_links_instance_mincard();

-- ── wf.data_type catalog extensions (§4.1) ─────────────────────────────────

ALTER TABLE wf.data_type
  ADD COLUMN IF NOT EXISTS description text;

ALTER TABLE wf.data_type
  ADD COLUMN IF NOT EXISTS base_type_id bigint NULL;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_wf_data_type_base_type') THEN
    ALTER TABLE wf.data_type
      ADD CONSTRAINT fk_wf_data_type_base_type
      FOREIGN KEY (base_type_id) REFERENCES wf.data_type (id);
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$fk$;

ALTER TABLE wf.data_type
  ADD COLUMN IF NOT EXISTS class_id int NULL;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_wf_data_type_class_id') THEN
    ALTER TABLE wf.data_type
      ADD CONSTRAINT fk_wf_data_type_class_id
      FOREIGN KEY (class_id) REFERENCES "Meta"."Classes" ("ID");
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$fk$;

CREATE INDEX IF NOT EXISTS ix_wf_data_type_class_id ON wf.data_type (class_id);
