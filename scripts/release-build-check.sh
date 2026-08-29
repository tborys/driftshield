#!/usr/bin/env bash
# Build the driftshield-sdk sdist and wheel, then prove the artefact is releasable:
#   - twine check passes
#   - the wheel contains only the driftshield package and its metadata
#   - a fresh venv install exposes the CLI with the analyze and submit commands
# Used by the release-build and release-publish workflows and runnable locally.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT_DIR/driftshield"
DIST_DIR="$PKG_DIR/dist"
PYTHON="${PYTHON:-python3}"

cd "$PKG_DIR"
rm -rf "$DIST_DIR"

echo "[release] building sdist and wheel"
"$PYTHON" -m pip install --quiet --upgrade pip build twine
"$PYTHON" -m build

echo "[release] twine check"
"$PYTHON" -m twine check --strict "$DIST_DIR"/*

WHEEL="$(ls "$DIST_DIR"/driftshield_sdk-*.whl)"
VERSION="$(basename "$WHEEL" | sed -E 's/^driftshield_sdk-([^-]+)-.*/\1/')"

echo "[release] wheel contents check ($WHEEL)"
UNEXPECTED="$("$PYTHON" - "$WHEEL" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
bad = [n for n in names
       if not (n.startswith("driftshield/") or n.startswith("driftshield_sdk-") and ".dist-info/" in n)
       or "__pycache__" in n or n.endswith(".pyc") or "/tests/" in n or "/frontend/" in n]
print("\n".join(bad))
PY
)"
if [ -n "$UNEXPECTED" ]; then
  echo "[release] wheel contains files outside the package:" >&2
  echo "$UNEXPECTED" >&2
  exit 1
fi

echo "[release] fresh venv install smoke test"
VENV="$(mktemp -d)/venv"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet "$WHEEL"
HELP="$("$VENV/bin/driftshield" --help | sed -E 's/\x1b\[[0-9;]*m//g')"
for cmd in analyze submit batch; do
  echo "$HELP" | grep -Eq "^\s*(│\s*)?$cmd\b" || { echo "[release] '$cmd' missing from driftshield --help" >&2; exit 1; }
done
"$VENV/bin/driftshield" --version | grep -q "driftshield $VERSION"
"$VENV/bin/python" -c "import driftshield; assert driftshield.__version__ == '$VERSION', driftshield.__version__; from driftshield import analyse_run, submit"

echo "[release] ok: driftshield-sdk $VERSION"
echo "$VERSION" > "$DIST_DIR/VERSION"
