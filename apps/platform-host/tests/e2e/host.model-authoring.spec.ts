import { expect, test } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3400";

test.describe("model authoring (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("semantic layer workspace loads authoring chrome", async ({ page }) => {
    await page.goto("/app/semantic");
    await expect(page.getByRole("heading", { name: "Semantic layer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Register entity" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export as package SQL" })).toBeVisible();
  });

  test("meta home shows model authoring panel", async ({ page }) => {
    await page.goto("/app/meta/classes");
    await expect(page.getByRole("heading", { name: "Model authoring" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Create class" })).toBeVisible();
  });

  test("subclass, field, object, semantic entity, and saved meta view", async ({ page, request }) => {
    const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const className = `e2e/E2eModel_${suffix}`;
    const objectLabel = `E2E Person ${suffix}`;
    const nickValue = `Nick_${suffix}`;
    const viewTitle = `E2E View ${suffix}`;
    const entityCode = `e2e_party_${suffix}`;
    const namespace = "e2e";
    const encodedClass = encodeURIComponent(className);

    await page.goto("/app/meta/classes");
    const createForm = page.locator("form").filter({
      has: page.getByRole("heading", { name: "Create subclass" }),
    });
    await createForm.getByLabel("Parent class").selectOption("platform/Person");
    await createForm.getByLabel("New class FQN").fill(className);
    await createForm.getByRole("button", { name: "Create class" }).click();
    await page.waitForLoadState("load");
    await expect(page.getByRole("link", { name: className })).toBeVisible();

    const fieldForm = page.locator("form").filter({
      has: page.getByRole("heading", { name: "Add or update field" }),
    });
    await fieldForm.getByLabel("Class").fill(className);
    await fieldForm.getByLabel("Field name").fill("Nickname");
    await fieldForm.getByRole("button", { name: "Save field" }).click();
    await expect(page.getByRole("status")).toContainText("Nickname saved");

    const createRes = await request.post(`/api/meta/classes/${encodedClass}/objects`, {
      data: { document: { Label: objectLabel, Nickname: nickValue } },
    });
    expect(createRes.status()).toBe(201);
    const { objId } = (await createRes.json()) as { objId: number };

    const getRes = await request.get(`/api/meta/objects/${objId}`);
    expect(getRes.ok()).toBeTruthy();
    const row = (await getRes.json()) as { object: { document: Record<string, unknown> } };
    expect(row.object.document.Label).toBe(objectLabel);
    expect(row.object.document.Nickname).toBe(nickValue);

    await page.goto(`/app/meta?class=${encodedClass}`);
    await expect(page.locator(".g-meta-explorer")).toBeVisible();
    await expect(page.getByTestId("pi-row-Label")).toBeVisible();
    await expect(page.getByTestId("pi-row-Nickname")).toBeVisible();

    await page.goto("/app/semantic");
    const entitySection = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Register entity" }),
    });
    const entityForm = entitySection.locator("form.g-portal-form");
    await entityForm.getByLabel("Namespace").fill(namespace);
    await entityForm.getByLabel("Entity code").fill(entityCode);
    await entityForm.getByLabel("Display name").fill(`E2E entity ${suffix}`);
    await entityForm.getByLabel("Meta class").selectOption(className);
    await entityForm.getByRole("button", { name: "Save entity" }).click();
    await page.waitForLoadState("load");
    await expect(page.getByRole("cell", { name: className })).toBeVisible();
    await expect(page.getByRole("cell", { name: entityCode })).toBeVisible();

    await page.goto("/app/views/list");
    await page.getByRole("button", { name: "New view" }).click();
    await page.getByLabel("Title").fill(viewTitle);
    await page.getByRole("radio", { name: /Meta class/ }).check();
    await page.getByRole("button", { name: new RegExp(`Use ${className}`) }).click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("View saved")).toBeVisible();
    const savedView = page.getByRole("button", { name: viewTitle });
    await expect(savedView).toBeVisible();
    await expect(page.getByLabel("Selected Meta class")).toHaveValue(className);
  });
});
