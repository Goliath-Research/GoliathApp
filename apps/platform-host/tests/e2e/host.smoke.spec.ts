import { expect, test } from "@playwright/test";

test.describe("platform host", () => {
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
});
