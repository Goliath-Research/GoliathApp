import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPlatformProductRegistryForTests } from "./registry";
import { resolveProductIdFromHost } from "./resolve";

describe("resolveProductIdFromHost", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    resetPlatformProductRegistryForTests();
  });

  it("uses default product when registry is unset", () => {
    expect(resolveProductIdFromHost("unknown.example")).toBe("goliathapp");
  });

  it("matches configured hostnames", () => {
    vi.stubEnv(
      "GOLIATH_PLATFORM_PRODUCTS_JSON",
      JSON.stringify({
        defaultProductId: "goliathapp",
        products: [
          {
            id: "goliathapp",
            displayName: "Goliath",
            portalSubtitle: "Platform portal",
            hostnames: ["app.example.com", "localhost"],
          },
          {
            id: "child_app",
            displayName: "Child",
            portalSubtitle: "Child portal",
            hostnames: ["child.example.com"],
          },
        ],
      }),
    );
    expect(resolveProductIdFromHost("child.example.com")).toBe("child_app");
    expect(resolveProductIdFromHost("app.example.com")).toBe("goliathapp");
  });
});
