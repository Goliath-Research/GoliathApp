import { expect, test } from "@playwright/test";

test.describe("hierarchy-driven nested SchemaPropertyGrid (CI postgres)", () => {
  test.skip(() => process.env.PLAYWRIGHT_AUTH_E2E !== "1", "requires PG seed");

  test("carrier exposes data-type, meta-class, and array fields", async ({ request }) => {
    const fieldsRes = await request.get("/api/meta/classes/e2e%2FNestedCarrier/fields");
    expect(fieldsRes.ok()).toBeTruthy();
    const { fields } = (await fieldsRes.json()) as { fields: Array<{ fieldName: string; typeName: string | null }> };
    const names = new Map(fields.map((f) => [f.fieldName, f.typeName]));
    expect(names.get("Payload")).toBe("e2e/NestedPayload");
    expect(names.get("ChildDoc")).toBe("meta/class/e2e/NestedChild");
    expect(names.get("ChildRows")).toBe("e2e/NestedChildRows");
  });

  test("child class resolves inherited ParentLabel field", async ({ request }) => {
    const fieldsRes = await request.get("/api/meta/classes/e2e%2FNestedChild/fields");
    expect(fieldsRes.ok()).toBeTruthy();
    const { fields } = (await fieldsRes.json()) as { fields: Array<{ fieldName: string; declaredOnClassName: string }> };
    const parentLabel = fields.find((f) => f.fieldName === "ParentLabel");
    expect(parentLabel).toBeTruthy();
    expect(parentLabel?.declaredOnClassName).toBe("e2e/NestedParent");
  });

  test("wf.data_type BFF returns nested payload schema", async ({ request }) => {
    const typeRes = await request.get("/api/meta/types/e2e%2FNestedPayload");
    expect(typeRes.ok()).toBeTruthy();
    const { type } = (await typeRes.json()) as { type: { kind: string; schemaJson: Record<string, unknown> } };
    expect(type.kind).toBe("object");
    const props = type.schemaJson.properties as Record<string, unknown>;
    expect(props.label).toBeTruthy();
    expect(props.qty).toBeTruthy();
  });

  test("nested carrier create/get round-trips payload", async ({ request }) => {
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

  test("nested-e2e page renders carrier workbench", async ({ page }, testInfo) => {
    await page.goto("/app/nested-e2e");
    await expect(page.getByRole("heading", { name: "e2e/NestedCarrier" })).toBeVisible();
    await expect(page.locator('[data-has-catalog-resolver="true"]')).toBeVisible();
    await expect(page.getByTestId("pi-open-Payload")).toBeVisible();
    const dir = process.env.PLAYWRIGHT_SCREENSHOT_DIR;
    const shot = dir
      ? `${dir}/meta-nested-hierarchy-grid.png`
      : testInfo.outputPath("meta-nested-hierarchy-grid.png");
    await page.screenshot({ path: shot, fullPage: true });
  });

  test("property inspector opens two nested modals and saves via BFF", async ({ page, request }) => {
    await page.goto("/app/nested-e2e");
    await page.getByTestId("pi-row-Caption").locator("input").fill("ModalE2E");
    await page.getByTestId("pi-row-Seq").locator("input").fill("9");

    await page.getByTestId("pi-open-ChildDoc").click();
    const modal1 = page.getByTestId("property-inspector-modal");
    await expect(modal1).toBeVisible();
    await modal1.getByTestId("pi-row-ChildCode").locator("input").fill("child-1");
    await modal1.getByTestId("pi-open-DetailPayload").click();
    const modal2 = page.getByTestId("property-inspector-modal").last();
    await expect(modal2).toBeVisible();
    await modal2.getByTestId("pi-row-label").locator("input").fill("deep-label");
    await modal2.getByTestId("pi-row-qty").locator("input").fill("3");
    await modal2.getByTestId("property-inspector-ok").click();
    await expect(page.getByTestId("property-inspector-modal")).toHaveCount(1);
    await modal1.getByTestId("property-inspector-ok").click();
    await expect(page.getByTestId("property-inspector-modal")).toHaveCount(0);

    await page.getByRole("button", { name: /Create via BFF/ }).click();
    await expect(page.getByText(/Created object #/)).toBeVisible({ timeout: 30_000 });
    const statusText = await page.locator(".g-host-app").textContent();
    const match = statusText?.match(/Created object #(\d+)/);
    expect(match).toBeTruthy();
    const objId = Number(match![1]);
    const getRes = await request.get(`/api/meta/objects/${objId}`);
    expect(getRes.ok()).toBeTruthy();
    const row = (await getRes.json()) as { object: { document: Record<string, unknown> } };
    const doc = row.object.document;
    expect(doc.Caption).toBe("ModalE2E");
    const childDoc = doc.ChildDoc as Record<string, unknown>;
    expect(childDoc.ChildCode).toBe("child-1");
    expect((childDoc.DetailPayload as Record<string, unknown>).label).toBe("deep-label");
  });
});
