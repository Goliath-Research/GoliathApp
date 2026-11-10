import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import {
  portalSessionListOperatorDashboards,
  portalSessionListOperatorViews,
} from "@/server/portal/bridge";
import { OperatorDashboardsWorkspace } from "@/components/OperatorDashboardsWorkspace";

export async function OperatorDashboardsWorkspaceServer({ selectedDashboardId }: { selectedDashboardId?: number }) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const [dashboards, views] = await Promise.all([
    portalSessionListOperatorDashboards(token),
    portalSessionListOperatorViews(token),
  ]);

  return (
    <OperatorDashboardsWorkspace
      initialDashboards={dashboards.map((d) => ({
        dashboardId: d.dashboardId,
        title: d.title,
        widgetCount: d.widgetCount,
      }))}
      initialViews={views.map((v) => ({
        viewId: v.viewId,
        title: v.title,
        semanticRequestCode: v.semanticRequestCode,
        metaClassName: v.metaClassName,
      }))}
      selectedDashboardId={selectedDashboardId}
    />
  );
}
