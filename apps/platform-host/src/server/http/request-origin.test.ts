import { describe, expect, it } from "vitest";
import { oidcCallbackUrl, requestOrigin } from "./request-origin";

describe("requestOrigin", () => {
  it("prefers forwarded host and proto", () => {
    const origin = requestOrigin("http://internal:3000/api/auth/start", (name) => {
      if (name === "x-forwarded-host") return "app.example.com";
      if (name === "x-forwarded-proto") return "https";
      return null;
    });
    expect(origin).toBe("https://app.example.com");
  });

  it("falls back to request URL origin", () => {
    const origin = requestOrigin("https://localhost:3400/login", () => null);
    expect(origin).toBe("https://localhost:3400");
  });

  it("builds public OIDC callback URL for token exchange", () => {
    const request = new Request(
      "http://internal:3000/api/auth/oidc/entra/callback?code=abc&state=xyz",
      { headers: { "x-forwarded-host": "app.example.com", "x-forwarded-proto": "https" } },
    );
    const url = oidcCallbackUrl(request, "entra");
    expect(url.href).toBe("https://app.example.com/api/auth/oidc/entra/callback?code=abc&state=xyz");
  });
});
