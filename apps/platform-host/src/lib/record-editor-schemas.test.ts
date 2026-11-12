import { describe, expect, it } from "vitest";
import { editableDocument, mergeIdentityForSave, RECORD_EDITORS } from "./record-editor-schemas";
import { recordsUrl } from "./record-editor-client";

describe("record editor schemas", () => {
  it("never exposes free-form object fields", () => {
    const walk = (node: unknown, path: string) => {
      if (!node || typeof node !== "object") return;
      const n = node as Record<string, unknown>;
      if (n.type === "object") {
        expect(n.properties, `${path} must declare properties`).toBeTruthy();
      }
      for (const [k, v] of Object.entries((n.properties ?? {}) as Record<string, unknown>)) walk(v, `${path}.${k}`);
      if (n.items) walk(n.items, `${path}[]`);
    };
    for (const def of Object.values(RECORD_EDITORS)) {
      walk(def.createSchema, `${def.entity}.create`);
      walk(def.editSchema, `${def.entity}.edit`);
    }
  });

  it("uses reference pickers for foreign keys", () => {
    const sub = RECORD_EDITORS.event_subscription.createSchema.properties as Record<string, Record<string, unknown>>;
    expect(sub.event_type["x-goliath-ref"]).toBe("event_type");
    expect(sub.workflow_version_id["x-goliath-ref"]).toBe("workflow_version");
    const enr = RECORD_EDITORS.worker_enrollment.createSchema.properties as Record<string, Record<string, unknown>>;
    expect(enr.cluster_key["x-goliath-ref"]).toBe("cluster");
  });

  it("builds row keys", () => {
    expect(RECORD_EDITORS.domain_program.rowKey({ name: "p", version: "2" })).toBe("p@2");
    expect(RECORD_EDITORS.worker_enrollment.rowKey({ cluster_key: "c", external_worker_key: "w" })).toBe("c/w");
  });

  it("keeps identity on save and strips read-only keys", () => {
    expect(mergeIdentityForSave("cluster", "c1", { cluster_key: "c1" }, { name: "n" })).toEqual({
      name: "n",
      cluster_key: "c1",
    });
    expect(mergeIdentityForSave("cluster", null, null, { cluster_key: "x" })).toEqual({ cluster_key: "x" });
    expect(
      editableDocument(RECORD_EDITORS.cluster.editSchema, { name: "n", cluster_key: "c", worker_count: 3, status: null }),
    ).toEqual({ name: "n" });
  });

  it("encodes urls", () => {
    expect(recordsUrl("domain_program", "/item", "a b@1")).toBe("/api/portal/records/domain_program/item?key=a%20b%401");
  });
});
