export {
  FIXTURE_DATA_PREFIX,
  KIND_DEFAULT_LABELS,
  PLATFORM_GENERIC_KIND,
  PLATFORM_OBJECT_KINDS,
  type PlatformObjectKind,
  type PresentationKind,
} from "./kinds.js";

export {
  FALLBACK_ICON_KEY,
  ICON_ALLOWLIST,
  UNKNOWN_ICON_KEY,
  iconComponentForKey,
  isIconKey,
  type IconKey,
} from "./icons/allowlist.js";

export { GENERIC_KIND_ICON_KEY, KIND_DEFAULT_ICON_KEYS, defaultIconKeyForKind } from "./icons/kind-defaults.js";

export {
  everyKindHasAllowlistedDefault,
  resolvePresentation,
  validateClassIconOverrides,
  type ClassIconOverrideManifest,
  type OverrideRegistrationReport,
  type ResolvePresentationInput,
  type ResolvedPresentation,
} from "./icons/resolve.js";

export { ObjectBadge, type ObjectBadgeProps } from "./components/ObjectBadge.js";
export { PlatformIcon, type PlatformIconProps } from "./components/PlatformIcon.js";
