import { afterEach, describe, expect, it, vi } from "vitest";
import {
  devLoginAllowlistedUserIds,
  resolveDevEstablishUserId,
} from "./env";

describe("resolveDevEstablishUserId", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses env default when header omitted", () => {
    vi.stubEnv("GOLIATH_P1_DEV_LOGIN_USER_ID", "42");
    expect(resolveDevEstablishUserId(null)).toEqual({ ok: true, userId: 42 });
  });

  it("ignores header outside E2E integration (no arbitrary principal)", () => {
    vi.stubEnv("GOLIATH_P1_DEV_LOGIN_USER_ID", "42");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_E2E_INTEGRATION", "");
    expect(resolveDevEstablishUserId("99")).toEqual({ ok: true, userId: 42 });
  });

  it("rejects non-allowlisted user in E2E integration", () => {
    vi.stubEnv("GOLIATH_P1_DEV_LOGIN_USER_ID", "42");
    vi.stubEnv("GOLIATH_E2E_DENIED_USER_ID", "43");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_E2E_INTEGRATION", "1");
    expect(resolveDevEstablishUserId("999")).toEqual({
      ok: false,
      status: 403,
      message: "dev login denied",
    });
  });

  it("allows only env-pinned identities in E2E integration", () => {
    vi.stubEnv("GOLIATH_P1_DEV_LOGIN_USER_ID", "42");
    vi.stubEnv("GOLIATH_E2E_DENIED_USER_ID", "43");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_E2E_INTEGRATION", "1");
    expect(devLoginAllowlistedUserIds().sort()).toEqual([42, 43]);
    expect(resolveDevEstablishUserId("43")).toEqual({ ok: true, userId: 43 });
    expect(resolveDevEstablishUserId("42")).toEqual({ ok: true, userId: 42 });
  });

  it("rejects malformed header before session open", () => {
    vi.stubEnv("GOLIATH_P1_DEV_LOGIN_USER_ID", "42");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_E2E_INTEGRATION", "1");
    expect(resolveDevEstablishUserId("0")).toEqual({
      ok: false,
      status: 403,
      message: "dev login denied",
    });
  });
});
