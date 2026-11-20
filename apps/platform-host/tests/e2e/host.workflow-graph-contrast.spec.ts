import { expect, test, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function repoRoot(): string {
  for (const candidate of [process.cwd(), resolve(process.cwd(), "../.."), resolve(process.cwd(), ".")]) {
    if (existsSync(resolve(candidate, "packages/ui/src/styles.css"))) return candidate;
  }
  throw new Error(`cannot find repo root from cwd=${process.cwd()}`);
}

const repoRootDir = repoRoot();
const uiStyles = readFileSync(resolve(repoRootDir, "packages/ui/src/styles.css"), "utf8");
const globals = readFileSync(resolve(repoRootDir, "apps/platform-host/src/app/globals.css"), "utf8").replace(
  /@import\s+"@goliath\/ui\/styles\.css"\s*;/,
  "",
);
const xyflow = readFileSync(resolve(repoRootDir, "node_modules/@xyflow/react/dist/style.css"), "utf8");

const STATES = [
  { id: "default", label: "start", type: "SEQUENCE", extra: "g-graph-node--root", selected: false },
  { id: "hover", label: "hover", type: "SEQUENCE", extra: "is-hover", selected: false },
  { id: "selected", label: "selected", type: "ACTION", extra: "", selected: true },
  { id: "end", label: "end", type: "ACTION", extra: "g-graph-node--end", selected: false },
  { id: "error", label: "missing action", type: "ACTION", extra: "g-graph-node--end g-graph-node--error", selected: false },
  { id: "inactive", label: "inactive version", type: "SEQUENCE", extra: "", selected: false, canvas: "g-graph-canvas--inactive" },
] as const;

function fixtureHtml(): string {
  const cards = STATES.map((s, i) => {
    const selected = s.selected ? "selected" : "";
    const canvasClass = "canvas" in s && s.canvas ? s.canvas : "";
    return `
      <div class="g-graph-canvas ${canvasClass}" style="height:auto;border:none;margin:0;">
        <div class="react-flow">
          <div
            class="react-flow__node react-flow__node-default selectable g-graph-node ${s.extra} ${selected}"
            data-testid="graph-node-${s.id}"
            data-state="${s.id}"
            style="position:relative;width:200px;min-height:56px;padding:8px;"
          >
            <div class="g-graph-node__label">
              <strong>${s.label}</strong>
              <span class="g-graph-node__type">${s.type}</span>
              <span class="g-graph-node__detail">step ${i + 1}</span>
            </div>
          </div>
        </div>
      </div>`;
  }).join("");
  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>${uiStyles}\n${xyflow}\n${globals}
      body { margin: 0; font-family: var(--g-font, system-ui, sans-serif); background: var(--g-bg); color: var(--g-fg); }
      .sheet { display: grid; grid-template-columns: repeat(3, auto); gap: 24px; padding: 24px; align-items: start; }
      .cell { display: flex; flex-direction: column; gap: 8px; }
      .cell span.cap { font-size: 12px; color: var(--g-fg-muted); }
      .edge-demo {
        display: inline-flex; align-items: center; gap: 8px;
        color: var(--g-graph-node-fg); background: var(--g-graph-node-bg);
        border: 1px solid var(--g-graph-node-border); border-radius: 4px; padding: 2px 8px; font-size: 12px;
      }
    </style>
  </head>
  <body>
    <div class="sheet">
      ${cards}
      <div class="cell">
        <span class="cap">edge label</span>
        <span class="edge-demo react-flow__edge-label" data-testid="graph-edge-label">then</span>
      </div>
    </div>
  </body>
</html>`;
}

function parseRgb(color: string): [number, number, number] {
  const m = color.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  if (!m) throw new Error(`unparseable color: ${color}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function srgbToLin(channel: number): number {
  const s = channel / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function contrastOf(fg: string, bg: string): number {
  const lin = (c: string) => {
    const [r, g, b] = parseRgb(c);
    return 0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b);
  };
  const a = lin(fg);
  const b = lin(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

async function measure(page: Page, selector: string, textSelector: string) {
  const colors = await page.locator(selector).evaluate((el, textSel) => {
    const node = el as HTMLElement;
    const text = node.querySelector(textSel) as HTMLElement | null;
    const cs = getComputedStyle(node);
    const ts = getComputedStyle(text ?? node);
    return { bg: cs.backgroundColor, fg: ts.color };
  }, textSelector);
  return { ...colors, ratio: contrastOf(colors.fg, colors.bg) };
}

async function render(page: Page, scheme: "light" | "dark") {
  await page.emulateMedia({ colorScheme: scheme });
  await page.setContent(fixtureHtml(), { waitUntil: "load" });
}

test.describe("workflow graph node caption contrast (visual)", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`${scheme} theme: captions stay dark on the white fill in every state`, async ({ page }, testInfo) => {
      await render(page, scheme);
      for (const s of STATES) {
        const node = page.getByTestId(`graph-node-${s.id}`);
        await expect(node).toBeVisible();
        for (const textSel of ["strong", ".g-graph-node__type", ".g-graph-node__detail"]) {
          const m = await measure(page, `[data-testid="graph-node-${s.id}"]`, textSel);
          expect(m.ratio, `${scheme} ${s.id} ${textSel} ${m.fg} on ${m.bg}`).toBeGreaterThanOrEqual(4.5);
        }
        const fill = await measure(page, `[data-testid="graph-node-${s.id}"]`, "strong");
        const [r, g, b] = parseRgb(fill.bg);
        const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        expect(luminance, `${scheme} ${s.id} fill should stay light, got ${fill.bg}`).toBeGreaterThan(0.9);
      }
      const edge = page.getByTestId("graph-edge-label");
      const edgeColors = await edge.evaluate((el) => {
        const cs = getComputedStyle(el as HTMLElement);
        return { bg: cs.backgroundColor, fg: cs.color };
      });
      expect(contrastOf(edgeColors.fg, edgeColors.bg)).toBeGreaterThanOrEqual(4.5);

      const selected = page.getByTestId("graph-node-selected");
      const outline = await selected.evaluate((el) => {
        const cs = getComputedStyle(el as HTMLElement);
        return { outline: cs.outlineColor, shadow: cs.boxShadow };
      });
      expect(outline.shadow + outline.outline).toMatch(/rgb\(/);

      const shotDir = process.env.PLAYWRIGHT_SCREENSHOT_DIR;
      const dest = shotDir
        ? resolve(shotDir, `workflow-graph-nodes-${scheme}.png`)
        : testInfo.outputPath(`workflow-graph-nodes-${scheme}.png`);
      await page.screenshot({ path: dest, fullPage: true });
    });
  }
});
