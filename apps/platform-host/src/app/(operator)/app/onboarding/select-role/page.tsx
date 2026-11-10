import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { SelectActiveRoleWorkspace } from "@/components/SelectActiveRoleWorkspace";
import {
  portalActiveRoleState,
  portalAutoSelectActiveRole,
  portalListSelectableRoles,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export const dynamic = "force-dynamic";

export default async function SelectRolePage({
  searchParams,
}: {
  searchParams: Promise<{ switch?: string }>;
}) {
  const params = await searchParams;
  const switchMode = params.switch === "1";
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    redirect("/login");
  }

  await portalAutoSelectActiveRole(token);
  const state = await portalActiveRoleState(token);
  if (!switchMode && state.activeRoleId != null) {
    redirect("/app");
  }
  if (!switchMode && state.selectableCount === 0) {
    redirect("/app/onboarding/no-role");
  }
  if (!switchMode && state.selectableCount === 1) {
    redirect("/app");
  }

  const roles = await portalListSelectableRoles(token);
  return <SelectActiveRoleWorkspace initialRoles={roles} switchMode={switchMode} />;
}
