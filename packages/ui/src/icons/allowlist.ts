import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Box,
  Boxes,
  Braces,
  Building2,
  CalendarClock,
  CircleDot,
  CircuitBoard,
  Cog,
  FileBox,
  GitBranch,
  KeyRound,
  LayoutDashboard,
  LayoutList,
  Link2,
  ListTree,
  PlayCircle,
  Radar,
  ScrollText,
  Shapes,
  Shield,
  Sparkles,
  SquareStack,
  TableProperties,
  TreePine,
  UserRound,
  Waypoints,
  Workflow,
  Zap,
} from "lucide-react";

/**
 * Allowlisted icon keys → Lucide components (ISC). No runtime SVG from the database.
 */
export const ICON_ALLOWLIST = {
  "platform:generic": Sparkles,
  "platform:unknown": CircleDot,
  "identity:user": UserRound,
  "identity:role": Shield,
  "identity:permission": KeyRound,
  "identity:organization": Building2,
  "meta:class": Shapes,
  "meta:object": Box,
  "meta:field": TableProperties,
  "meta:relation": Link2,
  "meta:tree": TreePine,
  "semantic:entity": SquareStack,
  "semantic:attribute": ListTree,
  "semantic:request": Radar,
  "workflow:action": Zap,
  "workflow:definition": Workflow,
  "workflow:run": PlayCircle,
  "workflow:step": Waypoints,
  "workflow:domain_program": Braces,
  "workflow:artifact": FileBox,
  "platform:event": Activity,
  "platform:subscription": GitBranch,
  "platform:schedule": CalendarClock,
  "platform:view": LayoutList,
  "platform:dashboard": LayoutDashboard,
  "platform:config": Cog,
  "platform:circuit": CircuitBoard,
  "platform:collection": Boxes,
  "platform:document": ScrollText,
} as const satisfies Record<string, LucideIcon>;

export type IconKey = keyof typeof ICON_ALLOWLIST;

export const FALLBACK_ICON_KEY: IconKey = "platform:generic";
export const UNKNOWN_ICON_KEY: IconKey = "platform:unknown";

export function isIconKey(value: string): value is IconKey {
  return Object.prototype.hasOwnProperty.call(ICON_ALLOWLIST, value);
}

export function iconComponentForKey(key: IconKey): LucideIcon {
  return ICON_ALLOWLIST[key];
}
