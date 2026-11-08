import { describe, expect, it } from "vitest";
import { PLATFORM_OBJECT_KINDS } from "../kinds.js";
import { FALLBACK_ICON_KEY, ICON_ALLOWLIST, isIconKey } from "./allowlist.js";
import { KIND_DEFAULT_ICON_KEYS } from "./kind-defaults.js";
import {
  everyKindHasAllowlistedDefault,
  resolvePresentation,
  validateClassIconOverrides,
} from "./resolve.js";

describe("icon allowlist", () => {
  it("has no dangling default keys", () => {
    for (const key of Object.values(KIND_DEFAULT_ICON_KEYS)) {
      expect(isIconKey(key)).toBe(true);
    }
    expect(isIconKey(FALLBACK_ICON_KEY)).toBe(true);
    for (const key of Object.keys(ICON_ALLOWLIST)) {
      expect(isIconKey(key)).toBe(true);
    }
  });

  it("every platform kind has a non-empty default", () => {
    expect(PLATFORM_OBJECT_KINDS.length).toBeGreaterThan(20);
    expect(everyKindHasAllowlistedDefault()).toBe(true);
    for (const kind of PLATFORM_OBJECT_KINDS) {
      const resolved = resolvePresentation({ kind });
      expect(resolved.iconKey).not.toBe("");
      expect(resolved.label.trim().length).toBeGreaterThan(0);
    }
  });
});

describe("class override resolution", () => {
  const overrides = {
    "meta/BaseDocument": "platform:document",
    "portal/Study": "platform:collection",
    "omics/SampleManifest": "platform:circuit",
  } as const;

  it("prefers exact class match", () => {
    const resolved = resolvePresentation({
      kind: "meta_object",
      classFqn: "portal/Study",
      classAncestry: ["portal/Study", "meta/BaseDocument"],
      classIconOverrides: overrides,
    });
    expect(resolved.iconKey).toBe("platform:collection");
    expect(resolved.resolution).toBe("class_exact");
  });

  it("walks nearest ancestor override", () => {
    const resolved = resolvePresentation({
      kind: "meta_object",
      classFqn: "omics/EnrollmentRow",
      classAncestry: ["omics/EnrollmentRow", "portal/Study", "meta/BaseDocument"],
      classIconOverrides: overrides,
    });
    expect(resolved.iconKey).toBe("platform:collection");
    expect(resolved.resolution).toBe("class_ancestor");
  });

  it("falls back to kind default when no override matches", () => {
    const resolved = resolvePresentation({
      kind: "workflow_definition",
      classFqn: "wf/CustomGraph",
      classAncestry: ["wf/CustomGraph"],
      classIconOverrides: overrides,
    });
    expect(resolved.iconKey).toBe(KIND_DEFAULT_ICON_KEYS.workflow_definition);
    expect(resolved.resolution).toBe("kind_default");
  });

  it("handles ancestry cycles safely", () => {
    const resolved = resolvePresentation({
      kind: "meta_class",
      classFqn: "A",
      classAncestry: ["A", "B", "A", "C"],
      classIconOverrides: { C: "meta:tree" },
    });
    expect(resolved.diagnostics.some((d) => d.includes("cycle"))).toBe(true);
    expect(resolved.iconKey).toBe(KIND_DEFAULT_ICON_KEYS.meta_class);
  });

  it("invalid explicit icon key uses unknown fallback", () => {
    const resolved = resolvePresentation({
      kind: "user",
      iconKey: "not-a-real-key",
    });
    expect(resolved.resolution).toBe("invalid_key_fallback");
    expect(isIconKey(resolved.iconKey)).toBe(true);
  });
});

describe("override manifest diagnostics", () => {
  it("reports invalid child registrations", () => {
    const report = validateClassIconOverrides({
      "portal/Study": "platform:collection",
      "": "meta:tree",
      "bad/Class": "invented:icon",
    });
    expect(report.valid).toHaveLength(1);
    expect(report.invalid).toHaveLength(2);
  });
});
