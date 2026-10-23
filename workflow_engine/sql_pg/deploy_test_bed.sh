#!/usr/bin/env bash
# Deploy wf test-bed seeds + run a smoke simulation (PostgreSQL).
#
# Usage (after apply_schema.sh or a local sql_pg core deploy):
#   export PGHOST=localhost PGDATABASE=goliath PGUSER=postgres PGPASSWORD=... PGSSLMODE=prefer
#   ./deploy_test_bed.sh
#   ./deploy_test_bed.sh --run TwoGroupTestFlow
#   ./deploy_test_bed.sh --run McTwoGroupTestFlow

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${PGHOST:?Set PGHOST}"
export PGPORT="${PGPORT:-5432}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGUSER:?Set PGUSER}"
export PGSSLMODE="${PGSSLMODE:-prefer}"

if [[ -z "${PGPASSWORD:-}" && -z "${PGPASSFILE:-}" ]]; then
  echo "Set PGPASSWORD or PGPASSFILE for database authentication." >&2
  exit 1
fi

RUN_WORKFLOW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN_WORKFLOW="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPTS=(
  wf_instance_extension.sql
  wf_test_bed_schema.sql
  wf_test_bed_worker.sql
  wf_two_group_test_seed.sql
  wf_mc_two_group_test_seed.sql
  wf_test_bed_run.sql
)

for name in "${SCRIPTS[@]}"; do
  echo "Applying $name ..."
  psql -q -v ON_ERROR_STOP=1 -f "$SCRIPT_DIR/$name"
done

echo "Test bed workflows seeded."

if [[ -n "$RUN_WORKFLOW" ]]; then
  CONTEXT_FILE="$SCRIPT_DIR/instance_context_examples/two_group_test.json"
  if [[ "$RUN_WORKFLOW" == "McTwoGroupTestFlow" ]]; then
    CONTEXT_FILE="$SCRIPT_DIR/instance_context_examples/mc_two_group_test.json"
  fi
  echo "Running smoke simulation for $RUN_WORKFLOW ..."
  psql -q -v ON_ERROR_STOP=1 \
    -v workflow_name="$RUN_WORKFLOW" \
    -v context_json="$(cat "$CONTEXT_FILE")" <<'SQL'
SELECT * FROM wf.sp_test_bed_run_workflow(
  :'workflow_name',
  :'context_json'::jsonb
);
SELECT * FROM wf.v_test_bed_task_summary ORDER BY test_bed_run_id DESC LIMIT 1;
SQL
fi

echo "Done."
