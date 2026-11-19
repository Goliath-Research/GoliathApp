import { describe, expect, it } from "vitest";
import { navChildrenOf, nodePathFromUrlPathname, resolvePortalWorkspace } from "./portal-node-registry";

describe("resolvePortalWorkspace", () => {
  it("maps meta nodes to hierarchy or workbench", () => {
    expect(resolvePortalWorkspace("/app").kind).toBe("meta_home");
    expect(resolvePortalWorkspace("/app/meta/classes").kind).toBe("meta_class_catalog");
    expect(resolvePortalWorkspace("/app/meta/objects").kind).toBe("meta_workbench");
  });

  it("maps views nodes to operator define/arrange surfaces", () => {
    expect(resolvePortalWorkspace("/app/views/list").kind).toBe("operator_views");
    expect(resolvePortalWorkspace("/app/views/dashboards").kind).toBe("operator_dashboards");
  });

  it("maps admin organizations to semantic list", () => {
    expect(resolvePortalWorkspace("/app/admin/organizations").semanticRequest).toBe("core.list_organizations");
  });

  it("maps semantic and navigation admin to authoring workspaces", () => {
    expect(resolvePortalWorkspace("/app/semantic").kind).toBe("semantic_authoring");
    expect(resolvePortalWorkspace("/app/admin/navigation").kind).toBe("admin_grants");
  });

  it("maps RBAC admin routes to security workspaces", () => {
    expect(resolvePortalWorkspace("/app/admin/users").kind).toBe("admin_users");
    expect(resolvePortalWorkspace("/app/admin/roles").kind).toBe("admin_roles");
    expect(resolvePortalWorkspace("/app/admin/permissions").kind).toBe("admin_permissions");
  });

  it("falls back to Meta workbench when NavTree uses meta_object + platform.nav.meta_object:class", () => {
    const spec = resolvePortalWorkspace("/app/childapp/samples", {
      presentationKind: "meta_object",
      infoName: "platform.nav.meta_object:childapp/Sample",
    });
    expect(spec.kind).toBe("meta_workbench");
    expect(spec.metaClass).toBe("childapp/Sample");
  });

  it("prefers explicit PATH_SPECS over NavTree meta_object hints", () => {
    const spec = resolvePortalWorkspace("/app/meta/objects", {
      presentationKind: "meta_object",
      infoName: "platform.nav.meta_object:childapp/Sample",
    });
    expect(spec.kind).toBe("meta_workbench");
    expect(spec.metaClass).toBe("portal/NavNode");
  });
});

describe("parent routes, unknown paths, and Meta member routes", () => {
  it("turns section parents into indexes", () => {
    for (const p of ["/app/admin", "/app/workflows", "/app/config", "/app/operations", "/app/inv"]) {
      expect(resolvePortalWorkspace(p).kind).toBe("route_index");
    }
  });

  it("explains extension for an unknown path", () => {
    expect(resolvePortalWorkspace("/app/childapp/unknown").kind).toBe("extension_help");
  });

  it("opens methods in the class-method editor and fields/relations in the class catalog", () => {
    const methods = resolvePortalWorkspace("/app/meta/methods");
    expect(methods.kind).toBe("record_editor");
    expect(methods.recordEntities).toEqual(["class_method"]);
    expect(resolvePortalWorkspace("/app/meta/fields").kind).toBe("meta_class_catalog");
    expect(resolvePortalWorkspace("/app/meta/relations").kind).toBe("meta_class_catalog");
  });

  it("lists direct NavTree children in menu order", () => {
    const rows = [
      { nodeId: 1, parentId: null, caption: "App", seq: 0, nodePath: "/app" },
      { nodeId: 2, parentId: 1, caption: "Workflows", seq: 1, nodePath: "/app/workflows" },
      { nodeId: 3, parentId: 2, caption: "Runs", seq: 2, nodePath: "/app/workflows/runs" },
      { nodeId: 4, parentId: 2, caption: "Definitions", seq: 1, nodePath: "/app/workflows/definitions" },
      { nodeId: 5, parentId: 3, caption: "Deep", seq: 0, nodePath: "/app/workflows/runs/deep" },
    ];
    expect(navChildrenOf(rows, "/app/workflows/").map((r) => r.caption)).toEqual(["Definitions", "Runs"]);
    expect(navChildrenOf(rows, "/app/missing")).toEqual([]);
  });
});

describe("nodePathFromUrlPathname", () => {
  it("strips query strings", () => {
    expect(nodePathFromUrlPathname("/app/meta?class=portal/NavNode")).toBe("/app/meta");
  });
});
