#!/bin/bash
# Build "Genius Control.app" (self-contained, no Python install needed to run it).
# Output: dist/Genius Control.app
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
VENV=build/venv
if [ ! -x "$VENV/bin/pyinstaller" ]; then
    "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip pyinstaller
fi

rm -rf "dist/Genius Control.app" build/pyinstaller
"$VENV/bin/pyinstaller" --noconfirm --clean --windowed \
    --name "Genius Control" \
    --osx-bundle-identifier local.geniuscontrol.app \
    --icon "$(pwd)/assets/GeniusControl.icns" \
    --workpath build/pyinstaller --specpath build/pyinstaller --distpath dist \
    genius_control.py

echo
echo "Built: $(pwd)/dist/Genius Control.app"
echo "Copy it to /Applications or double-click it from Finder."
