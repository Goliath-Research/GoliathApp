import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

export default async function DashboardsPage({
  searchParams,
}: {
  searchParams: Promise<{ dashboard?: string; mode?: string }>;
}) {
  const query = await searchParams;
  const spec = resolvePortalWorkspace("/app/views/dashboards");
  const dashboardId = query.dashboard ? Number.parseInt(query.dashboard, 10) : undefined;
  const viewMode = query.mode === "view";
  return (
    <PortalWorkspacePanel
      spec={spec}
      dashboardId={Number.isFinite(dashboardId) ? dashboardId : undefined}
      dashboardViewMode={viewMode}
    />
  );
}
