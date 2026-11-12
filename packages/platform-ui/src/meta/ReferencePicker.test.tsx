import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parsePropertySchema } from "./parseFlattenedFieldSchema.js";
import { parseReferenceHint } from "./referenceHint.js";
import { ReferenceResolverProvider, type ReferenceResolver } from "./ReferenceResolverContext.js";
import { SchemaPropertyGridSurface } from "./SchemaPropertyGridSurface.js";

const schema = {
  type: "object",
  properties: {
    action_name: { type: "string", "x-goliath-ref": "action" },
    cluster_id: { type: "integer", "x-goliath-ref": { kind: "cluster" } },
    nested: {
      type: "object",
      properties: {
        event_type: { type: "string", "x-goliath-ref": "event_type" },
      },
    },
  },
  required: ["action_name"],
};

function resolverWith(rows: Record<string, { value: string; label: string; detail?: string }[]>) {
  const search = vi.fn(async (kind: string, query: string) =>
    (rows[kind] ?? []).filter((r) => r.label.toLowerCase().includes(query.toLowerCase())),
  );
  return { search } satisfies ReferenceResolver;
}

describe("reference hint", () => {
  afterEach(() => cleanup());

  it("parses string and object forms", () => {
    expect(parseReferenceHint({ "x-goliath-ref": "action" })).toEqual({ kind: "action" });
    expect(parseReferenceHint({ "x-goliath-ref": { kind: "cluster" } })).toEqual({ kind: "cluster" });
    expect(parseReferenceHint({ type: "string" })).toBeNull();
    expect(parseReferenceHint({ "x-goliath-ref": "" })).toBeNull();
  });

  it("maps hinted properties to the reference editor", () => {
    expect(parsePropertySchema(schema.properties.action_name, true, schema)).toEqual({
      mode: "reference",
      optional: false,
      refKind: "action",
      valueType: "string",
    });
    expect(parsePropertySchema(schema.properties.cluster_id, false, schema)).toMatchObject({
      mode: "reference",
      refKind: "cluster",
      valueType: "integer",
    });
  });

  it("searches, picks an existing row and saves the typed value", async () => {
    const resolver = resolverWith({
      action: [
        { value: "core.echo", label: "core.echo", detail: "core" },
        { value: "core.sleep", label: "core.sleep" },
      ],
      cluster: [{ value: "7", label: "lab-cluster" }],
    });
    const onSubmit = vi.fn();
    render(
      <ReferenceResolverProvider resolver={resolver}>
        <SchemaPropertyGridSurface
          syntheticFields={[
            { fieldName: "action_name", required: true },
            { fieldName: "cluster_id", required: false },
          ]}
          schema={schema}
          rootSchema={schema}
          initialDocument={{}}
          onSubmit={onSubmit}
        />
      </ReferenceResolverProvider>,
    );
    expect(document.querySelector("textarea")).toBeNull();
    const search = screen.getByLabelText("Search action_name");
    await act(async () => {
      fireEvent.change(search, { target: { value: "sleep" } });
    });
    await waitFor(() => {
      expect(resolver.search).toHaveBeenCalledWith("action", "sleep", { limit: 50 });
    });
    const select = screen.getByLabelText("action_name") as HTMLSelectElement;
    await waitFor(() => {
      expect(Array.from(select.options).map((o) => o.value)).toContain("core.sleep");
    });
    fireEvent.change(select, { target: { value: "core.sleep" } });

    const clusterSelect = screen.getByLabelText("cluster_id") as HTMLSelectElement;
    await waitFor(() => {
      expect(Array.from(clusterSelect.options).map((o) => o.value)).toContain("7");
    });
    fireEvent.change(clusterSelect, { target: { value: "7" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save instance" }));
    });
    expect(onSubmit).toHaveBeenCalledWith({ action_name: "core.sleep", cluster_id: 7 });
  });

  it("keeps an existing value selectable before the search returns it", async () => {
    const resolver = resolverWith({ action: [] });
    render(
      <ReferenceResolverProvider resolver={resolver}>
        <SchemaPropertyGridSurface
          syntheticFields={[{ fieldName: "action_name", required: true }]}
          schema={schema}
          rootSchema={schema}
          initialDocument={{ action_name: "core.legacy" }}
        />
      </ReferenceResolverProvider>,
    );
    const select = screen.getByLabelText("action_name") as HTMLSelectElement;
    await waitFor(() => expect(resolver.search).toHaveBeenCalled());
    expect(select.value).toBe("core.legacy");
  });

  it("reaches the resolver from a nested inspector and Escape closes only the innermost modal", async () => {
    const resolver = resolverWith({ event_type: [{ value: "sample.received", label: "sample.received" }] });
    render(
      <ReferenceResolverProvider resolver={resolver}>
        <SchemaPropertyGridSurface
          syntheticFields={[{ fieldName: "nested", required: false }]}
          schema={schema}
          rootSchema={schema}
          documentClassFqn="platform/Example"
          initialDocument={{}}
        />
      </ReferenceResolverProvider>,
    );
    fireEvent.click(screen.getByTestId("pi-open-nested"));
    const modal = await screen.findByTestId("property-inspector-modal");
    expect(modal.querySelector('[aria-current="location"]')?.textContent).toBe("nested");
    const select = (await screen.findByLabelText("event_type")) as HTMLSelectElement;
    await waitFor(() => {
      expect(Array.from(select.options).map((o) => o.value)).toContain("sample.received");
    });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByTestId("property-inspector-modal")).not.toBeInTheDocument();
    });
  });

  it("Escape in a second-level inspector returns to its parent inspector", async () => {
    const deep = {
      type: "object",
      properties: {
        outer: {
          type: "object",
          properties: { inner: { type: "object", properties: { note: { type: "string" } } } },
        },
      },
    };
    render(
      <SchemaPropertyGridSurface
        syntheticFields={[{ fieldName: "outer", required: false }]}
        schema={deep}
        rootSchema={deep}
        documentClassFqn="platform/Example"
        initialDocument={{}}
      />,
    );
    fireEvent.click(screen.getByTestId("pi-open-outer"));
    await screen.findByTestId("property-inspector-modal");
    fireEvent.click(await screen.findByTestId("pi-open-inner"));
    await waitFor(() => expect(screen.getAllByTestId("property-inspector-modal")).toHaveLength(2));
    expect(screen.getByRole("button", { name: "Back to outer" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getAllByTestId("property-inspector-modal")).toHaveLength(1));
  });
});
