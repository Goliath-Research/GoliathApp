#!/usr/bin/env bash
# Assert the CI service is the intended PostgreSQL major and report whether
# pg_jsonschema is installable. pg_jsonschema is not in the stock postgres image;
# meta_model_phase_c.sql is expected to fall back to the always-on SQL key check.
set -euo pipefail

num="$(psql -v ON_ERROR_STOP=1 -X -At -c "SHOW server_version_num")"
actual_major="$((num / 10000))"
echo "server_version: $(psql -X -At -c "SHOW server_version")"
echo "psql: $(psql --version)"
echo "pg_jsonschema_available: $(psql -X -At -c "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_jsonschema')")"

expected_major="${EXPECTED_PG_MAJOR:?EXPECTED_PG_MAJOR is required}"
if [[ "${actual_major}" != "${expected_major}" ]]; then
  echo "Expected PostgreSQL ${expected_major}, got ${actual_major}" >&2
  exit 1
fi
