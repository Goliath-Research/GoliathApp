import { PortalWorkspacePanel } from "@/components/PortalWorkspacePanel";
import { nodePathFromUrlPathname, resolvePortalWorkspace } from "@/lib/portal-node-registry";

export const dynamic = "force-dynamic";

const DEFAULT_CLASS = "portal/NavNode";

export default async function MetaRoutePage({
  searchParams,
}: {
  searchParams: Promise<{ class?: string }>;
}) {
  const params = await searchParams;
  const className = (params.class ?? DEFAULT_CLASS).trim();
  const spec = resolvePortalWorkspace(nodePathFromUrlPathname("/app/meta"));
  return <PortalWorkspacePanel spec={spec} metaClassOverride={className} />;
}
