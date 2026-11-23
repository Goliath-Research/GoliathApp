#!/usr/bin/env bash
# Post-apply check: every catalog action is a method on exactly one owning class.
# Known duplicates (platform owner plus copies elsewhere) are listed but tolerated.
set -euo pipefail

: "${PGHOST:?Set PGHOST}"
export PGPORT="${PGPORT:-5432}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGUSER:?Set PGUSER}"
export PGSSLMODE="${PGSSLMODE:-verify-full}"
case "$PGSSLMODE" in
  verify-full|verify-ca) ;;
  *) echo "PGSSLMODE=$PGSSLMODE does not verify the server certificate; use verify-full or verify-ca (set PGSSLROOTCERT)." >&2; exit 1 ;;
esac

psql -X -v ON_ERROR_STOP=1 -c "
  SELECT action_name, status, owners
  FROM \"Meta\".fn_check_action_owners()
  WHERE status <> 'ok'
  ORDER BY status, action_name;
"

invalid="$(psql -X -t -A -c "
  SELECT count(*)::int FROM \"Meta\".fn_check_action_owners()
  WHERE status IN ('no_owner', 'multiple_owners');
")"
known="$(psql -X -t -A -c "
  SELECT count(*)::int FROM \"Meta\".fn_check_action_owners() WHERE status = 'known_duplicate';
")"

if [[ "${invalid}" != "0" ]]; then
  echo "action owner check failed: ${invalid} action(s) without exactly one owning class (${known} known duplicates)" >&2
  exit 1
fi
echo "All actions have one owning class (${known} known duplicates tolerated)."
