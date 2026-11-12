import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import {
  portalSessionListOperatorDashboards,
  portalSessionListOperatorViews,
} from "@/server/portal/bridge";
import { OperatorDashboardEditor } from "@/components/OperatorDashboardEditor";

export async function OperatorDashboardsWorkspaceServer({
  selectedDashboardId,
  viewMode,
}: {
  selectedDashboardId?: number;
  viewMode?: boolean;
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const [dashboards, views] = await Promise.all([
    portalSessionListOperatorDashboards(token),
    portalSessionListOperatorViews(token),
  ]);

  return (
    <OperatorDashboardEditor
      initialDashboards={dashboards.map((d) => ({
        dashboardId: d.dashboardId,
        title: d.title,
        widgetCount: d.widgetCount,
        visibility: d.visibility,
      }))}
      initialViews={views.map((v) => ({
        viewId: v.viewId,
        title: v.title,
        semanticRequestCode: v.semanticRequestCode,
        metaClassName: v.metaClassName,
      }))}
      selectedDashboardId={selectedDashboardId}
      viewMode={viewMode}
    />
  );
}
