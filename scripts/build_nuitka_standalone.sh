#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
NUITKA_ARGS=(
  --mode=standalone
  --assume-yes-for-downloads
  --follow-imports
  --include-package=unidecode
  # Whole application package: command handlers, registry spec_class targets and
  # enrich ops are imported dynamically (importlib.import_module / PEP 562 lazy
  # CLI init), which --follow-imports cannot discover statically. Force-include
  # connector so the lazy/dynamic targets are bundled.
  --include-package=connector
  --output-dir="$ROOT_DIR/build/nuitka/standalone"
  --output-filename=nexus
  --remove-output
  --nofollow-import-to=tests
  --report="$ROOT_DIR/build/nuitka/standalone/compile-report.xml"
)

BUILD_ROOT="$ROOT_DIR/build/nuitka/standalone"
DIST_DIR="$BUILD_ROOT/nexus.dist"
# Nuitka payload (binary + .so + Nuitka data) is isolated here; the binary and its
# shared objects must stay co-located ($ORIGIN rpath), so the binary lives in libs/.
PAYLOAD_DIR="$DIST_DIR/libs"
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
    "$dist_dir/var/logs" \
    "$dist_dir/var/plans"

  cp -a "$ROOT_DIR/datasets/." "$dist_dir/datasets/"
  cp -a "$ROOT_DIR/dictionaries/." "$dist_dir/dictionaries/"

  if [[ -f "$ROOT_DIR/examples/sources/source_employees.csv" ]]; then
    cp "$ROOT_DIR/examples/sources/source_employees.csv" \
      "$dist_dir/etc/source-data/source_employees.csv"
  fi

  if [[ -f "$ROOT_DIR/examples/sources/source_departments.csv" ]]; then
    cp "$ROOT_DIR/examples/sources/source_departments.csv" \
      "$dist_dir/etc/source-data/source_departments.csv"
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
payload["runtime"]["dictionary_specs_root"] = "./datasets/dictionaries"
payload["runtime"]["dictionary_data_root"] = "./dictionaries"
payload["runtime"]["source_data_root"] = "./etc/source-data"
payload["runtime"]["source_projection_root"] = "./datasets"
payload["runtime"]["target_projection_root"] = "./datasets/targets"

payload.setdefault("paths", {})
payload["paths"]["cache_dir"] = "var/cache"
payload["paths"]["log_dir"] = "var/logs"
payload["paths"]["report_dir"] = "reports"

payload.setdefault("dataset", {})
payload["dataset"]["registry_path"] = "./datasets/registry.yaml"

payload.setdefault("vault_management", {})
payload["vault_management"]["admin_password_hash_file"] = "./environment/vault-admin.env"

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(
    yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
PY
}

setup_bin_launcher_layout() {
  local dist_dir="$1"
  mkdir -p "$dist_dir/bin"

  cat >"$dist_dir/bin/nexus" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

exec "$DIST_DIR/libs/nexus" "$@"
SH
  chmod +x "$dist_dir/bin/nexus"
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
  require_path "$ROOT_DIR/datasets/targets"
  require_path "$ROOT_DIR/dictionaries"

  mkdir -p "$BUILD_ROOT"

  (
    cd "$ROOT_DIR"
    "$PYTHON_BIN" -m nuitka "${NUITKA_ARGS[@]}" connector/main.py
  )

  local nuitka_dist_dir
  nuitka_dist_dir="$(resolve_nuitka_dist_dir)"
  # Move the whole Nuitka payload into libs/ so the dist top level stays clean
  # (bin/, etc/, datasets/, dictionaries/, reports/, var/). Binary + .so move
  # together, so $ORIGIN rpath and Nuitka module resolution remain intact.
  rm -rf "$DIST_DIR"
  mkdir -p "$DIST_DIR"
  mv "$nuitka_dist_dir" "$PAYLOAD_DIR"

  require_path "$PAYLOAD_DIR/nexus"
  setup_bin_launcher_layout "$DIST_DIR"
  require_path "$DIST_DIR/bin/nexus"
  assemble_runtime_tree "$DIST_DIR"

  echo "standalone build assembled at: $DIST_DIR"
  echo "runtime config written to: $CONFIG_OUTPUT"
}

main "$@"
