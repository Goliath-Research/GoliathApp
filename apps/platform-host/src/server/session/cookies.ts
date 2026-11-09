export const SESSION_COOKIE_NAME =
  process.env.GOLIATH_PLATFORM_SESSION_COOKIE?.trim() || "goliath_platform_session";

const SESSION_COOKIE_PATH = "/";

export type SessionCookieOptions = {
  secure: boolean;
  maxAgeSeconds: number;
};

export function sessionCookieOptions(): SessionCookieOptions {
  const e2eIntegration = process.env.GOLIATH_PLATFORM_HOST_E2E_INTEGRATION === "1";
  const secure = process.env.NODE_ENV === "production" && !e2eIntegration;
  const maxAge = Number(process.env.GOLIATH_PLATFORM_SESSION_MAX_AGE_SECONDS ?? "1800");
  return {
    secure,
    maxAgeSeconds: Number.isFinite(maxAge) && maxAge > 0 ? maxAge : 1800,
  };
}

export function buildSessionSetCookie(sessionToken: string): string {
  const { secure, maxAgeSeconds } = sessionCookieOptions();
  const parts = [
    `${SESSION_COOKIE_NAME}=${encodeURIComponent(sessionToken)}`,
    "HttpOnly",
    "Path=" + SESSION_COOKIE_PATH,
    "SameSite=Lax",
    `Max-Age=${maxAgeSeconds}`,
  ];
  if (secure) parts.push("Secure");
  return parts.join("; ");
}

/** Refreshes Max-Age after portal.sp_session_touch (sliding idle expiry). */
export function sessionCookieStoreOptions(): {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
} {
  const { secure, maxAgeSeconds } = sessionCookieOptions();
  return {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: SESSION_COOKIE_PATH,
    maxAge: maxAgeSeconds,
  };
}

export function buildSessionClearCookie(): string {
  const { secure } = sessionCookieOptions();
  const parts = [
    `${SESSION_COOKIE_NAME}=`,
    "HttpOnly",
    "Path=" + SESSION_COOKIE_PATH,
    "Max-Age=0",
    "SameSite=Lax",
  ];
  if (secure) parts.push("Secure");
  return parts.join("; ");
}

export function readSessionTokenFromCookieHeader(cookieHeader: string | null): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName === SESSION_COOKIE_NAME) {
      const value = rest.join("=");
      if (!value) return null;
      try {
        return decodeURIComponent(value);
      } catch {
        return value;
      }
    }
  }
  return null;
}
