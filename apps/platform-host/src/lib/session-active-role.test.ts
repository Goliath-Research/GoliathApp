import { describe, expect, it } from "vitest";
import { shouldRedirectToNoRole, shouldRedirectToRoleSelection } from "./session-active-role";

describe("session-active-role gate", () => {
  it("redirects when multiple grants and no selection", () => {
    expect(
      shouldRedirectToRoleSelection({
        activeRoleId: null,
        selectableCount: 2,
        needsSelection: true,
      }),
    ).toBe(true);
  });

  it("does not redirect when a role is active", () => {
    expect(
      shouldRedirectToRoleSelection({
        activeRoleId: 3,
        selectableCount: 2,
        needsSelection: false,
      }),
    ).toBe(false);
  });

  it("sends users with zero grants to no-role", () => {
    expect(
      shouldRedirectToNoRole({
        activeRoleId: null,
        selectableCount: 0,
        needsSelection: false,
      }),
    ).toBe(true);
  });
});
