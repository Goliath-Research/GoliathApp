/*
  Layered security: class-level role grants and per-object ACLs (scoped tenancy).
  Global RBAC (Role_Permissions) remains the baseline; deny wins; most-specific class rule wins per role.
*/

BEGIN;

DO $perm$
DECLARE
  v_class_id int;
  v_obj_id int;
  v_op_id int;
BEGIN
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = 'portal/NavNode' LIMIT 1;
  IF v_class_id IS NULL THEN
    RETURN;
  END IF;
  SELECT o."ID" INTO v_obj_id FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1;
  IF v_obj_id IS NULL THEN
    INSERT INTO "Meta"."Objs" ("ClassID") VALUES (v_class_id) RETURNING "ID" INTO v_obj_id;
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
  INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
  SELECT 'platform.security.admin', v_obj_id, v_op_id
  WHERE NOT EXISTS (
    SELECT 1 FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.security.admin'
  );
END
$perm$;

CREATE TABLE IF NOT EXISTS portal."MetaClassRoleAccess" (
  "AccessID" bigserial PRIMARY KEY,
  "ScopeID" integer NOT NULL,
  "RoleID" integer NOT NULL,
  "ClassID" integer NOT NULL,
  "Action" text NOT NULL,
  "Effect" text NOT NULL,
  "CreatedAtUtc" timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "CK_MetaClassRoleAccess_Action"
    CHECK ("Action" IN ('read', 'create', 'update', 'delete', 'author')),
  CONSTRAINT "CK_MetaClassRoleAccess_Effect"
    CHECK ("Effect" IN ('allow', 'deny')),
  CONSTRAINT "UQ_MetaClassRoleAccess"
    UNIQUE ("ScopeID", "RoleID", "ClassID", "Action")
);

CREATE INDEX IF NOT EXISTS "IX_MetaClassRoleAccess_Class"
  ON portal."MetaClassRoleAccess" ("ScopeID", "ClassID");

CREATE TABLE IF NOT EXISTS portal."MetaObjectAccess" (
  "AccessID" bigserial PRIMARY KEY,
  "ScopeID" integer NOT NULL,
  "ObjID" integer NOT NULL,
  "RoleID" integer,
  "UserID" integer,
  "Action" text NOT NULL,
  "Effect" text NOT NULL,
  "CreatedAtUtc" timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "CK_MetaObjectAccess_Action"
    CHECK ("Action" IN ('read', 'create', 'update', 'delete', 'author')),
  CONSTRAINT "CK_MetaObjectAccess_Effect"
    CHECK ("Effect" IN ('allow', 'deny')),
  CONSTRAINT "CK_MetaObjectAccess_Principal"
    CHECK (
      ("RoleID" IS NOT NULL AND "UserID" IS NULL)
      OR ("RoleID" IS NULL AND "UserID" IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS "UX_MetaObjectAccess_Role"
  ON portal."MetaObjectAccess" ("ScopeID", "ObjID", "RoleID", "Action")
  WHERE "RoleID" IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS "UX_MetaObjectAccess_User"
  ON portal."MetaObjectAccess" ("ScopeID", "ObjID", "UserID", "Action")
  WHERE "UserID" IS NOT NULL;

CREATE TABLE IF NOT EXISTS portal.security_admin_audit (
  audit_id bigserial PRIMARY KEY,
  session_id integer NOT NULL,
  actor_user_id integer NOT NULL,
  scope_id integer,
  action_code text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

COMMIT;
