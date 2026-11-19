import { describe, expect, it } from "vitest";
import {
  addNode,
  connect,
  nodeBindings,
  nodeParameterGridSchema,
  removeEdges,
  removeNodes,
  setNodeBindings,
} from "./workflow-graph-edit";

const base = {
  root_node_key: "root",
  nodes: [
    { node_key: "root", node_type: "SEQUENCE" },
    { node_key: "a", node_type: "ACTION", action_name: "workflow.const_int" },
  ],
  edges: [{ parent_node_key: "root", child_node_key: "a", child_order: 0, branch_kind: "SEQUENCE" }],
  input_bindings: [{ node_key: "a", target_json_path: "$.value", source_expr: "${vars.n}", is_required: true }],
};

describe("workflow graph edits", () => {
  it("adds a node under a parent with a fresh key", () => {
    const { doc, key } = addNode(base, { node_type: "ACTION", action_name: "workflow.fs_stat" }, "root");
    expect(key).toBe("action_1");
    expect((doc.edges as unknown[]).at(-1)).toEqual({
      parent_node_key: "root",
      child_node_key: "action_1",
      child_order: 1,
      branch_kind: "SEQUENCE",
    });
  });

  it("does not duplicate or self-connect", () => {
    expect(connect(base, "root", "a")).toBe(base);
    expect(connect(base, "a", "a")).toBe(base);
  });

  it("removes nodes with their edges and bindings", () => {
    const next = removeNodes(base, ["a"]);
    expect(next.nodes).toEqual([{ node_key: "root", node_type: "SEQUENCE" }]);
    expect(next.edges).toEqual([]);
    expect(next.input_bindings).toEqual([]);
  });

  it("removes edges by canvas id", () => {
    expect(removeEdges(base, ["e0:root->a"]).edges).toEqual([]);
  });

  it("round-trips parameter bindings", () => {
    expect(nodeBindings(base, "a")).toEqual([{ parameter: "value", source_expr: "${vars.n}", is_required: true }]);
    const next = setNodeBindings(base, "a", [{ parameter: "value", source_expr: "${vars.m}" }]);
    expect(next.input_bindings).toEqual([
      { node_key: "a", target_json_path: "$.value", source_expr: "${vars.m}", is_required: false },
    ]);
  });

  it("types binding targets by the action's parameters", () => {
    const schema = nodeParameterGridSchema({ type: "object", properties: { path: { type: "string" } } });
    const items = ((schema.properties as Record<string, Record<string, unknown>>).bindings.items ?? {}) as {
      properties: Record<string, { enum?: string[] }>;
    };
    expect(items.properties.parameter.enum).toEqual(["path"]);
  });
});
