#!/usr/bin/env python3
"""
Niimbot B1 / B21 Pro — BLE protocol verification script (DOPE-33).

Connects to a Niimbot printer via the BLE bridge and confirms the GATT
service/characteristic UUIDs. For the B21 Pro, also confirms whether the
protocol matches the B1 (same ISSC UART-over-BLE bridge).

USAGE
-----
1. Start ble_server.py on this machine.
2. Connect the BLE bridge app on Android/iOS.
3. Run:
       python3 niimbot_b1_verify.py [--host 127.0.0.1] [--port 9876] [--name B21]

The --name flag is used as the scan name filter prefix (default: "B1").
For B21 Pro testing, pass --name B21.

OUTPUT
------
Prints all discovered services and characteristics.
Reports whether the B21 Pro UUIDs match the known B1 UUIDs.
"""

import argparse
import asyncio
import logging
import sys

sys.path.insert(0, "..")
import protocol as P
from ble_server import BleServer


# Confirmed B1 UUIDs (ISSC UART-over-BLE bridge)
B1_KNOWN_UUIDS = {
    "service":  "0000ff00-0000-1000-8000-00805f9b34fb",
    "write":    "0000ff02-0000-1000-8000-00805f9b34fb",
    "notify":   "0000ff01-0000-1000-8000-00805f9b34fb",
}


async def run_verification(host: str, port: int, name_filter: str) -> None:
    server = BleServer(host=host, port=port)
    await server.start()

    print(f"Waiting for mobile app to connect on {host}:{port} …")
    await server.wait_connected()
    print("Mobile app connected.\n")

    print(f"Scanning for Niimbot device (filter: {name_filter!r}) …")
    await server.send(P.cmd_scan_start(timeout_ms=15000, name_filter=name_filter))

    evt = await server.wait_for(P.ScanResult, timeout=20.0)
    print(f"Found: {evt.address}  {evt.name}  {evt.rssi} dBm")

    await server.send(P.cmd_scan_stop())
    await server.send(P.cmd_connect(evt.address))
    await server.wait_for(P.Connected, timeout=15.0)
    print("Connected.\n")

    await server.send(P.cmd_discover(evt.address))
    svc_evt = await server.wait_for(P.ServicesDiscovered, timeout=15.0)

    print("Discovered services:")
    found_uuids: dict[str, list[str]] = {}
    for svc in svc_evt.services:
        print(f"\n  SERVICE  {svc.uuid}")
        found_uuids[svc.uuid] = []
        for ch in svc.chars:
            print(f"    CHAR   {ch.uuid}  {ch.props}")
            found_uuids[svc.uuid].append(ch.uuid)

    print("\n--- B1 UUID Comparison ---")
    for role, expected in B1_KNOWN_UUIDS.items():
        match = any(expected in chars for chars in found_uuids.values()) or expected in found_uuids
        status = "MATCH" if match else "NOT FOUND"
        print(f"  {role:<10}  {expected}  [{status}]")

    all_match = all(
        any(uuid in chars for chars in found_uuids.values()) or uuid in found_uuids
        for uuid in B1_KNOWN_UUIDS.values()
    )
    print(f"\nProtocol match with B1: {'YES — same ISSC UART bridge' if all_match else 'NO — UUIDs differ, update driver'}")

    await server.send(P.cmd_disconnect(evt.address))
    await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Niimbot BLE UUID verification")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--name", default="B1", help="Scan name filter prefix (default: B1)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    try:
        asyncio.run(run_verification(args.host, args.port, args.name))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
