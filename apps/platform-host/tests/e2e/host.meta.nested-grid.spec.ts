import { expect, test } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

test.describe("hierarchy-driven nested SchemaPropertyGrid (CI postgres)", () => {
  test.skip(() => process.env.PLAYWRIGHT_AUTH_E2E !== "1", "requires PG seed");

  test("data-type object field opens nested grid dialog", async ({ page }) => {
    await page.goto("/app/nested-e2e");
    await expect(page.getByRole("heading", { name: "e2e/NestedCarrier" })).toBeVisible();
    await page.getByLabel(/Caption/).fill("NestedCaption");
    await page.getByLabel(/Seq/).fill("3");
    await page.getByRole("button", { name: /Edit nested.*Payload/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel(/^label$/i).fill("inner");
    await page.getByLabel(/^qty$/i).fill("9");
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("meta class field loads inherited ParentLabel in nested grid", async ({ page }) => {
    await page.goto("/app/nested-e2e");
    await page.getByRole("button", { name: /Edit nested.*ChildDoc/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByLabel(/ParentLabel/)).toBeVisible();
    await page.getByLabel(/ChildCode/).fill("c1");
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  });

  test("array of class-typed items supports add row dialog", async ({ page }) => {
    await page.goto("/app/nested-e2e");
    await page
      .locator(".g-meta-field-row--array", { hasText: "ChildRows" })
      .getByRole("button", { name: "Add row" })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByLabel(/ChildCode/).fill("row-a");
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  });

  test("child class nested dialog shows ancestry icon hook", async ({ page }, testInfo) => {
    await page.goto("/app/nested-e2e");
    await page.getByRole("button", { name: /Edit nested.*ChildDoc/i }).click();
    await expect(page.getByTestId("nested-grid-icon")).toContainText("platform:layout-grid");
    const dir = process.env.PLAYWRIGHT_SCREENSHOT_DIR;
    const shot = dir
      ? `${dir}/meta-nested-hierarchy-dialog.png`
      : testInfo.outputPath("meta-nested-hierarchy-dialog.png");
    await page.screenshot({ path: shot, fullPage: true });
  });

  test("nested dialog save round-trips via BFF", async ({ page, request }) => {
    await page.goto("/app/nested-e2e");
    await page.getByLabel(/Caption/).fill("NestedCaption");
    await page.getByLabel(/Seq/).fill("3");
    await page.getByRole("button", { name: /Edit nested.*Payload/i }).click();
    await page.getByLabel(/^label$/i).fill("inner");
    await page.getByLabel(/^qty$/i).fill("9");
    await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: /Create via BFF/ }).click();
    await expect(page.getByRole("status")).toContainText("Created object #", { timeout: 30_000 });

    const createRes = await request.post("/api/meta/classes/e2e%2FNestedCarrier/objects", {
      data: {
        document: {
          Caption: "ApiNested",
          Seq: 4,
          Payload: { label: "from-api", qty: 2 },
        },
      },
    });
    expect(createRes.status()).toBe(201);
    const { objId } = (await createRes.json()) as { objId: number };
    const getRes = await request.get(`/api/meta/objects/${objId}`);
    const row = (await getRes.json()) as { object: { document: Record<string, unknown> } };
    const payload = row.object.document.Payload as Record<string, unknown>;
    expect(payload.label).toBe("from-api");
  });
});
