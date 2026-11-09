import { describe, expect, it } from "vitest";
import { resolveMetaEditorManifestKey } from "./resolve-meta-editor";

describe("resolveMetaEditorManifestKey", () => {
  const manifest = {
    "meta/BaseDocument": "ExampleStudyManifestEditor",
    "child_app/StudyManifest": "ExampleStudyManifestEditor",
  };

  it("prefers exact class key", () => {
    const resolved = resolveMetaEditorManifestKey(
      "child_app/StudyManifest",
      ["child_app/StudyManifest", "meta/BaseDocument"],
      manifest,
    );
    expect(resolved.resolution).toBe("exact");
    expect(resolved.manifestKey).toBe("ExampleStudyManifestEditor");
  });

  it("walks ancestry for override", () => {
    const resolved = resolveMetaEditorManifestKey(
      "child_app/EnrollmentRow",
      ["child_app/EnrollmentRow", "child_app/StudyManifest", "meta/BaseDocument"],
      manifest,
    );
    expect(resolved.resolution).toBe("ancestor");
    expect(resolved.matchedClassFqn).toBe("child_app/StudyManifest");
  });
});
