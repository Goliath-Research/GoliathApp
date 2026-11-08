import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildOidcTransactionCookie,
  createOidcTransaction,
  parseOidcTransactionCookie,
  pkceChallengeS256,
} from "./state-cookie";

describe("oidc transaction cookie", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("round-trips signed transaction", () => {
    vi.stubEnv("GOLIATH_AUTH_STATE_SECRET", "test-secret-with-enough-bytes");
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 42 });
    const cookie = buildOidcTransactionCookie(tx);
    const header = cookie.split(";")[0] + ";";
    const parsed = parseOidcTransactionCookie(header);
    expect(parsed?.providerId).toBe("entra");
    expect(parsed?.state).toBe(tx.state);
    expect(parsed?.codeVerifier).toBe(tx.codeVerifier);
  });

  it("computes PKCE S256", () => {
    const challenge = pkceChallengeS256("verifier");
    expect(challenge.length).toBeGreaterThan(10);
  });
});
