import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { resolveWorkspaceForPathname } from "@/lib/portal-nav-resolve";

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
  const { spec, metaClassOverride: navMetaClass } = await resolveWorkspaceForPathname(pathname);
  const viewId = query.view ? Number.parseInt(query.view, 10) : undefined;
  const dashboardId = query.dashboard ? Number.parseInt(query.dashboard, 10) : undefined;
  return (
    <PortalWorkspacePanel
      spec={spec}
      metaClassOverride={query.class ?? navMetaClass}
      viewId={Number.isFinite(viewId) ? viewId : undefined}
      dashboardId={Number.isFinite(dashboardId) ? dashboardId : undefined}
      semanticHighlight={pathname.startsWith("/app/semantic") ? "" : undefined}
    />
  );
}
