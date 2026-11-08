"""Tkinter GUI: a Control tab for both devices and a Settings tab."""

from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from .devices import PowerGeniusClient, TunerGeniusClient
from .protocol import Event
from .settings import Settings, config_path
from .widgets import (AMBER, BG, BORDER, DIM, FONT, FONT_BIG, FONT_BOLD, FONT_SMALL, FONT_VALUE,
                      GREEN, GREY, ORANGE, PANEL, RED, TEXT, YELLOW, BarMeter, FlatButton,
                      RelayKnob, StatusDot, power_ticks, power_zones, swr_ticks, swr_zones)

STALE_AFTER_S = 3.0


def _panel(master, title):
    outer = tk.Frame(master, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    header = tk.Frame(outer, bg=PANEL)
    header.pack(fill="x", padx=10, pady=(8, 4))
    dot = StatusDot(header)
    dot.pack(side="left", padx=(0, 6))
    tk.Label(header, text=title, fg=TEXT, bg=PANEL, font=FONT_BIG).pack(side="left")
    info = tk.Label(header, text="Disconnected", fg=DIM, bg=PANEL, font=FONT_SMALL)
    info.pack(side="right")
    body = tk.Frame(outer, bg=PANEL)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    return outer, body, dot, info


def _meter_row(body, row, label, meter, unit_width=9):
    tk.Label(body, text=label, fg=TEXT, bg=PANEL, font=FONT_BOLD, width=4, anchor="w").grid(
        row=row, column=0, sticky="nw", pady=(2, 0))
    meter.grid(row=row, column=1, sticky="ew")
    value = tk.Label(body, text="--", fg=TEXT, bg=PANEL, font=FONT_VALUE, width=unit_width, anchor="e")
    value.grid(row=row, column=2, sticky="ne", padx=(6, 0))
    return value


def _fmt_w(watts):
    if watts is None:
        return "N/A"
    return f"{watts:,.0f} W" if watts >= 10 else f"{watts:.1f} W"


class TunerPanel:
    def __init__(self, master, app: "App"):
        self.app = app
        s = app.settings
        self.frame, body, self.dot, self.info = _panel(master, "Tuner Genius XL")
        body.columnconfigure(1, weight=1)

        self.pwr = BarMeter(body, 0, s.tgxl_power_scale_w, power_ticks(s.tgxl_power_scale_w),
                            power_zones(s.tgxl_power_scale_w))
        self.pwr_val = _meter_row(body, 0, "PWR", self.pwr)
        self.swr = BarMeter(body, 1.0, s.swr_scale_max, swr_ticks(s.swr_scale_max), swr_zones())
        self.swr_val = _meter_row(body, 1, "SWR", self.swr)

        status = tk.Frame(body, bg=PANEL)
        status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        self.ptt = tk.Label(status, text="PTT", fg=TEXT, bg=GREY, font=FONT_BOLD, width=5, pady=2)
        self.ptt.pack(side="left")
        self.freq = tk.Label(status, text="", fg=DIM, bg=PANEL, font=FONT)
        self.freq.pack(side="left", padx=10)
        self.state_lbl = tk.Label(status, text="", fg=DIM, bg=PANEL, font=FONT_BOLD)
        self.state_lbl.pack(side="right")

        ants = tk.Frame(body, bg=PANEL)
        ants.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.ant_btns = []
        for n in (1, 2, 3):
            ants.columnconfigure(n - 1, weight=1, uniform="ant")
            b = FlatButton(ants, f"ANT {n}", command=lambda n=n: self.app.tgxl.select_antenna(n),
                           bg="#101010", fg=DIM)
            b.grid(row=0, column=n - 1, sticky="ew", padx=2)
            self.ant_btns.append(b)

        bottom = tk.Frame(body, bg=PANEL)
        bottom.grid(row=4, column=0, columnspan=3, sticky="ew")
        knobs = tk.Frame(bottom, bg=PANEL)
        knobs.pack(side="left")
        self.c1 = RelayKnob(knobs, "C1")
        self.l = RelayKnob(knobs, "L")
        self.c2 = RelayKnob(knobs, "C2")
        for k in (self.c1, self.l, self.c2):
            k.pack(side="left", padx=2)

        btns = tk.Frame(bottom, bg=PANEL)
        btns.pack(side="right", fill="y")
        self.oper_btn = FlatButton(btns, "STBY", command=self.toggle_operate, fg=YELLOW, width=7)
        self.byp_btn = FlatButton(btns, "BYP", command=self.toggle_bypass, fg=ORANGE, width=7)
        self.tune_btn = FlatButton(btns, "TUNE", command=self.tune, fg=TEXT, width=7)
        self.oper_btn.grid(row=0, column=0, padx=2, pady=2)
        self.byp_btn.grid(row=0, column=1, padx=2, pady=2)
        self.tune_btn.grid(row=0, column=2, padx=2, pady=2)
        self.ptt_out = tk.Label(btns, text="PTT OUT", fg=TEXT, bg=GREY, font=FONT_BOLD, pady=3)
        self.ptt_out.grid(row=1, column=0, columnspan=3, sticky="ew", padx=2, pady=(6, 2))

        self.status: dict = {}
        self.last_status = 0.0
        self.set_connected(False)

    def apply_settings(self, s: Settings):
        self.pwr.configure_scale(0, s.tgxl_power_scale_w, power_ticks(s.tgxl_power_scale_w),
                                 power_zones(s.tgxl_power_scale_w))
        self.swr.configure_scale(1.0, s.swr_scale_max, swr_ticks(s.swr_scale_max))

    # Actions ---------------------------------------------------------------
    def toggle_operate(self):
        self.app.tgxl.set_operate(not self.status.get("operate", False))

    def toggle_bypass(self):
        self.app.tgxl.set_bypass(not self.status.get("bypass", False))

    def tune(self):
        self.app.tgxl.tune()

    # Updates ---------------------------------------------------------------
    def set_connected(self, connected: bool, info: str = ""):
        self.dot.set(GREEN if connected else RED)
        self.info.configure(text=info or ("Connected" if connected else "Disconnected"))
        for b in self.ant_btns + [self.oper_btn, self.byp_btn, self.tune_btn]:
            b.set_enabled(connected)
        if not connected:
            self.status = {}
            self.pwr.set(0)
            self.swr.set(1.0)
            self.pwr_val.configure(text="--")
            self.swr_val.configure(text="--")
            self.state_lbl.configure(text="OFFLINE", fg=DIM)
            for b in self.ant_btns:
                b.style(fg=DIM, bg="#101010", border=BORDER)

    def update(self, st: dict):
        self.status, self.last_status = st, time.monotonic()
        s = self.app.settings
        self.pwr.set(st["fwd_w"], st["peak_w"] if s.show_peak_power else None)
        self.pwr_val.configure(text=_fmt_w(st["fwd_w"]))
        self.swr.set(st["swr"])
        self.swr_val.configure(text=f"{st['swr']:.2f}" if st["fwd_w"] > 0.5 else "--")
        self.ptt.configure(bg=RED if st["ptt"] else GREY)
        self.ptt_out.configure(bg=RED if st["ptt"] else GREY)
        freq = st.get("freq_khz") or 0
        self.freq.configure(text=f"{float(freq) / 1000:.3f} MHz" if freq else "")

        for n, b in enumerate(self.ant_btns, start=1):
            if n == st["antenna"]:
                b.style(fg=TEXT, bg="#1c1c1c", border=RED)
            else:
                b.style(fg=DIM, bg="#101010", border=BORDER)

        if st["operate"]:
            self.oper_btn.style(text="OPR", fg="white", bg=GREEN)
        else:
            self.oper_btn.style(text="STBY", fg=YELLOW, bg="#262626")
        if st["bypass"]:
            self.byp_btn.style(text="BYP", fg="white", bg=ORANGE)
        else:
            self.byp_btn.style(text="BYP", fg=ORANGE, bg="#262626")
        if st["tuning"]:
            self.tune_btn.style(text="TUNING", fg="white", bg=RED)
        else:
            self.tune_btn.style(text="TUNE", fg=TEXT, bg="#262626")

        if st["tuning"]:
            self.state_lbl.configure(text="TUNING", fg=RED)
        elif st["bypass"]:
            self.state_lbl.configure(text="BYPASS", fg=ORANGE)
        elif st["operate"]:
            self.state_lbl.configure(text="OPERATE", fg=GREEN)
        else:
            self.state_lbl.configure(text="STANDBY", fg=YELLOW)

        self.c1.set(st["c1"])
        self.l.set(st["l"])
        self.c2.set(st["c2"])


class AmpPanel:
    def __init__(self, master, app: "App"):
        self.app = app
        s = app.settings
        self.frame, body, self.dot, self.info = _panel(master, "Power Genius XL")
        body.columnconfigure(1, weight=1)

        self.pwr = BarMeter(body, 0, s.pgxl_power_scale_w, power_ticks(s.pgxl_power_scale_w),
                            power_zones(s.pgxl_power_scale_w))
        self.pwr_val = _meter_row(body, 0, "OUT", self.pwr)
        self.drv = BarMeter(body, 0, s.pgxl_drive_scale_w, power_ticks(s.pgxl_drive_scale_w),
                            power_zones(s.pgxl_drive_scale_w))
        self.drv_val = _meter_row(body, 1, "DRV", self.drv)
        self.swr = BarMeter(body, 1.0, s.swr_scale_max, swr_ticks(s.swr_scale_max), swr_zones())
        self.swr_val = _meter_row(body, 2, "SWR", self.swr)
        self.id = BarMeter(body, 0, s.pgxl_current_scale_a, self._id_ticks(s.pgxl_current_scale_a),
                           self._id_zones(s.pgxl_current_scale_a))
        self.id_val = _meter_row(body, 3, "Id", self.id)

        bottom = tk.Frame(body, bg=PANEL)
        bottom.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.state_lbl = tk.Label(bottom, text="OFFLINE", fg=TEXT, bg=GREY, font=FONT_BOLD,
                                  width=12, pady=3)
        self.state_lbl.pack(side="left")
        self.band_lbl = tk.Label(bottom, text="", fg=DIM, bg=PANEL, font=FONT)
        self.band_lbl.pack(side="left", padx=10)
        self.env_lbl = tk.Label(bottom, text="", fg=TEXT, bg=PANEL, font=FONT_SMALL, justify="right")
        self.env_lbl.pack(side="left", expand=True)
        self.oper_btn = FlatButton(bottom, "STANDBY", command=self.toggle_operate, fg="black",
                                   bg=YELLOW, width=10)
        self.oper_btn.pack(side="right")

        self.status: dict = {}
        self.last_status = 0.0
        self.set_connected(False)

    @staticmethod
    def _id_ticks(max_a):
        return [(max_a * i / 7, f"{max_a * i / 7:.0f}") for i in range(8)]

    @staticmethod
    def _id_zones(max_a):
        return [(max_a * 5 / 7, "#2fa3e0", "#0f2a3d"), (max_a * 6 / 7, AMBER, "#3d3115"),
                (max_a * 10, RED, "#3d1616")]

    def apply_settings(self, s: Settings):
        self.pwr.configure_scale(0, s.pgxl_power_scale_w, power_ticks(s.pgxl_power_scale_w),
                                 power_zones(s.pgxl_power_scale_w))
        self.drv.configure_scale(0, s.pgxl_drive_scale_w, power_ticks(s.pgxl_drive_scale_w),
                                 power_zones(s.pgxl_drive_scale_w))
        self.swr.configure_scale(1.0, s.swr_scale_max, swr_ticks(s.swr_scale_max))
        self.id.configure_scale(0, s.pgxl_current_scale_a, self._id_ticks(s.pgxl_current_scale_a),
                                self._id_zones(s.pgxl_current_scale_a))

    def toggle_operate(self):
        going_online = not self.status.get("operate", False)
        if going_online and self.app.settings.confirm_operate:
            if not messagebox.askyesno("Power Genius XL", "Put the amplifier in OPERATE?"):
                return
        self.app.pgxl.set_operate(going_online)

    def set_connected(self, connected: bool, info: str = ""):
        self.dot.set(GREEN if connected else RED)
        self.info.configure(text=info or ("Connected" if connected else "Disconnected"))
        self.oper_btn.set_enabled(connected)
        if not connected:
            self.status = {}
            for m, start in ((self.pwr, 0), (self.drv, 0), (self.swr, 1.0), (self.id, 0)):
                m.set(start)
            for v in (self.pwr_val, self.drv_val, self.swr_val, self.id_val):
                v.configure(text="--")
            self.state_lbl.configure(text="OFFLINE", bg=GREY, fg=TEXT)
            self.oper_btn.style(text="STANDBY", fg="black", bg=GREY)
            self.env_lbl.configure(text="")
            self.band_lbl.configure(text="")

    def update(self, st: dict):
        self.status, self.last_status = st, time.monotonic()
        s = self.app.settings
        self.pwr.set(st["fwd_w"], st["peak_w"] if s.show_peak_power else None)
        self.pwr_val.configure(text=_fmt_w(st["fwd_w"]))
        if st["drive_w"] is None:
            self.drv.set(0)
            self.drv_val.configure(text="N/A")
        else:
            self.drv.set(st["drive_w"])
            self.drv_val.configure(text=_fmt_w(st["drive_w"]))
        self.swr.set(st["swr"])
        self.swr_val.configure(text=f"{st['swr']:.2f}" if st["fwd_w"] > 0.5 else "--")
        self.id.set(st["id_a"], st["peak_id_a"] if s.show_peak_power else None)
        self.id_val.configure(text=f"{st['id_a']:.1f} A")

        state = st["state"]
        if st["fault"]:
            self.state_lbl.configure(text=state if state != "IDLE" else "FAULT", bg=RED, fg="white")
        elif st["transmitting"]:
            self.state_lbl.configure(text=state.replace("_", " "), bg=RED, fg="white")
        elif st["operate"]:
            self.state_lbl.configure(text=state, bg=GREEN, fg="white")
        else:
            self.state_lbl.configure(text=state, bg=GREY, fg=TEXT)

        if st["operate"]:
            self.oper_btn.style(text="OPERATE", fg="white", bg=GREEN)
        else:
            self.oper_btn.style(text="STANDBY", fg="black", bg=YELLOW)

        bands = [f"{p} {b}m" for p, b in (("A", st["band_a"]), ("B", st["band_b"])) if b not in ("", 0)]
        meffa = f"   MEffA {st['meffa']}" if st["meffa"] not in ("", "OFF") else ""
        self.band_lbl.configure(text="  ".join(bands) + meffa)
        temp = st["temp_c"]
        temp_txt = f"{float(temp):.1f} °C" if temp != "" else "-- °C"
        self.env_lbl.configure(text=f"{temp_txt}   Vdd {st['vdd']} V   Vac {st['vac']} V")


class SettingsTab:
    def __init__(self, master, app: "App"):
        self.app = app
        self.frame = ttk.Frame(master, padding=12)
        self.vars: dict[str, tk.Variable] = {}
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

        net = ttk.LabelFrame(f, text="Network", padding=10)
        net.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        self._device_rows(net, 0, "Tuner Genius XL", "tgxl")
        self._device_rows(net, 3, "Power Genius XL", "pgxl")
        ttk.Separator(net).grid(row=6, column=0, columnspan=4, sticky="ew", pady=8)
        self._check(net, 7, "Connect automatically at startup", "auto_connect")
        self._entry(net, 8, "Status poll interval (ms)", "poll_interval_ms", width=7)
        ttk.Label(net, text="Line ending").grid(row=9, column=0, sticky="w", pady=2)
        le = tk.StringVar(value=app.settings.line_ending)
        self.vars["line_ending"] = le
        ttk.Combobox(net, textvariable=le, values=["LF", "CRLF"], width=6, state="readonly").grid(
            row=9, column=1, sticky="w")

        disp = ttk.LabelFrame(f, text="Display & preferences", padding=10)
        disp.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 8))
        self._entry(disp, 0, "TGXL power scale (W)", "tgxl_power_scale_w", width=7)
        self._entry(disp, 1, "PGXL output scale (W)", "pgxl_power_scale_w", width=7)
        self._entry(disp, 2, "PGXL drive scale (W)", "pgxl_drive_scale_w", width=7)
        self._entry(disp, 3, "PGXL current scale (A)", "pgxl_current_scale_a", width=7)
        self._entry(disp, 4, "SWR scale maximum", "swr_scale_max", width=7)
        self._check(disp, 5, "Show peak-hold markers", "show_peak_power")
        self._check(disp, 6, "Confirm before amplifier OPERATE", "confirm_operate")
        self._check(disp, 7, "Keep window on top", "always_on_top")

        bar = ttk.Frame(f)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(bar, text="Save & Apply", command=self.save).pack(side="left")
        ttk.Button(bar, text="Revert", command=self.load_from_settings).pack(side="left", padx=6)
        ttk.Button(bar, text="Defaults", command=self.defaults).pack(side="left")
        ttk.Button(bar, text="Reconnect", command=app.connect_all).pack(side="right")
        ttk.Button(bar, text="Disconnect", command=app.disconnect_all).pack(side="right", padx=6)
        self.saved_lbl = ttk.Label(f, text=f"Settings file: {config_path()}", foreground="gray")
        self.saved_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 8))

        diag = ttk.LabelFrame(f, text="Diagnostics", padding=6)
        diag.grid(row=3, column=0, columnspan=2, sticky="nsew")
        f.rowconfigure(3, weight=1)
        diag.columnconfigure(0, weight=1)
        diag.rowconfigure(2, weight=1)
        self.raw_tgxl = ttk.Label(diag, text="TGXL status: -", wraplength=760, font=("Menlo", 10))
        self.raw_tgxl.grid(row=0, column=0, columnspan=2, sticky="w")
        self.raw_pgxl = ttk.Label(diag, text="PGXL status: -", wraplength=760, font=("Menlo", 10))
        self.raw_pgxl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 4))
        self.log = tk.Text(diag, height=8, font=("Menlo", 10), state="disabled", wrap="none")
        self.log.grid(row=2, column=0, sticky="nsew")
        sb = ttk.Scrollbar(diag, command=self.log.yview)
        sb.grid(row=2, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        self.load_from_settings()

    # Builders ----------------------------------------------------------------
    def _device_rows(self, parent, row, title, prefix):
        self._check(parent, row, f"Enable {title}", f"{prefix}_enabled")
        self._entry(parent, row + 1, "IP address / hostname", f"{prefix}_host", width=18)
        self._entry(parent, row + 2, "TCP port", f"{prefix}_port", width=7)

    def _entry(self, parent, row, label, key, width=10):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=(16, 8))
        var = tk.StringVar()
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="w", pady=2)

    def _check(self, parent, row, label, key):
        var = tk.BooleanVar()
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).grid(row=row, column=0, columnspan=2,
                                                               sticky="w", pady=2)

    # Actions -----------------------------------------------------------------
    def load_from_settings(self, settings: Settings | None = None):
        s = settings or self.app.settings
        for key, var in self.vars.items():
            var.set(getattr(s, key))

    def defaults(self):
        self.load_from_settings(Settings())

    def collect(self) -> Settings | None:
        s = Settings()
        for key, var in self.vars.items():
            default = getattr(s, key)
            raw = var.get()
            try:
                if isinstance(default, bool):
                    value = bool(raw)
                elif isinstance(default, int):
                    value = int(str(raw).strip())
                elif isinstance(default, float):
                    value = float(str(raw).strip())
                else:
                    value = str(raw).strip()
            except ValueError:
                messagebox.showerror("Settings", f"Invalid value for {key.replace('_', ' ')}: {raw!r}")
                return None
            setattr(s, key, value)
        if s.poll_interval_ms < 100:
            s.poll_interval_ms = 100
        if s.swr_scale_max <= 1.5:
            s.swr_scale_max = 3.0
        return s

    def save(self):
        s = self.collect()
        if not s:
            return
        old = self.app.settings
        self.app.settings = s
        path = s.save()
        self.saved_lbl.configure(text=f"Saved to {path}")
        self.load_from_settings()
        self.app.apply_settings(reconnect=self._network_changed(old, s))

    @staticmethod
    def _network_changed(a: Settings, b: Settings) -> bool:
        keys = ("tgxl_enabled", "tgxl_host", "tgxl_port", "pgxl_enabled", "pgxl_host", "pgxl_port",
                "poll_interval_ms", "line_ending")
        return any(getattr(a, k) != getattr(b, k) for k in keys)

    def append_log(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S ") + line + "\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 500:
            self.log.delete("1.0", f"{lines - 500}.0")
        self.log.see("end")
        self.log.configure(state="disabled")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = Settings.load()
        self.events: "queue.Queue[Event]" = queue.Queue()
        self.tgxl = TunerGeniusClient(self.events)
        self.pgxl = PowerGeniusClient(self.events)

        root.title("Genius Control - TGXL / PGXL")
        root.configure(bg=BG)
        root.minsize(560, 640)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        control = tk.Frame(nb, bg=BG)
        self.tuner = TunerPanel(control, self)
        self.amp = AmpPanel(control, self)
        self.tuner.frame.pack(fill="x", padx=6, pady=(6, 4))
        self.amp.frame.pack(fill="x", padx=6, pady=(4, 6))
        self.statusbar = tk.Label(control, text="", fg=DIM, bg=BG, font=FONT_SMALL, anchor="w")
        self.statusbar.pack(fill="x", side="bottom", padx=8, pady=(0, 4))
        nb.add(control, text="  Control  ")

        self.settings_tab = SettingsTab(nb, self)
        nb.add(self.settings_tab.frame, text="  Settings  ")

        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.apply_settings(reconnect=self.settings.auto_connect)
        if not self.settings.auto_connect:
            self.statusbar.configure(text="Auto-connect is off. Use Settings > Reconnect.")
        root.after(50, self._drain)
        root.after(1000, self._watchdog)

    def apply_settings(self, reconnect: bool):
        s = self.settings
        self.root.attributes("-topmost", s.always_on_top)
        self.tuner.apply_settings(s)
        self.amp.apply_settings(s)
        if reconnect:
            self.connect_all()

    def connect_all(self):
        s = self.settings
        self.disconnect_all()
        poll = s.poll_interval_ms / 1000.0
        if s.tgxl_enabled and s.tgxl_host:
            self.tgxl.start(s.tgxl_host, s.tgxl_port, poll, s.terminator)
            self.tuner.info.configure(text=f"Connecting to {s.tgxl_host}…")
        if s.pgxl_enabled and s.pgxl_host:
            self.pgxl.start(s.pgxl_host, s.pgxl_port, poll, s.terminator)
            self.amp.info.configure(text=f"Connecting to {s.pgxl_host}…")

    def disconnect_all(self):
        for client in (self.tgxl, self.pgxl):
            client.stop()
            client.connected = False
        self.tuner.set_connected(False)
        self.amp.set_connected(False)

    def _panel_for(self, device):
        return self.tuner if device == "tgxl" else self.amp

    def _drain(self):
        try:
            for _ in range(200):
                ev = self.events.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _handle(self, ev: Event):
        panel = self._panel_for(ev.device)
        name = ev.device.upper()
        if ev.kind == "connected":
            fw = ev.data.get("firmware") or "?"
            panel.set_connected(True, f"{ev.data.get('host')}   FW {fw}")
            self.settings_tab.append_log(f"{name} connected ({ev.data.get('host')}, FW {fw})")
        elif ev.kind == "disconnected":
            panel.set_connected(False, "Disconnected - retrying…")
            self.settings_tab.append_log(f"{name} disconnected")
        elif ev.kind == "status":
            if self._client(ev.device).connected:
                panel.update(ev.data)
            label = self.settings_tab.raw_tgxl if ev.device == "tgxl" else self.settings_tab.raw_pgxl
            label.configure(text=f"{name} status: {ev.text}")
        elif ev.kind == "error":
            self.statusbar.configure(text=f"{name}: {ev.text}", fg=RED)
            self.settings_tab.append_log(f"{name} ERROR {ev.text}")
        elif ev.kind in ("log", "reply", "info"):
            self.settings_tab.append_log(f"{name} {ev.text}")
            if ev.kind == "reply" and ev.data.get("code") == 0:
                self.statusbar.configure(text=f"{name}: '{ev.data['command']}' OK", fg=DIM)

    def _client(self, device):
        return self.tgxl if device == "tgxl" else self.pgxl

    def _watchdog(self):
        now = time.monotonic()
        for device, panel in (("tgxl", self.tuner), ("pgxl", self.amp)):
            client = self._client(device)
            if client.connected:
                stale = panel.last_status and now - panel.last_status > STALE_AFTER_S
                panel.dot.set(AMBER if stale else GREEN)
        self.root.after(1000, self._watchdog)

    def quit(self):
        for client in (self.tgxl, self.pgxl):
            client.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
