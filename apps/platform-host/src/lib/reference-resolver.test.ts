import { describe, expect, it, vi } from "vitest";
import { createHostReferenceResolver, referenceSearchUrl } from "./reference-resolver";

describe("host reference resolver", () => {
  it("builds the search URL", () => {
    expect(referenceSearchUrl("event_type", "sample recv", 20)).toBe(
      "/api/portal/references?kind=event_type&q=sample+recv&limit=20",
    );
  });

  it("returns rows from the API", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ rows: [{ value: "a", label: "A", detail: null }] }), { status: 200 }),
    );
    const resolver = createHostReferenceResolver(fetchImpl as unknown as typeof fetch);
    await expect(resolver.search("action", "", { limit: 5 })).resolves.toEqual([
      { value: "a", label: "A", detail: null },
    ]);
    expect(fetchImpl).toHaveBeenCalledWith("/api/portal/references?kind=action&q=&limit=5", expect.anything());
  });

  it("surfaces API errors", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ error: "denied" }), { status: 403 }));
    const resolver = createHostReferenceResolver(fetchImpl as unknown as typeof fetch);
    await expect(resolver.search("cluster", "x")).rejects.toThrow("denied");
  });
});
