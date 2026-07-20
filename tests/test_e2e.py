"""End-to-end test against the mock HA server: scan → KB → diff → questions → patterns.

The mock data intentionally uses Hungarian entity names (accented Unicode) to
verify that discovery, search and Markdown generation are encoding-safe."""
from __future__ import annotations

import asyncio
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_ha
from ha_ai_learner.config import Config
from ha_ai_learner.knowledge import KnowledgeBase, diff_snapshots
from ha_ai_learner.scanner import scan
from ha_ai_learner.patterns import learn_patterns
from ha_ai_learner import interview as iv


async def main() -> None:
    server = await mock_ha.start(18123)
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(ha_url="http://127.0.0.1:18123", ha_token="test-token", data_dir=tmp)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    # 1) full scan
    snap = await scan(cfg)
    assert snap["ha_version"] == "2026.7.1", snap["ha_version"]
    assert len(snap["entities"]) == 3, snap["entities"].keys()
    assert snap["entities"]["light.nappali_lampa"]["area"] == "Nappali"
    assert snap["entities"]["light.nappali_lampa"]["floor"] == "Földszint"
    assert snap["entities"]["switch.sonoff_3"]["area"] is None
    assert "light.turn_on" in snap["services"]
    assert snap["hacs_installed"] is True
    assert snap["hacs_repositories"][0]["name"] == "sonoff-lan"
    print("✔ scan OK — entities, areas, services, HACS")

    # 2) knowledge base + markdown
    kb = KnowledgeBase(cfg)
    changes = kb.update_from_scan(snap)
    assert changes and "Initial scan" in changes[0]
    md = cfg.kb_markdown.read_text(encoding="utf-8")
    assert "Nappali lámpa" in md and "light.turn_on" in md and "sonoff-lan" in md
    assert cfg.kb_json.is_file()
    print("✔ knowledge base (JSON + Markdown) OK")

    # 3) interview questions (sonoff_3: no area + generic name)
    qs = iv.refresh_questions(cfg, kb)
    ids = [q["entity_id"] for q in qs]
    assert "switch.sonoff_3" in ids, ids
    assert "light.nappali_lampa" not in ids
    iv.answer(cfg, kb, "switch.sonoff_3", location="Konyha", purpose="kávéfőző kapcsoló")  # Hungarian on purpose: Unicode round-trip
    assert "switch.sonoff_3" not in [q["entity_id"] for q in iv.pending_questions(cfg)]
    e = kb.enriched_entities()["switch.sonoff_3"]
    assert e["purpose"] == "kávéfőző kapcsoló" and e["area"] == "Konyha"
    md = cfg.kb_markdown.read_text(encoding="utf-8")
    assert "kávéfőző kapcsoló" in md
    print("✔ interview: question generation + answer merged into the KB")

    # 4) search
    hits = kb.search("kávéfőző")
    assert hits and hits[0]["entity_id"] == "switch.sonoff_3"
    hits = kb.search("nappali lámpa")
    assert hits[0]["entity_id"] == "light.nappali_lampa"
    print("✔ search OK")

    # 5) diff on a modified second scan
    snap2 = copy.deepcopy(snap)
    snap2["entities"]["sensor.uj_szenzor"] = dict(
        snap["entities"]["sensor.halo_homerseklet"], entity_id="sensor.uj_szenzor",
        name="Új szenzor")
    del snap2["entities"]["light.nappali_lampa"]
    snap2["hacs_repositories"].append({"name": "browser-mod", "category": "integration",
                                       "installed_version": "2.3"})
    changes = kb.update_from_scan(snap2)
    text = "\n".join(changes)
    assert "sensor.uj_szenzor" in text and "light.nappali_lampa" in text
    assert "browser-mod" in text
    assert cfg.changes_log.is_file()
    print("✔ change detection OK:", len(changes), "changes")

    # 6) usage patterns from history
    kb.update_from_scan(snap)  # restore
    pats = await learn_patterns(cfg, kb.snapshot)
    assert pats["entities"], pats
    assert any("sonoff" in r or "lampa" in r or "lámpa" in r.lower() for r in pats["routines"]), pats["routines"]
    kb.set_patterns(pats)
    md = cfg.kb_markdown.read_text(encoding="utf-8")
    assert "Learned usage patterns" in md
    print("✔ pattern learning OK —", len(pats["routines"]), "candidate routine(s)")

    # 7) summary
    s = kb.summary()
    assert s["entity_count"] == 3 and s["hacs_installed"]
    print("✔ summary OK:", s["domains"])

    server.close()
    await server.wait_closed()
    print("\nALL TESTS PASSED ✅")


if __name__ == "__main__":
    asyncio.run(main())
