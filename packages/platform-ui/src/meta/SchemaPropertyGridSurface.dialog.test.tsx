import type { MetaClassField } from "@goliath/client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  });
});
