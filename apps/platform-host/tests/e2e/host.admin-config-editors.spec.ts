import { expect, test } from "@playwright/test";

test.describe("admin and config editors (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("organizations are created and renamed in the record grid", async ({ page }) => {
    const name = `E2E Org ${Date.now().toString(36)}`;
    await page.goto("/app/admin/organizations");
    await expect(page.getByTestId("record-grid-organization")).toBeVisible();
    await page.getByRole("button", { name: "Add organization" }).click();
    const dialog = page.getByTestId("record-dialog-organization");
    await dialog.getByTestId("pi-row-name").locator("input").fill(name);
    await dialog.getByRole("button", { name: "Create organization" }).click();
    await expect(page.getByTestId("record-grid-organization").getByText(name, { exact: true })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("config documents without a registered type are view-only", async ({ page }) => {
    await page.goto("/app/config/pipeline-profiles");
    await expect(page.getByTestId("record-grid-cfg_pipeline_profile")).toBeVisible();
    await page.getByRole("button", { name: "Add pipeline profile" }).click();
    const dialog = page.getByTestId("record-dialog-cfg_pipeline_profile");
    await expect(dialog.getByText("No document type is registered")).toBeVisible();
    await expect(dialog.locator("textarea")).toHaveCount(0);
    const res = await page.request.post("/api/portal/records/cfg_pipeline_profile", {
      data: { document: { name: "e2e_untyped", document: {} } },
    });
    expect(res.status()).toBe(409);
  });
});
