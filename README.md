# Genius Control — TGXL / PGXL network utility

A small desktop app that monitors and controls a **4O3A Tuner Genius XL** and a
**Power Genius XL** over the network. It is pure Python with tkinter: no
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

The app refuses to start on an old Tk and explains why. `build_app.sh` looks
for a suitable Python on its own; set `PYTHON=/path/to/python3` to choose one.

### macOS app

```bash
./build_app.sh
```

This builds a self-contained `dist/Genius Control.app` with PyInstaller (it
creates its own virtualenv in `build/` the first time). Drag it to
/Applications and launch it like any other app.

## Tabs

**Control**
- *Tuner Genius XL*: power (W) and SWR bar meters with peak markers, PTT and
  PTT OUT indicators (grey = off, red = on), ANT 1/2/3 selection (the active
  antenna has a red outline), C1 / L / C2 relay dials (0–255), and these buttons:
  - **STBY/OPR** switches the tuner between standby and operate.
  - **BYP** switches bypass on and off (orange = bypassed).
  - **TUNE** (the large button) starts an autotune cycle (red while tuning).
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
| TGXL | 9010 | `status` → `S<n>\|status k=v …` | `autotune`, `activate ant=N`, `bypass set=0/1`, `operate set=0/1`, `info` |
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

The icon is made from a screenshot of the app (`assets/icon-source.png`). To
regenerate it from a new screenshot:

```bash
build/venv/bin/pip install pillow
build/venv/bin/python tools/make_icon.py path/to/screenshot.png
./build_app.sh
```
