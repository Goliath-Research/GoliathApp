import { describe, expect, it } from "vitest";
import { PortalForbiddenError, PortalMetaNotFoundError } from "./bridge";

describe("meta portal error types", () => {
  it("names forbidden errors for BFF 403 mapping", () => {
    expect(new PortalForbiddenError("meta object scope denied").name).toBe("PortalForbiddenError");
  });

  it("names not-found errors for cross-tenant ID guessing", () => {
    expect(new PortalMetaNotFoundError("meta object not found").name).toBe("PortalMetaNotFoundError");
  });
});
