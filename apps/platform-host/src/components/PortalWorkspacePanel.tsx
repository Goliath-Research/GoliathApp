import {
  MetaClassHierarchyList,
  PlatformRecordTable,
  type MetaClassListRow,
} from "@goliath/platform-ui";
import { AdminGrantsWorkspace } from "@/components/AdminGrantsWorkspace";
import { MetaWorkbenchPanel } from "@/components/MetaWorkbenchPanel";
import { ModelAuthoringPanel } from "@/components/ModelAuthoringPanel";
import { OperatorDashboardsWorkspaceServer } from "@/components/OperatorDashboardsWorkspaceServer";
import { OperatorViewsWorkspaceServer } from "@/components/OperatorViewsWorkspaceServer";
import { SemanticLayerWorkspace } from "@/components/SemanticLayerWorkspace";
import {
  PortalForbiddenError,
  PortalMetaNotFoundError,
  portalOperatorNavTree,
  portalSessionMetaListClasses,
  portalSessionPlatformQuery,
  portalSessionRunSemanticRequest,
  portalSessionSemanticEntities,
} from "@/server/portal/bridge";
import type { PortalWorkspaceSpec } from "@/lib/portal-node-registry";
import { PLATFORM_QUERY_SQL } from "@/lib/portal-platform-queries";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { cookies } from "next/headers";

const SEMANTIC_REQUEST_COLUMNS: Record<string, { key: string; label: string }[]> = {
  "core.list_organizations": [
    { key: "organization_id", label: "ID" },
    { key: "name", label: "Name" },
    { key: "active", label: "Active" },
  ],
  "inv.item.list": [
    { key: "item_id", label: "Item ID" },
    { key: "item_number", label: "Number" },
    { key: "active", label: "Active" },
  ],
  "inv.purchase_order.list": [
    { key: "purchase_order_id", label: "PO ID" },
    { key: "status", label: "Status" },
  ],
  "inv.stock_lot.by_item": [
    { key: "stock_lot_id", label: "Lot ID" },
    { key: "item_id", label: "Item" },
  ],
  "inv.supplier_item.list": [
    { key: "supplier_item_id", label: "ID" },
    { key: "item_id", label: "Item" },
  ],
};

function rowsFromSemantic(
  requestCode: string,
  rows: Record<string, unknown>[],
): { columns: { key: string; label: string }[]; data: Record<string, unknown>[] } {
  const preset = SEMANTIC_REQUEST_COLUMNS[requestCode];
  if (preset) {
    return { columns: preset, data: rows };
  }
  if (rows.length === 0) {
    return { columns: [], data: [] };
  }
  const keys = Object.keys(rows[0] ?? {});
  return {
    columns: keys.map((key) => ({ key, label: key.replace(/_/g, " ") })),
    data: rows,
  };
}

