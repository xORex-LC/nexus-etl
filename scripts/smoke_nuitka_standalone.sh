#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/build/nuitka/standalone/nexus.dist}"
BIN_PATH="$DIST_DIR/libs/nexus"
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
    # Run two real pipeline commands: exercises dynamically-bundled command
    # handlers (lazy importlib targets), per-component report layout and the
    # observability read path / run ledger.
    "$BIN_PATH" --config "$CONFIG_PATH" mapping >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" normalize >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" obs latest normalizer --artifact report >/dev/null
  )

  require_path "$DIST_DIR/reports"
  require_path "$DIST_DIR/var/cache"
  require_path "$DIST_DIR/var/logs"
  require_path "$DIST_DIR/var/plans"

  require_component_report() {
    local component="$1"
    local found
    found="$(find "$DIST_DIR/reports/$component" -maxdepth 1 -type f -name "*_${component}.json" | sort | tail -n 1)"
    if [[ -z "$found" ]]; then
      echo "smoke did not produce a report under $DIST_DIR/reports/$component" >&2
      exit 1
    fi
    printf '%s\n' "$found"
  }

  local report_path normalize_report
  report_path="$(require_component_report mapper)"
  normalize_report="$(require_component_report normalizer)"

  echo "smoke passed"
  echo "mapper report:     $report_path"
  echo "normalizer report: $normalize_report"
}

main "$@"
