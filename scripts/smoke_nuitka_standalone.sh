#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/build/nuitka/standalone/nexus.dist}"
BIN_PATH="$DIST_DIR/nexus"
if [[ -x "$DIST_DIR/bin/nexus" ]]; then
  BIN_PATH="$DIST_DIR/bin/nexus"
fi
CONFIG_PATH="$DIST_DIR/etc/config.yaml"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

require_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "missing required path: $path" >&2
    exit 1
  fi
}

main() {
  require_path "$BIN_PATH"
  require_path "$CONFIG_PATH"
  require_path "$PYTHON_BIN"

  local outside_cwd
  outside_cwd="$(mktemp -d)"
  trap "rm -rf '$outside_cwd'" EXIT

  (
    cd "$outside_cwd"
    "$BIN_PATH" --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" vault-management --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" mapping >/dev/null
  )

  require_path "$DIST_DIR/reports"
  require_path "$DIST_DIR/var/cache"
  require_path "$DIST_DIR/var/logs"

  local report_path
  report_path="$(find "$DIST_DIR/reports/mapper" -maxdepth 1 -type f -name '*_mapper.json' | sort | tail -n 1)"
  if [[ -z "$report_path" ]]; then
    echo "mapping smoke did not produce a report under $DIST_DIR/reports/mapper" >&2
    exit 1
  fi

  echo "smoke passed"
  echo "report: $report_path"
}

main "$@"
