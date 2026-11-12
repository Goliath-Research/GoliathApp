import { expect, test } from "@playwright/test";

test.describe("views and dashboards editors", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("structured view editor has no JSON textarea and saves", async ({ page }) => {
    const suffix = `${Date.now().toString(36)}`;
    const title = `E2E Structured View ${suffix}`;

    await page.goto("/app/views/list");
    await expect(page.getByRole("heading", { name: "View editor" })).toBeVisible();
    await expect(page.locator("textarea")).toHaveCount(0);

    await page.getByRole("button", { name: "New view" }).click();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Description").fill("E2E structured editor");
    await page.getByLabel("Row limit").fill("15");
    await page.getByLabel("Chart type").selectOption("bar");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status")).toContainText("saved", { timeout: 15_000 });
    await expect(page.getByRole("button", { name: title })).toBeVisible();

    await page.reload();
    await page.getByRole("button", { name: title }).click();
    await expect(page.getByLabel("Title")).toHaveValue(title);
    await expect(page.getByLabel("Row limit")).toHaveValue("15");
  });

  test("dashboard grid editor saves widgets", async ({ page }) => {
    const suffix = `${Date.now().toString(36)}`;
    const viewTitle = `E2E Dash View ${suffix}`;
    const dashTitle = `E2E Dashboard ${suffix}`;

    await page.goto("/app/views/list");
    await page.getByRole("button", { name: "New view" }).click();
    await page.getByLabel("Title").fill(viewTitle);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status")).toContainText("saved", { timeout: 15_000 });

    await page.goto("/app/views/dashboards");
    await expect(page.getByRole("heading", { name: "Layout canvas" })).toBeVisible();
    await expect(page.locator("textarea")).toHaveCount(0);

    await page.getByRole("button", { name: "New dashboard" }).click();
    await page.getByLabel("Title").fill(dashTitle);
    await page.getByRole("button", { name: "Save dashboard" }).click();
    await expect(page.getByRole("status")).toContainText("saved", { timeout: 15_000 });

    const dragSource = page.getByRole("button", { name: viewTitle });
    const dropCell = page.locator(".g-portal-dashboard-editor__cell").first();
    await dragSource.dragTo(dropCell);

    await page.getByRole("button", { name: "Save dashboard" }).click();
    await expect(page.getByRole("status")).toContainText("saved", { timeout: 15_000 });

    await page.reload();
    await page.getByRole("button", { name: new RegExp(dashTitle) }).click();
    await expect(page.getByLabel("Widget title")).toHaveCount(1);
  });
});
