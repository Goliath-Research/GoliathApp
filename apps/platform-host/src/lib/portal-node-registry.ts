/**
 * Maps official NavTree NodePath values to operator workspace kinds.
 * Meta / OOP hierarchy routes are first-class; other platform surfaces use list/semantic runners.
 */

export type PortalWorkspaceKind =
  | "meta_home"
  | "meta_workbench"
  | "meta_class_catalog"
  | "semantic_entities"
  | "semantic_meta_bridge"
  | "semantic_authoring"
  | "admin_grants"
  | "admin_users"
  | "admin_roles"
  | "admin_permissions"
  | "platform_query"
  | "operator_views"
  | "operator_dashboards"
  | "placeholder";

export type PortalWorkspaceSpec = {
  kind: PortalWorkspaceKind;
  title: string;
  description?: string;
  /** Meta class query default for workbench routes. */
  metaClass?: string;
  /** Highlight semantic/child namespace in hierarchy. */
  semanticNamespace?: string;
  /** Session platform list proc key (see portal-platform-queries.ts). */
  platformQuery?: string;
  /** Semantic request_code for sp_run_semantic_request. */
  semanticRequest?: string;
};

const META_ROOT_DEFAULT = "portal/NavNode";

/** NodeInfos.Name prefix for generic Meta object list/editor screens (child apps). */
export const NAV_META_OBJECT_INFO_PREFIX = "platform.nav.meta_object:";

export type PortalNavResolveHint = {
  /** portal."NodeInfos"."FrameKey" (presentation_kind), e.g. meta_object */
  presentationKind?: string | null;
  /** portal."NodeInfos"."Name" */
  infoName?: string | null;
};

export function metaClassFromNavInfoName(infoName: string | null | undefined): string | null {
  if (!infoName?.startsWith(NAV_META_OBJECT_INFO_PREFIX)) return null;
  const cls = infoName.slice(NAV_META_OBJECT_INFO_PREFIX.length).trim();
  return cls.length > 0 ? cls : null;
}

const PATH_SPECS: Record<string, PortalWorkspaceSpec> = {
  "/app": {
    kind: "meta_home",
    title: "Meta class hierarchy",
    description: "Inherited GoliathApp classes and child semantic extensions.",
  },
  "/app/meta": {
    kind: "meta_home",
    title: "Meta model",
    description: "Primary OOP class hierarchy and editors.",
  },
  "/app/meta/classes": {
    kind: "meta_class_catalog",
    title: "Classes",
    description: "Full Meta.Classes hierarchy with workbench drill-in.",
  },
  "/app/meta/objects": {
    kind: "meta_workbench",
    title: "Meta objects",
    metaClass: META_ROOT_DEFAULT,
    description: "Instance documents for the selected class (SchemaPropertyGrid).",
  },
  "/app/meta/fields": {
    kind: "meta_workbench",
    title: "Fields",
    metaClass: META_ROOT_DEFAULT,
    description: "Field schema on platform and semantic classes.",
  },
  "/app/meta/relations": {
    kind: "meta_workbench",
    title: "Relations",
    metaClass: META_ROOT_DEFAULT,
  },
  "/app/meta/methods": {
    kind: "meta_workbench",
    title: "Methods",
    metaClass: META_ROOT_DEFAULT,
  },
  "/app/meta/data-types": {
    kind: "platform_query",
    title: "Data types",
    platformQuery: "data_types",
    description: "wf.data_type catalog; open named types in Meta when class-backed.",
  },
  "/app/meta/trees": {
    kind: "meta_workbench",
    title: "Trees",
    metaClass: "meta/Tree",
    description: "Hierarchical Meta tree classes and TreeNodes.",
  },
  "/app/semantic": {
    kind: "semantic_authoring",
    title: "Semantic layer",
    description: "Browse and register semantic namespaces, entities, attributes, and Meta mappings.",
  },
  "/app/semantic/namespaces": {
    kind: "semantic_authoring",
    title: "Semantic namespaces",
    description: "Register child namespaces and inspect registry rows.",
  },
  "/app/semantic/entities": {
    kind: "semantic_authoring",
    title: "Semantic entities",
    description: "Register entities and bind them to Meta classes.",
  },
  "/app/semantic/attributes": {
    kind: "semantic_authoring",
    title: "Semantic attributes",
    description: "Declare attribute columns and filter roles on entities.",
  },
  "/app/semantic/requests": {
    kind: "platform_query",
    title: "Semantic requests",
    platformQuery: "semantic_requests",
  },
  "/app/admin/users": {
    kind: "admin_users",
    title: "Users",
    description: "Create users, invitations, and scoped role assignments.",
  },
  "/app/admin/organizations": {
    kind: "platform_query",
    title: "Organizations",
    semanticRequest: "core.list_organizations",
  },
  "/app/admin/roles": {
    kind: "admin_roles",
    title: "Roles",
    description: "Create roles and edit global permission sets.",
  },
  "/app/admin/permissions": {
    kind: "admin_permissions",
    title: "Permissions",
    description: "Permission catalog referenced by roles and session gates.",
  },
  "/app/admin/scopes": { kind: "platform_query", title: "Scopes", platformQuery: "scopes" },
  "/app/admin/invitations": { kind: "platform_query", title: "Invitations", platformQuery: "invitations" },
  "/app/admin/navigation": {
    kind: "admin_grants",
    title: "Navigation & grants",
    description: "Register NavTree nodes and grant roles to users and menu entries in the active scope.",
  },
  "/app/workflows/definitions": {
    kind: "platform_query",
    title: "Workflow definitions",
    platformQuery: "workflow_defs",
  },
  "/app/workflows/runs": {
    kind: "platform_query",
    title: "Workflow runs",
    platformQuery: "workflow_runs",
  },
  "/app/workflows/actions": {
    kind: "platform_query",
    title: "Workflow actions",
    platformQuery: "workflow_actions",
  },
  "/app/workflows/steps": {
    kind: "platform_query",
    title: "Workflow steps",
    platformQuery: "workflow_steps",
  },
  "/app/workflows/domain-programs": {
    kind: "platform_query",
    title: "Domain programs",
    platformQuery: "domain_programs",
  },
  "/app/workflows/workers": {
    kind: "platform_query",
    title: "Worker enrollments",
    platformQuery: "worker_enrollments",
  },
  "/app/workflows/subscriptions": {
    kind: "platform_query",
    title: "Event subscriptions",
    platformQuery: "event_subscriptions",
  },
  "/app/config/site": { kind: "platform_query", title: "Site settings", platformQuery: "sites" },
  "/app/config/pipeline-profiles": {
    kind: "platform_query",
    title: "Pipeline profiles",
    platformQuery: "pipeline_profiles",
  },
  "/app/operations/events": { kind: "platform_query", title: "Events", platformQuery: "recent_events" },
  "/app/operations/schedules": { kind: "platform_query", title: "Schedules", platformQuery: "schedule_nodes" },
  "/app/operations/worker-fleet": {
    kind: "platform_query",
    title: "Worker fleet",
    platformQuery: "worker_health",
  },
  "/app/inv/items": { kind: "platform_query", title: "Items", semanticRequest: "inv.item.list" },
  "/app/inv/purchase-orders": {
    kind: "platform_query",
    title: "Purchase orders",
    semanticRequest: "inv.purchase_order.list",
  },
  "/app/inv/stock-lots": {
    kind: "platform_query",
    title: "Stock lots",
    semanticRequest: "inv.stock_lot.by_item",
  },
  "/app/inv/supplier-items": {
    kind: "platform_query",
    title: "Supplier items",
    semanticRequest: "inv.supplier_item.list",
  },
};

