import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, PortalSessionDeniedError } from "@/server/portal/bridge";
import {
  isRecordEditorEntity,
  listRecords,
  RecordEditorInputError,
  saveRecord,
} from "@/server/portal/record-editors";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ entity: string }> };

/** GET /api/portal/records/:entity — rows for the record editor list. */
export async function GET(_request: Request, ctx: Ctx) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  const { entity } = await ctx.params;
  if (!isRecordEditorEntity(entity)) return jsonError(404, "unknown record entity");
  try {
    const token = await readSessionTokenOrThrow();
    const rows = await listRecords(token, entity);
    return withSessionCookie(NextResponse.json({ entity, rows }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    if (err instanceof RecordEditorInputError) return jsonError(400, err.message);
    return mapPortalError(err);
  }
}

/** POST /api/portal/records/:entity — { key?: string, document: {...} } create or update. */
export async function POST(request: Request, ctx: Ctx) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  const { entity } = await ctx.params;
  if (!isRecordEditorEntity(entity)) return jsonError(404, "unknown record entity");
  try {
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { key?: string | null; document?: unknown };
    const saved = await saveRecord(token, entity, body.key ?? null, body.document);
    return withSessionCookie(NextResponse.json({ entity, ...saved }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    if (err instanceof RecordEditorInputError) return jsonError(400, err.message);
    return mapPortalError(err);
  }
}
