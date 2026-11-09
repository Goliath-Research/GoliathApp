import { describe, expect, it } from "vitest";
import { resolveSchemaRef, SCHEMA_PROPERTY_GRID_MAX_DEPTH } from "./jsonSchema.js";
import { parsePropertySchema } from "./parseFlattenedFieldSchema.js";

describe("jsonSchema $ref", () => {
  const root = {
    type: "object",
    $defs: {
      Address: {
        type: "object",
        properties: { city: { type: "string" } },
        required: ["city"],
      },
    },
    properties: {
      home: { $ref: "#/$defs/Address" },
    },
  };

  it("resolves $defs ref", () => {
    const resolved = resolveSchemaRef("#/$defs/Address", root);
    expect(resolved?.properties).toEqual({ city: { type: "string" } });
  });

  it("parses nested object via ref", () => {
    const editor = parsePropertySchema(root.properties.home, true, root);
    expect(editor.mode).toBe("nestedObject");
    if (editor.mode === "nestedObject") {
      expect(editor.objectSchema.properties).toEqual({ city: { type: "string" } });
    }
  });

  it("exposes recursion limit constant", () => {
    expect(SCHEMA_PROPERTY_GRID_MAX_DEPTH).toBeGreaterThanOrEqual(4);
  });
});
