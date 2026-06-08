#!/usr/bin/env python3
"""
BT Bridge Broker — BT Bridge Protocol v1.0

Listens for a TCP connection from the mobile BT bridge agent app, then lets you
drive BLE operations interactively or from a test script.

INTERACTIVE USE
---------------
    python3 ble_server.py [--port 9876] [--log FILE]

    Start the server, then connect the mobile app to this machine's IP on the
    configured port. Once connected, type commands at the prompt:

        scan            Start scanning (10 s, no filter)
        scan WF-        Start scanning, filter by name prefix "WF-"
        stop            Stop scanning
        connect <addr>  Connect to a device by address/UUID
        disconnect      Disconnect current device
        discover        Discover services on current device
        sub <char-uuid> Subscribe to a characteristic
        unsub <uuid>    Unsubscribe from a characteristic
        read <uuid>     Read a characteristic (generates a req_id automatically)
        write <uuid> <hex>  Write hex bytes to a characteristic (with response)
        writenr <uuid> <hex>  Write without response
        ping            Ping the mobile app
        quit            Shut down the server

SCRIPTED USE
------------
    Import BleServer from this module and use the async API:

        from ble_server import BleServer
        import asyncio, protocol as P

        async def main():
            server = BleServer(port=9876)
            await server.start()

            await server.wait_connected()       # wait for mobile to connect
            await server.send(P.cmd_scan_start(name_filter="WF-"))

            evt = await server.wait_for(P.ScanResult)
            print("Found:", evt.address, evt.name)

            await server.send(P.cmd_scan_stop())
            await server.send(P.cmd_connect(evt.address))
            await server.wait_for(P.Connected)

            await server.send(P.cmd_discover(evt.address))
            svc = await server.wait_for(P.ServicesDiscovered)
            # ... etc

        asyncio.run(main())
"""

import argparse
import asyncio
import logging
import sys
import uuid as _uuid
from typing import Callable, Type

import protocol as P


log = logging.getLogger("ble_server")


class BleServer:
    """Async TCP server that speaks the BT Bridge Protocol."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9876):
        self.host = host
        self.port = port
        self._writer:  asyncio.StreamWriter | None = None
        self._event_q: asyncio.Queue = asyncio.Queue()
        self._connected_event = asyncio.Event()
        self._server: asyncio.Server | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        log.info("Listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._writer:
            self._writer.close()

    # ------------------------------------------------------------------
    # Sending commands
    # ------------------------------------------------------------------

    async def send(self, cmd: str) -> None:
        """Send a raw command string (from protocol.py cmd_* functions)."""
        if self._writer is None:
            raise RuntimeError("No mobile client connected")
        self._writer.write((cmd + "\n").encode())
        await self._writer.drain()
        log.debug("→ %s", cmd)

    # ------------------------------------------------------------------
    # Receiving events
    # ------------------------------------------------------------------

    async def wait_for(
        self,
        event_type: Type,
        timeout: float = 30.0,
        predicate: Callable | None = None,
    ) -> P.Event:
        """Wait for a specific event type, with optional predicate filter."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {event_type.__name__}")
            try:
                evt = await asyncio.wait_for(self._event_q.get(), timeout=remaining)
            except TimeoutError:
                raise TimeoutError(f"Timed out waiting for {event_type.__name__}")
            if isinstance(evt, event_type):
                if predicate is None or predicate(evt):
                    return evt
            # Put it back if it doesn't match — simple requeue
            await self._event_q.put(evt)
            await asyncio.sleep(0.01)

    async def wait_connected(self, timeout: float = 60.0) -> None:
        """Block until the mobile app connects."""
        await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)

    async def next_event(self, timeout: float = 30.0) -> P.Event | None:
        """Return the next event from the queue."""
        try:
            return await asyncio.wait_for(self._event_q.get(), timeout=timeout)
        except TimeoutError:
            return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername")
        log.info("Mobile client connected from %s", addr)
        self._writer = writer
        self._connected_event.set()

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line_str = line.decode(errors="replace").strip()
                log.debug("← %s", line_str)
                evt = P.parse_event(line_str)
                if evt is not None:
                    await self._event_q.put(evt)
                    self._log_event(evt)
                else:
                    log.warning("Unrecognised message: %s", line_str)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            log.info("Mobile client disconnected")
            self._writer = None
            self._connected_event.clear()
            writer.close()

    def _log_event(self, evt: P.Event) -> None:
        match evt:
            case P.ScanResult():
                log.info("SCAN  %s  %s  %d dBm", evt.address, evt.name or "(no name)", evt.rssi)
            case P.Connected():
                log.info("CONNECTED  %s", evt.address)
            case P.Disconnected():
                log.info("DISCONNECTED  %s  code=%d", evt.address, evt.code)
            case P.ServicesDiscovered():
                for svc in evt.services:
                    log.info("SERVICE  %s", svc.uuid)
                    for ch in svc.chars:
                        log.info("  CHAR  %s  %s", ch.uuid, ch.props)
            case P.Notification():
                log.info("NOTIFY  %s  %s  %s", evt.address[:8], evt.char[-8:], evt.value)
            case P.ReadResult():
                log.info("READ  %s  status=%d  %s", evt.char[-8:], evt.status, evt.value)
            case P.WriteResult():
                log.info("WRITE  %s  status=%d", evt.char[-8:], evt.status)
            case P.Error():
                log.error("ERROR  %s  %s", evt.code, evt.message)
            case P.Pong():
                log.info("PONG")
            case P.Log():
                log.log(
                    {"debug": logging.DEBUG, "info": logging.INFO,
                     "warn": logging.WARNING, "error": logging.ERROR}.get(evt.level, logging.INFO),
                    "APP  %s", evt.message,
                )
            case P.Answer():
                log.info("ANSWER  %s  %s", evt.req_id, "YES" if evt.value else "NO")
            case P.Dismiss():
                log.info("DISMISS  %s", evt.req_id)


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

