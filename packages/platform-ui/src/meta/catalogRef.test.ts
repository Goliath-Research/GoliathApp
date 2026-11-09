import { describe, expect, it } from "vitest";
import { catalogRefFromFieldTypeName, parseGoliathRef } from "./catalogRef.js";

describe("catalogRef", () => {
  it("parses goliath meta class URIs", () => {
    expect(parseGoliathRef("goliath:meta/class/e2e/NestedChild")).toEqual({
      kind: "metaClass",
      className: "e2e/NestedChild",
    });
  });

  it("parses wf.data_type names for object kinds", () => {
    expect(catalogRefFromFieldTypeName("e2e/NestedPayload", "object")).toEqual({
      kind: "dataType",
      typeName: "e2e/NestedPayload",
    });
  });
});
