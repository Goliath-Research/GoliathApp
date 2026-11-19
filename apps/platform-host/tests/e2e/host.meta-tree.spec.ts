import { expect, test } from "@playwright/test";

test.describe("generic tree editor (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("NavNode is a tree-shaped class and its tree loads", async ({ page }) => {
    await page.goto("/app");
    const classes = await page.request.get("/api/portal/meta-tree");
    expect(classes.status()).toBe(200);
    const body = (await classes.json()) as { classes: Array<{ className: string }> };
    expect(body.classes.map((c) => c.className)).toContain("portal/NavNode");
    const tree = await page.request.get("/api/portal/meta-tree?class=portal%2FNavNode");
    expect(tree.status()).toBe(200);
    const rows = ((await tree.json()) as { rows: unknown[] }).rows;
    expect(rows.length).toBeGreaterThan(0);
  });

  test("trees page lists tree classes; navigation page renders the tree", async ({ page }) => {
    await page.goto("/app/meta/trees");
    await expect(page.getByRole("link", { name: "portal/NavNode" })).toBeVisible();
    await page.goto("/app/admin/navigation");
    await expect(page.getByTestId("meta-tree")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("tree").first()).toBeVisible();
  });

  test("move requests are validated", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.post("/api/portal/meta-tree", { data: { action: "move", className: "" } });
    expect(res.status()).toBe(400);
  });
});
