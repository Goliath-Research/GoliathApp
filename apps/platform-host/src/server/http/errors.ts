import "server-only";

import { NextResponse } from "next/server";
import {
  PortalBridgeMisconfiguredError,
  PortalForbiddenError,
  PortalMetaNotFoundError,
  PortalMetaValidationError,
  PortalSessionDeniedError,
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
  return jsonError(500, "internal error");
}
