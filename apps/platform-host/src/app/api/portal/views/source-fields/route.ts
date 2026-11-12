import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaClassFields,
  portalSessionSemanticFieldsForRequest,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const url = new URL(request.url);
    const requestCode = url.searchParams.get("semanticRequestCode");
    const metaClassName = url.searchParams.get("metaClassName");
    let fields: Array<{ field: string; label: string; jsonType: string; role?: string }> = [];
    if (requestCode) {
      const rows = await portalSessionSemanticFieldsForRequest(token, requestCode);
      fields = rows.map((r) => ({
        field: r.fieldCode,
        label: r.fieldCode.replace(/_/g, " "),
        jsonType: r.jsonType,
        role: r.role,
      }));
    } else if (metaClassName) {
      const rows = await portalSessionMetaClassFields(token, metaClassName);
      fields = rows.map((r) => ({
        field: r.fieldName,
        label: r.fieldName,
        jsonType: "string",
        role: r.isLocal ? "local" : "inherited",
      }));
    } else {
      return jsonError(400, "semanticRequestCode or metaClassName required");
    }
    const response = NextResponse.json({ fields });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
