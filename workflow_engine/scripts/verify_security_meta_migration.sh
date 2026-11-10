#!/usr/bin/env bash
# Post-apply verification for Meta security migration (production smoke).
set -euo pipefail

: "${PGHOST:?Set PGHOST}"
export PGPORT="${PGPORT:-5432}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGUSER:?Set PGUSER}"
export PGSSLMODE="${PGSSLMODE:-prefer}"

psql -v ON_ERROR_STOP=1 -c "
  SELECT check_name, ok, detail
  FROM portal.sp_security_meta_verify_production()
  ORDER BY check_name;
"

fail_count="$(psql -t -A -c "
  SELECT count(*)::int
  FROM portal.sp_security_meta_verify_production()
  WHERE NOT ok;
")"

if [[ "${fail_count}" != "0" ]]; then
  echo "verification failed: ${fail_count} check(s)" >&2
  exit 1
fi

echo "All production security Meta verification checks passed."
