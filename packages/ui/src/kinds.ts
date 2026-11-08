/**
 * Stable platform object kind ids for presentation (icons, labels).
 * These are UI vocabulary — not database status enums.
 */
export const PLATFORM_OBJECT_KINDS = [
  "user",
  "role",
  "permission",
  "organization",
  "meta_class",
  "meta_object",
  "meta_field",
  "meta_relation",
  "meta_tree",
  "semantic_entity",
  "semantic_attribute",
  "semantic_request",
  "workflow_action",
  "workflow_definition",
  "workflow_run",
  "workflow_step",
  "domain_program",
  "artifact",
  "event",
  "subscription",
  "schedule",
  "view",
  "dashboard",
  "config",
] as const;

export type PlatformObjectKind = (typeof PLATFORM_OBJECT_KINDS)[number];

export const PLATFORM_GENERIC_KIND = "platform_generic" as const;

export type PresentationKind = PlatformObjectKind | typeof PLATFORM_GENERIC_KIND;

export const KIND_DEFAULT_LABELS: Record<PresentationKind, string> = {
  user: "User",
  role: "Role",
  permission: "Permission",
  organization: "Organization",
  meta_class: "Class",
  meta_object: "Object",
  meta_field: "Field",
  meta_relation: "Relation",
  meta_tree: "Tree",
  semantic_entity: "Semantic entity",
  semantic_attribute: "Attribute",
  semantic_request: "Semantic request",
  workflow_action: "Workflow action",
  workflow_definition: "Workflow definition",
  workflow_run: "Workflow run",
  workflow_step: "Workflow step",
  domain_program: "Domain program",
  artifact: "Artifact",
  event: "Event",
  subscription: "Subscription",
  schedule: "Schedule",
  view: "View",
  dashboard: "Dashboard",
  config: "Configuration",
  platform_generic: "Platform object",
};

/** Human-readable fixture prefix — marks demo/sample data in UI. */
export const FIXTURE_DATA_PREFIX = "[Fixture]";
