#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/build/nuitka/standalone/nexus.dist}"
BIN_PATH="$DIST_DIR/nexus"
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

  "$PYTHON_BIN" - <<'PY' "$ROOT_DIR" "$DIST_DIR"
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from tests.vault_unseal_setup import TEST_UNSEAL_PASSPHRASE, initialize_test_vault

dist_dir = Path(sys.argv[2])
initialize_test_vault(dist_dir / "var" / "cache", passphrase=TEST_UNSEAL_PASSPHRASE)
PY

  (
    cd "$outside_cwd"
    "$BIN_PATH" --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" vault-management --help >/dev/null
    "$BIN_PATH" --config "$CONFIG_PATH" mapping >/dev/null
    "$PYTHON_BIN" - <<'PY' "$ROOT_DIR" "$BIN_PATH" "$CONFIG_PATH"
from pathlib import Path
import errno
import os
import pty
import select
import subprocess
import sys

sys.path.insert(0, sys.argv[1])
from tests.vault_unseal_setup import TEST_UNSEAL_PASSPHRASE

bin_path = Path(sys.argv[2])
config_path = Path(sys.argv[3])
master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    [str(bin_path), "--config", str(config_path), "--run-id", "smoke-enrich", "enrich"],
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    text=True,
    close_fds=True,
)
os.close(slave_fd)
sent = False
chunks: list[str] = []
try:
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.1)
        if ready:
            try:
                raw = os.read(master_fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            data = raw.decode("utf-8", errors="replace")
            if not data:
                break
            chunks.append(data)
            if (not sent) and "Введите unseal passphrase" in data:
                os.write(master_fd, f"{TEST_UNSEAL_PASSPHRASE}\n".encode("utf-8"))
                sent = True
        if proc.poll() is not None and not ready:
            break
finally:
    os.close(master_fd)

exit_code = proc.wait()
if exit_code != 0:
    raise SystemExit("standalone enrich smoke failed:\n" + "".join(chunks))
PY
  )

  require_path "$DIST_DIR/reports"
  require_path "$DIST_DIR/var/cache"
  require_path "$DIST_DIR/var/logs"

  local report_path
  report_path="$(find "$DIST_DIR/reports" -maxdepth 1 -type f -name 'report_mapping_*.json' | sort | tail -n 1)"
  if [[ -z "$report_path" ]]; then
    echo "mapping smoke did not produce a report under $DIST_DIR/reports" >&2
    exit 1
  fi

  local enrich_report_path
  enrich_report_path="$(find "$DIST_DIR/reports" -maxdepth 1 -type f -name 'report_enrich_smoke-enrich.json' | sort | tail -n 1)"
  if [[ -z "$enrich_report_path" ]]; then
    echo "enrich smoke did not produce a report under $DIST_DIR/reports" >&2
    exit 1
  fi

  "$PYTHON_BIN" - <<'PY' "$enrich_report_path"
from pathlib import Path
import json
import sys

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
items = report.get("items") or []
if not items:
    raise SystemExit("enrich smoke report does not contain items")
payload = items[0].get("payload") or {}
if payload.get("userName") in (None, ""):
    raise SystemExit("enrich smoke report did not populate payload.userName")
PY

  echo "smoke passed"
  echo "report: $report_path"
  echo "enrich report: $enrich_report_path"
}

main "$@"
