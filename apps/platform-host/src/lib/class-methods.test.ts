import { describe, expect, it } from "vitest";
import { groupMethodsByClass, methodOrigin, overrideDraft, type ClassMethodRow } from "./class-methods";

const row = (over: Partial<ClassMethodRow>): ClassMethodRow => ({
  class_name: "Base",
  method_id: 1,
  method_name: "run",
  declared_on_class: "Base",
  inherited: false,
  inheritance_depth: 0,
  is_override: false,
  is_abstract: false,
  is_final: false,
  impl_kind: "action",
  impl_ref: "run_action",
  description: null,
  param_count: 0,
  ...over,
});

describe("groupMethodsByClass", () => {
  it("groups by owning class and sorts", () => {
    const groups = groupMethodsByClass([
      row({ class_name: "Child", method_name: "zeta", method_id: 3 }),
      row({ class_name: "Base", method_name: "run" }),
      row({ class_name: "Child", method_name: "run", inherited: true, declared_on_class: "Base" }),
    ]);
    expect(groups.map((g) => g.className)).toEqual(["Base", "Child"]);
    expect(groups[1].methods.map((m) => m.method_name)).toEqual(["run", "zeta"]);
  });

  it("filters by class, method or implementation", () => {
    const rows = [row({}), row({ class_name: "Other", method_name: "x", impl_ref: "special_action" })];
    expect(groupMethodsByClass(rows, "special")).toHaveLength(1);
    expect(groupMethodsByClass(rows, "OTHER")[0].className).toBe("Other");
  });
});

describe("methodOrigin", () => {
  it("describes inheritance and overrides", () => {
    expect(methodOrigin(row({ inherited: true, declared_on_class: "Base" }))).toBe("inherited from Base");
    expect(methodOrigin(row({ is_override: true }))).toBe("override");
    expect(methodOrigin(row({}))).toBe("declared");
  });
});

describe("overrideDraft", () => {
  it("targets the inheriting class and copies the signature", () => {
    const draft = overrideDraft(row({ class_name: "Child", inherited: true }), {
      class_name: "Base",
      impl_kind: "action",
      action_name: "run_action",
      parameters: [{ name: "a", type_id: 4, required: true }],
      defaults: { a: 1 },
    });
    expect(draft).toEqual({
      class_name: "Child",
      method_name: "run",
      impl_kind: "action",
      action_name: "run_action",
      parameters: [{ name: "a", type_id: 4, required: true }],
    });
  });
});
