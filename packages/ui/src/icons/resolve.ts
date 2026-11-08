import {
  FIXTURE_DATA_PREFIX,
  KIND_DEFAULT_LABELS,
  PLATFORM_GENERIC_KIND,
  PLATFORM_OBJECT_KINDS,
  type PlatformObjectKind,
  type PresentationKind,
} from "../kinds.js";
import {
  FALLBACK_ICON_KEY,
  UNKNOWN_ICON_KEY,
  iconComponentForKey,
  isIconKey,
  type IconKey,
} from "./allowlist.js";
import { defaultIconKeyForKind } from "./kind-defaults.js";

export type ClassIconOverrideManifest = Readonly<Record<string, IconKey | string>>;

export type ResolvePresentationInput = {
  kind: PlatformObjectKind;
  /** Meta class FQN, e.g. `portal/NavNode`. */
  classFqn?: string | null;
  /**
   * Single-inheritance chain from the object's class upward (leaf → root).
   * Used for nearest-ancestor icon overrides and cycle detection.
   */
  classAncestry?: readonly string[];
  /** Optional explicit icon key from trusted UI metadata (not raw DB SVG). */
  iconKey?: string | null;
  /** Visible label; falls back to kind default label. */
  label?: string | null;
  /** Child build-time manifest (validated at registration). */
  classIconOverrides?: ClassIconOverrideManifest;
  /** When true, prefix label for fixture/demo rows. */
  fixture?: boolean;
};

export type ResolvedPresentation = {
  kind: PresentationKind;
  iconKey: IconKey;
  label: string;
  /** Why this icon was chosen (diagnostics for child manifests). */
  resolution: "explicit_key" | "class_exact" | "class_ancestor" | "kind_default" | "generic_fallback" | "invalid_key_fallback";
  diagnostics: string[];
};

export type OverrideRegistrationReport = {
  valid: Array<{ classFqn: string; iconKey: IconKey }>;
  invalid: Array<{ classFqn: string; iconKey: string; reason: string }>;
};

export function validateClassIconOverrides(
  manifest: ClassIconOverrideManifest | undefined,
): OverrideRegistrationReport {
  const valid: OverrideRegistrationReport["valid"] = [];
  const invalid: OverrideRegistrationReport["invalid"] = [];
  if (!manifest) {
    return { valid, invalid };
  }
  for (const [classFqn, iconKey] of Object.entries(manifest)) {
    const trimmed = classFqn.trim();
    if (!trimmed) {
      invalid.push({ classFqn, iconKey, reason: "empty class FQN" });
      continue;
    }
    if (!isIconKey(iconKey)) {
      invalid.push({ classFqn: trimmed, iconKey, reason: "icon key not in allowlist" });
      continue;
    }
    valid.push({ classFqn: trimmed, iconKey });
  }
  return { valid, invalid };
}

function sanitizeAncestry(chain: readonly string[] | undefined): {
  ordered: string[];
  cycleDetected: boolean;
  diagnostics: string[];
} {
  const diagnostics: string[] = [];
  if (!chain || chain.length === 0) {
    return { ordered: [], cycleDetected: false, diagnostics };
  }
  const seen = new Set<string>();
  const ordered: string[] = [];
  let cycleDetected = false;
  for (const raw of chain) {
    const fqn = raw.trim();
    if (!fqn) {
      diagnostics.push("skipped empty ancestor in chain");
      continue;
    }
    if (seen.has(fqn)) {
      cycleDetected = true;
      diagnostics.push(`cycle detected at ${fqn}; truncating ancestry walk`);
      break;
    }
    seen.add(fqn);
    ordered.push(fqn);
  }
  return { ordered, cycleDetected, diagnostics };
}

function resolveClassOverrideIconKey(
  classFqn: string | null | undefined,
  ancestry: readonly string[],
  overrides: ClassIconOverrideManifest | undefined,
): { key: IconKey | null; resolution: ResolvedPresentation["resolution"]; diagnostics: string[] } {
  const diagnostics: string[] = [];
  if (!overrides) {
    return { key: null, resolution: "kind_default", diagnostics };
  }

  const candidates = [classFqn?.trim(), ...ancestry].filter((v): v is string => Boolean(v));
  const visited = new Set<string>();
  for (const fqn of candidates) {
    if (visited.has(fqn)) {
      diagnostics.push(`duplicate class FQN in override walk: ${fqn}`);
      continue;
    }
    visited.add(fqn);
    const raw = overrides[fqn];
    if (raw == null) {
      continue;
    }
    if (!isIconKey(raw)) {
      diagnostics.push(`invalid override icon key for ${fqn}: ${raw}`);
      continue;
    }
    const resolution = fqn === classFqn?.trim() ? "class_exact" : "class_ancestor";
    return { key: raw, resolution, diagnostics };
  }
  return { key: null, resolution: "kind_default", diagnostics };
}

export function resolvePresentation(input: ResolvePresentationInput): ResolvedPresentation {
  const diagnostics: string[] = [];
  const { ordered: ancestry, cycleDetected, diagnostics: ancestryDiag } = sanitizeAncestry(input.classAncestry);
  diagnostics.push(...ancestryDiag);
  if (cycleDetected) {
    diagnostics.push("using kind default after ancestry cycle");
  }

  const baseLabel = (input.label?.trim() || KIND_DEFAULT_LABELS[input.kind]).trim();
  const label = input.fixture ? `${FIXTURE_DATA_PREFIX} ${baseLabel}` : baseLabel;

  if (input.iconKey != null && input.iconKey !== "") {
    if (isIconKey(input.iconKey)) {
      return {
        kind: input.kind,
        iconKey: input.iconKey,
        label,
        resolution: "explicit_key",
        diagnostics,
      };
    }
    diagnostics.push(`invalid explicit icon key: ${input.iconKey}`);
    return {
      kind: input.kind,
      iconKey: UNKNOWN_ICON_KEY,
      label,
      resolution: "invalid_key_fallback",
      diagnostics,
    };
  }

  const classOverride = resolveClassOverrideIconKey(input.classFqn, ancestry, input.classIconOverrides);
  diagnostics.push(...classOverride.diagnostics);
  if (classOverride.key) {
    return {
      kind: input.kind,
      iconKey: classOverride.key,
      label,
      resolution: classOverride.resolution,
      diagnostics,
    };
  }

  const kindKey = defaultIconKeyForKind(input.kind);
  if (!isIconKey(kindKey)) {
    diagnostics.push(`kind default mapped to missing allowlist entry: ${kindKey}`);
    return {
      kind: PLATFORM_GENERIC_KIND,
      iconKey: FALLBACK_ICON_KEY,
      label,
      resolution: "generic_fallback",
      diagnostics,
    };
  }

  return {
    kind: input.kind,
    iconKey: kindKey,
    label,
    resolution: "kind_default",
    diagnostics,
  };
}

/** Returns true when every platform kind default icon key exists in the allowlist. */
export function everyKindHasAllowlistedDefault(): boolean {
  for (const kind of PLATFORM_OBJECT_KINDS) {
    const key = defaultIconKeyForKind(kind);
    if (!isIconKey(key)) {
      return false;
    }
    void iconComponentForKey(key);
  }
  void iconComponentForKey(FALLBACK_ICON_KEY);
  void iconComponentForKey(UNKNOWN_ICON_KEY);
  return true;
}
