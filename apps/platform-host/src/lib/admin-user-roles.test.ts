import { describe, expect, it } from "vitest";
import { formatRoleGrantLabel, formatRoleGrantsSummary } from "./admin-user-roles";

describe("admin-user-roles", () => {
  it("formats grant with scope name", () => {
    expect(
      formatRoleGrantLabel({ grant_id: 1, role_name: "organization_admin", scope_name: "Acme Org" }),
    ).toBe("organization_admin (Acme Org)");
  });

  it("summarizes empty grants", () => {
    expect(formatRoleGrantsSummary([])).toBe("None — grant role");
  });

  it("summarizes multiple grants", () => {
    expect(
      formatRoleGrantsSummary([
        { grant_id: 1, role_name: "reader", scope_name: "Org" },
        { grant_id: 2, role_name: "organization_admin", scope_name: "Org" },
      ]),
    ).toBe("reader (Org), organization_admin (Org)");
  });
});
