import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { nodePathFromUrlPathname, resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

export default async function OperatorCatchAllPage({
  params,
  searchParams,
}: {
  params: Promise<{ segments: string[] }>;
  searchParams: Promise<{ class?: string; view?: string; dashboard?: string }>;
}) {
  const { segments } = await params;
  const query = await searchParams;
  const pathname = `/app/${segments.join("/")}`;
  const spec = resolvePortalWorkspace(nodePathFromUrlPathname(pathname));
  const viewId = query.view ? Number.parseInt(query.view, 10) : undefined;
  const dashboardId = query.dashboard ? Number.parseInt(query.dashboard, 10) : undefined;
  return (
    <PortalWorkspacePanel
      spec={spec}
      metaClassOverride={query.class}
      viewId={Number.isFinite(viewId) ? viewId : undefined}
      dashboardId={Number.isFinite(dashboardId) ? dashboardId : undefined}
      semanticHighlight={pathname.startsWith("/app/semantic") ? "" : undefined}
    />
  );
}
