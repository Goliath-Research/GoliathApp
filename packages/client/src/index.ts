/**
 * P1: same-origin BFF transport types aligned with `portal.sp_session_*` and
 * `portal.sp_session_operator_nav_tree` (host implements HTTP; DB contract is SQL).
 */
export type {
  ClassIconOverrideManifest,
  PlatformObjectKind,
  PresentationKind,
} from "@goliath/ui";

import { validateClassIconOverrides, type OverrideRegistrationReport } from "@goliath/ui";

export { validateClassIconOverrides, type OverrideRegistrationReport };

export type { PlatformSessionSnapshot, SessionTransportErrorCode } from "./session.js";
export { SessionTransportError } from "./session.js";
export type { OperatorNavNode } from "./nav.js";
export { coercePresentationKind } from "./nav.js";
export { createPlatformBffClient, type PlatformBffClient, type PlatformBffClientOptions } from "./transport.js";
export type { ChildHostExtension, ChildHostNavLeaf } from "./child-host.js";
export type { MetaClassSummary, MetaClassLineageNode, MetaClassField } from "./meta.js";
export type { PlatformAuthMethodKind, PublicAuthProvider, ChildAuthProviderRegistration } from "./auth.js";
export type { GoliathUiManifest } from "./manifest.js";

import type { GoliathUiManifest } from "./manifest.js";

export function diagnoseUiManifest(manifest: GoliathUiManifest): OverrideRegistrationReport {
  return validateClassIconOverrides(manifest.classIconOverrides);
}
