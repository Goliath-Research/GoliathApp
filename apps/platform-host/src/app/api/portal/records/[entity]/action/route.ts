import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, PortalSessionDeniedError } from "@/server/portal/bridge";
import { isRecordEditorEntity, RecordEditorInputError, runRecordAction } from "@/server/portal/record-editors";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

/** POST /api/portal/records/:entity/action — { action, key, document? } (publish, revoke, defaults). */
export async function POST(request: Request, ctx: { params: Promise<{ entity: string }> }) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  const { entity } = await ctx.params;
  if (!isRecordEditorEntity(entity)) return jsonError(404, "unknown record entity");
  try {
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { action?: string; key?: string; document?: unknown };
    if (!body.action || !body.key) return jsonError(400, "action and key are required");
    const result = await runRecordAction(token, entity, body.action, body.key, body.document);
    return withSessionCookie(NextResponse.json({ entity, action: body.action, result }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    if (err instanceof RecordEditorInputError) return jsonError(400, err.message);
    return mapPortalError(err);
  }
}
