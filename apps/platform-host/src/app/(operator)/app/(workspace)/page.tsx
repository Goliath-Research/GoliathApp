import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

export default function OperatorHomePage() {
  const spec = resolvePortalWorkspace("/app");
  return <PortalWorkspacePanel spec={spec} />;
}
