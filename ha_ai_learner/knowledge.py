"""Knowledge base: persistence, change detection and Markdown generation.

The knowledge base merges three sources:
  1. the latest scan snapshot (facts),
  2. learned answers from the interview module (human clarifications),
  3. usage patterns mined from history.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import Config


def _load_json(path: Path, default: Any) -> Any:
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- diff
def diff_snapshots(old: dict | None, new: dict) -> list[str]:
    """Human-readable list of changes between two snapshots."""
    if not old:
        return [f"Initial scan: {len(new['entities'])} entities, {len(new['devices'])} devices, "
                f"{len(new['services'])} services."]

    changes: list[str] = []

    def keyset(section: str) -> tuple[set, set]:
        return set(old.get(section, {})), set(new.get(section, {}))

    for section, label in [("entities", "entity"), ("devices", "device"),
                           ("services", "service"), ("integrations", "integration"),
                           ("areas", "area")]:
        o, n = keyset(section)
        for added in sorted(n - o):
            name = new[section][added].get("name") if isinstance(new[section][added], dict) else new[section][added]
            changes.append(f"+ New {label}: {added} ({name})")
        for removed in sorted(o - n):
            changes.append(f"- Removed {label}: {removed}")

    # renamed / moved entities
    for eid in set(old.get("entities", {})) & set(new.get("entities", {})):
        o_e, n_e = old["entities"][eid], new["entities"][eid]
        if o_e.get("name") != n_e.get("name"):
            changes.append(f"~ Renamed: {eid}: '{o_e.get('name')}' → '{n_e.get('name')}'")
        if o_e.get("area") != n_e.get("area"):
            changes.append(f"~ Moved: {eid}: '{o_e.get('area')}' → '{n_e.get('area')}'")

    # HACS
    o_hacs = {r["name"] for r in old.get("hacs_repositories", [])}
    n_hacs = {r["name"] for r in new.get("hacs_repositories", [])}
    for r in sorted(n_hacs - o_hacs):
        changes.append(f"+ New HACS add-on: {r}")
    for r in sorted(o_hacs - n_hacs):
        changes.append(f"- Removed HACS add-on: {r}")

    return changes


# ------------------------------------------------------------ knowledge base
class KnowledgeBase:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.snapshot: dict = _load_json(cfg.snapshot_file, {})
        self.answers: dict = _load_json(cfg.answers_file, {})
        self.patterns: dict = _load_json(cfg.patterns_file, {})

    # ------------------------------------------------------------- updating
    def update_from_scan(self, snapshot: dict) -> list[str]:
        """Store a new snapshot; return the list of detected changes."""
        changes = diff_snapshots(self.snapshot or None, snapshot)
        self.snapshot = snapshot
        _save_json(self.cfg.snapshot_file, snapshot)

        if changes:
            with open(self.cfg.changes_log, "a", encoding="utf-8") as f:
                stamp = dt.datetime.now().isoformat(timespec="seconds")
                for c in changes:
                    f.write(f"{stamp}  {c}\n")

        self.rebuild()
        return changes

    def set_answer(self, entity_id: str, field: str, value: str) -> None:
        self.answers.setdefault(entity_id, {})[field] = value
        _save_json(self.cfg.answers_file, self.answers)
        self.rebuild()

    def set_patterns(self, patterns: dict) -> None:
        self.patterns = patterns
        _save_json(self.cfg.patterns_file, patterns)
        self.rebuild()

    # -------------------------------------------------------------- queries
    def enriched_entities(self) -> dict[str, dict]:
        """Entities with learned answers merged in."""
        out = {}
        for eid, e in self.snapshot.get("entities", {}).items():
            e = dict(e)
            learned = self.answers.get(eid, {})
            if learned:
                e["learned"] = learned
                if learned.get("purpose"):
                    e["purpose"] = learned["purpose"]
                if learned.get("location"):
                    e["area"] = e["area"] or learned["location"]
            if eid in self.patterns.get("entities", {}):
                e["usage"] = self.patterns["entities"][eid]
            out[eid] = e
        return out

    def search(self, query: str, limit: int = 20) -> list[dict]:
        q = query.lower()
        terms = q.split()
        scored = []
        for e in self.enriched_entities().values():
            hay = " ".join(str(x) for x in [
                e["entity_id"], e.get("name"), e.get("area"), e.get("floor"),
                e.get("device_name"), e.get("integration"), e.get("device_class"),
                e.get("purpose"), " ".join(e.get("labels", [])),
                json.dumps(e.get("learned", {}), ensure_ascii=False),
            ]).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1]["entity_id"]))
        return [e for _, e in scored[:limit]]

    # ------------------------------------------------------------- markdown
    def rebuild(self) -> None:
        """Regenerate knowledge.json and knowledge.md from current state."""
        snap = self.snapshot
        if not snap:
            return

        entities = self.enriched_entities()
        kb = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "ha_version": snap.get("ha_version"),
            "location_name": snap.get("location_name"),
            "areas": snap.get("areas", {}),
            "entities": entities,
            "devices": snap.get("devices", {}),
            "services": snap.get("services", {}),
            "integrations": snap.get("integrations", {}),
            "hacs_repositories": snap.get("hacs_repositories", []),
            "patterns": self.patterns,
        }
        _save_json(self.cfg.kb_json, kb)

        md = self._markdown(kb)
        self.cfg.kb_markdown.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.kb_markdown.write_text(md, encoding="utf-8")

    def _markdown(self, kb: dict) -> str:
        lines: list[str] = []
        add = lines.append
        add(f"# Home Assistant knowledge base — {kb.get('location_name') or 'home'}")
        add("")
        add(f"*Generated: {kb['generated_at']} · HA version: {kb.get('ha_version')}*")
        add("")

        # Areas with entities grouped
        by_area: dict[str, list[dict]] = {}
        for e in kb["entities"].values():
            if e.get("disabled") or e.get("hidden"):
                continue
            by_area.setdefault(e.get("area") or "— no area —", []).append(e)

        add("## Areas and entities")
        add("")
        for area in sorted(by_area):
            ents = by_area[area]
            add(f"### {area} ({len(ents)} entities)")
            add("")
            for e in sorted(ents, key=lambda x: (x["domain"], x["entity_id"])):
                bits = [f"`{e['entity_id']}`", f"**{e['name']}**"]
                if e.get("state") is not None:
                    st = e["state"]
                    if e.get("unit"):
                        st = f"{st} {e['unit']}"
                    bits.append(f"state: {st}")
                if e.get("device_name"):
                    bits.append(f"device: {e['device_name']}")
                if e.get("purpose"):
                    bits.append(f"purpose: {e['purpose']}")
                if e.get("usage", {}).get("summary"):
                    bits.append(f"usage: {e['usage']['summary']}")
                add(f"- {' · '.join(bits)}")
            add("")

        # Devices
        add("## Devices")
        add("")
        for d in sorted(kb["devices"].values(), key=lambda x: (x.get("area") or "zzz", x.get("name") or "")):
            add(f"- **{d.get('name')}** ({d.get('manufacturer') or '?'} {d.get('model') or ''}) — "
                f"area: {d.get('area') or '?'} · integration: {d.get('integration') or '?'} · "
                f"{len(d.get('entities', []))} entities")
        add("")

        # Services by domain
        add("## Available services (callable actions)")
        add("")
        by_domain: dict[str, list] = {}
        for s in kb["services"].values():
            by_domain.setdefault(s["service"].split(".")[0], []).append(s)
        for domain in sorted(by_domain):
            add(f"### {domain}")
            add("")
            for s in sorted(by_domain[domain], key=lambda x: x["service"]):
                desc = (s.get("description") or "").split(".")[0]
                add(f"- `{s['service']}` — {desc}")
            add("")

        # Integrations + HACS
        add("## Integrations")
        add("")
        for dom in sorted(kb["integrations"]):
            i = kb["integrations"][dom]
            add(f"- **{dom}**: {', '.join(t for t in i.get('titles', []) if t)}")
        add("")
        if kb.get("hacs_repositories"):
            add("## HACS add-ons")
            add("")
            for r in sorted(kb["hacs_repositories"], key=lambda x: x.get("name") or ""):
                add(f"- {r.get('name')} ({r.get('category')}) — version: {r.get('installed_version') or '?'}")
            add("")

        # Patterns
        pats = kb.get("patterns", {})
        if pats.get("routines"):
            add("## Learned usage patterns")
            add("")
            for r in pats["routines"]:
                add(f"- {r}")
            add("")

        return "\n".join(lines)

    # ------------------------------------------------------------ summaries
    def summary(self) -> dict:
        snap = self.snapshot
        ents = snap.get("entities", {})
        domains = Counter(e["domain"] for e in ents.values())
        return {
            "scanned_at": snap.get("scanned_at"),
            "ha_version": snap.get("ha_version"),
            "location_name": snap.get("location_name"),
            "entity_count": len(ents),
            "device_count": len(snap.get("devices", {})),
            "service_count": len(snap.get("services", {})),
            "area_count": len(snap.get("areas", {})),
            "integration_count": len(snap.get("integrations", {})),
            "hacs_installed": snap.get("hacs_installed"),
            "hacs_count": len(snap.get("hacs_repositories", [])),
            "domains": dict(domains.most_common()),
            "answered_questions": sum(len(v) for v in self.answers.values()),
        }