const PARENT_FALLBACK: Record<string, PortalWorkspaceSpec> = {
  "/app/admin": {
    kind: "placeholder",
    title: "Administration",
    description: "Choose Users, Organizations, Roles, or another admin leaf in the navigation tree.",
  },
  "/app/workflows": {
    kind: "placeholder",
    title: "Workflows",
    description: "Choose Definitions, Runs, Actions, or another workflow leaf.",
  },
  "/app/config": { kind: "placeholder", title: "Configuration" },
  "/app/operations": { kind: "placeholder", title: "Operations" },
  "/app/views": {
    kind: "operator_views",
    title: "Views and dashboards",
    description: "Define views on semantic requests and Meta classes; arrange them on dashboards.",
  },
  "/app/views/list": {
    kind: "operator_views",
    title: "Views",
    description: "Define and run saved views on platform and semantic entities.",
  },
  "/app/views/dashboards": {
    kind: "operator_dashboards",
    title: "Dashboards",
    description: "Create dashboards and arrange saved views.",
  },
  "/app/inv": { kind: "placeholder", title: "Inventory" },
  "/app/inv/stock": {
    kind: "placeholder",
    title: "Stock operations",
    description: "Use workflow actions or inventory APIs from a connected worker; stock mutation UI is not in the host yet.",
  },
};

export function resolvePortalWorkspace(
  nodePath: string | null | undefined,
  hint?: PortalNavResolveHint,
): PortalWorkspaceSpec {
  const path = (nodePath ?? "/app").replace(/\/+$/, "") || "/app";
  if (PATH_SPECS[path]) return PATH_SPECS[path];
  const metaClassFromNav = metaClassFromNavInfoName(hint?.infoName);
  const frame = hint?.presentationKind?.trim() ?? "";
  if (metaClassFromNav && (frame === "meta_object" || frame.startsWith("meta_object"))) {
    const leaf = path.split("/").filter(Boolean).pop() ?? "Objects";
    return {
      kind: "meta_workbench",
      title: leaf.replace(/-/g, " "),
      metaClass: metaClassFromNav,
      description: `Meta instances for ${metaClassFromNav} (SchemaPropertyGrid).`,
    };
  }
  if (PARENT_FALLBACK[path]) return PARENT_FALLBACK[path];
  if (path.startsWith("/app/meta")) {
    return {
      kind: "meta_workbench",
      title: "Meta model",
      metaClass: META_ROOT_DEFAULT,
    };
  }
  const segment = path.split("/").filter(Boolean).pop() ?? "Workspace";
  return {
    kind: "placeholder",
    title: segment.replace(/-/g, " "),
    description: `No platform host screen is registered for ${path} yet.`,
  };
}

export function nodePathFromUrlPathname(pathname: string): string {
  if (!pathname.startsWith("/app")) return "/app";
  return pathname.split("?")[0]!.replace(/\/+$/, "") || "/app";
}
