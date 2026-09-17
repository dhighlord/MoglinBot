"""Local TCP control channel for the in-game moglin.swf GUI.

The Flash projector cannot use ExternalInterface (no browser host), but
``flash.net.Socket`` works in the standalone projector. moglin.swf connects to
this server on 127.0.0.1:5587, sends JSON commands ("hello", "status", bot
start/stop) and receives JSON commands ("packet" injection, "setStatus").

This is the rBot-equivalent bridge: the bot engine injects game packets into
the *live* client through this channel, and the in-game GUI reports status.
"""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from typing import Any, Callable


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: ControlServer = self.server  # type: ignore[attr-defined]
        server.on_client(self.request, self.client_address)

    def setup(self) -> None:
        super().setup()
        self.request.settimeout(1.0)


class ControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int) -> None:
        super().__init__((host, port), _Handler)
        self._client = None
        self._lock = threading.Lock()
        self._on_packet: Callable[[str, str], None] | None = None
        self._on_event: Callable[[str, Any], None] | None = None

    def set_handlers(
        self,
        on_packet: Callable[[str, str], None] | None,
        on_event: Callable[[str, Any], None] | None = None,
    ) -> None:
        with self._lock:
            self._on_packet = on_packet
            self._on_event = on_event

    def send(self, cmd: dict) -> bool:
        """Send a JSON command to the connected moglin.swf, if any."""
        with self._lock:
            client = self._client
        if client is None:
            return False
        try:
            client.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    def send_packet(self, packet: str, ptype: str = "str") -> bool:
        return self.send({"cmd": "packet", "packet": packet, "type": ptype})

    def send_status(self, message: str) -> bool:
        return self.send({"cmd": "setStatus", "message": message})

    def on_client(self, sock: Any, addr: Any) -> None:
        with self._lock:
            self._client = sock
        buffer = b""
        try:
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", "replace"))
        finally:
            with self._lock:
                if self._client is sock:
                    self._client = None

    def _dispatch(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        cmd = msg.get("cmd")
        if cmd == "hello":
            with self._lock:
                handler = self._on_event
            if handler:
                handler("hello", msg)
        elif cmd == "status":
            with self._lock:
                handler = self._on_event
            if handler:
                handler("status", msg)
        elif cmd == "botStart":
            with self._lock:
                handler = self._on_event
            if handler:
                handler("botStart", msg)
        elif cmd == "botStop":
            with self._lock:
                handler = self._on_event
            if handler:
                handler("botStop", msg)
