import { describe, expect, it } from "vitest";
import {
  compiledGraphHref,
  countSteps,
  linkedVersionId,
  programStructureTree,
  stepNode,
} from "./domain-program-structure";

describe("domain program structure tree", () => {
  it("labels every IR step kind", () => {
    expect(stepNode({ do: "item.check", with: { site: "a", n: 2 } })).toMatchObject({
      kind: "action",
      label: "item.check",
      detail: "site = a, n = 2",
    });
    expect(stepNode({ assign: "total", using: "math.sum" }).label).toBe("total ← math.sum");
    expect(stepNode({ if: "x > 1", then: [{ do: "a" }] }).children.map((c) => c.label)).toEqual(["then"]);
    expect(stepNode({ switch: "kind", cases: { a: [{ do: "x" }] }, default: [{ do: "y" }] }).children).toHaveLength(2);
    expect(stepNode({ for: { in: { var: "items" }, as: "it", parallel: true }, do: [{ do: "a" }] }).label).toBe(
      "for each it in items (parallel)",
    );
    expect(stepNode({ while: "more", do: [{ do: "a" }] }).kind).toBe("while");
    expect(stepNode({ repeat: { count: 3 }, do: [] }).label).toBe("repeat 3 times");
    expect(stepNode({ parallel: [{ do: "a" }, { do: "b" }] }).children).toHaveLength(2);
    expect(stepNode({ wait: { event: "lab.done", correlation: "$.id" } }).label).toBe("wait for event lab.done");
    expect(stepNode({ odd: true }).kind).toBe("unknown");
  });

  it("builds sections and counts steps", () => {
    const tree = programStructureTree({
      variables: { items: [1, 2], cfg: { schemaRef: "x/Config" } },
      on: [{ event: "thing.created", mode: "start_instance" }],
      phases: [{ name: "prep", steps: [{ do: "a" }] }],
      body: [{ do: "b" }, { for: { collection: "items" }, do: [{ do: "c" }] }],
    });
    expect(tree.map((n) => n.label)).toEqual(["Variables", "Event triggers", "Phases", "Body"]);
    expect(tree[0].children.map((c) => c.detail)).toEqual(["default: list (2)", "type x/Config"]);
    expect(countSteps(tree)).toBe(3);
  });

  it("links the compiled graph by version id", () => {
    expect(compiledGraphHref(42)).toBe("/app/workflows/definitions?version=42");
    expect(compiledGraphHref(null)).toBeNull();
    expect(linkedVersionId("?version=42")).toBe(42);
    expect(linkedVersionId("?version=abc")).toBeNull();
    expect(linkedVersionId("")).toBeNull();
  });

  it("labels a switch on a variable reference", () => {
    const node = stepNode({ switch: { ref: "mode" }, cases: { a: [{ call: "x" }] } });
    expect(node.label).toBe("switch mode");
  });
});
