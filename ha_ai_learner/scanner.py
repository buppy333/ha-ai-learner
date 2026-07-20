"""Full discovery scan of a Home Assistant instance → structured snapshot."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .config import Config
from .ha_client import HAClient

log = logging.getLogger(__name__)


def _index(items: list[dict], key: str) -> dict[str, dict]:
    return {it[key]: it for it in items if it.get(key)}


async def scan(cfg: Config) -> dict[str, Any]:
    """Run a full scan and return a normalized snapshot dict."""
    async with HAClient(cfg.ha_url, cfg.ha_token) as ha:
        await ha.ping()
        ha_config = await ha.get_config()
        states = await ha.get_states()
        services = await ha.get_services()
        reg = await ha.get_registries()

    areas = _index(reg["areas"], "area_id")
    floors = _index(reg["floors"], "floor_id")
    devices = _index(reg["devices"], "id")
    entity_reg = _index(reg["entities"], "entity_id")
    states_by_id = {s["entity_id"]: s for s in states}
    entries = _index(reg["config_entries"], "entry_id")

    # ------------------------------------------------------------- entities
    entities: dict[str, dict] = {}
    all_ids = set(entity_reg) | set(states_by_id)
    for eid in sorted(all_ids):
        if eid.startswith(cfg.ignore_prefixes):
            continue
        r = entity_reg.get(eid, {})
        s = states_by_id.get(eid, {})
        attrs = s.get("attributes", {})
        device = devices.get(r.get("device_id") or "")
        area_id = r.get("area_id") or (device or {}).get("area_id")
        area = areas.get(area_id or "")
        entry = entries.get((device or {}).get("primary_config_entry") or "")

        entities[eid] = {
            "entity_id": eid,
            "domain": eid.split(".", 1)[0],
            "name": r.get("name") or attrs.get("friendly_name") or r.get("original_name") or eid,
            "state": s.get("state"),
            "unit": attrs.get("unit_of_measurement"),
            "device_class": attrs.get("device_class") or r.get("original_device_class"),
            "icon": r.get("icon") or attrs.get("icon"),
            "device_id": r.get("device_id"),
            "device_name": (device or {}).get("name_by_user") or (device or {}).get("name"),
            "area_id": area_id,
            "area": (area or {}).get("name"),
            "floor": (floors.get((area or {}).get("floor_id") or "") or {}).get("name"),
            "labels": r.get("labels") or [],
            "platform": r.get("platform"),
            "integration": (entry or {}).get("title") or r.get("platform"),
            "disabled": bool(r.get("disabled_by")),
            "hidden": bool(r.get("hidden_by")),
            "entity_category": r.get("entity_category"),
            "supported_features": attrs.get("supported_features"),
            "capabilities": r.get("capabilities"),
            "last_changed": s.get("last_changed"),
        }

    # -------------------------------------------------------------- devices
    device_out: dict[str, dict] = {}
    for did, d in devices.items():
        device_out[did] = {
            "id": did,
            "name": d.get("name_by_user") or d.get("name"),
            "manufacturer": d.get("manufacturer"),
            "model": d.get("model"),
            "sw_version": d.get("sw_version"),
            "area": (areas.get(d.get("area_id") or "") or {}).get("name"),
            "via_device": d.get("via_device_id"),
            "entities": sorted(e for e, v in entities.items() if v["device_id"] == did),
            "integration": (entries.get(d.get("primary_config_entry") or "") or {}).get("title"),
        }

    # ------------------------------------------------------------- services
    service_out: dict[str, dict] = {}
    for svc_domain in services:
        domain = svc_domain.get("domain")
        for name, meta in (svc_domain.get("services") or {}).items():
            service_out[f"{domain}.{name}"] = {
                "service": f"{domain}.{name}",
                "name": meta.get("name") or name,
                "description": meta.get("description") or "",
                "fields": {
                    fname: {
                        "description": f.get("description") or "",
                        "required": f.get("required", False),
                        "example": f.get("example"),
                    }
                    for fname, f in (meta.get("fields") or {}).items()
                },
            }

    # ---------------------------------------------------------- integrations
    integrations: dict[str, dict] = {}
    for e in reg["config_entries"]:
        integrations.setdefault(e.get("domain"), {
            "domain": e.get("domain"),
            "titles": [],
            "source": e.get("source"),
        })["titles"].append(e.get("title"))

    hacs = None
    if reg["hacs_repositories"] is not None:
        repos = reg["hacs_repositories"]
        if isinstance(repos, dict):  # newer HACS returns dict with 'repositories'
            repos = repos.get("repositories", repos)
        hacs = [
            {
                "name": r.get("name") or r.get("full_name"),
                "category": r.get("category"),
                "installed_version": r.get("installed_version") or r.get("version_installed"),
            }
            for r in (repos or [])
            if isinstance(r, dict) and (r.get("installed") or r.get("installed_version") or r.get("version_installed"))
        ]

    return {
        "scanned_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ha_version": ha_config.get("version"),
        "location_name": ha_config.get("location_name"),
        "components": sorted(ha_config.get("components", [])),
        "areas": {a["area_id"]: {"name": a.get("name"),
                                 "floor": (floors.get(a.get("floor_id") or "") or {}).get("name")}
                  for a in reg["areas"]},
        "floors": {f["floor_id"]: f.get("name") for f in reg["floors"]},
        "labels": {l["label_id"]: l.get("name") for l in reg["labels"]},
        "entities": entities,
        "devices": device_out,
        "services": service_out,
        "integrations": integrations,
        "hacs_installed": reg["hacs_repositories"] is not None,
        "hacs_repositories": hacs or [],
    }
