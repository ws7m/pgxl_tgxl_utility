#!/usr/bin/env python3
"""Local simulator for a Tuner Genius XL, a Power Genius XL and a FlexRadio.

Lets you try the GUI without hardware. Point the app at 127.0.0.1 with ports
9010 (TGXL) and 9008 (PGXL), or pass --tgxl-port / --pgxl-port.

The simulated radio keys up for a few seconds every --tx-every seconds so the
meters move. Antenna, bypass, operate and autotune commands change the state.
"""

from __future__ import annotations

import argparse
import math
import random
import socketserver
import threading
import time


def watts_to_dbm(w: float) -> float:
    return 30 + 10 * math.log10(max(w, 1e-3))


def swr_to_rl(swr: float) -> float:
    gamma = (swr - 1) / (swr + 1)
    return -60.0 if gamma <= 0 else 20 * math.log10(gamma)


class Shared:
    """Radio/tuner/amp state shared between the two simulated devices."""

    def __init__(self, tx_every: float, tx_len: float):
        self.lock = threading.Lock()
        self.tx_every, self.tx_len = tx_every, tx_len
        self.t0 = time.monotonic()
        # tuner
        self.tg_operate = 1
        self.tg_bypass = 0
        self.tg_ant = 1
        self.tg_tune_until = 0.0
        self.relays = {1: [44, 12, 8], 2: [120, 60, 30], 3: [0, 200, 90]}
        self.swr_by_ant = {1: 1.15, 2: 1.6, 3: 2.4}
        # amp
        self.pg_operate = 0
        # radio
        self.rfpower = 50
        self.flex_clients = []

    def tx(self) -> bool:
        tuning = time.monotonic() < self.tg_tune_until
        return tuning or (time.monotonic() - self.t0) % self.tx_every < self.tx_len

    def drive_w(self) -> float:
        if time.monotonic() < self.tg_tune_until:
            return 10.0
        return self.rfpower * 0.9 + random.uniform(-1, 1) if self.tx() and self.rfpower else 0.0

    def out_w(self) -> float:
        d = self.drive_w()
        if not d:
            return 0.0
        return min(1500.0, d * 30) if self.pg_operate else d

    def swr(self) -> float:
        if self.tg_bypass or not self.tg_operate:
            return 2.8
        return self.swr_by_ant[self.tg_ant]


