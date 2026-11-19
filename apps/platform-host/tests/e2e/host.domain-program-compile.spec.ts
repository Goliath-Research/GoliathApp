import { expect, test } from "@playwright/test";

test.describe("domain program steps and compile (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("programs and their draft steps are record grids", async ({ page }) => {
    await page.goto("/app/workflows/domain-programs");
    await expect(page.getByTestId("record-grid-domain_program")).toBeVisible();
    await expect(page.getByTestId("record-grid-domain_program_step")).toBeVisible();
    await expect(page.getByTestId("record-grid-domain_program_step-add")).toHaveCount(0);
    await expect(page.locator("textarea")).toHaveCount(0);
  });

  test("compile and publish refuses programs that are not drafts", async ({ page }) => {
    await page.goto("/app");
    const name = `e2e-compile-${Date.now().toString(36)}`;
    const saved = await page.request.post("/api/portal/records/domain_program", {
      data: { document: { name, version: "1", project_path: "/e2e" } },
    });
    expect(saved.status(), await saved.text()).toBe(200);
    const published = await page.request.post("/api/portal/records/domain_program/action", {
      data: { action: "publish", key: `${name}@1` },
    });
    expect(published.status(), await published.text()).toBe(200);
    const res = await page.request.post("/api/portal/records/domain_program/action", {
      data: { action: "compile_publish", key: `${name}@1` },
    });
    expect(res.status()).toBe(409);
    expect(await res.text()).toContain("only drafts");
  });
});
