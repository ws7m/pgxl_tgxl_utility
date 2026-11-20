# Genius Control — TGXL / PGXL network utility

Version 1.0.0 (shown in the window title; set in `geniusctl/__init__.py`).

A small desktop app that monitors and controls a **4O3A Tuner Genius XL**, a
**Power Genius XL** and a **FlexRadio** over the network. It is pure Python with tkinter: no
packages to install. It runs on macOS, Windows and Linux with Python 3.10+.

```bash
python3 genius_control.py
```

### Requirements

Python 3.10 or newer **with Tcl/Tk 8.6+**. Apple's built-in `/usr/bin/python3`
has Tcl/Tk 8.5, which draws an empty window on current macOS. Install Python
from [python.org](https://www.python.org/downloads/macos/), which includes a
current Tk, or use Homebrew's `brew install python-tk@3.13`. Check with:

```bash
python3 -c "import tkinter; print(tkinter.Tcl().eval('info patchlevel'))"
```

The app refuses to start on an old Tk and explains why. The build scripts
look for a suitable Python on their own; set `PYTHON` to choose one.

### Building a standalone app

Each script builds with PyInstaller in its own virtualenv under `build/`
(created the first time, so the first build needs internet access). The result
needs no Python to run. PyInstaller can't cross-compile, so **run each script
on the system you are building for**.

| System | Command | Result |
|---|---|---|
| macOS | `./build_app.sh` | `dist/Genius Control.app`: drag it to /Applications |
| Windows | double-click `build_windows.bat` | `dist\GeniusControl.exe`: one file, copy it anywhere |
| Linux | `./build_linux.sh` | `dist/genius-control`: one file |

**Windows:** install Python from
[python.org](https://www.python.org/downloads/windows/) first (keep the
"tcl/tk and IDLE" option ticked). The batch file runs `build_windows.ps1`; you
can also run `powershell -ExecutionPolicy Bypass -File build_windows.ps1`.
The .exe isn't code-signed, so the first launch may show a SmartScreen
warning: click *More info* → *Run anyway*.

**Linux:** install Python with tkinter and venv first, for example
`sudo apt install python3 python3-tk python3-venv` (Debian/Ubuntu),
`sudo dnf install python3 python3-tkinter` (Fedora) or
`sudo pacman -S python tk` (Arch). `./build_linux.sh --install`, or
`dist/install.sh` after a build, copies the program to `~/.local/bin` and adds
*Genius Control* to your applications menu. A build runs on that distribution and on others with the same or a
newer glibc.

### Builds from GitHub Actions

Every push to `main` (and every pull request) runs `.github/workflows/build.yml`
on macOS, Windows and Linux: unit tests, the build script for that system,
and a check that the built app starts. To download the builds, open the
repository's **Actions** tab, pick a run, and look under **Artifacts**:

- `GeniusControl-macOS`: a zip of `Genius Control.app` (Apple Silicon)
- `GeniusControl-Windows`: `GeniusControl.exe`
- `GeniusControl-Linux`: `genius-control`, its icon and `install.sh` (x86-64;
  built on Ubuntu 22.04, so it runs on that and newer distributions)

You can also start a run by hand from the Actions tab (*Run workflow*).

Settings are stored in `~/Library/Application Support/GeniusControl` (macOS),
`%APPDATA%\GeniusControl` (Windows) or `~/.config/GeniusControl` (Linux).

## Tabs

**Control**
- *Tuner Genius XL*: power (W) and SWR bar meters with peak markers, PTT and
  PTT OUT indicators (grey = off, red = on), ANT 1/2/3 selection (the active
  antenna has a red outline), C1 / L / C2 relay dials (0–255), and these buttons:
  - **STBY/OPR** switches the tuner between standby and operate.
  - **BYP** switches bypass on and off (orange = bypassed).
  - **TUNE** (the large button) starts an autotune cycle (red while tuning).
  - **C1 / L / C2 dials:** drag a dial up or down to move that relay bank
    (2 px per step; hold Shift for 8 px per step), or scroll on it for single
    steps. The TGXL only moves one step per command, about 100 ms each, so after
    a fast drag the dial shows where you are going and the tuner catches up.
    The dials are locked while the tuner runs a tune cycle.
- *Power Genius XL*: output power, SWR and drain current (Id) meters, the state (STANDBY / IDLE / TRANSMIT_A …), band, temperature, Vdd,
  Vac, and an **OPERATE / STANDBY** button.

- *FlexRadio*: RF power and tune power sliders (0–100; drag, click, scroll,
  arrow keys, or −/+). They follow changes made on the radio or in SmartSDR.
  The **TUNE** button next to the tune power slider keys and unkeys the
  radio's tune carrier (red while on). Below them are the TX frequency and mode.
- *Band Tune*: pick a band (160, 80, 40, 30, 20, 17, 15, 12, 10 or 6 m) and
  a step (10 kHz by default), then press **START**. Starting at the low band
  edge, it moves the FlexRadio's transmit slice to each frequency, waits for
  the TGXL to follow, presses TGXL TUNE, and waits for the tune cycle to
  finish. It keeps going until the next step would reach or pass the upper
  band edge. **STOP** ends the run; a tune already in progress finishes on
  its own. When the run finishes, stops or fails, the radio goes back to the
  frequency it started on. It won't start while the TGXL is in standby or
  bypass. Band edges are the US / Region 2 limits.

**Settings**: IP address and port for each device (TGXL, PGXL, Flex), enable/disable each device,
auto-connect, poll interval, line ending, meter scales, peak markers,
confirm-before-operate, and always-on-top. Save & Apply writes the settings to
`~/Library/Application Support/GeniusControl/settings.json` on macOS. The
Diagnostics box shows the raw status lines and a command/reply log.

## Protocol notes

Both devices use the 4O3A ASCII protocol: `C<seq>|cmd` → `R<seq>|<hex>|msg`.

| Device | Port | Status | Commands used |
|---|---|---|---|
| TGXL | 9010 | `status` → `S<n>\|status k=v …` | `autotune`, `activate ant=N`, `bypass set=0/1`, `operate set=0/1`, `tune relay=0/1/2 move=1/-1`, `info` |
| PGXL | 9008 | `status` → `R<seq>\|0\|k=v …` | `operate=0/1` |
| FlexRadio | 4992 | `sub tx all`, `sub slice all` → pushed `S<handle>\|transmit …` / `slice <n> …` | `transmit set rfpower=N`, `transmit set tunepower=N`, `transmit tune 0/1`, `slice tune <n> <MHz>`, `info` |

- Power is reported in **dBm** and converted to watts. SWR is reported as
  **return loss in dB** and converted to VSWR.
- Only one `status` request is kept in flight per device, because the PGXL
  drops the connection if it gets a second one before answering the first.
- Commands end with a bare LF, because the TGXL rejects CR.
- Drive power is not shown: the PGXL's status reply on port 9008 has no drive
  field (the radio gets it through a separate meter).
- Authentication (needed only for WAN connections) is not supported.

## Trying it without hardware

```bash
python3 tools/simulator.py
```

This starts fake TGXL (9010), PGXL (9008) and FlexRadio (4992) devices on
127.0.0.1. The fake
radio keys up periodically. Set all three addresses to `127.0.0.1` in Settings.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## App icon

The icon is made from a screenshot of the app (`assets/icon-source.png`).
`tools/make_icon.py` writes `icon.png` (window icon), `GeniusControl.icns`
(macOS) and `GeniusControl.ico` (Windows). To regenerate them from a new
screenshot on a Mac:

```bash
build/venv/bin/pip install pillow
build/venv/bin/python tools/make_icon.py path/to/screenshot.png
./build_app.sh
```
