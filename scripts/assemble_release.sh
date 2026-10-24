#!/usr/bin/env bash
# Assemble a GoliathApp platform release tree (offline third-party tooling + exo project).
#
# Usage:
#   scripts/assemble_release.sh --output /tmp/goliathapp-release
#
# Requires network on first fetch; re-runs are incremental when vendor/ is populated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT=""

usage() {
  sed -n '2,12p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$OUTPUT" ]] || { echo "--output is required" >&2; exit 1; }

info() { echo "[INFO] $*"; }

info "Fetching pinned third-party artifacts"
python3 "$SCRIPT_DIR/fetch_third_party.py" --dest "$REPO_ROOT/third_party/vendor"

mkdir -p "$OUTPUT"
rsync -a --delete \
  --exclude '.git' \
  --exclude 'site/' \
  --exclude 'third_party/vendor/' \
  "$REPO_ROOT/" "$OUTPUT/"

info "Copying offline Exograph bundle into release tree"
mkdir -p "$OUTPUT/third_party/vendor"
rsync -a "$REPO_ROOT/third_party/vendor/exograph/" "$OUTPUT/third_party/vendor/exograph/"

info "Release tree ready at $OUTPUT"
