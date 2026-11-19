import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, PortalSessionDeniedError } from "@/server/portal/bridge";
import { deleteMetaTreeNode, listMetaTree, listMetaTreeClasses, moveMetaTreeNode } from "@/server/portal/meta-tree";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

function optionalInt(value: unknown): number | null | undefined {
  if (value === null) return null;
  if (value === undefined) return undefined;
  const n = Number(value);
  return Number.isInteger(n) ? n : undefined;
}

/** GET /api/portal/meta-tree?class=<name> — tree rows; without ?class, the tree-shaped classes. */
export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  try {
    const token = await readSessionTokenOrThrow();
    const className = new URL(request.url).searchParams.get("class");
    const body = className
      ? { className, rows: await listMetaTree(token, className) }
      : { classes: await listMetaTreeClasses(token) };
    return withSessionCookie(NextResponse.json(body), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    return mapPortalError(err);
  }
}

/** POST /api/portal/meta-tree — { action: "move" | "delete", className, objId, parentObjId?, position? }. */
export async function POST(request: Request) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  try {
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as Record<string, unknown>;
    const className = typeof body.className === "string" ? body.className : "";
    const objId = optionalInt(body.objId);
    if (!className || objId == null) return jsonError(400, "className and objId are required");
    if (body.action === "move") {
      const parent = optionalInt(body.parentObjId);
      const position = optionalInt(body.position);
      if (parent === undefined && body.parentObjId !== undefined) return jsonError(400, "parentObjId must be an integer or null");
      const pos = await moveMetaTreeNode(token, className, objId, parent ?? null, position ?? null);
      return withSessionCookie(NextResponse.json({ ok: true, position: pos }), token);
    }
    if (body.action === "delete") {
      await deleteMetaTreeNode(token, className, objId);
      return withSessionCookie(NextResponse.json({ ok: true }), token);
    }
    return jsonError(400, "unknown action");
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    return mapPortalError(err);
  }
}
