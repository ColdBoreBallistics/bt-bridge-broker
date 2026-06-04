#!/usr/bin/env python3
"""
WeatherFlow Tactical — end-to-end field verification script (DOPE-29, DOPE-30).

Connects to a WeatherFlow WEATHERmeter for Precision Shooting via the BLE bridge,
subscribes to the notification characteristic, and logs decoded sensor data for
manual comparison against reference instruments.

USAGE
-----
1. Start ble_server.py on this machine:
       python3 ../ble_server.py --port 9876

2. Connect the BLE bridge app on Android/iOS to this machine.

3. Run this script:
       python3 weatherflow_verify.py [--host 127.0.0.1] [--port 9876] [--duration 120]

4. Compare the printed values against:
   - Wind speed: anemometer reference (if available), or expected calm/known wind
   - Temperature: independent reference thermometer (±2 °F tolerance)
   - Pressure: weather station or known barometric reference (±2 hPa tolerance)
   - Humidity: reference hygrometer (±5% tolerance)
   - Wind direction: calibrated compass (±5° at cardinal points)

OUTPUT FORMAT
-------------
Each line printed as data arrives:
    [HH:MM:SS]  wind=3.2m/s  dir=247°  temp=72.3°F  hum=45%  pres=1013.2hPa  raw=57465053...

Press Ctrl-C to stop.
"""

import argparse
import asyncio
import logging
import struct
import sys
import time

sys.path.insert(0, "..")
import protocol as P
from ble_server import BleServer


WF_SERVICE_UUID = "961f0001-0000-1000-8000-00805f9b34fb"
WF_NOTIFY_UUID  = "961f0005-0000-1000-8000-00805f9b34fb"
WF_NAME_PREFIX  = "WF-"


def decode_wf_frame(raw: bytes) -> dict | None:
    """
    Decode a 16-byte WeatherFlow Tactical notification frame.

    Frame layout (confirmed via HCI snoop 2026-06-02):
      Bytes 0-4:  ASCII header "WFPSM"
      Bytes 5-6:  Wind speed (big-endian uint16), raw / 1024 = m/s
      Bytes 7-8:  Wind direction (big-endian uint16), degrees 0-359
      Bytes 9-10: Temperature (big-endian int16), raw / 100 = °C
      Bytes 11-12: Humidity (big-endian uint16), raw / 100 = %RH
      Bytes 13-14: Pressure (big-endian uint16), raw / 10 = hPa
      Byte  15:   Reserved / checksum

    NOTE: Internal frame details are confidential — do not reproduce in
    public channels, commit messages, or issue comments.
    """
    if len(raw) < 16:
        return None
    header = raw[0:5]
    if header != b"WFPSM":
        return None

    wind_raw, dir_raw, temp_raw, hum_raw, pres_raw = struct.unpack_from(">HHhHH", raw, 5)

    wind_ms  = wind_raw / 1024.0
    wind_dir = dir_raw
    temp_c   = temp_raw / 100.0
    temp_f   = temp_c * 9 / 5 + 32
    humidity = hum_raw / 100.0
    pressure = pres_raw / 10.0

    return {
        "wind_ms":  round(wind_ms,  2),
        "wind_dir": wind_dir,
        "temp_f":   round(temp_f,   1),
        "temp_c":   round(temp_c,   2),
        "humidity": round(humidity, 1),
        "pressure": round(pressure, 1),
    }


async def run_verification(host: str, port: int, duration: int) -> None:
    server = BleServer(host=host, port=port)
    await server.start()

    print(f"Waiting for mobile app to connect on {host}:{port} …")
    await server.wait_connected()
    print("Mobile app connected.\n")

    # Scan for WeatherFlow
    print(f"Scanning for WeatherFlow sensor (prefix: {WF_NAME_PREFIX!r}) …")
    await server.send(P.cmd_scan_start(timeout_ms=15000, name_filter=WF_NAME_PREFIX))

    evt = await server.wait_for(P.ScanResult, timeout=20.0)
    print(f"Found: {evt.address}  {evt.name}  {evt.rssi} dBm")

    await server.send(P.cmd_scan_stop())
    await server.send(P.cmd_connect(evt.address))
    await server.wait_for(P.Connected, timeout=15.0)
    print("Connected to GATT server.")

    await server.send(P.cmd_discover(evt.address))
    svc_evt = await server.wait_for(P.ServicesDiscovered, timeout=15.0)

    # Verify expected service is present
    found_service = any(s.uuid == WF_SERVICE_UUID for s in svc_evt.services)
    print(f"WeatherFlow service present: {'YES' if found_service else 'NO (UNEXPECTED)'}")
    if not found_service:
        print("ERROR: WeatherFlow primary service not found. Aborting.")
        return

    # Subscribe
    await server.send(P.cmd_subscribe(evt.address, WF_NOTIFY_UUID))
    print(f"\nSubscribed. Logging data for {duration}s. Press Ctrl-C to stop early.\n")
    print(f"{'Time':<10} {'Wind m/s':>9} {'Dir °':>6} {'Temp °F':>8} {'Hum %':>6} {'Pres hPa':>10}  Raw")
    print("-" * 80)

    deadline = time.time() + duration
    count = 0
    while time.time() < deadline:
        try:
            notif = await server.wait_for(P.Notification, timeout=5.0)
        except TimeoutError:
            print("  (no data for 5s)")
            continue

        raw = notif.value_bytes
        decoded = decode_wf_frame(raw)
        ts = time.strftime("%H:%M:%S")

        if decoded:
            print(
                f"{ts:<10} {decoded['wind_ms']:>9.2f} {decoded['wind_dir']:>6} "
                f"{decoded['temp_f']:>8.1f} {decoded['humidity']:>6.1f} "
                f"{decoded['pressure']:>10.1f}  {notif.value}"
            )
            count += 1
        else:
            print(f"{ts:<10}  PARSE ERROR — raw: {notif.value}")

    print(f"\nDone. {count} frames received.")

    # Battery level check
    battery_svc = "0000180f-0000-1000-8000-00805f9b34fb"
    battery_char = "00002a19-0000-1000-8000-00805f9b34fb"
    has_battery = any(
        any(c.uuid == battery_char for c in s.chars)
        for s in svc_evt.services if s.uuid == battery_svc
    )
    if has_battery:
        await server.send(P.cmd_read(evt.address, battery_char, "batt01"))
        try:
            result = await server.wait_for(P.ReadResult, timeout=5.0)
            level = int(result.value_bytes[0]) if result.value_bytes else -1
            print(f"Battery level: {level}%")
        except TimeoutError:
            print("Battery read timed out.")

    await server.send(P.cmd_disconnect(evt.address))
    await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="WeatherFlow Tactical field verification")
    parser.add_argument("--host",     default="127.0.0.1", help="Server bind address")
    parser.add_argument("--port",     type=int, default=9876)
    parser.add_argument("--duration", type=int, default=120, help="Seconds to log data (default: 120)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)  # suppress server noise during verification

    try:
        asyncio.run(run_verification(args.host, args.port, args.duration))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
