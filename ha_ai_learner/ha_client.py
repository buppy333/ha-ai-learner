"""Async Home Assistant client (REST via httpx + WebSocket via miniws).

The WebSocket API exposes the registries (entities, devices, areas, labels),
config entries and — if HACS is installed — the HACS repository list.
The REST API provides states, services and history.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .miniws import MiniWS, WSClosed

log = logging.getLogger(__name__)


class HAError(Exception):
    pass


class HAClient:
    def __init__(self, url: str, token: str, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    # ---------------------------------------------------------------- session
    async def __aenter__(self) -> "HAClient":
        self._client = httpx.AsyncClient(
            base_url=self.url,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise HAError("Client not started — use 'async with HAClient(...)'")
        return self._client

    # ------------------------------------------------------------------ REST
    async def rest_get(self, path: str, **params) -> Any:
        resp = await self.client.get(f"/api/{path.lstrip('/')}", params=params or None)
        if resp.status_code == 401:
            raise HAError("Unauthorized — check the long-lived access token")
        resp.raise_for_status()
        return resp.json()

    async def rest_post(self, path: str, payload: dict | None = None) -> Any:
        resp = await self.client.post(f"/api/{path.lstrip('/')}", json=payload or {})
        resp.raise_for_status()
        return resp.json()

    async def ping(self) -> bool:
        data = await self.rest_get("")
        return data.get("message") == "API running."

    async def get_config(self) -> dict:
        return await self.rest_get("config")

    async def get_states(self) -> list[dict]:
        return await self.rest_get("states")

    async def get_services(self) -> list[dict]:
        return await self.rest_get("services")

    async def get_history(self, start_iso: str, entity_ids: list[str] | None = None) -> list:
        params: dict[str, str] = {"minimal_response": "1", "no_attributes": "1"}
        if entity_ids:
            params["filter_entity_id"] = ",".join(entity_ids)
        return await self.rest_get(f"history/period/{start_iso}", **params)

    async def get_logbook(self, start_iso: str) -> list:
        return await self.rest_get(f"logbook/{start_iso}")

    async def call_service(self, domain: str, service: str, data: dict | None = None) -> Any:
        return await self.rest_post(f"services/{domain}/{service}", data or {})

    async def render_template(self, template: str) -> str:
        resp = await self.client.post("/api/template", json={"template": template})
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------- WebSocket
    async def ws_commands(self, commands: list[dict]) -> dict[int, Any]:
        """Open one WS connection, authenticate, run all commands, return results by id."""
        results: dict[int, Any] = {}
        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
        ws = await MiniWS.connect(ws_url, timeout=self.timeout)
        try:
            # auth handshake
            msg = json.loads(await ws.recv_text())
            if msg.get("type") == "auth_required":
                await ws.send_text(json.dumps({"type": "auth", "access_token": self.token}))
                msg = json.loads(await ws.recv_text())
            if msg.get("type") != "auth_ok":
                raise HAError(f"WebSocket auth failed: {msg}")

            pending: set[int] = set()
            for i, cmd in enumerate(commands, start=1):
                payload = dict(cmd)
                payload["id"] = i
                await ws.send_text(json.dumps(payload))
                pending.add(i)

            while pending:
                try:
                    msg = json.loads(await ws.recv_text(timeout=60))
                except (WSClosed, asyncio.TimeoutError):
                    break
                if msg.get("type") == "result" and msg.get("id") in pending:
                    pending.discard(msg["id"])
                    if msg.get("success"):
                        results[msg["id"]] = msg.get("result")
                    else:
                        results[msg["id"]] = {"__error__": msg.get("error")}
        finally:
            await ws.close()
        return results

    async def get_registries(self) -> dict[str, Any]:
        """Fetch entity/device/area/label registries, config entries and HACS repos."""
        commands = [
            {"type": "config/entity_registry/list"},      # 1
            {"type": "config/device_registry/list"},      # 2
            {"type": "config/area_registry/list"},        # 3
            {"type": "config/floor_registry/list"},       # 4
            {"type": "config/label_registry/list"},       # 5
            {"type": "config_entries/get"},               # 6
            {"type": "hacs/repositories/list"},           # 7 (only if HACS installed)
        ]
        res = await self.ws_commands(commands)

        def ok(i: int) -> Any:
            v = res.get(i)
            if isinstance(v, dict) and "__error__" in v:
                log.debug("WS command %s failed: %s", commands[i - 1]["type"], v["__error__"])
                return None
            return v

        return {
            "entities": ok(1) or [],
            "devices": ok(2) or [],
            "areas": ok(3) or [],
            "floors": ok(4) or [],
            "labels": ok(5) or [],
            "config_entries": ok(6) or [],
            "hacs_repositories": ok(7),  # None => HACS not installed
        }
