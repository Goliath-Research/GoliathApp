import { describe, expect, it } from "vitest";
import { parsePropertySchema } from "./parseFlattenedFieldSchema.js";

describe("nested schema editors", () => {
  const root = {
    type: "object",
    properties: {
      tags: { type: "array", items: { type: "string" } },
      rows: {
        type: "array",
        items: {
          type: "object",
          properties: { id: { type: "integer" } },
          required: ["id"],
        },
      },
      meta: {
        type: "object",
        properties: { flag: { type: "boolean" } },
      },
    },
  };

  it("selects nestedArray for object items", () => {
    const editor = parsePropertySchema(root.properties.rows, true, root);
    expect(editor.mode).toBe("nestedArray");
    if (editor.mode === "nestedArray") {
      expect(editor.itemsAreObject).toBe(true);
    }
  });

  it("selects nestedObject for object type", () => {
    const editor = parsePropertySchema(root.properties.meta, false, root);
    expect(editor.mode).toBe("nestedObject");
  });

  it("uses schemaless only for unknown nodes", () => {
    const editor = parsePropertySchema({ oneOf: [{ type: "string" }] }, true, root);
    expect(editor.mode).toBe("schemaless");
  });
});
