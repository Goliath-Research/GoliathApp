-- Official platform seed: inherited administrative NavTree for every GoliathApp database.
-- Not part of apply_schema.sh — run on the standard population path after DDL and catalog seeds.
--
-- Prerequisites:
--   bash workflow_engine/sql_pg/apply_schema.sh
--   python3 workflow_engine/sql_pg/seed_semantic_catalog.py   (typical)
--   python3 workflow_engine/sql_pg/seed_action_catalog.py --use-db   (typical)
--
-- Idempotent: register missing baseline nodes under /app; upsert NodeInfos FrameKey; grant
-- organization_admin Role_Permissions and Role2Node for every active organization scope;
-- mirror operator entitlements to god_architect (superset + platform.model.architect).
-- Re-run after creating a new organization if an earlier run had no scopes yet.
-- Descendant apps add nodes under their own NodePath prefixes — never replace this tree.
--
--   psql -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/seed_platform_nav_tree.sql
--
-- See docs/database-population.md and docs/nav-tree-meta.md.

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

DO $seed$
DECLARE
  nav_row record;
  v_parent_id int;
  v_info_id int;
  v_node_id int;
  v_role_id int;
  v_scope_id int;
  v_perm_id int;
  v_obj_id int;
  v_op_id int;
  v_class_id int;
  v_perm_name text;
  v_meta_obj int;
  v_meta_link int;
  v_link_type smallint;
  v_parent_obj int;
  v_nav_link_id int;
  v_doc jsonb;
