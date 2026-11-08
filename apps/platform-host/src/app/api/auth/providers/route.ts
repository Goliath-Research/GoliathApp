import { NextResponse } from "next/server";
import { listPublicAuthProviders } from "@/server/auth/registry";

export async function GET(request: Request) {
  const origin = new URL(request.url).origin;
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
