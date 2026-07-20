"""Usage-pattern learning from Home Assistant history.

Downloads state history for 'actionable' entities and mines simple,
explainable patterns:
  * per-entity activity histogram by hour of day,
  * typical on/off times for lights & switches,
  * frequently co-occurring entities (within a 5-minute window) → candidate routines.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from .config import Config
from .ha_client import HAClient

ACTION_DOMAINS = {"light", "switch", "media_player", "cover", "climate", "fan",
                  "lock", "vacuum", "scene", "script"}
ACTIVE_STATES = {"on", "playing", "open", "heat", "cool", "heating", "cooling",
                 "unlocked", "cleaning"}


def _parse_ts(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def learn_patterns(cfg: Config, snapshot: dict) -> dict[str, Any]:
    entities = snapshot.get("entities", {})
    targets = [eid for eid, e in entities.items()
               if e["domain"] in ACTION_DOMAINS and not e.get("disabled")][:100]
    if not targets:
        return {"entities": {}, "routines": [], "note": "no actionable entities"}

    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg.history_days))
    start_iso = start.isoformat()

    async with HAClient(cfg.ha_url, cfg.ha_token, timeout=120) as ha:
        history = await ha.get_history(start_iso, targets)

    per_entity: dict[str, dict] = {}
    activations: list[tuple[dt.datetime, str]] = []

    for series in history or []:
        if not series:
            continue
        eid = series[0].get("entity_id")
        hours = Counter()
        on_times: list[dt.datetime] = []
        changes = 0
        prev_state = None
        for point in series:
            ts = _parse_ts(point.get("last_changed") or point.get("last_updated") or "")
            state = point.get("state")
            if ts is None or state in ("unknown", "unavailable", None):
                continue
            changes += 1
            local = ts.astimezone()
            hours[local.hour] += 1
            if state in ACTIVE_STATES and prev_state not in ACTIVE_STATES:
                on_times.append(local)
                activations.append((ts, eid))
            prev_state = state

        if changes < 2:
            continue

        busiest = [h for h, _ in hours.most_common(3)]
        summary_bits = [f"{changes} state changes in {cfg.history_days} days"]
        if busiest:
            summary_bits.append("most active hours: " + ", ".join(f"{h}:00" for h in sorted(busiest)))
        if on_times:
            avg_hour = sorted(t.hour for t in on_times)[len(on_times) // 2]
            summary_bits.append(f"typically switches on around {avg_hour}:00")

        per_entity[eid] = {
            "changes": changes,
            "busiest_hours": sorted(busiest),
            "activations": len(on_times),
            "summary": " · ".join(summary_bits),
        }

    # ------------------------------------------------ co-occurrence routines
    activations.sort(key=lambda x: x[0])
    pair_counts: Counter = Counter()
    window = dt.timedelta(minutes=5)
    for i, (ts, eid) in enumerate(activations):
        j = i + 1
        while j < len(activations) and activations[j][0] - ts <= window:
            other = activations[j][1]
            if other != eid:
                pair_counts[tuple(sorted((eid, other)))] += 1
            j += 1

    routines: list[str] = []
    for (a, b), count in pair_counts.most_common(15):
        if count >= 3:
            name_a = entities.get(a, {}).get("name", a)
            name_b = entities.get(b, {}).get("name", b)
            routines.append(
                f"'{name_a}' ({a}) and '{name_b}' ({b}) often activate together "
                f"({count}x in {cfg.history_days} days, within 5 minutes)"
            )

    return {
        "learned_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "history_days": cfg.history_days,
        "entities": per_entity,
        "routines": routines,
    }
