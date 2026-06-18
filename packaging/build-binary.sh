#!/usr/bin/env bash
# Build and smoke-test the standalone `captouch` binary (Linux / macOS).
#
# Usage:  packaging/build-binary.sh [extra pyinstaller args]
# Needs the packaging extra:  pip install -e '.[packaging]'
#
# PyInstaller cannot cross-compile — this builds a binary for the host OS only.
# The Windows binary is produced by the CI matrix (.github/workflows/build.yml).
set -euo pipefail

cd "$(dirname "$0")/.."

pyinstaller packaging/captouch.spec --noconfirm \
    --distpath dist --workpath build/pyi "$@"

BIN=dist/captouch
echo "== smoke test =="
"$BIN" --version
"$BIN" slider --list-presets >/dev/null
"$BIN" trackpad --list-fab-profiles >/dev/null
QT_QPA_PLATFORM=offscreen "$BIN" gui --check
echo "OK: $BIN ($(du -h "$BIN" | cut -f1))"
