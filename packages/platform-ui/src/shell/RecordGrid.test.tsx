import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecordDialog, RecordGrid, filterRecordRows, sortRecordRows } from "./RecordGrid.js";

type Row = { id: number; name: string; status: string };
const rows: Row[] = [
  { id: 2, name: "beta", status: "active" },
  { id: 10, name: "alpha", status: "retired" },
  { id: 1, name: "gamma", status: "active" },
];
const columns = [
  { key: "id", label: "ID" },
  { key: "name", label: "Name" },
  { key: "status", label: "Status" },
];

afterEach(cleanup);

describe("record grid helpers", () => {
  it("filters on every term across visible cells", () => {
    expect(filterRecordRows(rows, columns, "active ga").map((r) => r.name)).toEqual(["gamma"]);
    expect(filterRecordRows(rows, columns, "")).toHaveLength(3);
  });
  it("sorts numbers numerically and flips direction", () => {
    expect(sortRecordRows(rows, { key: "id", dir: "asc" }).map((r) => r.id)).toEqual([1, 2, 10]);
    expect(sortRecordRows(rows, { key: "name", dir: "desc" }).map((r) => r.name)).toEqual(["gamma", "beta", "alpha"]);
  });
});

describe("RecordGrid", () => {
  it("renders toolbar Add and per-row View/Edit/actions", () => {
    const onAdd = vi.fn();
    const onView = vi.fn();
    const onEdit = vi.fn();
    const onRetire = vi.fn();
    render(
      <RecordGrid
        title="Things"
        noun="thing"
        columns={columns}
        rows={rows}
        rowKey={(r) => String(r.id)}
        rowLabel={(r) => r.name}
        onAdd={onAdd}
        onView={onView}
        onEdit={onEdit}
        canEdit={(r) => r.status !== "retired"}
        rowActions={[{ id: "retire", label: "Retire", visible: (r) => r.status === "active", onRun: onRetire }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add thing" }));
    fireEvent.click(screen.getByRole("button", { name: "View beta" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit gamma" }));
    fireEvent.click(screen.getByRole("button", { name: "Retire beta" }));
    expect(onAdd).toHaveBeenCalledOnce();
    expect(onView).toHaveBeenCalledWith(rows[0]);
    expect(onEdit).toHaveBeenCalledWith(rows[2]);
    expect(onRetire).toHaveBeenCalledWith(rows[0]);
    expect(screen.queryByRole("button", { name: "Edit alpha" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Retire alpha" })).toBeNull();
  });

  it("sorts on header click and filters from the toolbar", () => {
    render(<RecordGrid title="Things" columns={columns} rows={rows} rowKey={(r) => String(r.id)} />);
    fireEvent.click(screen.getByRole("button", { name: /^Name/ }));
    const body = screen.getAllByRole("rowgroup")[1]!;
    expect(within(body).getAllByRole("row").map((r) => r.textContent)).toEqual([
      "10alpharetired",
      "2betaactive",
      "1gammaactive",
    ]);
    fireEvent.change(screen.getByPlaceholderText("Filter…"), { target: { value: "retired" } });
    expect(within(screen.getAllByRole("rowgroup")[1]!).getAllByRole("row")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toContain("1 of 3");
  });
});

describe("RecordDialog", () => {
  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <RecordDialog open title="Edit thing" onClose={onClose}>
        <p>body</p>
      </RecordDialog>,
    );
    expect(screen.getByRole("dialog", { name: "Edit thing" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
