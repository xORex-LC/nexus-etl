#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
NUITKA_ARGS=(
  --mode=standalone
  --assume-yes-for-downloads
  --follow-imports
  --include-package-data=anyascii
  --output-dir="$ROOT_DIR/build/nuitka/standalone"
  --output-filename=nexus
  --remove-output
  --nofollow-import-to=tests
  --report="$ROOT_DIR/build/nuitka/standalone/compile-report.xml"
)

BUILD_ROOT="$ROOT_DIR/build/nuitka/standalone"
DIST_DIR="$BUILD_ROOT/nexus.dist"
CONFIG_TEMPLATE="$ROOT_DIR/examples/configs/config_example_ankey.yml"
CONFIG_OUTPUT="$DIST_DIR/etc/config.yaml"

require_path() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "missing required path: $path" >&2
    exit 1
  fi
}

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "missing required command: $name" >&2
    exit 1
  fi
}

assemble_runtime_tree() {
  local dist_dir="$1"

  mkdir -p \
    "$dist_dir/datasets" \
    "$dist_dir/dictionaries" \
    "$dist_dir/etc/source-data" \
    "$dist_dir/environment" \
    "$dist_dir/reports" \
    "$dist_dir/var/cache" \
    "$dist_dir/var/logs"

  cp -a "$ROOT_DIR/datasets/." "$dist_dir/datasets/"
  cp -a "$ROOT_DIR/dictionaries/." "$dist_dir/dictionaries/"

  if [[ -f "$ROOT_DIR/examples/sources/source_employees_example_1.csv" ]]; then
    cp "$ROOT_DIR/examples/sources/source_employees_example_1.csv" \
      "$dist_dir/etc/source-data/source_employees_example_1.csv"
  fi

  "$PYTHON_BIN" - <<'PY' "$CONFIG_TEMPLATE" "$CONFIG_OUTPUT" "$DIST_DIR"
from pathlib import Path
import sys

import yaml

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
dist_dir = Path(sys.argv[3]).resolve()

payload = yaml.safe_load(template_path.read_text(encoding="utf-8"))

payload.setdefault("runtime", {})
payload["runtime"]["runtime_root"] = str(dist_dir)
payload["runtime"]["config_root"] = "./etc"
payload["runtime"]["datasets_root"] = "./datasets"
payload["runtime"]["dictionary_specs_root"] = "./datasets"
payload["runtime"]["dictionary_data_root"] = "./dictionaries"
payload["runtime"]["source_data_root"] = "./etc/source-data"
payload["runtime"]["source_projection_root"] = "./datasets"
payload["runtime"]["target_projection_root"] = "./datasets"

payload.setdefault("paths", {})
payload["paths"]["cache_dir"] = "var/cache"
payload["paths"]["log_dir"] = "var/logs"
payload["paths"]["report_dir"] = "reports"

payload.setdefault("dataset", {})
payload["dataset"]["registry_path"] = "./datasets/employees.registry.yaml"

payload.setdefault("vault_management", {})
payload["vault_management"]["admin_password_hash_file"] = "./environment/vault-admin.env"

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(
    yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
PY
}

resolve_nuitka_dist_dir() {
  local candidate
  candidate="$(find "$BUILD_ROOT" -maxdepth 1 -mindepth 1 -type d -name '*.dist' | sort | head -n 1)"
  if [[ -z "$candidate" ]]; then
    echo "failed to locate Nuitka .dist directory under $BUILD_ROOT" >&2
    exit 1
  fi
  printf '%s\n' "$candidate"
}

main() {
  require_command patchelf
  require_path "$PYTHON_BIN"
  require_path "$CONFIG_TEMPLATE"
  require_path "$ROOT_DIR/datasets/registry.yaml"
  require_path "$ROOT_DIR/datasets/employees.registry.yaml"
  require_path "$ROOT_DIR/datasets/employees"
  require_path "$ROOT_DIR/datasets/targets"
  require_path "$ROOT_DIR/dictionaries"

  mkdir -p "$BUILD_ROOT"

  (
    cd "$ROOT_DIR"
    "$PYTHON_BIN" -m nuitka "${NUITKA_ARGS[@]}" connector/main.py
  )

  local nuitka_dist_dir
  nuitka_dist_dir="$(resolve_nuitka_dist_dir)"
  if [[ "$nuitka_dist_dir" != "$DIST_DIR" ]]; then
    rm -rf "$DIST_DIR"
    mv "$nuitka_dist_dir" "$DIST_DIR"
  fi

  require_path "$DIST_DIR/nexus"
  assemble_runtime_tree "$DIST_DIR"

  echo "standalone build assembled at: $DIST_DIR"
  echo "runtime config written to: $CONFIG_OUTPUT"
}

main "$@"
