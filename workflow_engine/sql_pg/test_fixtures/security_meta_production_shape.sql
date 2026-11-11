-- Production-shaped principals for portal.sp_security_meta_verify_production() in CI.
-- Simulates post-NavTree production: Meta.Objs ids 1..N may already be catalog rows before
-- user migrate; users 1/2 must still map via security_meta_legacy_map + LegacyUserId.
-- Idempotent: users 1/2, organization scope 1, org-admin grants, Entra link on provider 1.

INSERT INTO "RBAC"."Users" ("ID", "FullName", email, "Active")
VALUES
  (1, 'David Production', 'david-prod-fixture@test', 1),
  (2, 'Inty Production', 'inty-prod-fixture@test', 1)
ON CONFLICT ("ID") DO UPDATE
  SET "FullName" = EXCLUDED."FullName",
      email = EXCLUDED.email,
      "Active" = EXCLUDED."Active";

SELECT setval(
  pg_get_serial_sequence('"RBAC"."Users"', 'ID'),
  GREATEST((SELECT MAX("ID") FROM "RBAC"."Users"), 2)
);

DO $fixture$
DECLARE
  v_org_id int;
  v_scope_id int := 1;
  v_provider_id int := 1;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM "RBAC"."Scopes" s WHERE s."ScopeID" = 1) THEN
    INSERT INTO portal."Organizations" ("Name")
    VALUES ('Production Fixture Org')
    RETURNING "ID" INTO v_org_id;

    IF v_org_id IS NULL THEN
      SELECT o."ID" INTO v_org_id FROM portal."Organizations" o WHERE o."Name" = 'Production Fixture Org' LIMIT 1;
    END IF;

    INSERT INTO "RBAC"."Scopes" (
      "ScopeID", "Name", "ScopeType", "OrganizationID", "Active", "CreatedAtUtc"
    )
    OVERRIDING SYSTEM VALUE
    VALUES (
      1, 'Production Fixture Org', 'organization', v_org_id, true, now() AT TIME ZONE 'utc'
    );
  ELSE
    SELECT s."OrganizationID" INTO v_org_id FROM "RBAC"."Scopes" s WHERE s."ScopeID" = 1;
  END IF;

  IF v_org_id IS NOT NULL THEN
    PERFORM portal.sp_organization_set_admin(v_org_id, 1);
    PERFORM portal.sp_organization_set_admin(v_org_id, 2);
  END IF;

  INSERT INTO "RBAC"."IdentityProviders" ("ProviderID", "Name", "ProviderType", "Issuer", "Active", "CreatedAtUtc")
  OVERRIDING SYSTEM VALUE
  VALUES (1, 'entra-prod-fixture', 'oidc', 'https://login.microsoftonline.com/fixture/v2.0', true, now() AT TIME ZONE 'utc')
  ON CONFLICT DO NOTHING;

  INSERT INTO "RBAC"."ScopeIdentityProviders" ("ScopeID", "ProviderID", "Active", "CreatedAtUtc")
  VALUES (v_scope_id, v_provider_id, true, now() AT TIME ZONE 'utc')
  ON CONFLICT DO NOTHING;

  INSERT INTO "RBAC"."ExternalIdentities" (
    "UserID", "ProviderID", "Subject", "EmailSnapshot", "Active", "CreatedAtUtc"
  )
  SELECT 1, v_provider_id, 'david-entra-subject-fixture', 'david-prod-fixture@test', true, now() AT TIME ZONE 'utc'
  WHERE NOT EXISTS (
    SELECT 1 FROM "RBAC"."ExternalIdentities" ei
    WHERE ei."UserID" = 1 AND ei."ProviderID" = v_provider_id
  );
END
$fixture$;

SELECT portal.sp_security_meta_migrate_from_legacy();
SELECT portal.sp_security_meta_refresh_cache();
