import type { MetaClassField } from "@goliath/client";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SchemaPropertyGridSurface } from "./SchemaPropertyGridSurface.js";

const fields: MetaClassField[] = [
  {
    fieldName: "Caption",
    typeId: 1,
    typeName: "portal/nav/Caption",
    typeKind: "string",
    required: true,
    declaredOnClassId: 1,
    declaredOnClassName: "portal/NavNode",
    definedAtDepth: 0,
    isLocal: true,
  },
  {
    fieldName: "NodePath",
    typeId: 2,
    typeName: "portal/nav/NodePath",
    typeKind: "string",
    required: false,
    declaredOnClassId: 1,
    declaredOnClassName: "portal/NavNode",
    definedAtDepth: 0,
    isLocal: true,
  },
];

const flattened = {
  type: "object",
  properties: {
    Caption: { type: "string" },
    NodePath: { type: "string" },
  },
  required: ["Caption"],
};

describe("SchemaPropertyGridSurface submit", () => {
  afterEach(() => {
    cleanup();
  });

  it("does not submit when required validation fails", async () => {
    const onSubmit = vi.fn();
    render(
      <SchemaPropertyGridSurface
        fields={fields}
        schema={flattened}
        rootSchema={flattened}
        initialDocument={{ Caption: "Keep", NodePath: "was-set" }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );
    await act(async () => {
      fireEvent.change(screen.getByTestId("pi-row-Caption").querySelector("input")!, { target: { value: "" } });
      fireEvent.submit(screen.getByRole("button", { name: "Save" }).closest("form")!);
    });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("keeps in-progress edits when parent re-renders with the same initial snapshot", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <SchemaPropertyGridSurface
        fields={fields}
        schema={flattened}
        rootSchema={flattened}
        initialDocument={{ Caption: "Keep", NodePath: "was-set" }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );
    const input = screen.getByTestId("pi-row-Caption").querySelector("input")!;
    await act(async () => {
      fireEvent.change(input, { target: { value: "Edited" } });
    });
    rerender(
      <SchemaPropertyGridSurface
        fields={[...fields]}
        schema={flattened}
        rootSchema={flattened}
        initialDocument={{ Caption: "Keep", NodePath: "was-set" }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );
    expect(input).toHaveValue("Edited");
  });

  it("formats date-time values for datetime-local inputs", () => {
    const dateFields: MetaClassField[] = [
      {
        fieldName: "When",
        typeId: 1,
        typeName: "core/When",
        typeKind: "datetime",
        required: false,
        declaredOnClassId: 1,
        declaredOnClassName: "portal/NavNode",
        definedAtDepth: 0,
        isLocal: true,
      },
    ];
    const schema = {
      type: "object",
      properties: { When: { type: "string", format: "date-time" } },
    };
    render(
      <SchemaPropertyGridSurface
        fields={dateFields}
        schema={schema}
        rootSchema={schema}
        initialDocument={{ When: "2024-06-15T14:30:00.000Z" }}
      />,
    );
    const input = screen.getByTestId("pi-row-When").querySelector("input[type='datetime-local']") as HTMLInputElement;
    expect(input.value).toMatch(/^2024-06-15T\d{2}:\d{2}$/);
  });

  it("emits null for cleared optional fields present in initialDocument", async () => {
    const onSubmit = vi.fn();
    render(
      <SchemaPropertyGridSurface
        fields={fields}
        schema={flattened}
        rootSchema={flattened}
        initialDocument={{ Caption: "Keep", NodePath: "was-set" }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );
    await act(async () => {
      fireEvent.change(screen.getByTestId("pi-row-NodePath").querySelector("input")!, { target: { value: "" } });
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    expect(onSubmit).toHaveBeenCalledWith({ Caption: "Keep", NodePath: null });
  });
});
