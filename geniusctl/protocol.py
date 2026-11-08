"""4O3A "Genius" TCP protocol client (shared by Tuner Genius XL and Power Genius XL).

Wire format (both devices):
  banner   device -> client   V<a.b.c>[ AUTH]
  command  client -> device   C<seq>|<command><terminator>
  reply    device -> client   R<seq>|<hex result>|<message>
  status   device -> client   S<n>|<message>

The TGXL rejects a trailing CR, so the default terminator is a bare LF (the PGXL
accepts LF too). Only one `status` poll is kept in flight at a time: the PGXL
closes the socket if a second `status` arrives before the first is answered.
"""

from __future__ import annotations

import queue
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

_KV_RE = re.compile(r"(\w+)=(\S*)")


def _to_value(text: str):
    if text == "":
        return text
    try:
        return float(text) if any(c in text for c in ".eE") else int(text)
    except ValueError:
        return text


def parse_key_values(message: str) -> dict:
    """Parse 'key=value key2=value2 ...' into a dict (numbers converted)."""
    return {m.group(1): _to_value(m.group(2)) for m in _KV_RE.finditer(message)}


@dataclass
class Event:
    """Something that happened on a connection, delivered to the GUI thread."""

    device: str  # "tgxl" / "pgxl"
    kind: str  # "connected" | "disconnected" | "status" | "error" | "reply" | "log"
    data: dict = field(default_factory=dict)
    text: str = ""


class GeniusClient:
    """Threaded TCP client with auto-reconnect and status polling.

    Subclasses define how a status poll is answered (S line vs R reply).
    Events are pushed onto `events` (a queue.Queue) for the GUI to drain.
    """

    device = "genius"
    status_via_reply = False  # True: status arrives as R<seq>|0|..., False: as S<n>|status ...

    def __init__(self, events: "queue.Queue[Event]"):
        self.events = events
        self.host = ""
        self.port = 0
        self.poll_interval = 0.5
        self.terminator = "\n"
        self.status_timeout = 2.0
        self.reconnect_delay = 3.0

        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._seq = 0
        self._pending: dict[int, tuple[str, Callable[[int, str], None] | None]] = {}
        self._status_seq: int | None = None
        self._status_sent_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.firmware = ""

    # ------------------------------------------------------------------ control
    def start(self, host: str, port: int, poll_interval: float = 0.5, terminator: str = "\n"):
        self.stop()
        self.host, self.port = host, int(port)
        self.poll_interval = max(0.1, float(poll_interval))
        self.terminator = terminator
        self._stop = threading.Event()  # fresh event so an old, still-connecting thread stays stopped
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        name=f"{self.device}-client", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    def send(self, command: str, callback: Callable[[int, str], None] | None = None) -> int | None:
        """Send a command; returns its sequence number, or None if not sent.

        callback(result_code, message) runs on the client thread."""
        with self._lock:
            if not self._sock:
                self._emit("error", text=f"Not connected - cannot send '{command}'")
                return None
            self._seq = self._seq % 255 + 1
            seq = self._seq
            self._pending[seq] = (command, callback)
            try:
                self._sock.sendall(f"C{seq}|{command}{self.terminator}".encode("ascii"))
            except OSError as exc:
                self._pending.pop(seq, None)
                self._emit("error", text=f"Send failed: {exc}")
                return None
        if command != "status":
            self._emit("log", text=f"> C{seq}|{command}")
        return seq

    # ------------------------------------------------------------------ internals
    def _emit(self, kind: str, data: dict | None = None, text: str = ""):
        self.events.put(Event(self.device, kind, data or {}, text))

    def _close(self):
        with self._lock:
            sock, self._sock = self._sock, None
            self._pending.clear()
            self._status_seq = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _run(self, stop: threading.Event):
        while not stop.is_set():
            try:
                self._session(stop)
            except OSError as exc:
                if not stop.is_set():
                    self._emit("error", text=f"{self.host}:{self.port} - {exc}")
            if stop.is_set() and self._stop is not stop:
                return  # superseded by a newer start(); leave its socket alone
            self._close()
            if self.connected:
                self.connected = False
                self._emit("disconnected")
            stop.wait(self.reconnect_delay)

    def _session(self, stop: threading.Event):
        sock = socket.create_connection((self.host, self.port), timeout=5)
        if stop.is_set():
            sock.close()
            return
        sock.settimeout(0.1)
        with self._lock:
            self._sock = sock
            self._seq = 0
        buf = b""
        banner_deadline = time.monotonic() + 3
        got_banner = False
        next_poll = 0.0

        while not stop.is_set():
            now = time.monotonic()
            # Mark connected once the banner arrives (or after a short grace period).
            if not got_banner and now > banner_deadline:
                got_banner = True
                self._on_connected("")
            if got_banner and now >= next_poll:
                self._poll_status(now)
                next_poll = now + self.poll_interval
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise OSError("connection closed by device")
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", "replace").strip("\r ")
                if not line:
                    continue
                if not got_banner and line.startswith("V"):
                    got_banner = True
                    self._on_connected(line)
                    next_poll = 0.0
                    continue
                self._handle_line(line)

    def _on_connected(self, banner: str):
        tokens = banner[1:].split() if banner else []
        self.firmware = tokens[0] if tokens else ""
        self.connected = True
        info = {"firmware": self.firmware, "auth": "AUTH" in tokens, "host": self.host}
        self._emit("connected", info)
        if "AUTH" in tokens:
            self._emit("error", text="Device requests authentication (WAN connection); not supported.")
        self.on_connected()

    def on_connected(self):
        """Hook for subclasses (e.g. send 'info' after connecting)."""

    def _poll_status(self, now: float):
        if self._status_seq is not None:
            if now - self._status_sent_at < self.status_timeout:
                return  # previous status still in flight: never double up
            with self._lock:
                self._pending.pop(self._status_seq, None)
            self._status_seq = None
        self._status_sent_at = now
        self._status_seq = self.send("status", self._on_status_reply)

    def _on_status_reply(self, code: int, message: str):
        # TGXL answers status with an S line (handled in _handle_line); the PGXL
        # answers with an R frame carrying key=value pairs.
        if self.status_via_reply and code == 0:
            self._publish_status(message)

    def _handle_line(self, line: str):
        kind, _, rest = line.partition("|")
        if kind.startswith("R"):
            try:
                seq = int(kind[1:] or 0)
            except ValueError:
                seq = 0
            code_txt, _, message = rest.partition("|")
            try:
                code = int(code_txt or "0", 16)
            except ValueError:
                code = -1
            with self._lock:
                command, callback = self._pending.pop(seq, ("", None))
            if seq == self._status_seq:
                self._status_seq = None
            if command and command != "status":
                self._emit("reply", {"command": command, "code": code, "message": message},
                           text=f"< {line}")
                if code != 0:
                    self._emit("error", text=f"'{command}' failed: 0x{code:X} {message}")
            if callback:
                callback(code, message)
        elif kind.startswith("S"):
            if rest.startswith("status"):
                with self._lock:
                    if self._status_seq is not None:
                        self._pending.pop(self._status_seq, None)
                self._status_seq = None
                self._publish_status(rest[len("status"):])
            else:
                self._emit("log", text=f"< {line}")
        else:
            self._emit("log", text=f"< {line}")

    def _publish_status(self, message: str):
        raw = parse_key_values(message)
        self._emit("status", self.decode_status(raw), text=message.strip())

    def decode_status(self, raw: dict) -> dict:
        return dict(raw)
