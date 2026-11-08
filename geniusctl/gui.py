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
    header.pack(fill="x", padx=8, pady=(4, 2))
    dot = StatusDot(header)
    dot.pack(side="left", padx=(0, 6))
    tk.Label(header, text=title, fg=TEXT, bg=PANEL, font=FONT_BIG).pack(side="left")
    info = tk.Label(header, text="Disconnected", fg=DIM, bg=PANEL, font=FONT_SMALL, width=1, anchor="e")
    info.pack(side="right", fill="x", expand=True, padx=(8, 0))
    body = tk.Frame(outer, bg=PANEL)
    body.pack(fill="both", expand=True, padx=8, pady=(0, 6))
    return outer, body, dot, info


def _meter_row(body, row, label, meter, unit_width=8):
    tk.Label(body, text=label, fg=TEXT, bg=PANEL, font=("Helvetica", 10, "bold"), anchor="w").grid(
        row=row, column=0, sticky="nw", padx=(0, 2))
    meter.grid(row=row, column=1, sticky="ew")
    value = tk.Label(body, text="--", fg=TEXT, bg=PANEL, font=FONT_VALUE, width=unit_width, anchor="e")
    value.grid(row=row, column=2, sticky="ne", padx=(4, 0))
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
        status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 2))
        self.ptt = tk.Label(status, text="PTT", fg=TEXT, bg=GREY, font=FONT_BOLD, width=5, pady=1)
        self.ptt.pack(side="left")
        self.freq = tk.Label(status, text="", fg=DIM, bg=PANEL, font=FONT)
        self.freq.pack(side="left", padx=10)
        self.state_lbl = tk.Label(status, text="", fg=DIM, bg=PANEL, font=FONT_BOLD)
        self.state_lbl.pack(side="right")

        ants = tk.Frame(body, bg=PANEL)
        ants.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 4))
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
            k.pack(side="left", padx=0)

        btns = tk.Frame(bottom, bg=PANEL)
        btns.pack(side="right", fill="y")
        self.oper_btn = FlatButton(btns, "STBY", command=self.toggle_operate, fg=YELLOW, width=5)
        self.byp_btn = FlatButton(btns, "BYP", command=self.toggle_bypass, fg=ORANGE, width=5)
        self.tune_btn = FlatButton(btns, "TUNE", command=self.tune, fg=TEXT, width=6)
        self.oper_btn.grid(row=0, column=0, padx=2, pady=2)
        self.byp_btn.grid(row=0, column=1, padx=2, pady=2)
        self.tune_btn.grid(row=0, column=2, padx=2, pady=2)
        self.ptt_out = tk.Label(btns, text="PTT OUT", fg=TEXT, bg=GREY, font=FONT_BOLD, pady=1)
        self.ptt_out.grid(row=1, column=0, columnspan=3, sticky="ew", padx=2, pady=(4, 0))

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
        self.swr = BarMeter(body, 1.0, s.swr_scale_max, swr_ticks(s.swr_scale_max), swr_zones())
        self.swr_val = _meter_row(body, 1, "SWR", self.swr)
        self.id = BarMeter(body, 0, s.pgxl_current_scale_a, self._id_ticks(s.pgxl_current_scale_a),
                           self._id_zones(s.pgxl_current_scale_a))
        self.id_val = _meter_row(body, 2, "Id", self.id)

        bottom = tk.Frame(body, bg=PANEL)
        bottom.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.state_lbl = tk.Label(bottom, text="OFFLINE", fg=TEXT, bg=GREY, font=FONT_BOLD,
                                  width=11, pady=3)
        self.state_lbl.pack(side="left")
        self.oper_btn = FlatButton(bottom, "STANDBY", command=self.toggle_operate, fg="black",
                                   bg=YELLOW, width=9)
        self.oper_btn.pack(side="right")
        info = tk.Frame(bottom, bg=PANEL)
        info.pack(side="left", expand=True)
        self.band_lbl = tk.Label(info, text="", fg=DIM, bg=PANEL, font=FONT_SMALL)
        self.band_lbl.pack()
        self.env_lbl = tk.Label(info, text="", fg=TEXT, bg=PANEL, font=FONT_SMALL)
        self.env_lbl.pack()

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
            for m, start in ((self.pwr, 0), (self.swr, 1.0), (self.id, 0)):
                m.set(start)
            for v in (self.pwr_val, self.swr_val, self.id_val):
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
        self.band_lbl.configure(text=("  ".join(bands) + meffa).strip())
        temp = st["temp_c"]
        temp_txt = f"{float(temp):.1f} °C" if temp != "" else "-- °C"
        self.env_lbl.configure(text=f"{temp_txt}  Vdd {st['vdd']}  Vac {st['vac']}")


