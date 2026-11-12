import { expect, test } from "@playwright/test";

const ENTITIES = ["class_method", "domain_program", "cluster", "worker_enrollment", "event_subscription"];

test.describe("workflows record editors", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  for (const entity of ENTITIES) {
    test(`lists ${entity} records`, async ({ page }) => {
      await page.goto("/app");
      const res = await page.request.get(`/api/portal/records/${entity}`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as { entity: string; rows: unknown[] };
      expect(body.entity).toBe(entity);
      expect(Array.isArray(body.rows)).toBe(true);
    });
  }

  test("unknown entities are 404", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.get("/api/portal/records/nope");
    expect(res.status()).toBe(404);
  });

  test("cluster create, edit and reload through the API", async ({ page }) => {
    await page.goto("/app");
    const key = `e2e-cluster-${Date.now()}`;
    const created = await page.request.post("/api/portal/records/cluster", {
      data: { document: { cluster_key: key, name: "E2E cluster", allowed_source_cidrs: ["10.0.0.0/8"] } },
    });
    expect(created.status()).toBe(200);
    expect(((await created.json()) as { key: string }).key).toBe(key);
    const updated = await page.request.post("/api/portal/records/cluster", {
      data: { key, document: { cluster_key: key, name: "E2E cluster renamed", status: "DISABLED" } },
    });
    expect(updated.status()).toBe(200);
    const item = await page.request.get(`/api/portal/records/cluster/item?key=${encodeURIComponent(key)}`);
    expect(item.status()).toBe(200);
    const doc = ((await item.json()) as { document: Record<string, unknown> }).document;
    expect(doc.name).toBe("E2E cluster renamed");
    expect(doc.status).toBe("DISABLED");
    expect(doc.allowed_source_cidrs).toEqual(["10.0.0.0/8"]);
  });

  test("invalid documents are rejected with 400", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.post("/api/portal/records/cluster", {
      data: { document: { cluster_key: `e2e-bad-${Date.now()}`, status: "RUNNING" } },
    });
    expect(res.status()).toBe(400);
  });

  test("actions page lists class methods grouped by class", async ({ page }) => {
    await page.goto("/app/workflows/actions");
    const editor = page.getByTestId("record-editor-class_method");
    await expect(editor).toBeVisible();
    await expect(editor.getByRole("heading", { name: "Actions (class methods)" })).toBeVisible();
    await expect(editor.getByRole("button", { name: "New method" })).toBeVisible();
  });

  test("workers page edits clusters in the property grid", async ({ page }) => {
    await page.goto("/app/workflows/workers");
    const editor = page.getByTestId("record-editor-cluster");
    await expect(editor).toBeVisible();
    await editor.getByTestId("record-editor-new-cluster").click();
    await expect(editor.getByRole("button", { name: "Create cluster" })).toBeVisible();
  });
});
