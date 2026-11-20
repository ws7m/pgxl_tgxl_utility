"""Tuner Genius XL, Power Genius XL and FlexRadio clients built on the shared protocol."""

from __future__ import annotations

import threading
import time

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
    quiet_prefixes = ("status", "tune relay=")

    RELAYS = ("C1", "L", "C2")  # relay= index on the wire
    RELAY_REPLY_TIMEOUT_S = 2.0

    def __init__(self, events):
        super().__init__(events)
        self.three_way = True
        # Manual relay moves: the TGXL only accepts one step at a time
        # ('tune relay=<0|1|2> move=<1|-1>', ~100 ms each), so requested moves
        # are kept as a net step count per relay and sent one step at a time,
        # each after the previous one is acknowledged.
        self._relay_lock = threading.Lock()
        self._relay_pending = [0, 0, 0]
        self._relay_inflight_at: float | None = None

    def start(self, host, port, poll_interval=0.5, terminator="\n"):
        self._reset_relay_moves()
        super().start(host, port, poll_interval, terminator)

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

    # Manual relay moves ---------------------------------------------------
    def move_relay(self, relay: int, steps: int):
        """Queue a manual move of relay bank 0=C1, 1=L, 2=C2 by `steps` (+/-)."""
        if relay not in (0, 1, 2) or not steps:
            return
        with self._relay_lock:
            self._relay_pending[relay] += int(steps)
        self._pump_relays()

    def relay_moves_pending(self) -> bool:
        with self._relay_lock:
            return any(self._relay_pending) or self._relay_inflight_at is not None

    def _reset_relay_moves(self):
        with self._relay_lock:
            self._relay_pending = [0, 0, 0]
            self._relay_inflight_at = None

    def _pump_relays(self):
        with self._relay_lock:
            now = time.monotonic()
            if self._relay_inflight_at is not None:
                if now - self._relay_inflight_at < self.RELAY_REPLY_TIMEOUT_S:
                    return  # wait for the step in flight to be acknowledged
                self._relay_inflight_at = None  # reply lost: carry on
            relay = next((i for i, n in enumerate(self._relay_pending) if n), None)
            if relay is None:
                return
            step = 1 if self._relay_pending[relay] > 0 else -1
            self._relay_pending[relay] -= step
            self._relay_inflight_at = now
        if self.send(f"tune relay={relay} move={step}", self._relay_done) is None:
            self._reset_relay_moves()

    def _relay_done(self, code: int, _message: str):
        with self._relay_lock:
            self._relay_inflight_at = None
            if code != 0:  # refused (error already reported): drop the rest
                self._relay_pending = [0, 0, 0]
        self._pump_relays()

    def _poll_status(self, now: float):
        self._pump_relays()  # recovers if a step's reply was lost
        super()._poll_status(now)

    def _close(self):
        super()._close()
        self._reset_relay_moves()

    # Status ---------------------------------------------------------------
    def decode_status(self, raw: dict) -> dict:
        if self.three_way:
            # antA is zero-based on the wire: 0 = ANT 1, 1 = ANT 2, 2 = ANT 3
            # (confirmed against a 3WAY unit on firmware 1.2.44).
            ant = _int(raw.get("antA"), -1) + 1
        else:
            ant = _int(raw.get("active"))
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


    def set_operate(self, on: bool):
        return self.send(f"operate={1 if on else 0}")

    def decode_status(self, raw: dict) -> dict:
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


def parse_flex_info(message: str) -> dict:
    """Parse a FlexRadio 'info' reply: key="value",key=value,... (comma separated)."""
    out = {}
    for part in message.split(","):
        key, sep, value = part.partition("=")
        if sep:
            out[key.strip()] = value.strip().strip('"')
    return out


class FlexRadioClient(GeniusClient):
    """FlexRadio SmartSDR API, TCP port 4992.

    On connect the radio sends 'V<version>' then 'H<handle>'. There is no status
    poll: after 'sub tx all' / 'sub slice all' the radio pushes
    'S<handle>|transmit k=v ...' and 'S<handle>|slice <n> k=v ...' lines (often
    only the keys that changed), which are merged into state dicts.
    """

    device = "flex"
    default_port = 4992

    def __init__(self, events):
        super().__init__(events)
        self.handle = ""
        self.tx: dict = {}
        self.slices: dict[int, dict] = {}

    def start(self, host, port, poll_interval=0.5, terminator="\n"):
        self.tx = {}
        self.slices = {}
        super().start(host, port, poll_interval, "\n")

    def on_connected(self):
        def got_info(code, message):
            if code == 0:
                info = parse_flex_info(message)
                self._emit("info", info, text=f"{info.get('model', '')} {info.get('name', '')}")

        self.send("info", got_info)
        self.send("sub tx all")
        self.send("sub slice all")

    def _poll_status(self, now: float):
        pass  # the radio pushes transmit status after 'sub tx all'

    def _handle_line(self, line: str):
        if line.startswith("H"):
            self.handle = line[1:]
            return
        kind, _, rest = line.partition("|")
        if kind.startswith("S"):
            if rest.startswith("transmit "):
                self.tx.update(parse_key_values(rest[len("transmit "):]))
                self._emit("status", self.decode_status(dict(self.tx)), text=rest.strip())
            elif rest.startswith("slice "):
                self._slice_status(rest[len("slice "):])
            return  # other radio status (eq, panadapters, ...) is not needed here
        if kind.startswith("M"):
            self._emit("log", text=f"< {line}")
            return
        super()._handle_line(line)

    def _slice_status(self, text: str):
        index_txt, _, body = text.partition(" ")
        try:
            index = int(index_txt)
        except ValueError:
            return
        kv = parse_key_values(body)
        if _int(kv.get("in_use"), 1) == 0:
            self.slices.pop(index, None)
        else:
            self.slices.setdefault(index, {}).update(kv)

    def tx_slice(self) -> tuple[int, float] | None:
        """(index, frequency in MHz) of the transmit slice, or None if unknown."""
        for index, kv in sorted(self.slices.items()):
            if _int(kv.get("tx")) == 1:
                return index, _float(kv.get("RF_frequency"))
        return None

    def tune_slice(self, index: int, mhz: float):
        return self.send(f"slice tune {int(index)} {mhz:.6f}")

    def set_tune_power(self, value: int):
        value = max(0, min(100, int(value)))
        return self.send(f"transmit set tunepower={value}")

    def set_tune(self, on: bool):
        """Key/unkey the radio's tune carrier (at the tune power)."""
        return self.send(f"transmit tune {1 if on else 0}")

    def set_rf_power(self, value: int):
        value = max(0, min(100, int(value)))
        return self.send(f"transmit set rfpower={value}")

    def decode_status(self, raw: dict) -> dict:
        return {
            "raw": raw,
            "rfpower": _int(raw.get("rfpower"), -1),
            "tunepower": _int(raw.get("tunepower"), -1),
            "max_power": _int(raw.get("max_power_level"), 100) or 100,
            "changes_allowed": _int(raw.get("tx_rf_power_changes_allowed"), 1) == 1,
            "tune": _int(raw.get("tune")) == 1,
            "freq_mhz": _float(raw.get("freq")),
            "mode": raw.get("tx_slice_mode", ""),
        }
