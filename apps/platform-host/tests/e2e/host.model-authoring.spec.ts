import { expect, test } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3400";

test.describe("model authoring (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("semantic layer workspace loads authoring chrome", async ({ page }) => {
    await page.goto("/app/semantic");
    await expect(page.getByRole("heading", { name: "Semantic layer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Register entity" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export as package SQL" })).toBeVisible();
  });

  test("meta home shows model authoring panel", async ({ page }) => {
    await page.goto("/app/meta/classes");
    await expect(page.getByRole("heading", { name: "Model authoring" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create class" })).toBeVisible();
  });
});
