import type { MetaClassField } from "@goliath/client";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import { SchemaPropertyGridSurface } from "./SchemaPropertyGridSurface.js";

const carrierFields: MetaClassField[] = [
  {
    fieldName: "Payload",
    typeId: 1,
    typeName: "e2e/NestedPayload",
    typeKind: "object",
    required: true,
    declaredOnClassId: 1,
    declaredOnClassName: "e2e/NestedCarrier",
    definedAtDepth: 0,
    isLocal: true,
  },
];

const flattened = {
  type: "object",
  properties: {
    Payload: { $ref: "goliath:type/e2e/NestedPayload" },
  },
  required: ["Payload"],
};

describe("SchemaPropertyGridSurface nested dialog", () => {
  afterEach(() => {
    cleanup();
  });

  it("opens property inspector host when catalog ellipsis is clicked", async () => {
    const catalogResolver: MetaCatalogResolver = {
      loadMetaClass: vi.fn(),
      loadDataType: vi.fn(async () => ({
        typeName: "e2e/NestedPayload",
        kind: "object",
        schemaJson: {
          type: "object",
          properties: { label: { type: "string" }, qty: { type: "integer" } },
          required: ["label"],
        },
        elementTypeName: null,
      })),
    };

    render(
      <SchemaPropertyGridSurface
        fields={carrierFields}
        schema={flattened}
        rootSchema={flattened}
        bundledSchema={flattened}
        catalogResolver={catalogResolver}
        documentClassFqn="e2e/NestedCarrier"
        initialDocument={{}}
      />,
    );

    fireEvent.click(screen.getByTestId("pi-open-Payload"));
    await waitFor(() => {
      expect(screen.getByTestId("property-inspector-modal")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("property-inspector-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("property-inspector-modal")).not.toBeInTheDocument();
    });
  });

  it("commits nested catalog edits to row summary on OK", async () => {
    const catalogResolver: MetaCatalogResolver = {
      loadMetaClass: vi.fn(),
      loadDataType: vi.fn(async () => ({
        typeName: "e2e/NestedPayload",
        kind: "object",
        schemaJson: {
          type: "object",
          properties: { label: { type: "string" }, qty: { type: "integer" } },
          required: ["label"],
        },
        elementTypeName: null,
      })),
    };

    render(
      <SchemaPropertyGridSurface
        fields={carrierFields}
        schema={flattened}
        rootSchema={flattened}
        bundledSchema={flattened}
        catalogResolver={catalogResolver}
        documentClassFqn="e2e/NestedCarrier"
        initialDocument={{}}
      />,
    );

    fireEvent.click(screen.getByTestId("pi-open-Payload"));
    await waitFor(() => {
      expect(screen.getByTestId("property-inspector-modal")).toBeInTheDocument();
    });
    const modal = screen.getByTestId("property-inspector-modal");
    const labelInput = modal.querySelector('[data-testid="pi-row-label"] input') as HTMLInputElement;
    const qtyInput = modal.querySelector('[data-testid="pi-row-qty"] input') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(labelInput, { target: { value: "payload-1" } });
      fireEvent.change(qtyInput, { target: { value: "1" } });
    });
    await waitFor(() => {
      expect(qtyInput).toHaveValue(1);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("property-inspector-ok"));
    });
    await waitFor(() => {
      expect(screen.queryByTestId("property-inspector-modal")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("pi-row-Payload")).toHaveTextContent(/field\(s\)/);
    expect(screen.getByTestId("pi-row-Payload")).not.toHaveTextContent("*—Open");
  });
});
