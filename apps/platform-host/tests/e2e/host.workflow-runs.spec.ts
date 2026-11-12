import { expect, test } from "@playwright/test";

test.describe("workflow runs time range", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("runs page offers 24h / 7d / 30d / all and defaults to 7 days", async ({ page }) => {
    await page.goto("/app/workflows/runs");
    const ranges = page.getByRole("navigation", { name: "Time range" });
    await expect(ranges).toBeVisible();
    for (const label of ["Last 24 hours", "Last 7 days", "Last 30 days", "All runs"]) {
      await expect(ranges.getByRole("link", { name: label })).toBeVisible();
    }
    await expect(ranges.getByRole("link", { name: "Last 7 days" })).toHaveAttribute("aria-current", "page");

    await ranges.getByRole("link", { name: "All runs" }).click();
    await expect(page).toHaveURL(/\/app\/workflows\/runs\?range=all$/);
    await expect(
      page.getByRole("navigation", { name: "Time range" }).getByRole("link", { name: "All runs" }),
    ).toHaveAttribute("aria-current", "page");
    await expect(page.getByText(/all runs\)\.$/)).toBeVisible();
  });

  test("runs API accepts range=all with a clamped limit", async ({ page }) => {
    await page.goto("/app/workflows/runs");
    const res = await page.request.get("/api/portal/workflows/runs?range=all&limit=100000");
    expect(res.status()).toBe(200);
    const body = (await res.json()) as { range: string; limit: number; rows: unknown[] };
    expect(body.range).toBe("all");
    expect(body.limit).toBe(500);
    expect(Array.isArray(body.rows)).toBe(true);
  });
});
