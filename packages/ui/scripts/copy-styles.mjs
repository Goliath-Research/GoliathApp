import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "src", "styles.css");
const outDir = join(root, "dist");
mkdirSync(outDir, { recursive: true });
copyFileSync(src, join(outDir, "styles.css"));
