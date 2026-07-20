"""MCP server exposing the learned Home Assistant knowledge to AI clients
(Claude Desktop, Claude Code, or any MCP-capable client).

Run:  ha-learner mcp        (stdio transport)
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .knowledge import KnowledgeBase
from . import interview as iv

mcp = FastMCP("ha-ai-learner")

_cfg = None
_kb = None


def _get_kb() -> KnowledgeBase:
    global _cfg, _kb
    if _kb is None:
        _cfg = load_config()
        _kb = KnowledgeBase(_cfg)
    return _kb


def _j(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def home_summary() -> str:
    """Overview of the Home Assistant setup: counts of entities, devices,
    services, areas, integrations, HACS add-ons and domain breakdown."""
    return _j(_get_kb().summary())


@mcp.tool()
def search_entities(query: str, limit: int = 20) -> str:
    """Search entities by free text (name, room, device, integration, purpose).
    Example queries: 'living room lamp', 'temperature bedroom', 'zigbee motion'.
    Works with any language the knowledge base contains."""
    return _j(_get_kb().search(query, limit=limit))


@mcp.tool()
def get_entity(entity_id: str) -> str:
    """Full detail of one entity, including learned answers and usage patterns."""
    e = _get_kb().enriched_entities().get(entity_id)
    return _j(e) if e else f"Entity '{entity_id}' not found."


@mcp.tool()
def list_areas() -> str:
    """List all areas/rooms with their entity counts."""
    kb = _get_kb()
    areas: dict[str, int] = {}
    for e in kb.enriched_entities().values():
        areas[e.get("area") or "(no area)"] = areas.get(e.get("area") or "(no area)", 0) + 1
    return _j(areas)


@mcp.tool()
def list_services(domain: str = "") -> str:
    """List callable Home Assistant services, optionally filtered by domain
    (e.g. 'light', 'climate')."""
    svcs = _get_kb().snapshot.get("services", {})
    if domain:
        svcs = {k: v for k, v in svcs.items() if k.startswith(domain + ".")}
    return _j({k: v.get("description", "") for k, v in sorted(svcs.items())})


@mcp.tool()
def get_service(service: str) -> str:
    """Full detail of one service including its fields (e.g. 'light.turn_on')."""
    s = _get_kb().snapshot.get("services", {}).get(service)
    return _j(s) if s else f"Service '{service}' not found."


@mcp.tool()
def usage_patterns() -> str:
    """Learned usage patterns: per-entity activity and candidate routines."""
    return _j(_get_kb().patterns)


@mcp.tool()
def pending_questions(limit: int = 10) -> str:
    """Questions the learner wants to ask the user about unclear entities.
    Present these to the user, then store replies with answer_question."""
    kb = _get_kb()
    return _j(iv.pending_questions(_cfg)[:limit])


@mcp.tool()
def answer_question(entity_id: str, location: str = "", purpose: str = "", note: str = "") -> str:
    """Store the user's answer about an entity (its room/location, its purpose,
    or a free-form note). The knowledge base is updated permanently."""
    kb = _get_kb()
    learned = iv.answer(_cfg, kb, entity_id,
                        location=location or None,
                        purpose=purpose or None,
                        note=note or None)
    return _j({"entity_id": entity_id, "learned": learned})


@mcp.tool()
async def rescan() -> str:
    """Run a fresh discovery scan of Home Assistant now and report what changed.
    Requires network access to the HA instance."""
    from .scanner import scan
    kb = _get_kb()
    snapshot = await scan(_cfg)
    changes = kb.update_from_scan(snapshot)
    iv.refresh_questions(_cfg, kb)
    return _j({"changes": changes, "summary": kb.summary()})


@mcp.tool()
def recent_changes(lines: int = 30) -> str:
    """Show the most recent detected changes (new/removed/renamed entities,
    devices, HACS add-ons)."""
    kb = _get_kb()
    if not _cfg.changes_log.is_file():
        return "No changes logged yet."
    content = _cfg.changes_log.read_text(encoding="utf-8").strip().splitlines()
    return "\n".join(content[-lines:])


@mcp.tool()
async def get_live_state(entity_id: str) -> str:
    """Fetch the CURRENT live state of an entity directly from Home Assistant
    (the knowledge base state may be from the last scan)."""
    from .ha_client import HAClient
    kb = _get_kb()
    async with HAClient(_cfg.ha_url, _cfg.ha_token) as ha:
        state = await ha.rest_get(f"states/{entity_id}")
    return _j(state)


@mcp.tool()
async def call_service(service: str, entity_id: str = "", data_json: str = "") -> str:
    """Call a Home Assistant service (e.g. 'light.turn_on' on a given entity).
    Only enabled when allow_service_calls=true in the learner config."""
    kb = _get_kb()
    if not _cfg.allow_service_calls:
        return ("Service calls are disabled. Set allow_service_calls: true in "
                "config.yaml (or HA_LEARNER_ALLOW_CALLS=1) to enable control.")
    from .ha_client import HAClient
    domain, _, name = service.partition(".")
    payload = json.loads(data_json) if data_json else {}
    if entity_id:
        payload["entity_id"] = entity_id
    async with HAClient(_cfg.ha_url, _cfg.ha_token) as ha:
        result = await ha.call_service(domain, name, payload)
    return _j(result)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
