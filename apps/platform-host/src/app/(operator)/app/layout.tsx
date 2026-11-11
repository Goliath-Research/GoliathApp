import { redirect } from "next/navigation";
import {
  PortalBridgeMisconfiguredError,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { requirePortalSession } from "@/server/session/require";

export const dynamic = "force-dynamic";

export default async function OperatorAppLayout({ children }: { children: React.ReactNode }) {
  try {
    await requirePortalSession();
    return <>{children}</>;
  } catch (err) {
    if (err instanceof PortalBridgeMisconfiguredError) {
      redirect("/?auth=unconfigured");
    }
    if (err instanceof PortalSessionDeniedError) {
      redirect("/login");
    }
    throw err;
  }
}
