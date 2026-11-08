import type { LucideIcon } from "lucide-react";
import { iconComponentForKey, type IconKey } from "../icons/allowlist.js";

export type PlatformIconProps = {
  iconKey: IconKey;
  /** Accessible name when rendered without visible text (e.g. tree-only). */
  title: string;
  size?: number;
  className?: string;
};

export function PlatformIcon({ iconKey, title, size = 18, className }: PlatformIconProps) {
  const Icon: LucideIcon = iconComponentForKey(iconKey);
  return (
    <Icon
      aria-hidden={false}
      role="img"
      aria-label={title}
      width={size}
      height={size}
      className={className ? `g-icon ${className}` : "g-icon"}
    />
  );
}