class SettingsTab:
    def __init__(self, master, app: "App"):
        self.app = app
        self.frame = ttk.Frame(master, padding=6)
        self.vars: dict[str, tk.Variable] = {}
        self.raw = {"tgxl": "-", "pgxl": "-"}
        f = self.frame
        f.columnconfigure(0, weight=1)

        net = ttk.LabelFrame(f, text="Network", padding=(8, 4))
        net.grid(row=0, column=0, sticky="ew")
        ttk.Label(net, text="Address").grid(row=0, column=1, sticky="w")
        ttk.Label(net, text="Port").grid(row=0, column=2, sticky="w")
        self._device_row(net, 1, "TGXL", "tgxl")
        self._device_row(net, 2, "PGXL", "pgxl")
        opts = ttk.Frame(net)
        opts.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self._check(opts, 0, 0, "Auto-connect", "auto_connect")
        self._entry(opts, 0, 1, "Poll ms", "poll_interval_ms", width=5)
        ttk.Label(opts, text="EOL").grid(row=0, column=3, sticky="e", padx=(8, 2))
        le = tk.StringVar(value=app.settings.line_ending)
        self.vars["line_ending"] = le
        ttk.Combobox(opts, textvariable=le, values=["LF", "CRLF"], width=5, state="readonly").grid(
            row=0, column=4, sticky="w")

        disp = ttk.LabelFrame(f, text="Display & preferences", padding=(8, 4))
        disp.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._entry(disp, 0, 0, "TGXL W", "tgxl_power_scale_w", width=5)
        self._entry(disp, 0, 1, "PGXL W", "pgxl_power_scale_w", width=5)
        self._entry(disp, 1, 0, "Id max A", "pgxl_current_scale_a", width=5)
        self._entry(disp, 1, 1, "SWR max", "swr_scale_max", width=5)
        self._check(disp, 2, 0, "Peak markers", "show_peak_power")
        self._check(disp, 2, 1, "Confirm OPERATE", "confirm_operate")
        self._check(disp, 3, 0, "Keep on top", "always_on_top")

        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(bar, text="Save & Apply", command=self.save).pack(side="left")
        ttk.Button(bar, text="Disconnect", command=app.disconnect_all).pack(side="right")
        ttk.Button(bar, text="Reconnect", command=app.connect_all).pack(side="right", padx=4)

        diag = ttk.LabelFrame(f, text="Diagnostics", padding=4)
        diag.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        f.rowconfigure(3, weight=1)
        diag.columnconfigure(0, weight=1)
        diag.rowconfigure(1, weight=1)
        self.raw_text = tk.Text(diag, height=2, width=40, font=("Menlo", 9), state="disabled",
                                wrap="char")
        self.raw_text.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.log = tk.Text(diag, height=3, width=40, font=("Menlo", 9), state="disabled", wrap="none")
        self.log.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(diag, command=self.log.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        self.load_from_settings()
        self.append_log(f"Settings file: {config_path()}")

    # Builders ----------------------------------------------------------------
    def _device_row(self, parent, row, name, prefix):
        var = tk.BooleanVar()
        self.vars[f"{prefix}_enabled"] = var
        ttk.Checkbutton(parent, text=name, variable=var).grid(row=row, column=0, sticky="w",
                                                              padx=(0, 6), pady=1)
        for col, key, width in ((1, f"{prefix}_host", 16), (2, f"{prefix}_port", 5)):
            v = tk.StringVar()
            self.vars[key] = v
            ttk.Entry(parent, textvariable=v, width=width).grid(row=row, column=col, sticky="w",
                                                                padx=(0, 4), pady=1)

    def _entry(self, parent, row, col, label, key, width=6):
        ttk.Label(parent, text=label).grid(row=row, column=col * 3, sticky="w", pady=1,
                                           padx=(0 if col == 0 else 10, 4))
        var = tk.StringVar()
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=col * 3 + 1,
                                                              sticky="w", pady=1)

    def _check(self, parent, row, col, label, key):
        var = tk.BooleanVar()
        self.vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).grid(
            row=row, column=col * 3, columnspan=2, sticky="w", pady=1,
            padx=(0 if col == 0 else 10, 0))

    def set_raw(self, device: str, text: str):
        self.raw[device] = text
        self.raw_text.configure(state="normal")
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("end", f"TGXL: {self.raw['tgxl']}\nPGXL: {self.raw['pgxl']}")
        self.raw_text.configure(state="disabled")

    # Actions -----------------------------------------------------------------
    def load_from_settings(self, settings: Settings | None = None):
        s = settings or self.app.settings
        for key, var in self.vars.items():
            var.set(getattr(s, key))

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
        self.append_log(f"Settings saved to {path}")
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
        root.minsize(380, 400)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        control = tk.Frame(nb, bg=BG)
        self.tuner = TunerPanel(control, self)
        self.amp = AmpPanel(control, self)
        self.tuner.frame.pack(fill="x", padx=4, pady=(4, 2))
        self.amp.frame.pack(fill="x", padx=4, pady=(2, 2))
        self.statusbar = tk.Label(control, text="", fg=DIM, bg=BG, font=FONT_SMALL, anchor="w", width=1)
        self.statusbar.pack(fill="x", side="bottom", padx=6, pady=(0, 2))
        nb.add(control, text="Control")

        self.settings_tab = SettingsTab(nb, self)
        nb.add(self.settings_tab.frame, text="Settings")

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
            self.settings_tab.set_raw(ev.device, ev.text)
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
