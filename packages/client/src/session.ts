/** Snapshot returned by the platform host BFF (`GET /api/session/me`). */
export type PlatformSessionSnapshot = {
  sessionId: number;
  userId: number;
  email: string;
  fullName: string;
  activeScopeId: number | null;
  expiresAtUtc: string;
};

export type SessionTransportErrorCode =
  | "unauthenticated"
  | "forbidden"
  | "misconfigured"
  | "upstream";

export class SessionTransportError extends Error {
  readonly code: SessionTransportErrorCode;
  readonly httpStatus: number;

  constructor(code: SessionTransportErrorCode, message: string, httpStatus: number) {
    super(message);
    this.name = "SessionTransportError";
    this.code = code;
    this.httpStatus = httpStatus;
  }
}
