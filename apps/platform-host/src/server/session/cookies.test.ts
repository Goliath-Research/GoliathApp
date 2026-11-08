import { describe, expect, it } from "vitest";
import { buildSessionClearCookie, buildSessionSetCookie, readSessionTokenFromCookieHeader } from "./cookies";

describe("session cookies", () => {
  it("round-trips session token in cookie header", () => {
    const set = buildSessionSetCookie("tok_en+code");
    expect(set).toContain("HttpOnly");
    const token = readSessionTokenFromCookieHeader(set.split(";")[0] + ";");
    expect(token).toBe("tok_en+code");
  });

  it("clears cookie with Max-Age=0", () => {
    expect(buildSessionClearCookie()).toContain("Max-Age=0");
  });
});
