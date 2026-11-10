import { expect, test } from "@playwright/test";

test.describe("operator portal", () => {
  test("unauthenticated /app redirects to login", async ({ page }) => {
    await page.goto("/app");
    await expect(page).toHaveURL(/\/(login|\?auth=)/);
  });

  test("navigation API requires session", async ({ request }) => {
    const res = await request.get("/api/navigation");
    expect([401, 503]).toContain(res.status());
  });
});
