import { expect, test } from "@playwright/test";

test.describe("platform host", () => {
  test("auth provider discovery is public metadata only", async ({ request }) => {
    const res = await request.get("/api/auth/providers");
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { providers: unknown[]; supportedMethods: Record<string, unknown> };
    expect(Array.isArray(body.providers)).toBeTruthy();
    expect(body.supportedMethods.oidc_authorization_code).toBeTruthy();
  });

  test("dev-establish is not a production login surface", async ({ request }) => {
    const res = await request.post("/api/session/dev-establish");
    if (process.env.PLAYWRIGHT_AUTH_E2E === "1") {
      expect(res.status()).toBe(403);
    } else {
      expect(res.status()).toBe(404);
    }
  });

  test("meta class API fails closed without a session", async ({ request }) => {
    const res = await request.get("/api/meta/classes/portal%2FNavNode");
    expect([401, 503]).toContain(res.status());
  });

  test("meta object API fails closed without a session", async ({ request }) => {
    const getRes = await request.get("/api/meta/objects/1");
    expect([401, 503]).toContain(getRes.status());
    const postRes = await request.post("/api/meta/classes/portal%2FNavNode/objects", {
      data: { document: { Caption: "x", Seq: 1 } },
    });
    expect([401, 503]).toContain(postRes.status());
  });

  test("protected navigation API fails closed without a session", async ({ request }) => {
    const res = await request.get("/api/navigation");
    expect([401, 503]).toContain(res.status());
    const body = (await res.json()) as { error: string };
    expect(body.error.length).toBeGreaterThan(0);
  });

  test("session me fails closed without a session cookie", async ({ request }) => {
    const res = await request.get("/api/session/me");
    expect([401, 503]).toContain(res.status());
  });

  test("health endpoint returns build metadata", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { status: string; service: string; packages: string[] };
    expect(body.status).toBe("ok");
    expect(body.service).toBe("goliath-platform-host");
    expect(body.packages).toContain("@goliath/ui");
  });

  test("home and fixture routes render icons with accessible labels", async ({ page }, testInfo) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Platform UI foundation (P0)" })).toBeVisible();
    await expect(page.getByRole("img").first()).toBeVisible();

    await page.goto("/fixture");
    await expect(page.getByText("[Fixture data only]")).toBeVisible();
    await expect(page.getByText("Platform presentation fixture (P0)")).toBeVisible();
    const images = page.getByRole("img");
    await expect(images.first()).toBeVisible();
    expect(await images.count()).toBeGreaterThan(10);

    const artifactDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR;
    const lightPath = artifactDir
      ? `${artifactDir}/platform-host-fixture-light.png`
      : testInfo.outputPath("platform-host-fixture-light.png");
    const darkPath = artifactDir
      ? `${artifactDir}/platform-host-fixture-dark.png`
      : testInfo.outputPath("platform-host-fixture-dark.png");

    await page.emulateMedia({ colorScheme: "light" });
    await page.screenshot({ path: lightPath, fullPage: true });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({ path: darkPath, fullPage: true });
  });

  test("workflow runs API requires a session", async ({ request }) => {
    const res = await request.get("/api/portal/workflows/runs?range=all");
    expect([401, 503]).toContain(res.status());
  });

  test("reference search API requires a session", async ({ request }) => {
    const res = await request.get("/api/portal/references?kind=action");
    expect([401, 503]).toContain(res.status());
  });

  test("record editor APIs require a session", async ({ request }) => {
    for (const entity of [
      "class_method",
      "domain_program",
      "cluster",
      "worker_enrollment",
      "event_subscription",
      "workflow_version",
      "workflow_run",
    ]) {
      const list = await request.get(`/api/portal/records/${entity}`);
      expect([401, 503]).toContain(list.status());
    }
    const save = await request.post("/api/portal/records/cluster", { data: { document: { cluster_key: "x" } } });
    expect([401, 503]).toContain(save.status());
  });
});
