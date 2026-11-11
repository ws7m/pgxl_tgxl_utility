#!/bin/bash
# Build "Genius Control.app" (self-contained, no Python install needed to run it).
# Output: dist/Genius Control.app
#
# Needs a Python 3.10+ whose tkinter uses Tcl/Tk 8.6 or newer. Apple's
# /usr/bin/python3 ships Tk 8.5, which draws blank windows on current macOS,
# so it is skipped. Install Python from https://www.python.org/downloads/macos/
# (it includes a current Tk), or point PYTHON=/path/to/python3 at one.
set -euo pipefail
cd "$(dirname "$0")"

# Prints "ok <version> <tk>" when the interpreter is usable, else "bad <reason>".
check_python() {
    "$1" - <<'EOF' 2>/dev/null || echo "bad cannot import tkinter"
import sys
if sys.version_info < (3, 10):
    print("bad Python %d.%d is too old (need 3.10+)" % sys.version_info[:2]); raise SystemExit
import tkinter
tk = tkinter.Tcl().eval("info patchlevel")
major, minor = (int(x) for x in tk.split(".")[:2])
if (major, minor) < (8, 6):
    print("bad Tcl/Tk %s is too old (need 8.6+; it draws blank windows)" % tk); raise SystemExit
print("ok %s %s" % (sys.version.split()[0], tk))
EOF
}

candidates=()
if [ -n "${PYTHON:-}" ]; then
    candidates=("$PYTHON")
else
    for v in 3.14 3.13 3.12 3.11 3.10; do
        candidates+=("/Library/Frameworks/Python.framework/Versions/$v/bin/python3")
        candidates+=("python$v")
    done
    candidates+=(/opt/homebrew/bin/python3 /usr/local/bin/python3 python3)
fi

PY=""
for c in "${candidates[@]}"; do
    path=$(command -v "$c" 2>/dev/null) || continue
    result=$(check_python "$path")
    if [[ $result == ok* ]]; then
        PY=$path
        read -r _ pyver tkver <<<"$result"
        break
    fi
    echo "Skipping $path: ${result#bad }"
done

if [ -z "$PY" ]; then
    cat >&2 <<'EOF'

No suitable Python found. The app needs Python 3.10+ with Tcl/Tk 8.6 or newer.
Apple's /usr/bin/python3 has Tk 8.5, which shows a blank window.

Fix: install Python from https://www.python.org/downloads/macos/ and run this
script again (or run: PYTHON=/path/to/python3 ./build_app.sh).
With Homebrew: brew install python-tk@3.13
EOF
    exit 1
fi
echo "Using $PY (Python $pyver, Tcl/Tk $tkver)"

# Rebuild the build venv if it was made from a different interpreter.
VENV=build/venv
if [ -x "$VENV/bin/python" ]; then
    venv_check=$(check_python "$VENV/bin/python")
    venv_base=$("$VENV/bin/python" -c 'import sys; print(sys.base_prefix)' 2>/dev/null || true)
    py_base=$("$PY" -c 'import sys; print(sys.base_prefix)')
    if [[ $venv_check != ok* || $venv_base != "$py_base" ]]; then
        echo "Recreating $VENV (it was built with a different Python)"
        rm -rf "$VENV"
    fi
fi
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
