import { describe, expect, it } from "vitest";
import {
  resolveHierarchyFieldEditor,
  resolveClassGridPresentation,
  walkRegistryAncestry,
} from "./metaHierarchyResolver.js";

describe("metaHierarchyResolver", () => {
  const registry = {
    editorComponentsByClassFqn: {
      "e2e/NestedParent": "ParentEditor",
      "e2e/NestedChild": "ChildEditor",
    },
    iconOverridesByClassFqn: {
      "e2e/NestedChild": "platform:layout-grid",
    },
    editorComponentsByDataTypeName: {},
  };

  it("walkRegistryAncestry prefers exact FQN then ancestors", () => {
    const walk = walkRegistryAncestry(
      "e2e/NestedChild",
      ["e2e/NestedParent", "meta/BaseDocument"],
      registry.editorComponentsByClassFqn,
    );
    expect(walk.key).toBe("ChildEditor");
    expect(walk.resolution).toBe("exact");
  });

  it("resolveClassGridPresentation picks ancestor editor", () => {
    const childOnly = {
      ...registry,
      editorComponentsByClassFqn: { "e2e/NestedParent": "ParentEditor" },
    };
    const pres = resolveClassGridPresentation("e2e/NestedChild", ["e2e/NestedParent"], childOnly);
    expect(pres.manifestKey).toBe("ParentEditor");
    expect(pres.editorResolution).toBe("ancestor");
  });

  it("resolves wf.data_type object field as typedDataType", () => {
    const field = {
      fieldName: "Payload",
      typeId: 1,
      typeName: "e2e/NestedPayload",
      typeKind: "object",
      required: true,
      declaredOnClassId: 1,
      declaredOnClassName: "e2e/NestedCarrier",
      definedAtDepth: 0,
      isLocal: true,
    };
    const result = resolveHierarchyFieldEditor({
      field,
      declaringClassAncestry: ["e2e/NestedCarrier"],
      flattenedSchema: {
        type: "object",
        properties: {
          Payload: {
            type: "object",
            properties: { label: { type: "string" }, qty: { type: "integer" } },
          },
        },
      },
      registry,
    });
    expect(result.editor.mode).toBe("nestedObject");
  });

  it("resolves meta/class catalog type as typedMetaClass", () => {
    const field = {
      fieldName: "ChildDoc",
      typeId: 2,
      typeName: "meta/class/e2e/NestedChild",
      typeKind: "object",
      required: false,
      declaredOnClassId: 1,
      declaredOnClassName: "e2e/NestedCarrier",
      definedAtDepth: 0,
      isLocal: true,
    };
    const result = resolveHierarchyFieldEditor({
      field,
      declaringClassAncestry: ["e2e/NestedCarrier"],
      flattenedSchema: { type: "object", properties: {} },
      registry,
    });
    expect(result.editor.mode).toBe("typedMetaClass");
    if (result.editor.mode === "typedMetaClass") {
      expect(result.editor.className).toBe("e2e/NestedChild");
    }
    expect(result.presentation.manifestKey).toBe("ChildEditor");
  });

  it("inherits primitive shape from typeKind not JSON type alone", () => {
    const field = {
      fieldName: "Caption",
      typeId: 3,
      typeName: "String",
      typeKind: "string",
      required: true,
      declaredOnClassId: 1,
      declaredOnClassName: "e2e/NestedCarrier",
      definedAtDepth: 0,
      isLocal: true,
    };
    const result = resolveHierarchyFieldEditor({
      field,
      declaringClassAncestry: ["e2e/NestedCarrier"],
      flattenedSchema: { type: "object", properties: {} },
      registry,
    });
    expect(result.editor.mode).toBe("string");
  });
});
