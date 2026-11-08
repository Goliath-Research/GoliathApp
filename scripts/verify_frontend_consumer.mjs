#!/usr/bin/env node
/**
 * Child-repo simulation: install built tarballs (no workspace: protocol).
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const packages = ["ui", "client", "platform-ui"];

function run(cmd, args, cwd = repoRoot) {
  execFileSync(cmd, args, { cwd, stdio: "inherit" });
}

const workDir = mkdtempSync(join(tmpdir(), "goliath-consumer-"));
try {
  const consumerDir = join(workDir, "consumer");
  mkdirSync(consumerDir, { recursive: true });
  run("npm", ["init", "-y"], consumerDir);

  const tarballs = packages.map((name) => {
    const dir = join(repoRoot, "packages", name);
    const line = execFileSync("npm", ["pack", "--json"], { cwd: dir, encoding: "utf8" });
    const file = JSON.parse(line)[0].filename;
    return join(dir, file);
  });

  run(
    "npm",
    ["install", ...tarballs, "react@19.3.0", "react-dom@19.3.0", "lucide-react@^0.470.0"],
    consumerDir,
  );

  writeFileSync(
    join(consumerDir, "smoke.mjs"),
    `import { resolvePresentation } from "@goliath/ui";
import { diagnoseUiManifest } from "@goliath/client";
import { PlatformFixtureDemo } from "@goliath/platform-ui/fixture";
const p = resolvePresentation({ kind: "workflow_run" });
if (!p.iconKey || !p.label) throw new Error("missing presentation");
const report = diagnoseUiManifest({ appId: "smoke", classIconOverrides: { "x/Y": "bad" } });
if (report.invalid.length === 0) throw new Error("expected invalid override");
if (typeof PlatformFixtureDemo !== "function") throw new Error("missing fixture demo");
console.log("consumer smoke ok", p.iconKey);
`,
  );

  run("node", ["smoke.mjs"], consumerDir);
} finally {
  rmSync(workDir, { recursive: true, force: true });
}
