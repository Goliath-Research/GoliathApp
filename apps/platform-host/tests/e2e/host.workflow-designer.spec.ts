import { expect, test } from "@playwright/test";

test.describe("workflow designer (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("Add workflow creates an inactive v1.0 and opens the designer", async ({ page }) => {
    const name = `e2e-designer-${Date.now().toString(36)}`;
    await page.goto("/app/workflows/definitions");
    const grid = page.getByTestId("record-grid-workflow_definitions");
    await expect(grid).toBeVisible();
    await page.getByRole("button", { name: "Add workflow" }).click();
    const dialog = page.getByTestId("record-dialog-workflow_new");
    await expect(dialog).toBeVisible();
    await dialog.getByTestId("pi-row-name").locator("input").fill(name);
    await dialog.getByRole("button", { name: "Create workflow" }).click();
    const designer = page.getByTestId("record-dialog-workflow_definitions");
    await expect(designer).toBeVisible({ timeout: 15_000 });
    await expect(designer.getByRole("toolbar", { name: "workflow designer" })).toBeVisible();
    await expect(designer.getByTestId("graph-node-root")).toBeVisible();
    await expect(designer.locator("textarea")).toHaveCount(0);

    // Add a non-action node under the root from the toolbar; the canvas shows it.
    await designer.getByTestId("graph-node-root").click();
    await designer.getByLabel("New node type").selectOption("SEQUENCE");
    await designer.getByRole("button", { name: "Add node under root" }).click();
    await expect(designer.getByTestId("graph-node-sequence_1")).toBeVisible();
  });

  test("graph saves enforce the action key", async ({ page }) => {
    await page.goto("/app");
    const name = `e2e-akey-${Date.now().toString(36)}`;
    const created = await page.request.post("/api/portal/records/workflow_version", {
      data: { document: { name } },
    });
    expect(created.status(), await created.text()).toBe(200);
    const { key } = (await created.json()) as { key: string };
    const res = await page.request.post("/api/portal/records/workflow_version", {
      data: {
        key,
        document: {
          nodes: [
            { node_key: "root", node_type: "SEQUENCE" },
            { node_key: "step", node_type: "ACTION" },
          ],
        },
      },
    });
    expect(res.status()).toBe(400);
    expect(await res.text()).toContain("needs an action");
  });

  test("action parameters endpoint validates input", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.get("/api/portal/workflows/action-parameters");
    expect(res.status()).toBe(400);
  });
});
