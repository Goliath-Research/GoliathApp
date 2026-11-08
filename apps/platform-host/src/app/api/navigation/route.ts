import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { coercePresentationKind } from "@goliath/client";
import {
  isPortalBridgeConfigured,
  portalOperatorNavTree,
  portalSessionTouch,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { jsonError, mapPortalError } from "@/server/http/errors";

export async function GET() {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      return jsonError(401, "unauthenticated");
    }
    const touched = await portalSessionTouch(token);
    if (!touched) {
      return jsonError(401, "session expired");
    }
    const rows = await portalOperatorNavTree(token);
    return NextResponse.json({
      nodes: rows.map((row) => ({
        nodeId: row.nodeId,
        parentId: row.parentId,
        caption: row.caption,
        seq: row.seq,
        presentationKind: coercePresentationKind(row.presentationKind),
      })),
    });
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
