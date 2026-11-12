import { expect, test } from "@playwright/test";

const KINDS = [
  "action",
  "meta_method",
  "workflow_def",
  "workflow_version",
  "event_type",
  "cluster",
  "worker",
  "data_type",
  "meta_class",
  "study",
];

test.describe("reference picker search API", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  for (const kind of KINDS) {
    test(`searches existing ${kind} rows`, async ({ page }) => {
      await page.goto("/app");
      const res = await page.request.get(`/api/portal/references?kind=${kind}&q=&limit=5`);
      expect(res.status()).toBe(200);
      const body = (await res.json()) as { kind: string; rows: { value: string; label: string }[] };
      expect(body.kind).toBe(kind);
      expect(Array.isArray(body.rows)).toBe(true);
      expect(body.rows.length).toBeLessThanOrEqual(5);
    });
  }

  test("data types are searchable by name", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.get("/api/portal/references?kind=data_type&q=e2e%2FNested&limit=20");
    expect(res.status()).toBe(200);
    const body = (await res.json()) as { rows: { label: string }[] };
    expect(body.rows.some((r) => r.label.startsWith("e2e/NestedPayload@"))).toBe(true);
  });

  test("unknown kinds are rejected", async ({ page }) => {
    await page.goto("/app");
    const res = await page.request.get("/api/portal/references?kind=nope");
    expect(res.status()).toBe(400);
  });
});
