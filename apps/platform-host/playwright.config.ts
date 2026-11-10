import { defineConfig, devices } from "@playwright/test";

const authFile = "tests/e2e/.auth/primary.json";
const authE2e = process.env.PLAYWRIGHT_AUTH_E2E === "1";

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
  projects: [
    ...(authE2e
      ? [
          { name: "setup", testMatch: /auth\.setup\.ts/ },
          {
            name: "chromium-auth",
            testMatch:
              /host\.meta\.(authenticated|nested-grid)\.spec\.ts|host\.model-authoring\.spec\.ts|host\.layered-security\.spec\.ts|host\.admin-invite\.spec\.ts/,
            dependencies: ["setup"],
            use: { ...devices["Desktop Chrome"], storageState: authFile },
          },
        ]
      : []),
    {
      name: "chromium-unauth",
      testMatch: /host\.smoke\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: "sh -c 'PORT=3400 HOSTNAME=127.0.0.1 npm run start'",
        url: "http://127.0.0.1:3400/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        ...(authE2e
          ? { env: { GOLIATH_PLATFORM_HOST_E2E_INTEGRATION: "1" } as Record<string, string> }
          : {}),
      },
});
