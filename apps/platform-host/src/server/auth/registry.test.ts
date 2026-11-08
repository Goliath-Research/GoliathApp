import { describe, expect, it } from "vitest";
import { assertRedirectOriginAllowed } from "./origin-allowlist";
import type { OidcProviderConfig } from "./types";

const baseCfg: OidcProviderConfig = {
  providerId: "test",
  displayName: "Test",
  method: "oidc_authorization_code",
  issuer: "https://issuer.example",
  clientId: "cid",
  clientSecret: "secret",
  scopeId: 1,
  scopes: ["openid"],
  allowedOrigins: ["https://app.example.com"],
};

describe("assertRedirectOriginAllowed", () => {
  it("matches canonical origin when allowlist omits default port", () => {
    expect(() =>
      assertRedirectOriginAllowed("https://app.example.com:443", baseCfg),
    ).not.toThrow();
  });

  it("rejects origins not on explicit allowlist", () => {
    expect(() => assertRedirectOriginAllowed("https://evil.example", baseCfg)).toThrow(
      /allowlisted/,
    );
  });

  it("requires configured allowedOrigins", () => {
    const cfg = { ...baseCfg, allowedOrigins: [] };
    expect(() => assertRedirectOriginAllowed("https://app.example.com", cfg)).toThrow(
      /allowedOrigins is required/,
    );
  });
});
