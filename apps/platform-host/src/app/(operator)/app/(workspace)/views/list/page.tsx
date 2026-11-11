import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

export default async function ViewsListPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const query = await searchParams;
  const spec = resolvePortalWorkspace("/app/views/list");
  const viewId = query.view ? Number.parseInt(query.view, 10) : undefined;
  return <PortalWorkspacePanel spec={spec} viewId={Number.isFinite(viewId) ? viewId : undefined} />;
}
