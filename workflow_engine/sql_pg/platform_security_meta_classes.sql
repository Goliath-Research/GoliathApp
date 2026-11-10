/*
  Platform security Meta classes (users, roles, permissions, grants, identities, invitations).
  See docs/platform-security-meta.md
*/

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
SELECT v.name, '1.0', 'published', v.kind, v.schema_json, md5(v.schema_json::text)
FROM (VALUES
  ('platform/security/Text', 'string', '{"type":"string","maxLength":512}'::jsonb),
  ('platform/security/Email', 'string', '{"type":"string","format":"email","maxLength":255}'::jsonb),
  ('platform/security/Boolean', 'bool', '{"type":"boolean"}'::jsonb),
  ('platform/security/Integer', 'int', '{"type":"integer"}'::jsonb),
  ('platform/security/Timestamp', 'datetime', '{"type":"string","format":"date-time"}'::jsonb)
) AS v(name, kind, schema_json)
WHERE NOT EXISTS (
  SELECT 1 FROM wf.data_type t WHERE t.name = v.name AND t.version = '1.0'
);

DO $sec_classes$
DECLARE
  v_string bigint;
  v_email bigint;
  v_bool bigint;
  v_int bigint;
  v_ts bigint;
  v_entity int;
  v_person int;
  v_org int;
  v_class int;
  v_spec record;
BEGIN
  SELECT id INTO v_string FROM wf.data_type WHERE name = 'platform/security/Text' AND version = '1.0';
  SELECT id INTO v_email FROM wf.data_type WHERE name = 'platform/security/Email' AND version = '1.0';
  SELECT id INTO v_bool FROM wf.data_type WHERE name = 'platform/security/Boolean' AND version = '1.0';
  SELECT id INTO v_int FROM wf.data_type WHERE name = 'platform/security/Integer' AND version = '1.0';
  SELECT id INTO v_ts FROM wf.data_type WHERE name = 'platform/security/Timestamp' AND version = '1.0';

  SELECT c."ID" INTO v_entity FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Entity';
  SELECT c."ID" INTO v_person FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Person';
  SELECT c."ID" INTO v_org FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Organization';

  FOR v_spec IN
    SELECT *
    FROM (VALUES
      ('platform/User', 'platform/Person'),
      ('platform/Role', 'platform/Entity'),
      ('platform/Permission', 'platform/Entity'),
      ('platform/RoleGrant', 'platform/Entity'),
      ('platform/ExternalIdentity', 'platform/Entity'),
      ('platform/Invitation', 'platform/Entity')
    ) AS t(name, parent)
  LOOP
    INSERT INTO "Meta"."Classes" ("Name", "ParentID")
    SELECT v_spec.name, (
      SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = v_spec.parent LIMIT 1
    )
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = v_spec.name);
  END LOOP;

  PERFORM "Meta".sp_backfill_all_class_hierarchies();

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/User';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('Email', v_email, true, 'Primary email'),
      ('FullName', v_string, true, 'Full name'),
      ('Active', v_bool, true, 'Account active'),
      ('LegacyUserId', v_int, true, 'Stable RBAC user id for sessions')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('RoleName', v_string, true, 'Role name'),
      ('BypassScope', v_bool, true, 'Bypass scope filter'),
      ('LegacyRoleId', v_int, true, 'Stable RBAC role id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Permission';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('PermissionName', v_string, true, 'Permission name'),
      ('LegacyPermissionId', v_int, true, 'Stable RBAC permission id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('Active', v_bool, true, 'Grant active'),
      ('GrantType', v_string, false, 'Grant type'),
      ('GrantedAtUtc', v_ts, false, 'Granted at'),
      ('RevokedAtUtc', v_ts, false, 'Revoked at'),
      ('LegacyGrantId', v_int, true, 'Stable RBAC grant id'),
      ('LegacyUserId', v_int, true, 'User id'),
      ('LegacyRoleId', v_int, true, 'Role id'),
      ('LegacyScopeId', v_int, false, 'Scope id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ExternalIdentity';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('ProviderId', v_int, true, 'Identity provider id'),
      ('Subject', v_string, true, 'Issuer subject'),
      ('EmailSnapshot', v_email, false, 'Email snapshot'),
      ('Active', v_bool, true, 'Link active'),
      ('LegacyExternalIdentityId', v_int, true, 'RBAC ExternalIdentities id'),
      ('LegacyUserId', v_int, true, 'User id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Invitation';
  IF v_class IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Display label'),
      ('Email', v_email, true, 'Invitee email'),
      ('Status', v_string, true, 'Invitation status'),
      ('ExpiresAtUtc', v_ts, true, 'Expires at'),
      ('ExpectedProviderId', v_int, true, 'Expected provider'),
      ('DefaultRoleId', v_int, false, 'Default role'),
      ('GrantType', v_string, false, 'Grant type'),
      ('LegacyInvitationId', v_int, true, 'Onboarding invitation id'),
      ('LegacyScopeId', v_int, true, 'Scope id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  IF v_org IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_org, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('LegacyOrganizationId', v_int, false, 'portal.Organizations id'),
      ('LegacyScopeId', v_int, false, 'RBAC.Scopes id for organization scope')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_org AND x."Name" = f.name);
  END IF;
END
$sec_classes$;

CREATE TABLE IF NOT EXISTS portal.security_meta_legacy_map (
  legacy_kind text NOT NULL,
  legacy_id bigint NOT NULL,
  meta_obj_id integer NOT NULL,
  CONSTRAINT "PK_portal_security_meta_legacy_map" PRIMARY KEY (legacy_kind, legacy_id)
);

CREATE INDEX IF NOT EXISTS "IX_portal_security_meta_legacy_map_obj"
  ON portal.security_meta_legacy_map (meta_obj_id);

COMMIT;
