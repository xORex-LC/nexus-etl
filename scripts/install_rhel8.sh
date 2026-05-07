#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP_USER="${APP_USER:-nexus}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/nexus}"
SRC_ROOT="${SRC_ROOT:-/opt/nexus-src}"
RELEASE_ID="${RELEASE_ID:-$(date +%Y%m%d-%H%M%S)}"
PYTHON_BIN_NAME="${PYTHON_BIN_NAME:-python3.11}"
BOOTSTRAP=0
HARD_CLEAN=0
KEEP_BUILD_CACHE=0

usage() {
  cat <<'EOF'
Usage:
  scripts/build_and_install_rhel8.sh [options]

Options:
  --bootstrap          Install build prerequisites on RHEL 8 (requires sudo/root).
  --hard-clean         Remove build venv and source checkout after successful install.
  --keep-build-cache   Keep build/ artifacts in source checkout.
  --app-user USER      App user (default: nexus).
  --install-root PATH  Install root (default: /opt/nexus).
  --src-root PATH      Source checkout path (default: /opt/nexus-src).
  --release-id ID      Release id (default: timestamp).
  -h, --help           Show help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap) BOOTSTRAP=1 ;;
    --hard-clean) HARD_CLEAN=1 ;;
    --keep-build-cache) KEEP_BUILD_CACHE=1 ;;
    --app-user) APP_USER="$2"; shift ;;
    --install-root) INSTALL_ROOT="$2"; shift ;;
    --src-root) SRC_ROOT="$2"; shift ;;
    --release-id) RELEASE_ID="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
  SUDO="sudo"
fi

bootstrap_rhel8() {
  if ! grep -qE 'release 8' /etc/redhat-release; then
    echo "This bootstrap is intended for RHEL 8.x. Found: $(cat /etc/redhat-release)" >&2
    exit 1
  fi

  $SUDO dnf -y install dnf-plugins-core
  $SUDO dnf -y install \
    git tar gzip findutils coreutils which \
    patchelf gcc gcc-c++ make \
    python3.11 python3.11-devel python3.11-pip python3.11-setuptools python3.11-wheel \
    openssl-devel libffi-devel zlib-devel bzip2-devel xz-devel sqlite-devel

  if ! id "$APP_USER" >/dev/null 2>&1; then
    $SUDO useradd -m -s /bin/bash "$APP_USER"
  fi
  $SUDO mkdir -p "$INSTALL_ROOT" "$SRC_ROOT"
  $SUDO chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT" "$SRC_ROOT"
}

ensure_checkout() {
  if [[ ! -d "$SRC_ROOT/.git" ]]; then
    echo "Missing git checkout at $SRC_ROOT" >&2
    echo "Clone repo first, for example:" >&2
    echo "  git clone <repo-url> $SRC_ROOT" >&2
    exit 1
  fi
}

build_release() {
  cd "$SRC_ROOT"
  "$PYTHON_BIN_NAME" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip wheel setuptools
  .venv/bin/python -m pip install -e .

  make clean
  make build-standalone
  make smoke-standalone
  make release-standalone
}

install_release() {
  local archive="$SRC_ROOT/build/artifacts/nexus-linux-x86_64.tar.gz"
  local checksum="$archive.sha256"
  local release_dir="$INSTALL_ROOT/releases/$RELEASE_ID"

  [[ -f "$archive" ]] || { echo "Archive not found: $archive" >&2; exit 1; }
  [[ -f "$checksum" ]] || { echo "Checksum not found: $checksum" >&2; exit 1; }

  mkdir -p "$release_dir"
  sha256sum -c "$checksum"
  tar -C "$release_dir" -xzf "$archive"

  ln -sfn "$release_dir/nexus.dist" "$INSTALL_ROOT/current"
  "$INSTALL_ROOT/current/bin/nexus" --help >/dev/null
}

cleanup() {
  cd "$SRC_ROOT"
  if [[ "$KEEP_BUILD_CACHE" -eq 0 ]]; then
    rm -rf build .pytest_cache
  fi
  if [[ "$HARD_CLEAN" -eq 1 ]]; then
    rm -rf .venv
  fi
}

main() {
  if [[ "$BOOTSTRAP" -eq 1 ]]; then
    bootstrap_rhel8
  fi

  ensure_checkout
  build_release
  install_release
  cleanup

  cat <<EOF
Done.
Release: $RELEASE_ID
Current: $INSTALL_ROOT/current
Run: $INSTALL_ROOT/current/bin/nexus --help
EOF
}

main "$@"
