"""Persistent settings stored as JSON in the user's config directory."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("GENIUSCTL_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "GeniusControl" / "settings.json"


@dataclass
class Settings:
    # Network
    tgxl_enabled: bool = True
    tgxl_host: str = "192.168.1.170"
    tgxl_port: int = 9010
    pgxl_enabled: bool = True
    pgxl_host: str = "192.168.1.171"
    pgxl_port: int = 9008
    flex_enabled: bool = True
    flex_host: str = ""
    flex_port: int = 4992
    auto_connect: bool = True
    poll_interval_ms: int = 500
    line_ending: str = "LF"  # "LF" or "CRLF" (the TGXL rejects CR)

    # Display
    tgxl_power_scale_w: int = 2000
    pgxl_power_scale_w: int = 2000
    pgxl_current_scale_a: int = 70
    swr_scale_max: float = 3.0
    show_peak_power: bool = True
    confirm_operate: bool = False
    always_on_top: bool = False

    @property
    def terminator(self) -> str:
        return "\r\n" if self.line_ending == "CRLF" else "\n"

    @classmethod
    def load(cls) -> "Settings":
        path = config_path()
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f.name: f.type for f in fields(cls)}
        defaults = cls()
        kwargs = {}
        for key, value in data.items():
            if key in known:
                default = getattr(defaults, key)
                try:
                    kwargs[key] = type(default)(value) if not isinstance(default, bool) else bool(value)
                except (TypeError, ValueError):
                    pass
        return cls(**kwargs)

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path
