import { test as setup, expect } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const authFile = path.join(__dirname, ".auth", "primary.json");

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

setup("authenticate primary scoped session", async ({ request }) => {
  if (process.env.PLAYWRIGHT_AUTH_E2E !== "1") {
    setup.skip();
  }
  loadCiEnv();
  if (process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN !== "1") {
    throw new Error("PLAYWRIGHT_AUTH_E2E requires GOLIATH_PLATFORM_HOST_DEV_LOGIN=1");
  }
  const secret = process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET;
  const scopeId = process.env.GOLIATH_E2E_SCOPE_ID;
  if (!secret || !scopeId) {
    throw new Error("missing ci.env — run platform_host_e2e_pg_seed.py");
  }
  const res = await request.post("/api/session/dev-establish", {
    headers: {
      "x-goliath-dev-login-secret": secret,
      "x-goliath-dev-login-scope-id": scopeId,
    },
  });
  expect(res.ok()).toBeTruthy();
  await fs.promises.mkdir(path.dirname(authFile), { recursive: true });
  await request.storageState({ path: authFile });
});
