import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { platformHostRevision, platformHostVersion } from "./build-info";

describe("build-info", () => {
  const env = process.env;

  beforeEach(() => {
    process.env = { ...env };
  });

  afterEach(() => {
    process.env = env;
  });

  it("reads revision from PLATFORM_HOST_REVISION", () => {
    process.env.PLATFORM_HOST_REVISION = "eaf50e67abcd";
    expect(platformHostRevision()).toBe("eaf50e67abcd");
  });

  it("reads version default", () => {
    delete process.env.PLATFORM_HOST_VERSION;
    expect(platformHostVersion()).toBe("0.1.0-p0");
  });
});
