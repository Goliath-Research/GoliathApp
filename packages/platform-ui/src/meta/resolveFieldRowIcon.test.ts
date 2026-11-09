import { describe, expect, it } from "vitest";
import type { MetaClassField } from "@goliath/client";
import { resolveFieldRowIcon } from "./resolveFieldRowIcon.js";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";

const registry: HierarchyPresentationRegistry = {
  editorComponentsByClassFqn: {},
  iconOverridesByClassFqn: {
    "e2e/NestedChild": "platform:class-nested-child",
    "e2e/NestedParent": "platform:class-nested-parent",
  },
  editorComponentsByDataTypeName: {},
};

describe("resolveFieldRowIcon", () => {
  it("walks class ancestry for meta-class catalog targets", () => {
    const field: MetaClassField = {
      fieldName: "ChildDoc",
      typeId: 1,
      typeName: "meta/class/e2e/NestedChild",
      typeKind: "object",
      required: false,
      declaredOnClassId: 1,
      declaredOnClassName: "e2e/NestedCarrier",
      definedAtDepth: 0,
      isLocal: true,
    };
    const icon = resolveFieldRowIcon(
      field,
      { mode: "typedMetaClass", className: "e2e/NestedChild", optional: true },
      { kind: "metaClass", className: "e2e/NestedChild" },
      ["e2e/NestedCarrier", "e2e/NestedChild"],
      registry,
    );
    expect(icon).toBe("platform:class-nested-child");
  });

  it("falls back to type kind when no registry icon", () => {
    const icon = resolveFieldRowIcon(
      undefined,
      { mode: "string", optional: true },
      null,
      [],
      registry,
    );
    expect(icon).toBe("platform:type-string");
  });
});
