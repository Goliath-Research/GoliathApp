import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { PRODUCT_ID_HEADER } from "@/server/product/request-product";
import { resolveProductIdFromHost } from "@/server/product/resolve";

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
  const host = request.headers.get("host")?.split(":")[0] ?? "";
  const productId = resolveProductIdFromHost(host);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PRODUCT_ID_HEADER, productId);

  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  const response = NextResponse.next({ request: { headers: requestHeaders } });
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
  matcher: ["/app", "/app/:path*", "/api/:path*", "/login"],
};
