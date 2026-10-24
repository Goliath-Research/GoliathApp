#!/usr/bin/env bash
# Provider-neutral checklist for the goliath-exo target (PostgreSQL + Exograph/MCP).
#
# Usage:
#   deploy/scripts/deploy_goliath_exo.sh --target deploy/targets/goliath-exo.json
#
# Does not SSH or start systemd by itself; prints the ordered steps and validates the target JSON.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET=""

usage() {
  sed -n '2,8p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$TARGET" && -f "$TARGET" ]] || { echo "--target must point to an existing JSON file" >&2; exit 1; }

python3 - <<'PY' "$TARGET" "$REPO_ROOT/deploy/targets/target.schema.json"
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])
schema_path = Path(sys.argv[2])
target = json.loads(target_path.read_text())
if target.get("name") != "goliath-exo":
    raise SystemExit(f"expected name goliath-exo, got {target.get('name')!r}")
print(f"[ok] loaded target {target['name']} (rollouts: {target['rollouts_environment']})")
PY

cat <<'EOF'

Deploy sequence (adapt hosts / orchestrator to your environment):

  1. Apply GoliathApp SQL: workflow_engine/sql_pg/apply_schema.sh
  2. Seed core semantic catalog: python3 workflow_engine/sql_pg/seed_semantic_catalog.py
  3. Ensure goliath_portal / goliath_gateway passwords match the target database section
  4. Fetch offline Exograph: python3 scripts/fetch_third_party.py
  5. Build exo IR: (cd exo && third_party/vendor/exograph/0.29.1/linux-x86_64/exo build)
  6. Configure exograph.env:
       EXO_POSTGRES_URL=postgres://goliath_portal:…@HOST:5432/DB?sslmode=verify-full
       (do not set EXO_POSTGRES_READ_WRITE)
       EXO_JWT_SECRET aligned with portal session minting
  7. Start exo-server from the release bundle; expose MCP profile semantic_read if agents are enabled
  8. Portal backends may use PortalClient or GraphQL runSemanticRequest with the same session token

Workers and the REST gateway are out of scope for goliath-exo; use GoliathOmics deploy targets.

EOF
