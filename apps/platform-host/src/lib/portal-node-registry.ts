/**
 * Maps official NavTree NodePath values to operator workspace kinds.
 * Meta / OOP hierarchy routes are first-class; other platform surfaces use list/semantic runners.
 */

export type PortalWorkspaceKind =
  | "meta_home"
  | "meta_workbench"
  | "meta_trees"
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
  | "record_editor"
  | "workflow_graph"
  | "route_index"
  | "extension_help"
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
  /** Record editor entities (record-editor-schemas.ts) rendered by kind "record_editor". */
  recordEntities?: string[];
  /** Tree-shaped Meta class edited with the generic tree editor on this page. */
  treeClass?: string;
  /** Graph editor mode for kind "workflow_graph". */
  graphMode?: "definitions" | "steps";
  /** Related pages shown under the heading. */
  links?: { href: string; label: string }[];
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
    description:
      "Full Meta.Classes hierarchy with workbench drill-in. platform/* classes are edited by the God Architect only.",
    recordEntities: ["meta_class"],
  },
  "/app/meta/objects": {
    kind: "meta_workbench",
    title: "Meta objects",
    metaClass: META_ROOT_DEFAULT,
    description: "Instance documents for the selected class (SchemaPropertyGrid).",
  },
  "/app/meta/fields": {
    kind: "record_editor",
    title: "Fields",
    description:
      "Create, edit and delete class fields typed by catalog data types. Fields of platform/* classes are edited by the God Architect only.",
    recordEntities: ["meta_field"],
  },
  "/app/meta/relations": {
    kind: "record_editor",
    title: "Relations",
    description: "Create, edit and delete relations between classes (cardinality, hierarchical).",
    recordEntities: ["meta_link"],
  },
  "/app/meta/methods": {
    kind: "record_editor",
    title: "Methods",
    description:
      "Class methods grouped by class, with inheritance and overrides. Methods are the workflow actions; parameters are typed by catalog data types.",
    recordEntities: ["class_method"],
  },
  "/app/meta/data-types": {
    kind: "platform_query",
    title: "Data types",
    platformQuery: "data_types",
    description: "wf.data_type catalog; open named types in Meta when class-backed.",
  },
  "/app/meta/trees": {
    kind: "meta_trees",
    title: "Trees",
    description:
      "Classes with a hierarchical self relation. Open one to edit it as a tree (add, move, reorder, view and edit nodes).",
  },
  "/app/semantic": {
    kind: "semantic_authoring",
    title: "Semantic layer",
    description: "Browse and register semantic namespaces, entities, attributes, and Meta mappings.",
  },
  "/app/semantic/namespaces": {
    kind: "record_editor",
    title: "Semantic namespaces",
    description: "Create, rename and delete semantic namespaces. Platform namespaces (platform, portal, core) are edited by the God Architect only.",
    recordEntities: ["semantic_namespace"],
  },
  "/app/semantic/entities": {
    kind: "record_editor",
    title: "Semantic entities",
    description: "Create, edit and delete semantic entities; an entity can map to a Meta class when created.",
    recordEntities: ["semantic_entity"],
  },
  "/app/semantic/attributes": {
    kind: "record_editor",
    title: "Semantic attributes",
    description: "Declare attribute columns, roles and filter operators on entities.",
    recordEntities: ["semantic_attribute"],
  },
  "/app/semantic/requests": {
    kind: "record_editor",
    title: "Semantic requests",
    description: "Create, edit, retire and delete semantic requests: typed parameters, filters, target and row type.",
    recordEntities: ["semantic_request"],
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
    description:
      "Edit the navigation tree (God Architect), and grant roles to users and menu entries in the active scope.",
    treeClass: "portal/NavNode",
  },
  "/app/workflows/definitions": {
    kind: "workflow_graph",
    title: "Workflow definitions",
    description: "Edit a version graph and save it as a new inactive version, then activate it explicitly.",
    graphMode: "definitions",
  },
  "/app/workflows/runs": {
    kind: "platform_query",
    title: "Workflow runs",
    platformQuery: "workflow_runs",
  },
  "/app/workflows/actions": {
    kind: "record_editor",
    title: "Workflow actions",
    description:
      "Actions are Meta class methods. Edit a method and its typed parameters; the action catalog is kept in sync.",
    recordEntities: ["class_method"],
  },
  "/app/workflows/steps": {
    kind: "workflow_graph",
    title: "Workflow steps",
    description: "Edit the steps (nodes and edges) of a version; saving creates a new inactive version.",
    graphMode: "steps",
  },
  "/app/workflows/domain-programs": {
    kind: "record_editor",
    title: "Domain programs",
    description: "Edit draft program metadata and publish drafts. Published versions are immutable.",
    recordEntities: ["domain_program"],
  },
  "/app/workflows/workers": {
    kind: "record_editor",
    title: "Workers and clusters",
    description:
      "Edit clusters and worker enrollments, and set each enrolled worker's desired state (drain, stop, activate). Machines are not started or provisioned here.",
    recordEntities: ["cluster", "worker_enrollment"],
    links: [{ href: "/app/operations/worker-fleet", label: "Worker fleet health" }],
  },
  "/app/workflows/subscriptions": {
    kind: "record_editor",
    title: "Event subscriptions",
    description: "Create and edit the event subscriptions that start or signal workflow runs.",
    recordEntities: ["event_subscription"],
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
    links: [
      { href: "/app/workflows/workers", label: "Drain, stop or activate workers, and manage enrollments" },
    ],
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
    kind: "route_index",
    title: "Administration",
    description: "Users, organizations, roles, permissions, scopes, invitations, and navigation.",
  },
  "/app/workflows": {
    kind: "route_index",
    title: "Workflows",
    description: "Definitions, steps, actions, domain programs, runs, workers, and event subscriptions.",
  },
  "/app/config": { kind: "route_index", title: "Configuration", description: "Sites and pipeline profiles." },
  "/app/operations": {
    kind: "route_index",
    title: "Operations",
    description: "Events, schedules, and the worker fleet.",
  },
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
  "/app/inv": { kind: "route_index", title: "Inventory", description: "Items, lots, purchase orders, and suppliers." },
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
  // The panel shows the node's children when it has any; otherwise it explains how a child
  // app attaches a screen to this path without host code.
  return {
    kind: "extension_help",
    title: segment.replace(/-/g, " "),
  };
}

export type NavIndexRow = {
  nodeId: number;
  parentId: number | null;
  caption: string;
  seq: number;
  nodePath: string | null;
};

/** Direct children of the NavTree node at `path`, in menu order (only nodes with a path). */
export function navChildrenOf(rows: NavIndexRow[], path: string): NavIndexRow[] {
  const normalized = path.replace(/\/+$/, "") || "/app";
  const parent = rows.find((r) => r.nodePath === normalized);
  if (!parent) return [];
  return rows
    .filter((r) => r.parentId === parent.nodeId && r.nodePath)
    .sort((a, b) => a.seq - b.seq || a.caption.localeCompare(b.caption));
}

export function nodePathFromUrlPathname(pathname: string): string {
  if (!pathname.startsWith("/app")) return "/app";
  return pathname.split("?")[0]!.replace(/\/+$/, "") || "/app";
}