BEGIN
  -- Ensure operator permissions used by platform admin surfaces (Meta catalog is seeded in portal_session_meta_api.sql).
  SELECT c."ID" INTO v_class_id
  FROM "Meta"."Classes" c
  WHERE c."Name" = 'portal/NavNode'
  LIMIT 1;

  IF v_class_id IS NOT NULL THEN
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
      'meta.object.write',
      'platform.model.author',
      'platform.security.admin',
      'inv.stock.receive',
      'inv.stock.adjust',
      'inv.stock.issue',
      'workflow.validation.plan',
      'semantic.restricted.probe'
    ]
    LOOP
      INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
      SELECT v_perm_name, v_obj_id, v_op_id
      WHERE NOT EXISTS (
        SELECT 1 FROM "RBAC"."Permissions" p WHERE p."Name" = v_perm_name
      );
    END LOOP;
  END IF;

  SELECT role_row."ID" INTO v_role_id
  FROM "RBAC"."Roles" role_row
  WHERE role_row."Name" = 'organization_admin'
  LIMIT 1;

  IF v_role_id IS NOT NULL THEN
  FOR v_perm_name IN
    SELECT unnest(ARRAY[
      'meta.schema.read',
      'meta.object.read',
      'meta.object.write',
      'platform.model.author',
      'platform.security.admin',
      'inv.stock.receive',
      'inv.stock.adjust',
      'inv.stock.issue',
      'workflow.validation.plan'
    ]::text[])
  LOOP
    SELECT p."ID" INTO v_perm_id
    FROM "RBAC"."Permissions" p
    WHERE p."Name" = v_perm_name
    LIMIT 1;
    IF v_perm_id IS NOT NULL THEN
      INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
      SELECT v_role_id, v_perm_id
      WHERE NOT EXISTS (
        SELECT 1 FROM "RBAC"."Role_Permissions" rp
        WHERE rp."RoleID" = v_role_id AND rp."PermissionID" = v_perm_id
      );
    END IF;
  END LOOP;
  END IF;

  CREATE TEMP TABLE _platform_baseline_nav (
    caption text NOT NULL,
    node_path text NOT NULL,
    sort_path text NOT NULL,
    seq smallint NOT NULL,
    parent_path text NULL,
    frame_key text NOT NULL,
    info_name text NOT NULL,
    PRIMARY KEY (node_path)
  ) ON COMMIT DROP;

  INSERT INTO _platform_baseline_nav (caption, node_path, sort_path, seq, parent_path, frame_key, info_name)
  VALUES
    ('Platform', '/app', '0010', 10::smallint, NULL, 'config', 'platform.nav.root'),
    ('Administration', '/app/admin', '0010.0010', 10::smallint, '/app', 'role', 'platform.nav.admin'),
    ('Users', '/app/admin/users', '0010.0010.0010', 10::smallint, '/app/admin', 'user', 'platform.nav.admin.users'),
    ('Organizations', '/app/admin/organizations', '0010.0010.0020', 20::smallint, '/app/admin', 'organization', 'platform.nav.admin.organizations'),
    ('Roles', '/app/admin/roles', '0010.0010.0030', 30::smallint, '/app/admin', 'role', 'platform.nav.admin.roles'),
    ('Permissions', '/app/admin/permissions', '0010.0010.0040', 40::smallint, '/app/admin', 'permission', 'platform.nav.admin.permissions'),
    ('Scopes', '/app/admin/scopes', '0010.0010.0050', 50::smallint, '/app/admin', 'view', 'platform.nav.admin.scopes'),
    ('Invitations', '/app/admin/invitations', '0010.0010.0060', 60::smallint, '/app/admin', 'user', 'platform.nav.admin.invitations'),
    ('Navigation', '/app/admin/navigation', '0010.0010.0070', 70::smallint, '/app/admin', 'view', 'platform.nav.admin.navigation'),
    ('Meta model', '/app/meta', '0010.0020', 20::smallint, '/app', 'meta_tree', 'platform.nav.meta'),
    ('Classes', '/app/meta/classes', '0010.0020.0010', 10::smallint, '/app/meta', 'meta_class', 'platform.nav.meta.classes'),
    ('Objects', '/app/meta/objects', '0010.0020.0020', 20::smallint, '/app/meta', 'meta_object', 'platform.nav.meta.objects'),
    ('Fields', '/app/meta/fields', '0010.0020.0030', 30::smallint, '/app/meta', 'meta_field', 'platform.nav.meta.fields'),
    ('Relations', '/app/meta/relations', '0010.0020.0040', 40::smallint, '/app/meta', 'meta_relation', 'platform.nav.meta.relations'),
    ('Methods', '/app/meta/methods', '0010.0020.0050', 50::smallint, '/app/meta', 'workflow_action', 'platform.nav.meta.methods'),
    ('Data types', '/app/meta/data-types', '0010.0020.0060', 60::smallint, '/app/meta', 'config', 'platform.nav.meta.data_types'),
    ('Trees', '/app/meta/trees', '0010.0020.0070', 70::smallint, '/app/meta', 'meta_tree', 'platform.nav.meta.trees'),
    ('Workflows', '/app/workflows', '0010.0030', 30::smallint, '/app', 'workflow_definition', 'platform.nav.workflows'),
    ('Definitions', '/app/workflows/definitions', '0010.0030.0010', 10::smallint, '/app/workflows', 'workflow_definition', 'platform.nav.workflows.definitions'),
    ('Runs', '/app/workflows/runs', '0010.0030.0020', 20::smallint, '/app/workflows', 'workflow_run', 'platform.nav.workflows.runs'),
    ('Actions', '/app/workflows/actions', '0010.0030.0030', 30::smallint, '/app/workflows', 'workflow_action', 'platform.nav.workflows.actions'),
    ('Steps', '/app/workflows/steps', '0010.0030.0040', 40::smallint, '/app/workflows', 'workflow_step', 'platform.nav.workflows.steps'),
    ('Domain programs', '/app/workflows/domain-programs', '0010.0030.0050', 50::smallint, '/app/workflows', 'domain_program', 'platform.nav.workflows.domain_programs'),
    ('Workers', '/app/workflows/workers', '0010.0030.0060', 60::smallint, '/app/workflows', 'subscription', 'platform.nav.workflows.workers'),
    ('Event subscriptions', '/app/workflows/subscriptions', '0010.0030.0070', 70::smallint, '/app/workflows', 'subscription', 'platform.nav.workflows.subscriptions'),
    ('Semantic layer', '/app/semantic', '0010.0040', 40::smallint, '/app', 'semantic_entity', 'platform.nav.semantic'),
    ('Namespaces', '/app/semantic/namespaces', '0010.0040.0010', 10::smallint, '/app/semantic', 'config', 'platform.nav.semantic.namespaces'),
    ('Entities', '/app/semantic/entities', '0010.0040.0020', 20::smallint, '/app/semantic', 'semantic_entity', 'platform.nav.semantic.entities'),
    ('Attributes', '/app/semantic/attributes', '0010.0040.0030', 30::smallint, '/app/semantic', 'semantic_attribute', 'platform.nav.semantic.attributes'),
    ('Requests', '/app/semantic/requests', '0010.0040.0040', 40::smallint, '/app/semantic', 'semantic_request', 'platform.nav.semantic.requests'),
    ('Configuration', '/app/config', '0010.0050', 50::smallint, '/app', 'config', 'platform.nav.config'),
    ('Site settings', '/app/config/site', '0010.0050.0010', 10::smallint, '/app/config', 'config', 'platform.nav.config.site'),
    ('Pipeline profiles', '/app/config/pipeline-profiles', '0010.0050.0020', 20::smallint, '/app/config', 'config', 'platform.nav.config.pipeline_profiles'),
    ('Operations', '/app/operations', '0010.0060', 60::smallint, '/app', 'event', 'platform.nav.operations'),
    ('Events', '/app/operations/events', '0010.0060.0010', 10::smallint, '/app/operations', 'event', 'platform.nav.operations.events'),
    ('Schedules', '/app/operations/schedules', '0010.0060.0020', 20::smallint, '/app/operations', 'schedule', 'platform.nav.operations.schedules'),
    ('Worker fleet', '/app/operations/worker-fleet', '0010.0060.0030', 30::smallint, '/app/operations', 'subscription', 'platform.nav.operations.worker_fleet'),
    ('Views & dashboards', '/app/views', '0010.0070', 70::smallint, '/app', 'view', 'platform.nav.views'),
    ('Views', '/app/views/list', '0010.0070.0010', 10::smallint, '/app/views', 'view', 'platform.nav.views.list'),
    ('Dashboards', '/app/views/dashboards', '0010.0070.0020', 20::smallint, '/app/views', 'dashboard', 'platform.nav.views.dashboards'),
    ('Inventory', '/app/inv', '0010.0080', 80::smallint, '/app', 'artifact', 'platform.nav.inv'),
    ('Items', '/app/inv/items', '0010.0080.0010', 10::smallint, '/app/inv', 'artifact', 'platform.nav.inv.items'),
    ('Purchase orders', '/app/inv/purchase-orders', '0010.0080.0020', 20::smallint, '/app/inv', 'artifact', 'platform.nav.inv.purchase_orders'),
    ('Stock lots', '/app/inv/stock-lots', '0010.0080.0030', 30::smallint, '/app/inv', 'artifact', 'platform.nav.inv.stock_lots'),
    ('Supplier items', '/app/inv/supplier-items', '0010.0080.0040', 40::smallint, '/app/inv', 'artifact', 'platform.nav.inv.supplier_items'),
    ('Stock operations', '/app/inv/stock', '0010.0080.0050', 50::smallint, '/app/inv', 'workflow_action', 'platform.nav.inv.stock');

  -- Legacy NavTree rows (upgrades) may lack MetaObjID; backfill in tree order before register_node children.
  PERFORM nav_id FROM portal.sp_nav_backfill_meta(false);

  FOR nav_row IN
    SELECT *
    FROM _platform_baseline_nav
    ORDER BY sort_path
  LOOP
    SELECT ni."Id" INTO v_info_id
    FROM portal."NodeInfos" ni
    WHERE ni."Name" = nav_row.info_name
    LIMIT 1;

    IF v_info_id IS NULL THEN
      INSERT INTO portal."NodeInfos" ("Name", "Singleton", "FrameKey")
      VALUES (nav_row.info_name, true, nav_row.frame_key)
      RETURNING "Id" INTO v_info_id;
    ELSE
      UPDATE portal."NodeInfos" ni
      SET "FrameKey" = nav_row.frame_key
      WHERE ni."Id" = v_info_id AND COALESCE(ni."FrameKey", '') IS DISTINCT FROM nav_row.frame_key;
    END IF;

    v_parent_id := NULL;
    IF nav_row.parent_path IS NOT NULL THEN
      SELECT n."ID" INTO v_parent_id
      FROM portal."NavTree" n
      WHERE n."NodePath" = nav_row.parent_path
      LIMIT 1;
    END IF;

    SELECT n."ID" INTO v_node_id
    FROM portal."NavTree" n
    WHERE n."NodePath" = nav_row.node_path
    LIMIT 1;

    IF v_node_id IS NULL THEN
      SELECT node_id INTO v_node_id
      FROM portal.sp_nav_register_node(
        v_parent_id,
        nav_row.caption,
        nav_row.seq,
        v_info_id,
        nav_row.node_path,
        nav_row.sort_path
      );
    ELSE
      UPDATE portal."NavTree" n
      SET
        "ParentID" = v_parent_id,
        "Caption" = nav_row.caption,
        "Seq" = nav_row.seq,
        "InfoID" = v_info_id,
        "SortPath" = nav_row.sort_path
      WHERE n."ID" = v_node_id
        AND (
          n."ParentID" IS DISTINCT FROM v_parent_id
          OR n."Caption" IS DISTINCT FROM nav_row.caption
          OR n."Seq" IS DISTINCT FROM nav_row.seq
          OR n."InfoID" IS DISTINCT FROM v_info_id
          OR n."SortPath" IS DISTINCT FROM nav_row.sort_path
        );

      v_meta_obj := NULL;
      SELECT n."MetaObjID" INTO v_meta_obj
      FROM portal."NavTree" n
      WHERE n."ID" = v_node_id;

      IF v_meta_obj IS NOT NULL THEN
        IF EXISTS (
          SELECT 1
          FROM "Meta"."Objs" o
          WHERE o."ID" = v_meta_obj
            AND o."ClassID" = portal.fn_nav_node_class_id()
        ) THEN
          v_doc := jsonb_strip_nulls(jsonb_build_object(
            'Caption', nav_row.caption,
            'Seq', nav_row.seq,
            'NodePath', nav_row.node_path,
            'SortPath', nav_row.sort_path,
            'InfoID', v_info_id
          ));
          PERFORM "Meta".sp_obj_update(v_meta_obj, v_doc);
        END IF;

        v_meta_link := portal.fn_nav_parent_metalink_id();
        v_link_type := portal.fn_nav_hierarchy_link_type_id();
        v_class_id := portal.fn_nav_node_class_id();

        v_parent_obj := NULL;
        IF v_parent_id IS NOT NULL THEN
          SELECT n."MetaObjID" INTO v_parent_obj
          FROM portal."NavTree" n
          WHERE n."ID" = v_parent_id;
        END IF;

        SELECT l."ID" INTO v_nav_link_id
        FROM "Meta"."Links" l
        WHERE l."MetaLinkID" = v_meta_link
          AND l."ObjID1" = v_meta_obj
        LIMIT 1;

        IF v_parent_id IS NOT NULL AND v_parent_obj IS NULL THEN
          RAISE EXCEPTION 'parent nav node % has no MetaObjID; run portal.sp_nav_backfill_meta first', v_parent_id;
        END IF;

        IF v_parent_obj IS NULL THEN
          IF v_nav_link_id IS NOT NULL THEN
            DELETE FROM "Meta"."Links" l WHERE l."ID" = v_nav_link_id;
          END IF;
          PERFORM "Meta".sp_tree_attach_child(v_meta_obj, NULL, v_meta_link);
        ELSIF v_nav_link_id IS NULL THEN
          INSERT INTO "Meta"."Links" (
            "Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2"
          )
          VALUES (
            'nav-parent-' || v_meta_obj::text,
            v_class_id,
            v_class_id,
            v_link_type,
            v_meta_link,
            v_meta_obj,
            v_parent_obj
          );
        ELSE
          UPDATE "Meta"."Links" l
          SET "ObjID2" = v_parent_obj
          WHERE l."ID" = v_nav_link_id
            AND l."ObjID2" IS DISTINCT FROM v_parent_obj;
        END IF;
      END IF;
    END IF;
  END LOOP;

  PERFORM nav_id FROM portal.sp_nav_backfill_meta(false);

  IF v_role_id IS NOT NULL THEN
    FOR v_scope_id IN
      SELECT s."ScopeID"
      FROM "RBAC"."Scopes" s
      WHERE s."ScopeType" = 'organization'
        AND COALESCE(s."Active", true)
    LOOP
      FOR v_node_id IN
        SELECT n."ID"
        FROM portal."NavTree" n
        WHERE n."NodePath" LIKE '/app%'
      LOOP
        PERFORM portal.sp_grant_role_nav_node(v_role_id, v_node_id, v_scope_id);
      END LOOP;
    END LOOP;
  END IF;

  IF to_regprocedure('portal.sp_sync_god_architect_operator_entitlements()') IS NOT NULL THEN
    PERFORM portal.sp_sync_god_architect_operator_entitlements();
  END IF;
END
$seed$;

COMMIT;
