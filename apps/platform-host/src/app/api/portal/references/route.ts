import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionSearchReferences,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

/** GET /api/portal/references?kind=&q=&limit= — reference picker search (x-goliath-ref). */
export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const url = new URL(request.url);
    const kind = (url.searchParams.get("kind") ?? "").trim();
    if (!kind) {
      return jsonError(400, "kind is required");
    }
    const query = url.searchParams.get("q") ?? "";
    const limitRaw = Number.parseInt(url.searchParams.get("limit") ?? "50", 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 200) : 50;
    const rows = await portalSessionSearchReferences(token, kind, query, limit);
    return withSessionCookie(NextResponse.json({ kind, rows }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
