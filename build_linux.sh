#!/bin/bash
# Build Genius Control for Linux: a single self-contained executable.
#   ./build_linux.sh             -> dist/genius-control, its icon and dist/install.sh
#   ./build_linux.sh --install   -> also installs it for this user in ~/.local
#
# Run this ON Linux (PyInstaller can't cross-compile). The program works on
# this distribution and on others with the same or a newer glibc.
#
# Needs Python 3.10+ with tkinter (Tcl/Tk 8.6+) and venv. On Debian/Ubuntu:
#   sudo apt install python3 python3-tk python3-venv
# Fedora: sudo dnf install python3 python3-tkinter
# Arch:   sudo pacman -S python tk
set -euo pipefail
cd "$(dirname "$0")"

INSTALL=0
[ "${1:-}" = "--install" ] && INSTALL=1

check_python() {  # prints "ok <python> <tk>" or "bad <reason>"
    local out
    out=$("$1" -I tools/check_python.py 2>/dev/null || true)
    echo "${out:-bad could not run it}"
}

candidates=()
if [ -n "${PYTHON:-}" ]; then
    candidates=("$PYTHON")
else
    candidates=(python3.14 python3.13 python3.12 python3.11 python3.10 python3)
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
    cat >&2 <<'MSG'

No suitable Python found. Genius Control needs Python 3.10+ with tkinter
(Tcl/Tk 8.6+) and venv. Install them, then run this script again:
  Debian/Ubuntu: sudo apt install python3 python3-tk python3-venv
  Fedora:        sudo dnf install python3 python3-tkinter
  Arch:          sudo pacman -S python tk
Or choose an interpreter: PYTHON=/path/to/python3 ./build_linux.sh
MSG
    exit 1
fi
echo "Using $PY (Python $pyver, Tcl/Tk $tkver)"

# Build venv for this OS; recreated if it was made from a different Python.
VENV=build/venv-linux
if [ -x "$VENV/bin/python" ]; then
    venv_base=$("$VENV/bin/python" -c 'import sys; print(sys.base_prefix)' 2>/dev/null || true)
    py_base=$("$PY" -c 'import sys; print(sys.base_prefix)')
    if [[ $(check_python "$VENV/bin/python") != ok* || $venv_base != "$py_base" ]]; then
        echo "Recreating $VENV (it was built with a different Python)"
        rm -rf "$VENV"
    fi
fi
if [ ! -x "$VENV/bin/pyinstaller" ]; then
    "$PY" -m venv "$VENV"
    "$VENV/bin/python" -m pip install -q --upgrade pip pyinstaller
fi

NAME=genius-control
rm -rf "dist/$NAME" "dist/$NAME.png" dist/install.sh build/pyinstaller-linux
"$VENV/bin/pyinstaller" --noconfirm --clean --onefile --windowed \
    --name "$NAME" \
    --add-data "$(pwd)/assets/icon.png:assets" \
    --workpath build/pyinstaller-linux --specpath build/pyinstaller-linux --distpath dist \
    genius_control.py

cp assets/icon.png "dist/$NAME.png"
# The menu entry needs absolute paths for the user who installs it, so it is
# written by install.sh at install time rather than here.
cat > dist/install.sh <<'INSTALL'
#!/bin/sh
# Install Genius Control for this user: ~/.local/bin + applications menu entry.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons"
install -m 755 genius-control "$HOME/.local/bin/"
install -m 644 genius-control.png "$HOME/.local/share/icons/"
cat > "$HOME/.local/share/applications/genius-control.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Genius Control
Comment=Control a 4O3A Tuner Genius XL, Power Genius XL and FlexRadio
Exec=$HOME/.local/bin/genius-control
Icon=$HOME/.local/share/icons/genius-control.png
Terminal=false
Categories=HamRadio;Utility;
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$HOME/.local/share/applications" || true
echo "Installed to $HOME/.local/bin/genius-control and added Genius Control to the applications menu."
INSTALL
chmod +x dist/install.sh

echo
echo "Built: $(pwd)/dist/$NAME"

if [ $INSTALL = 1 ]; then
    dist/install.sh
else
    echo "Run it with: ./dist/$NAME"
    echo "Or run ./build_linux.sh --install (or dist/install.sh) to add it to your applications menu."
fi
