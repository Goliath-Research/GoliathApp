import { describe, expect, it } from "vitest";
import { parsePropertySchema } from "./parseFlattenedFieldSchema.js";

describe("parsePropertySchema", () => {
  it("parses enum and optional null via anyOf", () => {
    const parsed = parsePropertySchema({ type: "string", enum: ["draft", "live"] }, true, null);
    expect(parsed.mode).toBe("string");
    if (parsed.mode === "string") {
      expect(parsed.enumValues).toEqual(["draft", "live"]);
    }

    const optional = parsePropertySchema({ anyOf: [{ type: "string" }, { type: "null" }] }, false, null);
    expect(optional.optional).toBe(true);
  });

  it("parses date and date-time string formats", () => {
    const dateOnly = parsePropertySchema({ type: "string", format: "date" }, true, null);
    expect(dateOnly.mode).toBe("date");
    if (dateOnly.mode === "date") {
      expect(dateOnly.inputType).toBe("date");
    }
    const dateTime = parsePropertySchema({ type: "string", format: "date-time" }, true, null);
    if (dateTime.mode === "date") {
      expect(dateTime.inputType).toBe("datetime-local");
    }
  });

  it("uses nested object instead of JSON textarea", () => {
    const parsed = parsePropertySchema(
      { type: "object", properties: { a: { type: "string" } } },
      true,
      null,
    );
    expect(parsed.mode).toBe("nestedObject");
  });
});
