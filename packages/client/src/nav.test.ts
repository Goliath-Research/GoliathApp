import { describe, expect, it } from "vitest";
import { buildOperatorNavTree } from "./nav.js";
import type { OperatorNavNode } from "./nav.js";

describe("buildOperatorNavTree", () => {
  it("nests children and assigns official node paths as hrefs", () => {
    const nodes: OperatorNavNode[] = [
      {
        nodeId: 1,
        parentId: null,
        caption: "Platform",
        seq: 10,
        presentationKind: "config",
        nodePath: "/app",
      },
      {
        nodeId: 2,
        parentId: 1,
        caption: "Meta model",
        seq: 20,
        presentationKind: "meta_tree",
        nodePath: "/app/meta",
      },
      {
        nodeId: 3,
        parentId: 2,
        caption: "Classes",
        seq: 10,
        presentationKind: "meta_class",
        nodePath: "/app/meta/classes",
      },
    ];
    const tree = buildOperatorNavTree(nodes);
    expect(tree).toHaveLength(1);
    expect(tree[0]?.href).toBe("/app");
    expect(tree[0]?.children[0]?.href).toBe("/app/meta");
    expect(tree[0]?.children[0]?.children[0]?.href).toBe("/app/meta/classes");
  });
});
