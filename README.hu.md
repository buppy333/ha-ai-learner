# HA-AI Learner

**Öntanuló felfedező eszköz + MCP szerver, ami a Home Assistant okosotthonodból olyan tudásbázist épít, amit egy AI asszisztens ténylegesen használni tud.**

*In English: [README.md](README.md)*

---

Az AI asszisztensek jól gondolkodnak az okosotthonodról — csak éppen semmit sem tudnak róla. Melyik entitás a konyhai lámpa? Mit kapcsol valójában a `switch.sonoff_3`? Milyen service-ek hívhatók, és mikor szoktál mit bekapcsolni?

A HA-AI Learner ezt egyszer megválaszolja, tartósan megjegyzi, és frissen tartja:

1. **Felfedezés** — a HA REST + WebSocket API-n keresztül feltérképezi az összes entitást, eszközt, területet/emeletet, címkét, service-t, integrációt és a telepített HACS bővítményeket.
2. **Tudásbázis** — mindebből olvasható Markdown (`knowledge.md`) és géppel feldolgozható JSON (`knowledge.json`) épül.
3. **Változáskövetés** — minden újra-scan diffet készít (új/törölt/átnevezett entitás, új HACS bővítmény…), és a `changes.log`-ba írja.
4. **Kérdez, ha nem érti** — a bizonytalan entitásokhoz (pl. `switch.sonoff_3`, nincs terület, generált név) kérdéseket generál; a válaszaid véglegesen beépülnek a tudásbázisba.
5. **Használati minták** — a HA history alapján megtanulja, mikor mit használsz (aktív órák, tipikus bekapcsolási idő, együtt kapcsolódó eszközök → rutin-jelöltek).
6. **MCP szerver** — a Claude (Desktop / Code / Cowork) vagy bármely MCP-képes kliens eszközként éri el a tudást: keresés, entitás/service lekérdezés, kérdés-válasz, azonnali újra-scan, élő állapot, és — csak ha engedélyezed — vezérlés.

## Telepítés

Bármely gépen futhat, ami eléri a HA-t a helyi hálózaton (lehet maga a HA gép is). Python 3.10+ szükséges.

```bash
git clone https://github.com/buppy333/ha-ai-learner.git
cd ha-ai-learner
pip install -e .
```

## Beállítás

1. HA felület → bal alul a **profilod** → **Biztonság** fül → *Hosszú élettartamú hozzáférési kulcsok* → **Kulcs létrehozása** → másold ki.
2. Másold a `config.example.yaml`-t `config.yaml` néven (vagy `~/.config/ha-ai-learner/config.yaml`), és írd be az URL-t + tokent.

Környezeti változóval is mehet: `HA_URL`, `HA_TOKEN`, `HA_LEARNER_DATA_DIR`, `HA_LEARNER_ALLOW_CALLS`.

## Használat

```bash
ha-learner scan                # egyszeri teljes felderítés + tudásbázis
ha-learner scan --patterns     # + használati minták tanulása a history-ból
ha-learner watch               # periodikus scan (alapból 60 percenként)
ha-learner interview           # interaktív kérdezz-felelek a kétes entitásokról
ha-learner questions           # függő kérdések listázása (JSON)
ha-learner answer switch.sonoff_3 --location "Konyha" --purpose "kávéfőző"
ha-learner find "nappali lámpa"
ha-learner summary
ha-learner mcp                 # MCP szerver indítása (stdio)
```

A tudásbázis alapból ide kerül: `~/.ha-ai-learner/`
(`knowledge.md`, `knowledge.json`, `answers.json`, `questions.json`, `patterns.json`, `changes.log`)

### Időzített futtatás

- Linux/HA gépen: `ha-learner watch` (systemd service-ként vagy tmux alatt), vagy cron:
  `0 * * * * ha-learner scan --patterns`
- A Claude az MCP-n keresztül is tud kézzel frissíteni (`rescan` eszköz).

## MCP szerver bekötése Claude Desktopba

`claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "ha-ai-learner": {
      "command": "ha-learner",
      "args": ["mcp"],
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "A_TOKENED"
      }
    }
  }
}
```

Claude Code-hoz: `claude mcp add ha-ai-learner -- ha-learner mcp`

**Elérhető MCP eszközök:** `home_summary`, `search_entities`, `get_entity`, `list_areas`, `list_services`, `get_service`, `usage_patterns`, `pending_questions`, `answer_question`, `rescan`, `recent_changes`, `get_live_state`, `call_service`.

**Így működik a „kérdések útján azonosítás":** a Claude meghívja a `pending_questions` eszközt, felteszi neked a kérdéseket („Melyik helyiségben van a `switch.sonoff_3`?"), a válaszodat az `answer_question`-nel elmenti — és onnantól a tudásbázis örökre tudja, újra-scanek után is.

## Biztonság

- Alapértelmezésben **csak olvas** — a `call_service` (vezérlés) csak akkor él, ha a configban `allow_service_calls: true`.
- A token a helyi config fájlodban van — soha ne kerüljön Gitbe. A `config.yaml` benne van a `.gitignore`-ban.
- Az MCP szerver stdio-n fut a saját gépeden; a hálózat felé csak a saját HA-d felé megy hívás.

## Tesztelés

Teljes end-to-end teszt a beépített mock HA szerver ellen (nem kell hozzá élő HA):

```bash
python3 tests/test_e2e.py
```

## Licenc

[MIT](LICENSE) © Pénzes Tamás
