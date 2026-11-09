import { expect, test, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3400";

function loadCiEnv(): void {
  const envPath = path.join(__dirname, "..", "..", ".e2e", "ci.env");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq);
    const value = trimmed.slice(eq + 1);
    if (!(key in process.env)) process.env[key] = value;
  }
}

async function isolatedSession(
  userId: string,
  scopeId: string,
): Promise<APIRequestContext> {
  const secret = process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET!;
  const ctx = await playwrightRequest.newContext({ baseURL });
  const res = await ctx.post("/api/session/dev-establish", {
    headers: {
      "x-goliath-dev-login-secret": secret,
      "x-goliath-dev-login-scope-id": scopeId,
      "x-goliath-dev-login-user-id": userId,
    },
  });
  expect(res.ok()).toBeTruthy();
  return ctx;
}

test.beforeAll(() => {
  loadCiEnv();
});

test.describe("authenticated meta (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("meta explorer renders icons and child editor slot", async ({ page }, testInfo) => {
    await page.goto("/app/meta?class=portal%2FNavNode");
    await expect(page.getByRole("heading", { name: "Inherited Meta class browser" })).toBeVisible();
    await expect(page.getByRole("img").first()).toBeVisible();
    await expect(page.getByRole("status")).toContainText("Child editor slot");

    const dir = process.env.PLAYWRIGHT_SCREENSHOT_DIR;
    const shot = dir
      ? `${dir}/meta-authenticated-explorer.png`
      : testInfo.outputPath("meta-authenticated-explorer.png");
    await page.screenshot({ path: shot, fullPage: true });
  });

  async function fillRequiredSchemaGridFields(
    page: import("@playwright/test").Page,
    request: import("@playwright/test").APIRequestContext,
  ) {
    const fieldsRes = await request.get("/api/meta/classes/portal%2FNavNode/fields");
    expect(fieldsRes.ok()).toBeTruthy();
    const { fields } = (await fieldsRes.json()) as {
      fields: Array<{
        fieldName: string;
        required: boolean;
        typeKind: string | null;
        typeName: string | null;
      }>;
    };
    for (const field of fields.filter((f) => f.required)) {
      const row = page.locator(".g-schema-property-grid .g-meta-field-row", {
        has: page.locator("label", { hasText: new RegExp(`^${field.fieldName}\\s*\\*$`) }),
      });
      const checkbox = row.locator('input[type="checkbox"]');
      if ((await checkbox.count()) > 0) {
        await checkbox.check();
        continue;
      }
      const select = row.locator("select");
      if ((await select.count()) > 0) {
        await select.selectOption({ index: 1 });
        continue;
      }
      const textarea = row.locator("textarea");
      if ((await textarea.count()) > 0) {
        await textarea.fill("[]");
        continue;
      }
      const input = row.locator("input").first();
      const kind = field.typeKind?.toLowerCase() ?? "";
      const typeName = field.typeName?.toLowerCase() ?? "";
      if (field.fieldName === "Caption") {
        await input.fill("E2ECaption");
      } else if (kind === "int" || typeName.includes("int") || field.fieldName === "Seq") {
        await input.fill("17");
      } else if (kind === "number" || typeName.includes("number") || typeName.includes("decimal")) {
        await input.fill("1.5");
      } else {
        await input.fill("e2e");
      }
    }
  }

  test("SchemaPropertyGrid renders required NavNode fields", async ({ page, request }) => {
    await page.goto("/app/meta?class=portal%2FNavNode");
    await expect(page.locator(".g-schema-property-grid")).toBeVisible();
    const fieldsRes = await request.get("/api/meta/classes/portal%2FNavNode/fields");
    const { fields } = (await fieldsRes.json()) as {
      fields: Array<{ fieldName: string; required: boolean }>;
    };
    const requiredNames = fields.filter((f) => f.required).map((f) => f.fieldName);
    expect(requiredNames.length).toBeGreaterThan(0);
    const grid = page.locator(".g-schema-property-grid");
    for (const name of requiredNames) {
      await expect(grid.getByRole("textbox", { name: new RegExp(`^${name}`) }).or(
        grid.getByRole("spinbutton", { name: new RegExp(`^${name}`) }),
      )).toBeVisible();
    }
    await fillRequiredSchemaGridFields(page, request);
    await expect(page.getByRole("button", { name: /Create via BFF/ })).toBeEnabled();
  });

  test("authenticated BFF create get patch round-trip", async ({ request }) => {
    const createRes = await request.post("/api/meta/classes/portal%2FNavNode/objects", {
      data: { document: { Caption: "ApiCaption", Seq: 18 } },
    });
    expect(createRes.status()).toBe(201);
    const body = (await createRes.json()) as { objId: number };
    const getRes = await request.get(`/api/meta/objects/${body.objId}`);
    expect(getRes.ok()).toBeTruthy();
    const row = (await getRes.json()) as { object: { document: Record<string, unknown> } };
    expect(row.object.document.Caption).toBe("ApiCaption");

    const patchRes = await request.patch(`/api/meta/objects/${body.objId}`, {
      data: { document: { Caption: "ApiCaptionPatched", Seq: 19 } },
    });
    expect(patchRes.ok()).toBeTruthy();
    const after = await request.get(`/api/meta/objects/${body.objId}`);
    const afterDoc = (await after.json()) as { object: { document: Record<string, unknown> } };
    expect(afterDoc.object.document.Seq).toBe(19);
  });

  test("invalid document rejected with 400", async ({ request }) => {
    const res = await request.post("/api/meta/classes/portal%2FNavNode/objects", {
      data: { document: { NotAField: 1 } },
    });
    expect(res.status()).toBe(400);
  });

  test("cross-scope and missing ids share indistinguishable 404", async ({ request }) => {
    const scopeB = process.env.GOLIATH_E2E_SCOPE_B_ID!;
    const userId = process.env.GOLIATH_P1_DEV_LOGIN_USER_ID!;

    const createRes = await request.post("/api/meta/classes/portal%2FNavNode/objects", {
      data: { document: { Caption: "ScopeA", Seq: 20 } },
    });
    expect(createRes.status()).toBe(201);
    const { objId } = (await createRes.json()) as { objId: number };

    const scopeBCtx = await isolatedSession(userId, scopeB);

    const cross = await scopeBCtx.get(`/api/meta/objects/${objId}`);
    const missing = await scopeBCtx.get("/api/meta/objects/999999991");
    expect(cross.status()).toBe(404);
    expect(missing.status()).toBe(404);
    const crossBody = (await cross.json()) as { error: string };
    const missingBody = (await missing.json()) as { error: string };
    expect(crossBody.error).toBe(missingBody.error);
    expect(crossBody.error).toBe("meta object not found");
    await scopeBCtx.dispose();
  });

  test("dev-establish rejects non-allowlisted user id with secret", async ({ request }) => {
    const secret = process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET!;
    const res = await request.post("/api/session/dev-establish", {
      headers: {
        "x-goliath-dev-login-secret": secret,
        "x-goliath-dev-login-user-id": "999999998",
      },
    });
    expect(res.status()).toBe(403);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("dev login denied");
  });

  test("user without meta grants gets stable 403 on write", async () => {
    const deniedUser = process.env.GOLIATH_E2E_DENIED_USER_ID!;
    const scopeB = process.env.GOLIATH_E2E_SCOPE_B_ID!;
    const deniedCtx = await isolatedSession(deniedUser, scopeB);
    const res = await deniedCtx.post("/api/meta/classes/portal%2FNavNode/objects", {
      data: { document: { Caption: "X", Seq: 1 } },
    });
    expect(res.status()).toBe(403);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("meta permission denied");
    await deniedCtx.dispose();
  });
});
