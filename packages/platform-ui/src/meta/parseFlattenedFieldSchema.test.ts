import { describe, expect, it } from "vitest";
import { parseFlattenedFieldSchema } from "./parseFlattenedFieldSchema.js";

describe("parseFlattenedFieldSchema", () => {
  it("parses enum and optional null via anyOf", () => {
    const parsed = parseFlattenedFieldSchema(
      { type: "string", enum: ["draft", "live"] },
      true,
    );
    expect(parsed.mode).toBe("string");
    expect(parsed.enumValues).toEqual(["draft", "live"]);

    const optional = parseFlattenedFieldSchema(
      { anyOf: [{ type: "string" }, { type: "null" }] },
      false,
    );
    expect(optional.optional).toBe(true);
  });

  it("falls back to json mode for unsupported composition", () => {
    const parsed = parseFlattenedFieldSchema({ allOf: [{ type: "object" }] }, true);
    expect(parsed.mode).toBe("json");
    if (parsed.mode === "json") {
      expect(parsed.reason).toContain("composition");
    }
  });
});
