import { describe, expect, it, vi } from "vitest";
import { createPlatformBffClient } from "./transport.js";
import { SessionTransportError } from "./session.js";

describe("createPlatformBffClient", () => {
  it("returns null session on 401", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    const client = createPlatformBffClient({ fetchFn });
    await expect(client.getSession()).resolves.toBeNull();
  });

  it("maps navigation JSON with presentation kind fallback", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          nodes: [
            {
              nodeId: 1,
              parentId: null,
              caption: "Home",
              seq: 1,
              presentationKind: "not-a-real-kind",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = createPlatformBffClient({ fetchFn });
    const nodes = await client.getOperatorNavigation();
    expect(nodes[0]?.presentationKind).toBe("platform_generic" as const);
  });

  it("throws SessionTransportError when navigation is forbidden", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "session denied" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = createPlatformBffClient({ fetchFn });
    await expect(client.getOperatorNavigation()).rejects.toBeInstanceOf(SessionTransportError);
  });
});
