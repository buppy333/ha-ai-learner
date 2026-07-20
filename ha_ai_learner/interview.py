"""Interview module — generates clarifying questions for entities the AI
cannot confidently identify, and stores the human answers.

Heuristics for "unclear" entities:
  * no area assigned (and its device has none either),
  * generic / auto-generated name (sonoff_3, shelly1_ABC123, 0x00158d...),
  * name equals the entity_id,
  * duplicate friendly names across different devices.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .config import Config
from .knowledge import KnowledgeBase, _load_json, _save_json

GENERIC_NAME_RE = re.compile(
    r"(_\d+$)|(0x[0-9a-f]{6,})|([0-9a-f]{6,}$)|(esp_?\d)|(tasmota)|(sonoff[_ ]?\d)|"
    r"(shelly\w*[-_][0-9a-f]{4,})|(^switch \d+$)|(^sensor \d+$)",
    re.IGNORECASE,
)

INTERESTING_DOMAINS = {
    "light", "switch", "sensor", "binary_sensor", "climate", "cover", "fan",
    "media_player", "lock", "camera", "vacuum", "humidifier", "water_heater",
    "button", "number", "select", "siren", "valve",
}


def find_unclear_entities(kb: KnowledgeBase, limit: int = 50) -> list[dict]:
    entities = kb.enriched_entities()
    name_counts = Counter(
        e.get("name") for e in entities.values() if not e.get("disabled")
    )

    questions: list[dict] = []
    for eid, e in entities.items():
        if e.get("disabled") or e.get("hidden"):
            continue
        if e["domain"] not in INTERESTING_DOMAINS:
            continue
        if e.get("entity_category") in ("diagnostic", "config"):
            continue
        learned = e.get("learned", {})

        reasons = []
        if not e.get("area") and not learned.get("location"):
            reasons.append("not assigned to any area")
        name = e.get("name") or ""
        if (name == eid or GENERIC_NAME_RE.search(name)) and not learned.get("purpose"):
            reasons.append(f"generic/auto-generated name: '{name}'")
        if name_counts.get(name, 0) > 1 and not learned.get("purpose"):
            reasons.append(f"multiple entities share the name '{name}'")

        if not reasons:
            continue

        q_texts = []
        if not e.get("area"):
            q_texts.append(f"Which room is '{name}' ({eid}) located in?")
        if any("name" in r for r in reasons):
            q_texts.append(f"What exactly does {eid} ('{name}') control or measure?")

        questions.append({
            "entity_id": eid,
            "name": name,
            "domain": e["domain"],
            "device": e.get("device_name"),
            "integration": e.get("integration"),
            "state": e.get("state"),
            "reasons": reasons,
            "questions": q_texts,
        })
        if len(questions) >= limit:
            break

    return questions


def refresh_questions(cfg: Config, kb: KnowledgeBase) -> list[dict]:
    """Regenerate the pending-questions file (dropping already-answered ones)."""
    qs = find_unclear_entities(kb)
    _save_json(cfg.questions_file, qs)
    return qs


def pending_questions(cfg: Config) -> list[dict]:
    return _load_json(cfg.questions_file, [])


def answer(cfg: Config, kb: KnowledgeBase, entity_id: str, *,
           location: str | None = None, purpose: str | None = None,
           note: str | None = None) -> dict:
    """Record a human answer; it is merged into the knowledge base permanently."""
    if location:
        kb.set_answer(entity_id, "location", location)
    if purpose:
        kb.set_answer(entity_id, "purpose", purpose)
    if note:
        kb.set_answer(entity_id, "note", note)

    # drop from pending list
    qs = [q for q in pending_questions(cfg) if q["entity_id"] != entity_id]
    _save_json(cfg.questions_file, qs)
    return kb.answers.get(entity_id, {})
