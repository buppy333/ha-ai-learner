"""Mock Home Assistant server (REST + WebSocket) for end-to-end testing."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import json

from ha_ai_learner.miniws import encode_frame, read_frame, OP_TEXT, OP_CLOSE, _WS_GUID

NOW = dt.datetime.now(dt.timezone.utc)


def iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


REGISTRIES = {
    "config/entity_registry/list": [
        {"entity_id": "light.nappali_lampa", "name": "Nappali lámpa", "area_id": "nappali",
         "device_id": "dev1", "platform": "hue", "labels": [], "disabled_by": None, "hidden_by": None},
        {"entity_id": "switch.sonoff_3", "name": None, "original_name": "sonoff_3", "area_id": None,
         "device_id": "dev2", "platform": "sonoff", "labels": [], "disabled_by": None, "hidden_by": None},
        {"entity_id": "sensor.halo_homerseklet", "name": "Háló hőmérséklet", "area_id": "halo",
         "device_id": "dev3", "platform": "zha", "labels": [], "disabled_by": None, "hidden_by": None,
         "original_device_class": "temperature"},
    ],
    "config/device_registry/list": [
        {"id": "dev1", "name": "Hue bulb", "manufacturer": "Signify", "model": "LCA001",
         "area_id": "nappali", "primary_config_entry": "ce1"},
        {"id": "dev2", "name": "Sonoff Basic", "manufacturer": "ITEAD", "model": "BASICR2",
         "area_id": None, "primary_config_entry": "ce2"},
        {"id": "dev3", "name": "Aqara sensor", "manufacturer": "Aqara", "model": "WSDCGQ11LM",
         "area_id": "halo", "primary_config_entry": "ce3"},
    ],
    "config/area_registry/list": [
        {"area_id": "nappali", "name": "Nappali", "floor_id": "fsz"},
        {"area_id": "halo", "name": "Hálószoba", "floor_id": "emelet"},
    ],
    "config/floor_registry/list": [
        {"floor_id": "fsz", "name": "Földszint"},
        {"floor_id": "emelet", "name": "Emelet"},
    ],
    "config/label_registry/list": [{"label_id": "fontos", "name": "Fontos"}],
    "config_entries/get": [
        {"entry_id": "ce1", "domain": "hue", "title": "Philips Hue", "source": "user"},
        {"entry_id": "ce2", "domain": "sonoff", "title": "Sonoff LAN", "source": "user"},
        {"entry_id": "ce3", "domain": "zha", "title": "Zigbee Home Automation", "source": "user"},
    ],
    "hacs/repositories/list": [
        {"name": "sonoff-lan", "category": "integration", "installed": True, "installed_version": "3.8.0"},
    ],
}

STATES = [
    {"entity_id": "light.nappali_lampa", "state": "on",
     "attributes": {"friendly_name": "Nappali lámpa", "supported_features": 44},
     "last_changed": iso(1)},
    {"entity_id": "switch.sonoff_3", "state": "off",
     "attributes": {"friendly_name": "sonoff_3"}, "last_changed": iso(2)},
    {"entity_id": "sensor.halo_homerseklet", "state": "22.5",
     "attributes": {"friendly_name": "Háló hőmérséklet", "unit_of_measurement": "°C",
                    "device_class": "temperature"}, "last_changed": iso(0.5)},
]

SERVICES = [
    {"domain": "light", "services": {
        "turn_on": {"name": "Turn on", "description": "Turn on one or more lights.",
                    "fields": {"brightness": {"description": "Brightness 0..255", "required": False}}},
        "turn_off": {"name": "Turn off", "description": "Turn off one or more lights.", "fields": {}},
    }},
    {"domain": "switch", "services": {
        "toggle": {"name": "Toggle", "description": "Toggle a switch.", "fields": {}},
    }},
]


def history_payload() -> list:
    def series(eid, events):
        return [{"entity_id": eid, "state": s, "last_changed": iso(h)} for s, h in events]
    return [
        series("light.nappali_lampa",
               [("off", 30), ("on", 26.0), ("off", 20), ("on", 14.0), ("off", 10),
                ("on", 2.05), ("off", 1)]),
        series("switch.sonoff_3",
               [("off", 30), ("on", 26.02), ("off", 20), ("on", 14.02), ("off", 10),
                ("on", 2.0), ("off", 1)]),
    ]


# ------------------------------------------------------------------ server
async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        request_line = await reader.readline()
        if not request_line:
            return
        method, path, _ = request_line.decode().split(" ", 2)
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            k, _, v = line.decode().partition(":")
            headers[k.strip().lower()] = v.strip()

        if path == "/api/websocket":
            await handle_ws(reader, writer, headers)
            return

        body = b""
        if int(headers.get("content-length", 0)):
            body = await reader.readexactly(int(headers["content-length"]))

        data = route_rest(method, path, body)
        payload = json.dumps(data).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def route_rest(method: str, path: str, body: bytes):
    path = path.split("?")[0]
    if path == "/api/" or path == "/api":
        return {"message": "API running."}
    if path == "/api/config":
        return {"version": "2026.7.1", "location_name": "Teszt Otthon",
                "components": ["hue", "zha", "sonoff", "hacs"]}
    if path == "/api/states":
        return STATES
    if path.startswith("/api/states/"):
        eid = path.rsplit("/", 1)[1]
        return next((s for s in STATES if s["entity_id"] == eid), {})
    if path == "/api/services":
        return SERVICES
    if path.startswith("/api/history/period"):
        return history_payload()
    if path.startswith("/api/services/") and method == "POST":
        return [{"ok": True, "called": path, "data": json.loads(body or b"{}")}]
    return {}


async def handle_ws(reader, writer, headers):
    key = headers.get("sec-websocket-key", "")
    accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    writer.write((f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
    await writer.drain()

    async def send(obj):
        writer.write(encode_frame(OP_TEXT, json.dumps(obj).encode(), mask=False))
        await writer.drain()

    await send({"type": "auth_required"})
    while True:
        opcode, fin, payload = await read_frame(reader)
        if opcode == OP_CLOSE:
            break
        if opcode != OP_TEXT:
            continue
        msg = json.loads(payload.decode())
        if msg.get("type") == "auth":
            if msg.get("access_token") == "test-token":
                await send({"type": "auth_ok", "ha_version": "2026.7.1"})
            else:
                await send({"type": "auth_invalid"})
        elif msg.get("type") in REGISTRIES:
            await send({"id": msg["id"], "type": "result", "success": True,
                        "result": REGISTRIES[msg["type"]]})
        elif msg.get("type"):
            await send({"id": msg.get("id"), "type": "result", "success": False,
                        "error": {"code": "unknown_command"}})


async def start(port: int = 18123):
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    return server
