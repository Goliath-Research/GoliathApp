import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

export default function DashboardsPage() {
  const spec = resolvePortalWorkspace("/app/views/dashboards");
  return <PortalWorkspacePanel spec={spec} />;
}
