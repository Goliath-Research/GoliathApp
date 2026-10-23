-- Cross-schema foreign keys for GoliathApp platform objects only.
-- Omics portal clinical FKs live in GoliathOmics apply scripts.

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Collection_ItemClass') THEN
    ALTER TABLE "Meta"."Collections"
      ADD CONSTRAINT "FK_Collection_ItemClass"
      FOREIGN KEY ("ItemClassID") REFERENCES "Meta"."Classes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CollectionItem_Collection') THEN
    ALTER TABLE "Meta"."CollectionItem"
      ADD CONSTRAINT "FK_CollectionItem_Collection"
      FOREIGN KEY ("CollectionID") REFERENCES "Meta"."Collections" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CollectionItem_Objs_ID') THEN
    ALTER TABLE "Meta"."CollectionItem"
      ADD CONSTRAINT "FK_CollectionItem_Objs_ID"
      FOREIGN KEY ("ValueObjectID") REFERENCES "Meta"."Objs" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CollectionItem_Parent') THEN
    ALTER TABLE "Meta"."CollectionItem"
      ADD CONSTRAINT "FK_CollectionItem_Parent"
      FOREIGN KEY ("ParentID") REFERENCES "Meta"."CollectionItem" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CollectionItemValue_CollectionItem') THEN
    ALTER TABLE "Meta"."CollectionItemValue"
      ADD CONSTRAINT "FK_CollectionItemValue_CollectionItem"
      FOREIGN KEY ("CollectionItemID") REFERENCES "Meta"."CollectionItem" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Links_Classes1_ID') THEN
    ALTER TABLE "Meta"."Links"
      ADD CONSTRAINT "FK_Links_Classes1_ID"
      FOREIGN KEY ("ClassID1") REFERENCES "Meta"."Classes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Links_Classes2_ID') THEN
    ALTER TABLE "Meta"."Links"
      ADD CONSTRAINT "FK_Links_Classes2_ID"
      FOREIGN KEY ("ClassID2") REFERENCES "Meta"."Classes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Links_LinkTypes') THEN
    ALTER TABLE "Meta"."Links"
      ADD CONSTRAINT "FK_Links_LinkTypes"
      FOREIGN KEY ("LinkTypeID") REFERENCES "Meta"."LinkTypes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Objs_Classes_ID') THEN
    ALTER TABLE "Meta"."Objs"
      ADD CONSTRAINT "FK_Objs_Classes_ID"
      FOREIGN KEY ("ClassID") REFERENCES "Meta"."Classes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Operations_ObjectTypes') THEN
    ALTER TABLE "Meta"."Operations"
      ADD CONSTRAINT "FK_Operations_ObjectTypes"
      FOREIGN KEY ("ClassID") REFERENCES "Meta"."Classes" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_BypassScopeApprovals_ApprovedByUserID') THEN
    ALTER TABLE "RBAC"."BypassScopeApprovals"
      ADD CONSTRAINT "FK_BypassScopeApprovals_ApprovedByUserID"
      FOREIGN KEY ("ApprovedByUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_BypassScopeApprovals_RequestedByUserID') THEN
    ALTER TABLE "RBAC"."BypassScopeApprovals"
      ADD CONSTRAINT "FK_BypassScopeApprovals_RequestedByUserID"
      FOREIGN KEY ("RequestedByUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_BypassScopeApprovals_RoleID') THEN
    ALTER TABLE "RBAC"."BypassScopeApprovals"
      ADD CONSTRAINT "FK_BypassScopeApprovals_RoleID"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_BypassScopeApprovals_UserID') THEN
    ALTER TABLE "RBAC"."BypassScopeApprovals"
      ADD CONSTRAINT "FK_BypassScopeApprovals_UserID"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Group_Roles_Groups') THEN
    ALTER TABLE "RBAC"."Group_Roles"
      ADD CONSTRAINT "FK_Group_Roles_Groups"
      FOREIGN KEY ("GroupID") REFERENCES "RBAC"."Groups" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Group_Roles_Roles') THEN
    ALTER TABLE "RBAC"."Group_Roles"
      ADD CONSTRAINT "FK_Group_Roles_Roles"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_GroupMembers_Groups') THEN
    ALTER TABLE "RBAC"."Group_Users"
      ADD CONSTRAINT "FK_GroupMembers_Groups"
      FOREIGN KEY ("GroupID") REFERENCES "RBAC"."Groups" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_GroupMembers_Users') THEN
    ALTER TABLE "RBAC"."Group_Users"
      ADD CONSTRAINT "FK_GroupMembers_Users"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Permissions_Objects') THEN
    ALTER TABLE "RBAC"."Permissions"
      ADD CONSTRAINT "FK_Permissions_Objects"
      FOREIGN KEY ("ObjID") REFERENCES "Meta"."Objs" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Permissions_Operations') THEN
    ALTER TABLE "RBAC"."Permissions"
      ADD CONSTRAINT "FK_Permissions_Operations"
      FOREIGN KEY ("OperationID") REFERENCES "Meta"."Operations" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_ExternalIdentities_ProviderID') THEN
    ALTER TABLE "RBAC"."ExternalIdentities"
      ADD CONSTRAINT "FK_RBAC_ExternalIdentities_ProviderID"
      FOREIGN KEY ("ProviderID") REFERENCES "RBAC"."IdentityProviders" ("ProviderID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_ExternalIdentities_UserID') THEN
    ALTER TABLE "RBAC"."ExternalIdentities"
      ADD CONSTRAINT "FK_RBAC_ExternalIdentities_UserID"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_ScopeIdentityProviders_ProviderID') THEN
    ALTER TABLE "RBAC"."ScopeIdentityProviders"
      ADD CONSTRAINT "FK_RBAC_ScopeIdentityProviders_ProviderID"
      FOREIGN KEY ("ProviderID") REFERENCES "RBAC"."IdentityProviders" ("ProviderID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_ScopeIdentityProviders_ScopeID') THEN
    ALTER TABLE "RBAC"."ScopeIdentityProviders"
      ADD CONSTRAINT "FK_RBAC_ScopeIdentityProviders_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_Scopes_OwnerUserID') THEN
    ALTER TABLE "RBAC"."Scopes"
      ADD CONSTRAINT "FK_RBAC_Scopes_OwnerUserID"
      FOREIGN KEY ("OwnerUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_RBAC_Scopes_OrganizationID') THEN
    ALTER TABLE "RBAC"."Scopes"
      ADD CONSTRAINT "FK_RBAC_Scopes_OrganizationID"
      FOREIGN KEY ("OrganizationID") REFERENCES portal."Organizations" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Role_Permissions_Permissions') THEN
    ALTER TABLE "RBAC"."Role_Permissions"
      ADD CONSTRAINT "FK_Role_Permissions_Permissions"
      FOREIGN KEY ("PermissionID") REFERENCES "RBAC"."Permissions" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Role_Permissions_Roles') THEN
    ALTER TABLE "RBAC"."Role_Permissions"
      ADD CONSTRAINT "FK_Role_Permissions_Roles"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Session_Roles_Roles') THEN
    ALTER TABLE "RBAC"."Session_Roles"
      ADD CONSTRAINT "FK_Session_Roles_Roles"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Session_Roles_Sessions') THEN
    ALTER TABLE "RBAC"."Session_Roles"
      ADD CONSTRAINT "FK_Session_Roles_Sessions"
      FOREIGN KEY ("SessionID") REFERENCES "RBAC"."Sessions" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Sessions_ActiveScopeID') THEN
    ALTER TABLE "RBAC"."Sessions"
      ADD CONSTRAINT "FK_Sessions_ActiveScopeID"
      FOREIGN KEY ("ActiveScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Sessions_AuthProviderID') THEN
    ALTER TABLE "RBAC"."Sessions"
      ADD CONSTRAINT "FK_Sessions_AuthProviderID"
      FOREIGN KEY ("AuthProviderID") REFERENCES "RBAC"."IdentityProviders" ("ProviderID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Sessions_Users') THEN
    ALTER TABLE "RBAC"."Sessions"
      ADD CONSTRAINT "FK_Sessions_Users"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_UserRoleGrants_ApprovalID') THEN
    ALTER TABLE "RBAC"."UserRoleGrants"
      ADD CONSTRAINT "FK_UserRoleGrants_ApprovalID"
      FOREIGN KEY ("ApprovalID") REFERENCES "RBAC"."BypassScopeApprovals" ("ApprovalID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_UserRoleGrants_RoleID') THEN
    ALTER TABLE "RBAC"."UserRoleGrants"
      ADD CONSTRAINT "FK_UserRoleGrants_RoleID"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_UserRoleGrants_ScopeID') THEN
    ALTER TABLE "RBAC"."UserRoleGrants"
      ADD CONSTRAINT "FK_UserRoleGrants_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_UserRoleGrants_UserID') THEN
    ALTER TABLE "RBAC"."UserRoleGrants"
      ADD CONSTRAINT "FK_UserRoleGrants_UserID"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_NavTree_NodeInfos_Id') THEN
    ALTER TABLE "portal"."NavTree"
      ADD CONSTRAINT "FK_NavTree_NodeInfos_Id"
      FOREIGN KEY ("InfoID") REFERENCES "portal"."NodeInfos" ("Id");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Objs_Objs_ID') THEN
    ALTER TABLE "portal"."Objs"
      ADD CONSTRAINT "FK_Objs_Objs_ID"
      FOREIGN KEY ("MetaObjID") REFERENCES "Meta"."Objs" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Role2Node_NavTree_ID') THEN
    ALTER TABLE "portal"."Role2Node"
      ADD CONSTRAINT "FK_Role2Node_NavTree_ID"
      FOREIGN KEY ("NodeId") REFERENCES "portal"."NavTree" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Role2Node_Roles_ID') THEN
    ALTER TABLE "portal"."Role2Node"
      ADD CONSTRAINT "FK_Role2Node_Roles_ID"
      FOREIGN KEY ("RoleId") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Role2Node_Scopes_ScopeID') THEN
    ALTER TABLE "portal"."Role2Node"
      ADD CONSTRAINT "FK_Role2Node_Scopes_ScopeID"
      FOREIGN KEY ("ScopeId") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Contracts_Organizations_ID') THEN
    ALTER TABLE "Contract"."Contracts"
      ADD CONSTRAINT "FK_Contracts_Organizations_ID"
      FOREIGN KEY ("OrganizationID") REFERENCES portal."Organizations" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ContractLimits_ContractID') THEN
    ALTER TABLE "Contract"."ContractLimits"
      ADD CONSTRAINT "FK_ContractLimits_ContractID"
      FOREIGN KEY ("ContractID") REFERENCES "Contract"."Contracts" ("ContractID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ContractScopes_ContractID') THEN
    ALTER TABLE "Contract"."ContractScopes"
      ADD CONSTRAINT "FK_ContractScopes_ContractID"
      FOREIGN KEY ("ContractID") REFERENCES "Contract"."Contracts" ("ContractID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ContractScopes_ScopeID') THEN
    ALTER TABLE "Contract"."ContractScopes"
      ADD CONSTRAINT "FK_ContractScopes_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CRP_ContractID') THEN
    ALTER TABLE "Contract"."ContractRolePolicies"
      ADD CONSTRAINT "FK_CRP_ContractID"
      FOREIGN KEY ("ContractID") REFERENCES "Contract"."Contracts" ("ContractID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CRP_RoleID') THEN
    ALTER TABLE "Contract"."ContractRolePolicies"
      ADD CONSTRAINT "FK_CRP_RoleID"
      FOREIGN KEY ("RoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CWE_ContractID') THEN
    ALTER TABLE "Contract"."ContractWorkflowEntitlements"
      ADD CONSTRAINT "FK_CWE_ContractID"
      FOREIGN KEY ("ContractID") REFERENCES "Contract"."Contracts" ("ContractID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_CWE_WorkflowDefID') THEN
    ALTER TABLE "Contract"."ContractWorkflowEntitlements"
      ADD CONSTRAINT "FK_CWE_WorkflowDefID"
      FOREIGN KEY ("WorkflowDefID") REFERENCES "wf"."workflow_def" ("id");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_WUC_ContractID') THEN
    ALTER TABLE "Contract"."WorkflowUsageCounters"
      ADD CONSTRAINT "FK_WUC_ContractID"
      FOREIGN KEY ("ContractID") REFERENCES "Contract"."Contracts" ("ContractID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_WUC_ScopeID') THEN
    ALTER TABLE "Contract"."WorkflowUsageCounters"
      ADD CONSTRAINT "FK_WUC_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_WUC_WorkflowDefID') THEN
    ALTER TABLE "Contract"."WorkflowUsageCounters"
      ADD CONSTRAINT "FK_WUC_WorkflowDefID"
      FOREIGN KEY ("WorkflowDefID") REFERENCES "wf"."workflow_def" ("id");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ApprovalQueue_InvitationID') THEN
    ALTER TABLE "Onboarding"."ApprovalQueue"
      ADD CONSTRAINT "FK_ApprovalQueue_InvitationID"
      FOREIGN KEY ("InvitationID") REFERENCES "Onboarding"."Invitations" ("InvitationID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ApprovalQueue_RequestedRoleID') THEN
    ALTER TABLE "Onboarding"."ApprovalQueue"
      ADD CONSTRAINT "FK_ApprovalQueue_RequestedRoleID"
      FOREIGN KEY ("RequestedRoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_ApprovalQueue_ReviewedByUserID') THEN
    ALTER TABLE "Onboarding"."ApprovalQueue"
      ADD CONSTRAINT "FK_ApprovalQueue_ReviewedByUserID"
      FOREIGN KEY ("ReviewedByUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_InvitationBatches_CreatedByUserID') THEN
    ALTER TABLE "Onboarding"."InvitationBatches"
      ADD CONSTRAINT "FK_InvitationBatches_CreatedByUserID"
      FOREIGN KEY ("CreatedByUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_InvitationBatches_ScopeID') THEN
    ALTER TABLE "Onboarding"."InvitationBatches"
      ADD CONSTRAINT "FK_InvitationBatches_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Invitations_AcceptedByUserID') THEN
    ALTER TABLE "Onboarding"."Invitations"
      ADD CONSTRAINT "FK_Invitations_AcceptedByUserID"
      FOREIGN KEY ("AcceptedByUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Invitations_BatchID') THEN
    ALTER TABLE "Onboarding"."Invitations"
      ADD CONSTRAINT "FK_Invitations_BatchID"
      FOREIGN KEY ("BatchID") REFERENCES "Onboarding"."InvitationBatches" ("BatchID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Invitations_DefaultRoleID') THEN
    ALTER TABLE "Onboarding"."Invitations"
      ADD CONSTRAINT "FK_Invitations_DefaultRoleID"
      FOREIGN KEY ("DefaultRoleID") REFERENCES "RBAC"."Roles" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Invitations_ExpectedProviderID') THEN
    ALTER TABLE "Onboarding"."Invitations"
      ADD CONSTRAINT "FK_Invitations_ExpectedProviderID"
      FOREIGN KEY ("ExpectedProviderID") REFERENCES "RBAC"."IdentityProviders" ("ProviderID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_Invitations_ScopeID') THEN
    ALTER TABLE "Onboarding"."Invitations"
      ADD CONSTRAINT "FK_Invitations_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_OnboardingAudit_ActorUserID') THEN
    ALTER TABLE "Onboarding"."AuditLog"
      ADD CONSTRAINT "FK_OnboardingAudit_ActorUserID"
      FOREIGN KEY ("ActorUserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_OnboardingAudit_InvitationID') THEN
    ALTER TABLE "Onboarding"."AuditLog"
      ADD CONSTRAINT "FK_OnboardingAudit_InvitationID"
      FOREIGN KEY ("InvitationID") REFERENCES "Onboarding"."Invitations" ("InvitationID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_OnboardingAudit_ScopeID') THEN
    ALTER TABLE "Onboarding"."AuditLog"
      ADD CONSTRAINT "FK_OnboardingAudit_ScopeID"
      FOREIGN KEY ("ScopeID") REFERENCES "RBAC"."Scopes" ("ScopeID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_OrganizationMembers_OrganizationID') THEN
    ALTER TABLE portal."OrganizationMembers"
      ADD CONSTRAINT "FK_OrganizationMembers_OrganizationID"
      FOREIGN KEY ("OrganizationID") REFERENCES portal."Organizations" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'FK_OrganizationMembers_UserID') THEN
    ALTER TABLE portal."OrganizationMembers"
      ADD CONSTRAINT "FK_OrganizationMembers_UserID"
      FOREIGN KEY ("UserID") REFERENCES "RBAC"."Users" ("ID");
  END IF;
  EXCEPTION WHEN others THEN
    RAISE NOTICE 'skip FK: %', SQLERRM;
END $fk$;
