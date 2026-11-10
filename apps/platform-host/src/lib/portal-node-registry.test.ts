import { describe, expect, it } from "vitest";
import { nodePathFromUrlPathname, resolvePortalWorkspace } from "./portal-node-registry";

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
});

describe("nodePathFromUrlPathname", () => {
  it("strips query strings", () => {
    expect(nodePathFromUrlPathname("/app/meta?class=portal/NavNode")).toBe("/app/meta");
  });
});
