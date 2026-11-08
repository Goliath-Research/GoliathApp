import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3400",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command:
          "sh -c 'cd .next/standalone && PORT=3400 HOSTNAME=127.0.0.1 node apps/platform-host/server.js'",
        url: "http://127.0.0.1:3400/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
});
