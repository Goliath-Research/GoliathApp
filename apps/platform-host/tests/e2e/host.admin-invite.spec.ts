import { expect, test } from "@playwright/test";

test.describe("admin user invite (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("invite form shows success and validation error", async ({ page, request }) => {
    test.setTimeout(90_000);
    await page.goto("/app/admin/users");
    await page.getByTestId("record-grid-user").getByRole("button", { name: "Invite user" }).click();
    const inviteDialog = page.getByTestId("record-dialog-invite_user");
    await expect(inviteDialog.getByRole("heading", { name: "Invite user" })).toBeVisible();

    const inviteForm = inviteDialog.locator("form");
    await inviteForm.getByLabel("Email").fill(`pending-${Date.now()}@test.example`);
    await inviteForm.getByRole("button", { name: "Record invitation" }).click();
    await expect(page.locator("p.g-admin-error")).toContainText(/role/i);

    const suffix = `${Date.now()}`;
    const email = `e2e-invite-${suffix}@test.example`;
    await inviteForm.getByLabel("Email").fill(email);
    await inviteForm.getByLabel("Default role").selectOption({ label: "organization_admin" });
    const roleId = await inviteForm.getByLabel("Default role").inputValue();
    await inviteForm.getByRole("button", { name: "Record invitation" }).click();
    await expect(page.getByText(/Invitation recorded/i)).toBeVisible();

    const dup = await request.post("/api/portal/security", {
      data: { action: "invite_user", email, defaultRoleId: Number(roleId) },
    });
    expect(dup.status()).toBe(409);
    const dupBody = (await dup.json()) as { error?: string };
    expect(dupBody.error ?? "").toMatch(/pending invitation/i);
  });
});
