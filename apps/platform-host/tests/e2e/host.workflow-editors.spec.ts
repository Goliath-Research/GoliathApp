import { expect, test } from "@playwright/test";

test.describe("workflow graph editor and run inspector", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("lists workflow versions and runs", async ({ page }) => {
    await page.goto("/app");
    for (const entity of ["workflow_version", "workflow_run"]) {
      const res = await page.request.get(`/api/portal/records/${entity}`);
      expect(res.status()).toBe(200);
      expect(Array.isArray(((await res.json()) as { rows: unknown[] }).rows)).toBe(true);
    }
  });

  test("workflow runs are not edited directly", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.post("/api/portal/records/workflow_run", {
      data: { key: "1", document: {} },
    });
    expect(res.status()).toBe(400);
  });

  test("unknown run actions are rejected", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.post("/api/portal/records/workflow_run/action", {
      data: { action: "delete", key: "1" },
    });
    expect(res.status()).toBe(400);
  });

  test("definitions and steps pages render the graph editor", async ({ page }) => {
    await page.goto("/app/workflows/definitions");
    await expect(page.getByTestId("workflow-graph-definitions")).toBeVisible();
    await page.goto("/app/workflows/steps");
    await expect(page.getByTestId("workflow-graph-steps")).toBeVisible();
  });

  test("runs page shows the run inspector", async ({ page }) => {
    await page.goto("/app/workflows/runs");
    await expect(page.getByTestId("run-inspector")).toBeVisible();
    await expect(page.getByLabel("Run to inspect")).toBeVisible();
  });
});
