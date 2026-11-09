import { describe, expect, it } from "vitest";
import { resolvePortalForbiddenBody, resolvePortalNotFoundBody } from "./errors-normalization";

describe("resolvePortalNotFoundBody", () => {
  it("keeps class-not-found messaging distinct from instance APIs", () => {
    expect(resolvePortalNotFoundBody("meta class not found")).toBe("meta class not found");
  });

  it("normalizes identity-independent Meta permission failures", () => {
    expect(resolvePortalForbiddenBody("meta permission denied for active scope")).toBe(
      "meta permission denied",
    );
    expect(resolvePortalForbiddenBody("active scope required for meta instance access")).toBe(
      "meta permission denied",
    );
  });

  it("normalizes every instance-not-found path to the same body", () => {
    const crossScope = resolvePortalNotFoundBody("meta object scope denied");
    const missing = resolvePortalNotFoundBody("meta object not found");
    const unmapped = resolvePortalNotFoundBody("meta object not found");
    expect(crossScope).toBe(missing);
    expect(missing).toBe(unmapped);
    expect(crossScope).toBe("meta object not found");
  });
});
