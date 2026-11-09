import { afterEach, describe, expect, it, vi } from "vitest";
import { devLoginAllowed } from "./env";

describe("devLoginAllowed", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is false in production even when flag is set", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_DEV_LOGIN", "1");
    expect(devLoginAllowed()).toBe(false);
  });

  it("allows dev login in production only for Playwright E2E integration", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_DEV_LOGIN", "1");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_E2E_INTEGRATION", "1");
    expect(devLoginAllowed()).toBe(true);
  });

  it("requires explicit flag outside production", () => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("GOLIATH_PLATFORM_HOST_DEV_LOGIN", "");
    expect(devLoginAllowed()).toBe(false);
    vi.stubEnv("GOLIATH_PLATFORM_HOST_DEV_LOGIN", "1");
    expect(devLoginAllowed()).toBe(true);
  });
});
