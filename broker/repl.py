"""Optional interactive REPL for the BT Bridge broker (--interactive)."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from broker.registry import AgentRegistry

log = logging.getLogger(__name__)

HELP = """
BT Bridge REPL — commands
  agents                      list connected agents
  agent set <id>[,<id>...]    set active agent(s)
  agent clear                 clear selection
  scan start [<filter>]       start BLE scan
  scan stop                   stop BLE scan
  connect <address>           connect to device
  disconnect <address>        disconnect from device
  discover <address>          discover GATT services
  subscribe <address> <char>  subscribe to notifications
  read <address> <char>       read characteristic
  ping                        ping agent(s)
  help                        show this help
  exit / quit                 exit
""".strip()


async def run_repl(registry: AgentRegistry) -> None:
    selected: list[str] = []
    loop = asyncio.get_running_loop()

    def _prompt() -> None:
        agents = registry.list_agents()
        if selected:
            label = ",".join(selected)
        elif len(agents) == 1:
            label = agents[0].agent_id
        else:
            label = "no agent"
        sys.stdout.write(f"bt[{label}]> ")
        sys.stdout.flush()

    async def _readline() -> str:
        return await loop.run_in_executor(None, sys.stdin.readline)

    async def _resolve() -> list[str]:
        """Return list of agent IDs to target, or [] with a printed message."""
        agents = registry.list_agents()
        if selected:
            return selected
        if not agents:
            print("[no agent connected]")
            return []
        if len(agents) == 1:
            return [agents[0].agent_id]
        print(f"[{len(agents)} agents — use: agent set <id>]")
        return []

    while True:
        _prompt()
        line = await _readline()
        if not line:
            break
        parts = line.strip().split()
        if not parts:
            continue
        cmd = parts[0].lower()

        if cmd in ("exit", "quit"):
            break

        elif cmd == "help":
            print(HELP)

        elif cmd == "agents":
            for a in registry.list_agents():
                mark = "*" if not selected or a.agent_id in selected else " "
                print(f"  {mark} {a.agent_id}  platform={a.platform or '?'}  ble={a.ble_enabled}  scanning={a.scanning}")

        elif cmd == "agent":
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "set" and len(parts) > 2:
                selected = parts[2].split(",")
                print(f"[active: {', '.join(selected)}]")
            elif sub == "clear":
                selected = []
                print("[selection cleared]")
            else:
                print("usage: agent set <id>[,<id>...] | agent clear")

        elif cmd == "scan":
            targets = await _resolve()
            if not targets:
                continue
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "start":
                name_filter = parts[2] if len(parts) > 2 else None
                c: dict[str, Any] = {"cmd": "scan_start", "timeout_ms": 30000}
                if name_filter:
                    c["name_filter"] = name_filter
                for aid in targets:
                    await registry.send_command(aid, c)
            elif sub == "stop":
                for aid in targets:
                    await registry.send_command(aid, {"cmd": "scan_stop"})
            else:
                print("usage: scan start [<filter>] | scan stop")

        elif cmd == "connect":
            if len(parts) < 2:
                print("usage: connect <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "connect", "address": parts[1]})

        elif cmd == "disconnect":
            if len(parts) < 2:
                print("usage: disconnect <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "disconnect", "address": parts[1]})

        elif cmd == "discover":
            if len(parts) < 2:
                print("usage: discover <address>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "discover", "address": parts[1]})

        elif cmd == "subscribe":
            if len(parts) < 3:
                print("usage: subscribe <address> <char-uuid>")
                continue
            targets = await _resolve()
            for aid in targets:
                await registry.send_command(aid, {"cmd": "subscribe", "address": parts[1], "char": parts[2]})

        elif cmd == "read":
            if len(parts) < 3:
                print("usage: read <address> <char-uuid>")
                continue
            targets = await _resolve()
            for aid in targets:
                import uuid
                req_id = uuid.uuid4().hex[:8]
                try:
                    result = await registry.send_and_wait(
                        aid,
                        {"cmd": "read", "address": parts[1], "char": parts[2]},
                        req_id,
                        timeout=5.0,
                    )
                    print(f"  [{aid}] {result.get('value', '?')}  status={result.get('status', '?')}")
                except Exception as exc:
                    print(f"  [{aid}] error: {exc}")

        elif cmd == "ping":
            import time as _time
            targets = await _resolve()
            for aid in targets:
                import uuid
                req_id = uuid.uuid4().hex[:8]
                t0 = _time.monotonic()
                try:
                    await registry.send_and_wait(aid, {"cmd": "ping"}, req_id, timeout=5.0)
                    ms = int((_time.monotonic() - t0) * 1000)
                    print(f"  [{aid}] pong  {ms} ms")
                except Exception as exc:
                    print(f"  [{aid}] timeout: {exc}")

        else:
            print(f"Unknown command: {cmd!r}. Type 'help'.")
