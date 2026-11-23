import { NextResponse } from "next/server";
import { listAllowedRedirectOrigins, listPublicAuthProviders } from "@/server/auth/registry";
import { allowlistedOriginFromRequest } from "@/server/http/request-origin";

export async function GET(request: Request) {
  const origin = allowlistedOriginFromRequest(request, listAllowedRedirectOrigins());
  return NextResponse.json({
    providers: listPublicAuthProviders(origin),
    supportedMethods: {
      oidc_authorization_code: {
        status: "implemented",
        notes: "Authorization code + PKCE via openid-client; requires DB-linked ExternalIdentities.",
      },
      password: { status: "planned", notes: "Not implemented in this PR." },
      passkey: { status: "planned", notes: "Not implemented in this PR." },
      email_magic_link: { status: "planned", notes: "Not implemented in this PR." },
    },
  });
}
