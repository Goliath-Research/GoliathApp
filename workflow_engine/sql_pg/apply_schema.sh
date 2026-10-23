#!/usr/bin/env bash
# Apply GoliathApp PostgreSQL schema (ordered SCRIPTS list).
#
# Prerequisites:
#   - psql (PostgreSQL client 15+; 17+ recommended)
#   - libpq connection settings (see below)
#
# Example:
#   export PGHOST=localhost
#   export PGPORT=5432
#   export PGDATABASE=goliath
#   export PGUSER=postgres
#   export PGPASSWORD='...'
#   export PGSSLMODE=prefer
#   ./apply_schema.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

: "${PGHOST:?Set PGHOST (libpq host)}"
export PGPORT="${PGPORT:-5432}"
: "${PGDATABASE:?Set PGDATABASE (libpq database name)}"
: "${PGUSER:?Set PGUSER (libpq user)}"
export PGSSLMODE="${PGSSLMODE:-prefer}"

if [[ -z "${PGPASSWORD:-}" && -z "${PGPASSFILE:-}" ]]; then
  echo "Set PGPASSWORD or PGPASSFILE for database authentication." >&2
  exit 1
fi

SCRIPTS=(
  00_schema.sql
  wf_instance_extension.sql
  wf_json_column_alignment.sql
  03_engine_core.sql
  05_runtime_parity.sql
  06_scope_writepath_parity.sql
  07_scope_encoding_parity.sql
  08_foreach_support.sql
  wf_reclaim_expired_leases.sql
  wf_worker_desired_state.sql
  02_repository_api.sql
  wf_action_schema.sql
  wf_repo_upsert_workflow_action.sql
  wf_action_dispatch_metadata.sql
  wf_action_dispatch_concurrency.sql
  wf_action_dispatch_affinity.sql
  wf_data_type.sql
  01_worker_api.sql
  wf_cluster_security_columns.sql
  wf_worker_enrollment.sql
  portal_worker_enrollment_api.sql
  wf_apply_validation_plan.sql
  wf_execution_scope.sql
  04_admin.sql
  wf_repo_create_workflow_graph.sql
  wf_sql_collection_bindings.sql
  portal_workflow_api.sql
  wf_drop_platform_sample_storage.sql
  meta_schema.sql
  rbac_schema.sql
  contract_schema.sql
  onboarding_schema.sql
  portal_shell_schema.sql
  portal_organization_schema.sql
  legacy_cross_schema_fks.sql
  cfg_schema.sql
  cfg_registry_tables.sql
  cfg_wf_relationships.sql
  cfg_analyte_schema.sql
  cfg_repo_api.sql
  portal_resource_profile.sql
  cfg_portal_api.sql
  portal_sample_extras_schema.sql
  cfg_process_pack_catalog.sql
  cfg_assay_procedure_links.sql
  cfg_hyperparameter_search.sql
  portal_modern_api_parity.sql
  rbac_api_parity.sql
  meta_api_parity.sql
  contract_api_parity.sql
  onboarding_api_parity.sql
  portal_study_pipeline_api.sql
  portal_ops_recovery_api.sql
  portal_rbac_api.sql
  portal_contract_api.sql
  portal_study_ops_api.sql
  portal_guardrails_editor.sql
  cfg_study_start_request.sql
  wf_event_plane.sql
)

echo "Target: host=$PGHOST db=$PGDATABASE user=$PGUSER sslmode=$PGSSLMODE"

echo "Preflight..."
psql -q -v ON_ERROR_STOP=1 -c "SELECT current_user, current_database(), version();"

for name in "${SCRIPTS[@]}"; do
  path="$SCRIPT_DIR/$name"
  if [[ ! -f "$path" ]]; then
    echo "Missing script: $path" >&2
    exit 1
  fi
  echo "Applying $name ..."
  psql -q -v ON_ERROR_STOP=1 -f "$path"
done

echo "Contract check..."
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 not found; skipping contract check" >&2
else
  "$PYTHON_BIN" "$REPO_ROOT/workflow_engine/contract/validate_contract.py"
fi

echo "Deployed wf objects on $PGHOST/$PGDATABASE"
