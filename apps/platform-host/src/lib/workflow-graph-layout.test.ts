import { describe, expect, it } from "vitest";
import { layoutWorkflowGraph } from "./workflow-graph-layout";

describe("layoutWorkflowGraph", () => {
  const spec = {
    root_node_key: "root",
    nodes: [
      { node_key: "root", node_type: "SEQUENCE" },
      { node_key: "check", node_type: "IF", condition_var: "ready" },
      { node_key: "run", node_type: "ACTION", action_name: "x/Run" },
      { node_key: "skip", node_type: "ACTION", action_name: "x/Skip" },
    ],
    edges: [
      { parent_node_key: "root", child_node_key: "check", child_order: 0, branch_kind: "SEQUENCE" },
      { parent_node_key: "check", child_node_key: "run", child_order: 0, branch_kind: "THEN" },
      { parent_node_key: "check", child_node_key: "skip", child_order: 1, branch_kind: "ELSE" },
      { parent_node_key: "check", child_node_key: "ghost", child_order: 2 },
    ],
  };

  it("places children below their parent and labels nodes and branches", () => {
    const g = layoutWorkflowGraph(spec);
    const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    expect(byId.root.isRoot).toBe(true);
    expect(byId.root.isEnd).toBe(false);
    expect(byId.run.isEnd).toBe(true);
    expect(byId.skip.isEnd).toBe(true);
    expect(byId.run.isError).toBe(false);
    expect(byId.check.y).toBeGreaterThan(byId.root.y);
    expect(byId.run.y).toBeGreaterThan(byId.check.y);
    expect(byId.run.detail).toBe("x/Run");
    expect(byId.check.detail).toBe("ready");
    expect(g.edges.map((e) => e.label)).toEqual(["#0", "then", "else"]);
  });

  it("marks ACTION nodes without an action as errors", () => {
    const g = layoutWorkflowGraph({
      root_node_key: "root",
      nodes: [
        { node_key: "root", node_type: "SEQUENCE" },
        { node_key: "step", node_type: "ACTION" },
      ],
      edges: [{ parent_node_key: "root", child_node_key: "step" }],
    });
    const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    expect(byId.step.isError).toBe(true);
    expect(byId.step.isEnd).toBe(true);
    expect(byId.root.isError).toBe(false);
  });

  it("drops edges to unknown nodes and reports them", () => {
    expect(layoutWorkflowGraph(spec).missing).toEqual(["ghost"]);
  });

  it("handles an empty or missing spec", () => {
    expect(layoutWorkflowGraph(null)).toEqual({ nodes: [], edges: [], missing: [] });
  });
});
