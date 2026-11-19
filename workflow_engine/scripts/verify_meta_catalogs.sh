#!/usr/bin/env bash
# Post-apply check: every catalog table registered as a Meta catalog kind agrees with Meta
# (one object per row, same values). Prints per-kind counts; exits non-zero on any drift.
set -euo pipefail

: "${PGHOST:?Set PGHOST}"
export PGPORT="${PGPORT:-5432}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${PGUSER:?Set PGUSER}"
export PGSSLMODE="${PGSSLMODE:-prefer}"

psql -X -v ON_ERROR_STOP=1 -c "
  SELECT k.kind, k.relation::text AS relation, c.\"Name\" AS class,
         (SELECT count(*) FROM \"Meta\".catalog_row r WHERE r.kind = k.kind) AS objects,
         (SELECT count(*) FROM \"Meta\".fn_catalog_drift(k.kind)) AS drift
  FROM \"Meta\".catalog_kind k JOIN \"Meta\".\"Classes\" c ON c.\"ID\" = k.class_id
  ORDER BY k.kind;
"

drift="$(psql -X -t -A -c 'SELECT count(*)::int FROM "Meta".fn_catalog_drift()')"
if [[ "${drift}" != "0" ]]; then
  psql -X -c 'SELECT * FROM "Meta".fn_catalog_drift() ORDER BY kind LIMIT 20'
  echo "meta catalog check failed: ${drift} row(s) differ between catalog tables and Meta" >&2
  exit 1
fi
echo "All Meta catalogs match their tables."
