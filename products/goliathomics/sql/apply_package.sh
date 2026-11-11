#!/usr/bin/env bash
# Apply GoliathOmics SQL package on the database selected by PG* env vars.
set -euo pipefail

: "${PGHOST:?Set PGHOST}"
: "${PGDATABASE:?Set PGDATABASE (e.g. GoliathOmics_v2 when David approves create)}"
: "${PGUSER:?Set PGUSER}"
export PGPORT="${PGPORT:-5432}"
export PGSSLMODE="${PGSSLMODE:-prefer}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for sql in 01_omics_meta_domain_classes.sql 02_omics_nav_seed.sql; do
  echo "Applying ${sql}..."
  psql -v ON_ERROR_STOP=1 -f "${SCRIPT_DIR}/${sql}"
done

echo "GoliathOmics package apply complete on ${PGDATABASE}@${PGHOST}."
