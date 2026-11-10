import { expect, test } from "@playwright/test";

test.describe("admin user invite (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("invite form shows success and validation error", async ({ page, request }) => {
    await page.goto("/app/admin/users");
    await expect(page.getByRole("heading", { name: "Invite user" })).toBeVisible();

    const inviteForm = page.locator("form").filter({ hasText: "Invite user" });
    await inviteForm.getByLabel("Email").fill(`pending-${Date.now()}@test.example`);
    await inviteForm.getByRole("button", { name: "Record invitation" }).click();
    await expect(page.getByRole("alert")).toContainText(/role/i);

    const suffix = `${Date.now()}`;
    const email = `e2e-invite-${suffix}@test.example`;
    const roleRes = await request.post("/api/portal/security", {
      data: { action: "create_role", name: `e2e_invite_role_${suffix}` },
    });
    expect(roleRes.ok()).toBeTruthy();
    const { roleId } = (await roleRes.json()) as { roleId: number };

    await inviteForm.getByLabel("Email").fill(email);
    await inviteForm.getByLabel("Default role").selectOption(String(roleId));
    await inviteForm.getByRole("button", { name: "Record invitation" }).click();
    await expect(page.getByRole("status")).toContainText("Invitation recorded");

    const dup = await request.post("/api/portal/security", {
      data: { action: "invite_user", email, defaultRoleId: roleId },
    });
    expect(dup.status()).toBe(409);
    const dupBody = (await dup.json()) as { error?: string };
    expect(dupBody.error ?? "").toMatch(/pending invitation/i);
  });
});
