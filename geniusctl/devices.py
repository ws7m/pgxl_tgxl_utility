"""Tuner Genius XL and Power Genius XL clients built on the shared protocol."""

from __future__ import annotations

from .protocol import GeniusClient, parse_key_values

# Units on the wire: power in dBm, SWR as return loss in dB (negative, -60 = no RF).
NO_RF_RETURN_LOSS = -60.0


def dbm_to_watts(dbm, floor_dbm: float | None = None) -> float:
    """Convert dBm to watts. Values at or below floor_dbm read as 0 W."""
    try:
        dbm = float(dbm)
    except (TypeError, ValueError):
        return 0.0
    if floor_dbm is not None and dbm <= floor_dbm:
        return 0.0
    return 10 ** ((dbm - 30.0) / 10.0)


def return_loss_to_swr(rl_db) -> float:
    """Convert return loss in dB (either sign) to VSWR. No RF (-60) gives 1.0."""
    try:
        rl = abs(float(rl_db))
    except (TypeError, ValueError):
        return 1.0
    if rl >= abs(NO_RF_RETURN_LOSS):
        return 1.0
    if rl <= 0.0:
        return 99.9
    gamma = 10 ** (-rl / 20.0)
    return min(99.9, (1 + gamma) / (1 - gamma))


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class TunerGeniusClient(GeniusClient):
    """Tuner Genius XL, TCP port 9010. Status arrives as 'S<n>|status k=v ...'."""

    device = "tgxl"
    status_via_reply = False
    default_port = 9010

    def __init__(self, events):
        super().__init__(events)
        self.three_way = True

    def on_connected(self):
        def got_info(code, message):
            if code == 0:
                info = parse_key_values(message)
                if "3way" in info:
                    self.three_way = bool(_int(info["3way"]))
                self._emit("info", info, text=message)

        self.send("info", got_info)

    # Commands -------------------------------------------------------------
    def tune(self):
        return self.send("autotune")

    def select_antenna(self, n: int):
        key = "ant" if self.three_way else "ch"
        return self.send(f"activate {key}={int(n)}")

    def set_bypass(self, on: bool):
        return self.send(f"bypass set={1 if on else 0}")

    def set_operate(self, on: bool):
        return self.send(f"operate set={1 if on else 0}")

    # Status ---------------------------------------------------------------
    def decode_status(self, raw: dict) -> dict:
        ant = _int(raw.get("antA", 0))
        if not ant and not self.three_way:
            ant = _int(raw.get("active", 0))
        return {
            "raw": raw,
            "fwd_w": dbm_to_watts(raw.get("fwd"), floor_dbm=0.0),
            "peak_w": dbm_to_watts(raw.get("peak"), floor_dbm=0.0),
            "swr": return_loss_to_swr(raw.get("swr", NO_RF_RETURN_LOSS)),
            "operate": _int(raw.get("state")) == 1,
            "bypass": _int(raw.get("bypass")) == 1,
            "tuning": _int(raw.get("tuning")) == 1,
            "ptt": _int(raw.get("pttA")) == 1 or _int(raw.get("pttB")) == 1,
            "antenna": ant,
            "c1": _int(raw.get("relayC1")),
            "l": _int(raw.get("relayL")),
            "c2": _int(raw.get("relayC2")),
            "freq_khz": raw.get("freqA", 0),
            "mode": _int(raw.get("modeA")),
        }


class PowerGeniusClient(GeniusClient):
    """Power Genius XL, TCP port 9008. Status arrives as 'R<seq>|0|k=v ...'."""

    device = "pgxl"
    status_via_reply = True
    default_port = 9008

    # Keys some firmware versions may use for drive power (dBm). The documented
    # 3.9.x status reply has none, in which case drive reads as unavailable.
    DRIVE_KEYS = ("drv", "drive", "fwdin", "pin", "drvpwr")

    def set_operate(self, on: bool):
        return self.send(f"operate={1 if on else 0}")

    def decode_status(self, raw: dict) -> dict:
        drive_w = None
        for key in self.DRIVE_KEYS:
            if key in raw:
                drive_w = dbm_to_watts(raw[key], floor_dbm=0.0)
                break
        state = str(raw.get("state", "")).upper()
        return {
            "raw": raw,
            "state": state or "UNKNOWN",
            "operate": state not in ("", "STANDBY", "UNKNOWN"),
            "transmitting": state.startswith("TRANSMIT"),
            "fault": state == "FAULT" or _int(raw.get("unkey")) == 1,
            # fwd sits at 30 dBm (meter floor, 1 W) with no RF: treat that as 0 W.
            "fwd_w": dbm_to_watts(raw.get("fwd"), floor_dbm=30.0),
            "peak_w": dbm_to_watts(raw.get("peakfwd"), floor_dbm=30.0),
            "drive_w": drive_w,
            "swr": return_loss_to_swr(raw.get("swr", NO_RF_RETURN_LOSS)),
            "id_a": _float(raw.get("id")),
            "peak_id_a": _float(raw.get("peakid")),
            "temp_c": raw.get("temp", ""),
            "vdd": raw.get("vdd", ""),
            "vac": raw.get("vac", ""),
            "band_a": raw.get("bandA", ""),
            "band_b": raw.get("bandB", ""),
            "meffa": raw.get("meffa", ""),
        }
