import "server-only";

import { NextResponse } from "next/server";
import { PortalBridgeMisconfiguredError, PortalSessionDeniedError } from "../portal/bridge";

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
  return jsonError(500, "internal error");
}
