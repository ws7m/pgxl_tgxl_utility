"""Canvas-drawn widgets: bar meters, relay dials, and flat colored buttons.

Native buttons on macOS ignore background colors, so the toggle buttons here
are drawn with tk.Label so they can show the grey/green/red state coloring.
"""

from __future__ import annotations

import math
import tkinter as tk

# Palette (dark, in the spirit of the 4O3A utilities)
BG = "#0a0a0a"
PANEL = "#151515"
BORDER = "#3a3a3a"
TEXT = "#e6e6e6"
DIM = "#8a8a8a"
GREY = "#5a5a5a"
GREEN = "#1f9d3a"
GREEN_DIM = "#173a20"
AMBER = "#d9a020"
AMBER_DIM = "#3d3115"
RED = "#d02a2a"
RED_DIM = "#3d1616"
BLUE = "#2e86de"
BLUE_DIM = "#0f2a3d"
KNOB = "#0e3f86"
YELLOW = "#d6c84a"
ORANGE = "#d27a2a"

FONT = ("Helvetica", 12)
FONT_SMALL = ("Helvetica", 9)
FONT_BOLD = ("Helvetica", 12, "bold")
FONT_BIG = ("Helvetica", 13, "bold")
FONT_VALUE = ("Menlo", 13, "bold")


class FlatButton(tk.Label):
    """A clickable label with explicit colors that work on every platform."""

    def __init__(self, master, text, command=None, width=8, fg=TEXT, bg="#262626",
                 font=FONT_BOLD, **kw):
        super().__init__(master, text=text, width=width, fg=fg, bg=bg, font=font,
                         relief="flat", bd=0, padx=4, pady=3, cursor="hand2",
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        self.command = command
        self._enabled = True
        self._base = (fg, bg)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._enabled and self.configure(highlightbackground=TEXT))
        self.bind("<Leave>", lambda e: self.configure(highlightbackground=self._border))
        self._border = BORDER

    def _click(self, _event):
        if self._enabled and self.command:
            self.command()

    def style(self, fg=None, bg=None, border=None, text=None):
        cfg = {}
        if fg:
            cfg["fg"] = fg
        if bg:
            cfg["bg"] = bg
        if border:
            self._border = border
            cfg["highlightbackground"] = border
        if text is not None:
            cfg["text"] = text
        self.configure(**cfg)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")


class BarMeter(tk.Canvas):
    """Horizontal bar meter with colored zones, tick labels and a peak marker.

    zones: list of (upper_value, bright_color, dim_color) in ascending order.
    ticks: list of (value, label).
    """

    def __init__(self, master, vmin, vmax, ticks, zones, width=250, height=31, log=False):
        super().__init__(master, width=width, height=height, bg=PANEL, highlightthickness=0)
        self.vmin, self.vmax = vmin, vmax
        self.ticks, self.zones = ticks, zones
        self.w, self.h = width, height
        self.pad = 10
        self.bar_h = 13
        self.value = vmin
        self.peak = None
        self.bind("<Configure>", self._resize)
        self._draw()

    def _resize(self, event):
        self.w = event.width
        self._draw()

    def configure_scale(self, vmin, vmax, ticks, zones=None):
        self.vmin, self.vmax, self.ticks = vmin, vmax, ticks
        if zones:
            self.zones = zones
        self._draw()

    def _x(self, v):
        span = (self.vmax - self.vmin) or 1
        frac = min(1.0, max(0.0, (v - self.vmin) / span))
        return self.pad + frac * (self.w - 2 * self.pad)

    def set(self, value, peak=None):
        self.value, self.peak = value, peak
        self._draw()

    def _draw(self):
        self.delete("all")
        y0, y1 = 2, 2 + self.bar_h
        lo = self.vmin
        for hi, bright, dim in self.zones:
            x0, x1 = self._x(lo), self._x(min(hi, self.vmax))
            if x1 > x0:
                self.create_rectangle(x0, y0, x1, y1, fill=dim, width=0)
                fill_to = min(x1, self._x(self.value))
                if fill_to > x0:
                    self.create_rectangle(x0, y0, fill_to, y1, fill=bright, width=0)
            lo = hi
            if lo >= self.vmax:
                break
        if self.peak is not None and self.peak > self.vmin:
            px = self._x(self.peak)
            self.create_line(px, y0 - 2, px, y1 + 2, fill=TEXT, width=2)
        for value, label in self.ticks:
            x = self._x(value)
            self.create_line(x, y1, x, y1 + 2, fill=DIM)
            anchor = "n"
            if value <= self.vmin:
                anchor = "nw"
                x -= 2
            elif value >= self.vmax:
                anchor = "ne"
                x += 2
            self.create_text(x, y1 + 2, text=label, fill=TEXT, font=FONT_SMALL, anchor=anchor)


class RelayKnob(tk.Canvas):
    """Read-only dial showing a relay bank position (0-255), like the TGXL C1/L/C2."""

    def __init__(self, master, label, size=46, vmax=255):
        super().__init__(master, width=size + 8, height=size + 18, bg=PANEL, highlightthickness=0)
        self.label, self.size, self.vmax = label, size, vmax
        self.value = 0
        self._draw()

    def set(self, value):
        if value != self.value:
            self.value = value
            self._draw()

    def _draw(self):
        self.delete("all")
        s, o = self.size, 4
        cx, cy, r = o + s / 2, o + s / 2, s / 2
        self.create_oval(o, o, o + s, o + s, fill=KNOB, outline="#1a5bb5", width=2)
        # 270-degree sweep from lower-left (min) to lower-right (max)
        frac = min(1.0, max(0.0, self.value / self.vmax))
        angle = math.radians(225 - 270 * frac)
        x = cx + (r - 6) * math.cos(angle)
        y = cy - (r - 6) * math.sin(angle)
        self.create_line(cx - (x - cx) * 0.25, cy - (y - cy) * 0.25, x, y,
                         fill="white", width=2, capstyle="round")
        self.create_text(cx, o + s + 8, text=f"{self.label}  {self.value}",
                         fill=TEXT, font=FONT_SMALL)


class StatusDot(tk.Canvas):
    def __init__(self, master, size=12):
        super().__init__(master, width=size, height=size, bg=master["bg"], highlightthickness=0)
        self._oval = self.create_oval(1, 1, size - 1, size - 1, fill=GREY, width=0)

    def set(self, color):
        self.itemconfigure(self._oval, fill=color)


def power_ticks(max_w: int):
    """Five evenly spaced tick labels like 0 / 500 / 1K / 1K5 / 2K."""
    def fmt(v):
        if v >= 1000:
            k, rem = divmod(int(v), 1000)
            return f"{k}K" + (f"{rem // 100}" if rem else "")
        return f"{int(v)}"
    return [(max_w * i / 4, fmt(max_w * i / 4)) for i in range(5)]


def power_zones(max_w: float):
    return [(max_w * 0.5, BLUE, BLUE_DIM), (max_w * 0.75, AMBER, AMBER_DIM), (max_w * 10, RED, RED_DIM)]


def swr_ticks(max_swr: float):
    steps = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    return [(v, f"{v:.1f}") for v in steps if v <= max_swr + 1e-9]


def swr_zones():
    return [(1.5, GREEN, GREEN_DIM), (2.0, AMBER, AMBER_DIM), (99, RED, RED_DIM)]
