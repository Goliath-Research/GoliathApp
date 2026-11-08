import type { PlatformObjectKind, PresentationKind } from "../kinds.js";
import { FALLBACK_ICON_KEY, type IconKey } from "./allowlist.js";

/** Deterministic default icon per platform object kind — never empty. */
export const KIND_DEFAULT_ICON_KEYS: Record<PlatformObjectKind, IconKey> = {
  user: "identity:user",
  role: "identity:role",
  permission: "identity:permission",
  organization: "identity:organization",
  meta_class: "meta:class",
  meta_object: "meta:object",
  meta_field: "meta:field",
  meta_relation: "meta:relation",
  meta_tree: "meta:tree",
  semantic_entity: "semantic:entity",
  semantic_attribute: "semantic:attribute",
  semantic_request: "semantic:request",
  workflow_action: "workflow:action",
  workflow_definition: "workflow:definition",
  workflow_run: "workflow:run",
  workflow_step: "workflow:step",
  domain_program: "workflow:domain_program",
  artifact: "workflow:artifact",
  event: "platform:event",
  subscription: "platform:subscription",
  schedule: "platform:schedule",
  view: "platform:view",
  dashboard: "platform:dashboard",
  config: "platform:config",
};

export const GENERIC_KIND_ICON_KEY: IconKey = FALLBACK_ICON_KEY;

export function defaultIconKeyForKind(kind: PresentationKind): IconKey {
  if (kind === "platform_generic") {
    return GENERIC_KIND_ICON_KEY;
  }
  return KIND_DEFAULT_ICON_KEYS[kind];
}
