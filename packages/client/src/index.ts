/**
 * P0: presentation and manifest contracts only. Authenticated transport lands in P1
 * (`portal.sp_session_*` — no invented HTTP shapes).
 */
export type {
  ClassIconOverrideManifest,
  PlatformObjectKind,
  PresentationKind,
} from "@goliath/ui";

import { validateClassIconOverrides, type OverrideRegistrationReport } from "@goliath/ui";

export { validateClassIconOverrides, type OverrideRegistrationReport };

/** Build-time hook: child apps export this shape from their UI manifest module. */
export type GoliathUiManifest = {
  appId: string;
  classIconOverrides?: Record<string, string>;
  /**
   * Stable editor keys bound to React components in the child bundle (no Python→React loading).
   * Values are opaque ids validated at child compile time.
   */
  editorComponents?: Record<string, string>;
};

export function diagnoseUiManifest(manifest: GoliathUiManifest): OverrideRegistrationReport {
  return validateClassIconOverrides(manifest.classIconOverrides);
}
