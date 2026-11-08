# Genius Control — TGXL / PGXL network utility

A small desktop app that monitors and controls a **4O3A Tuner Genius XL** and a
**Power Genius XL** over the network. It is pure Python with tkinter: no
packages to install. It runs on macOS, Windows and Linux with Python 3.10+.

```bash
python3 genius_control.py
```

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
  - **TUNE** starts an autotune cycle (red while tuning).
- *Power Genius XL*: output power, SWR and drain current (Id) meters, the state (STANDBY / IDLE / TRANSMIT_A …), band, temperature, Vdd,
  Vac, and an **OPERATE / STANDBY** button.

**Settings**: IP address and port for each device, enable/disable each device,
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

This starts fake TGXL (9010) and PGXL (9008) devices on 127.0.0.1. The fake
radio keys up periodically. Set both addresses to `127.0.0.1` in Settings.

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
