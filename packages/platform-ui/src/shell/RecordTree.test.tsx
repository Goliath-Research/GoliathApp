import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecordTree, buildTreeIndex, subtreeKeys, type RecordTreeNode } from "./RecordTree.js";

const nodes: RecordTreeNode[] = [
  { key: "1", parentKey: null, label: "Root" },
  { key: "2", parentKey: "1", label: "Alpha" },
  { key: "3", parentKey: "1", label: "Beta" },
  { key: "4", parentKey: "3", label: "Gamma" },
  { key: "5", parentKey: null, label: "Other" },
];

afterEach(cleanup);

describe("tree helpers", () => {
  it("indexes children in order and finds subtrees", () => {
    const index = buildTreeIndex(nodes);
    expect(index.children.get("1")!.map((n) => n.label)).toEqual(["Alpha", "Beta"]);
    expect([...subtreeKeys(index, "1")].sort()).toEqual(["1", "2", "3", "4"]);
  });
});

describe("RecordTree", () => {
  it("adds, reorders, moves and deletes through callbacks", () => {
    const onMove = vi.fn();
    const onAddChild = vi.fn();
    const onAddSibling = vi.fn();
    const onDelete = vi.fn();
    render(
      <RecordTree
        title="Menu"
        nodes={nodes}
        onMove={onMove}
        onAddChild={onAddChild}
        onAddSibling={onAddSibling}
        onDelete={onDelete}
        canDelete={(_n, kids) => kids === 0}
        onView={() => {}}
        onEdit={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add node" }));
    expect(onAddChild).toHaveBeenCalledWith(null);
    fireEvent.click(screen.getByRole("button", { name: "Add child under Beta" }));
    expect(onAddChild).toHaveBeenLastCalledWith(nodes[2]);
    fireEvent.click(screen.getByRole("button", { name: "Add sibling after Alpha" }));
    expect(onAddSibling).toHaveBeenCalledWith(nodes[1]);
    fireEvent.click(screen.getByRole("button", { name: "Move Beta up" }));
    expect(onMove).toHaveBeenLastCalledWith(nodes[2], "1", 0);
    expect((screen.getByRole("button", { name: "Move Alpha up" }) as HTMLButtonElement).disabled).toBe(true);
    // Move-to-parent picker excludes the node's own subtree.
    fireEvent.click(screen.getByRole("button", { name: "Move Beta to another parent" }));
    const picker = screen.getByLabelText(/New parent/) as HTMLSelectElement;
    expect([...picker.options].map((o) => o.textContent)).toEqual(["(top level)", "Root", "Alpha", "Other"]);
    fireEvent.change(picker, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Move" }));
    expect(onMove).toHaveBeenLastCalledWith(nodes[2], "5", null);
    expect(screen.queryByRole("button", { name: "Delete Root" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete Gamma" }));
    expect(onDelete).toHaveBeenCalledWith(nodes[3]);
  });

  it("collapses and filters", () => {
    render(<RecordTree title="Menu" nodes={nodes} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse Root" }));
    expect(screen.queryByText("Alpha")).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Filter…"), { target: { value: "gam" } });
    expect(screen.getByText("Gamma")).toBeTruthy();
    expect(screen.queryByText("Alpha")).toBeNull();
    expect(screen.queryByText("Other")).toBeNull();
  });
});
