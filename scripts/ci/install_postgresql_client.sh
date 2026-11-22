#!/usr/bin/env bash
# Install psql/pg_dump from the PGDG apt repo at the given major version.
# Ubuntu's own postgresql-client is older than the server we test against, and
# pg_dump refuses to dump a server newer than itself.
set -euo pipefail

major="${1:?usage: install_postgresql_client.sh <major-version>}"

sudo apt-get update
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y "postgresql-client-${major}"

# The versioned binaries live under /usr/lib/postgresql/<major>/bin; put them first.
echo "/usr/lib/postgresql/${major}/bin" >> "${GITHUB_PATH:-/dev/null}"
export PATH="/usr/lib/postgresql/${major}/bin:${PATH}"

psql --version
pg_dump --version
