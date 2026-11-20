import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geniusctl.bandtune import BANDS, BandTuner, TunerView, band_frequencies  # noqa: E402


class FrequencyListTests(unittest.TestCase):
    def test_all_requested_bands_present(self):
        self.assertEqual(list(BANDS), ["160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m",
                                       "10m", "6m"])

    def test_40m_10khz(self):
        f = band_frequencies("40m", 10)
        self.assertEqual(f[0], 7.000)
        self.assertEqual(f[-1], 7.290)  # stops before reaching the 7.300 band edge
        self.assertEqual(len(f), 30)

    def test_steps_stay_inside_every_band(self):
        for band, (low, high) in BANDS.items():
            for step in (1, 7.5, 10, 25):
                f = band_frequencies(band, step)
                self.assertAlmostEqual(f[0], low)
                self.assertTrue(all(low <= x < high for x in f), band)
                self.assertGreaterEqual(f[-1] + step / 1000, high - 1e-9)  # next step: at or past edge

    def test_no_float_drift(self):
        self.assertEqual(band_frequencies("17m", 10)[-1], 18.158)

    def test_bad_step(self):
        with self.assertRaises(ValueError):
            band_frequencies("20m", 0)


class FakeRig:
    """A radio + TGXL: tuning=1 for `tune_ticks` ticks after a TUNE press."""

    def __init__(self, tune_ticks=3, starts_tuning=True):
        self.freq_mhz = 14.074
        self.tuner = TunerView(True, True, False, False, 14074.0, (1, 2, 3))
        self.tune_ticks, self.starts_tuning = tune_ticks, starts_tuning
        self.left = 0
        self.presses = []
        self.moves = []

    def set_freq(self, mhz):
        self.moves.append(mhz)
        self.freq_mhz = mhz
        self.tuner.freq_khz = mhz * 1000

    def press(self):
        self.presses.append(self.freq_mhz)
        if self.starts_tuning:
            self.left = self.tune_ticks

    def view(self):
        self.tuner.tuning = self.left > 0
        if self.left:
            self.left -= 1
        return self.tuner


def run(seq, rig, max_ticks=5000, dt=0.1):
    now = 0.0
    for _ in range(max_ticks):
        if not seq.running:
            break
        now += dt
        seq.tick(now)
    return now


class SequencerTests(unittest.TestCase):
    def make(self, rig):
        return BandTuner(set_freq=rig.set_freq, start_tune=rig.press, get_tuner=rig.view)

    def test_full_band_run(self):
        rig = FakeRig()
        seq = self.make(rig)
        self.assertTrue(seq.start("30m", 10, 0.0, return_mhz=14.074))
        run(seq, rig)
        self.assertEqual(seq.state, "done")
        self.assertEqual(rig.presses, [10.100, 10.110, 10.120, 10.130, 10.140])
        self.assertEqual(len(seq.results), 5)
        self.assertEqual(rig.freq_mhz, 14.074)  # back where it started

    def test_stop_restores_frequency(self):
        rig = FakeRig()
        seq = self.make(rig)
        seq.start("40m", 10, 0.0, return_mhz=14.074)
        for i in range(30):
            seq.tick(i * 0.1)
        self.assertTrue(seq.running)
        seq.stop()
        self.assertFalse(seq.running)
        self.assertEqual(seq.state, "stopped")
        self.assertEqual(rig.freq_mhz, 14.074)
        presses = len(rig.presses)
        seq.tick(100.0)
        self.assertEqual(len(rig.presses), presses)  # nothing more after stop

    def test_refuses_when_bypassed_or_standby(self):
        rig = FakeRig()
        rig.tuner.bypass = True
        seq = self.make(rig)
        self.assertFalse(seq.start("20m", 10, 0.0, None))
        self.assertIn("BYPASS", seq.message)
        rig.tuner.bypass, rig.tuner.operate = False, False
        self.assertFalse(seq.start("20m", 10, 0.0, None))
        self.assertIn("STANDBY", seq.message)
        self.assertEqual(rig.moves, [])

    def test_tune_never_starts_is_an_error(self):
        rig = FakeRig(starts_tuning=False)
        seq = self.make(rig)
        seq.start("20m", 10, 0.0, return_mhz=14.074)
        run(seq, rig)
        self.assertEqual(seq.state, "error")
        self.assertEqual(len(rig.presses), 2)  # first press + one retry
        self.assertEqual(rig.freq_mhz, 14.074)

    def test_fast_tune_seen_by_relay_change(self):
        rig = FakeRig(starts_tuning=False)
        orig_press = rig.press

        def press():
            orig_press()
            rig.tuner.relays = (len(rig.presses), 0, 0)  # relays moved, tuning=1 never seen
        seq = BandTuner(set_freq=rig.set_freq, start_tune=press, get_tuner=rig.view)
        seq.start("30m", 25, 0.0, return_mhz=None)
        run(seq, rig)
        self.assertEqual(seq.state, "done")
        self.assertEqual(len(seq.results), 2)

    def test_waits_for_tuner_to_follow_radio(self):
        rig = FakeRig()
        lag = {"n": 0}

        def slow_set(mhz):  # the TGXL reports the new frequency a few ticks later
            rig.moves.append(mhz)
            rig.freq_mhz = mhz
            lag["n"] = 8
        orig_view = rig.view

        def view():
            if lag["n"]:
                lag["n"] -= 1
                if not lag["n"]:
                    rig.tuner.freq_khz = rig.freq_mhz * 1000
            return orig_view()
        seq = BandTuner(set_freq=slow_set, start_tune=rig.press, get_tuner=view)
        seq.start("30m", 50, 0.0, None)
        run(seq, rig)
        self.assertEqual(rig.presses, [10.100])
        self.assertEqual(seq.state, "done")

    def test_tuner_disconnect_stops(self):
        rig = FakeRig()
        seq = self.make(rig)
        seq.start("20m", 10, 0.0, return_mhz=14.074)
        seq.tick(0.1)
        rig.tuner.connected = False
        seq.tick(0.2)
        self.assertEqual(seq.state, "error")
        self.assertEqual(rig.freq_mhz, 14.074)


if __name__ == "__main__":
    unittest.main()
