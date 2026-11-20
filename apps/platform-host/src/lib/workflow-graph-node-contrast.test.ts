import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const stylesCss = readFileSync(resolve(here, "../../../../packages/ui/src/styles.css"), "utf8");
const globalsCss = readFileSync(resolve(here, "../app/globals.css"), "utf8");

const AA = 4.5;

function srgbToLin(channel: number): number {
  const s = channel / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function relLum(hex: string): number {
  const raw = hex.trim().replace("#", "");
  const body = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw;
  const n = Number.parseInt(body, 16);
  return 0.2126 * srgbToLin((n >> 16) & 255) + 0.7152 * srgbToLin((n >> 8) & 255) + 0.0722 * srgbToLin(n & 255);
}

/** WCAG contrast ratio of two #rrggbb colors. */
function contrastRatio(fg: string, bg: string): number {
  const a = relLum(fg);
  const b = relLum(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

function blockTokens(block: string): Map<string, string> {
  const tokens = new Map<string, string>();
  const re = /(--g-[\w-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(block))) tokens.set(m[1], m[2].trim());
  return tokens;
}

function rootBlock(css: string): string {
  const start = css.indexOf(":root {");
  const media = css.indexOf("@media (prefers-color-scheme: dark)");
  if (start < 0 || media < 0) throw new Error("expected :root and dark media query");
  return css.slice(start, media);
}

function darkBlock(css: string): string {
  const media = css.indexOf("@media (prefers-color-scheme: dark)");
  if (media < 0) throw new Error("expected dark media query");
  const open = css.indexOf("{", media);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) return css.slice(media, i + 1);
    }
  }
  throw new Error("unclosed dark media query");
}

describe("workflow graph node caption contrast", () => {
  const root = blockTokens(rootBlock(stylesCss));
  const dark = blockTokens(darkBlock(stylesCss));
  const bg = root.get("--g-graph-node-bg");
  const pairs: [string, string][] = [
    ["--g-graph-node-fg", "caption / body text"],
    ["--g-graph-node-fg-muted", "type caption"],
    ["--g-graph-node-accent", "title / badge / start border"],
    ["--g-graph-node-error", "error type caption"],
  ];

  it("defines graph-node tokens on the light :root and does not flip them in dark", () => {
    expect(bg).toMatch(/^#[0-9a-fA-F]{6}$/);
    for (const [token] of pairs) {
      expect(root.get(token), token).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(dark.has(token), `${token} must not be reassigned in dark theme`).toBe(false);
    }
    expect(dark.has("--g-graph-node-bg")).toBe(false);
  });

  it.each(pairs)("%s (%s) meets WCAG AA on the node fill in both themes", (token, _role) => {
    const fg = root.get(token)!;
    const ratio = contrastRatio(fg, bg!);
    expect(ratio, `${token} ${fg} on ${bg} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(AA);
    // Dark theme reuses the same tokens; report the same ratio.
    expect(contrastRatio(fg, bg!)).toBeGreaterThanOrEqual(AA);
  });

  it("records known ratios for the report", () => {
    const expected: Record<string, number> = {
      "--g-graph-node-fg": 17.49,
      "--g-graph-node-fg-muted": 7.63,
      "--g-graph-node-accent": 5.47,
      "--g-graph-node-error": 7.33,
    };
    for (const [token, want] of Object.entries(expected)) {
      expect(contrastRatio(root.get(token)!, bg!), token).toBeCloseTo(want, 2);
    }
  });

  it("keeps selected nodes on the white fill with a ring, not an inverted fill", () => {
    expect(globalsCss).toMatch(/\.g-graph-canvas \.react-flow(?:\.dark)?/);
    expect(globalsCss).toMatch(/--xy-node-background-color:\s*var\(--g-graph-node-bg\)/);
    expect(globalsCss).toMatch(/--xy-node-color:\s*var\(--g-graph-node-fg\)/);
    expect(globalsCss).toMatch(/--xy-edge-label-color:\s*var\(--g-graph-node-fg\)/);
    expect(globalsCss).toMatch(/--xy-edge-label-background-color:\s*var\(--g-graph-node-bg\)/);
    const selected = globalsCss.match(
      /\.g-graph-canvas \.react-flow__node\.selectable\.selected[\s\S]*?box-shadow:\s*0 0 0 2px var\(--g-graph-node-ring\)/,
    );
    expect(selected).not.toBeNull();
    expect(globalsCss).toMatch(
      /\.g-graph-canvas \.react-flow__node[\s\S]*?background-color:\s*var\(--g-graph-node-bg\)/,
    );
    expect(globalsCss).not.toMatch(/\.g-graph-node__type\s*\{[^}]*opacity\s*:/);
    expect(globalsCss).not.toMatch(/\.react-flow__node[^{.]*selected[^{]*\{[^}]*background(?:-color)?:\s*(#000|#111|#1a192b|#1e1e1e|black)/i);
  });
});
