"""Band Tune: step the radio across a band and run a TGXL tune cycle at each step.

For the chosen band the sequence starts at the low band edge and, at each step:
  1. tunes the FlexRadio transmit slice to the frequency,
  2. waits until the TGXL reports that frequency (it follows the radio),
  3. starts a TGXL tune (as if TUNE were pressed),
  4. waits for the tune cycle to finish,
  5. moves up by the increment, until it reaches or passes the upper band edge.
Stopping, finishing or an error puts the slice back on its original frequency.

The sequencer is driven by tick(now) from the GUI and talks to the devices only
through the callables it is given, so it can be tested without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Amateur band edges in MHz (US / ITU Region 2).
BANDS: dict[str, tuple[float, float]] = {
    "160m": (1.800, 2.000),
    "80m": (3.500, 4.000),
    "40m": (7.000, 7.300),
    "30m": (10.100, 10.150),
    "20m": (14.000, 14.350),
    "17m": (18.068, 18.168),
    "15m": (21.000, 21.450),
    "12m": (24.890, 24.990),
    "10m": (28.000, 29.700),
    "6m": (50.000, 54.000),
}
DEFAULT_STEP_KHZ = 10
STEP_CHOICES_KHZ = (1, 2, 5, 10, 20, 25, 50, 100)


def band_frequencies(band: str, step_khz: float) -> list[float]:
    """Frequencies (MHz) from the low edge up, stopping at or before the high edge."""
    low, high = BANDS[band]
    step_hz = round(step_khz * 1000)
    if step_hz <= 0:
        raise ValueError("increment must be greater than zero")
    low_hz, high_hz = round(low * 1e6), round(high * 1e6)
    return [hz / 1e6 for hz in range(low_hz, high_hz, step_hz)]


@dataclass
class TunerView:
    """What the sequencer needs to know about the TGXL right now."""

    connected: bool
    operate: bool
    bypass: bool
    tuning: bool
    freq_khz: float
    relays: tuple[int, int, int]


@dataclass
class StepResult:
    mhz: float
    ok: bool
    note: str = ""
    relays: tuple[int, int, int] | None = None


@dataclass
class BandTuner:
    set_freq: Callable[[float], object]  # tune the radio's TX slice (MHz)
    start_tune: Callable[[], object]  # press TGXL TUNE
    get_tuner: Callable[[], TunerView | None]

    FREQ_SETTLE_S: float = 0.4  # minimum wait after moving the radio
    FREQ_TIMEOUT_S: float = 3.0  # carry on if the TGXL never reports the new frequency
    TUNE_START_S: float = 5.0  # time for the TGXL to report tuning=1
    TUNE_TIMEOUT_S: float = 60.0  # longest a single tune cycle may take
    BETWEEN_S: float = 0.5  # pause between steps
    MAX_RETRIES: int = 1  # extra TUNE presses if a tune never starts

    state: str = "idle"
    message: str = ""
    band: str = ""
    freqs: list[float] = field(default_factory=list)
    index: int = 0
    results: list[StepResult] = field(default_factory=list)
    return_mhz: float | None = None
    _t: float = 0.0
    _retries: int = 0
    _relays_before: tuple[int, int, int] | None = None

    @property
    def running(self) -> bool:
        return self.state not in ("idle", "done", "stopped", "error")

    @property
    def current_mhz(self) -> float | None:
        return self.freqs[self.index] if self.running and self.index < len(self.freqs) else None

    # ------------------------------------------------------------------ control
    def start(self, band: str, step_khz: float, now: float, return_mhz: float | None) -> bool:
        """Begin a run. Returns False (with self.message set) if it cannot start."""
        if self.running:
            return False
        tuner = self.get_tuner()
        problem = self._tuner_problem(tuner)
        if problem:
            self.state, self.message = "error", problem
            return False
        try:
            self.freqs = band_frequencies(band, step_khz)
        except (KeyError, ValueError) as exc:
            self.state, self.message = "error", f"Cannot start: {exc}"
            return False
        self.band, self.index, self.results = band, 0, []
        self.return_mhz = return_mhz
        self._goto(now)
        return True

    def stop(self, reason: str = "Stopped") -> None:
        if self.running:
            self._finish("stopped", f"{reason} after {len(self.results)} of {len(self.freqs)} steps")

    # ------------------------------------------------------------------ engine
    def tick(self, now: float) -> None:
        if not self.running:
            return
        tuner = self.get_tuner()
        if tuner is None or not tuner.connected:
            self._finish("error", "Stopped: the Tuner Genius XL disconnected")
            return
        mhz = self.freqs[self.index]
        elapsed = now - self._t

        if self.state == "wait_freq":
            at_freq = abs(tuner.freq_khz - mhz * 1000) < 1.0
            if elapsed >= self.FREQ_SETTLE_S and (at_freq or elapsed >= self.FREQ_TIMEOUT_S):
                self._press_tune(now, tuner)
        elif self.state == "wait_tune":
            if tuner.tuning:
                self.state, self._t = "tuning", now
                self.message = self._progress("tuning")
            elif elapsed >= self.TUNE_START_S:
                if self._relays_before is not None and tuner.relays != self._relays_before:
                    self._step_done(now, tuner, "fast tune")  # finished between two polls
                elif self._retries < self.MAX_RETRIES:
                    self._retries += 1
                    self._press_tune(now, tuner, retry=True)
                else:
                    problem = self._tuner_problem(tuner) or "check the tuner"
                    self._finish("error", f"TGXL did not start tuning at {mhz:.3f} MHz ({problem})")
        elif self.state == "tuning":
            if not tuner.tuning:
                self._step_done(now, tuner)
            elif elapsed >= self.TUNE_TIMEOUT_S:
                self._finish("error", f"Tune at {mhz:.3f} MHz took over {self.TUNE_TIMEOUT_S:.0f} s")
        elif self.state == "between":
            if elapsed >= self.BETWEEN_S:
                self._goto(now)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _tuner_problem(tuner: TunerView | None) -> str:
        if tuner is None or not tuner.connected:
            return "Tuner Genius XL is not connected"
        if tuner.bypass:
            return "Tuner Genius XL is in BYPASS"
        if not tuner.operate:
            return "Tuner Genius XL is in STANDBY"
        return ""

    def _progress(self, what: str) -> str:
        mhz = self.freqs[self.index]
        return f"{self.band}  step {self.index + 1}/{len(self.freqs)}  {mhz:.3f} MHz  {what}"

    def _goto(self, now: float):
        mhz = self.freqs[self.index]
        self.set_freq(mhz)
        self.state, self._t, self._retries = "wait_freq", now, 0
        self.message = self._progress("moving radio")

    def _press_tune(self, now: float, tuner: TunerView, retry: bool = False):
        self._relays_before = tuner.relays
        self.start_tune()
        self.state, self._t = "wait_tune", now
        self.message = self._progress("retrying tune" if retry else "starting tune")

    def _step_done(self, now: float, tuner: TunerView, note: str = ""):
        self.results.append(StepResult(self.freqs[self.index], True, note, tuner.relays))
        self.index += 1
        if self.index >= len(self.freqs):
            self._finish("done", f"{self.band} done: tuned {len(self.results)} frequencies")
        else:
            self.state, self._t = "between", now
            self.message = self._progress("done")

    def _finish(self, state: str, message: str):
        self.state, self.message = state, message
        if self.return_mhz:
            self.set_freq(self.return_mhz)
