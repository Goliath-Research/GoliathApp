#!/usr/bin/env bash
# Turn on TLS in the CI PostgreSQL service container with a throwaway CA, then
# export PGSSLMODE=verify-full and PGSSLROOTCERT so later steps verify the server.
#
# Usage: enable_postgres_tls.sh <service-container-id>
# Requires PGHOST, PGPORT, PGUSER, PGPASSWORD (superuser) in the environment.
set -euo pipefail

container="${1:?usage: enable_postgres_tls.sh <service-container-id>}"
out="${RUNNER_TEMP:-/tmp}/postgres-tls"
remote_dir=/var/lib/postgresql/ci-tls
mkdir -p "$out"

openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -subj "/CN=goliath-ci-postgres-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -keyout "$out/ca.key" -out "$out/ca.crt" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
  -keyout "$out/server.key" -out "$out/server.csr" 2>/dev/null
printf '%s\n' \
  "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1" \
  "basicConstraints=critical,CA:FALSE" \
  "keyUsage=critical,digitalSignature,keyEncipherment" \
  "extendedKeyUsage=serverAuth" > "$out/server.ext"
openssl x509 -req -in "$out/server.csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" \
  -CAcreateserial -days 2 -extfile "$out/server.ext" -out "$out/server.crt" 2>/dev/null

docker exec -u root "$container" mkdir -p "$remote_dir"
docker cp "$out/server.crt" "$container:$remote_dir/server.crt"
docker cp "$out/server.key" "$container:$remote_dir/server.key"
docker exec -u root "$container" chown -R postgres:postgres "$remote_dir"
docker exec -u root "$container" chmod 600 "$remote_dir/server.key"

# The server has no certificate yet, so this one bootstrap call cannot verify it.
PGSSLMODE=disable psql -X -q -v ON_ERROR_STOP=1 \
  -c "ALTER SYSTEM SET ssl_cert_file = '$remote_dir/server.crt'" \
  -c "ALTER SYSTEM SET ssl_key_file = '$remote_dir/server.key'" \
  -c "ALTER SYSTEM SET ssl = on" \
  -c "SELECT pg_reload_conf()" >/dev/null

for _ in $(seq 1 20); do
  if ssl=$(PGSSLMODE=verify-full PGSSLROOTCERT="$out/ca.crt" psql -X -tA \
      -c "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()" 2>/dev/null) \
      && [[ "$ssl" == "t" ]]; then
    break
  fi
  sleep 0.5
done
if [[ "${ssl:-}" != "t" ]]; then
  echo "PostgreSQL did not accept a verify-full TLS connection" >&2
  PGSSLMODE=verify-full PGSSLROOTCERT="$out/ca.crt" psql -X -tA -c "SELECT 1" || true
  exit 1
fi
echo "PostgreSQL TLS enabled; verify-full connection succeeded."

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    echo "PGSSLMODE=verify-full"
    echo "PGSSLROOTCERT=$out/ca.crt"
  } >> "$GITHUB_ENV"
fi