export async function PortalWorkspacePanel({
  spec,
  metaClassOverride,
  semanticHighlight,
  dashboardId,
  viewId,
}: {
  spec: PortalWorkspaceSpec;
  metaClassOverride?: string;
  semanticHighlight?: string;
  dashboardId?: number;
  viewId?: number;
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return null;
  }

  try {
    if (spec.kind === "meta_home" || spec.kind === "meta_class_catalog") {
      const classes: MetaClassListRow[] = await portalSessionMetaListClasses(token);
      const platformParents = classes
        .map((c) => c.className)
        .filter((name) => name.startsWith("platform/"));
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <ModelAuthoringPanel parentClasses={platformParents.length ? platformParents : ["platform/Entity"]} />
          <MetaClassHierarchyList
            classes={classes}
            selectedClassName={metaClassOverride}
            semanticHighlight={semanticHighlight}
          />
          {metaClassOverride ? (
            <section className="g-portal-stage__workbench">
              <h3>Workbench</h3>
              <MetaWorkbenchPanel className={metaClassOverride} />
            </section>
          ) : null}
        </div>
      );
    }

    if (spec.kind === "meta_workbench") {
      const className = metaClassOverride ?? spec.metaClass ?? "portal/NavNode";
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <MetaWorkbenchPanel className={className} />
        </div>
      );
    }

    if (
      spec.kind === "semantic_entities" ||
      spec.kind === "semantic_meta_bridge" ||
      spec.kind === "semantic_authoring"
    ) {
      const entities = await portalSessionSemanticEntities(token);
      const classRows = await portalSessionMetaListClasses(token);
      const namespaces = await portalSessionPlatformQuery(
        token,
        PLATFORM_QUERY_SQL.semantic_namespaces.sql,
      );
      const attributes = await portalSessionPlatformQuery(
        token,
        PLATFORM_QUERY_SQL.semantic_attributes.sql,
      );
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          <SemanticLayerWorkspace
            entities={entities}
            namespaces={namespaces}
            attributes={attributes}
            metaClasses={classRows.map((c) => c.className)}
          />
        </div>
      );
    }

    if (spec.kind === "admin_grants") {
      const roles = await portalSessionPlatformQuery(token, PLATFORM_QUERY_SQL.roles.sql);
      const users = await portalSessionPlatformQuery(token, PLATFORM_QUERY_SQL.users.sql);
      const nav = await portalOperatorNavTree(token);
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <AdminGrantsWorkspace
            roles={roles.map((r) => ({
              role_id: Number(r.role_id),
              role_name: String(r.name ?? ""),
            }))}
            users={users.map((u) => ({
              user_id: Number(u.user_id),
              full_name: String(u.full_name ?? u.email ?? ""),
            }))}
            navNodes={nav.map((n) => ({
              node_id: n.nodeId,
              caption: n.caption,
              node_path: n.nodePath,
            }))}
          />
        </div>
      );
    }

    if (spec.kind === "operator_views") {
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <OperatorViewsWorkspaceServer runViewId={viewId} />
        </div>
      );
    }

    if (spec.kind === "operator_dashboards") {
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <OperatorDashboardsWorkspaceServer selectedDashboardId={dashboardId} />
        </div>
      );
    }

    if (spec.kind === "platform_query") {
      if (spec.semanticRequest) {
        const rows = await portalSessionRunSemanticRequest(token, spec.semanticRequest, { limit: 50 });
        const { columns, data } = rowsFromSemantic(spec.semanticRequest, rows);
        return (
          <div className="g-portal-stage">
            <h2>{spec.title}</h2>
            <PlatformRecordTable caption={spec.title} columns={columns} rows={data} />
          </div>
        );
      }
      const queryKey = spec.platformQuery;
      if (!queryKey || !PLATFORM_QUERY_SQL[queryKey]) {
        return <PlaceholderPanel title={spec.title} description="Query mapping is missing." />;
      }
      const def = PLATFORM_QUERY_SQL[queryKey];
      const rows = await portalSessionPlatformQuery(token, def.sql);
      return (
        <div className="g-portal-stage">
          <h2>{spec.title}</h2>
          {spec.description ? <p className="g-host-home__lead">{spec.description}</p> : null}
          <PlatformRecordTable caption={spec.title} columns={def.columns} rows={rows} />
        </div>
      );
    }

    return <PlaceholderPanel title={spec.title} description={spec.description} />;
  } catch (err) {
    if (err instanceof PortalForbiddenError) {
      return (
        <div className="g-portal-stage" role="alert">
          <h2>Access denied</h2>
          <p>Your session lacks permission for this workspace ({spec.title}).</p>
        </div>
      );
    }
    if (err instanceof PortalMetaNotFoundError) {
      return (
        <div className="g-portal-stage" role="alert">
          <h2>Meta class not found</h2>
          <p>Open the class hierarchy and pick a registered Meta class.</p>
        </div>
      );
    }
    throw err;
  }
}

function PlaceholderPanel({ title, description }: { title: string; description?: string }) {
  return (
    <div className="g-portal-stage">
      <h2>{title}</h2>
      <p role="status">
        {description ??
          "This official NavTree destination does not have a host implementation yet. The navigation entry is registered for descendant extensions."}
      </p>
    </div>
  );
}
