import type { PlatformObjectKind } from "../kinds.js";
import { resolvePresentation, type ClassIconOverrideManifest } from "../icons/resolve.js";
import { PlatformIcon } from "./PlatformIcon.js";

export type ObjectBadgeProps = {
  kind: PlatformObjectKind;
  label?: string | null;
  classFqn?: string | null;
  classAncestry?: readonly string[];
  iconKey?: string | null;
  classIconOverrides?: ClassIconOverrideManifest;
  fixture?: boolean;
  /** Secondary line (e.g. FQN or request code). */
  subtitle?: string | null;
};

/**
 * Icon plus visible label — never renders without both accessible name and icon glyph.
 */
export function ObjectBadge({
  kind,
  label,
  classFqn,
  classAncestry,
  iconKey,
  classIconOverrides,
  fixture,
  subtitle,
}: ObjectBadgeProps) {
  const resolved = resolvePresentation({
    kind,
    label,
    classFqn,
    classAncestry,
    iconKey,
    classIconOverrides,
    fixture,
  });

  return (
    <span className="g-object-badge" data-kind={resolved.kind} data-icon-key={resolved.iconKey}>
      <PlatformIcon iconKey={resolved.iconKey} title={resolved.label} className="g-object-badge__icon" />
      <span className="g-object-badge__text">
        <span className="g-object-badge__label">{resolved.label}</span>
        {subtitle ? <span className="g-object-badge__subtitle">{subtitle}</span> : null}
      </span>
    </span>
  );
}
