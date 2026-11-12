import { describe, expect, it } from "vitest";
import {
  buildSemanticRunParams,
  parseViewDefinition,
  previewColumns,
} from "./operator-view-definition";

describe("operator-view-definition", () => {
  it("parses empty params as defaults", () => {
    const def = parseViewDefinition(undefined);
    expect(def.limit).toBe(50);
    expect(def.visualization.type).toBe("table");
  });

  it("builds semantic filter template", () => {
    const params = buildSemanticRunParams({
      columns: [],
      filters: [{ field: "name", operator: "contains", value: "acme" }],
      sort: [],
      groupBy: [],
      aggregations: [],
      limit: 25,
      visualization: { type: "table" },
    });
    expect(params.limit).toBe(25);
    expect(params.filter_template).toEqual({
      all_of: [{ attribute: "name", op: "contains", param: "f0" }],
    });
    expect(params.f0).toBe("acme");
  });

  it("previewColumns prefers configured columns", () => {
    const cols = previewColumns(
      {
        columns: [{ field: "a", label: "A" }],
        filters: [],
        sort: [],
        groupBy: [],
        aggregations: [],
        limit: 10,
        visualization: { type: "table" },
      },
      { b: 1 },
    );
    expect(cols).toEqual([{ key: "a", label: "A" }]);
  });
});
