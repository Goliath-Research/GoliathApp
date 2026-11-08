import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const COOKIE_NAME = "goliath_oidc_tx";

export type OidcTransaction = {
  state: string;
  nonce: string;
  codeVerifier: string;
  providerId: string;
  scopeId: number;
  exp: number;
};

function signingKey(): string | null {
  const key = process.env.GOLIATH_AUTH_STATE_SECRET?.trim();
  return key && key.length >= 16 ? key : null;
}

function sign(payloadB64: string): string {
  const key = signingKey();
  if (!key) throw new Error("GOLIATH_AUTH_STATE_SECRET is not configured");
  return createHmac("sha256", key).update(payloadB64).digest("base64url");
}

export function createOidcTransaction(
  input: Omit<OidcTransaction, "state" | "nonce" | "codeVerifier" | "exp">,
): OidcTransaction {
  return {
    ...input,
    state: randomBytes(24).toString("base64url"),
    nonce: randomBytes(24).toString("base64url"),
    codeVerifier: randomBytes(32).toString("base64url"),
    exp: Date.now() + 10 * 60_000,
  };
}

export function buildOidcTransactionCookie(tx: OidcTransaction): string {
  const payload = Buffer.from(JSON.stringify(tx), "utf8").toString("base64url");
  const sig = sign(payload);
  const value = `${payload}.${sig}`;
  const secure = process.env.NODE_ENV === "production";
  const parts = [
    `${COOKIE_NAME}=${encodeURIComponent(value)}`,
    "HttpOnly",
    "Path=/api/auth/oidc",
    "SameSite=Lax",
    "Max-Age=600",
  ];
  if (secure) parts.push("Secure");
  return parts.join("; ");
}

export function parseOidcTransactionCookie(header: string | null): OidcTransaction | null {
  if (!header || !signingKey()) return null;
  for (const part of header.split(";")) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName !== COOKIE_NAME) continue;
    const value = decodeURIComponent(rest.join("="));
    const [payload, sig] = value.split(".");
    if (!payload || !sig) return null;
    const expected = sign(payload);
    try {
      const a = Buffer.from(sig);
      const b = Buffer.from(expected);
      if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
    } catch {
      return null;
    }
    const tx = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as OidcTransaction;
    if (!tx.exp || Date.now() > tx.exp) return null;
    return tx;
  }
  return null;
}

export function clearOidcTransactionCookie(): string {
  const secure = process.env.NODE_ENV === "production";
  const parts = [`${COOKIE_NAME}=`, "HttpOnly", "Path=/api/auth/oidc", "Max-Age=0", "SameSite=Lax"];
  if (secure) parts.push("Secure");
  return parts.join("; ");
}

export function pkceChallengeS256(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}
