import { describe, expect, it } from "vitest";
import { resolveFieldEditor } from "./resolveFieldEditor.js";

describe("resolveFieldEditor", () => {
  const field = {
    fieldName: "Caption",
    typeId: null,
    typeName: "String",
    typeKind: "string",
    required: true,
    declaredOnClassId: 1,
    declaredOnClassName: "portal/NavNode",
    definedAtDepth: 0,
    isLocal: true,
  };

  it("prefers flattened schema property over Meta field kind", () => {
    const editor = resolveFieldEditor(field, {
      type: "object",
      properties: { Caption: { type: "string", enum: ["a", "b"] } },
    });
    expect(editor.mode).toBe("string");
    expect(editor.enumValues).toEqual(["a", "b"]);
  });

  it("falls back to Meta field kind when schema property missing", () => {
    const editor = resolveFieldEditor(field, { type: "object", properties: {} });
    expect(editor.mode).toBe("string");
  });
});
