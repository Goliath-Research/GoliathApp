/** Keys passed to portal session list wrappers in bridge.ts */
export const PLATFORM_QUERY_SQL: Record<
  string,
  { sql: string; columns: { key: string; label: string }[] }
> = {
  users: {
    sql: `SELECT * FROM portal.sp_session_list_users($1, false)`,
    columns: [
      { key: "user_id", label: "User ID" },
      { key: "full_name", label: "Name" },
      { key: "email", label: "Email" },
      { key: "active", label: "Active" },
    ],
  },
  roles: {
    sql: `SELECT * FROM portal.sp_session_list_roles($1)`,
    columns: [
      { key: "role_id", label: "Role ID" },
      { key: "name", label: "Name" },
      { key: "bypass_scope", label: "Bypass scope" },
    ],
  },
  permissions: {
    sql: `SELECT * FROM portal.sp_session_list_permissions($1, NULL)`,
    columns: [
      { key: "permission_id", label: "ID" },
      { key: "name", label: "Name" },
      { key: "role_id", label: "Role ID" },
    ],
  },
  scopes: {
    sql: `SELECT * FROM portal.sp_session_list_scopes($1, false)`,
    columns: [
      { key: "scope_id", label: "Scope ID" },
      { key: "scope_type", label: "Type" },
      { key: "name", label: "Name" },
      { key: "organization_id", label: "Organization" },
      { key: "active", label: "Active" },
    ],
  },
  invitations: {
    sql: `SELECT * FROM portal.sp_session_list_invitations($1, NULL, NULL)`,
    columns: [
      { key: "invitation_id", label: "ID" },
      { key: "email", label: "Email" },
      { key: "status", label: "Status" },
      { key: "scope_id", label: "Scope" },
      { key: "expires_at_utc", label: "Expires" },
    ],
  },
  workflow_defs: {
    sql: `SELECT * FROM portal.sp_session_list_workflow_defs($1, NULL)`,
    columns: [
      { key: "workflow_def_id", label: "Def ID" },
      { key: "name", label: "Name" },
      { key: "source", label: "Source" },
      { key: "version_major", label: "Major" },
      { key: "version_minor", label: "Minor" },
    ],
  },
  workflow_runs: {
    sql: `SELECT * FROM portal.sp_session_list_recent_instances($1, 168, 200)`,
    columns: [
      { key: "instance_id", label: "Instance" },
      { key: "workflow_def_name", label: "Workflow" },
      { key: "status", label: "Status" },
      { key: "study_name", label: "Study" },
      { key: "started_at_utc", label: "Started" },
    ],
  },
  workflow_actions: {
    sql: `SELECT * FROM portal.sp_session_list_workflow_actions($1)`,
    columns: [
      { key: "action_name", label: "Action" },
      { key: "capability", label: "Capability" },
      { key: "implementation_status", label: "Status" },
    ],
  },
  workflow_steps: {
    sql: `SELECT * FROM portal.sp_session_list_workflow_step_nodes($1)`,
    columns: [
      { key: "workflow_def_name", label: "Workflow" },
      { key: "node_key", label: "Node" },
      { key: "node_type", label: "Type" },
      { key: "action_name", label: "Action" },
    ],
  },
  domain_programs: {
    sql: `SELECT * FROM portal.sp_session_list_domain_programs($1, false)`,
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
    ],
  },
  worker_enrollments: {
    sql: `SELECT * FROM portal.sp_session_list_worker_enrollments($1, NULL)`,
    columns: [
      { key: "cluster_key", label: "Cluster" },
      { key: "external_worker_key", label: "Worker key" },
      { key: "status", label: "Status" },
    ],
  },
  event_subscriptions: {
    sql: `SELECT * FROM portal.sp_session_list_event_subscriptions($1)`,
    columns: [
      { key: "event_type_name", label: "Event type" },
      { key: "workflow_def_name", label: "Workflow" },
      { key: "mode", label: "Mode" },
      { key: "enabled", label: "Enabled" },
    ],
  },
  sites: {
    sql: `SELECT * FROM portal.sp_session_list_sites($1)`,
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
    ],
  },
  pipeline_profiles: {
    sql: `SELECT * FROM portal.sp_session_list_pipeline_profiles($1, false)`,
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
    ],
  },
  data_types: {
    sql: `SELECT * FROM portal.sp_session_list_data_types($1, true)`,
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
      { key: "kind", label: "Kind" },
    ],
  },
  semantic_namespaces: {
    sql: `SELECT * FROM portal.sp_session_list_semantic_namespaces($1)`,
    columns: [
      { key: "code", label: "Code" },
      { key: "display_name", label: "Display name" },
      { key: "owner_app", label: "Owner app" },
    ],
  },
  semantic_attributes: {
    sql: `SELECT * FROM portal.sp_session_list_semantic_attributes($1, NULL)`,
    columns: [
      { key: "entity_id", label: "Entity ID" },
      { key: "code", label: "Code" },
      { key: "column_name", label: "Column" },
      { key: "json_type", label: "JSON type" },
      { key: "role", label: "Role" },
    ],
  },
  semantic_requests: {
    sql: `SELECT * FROM portal.sp_session_list_semantic_requests($1)`,
    columns: [
      { key: "request_code", label: "Request" },
      { key: "namespace", label: "Namespace" },
      { key: "entity_code", label: "Entity" },
      { key: "display_name", label: "Title" },
    ],
  },
  recent_events: {
    sql: `SELECT * FROM portal.sp_session_list_recent_events($1, 100)`,
    columns: [
      { key: "event_type_name", label: "Type" },
      { key: "source", label: "Source" },
      { key: "occurred_at_utc", label: "Occurred" },
    ],
  },
  schedule_nodes: {
    sql: `SELECT * FROM portal.sp_session_list_schedule_nodes($1)`,
    columns: [
      { key: "workflow_def_name", label: "Workflow" },
      { key: "node_key", label: "Schedule node" },
      { key: "schedule_interval_seconds", label: "Interval (s)" },
    ],
  },
  worker_health: {
    sql: `SELECT * FROM portal.sp_session_list_worker_health($1, NULL)`,
    columns: [
      { key: "cluster_key", label: "Cluster" },
      { key: "display_name", label: "Worker" },
      { key: "status", label: "Status" },
      { key: "last_seen_at_utc", label: "Last seen" },
    ],
  },
};
