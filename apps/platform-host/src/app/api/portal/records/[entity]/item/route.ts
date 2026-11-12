import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, PortalSessionDeniedError } from "@/server/portal/bridge";
import { getRecord, isRecordEditorEntity, RecordEditorInputError } from "@/server/portal/record-editors";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

/** GET /api/portal/records/:entity/item?key= — editable document for one record. */
export async function GET(request: Request, ctx: { params: Promise<{ entity: string }> }) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  const { entity } = await ctx.params;
  if (!isRecordEditorEntity(entity)) return jsonError(404, "unknown record entity");
  try {
    const token = await readSessionTokenOrThrow();
    const key = new URL(request.url).searchParams.get("key") ?? "";
    if (!key) return jsonError(400, "key is required");
    const document = await getRecord(token, entity, key);
    return withSessionCookie(NextResponse.json({ entity, key, document }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    if (err instanceof RecordEditorInputError) return jsonError(400, err.message);
    return mapPortalError(err);
  }
}
