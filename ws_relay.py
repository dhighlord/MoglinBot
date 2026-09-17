"""WebSocket <-> TCP relay for Ruffle's socketProxy.

Ruffle's *web* player cannot open raw TCP sockets (browser restriction), so its
``flash.net.Socket`` calls must be tunnelled through a WebSocket. AQW's game
client connects to the game server over raw TCP (null-terminated messages), so
this relay:

  * accepts a WebSocket connection from Ruffle,
  * opens a raw TCP connection to the real AQW game server,
  * bidirectionally pipes bytes between them (message framing: text WS messages
    carry the raw TCP bytes; we also support the binary protocol for safety).

This mirrors what rBot did with its CaptureProxy (MITM on port 5588) — except we
proxy at the WebSocket layer so the *real* client (running in Ruffle) reaches the
real server, and we can inject packets into that same live connection.

Usage (module API):
    relay = TcpWsRelay("game.aq.com", 5588)
    asyncio.run(relay.serve_forever())
"""

from __future__ import annotations

import asyncio
import logging

import websockets

# The relay runs inside the GUI process; keep its messages out of the visible
# bot log unless something is actually wrong.
logging.getLogger("websockets").setLevel(logging.WARNING)

log = logging.getLogger("relay")
log.setLevel(logging.WARNING)

# Ruffle's socketProxy routes every Socket.connect() for a matching (host,port)
# to a WebSocket URL. The WS URL path carries the destination host/port so a
# single relay process can serve the whole game.
# Format: ws://127.0.0.1:PORT/?host=<dest>&port=<dest_port>


class TcpWsRelay:
    def __init__(self, listen_host: str = "127.0.0.1", listen_port: int = 8088) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port

    async def _handle(self, ws) -> None:
        """Pipe a single Ruffle WebSocket connection to a raw TCP peer."""
        # Destination from the WS URL query (?host=...&port=...), else default.
        host = ""
        port = 0
        request = getattr(ws, "request", None)
        if request is not None and getattr(request, "path", None):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(request.path)
            params = parse_qs(parsed.query)
            host = (params.get("host") or [""])[0]
            port = int((params.get("port") or ["0"])[0])
        if not host or not port:
            # No destination in the query — likely a connectivity probe or a
            # client that forgot its parameters. Close quietly; not an error.
            log.debug("WS client connected without host/port; closing.")
            await ws.close()
            return

        log.info("Ruffle socket -> %s:%s", host, port)
        reader, writer = await asyncio.open_connection(host, port)

        async def ws_to_tcp():
            try:
                async for message in ws:
                    data = message.encode("latin1") if isinstance(message, str) else message
                    writer.write(data)
                    await writer.drain()
            except Exception as exc:  # noqa: BLE001
                log.debug("ws->tcp ended: %s", exc)
            finally:
                writer.close()

        async def tcp_to_ws():
            try:
                while True:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break
                    # Send as text (AQW protocol is text/null-terminated).
                    await ws.send(chunk.decode("latin1"))
            except Exception as exc:  # noqa: BLE001
                log.debug("tcp->ws ended: %s", exc)

        await asyncio.gather(ws_to_tcp(), tcp_to_ws(), return_exceptions=True)
        try:
            writer.close()
        except Exception:
            pass
        await ws.close()

    async def serve_forever(self) -> None:
        async with websockets.serve(self._handle, self.listen_host, self.listen_port):
            log.info("Relay listening on ws://%s:%s", self.listen_host, self.listen_port)
            await asyncio.Future()  # run forever


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    relay = TcpWsRelay()
    asyncio.run(relay.serve_forever())


if __name__ == "__main__":
    main()
