import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, PortalSessionDeniedError } from "@/server/portal/bridge";
import { getDomainProgramStructure } from "@/server/portal/domain-program-structure";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

/** GET /api/portal/domain-programs/structure?name=&version= — read-only program structure. */
export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  const url = new URL(request.url);
  const name = url.searchParams.get("name")?.trim();
  const version = url.searchParams.get("version")?.trim();
  if (!name || !version) return jsonError(400, "name and version are required");
  try {
    const token = await readSessionTokenOrThrow();
    const structure = await getDomainProgramStructure(token, name, version);
    return withSessionCookie(NextResponse.json({ structure }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    return mapPortalError(err);
  }
}
