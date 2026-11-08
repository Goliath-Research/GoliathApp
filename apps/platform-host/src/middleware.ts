import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE_NAME =
  process.env.GOLIATH_PLATFORM_SESSION_COOKIE?.trim() || "goliath_platform_session";

function sessionMaxAgeSeconds(): number {
  const maxAge = Number(process.env.GOLIATH_PLATFORM_SESSION_MAX_AGE_SECONDS ?? "1800");
  return Number.isFinite(maxAge) && maxAge > 0 ? maxAge : 1800;
}

/**
 * Reissue session cookie Max-Age on /app navigations (RSC cannot call cookies().set).
 * DB idle extension still happens in requirePortalSession via sp_session_touch.
 */
export function middleware(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return NextResponse.next();

  const response = NextResponse.next();
  const secure = process.env.NODE_ENV === "production";
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: sessionMaxAgeSeconds(),
  });
  return response;
}

export const config = {
  matcher: ["/app", "/app/:path*"],
};
