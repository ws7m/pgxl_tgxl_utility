import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geniusctl.devices import (PowerGeniusClient, TunerGeniusClient, dbm_to_watts,  # noqa: E402
                               return_loss_to_swr)
from geniusctl.protocol import parse_key_values  # noqa: E402
import simulator  # noqa: E402


class ConversionTests(unittest.TestCase):
    def test_dbm_to_watts(self):
        self.assertAlmostEqual(dbm_to_watts(60.0), 1000.0, places=3)
        self.assertAlmostEqual(dbm_to_watts(40.0), 10.0, places=3)
        self.assertEqual(dbm_to_watts(30.0, floor_dbm=30.0), 0.0)
        self.assertEqual(dbm_to_watts("junk"), 0.0)

    def test_return_loss_to_swr(self):
        self.assertEqual(return_loss_to_swr(-60), 1.0)
        self.assertAlmostEqual(return_loss_to_swr(-9.54), 2.0, places=2)
        self.assertAlmostEqual(return_loss_to_swr(9.54), 2.0, places=2)
        self.assertAlmostEqual(return_loss_to_swr(-20.83), 1.2, places=2)

    def test_parse_key_values(self):
        kv = parse_key_values(" fwd=21.42 swr=-60.0000 flexA=FLEX-8600 flexB= relayC1=44")
        self.assertEqual(kv, {"fwd": 21.42, "swr": -60.0, "flexA": "FLEX-8600", "flexB": "",
                              "relayC1": 44})


class SimulatorRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = simulator.Shared(tx_every=1000, tx_len=0)
        cls.servers = [simulator.serve("tgxl", "127.0.0.1", 0, cls.shared),
                       simulator.serve("pgxl", "127.0.0.1", 0, cls.shared)]

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            s.shutdown()
            s.server_close()

    def _wait(self, q, predicate, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                ev = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if predicate(ev):
                return ev
        self.fail("timed out waiting for event")

    def test_tgxl_commands(self):
        q = queue.Queue()
        c = TunerGeniusClient(q)
        c.start("127.0.0.1", self.servers[0].server_address[1], poll_interval=0.1)
        try:
            ev = self._wait(q, lambda e: e.kind == "connected")
            self.assertEqual(ev.data["firmware"], "1.2.44")
            self._wait(q, lambda e: e.kind == "status")
            c.select_antenna(3)
            self._wait(q, lambda e: e.kind == "status" and e.data["antenna"] == 3)
            c.set_bypass(True)
            self._wait(q, lambda e: e.kind == "status" and e.data["bypass"])
            c.set_bypass(False)
            c.tune()
            ev = self._wait(q, lambda e: e.kind == "status" and e.data["tuning"])
            self.assertGreater(ev.data["fwd_w"], 0)
        finally:
            c.stop()

    def test_pgxl_operate(self):
        q = queue.Queue()
        c = PowerGeniusClient(q)
        c.start("127.0.0.1", self.servers[1].server_address[1], poll_interval=0.1)
        try:
            self._wait(q, lambda e: e.kind == "connected")
            ev = self._wait(q, lambda e: e.kind == "status")
            self.assertEqual(ev.data["state"], "STANDBY")
            self.assertIsNone(ev.data["drive_w"])
            c.set_operate(True)
            self._wait(q, lambda e: e.kind == "status" and e.data["state"] == "IDLE")
            c.set_operate(False)
            self._wait(q, lambda e: e.kind == "status" and e.data["state"] == "STANDBY")
        finally:
            c.stop()


if __name__ == "__main__":
    unittest.main()