async def _interactive(server: BleServer) -> None:
    loop   = asyncio.get_event_loop()
    addr   = None    # currently selected device address
    req_n  = 0       # auto-incrementing request ID counter

    def next_req() -> str:
        nonlocal req_n
        req_n += 1
        return f"req{req_n:04d}"

    print("BT Bridge Broker started. Waiting for mobile app to connect…")
    print("Press Ctrl-C to quit.\n")

    while True:
        try:
            raw = await loop.run_in_executor(None, input, "ble> ")
        except (EOFError, KeyboardInterrupt):
            break

        parts = raw.strip().split()
        if not parts:
            continue

        cmd = parts[0].lower()

        try:
            match cmd:
                case "scan":
                    filt = parts[1] if len(parts) > 1 else None
                    await server.send(P.cmd_scan_start(name_filter=filt))
                case "stop":
                    await server.send(P.cmd_scan_stop())
                case "connect":
                    if len(parts) < 2:
                        print("Usage: connect <address>")
                        continue
                    addr = parts[1]
                    await server.send(P.cmd_connect(addr))
                case "disconnect":
                    if addr is None:
                        print("No device selected")
                        continue
                    await server.send(P.cmd_disconnect(addr))
                    addr = None
                case "discover":
                    if addr is None:
                        print("No device connected")
                        continue
                    await server.send(P.cmd_discover(addr))
                case "sub":
                    if len(parts) < 2 or addr is None:
                        print("Usage: sub <char-uuid>  (must be connected)")
                        continue
                    await server.send(P.cmd_subscribe(addr, parts[1]))
                case "unsub":
                    if len(parts) < 2 or addr is None:
                        print("Usage: unsub <char-uuid>")
                        continue
                    await server.send(P.cmd_unsubscribe(addr, parts[1]))
                case "read":
                    if len(parts) < 2 or addr is None:
                        print("Usage: read <char-uuid>  (must be connected)")
                        continue
                    await server.send(P.cmd_read(addr, parts[1], next_req()))
                case "write":
                    if len(parts) < 3 or addr is None:
                        print("Usage: write <char-uuid> <hex>  (must be connected)")
                        continue
                    await server.send(P.cmd_write(addr, parts[1], bytes.fromhex(parts[2]), next_req(), rsp=True))
                case "writenr":
                    if len(parts) < 3 or addr is None:
                        print("Usage: writenr <char-uuid> <hex>  (must be connected)")
                        continue
                    await server.send(P.cmd_write(addr, parts[1], bytes.fromhex(parts[2]), next_req(), rsp=False))
                case "ping":
                    await server.send(P.cmd_ping())
                case "quit" | "exit" | "q":
                    break
                case "help" | "?":
                    print(__doc__)
                case _:
                    print(f"Unknown command: {cmd}. Type 'help' for usage.")

        except RuntimeError as e:
            print(f"Error: {e}")

    await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="BT Bridge Broker")
    parser.add_argument("--port",     type=int, default=9876,  help="TCP port to listen on (default: 9876)")
    parser.add_argument("--host",     default="0.0.0.0",       help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--log",      default=None,            help="Path to log file (default: stdout only)")
    parser.add_argument("--debug",    action="store_true",     help="Enable debug logging")
    parser.add_argument("--headless", action="store_true",     help="Skip interactive prompt — log events and run until killed")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )

    server = BleServer(host=args.host, port=args.port)

    async def run() -> None:
        await server.start()
        if args.headless:
            log.info("Headless mode — waiting for mobile app (Ctrl-C to quit)")
            await asyncio.get_event_loop().create_future()  # run forever
        else:
            await _interactive(server)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