class Handler(socketserver.StreamRequestHandler):
    shared: Shared
    kind = ""

    def handle(self):
        self.status_pending = False
        version = {"tgxl": "1.2.44", "pgxl": "3.9.9", "flex": "1.4.0.0"}[self.kind]
        self.wfile.write(f"V{version}\r\n".encode())
        if self.kind == "flex":
            self.handle_id = f"{random.randint(0, 0xFFFFFFFF):08X}"
            self.wfile.write(f"H{self.handle_id}\n".encode())
        print(f"[{self.kind}] client {self.client_address[0]} connected")
        for raw in self.rfile:
            line = raw.decode(errors="replace").rstrip("\n")
            if self.kind == "tgxl" and line.endswith("\r"):
                self.reply_raw("R0|1|Invalid command")
                continue
            line = line.rstrip("\r")
            if not line.startswith("C") or "|" not in line:
                continue
            seq, cmd = line[1:].split("|", 1)
            try:
                self.dispatch(seq, cmd.strip())
            except (BrokenPipeError, ConnectionResetError):
                break
        print(f"[{self.kind}] client {self.client_address[0]} disconnected")

    def reply_raw(self, text):
        self.wfile.write((text + "\r\n").encode())

    def reply(self, seq, code=0, message=""):
        self.reply_raw(f"R{seq}|{code:X}|{message}")

    def dispatch(self, seq, cmd):
        sh = self.shared
        with sh.lock:
            if self.kind == "tgxl":
                self.tgxl(seq, cmd, sh)
            elif self.kind == "flex":
                self.flex(seq, cmd, sh)
            else:
                self.pgxl(seq, cmd, sh)

    # ---------------------------------------------------------------- FlexRadio
    def flex_tx_status(self, sh: Shared):
        return (f"S{self.handle_id}|transmit freq=14.205000 rfpower={sh.rfpower} tunepower=15 "
                f"tx_slice_mode=USB max_power_level=100 tx_rf_power_changes_allowed=1 tune=0")

    def flex(self, seq, cmd, sh: Shared):
        if cmd == "info":
            self.reply(seq, 0, 'model="FLEX-6600",chassis_serial="SIM",name="SIM-6600",'
                               'callsign="N0CALL",software_ver=4.3.16.0,ip=127.0.0.1')
        elif cmd == "sub tx all":
            self.reply(seq)
            self.reply_raw(self.flex_tx_status(sh))
            sh.flex_clients.append(self)
        elif cmd.startswith("transmit set rfpower="):
            sh.rfpower = max(0, min(100, int(cmd.split("=")[1])))
            self.reply(seq)
            for client in list(sh.flex_clients):  # the radio pushes the change to subscribers
                try:
                    client.reply_raw(client.flex_tx_status(sh))
                except OSError:
                    sh.flex_clients.remove(client)
        else:
            self.reply(seq, 0x50000015, "unknown command")

    # ---------------------------------------------------------------- TGXL
    def tgxl(self, seq, cmd, sh: Shared):
        now = time.monotonic()
        if cmd == "status":
            tuning = now < sh.tg_tune_until
            out = sh.out_w()
            fwd = watts_to_dbm(out) if out else 0.0
            swr = swr_to_rl(sh.swr()) if out else -60.0
            c1, l, c2 = sh.relays[sh.tg_ant]
            if tuning:
                c1, l, c2 = (random.randint(0, 255) for _ in range(3))
            ptt = 1 if sh.tx() else 0
            self.reply_raw(
                f"S0|status fwd={fwd:.2f} peak={fwd:.2f} max=62.43 swr={swr:.4f} "
                f"pttA={ptt} bandA=20 modeA=1 flexA=SIM-6600 freqA=14205.000 bypassA={sh.tg_bypass} "
                f"bypassRxA=0 antA={sh.tg_ant - 1} pttB=0 bandB=0 modeB=0 flexB= freqB=0.000 bypassB=0 "
                f"bypassRxB=0 antB=0 state={sh.tg_operate} active=1 tuning={int(tuning)} "
                f"bypass={sh.tg_bypass} ag=0 relayC1={c1} relayL={l} relayC2={c2}")
        elif cmd == "info":
            self.reply(seq, 0, "3way=1 serial=SIM-0001 nickname=SimTuner")
        elif cmd == "autotune":
            sh.tg_tune_until = now + 3.0
            sh.swr_by_ant[sh.tg_ant] = round(random.uniform(1.05, 1.3), 2)
            sh.relays[sh.tg_ant] = [random.randint(0, 255) for _ in range(3)]
            self.reply(seq)
        elif cmd.startswith("activate ant="):
            n = int(cmd.split("=")[1])
            if n in (1, 2, 3):
                sh.tg_ant = n
                self.reply(seq)
            else:
                self.reply(seq, 0x50000013, "bad parameter")
        elif cmd.startswith("bypass set="):
            sh.tg_bypass = int(cmd.split("=")[1])
            self.reply(seq)
        elif cmd.startswith("operate set="):
            sh.tg_operate = int(cmd.split("=")[1])
            self.reply(seq)
        else:
            self.reply(seq, 0x50000015, "unknown command")

    # ---------------------------------------------------------------- PGXL
    def pgxl(self, seq, cmd, sh: Shared):
        if cmd == "status":
            tx = sh.tx() and sh.pg_operate
            out = sh.out_w() if sh.pg_operate else 0.0
            state = "STANDBY" if not sh.pg_operate else ("TRANSMIT_A" if tx else "IDLE")
            fwd = watts_to_dbm(out) if out > 1 else 30.0
            swr = swr_to_rl(sh.swr()) if out > 1 else -60.0
            id_a = out / 50.0 * 1.6 if tx else 0.0
            vdd = 50.1 if tx else 0.0
            self.reply(seq, 0,
                       f"state={state} bandA=20 bandB=0 bsrcA=FLEX bsrcB=FLEX flexA=SIM-6600 flexB= "
                       f"vac=238 vdd={vdd:.1f} id={id_a:.1f} peakid={id_a:.1f} fwd={fwd:.1f} "
                       f"peakfwd={fwd:.1f} swr={swr:.1f} temp={22.6 + id_a / 4:.1f} hltemp=23.1 "
                       f"cntfreq=0 cat1freq=0 cat2freq=0 biasA=RADIO_AB biasB=RADIO_AB "
                       f"fanmode=STANDARD meffa=OFF unkey=0 ants=0")
        elif cmd.startswith("operate="):
            sh.pg_operate = int(cmd.split("=")[1])
            self.reply(seq)
        elif cmd.startswith("setup read") or cmd.startswith("ifconf read"):
            self.reply(seq, 0, "nickname=SimAmp meffa=OFF")
        else:
            self.reply(seq, 0x50000015, "unknown command")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(kind, host, port, shared):
    handler = type(f"{kind}Handler", (Handler,), {"kind": kind, "shared": shared})
    srv = Server((host, port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"{kind.upper()} simulator listening on {host}:{port}")
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--tgxl-port", type=int, default=9010)
    ap.add_argument("--pgxl-port", type=int, default=9008)
    ap.add_argument("--flex-port", type=int, default=4992)
    ap.add_argument("--tx-every", type=float, default=10.0, help="seconds between simulated key-ups")
    ap.add_argument("--tx-len", type=float, default=4.0, help="length of each key-up in seconds")
    args = ap.parse_args()
    shared = Shared(args.tx_every, args.tx_len)
    servers = [serve("tgxl", args.host, args.tgxl_port, shared),
               serve("pgxl", args.host, args.pgxl_port, shared),
               serve("flex", args.host, args.flex_port, shared)]
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
