import "server-only";

import { NextResponse } from "next/server";
import {
  PortalBridgeMisconfiguredError,
  PortalForbiddenError,
  PortalMetaNotFoundError,
  PortalMetaConflictError,
  PortalMetaValidationError,
  PortalSessionDeniedError,
  logPortalBridgeError,
  portalBridgeErrorMessage,
} from "../portal/bridge";
import { resolvePortalForbiddenBody, resolvePortalNotFoundBody } from "./errors-normalization";

export { resolvePortalForbiddenBody, resolvePortalNotFoundBody } from "./errors-normalization";

export function jsonError(status: number, error: string) {
  return NextResponse.json({ error }, { status });
}

export function mapPortalError(err: unknown) {
  if (err instanceof PortalBridgeMisconfiguredError) {
    return jsonError(503, "portal bridge is not configured");
  }
  if (err instanceof PortalSessionDeniedError) {
    return jsonError(401, err.message);
  }
  if (err instanceof PortalMetaNotFoundError) {
    return jsonError(404, resolvePortalNotFoundBody(err.message));
  }
  if (err instanceof PortalForbiddenError) {
    return jsonError(403, resolvePortalForbiddenBody(err.message));
  }
  if (err instanceof PortalMetaValidationError) {
    return jsonError(400, err.message);
  }
  if (err instanceof PortalMetaConflictError) {
    return jsonError(409, err.message);
  }
  if (err instanceof Error && err.message && !err.message.includes("internal error")) {
    const friendly = portalBridgeErrorMessage(err);
    if (friendly !== err.message || err.message.length < 200) {
      logPortalBridgeError("portal route", err);
      return jsonError(500, friendly);
    }
  }
  logPortalBridgeError("portal route internal", err);
  return jsonError(500, "internal error");
}
