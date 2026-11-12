import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("SchemaPropertyGridSurface", () => {
  it("does not render JSON textarea editors", () => {
    const source = readFileSync(resolve(import.meta.dirname, "SchemaPropertyGridSurface.tsx"), "utf8");
    expect(source).not.toMatch(/<textarea[\s\S]*g-host-textarea/);
  });
});
