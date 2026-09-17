"""Bridge between the Moglin Bot GUI and the live AQW game client.

The game runs inside a Ruffle *web* player embedded in the GUI (pywebview's
browser engine). rBot's ``rbot.swf`` loader registers ExternalInterface
callbacks on the live game client, so we can:

  * inject packets via ``sendClientPacket(packet, 'str')`` — the game's own
    ``sfc.sendString`` — which makes the *real* character move/fight visibly, and
  * receive server packets via the ``packet``/``pext`` callbacks that rbot.swf
    forwards to JavaScript.

This module is the Python side of that bridge. It is deliberately decoupled
from the GUI loop so the aqw-python engine can use it from its own thread.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

# Packet types accepted by rbot.swf's sendClientPacket:
#   'str'  - a null-terminated AQW message like %xt%zm%...
#   'json' - a JSON object
#   'xml'  - an XML string
PACKET_STR = "str"
PACKET_JSON = "json"
PACKET_XML = "xml"


class LiveClient:
    """Thread-safe handle for talking to the Ruffle-embedded game client."""

    def __init__(self) -> None:
        # A callable that runs JS in the webview and returns the result.
        # Signature: (js: str) -> Any
        self._eval_js: Callable[[str], Any] | None = None
        self._game_loaded = threading.Event()
        self._inbound: "queue.Queue[dict]" = queue.Queue()
        self._lock = threading.Lock()

    # ---- wiring ------------------------------------------------------------
    def set_eval_js(self, fn: Callable[[str], Any]) -> None:
        with self._lock:
            self._eval_js = fn

    def mark_game_loaded(self) -> None:
        self._game_loaded.set()

    def mark_game_closed(self) -> None:
        self._game_loaded.clear()

    def is_game_loaded(self) -> bool:
        return self._game_loaded.is_set()

    # ---- outbound: inject a packet into the live client --------------------
    def send(self, packet: str, ptype: str = PACKET_STR) -> bool:
        """Inject ``packet`` into the live game client.

        Returns True if the packet was dispatched to JS; False otherwise.
        """
        fn = self._eval_js
        if fn is None:
            return False
        if not self._game_loaded.is_set():
            # Game not loaded yet; drop (the caller can retry).
            return False
        js = (
            "window.__moglin_sendPacket(%r, %r);" % (packet, ptype)
        )
        try:
            fn(js)
            return True
        except Exception:
            return False

    # ---- inbound: server packets forwarded from JS -------------------------
    def on_packet(self, packet: str) -> None:
        """Called from JS when the game emits a server packet."""
        self._inbound.put({"type": "packet", "data": packet})

    def on_pext(self, packet: str) -> None:
        """Called from JS for SmartFox extension responses (JSON)."""
        self._inbound.put({"type": "pext", "data": packet})

    def on_debug(self, message: str) -> None:
        self._inbound.put({"type": "debug", "data": message})

    def drain_inbound(self) -> list[dict]:
        items: list[dict] = []
        while True:
            try:
                items.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        return items

    def wait_for_packet(self, timeout: float = 5.0) -> dict | None:
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            return None
