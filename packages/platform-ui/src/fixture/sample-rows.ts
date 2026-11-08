import type { PlatformObjectKind } from "@goliath/ui";

export type FixtureRow = {
  id: string;
  kind: PlatformObjectKind;
  label: string;
  subtitle?: string;
  classFqn?: string;
  classAncestry?: string[];
};

/** Clearly labeled fixture data for P0 demos and tests — not production records. */
export const FIXTURE_PLATFORM_ROWS: FixtureRow[] = [
  { id: "u1", kind: "user", label: "Operator A" },
  { id: "r1", kind: "role", label: "PortalAdmin" },
  { id: "p1", kind: "permission", label: "semantic.restricted.probe" },
  { id: "o1", kind: "organization", label: "Core tenancy org" },
  { id: "c1", kind: "meta_class", label: "portal/NavNode", classFqn: "portal/NavNode" },
  {
    id: "obj1",
    kind: "meta_object",
    label: "Studies root nav",
    classFqn: "portal/NavNode",
    classAncestry: ["portal/NavNode", "meta/BaseNode"],
  },
  { id: "f1", kind: "meta_field", label: "Parent TreeRef" },
  { id: "rel1", kind: "meta_relation", label: "Parent link" },
  { id: "t1", kind: "meta_tree", label: "Navigation tree" },
  { id: "se1", kind: "semantic_entity", label: "organization", subtitle: "core.organization" },
  { id: "sa1", kind: "semantic_attribute", label: "name", subtitle: "filterable" },
  { id: "sr1", kind: "semantic_request", label: "List organizations", subtitle: "core.list_organizations" },
  { id: "wa1", kind: "workflow_action", label: "goliath.workflow.finalize", subtitle: "DOMAIN" },
  { id: "wd1", kind: "workflow_definition", label: "SamplePrepPipeline" },
  { id: "wr1", kind: "workflow_run", label: "Instance #1042" },
  { id: "ws1", kind: "workflow_step", label: "ALIGNMENT_QC" },
  { id: "dp1", kind: "domain_program", label: "ingest_fastq" },
  { id: "ar1", kind: "artifact", label: "BAM output" },
  { id: "ev1", kind: "event", label: "workflow.instance.started" },
  { id: "sub1", kind: "subscription", label: "worker.wake" },
  { id: "sch1", kind: "schedule", label: "nightly drain" },
  { id: "v1", kind: "view", label: "Ops instances" },
  { id: "d1", kind: "dashboard", label: "Home board" },
  { id: "cfg1", kind: "config", label: "site.default" },
];

export type FixtureTreeNode = {
  id: string;
  kind: PlatformObjectKind;
  label: string;
  children?: FixtureTreeNode[];
};

export const FIXTURE_NAV_TREE: FixtureTreeNode = {
  id: "root",
  kind: "meta_tree",
  label: "Platform navigation (fixture)",
  children: [
    {
      id: "admin",
      kind: "role",
      label: "Administration",
      children: [
        { id: "users", kind: "user", label: "Users" },
        { id: "roles", kind: "role", label: "Roles" },
        { id: "perms", kind: "permission", label: "Permissions" },
      ],
    },
    {
      id: "wf",
      kind: "workflow_definition",
      label: "Workflows",
      children: [
        { id: "defs", kind: "workflow_definition", label: "Definitions" },
        { id: "runs", kind: "workflow_run", label: "Runs" },
        { id: "acts", kind: "workflow_action", label: "Actions" },
      ],
    },
    {
      id: "sem",
      kind: "semantic_entity",
      label: "Semantic layer",
      children: [
        { id: "ent", kind: "semantic_entity", label: "Entities" },
        { id: "req", kind: "semantic_request", label: "Requests" },
      ],
    },
  ],
};
