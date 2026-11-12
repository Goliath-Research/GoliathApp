import { describe, expect, it } from "vitest";
import {
  canCancelRun,
  canRetryNode,
  editableGraphDocument,
  WORKFLOW_DEFINITION_SCHEMA,
  WORKFLOW_STEPS_SCHEMA,
} from "./workflow-graph-schemas";

const spec = {
  name: "wf",
  description: "d",
  root_node_key: "root",
  nodes: [
    { node_key: "root", node_type: "SEQUENCE" },
    { node_key: "a", node_type: "ACTION", action_name: "x", input_template: { deep: { v: 1 } } },
  ],
  edges: [{ parent_node_key: "root", child_node_key: "a", child_order: 0 }],
  output_bindings: [{ node_key: "a", var_name: "v", source_kind: "output" }],
};

describe("workflow graph editor", () => {
  it("never exposes input templates or free-form objects", () => {
    const doc = editableGraphDocument("definitions", spec);
    expect((doc.nodes as Record<string, unknown>[])[1]).not.toHaveProperty("input_template");
    expect(doc).not.toHaveProperty("name");
    const walk = (node: unknown) => {
      if (!node || typeof node !== "object") return;
      const n = node as Record<string, unknown>;
      if (n.type === "object") expect(n.properties).toBeTruthy();
      Object.values((n.properties ?? {}) as Record<string, unknown>).forEach(walk);
      if (n.items) walk(n.items);
    };
    walk(WORKFLOW_DEFINITION_SCHEMA);
    walk(WORKFLOW_STEPS_SCHEMA);
  });

  it("steps mode edits only the node graph", () => {
    const doc = editableGraphDocument("steps", spec);
    expect(Object.keys(doc).sort()).toEqual(["edges", "nodes", "root_node_key"]);
  });

  it("run action guards", () => {
    expect(canCancelRun("RUNNING")).toBe(true);
    expect(canCancelRun("COMPLETED")).toBe(false);
    expect(canCancelRun("CANCELLED")).toBe(false);
    expect(canRetryNode("FAILED")).toBe(true);
    expect(canRetryNode("COMPLETED")).toBe(false);
  });
});
