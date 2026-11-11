import * as oauth from "openid-client";
import type { OidcProviderConfig } from "./types";
import { pkceChallengeS256 } from "./state-cookie";

export async function buildOidcAuthorizationUrl(
  cfg: OidcProviderConfig,
  redirectUri: string,
  state: string,
  nonce: string,
  codeVerifier: string,
): Promise<string> {
  const config = await oauth.discovery(new URL(cfg.issuer), cfg.clientId, cfg.clientSecret);
  const codeChallenge = pkceChallengeS256(codeVerifier);
  return oauth.buildAuthorizationUrl(config, {
    redirect_uri: redirectUri,
    scope: cfg.scopes.join(" "),
    state,
    nonce,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
  }).href;
}

export async function exchangeOidcCallback(
  cfg: OidcProviderConfig,
  callbackUrl: URL,
  state: string,
  nonce: string,
  codeVerifier: string,
): Promise<{ issuer: string; subject: string; snapshot: string }> {
  const config = await oauth.discovery(new URL(cfg.issuer), cfg.clientId, cfg.clientSecret);
  const tokens = await oauth.authorizationCodeGrant(config, callbackUrl, {
    expectedState: state,
    expectedNonce: nonce,
    pkceCodeVerifier: codeVerifier,
  });
  const claims = tokens.claims();
  if (!claims?.sub) {
    throw new Error("id_token missing sub");
  }
  const issuer = String(claims.iss ?? cfg.issuer);
  const subject = String(claims.sub);
  const emailClaim =
    typeof claims.email === "string"
      ? claims.email
      : typeof claims.preferred_username === "string"
        ? claims.preferred_username
        : typeof claims.upn === "string"
          ? claims.upn
          : null;
  const snapshot = JSON.stringify({
    iss: issuer,
    sub: subject,
    aud: claims.aud,
    email: emailClaim,
    name: typeof claims.name === "string" ? claims.name : null,
  });
  return { issuer, subject, snapshot };
}
