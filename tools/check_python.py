"""Check that this Python can build/run Genius Control (used by the build scripts).

Run as:  <python> -I tools/check_python.py
Prints "ok <python version> <tk version>" and exits 0, or "bad <reason>" and exits 1.
"""

import sys


def main() -> int:
    if sys.version_info < (3, 10):
        print("bad Python %d.%d is too old (need 3.10+)" % sys.version_info[:2])
        return 1
    try:
        import tkinter
    except ImportError:
        print("bad tkinter is not installed for this Python")
        return 1
    try:
        tk = tkinter.Tcl().eval("info patchlevel")
    except tkinter.TclError as exc:
        print(f"bad Tcl/Tk does not start ({exc})")
        return 1
    major, minor = (int(x) for x in tk.split(".")[:2])
    if (major, minor) < (8, 6):
        print(f"bad Tcl/Tk {tk} is too old (need 8.6+; it draws blank windows)")
        return 1
    try:
        import venv  # noqa: F401
        import ensurepip  # noqa: F401
    except ImportError:
        print("bad the venv/ensurepip modules are missing")
        return 1
    print(f"ok {sys.version.split()[0]} {tk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
