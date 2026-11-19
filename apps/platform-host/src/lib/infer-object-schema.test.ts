import { describe, expect, it } from "vitest";
import { inferObjectSchema } from "./infer-object-schema";
import { withDocumentSchema } from "./record-editor-schemas";

describe("document schemas", () => {
  it("infers a read-only schema", () => {
    expect(inferObjectSchema({ a: true, b: 2, c: "x", d: { e: 1.5 }, f: [{ g: "h" }] })).toEqual({
      type: "object",
      properties: {
        a: { type: "boolean" },
        b: { type: "integer" },
        c: { type: "string" },
        d: { type: "object", properties: { e: { type: "number" } } },
        f: { type: "array", items: { type: "object", properties: { g: { type: "string" } } } },
      },
    });
  });

  it("adds the registered document schema as the document field", () => {
    const s = withDocumentSchema(
      { type: "object", properties: { name: { type: "string" } } },
      { type: "object", properties: { flag: { type: "boolean" } }, required: ["flag"] },
    );
    expect((s.properties as Record<string, unknown>).document).toEqual({
      type: "object",
      description: "Document (typed by the registered document type)",
      properties: { flag: { type: "boolean" } },
      required: ["flag"],
    });
    expect(withDocumentSchema({ type: "object" }, null)).toEqual({ type: "object" });
  });
});
