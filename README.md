# HA-AI Learner

**A self-learning discovery tool + MCP server that turns your Home Assistant into knowledge an AI assistant can actually use.**

[![CI](https://github.com/buppy333/ha-ai-learner/actions/workflows/ci.yml/badge.svg)](https://github.com/buppy333/ha-ai-learner/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)](https://modelcontextprotocol.io)

*Magyarul: [README.hu.md](README.hu.md)*

---

AI assistants are great at reasoning about your smart home — but they know nothing about it. Which entity is the kitchen light? What does `switch.sonoff_3` actually switch? What services can be called, and when do you usually turn things on?

HA-AI Learner answers this once, persistently, and keeps it fresh:

1. **Discovers** everything through the Home Assistant REST + WebSocket APIs: entities, devices, areas/floors, labels, services, integrations, and installed HACS add-ons.
2. **Builds a knowledge base** as human-readable Markdown (`knowledge.md`) and machine-readable JSON (`knowledge.json`).
3. **Tracks changes** — every re-scan produces a diff (new/removed/renamed/moved entities, new HACS add-ons…) appended to `changes.log`.
4. **Asks when it doesn't understand** — entities with generated names (`switch.sonoff_3`), no area, or duplicate names get clarifying questions; your answers merge into the knowledge base permanently.
5. **Learns usage patterns** from history: active hours, typical switch-on times, and entities that activate together (candidate routines).
6. **Serves it all over MCP** — Claude (Desktop / Code / Cowork) or any MCP client can search entities, inspect services, ask you the pending questions, trigger a re-scan, read live state, and (only if you enable it) control devices.

```text
┌─────────────────┐   REST + WebSocket   ┌──────────────────┐
│  Home Assistant │ ◄──────────────────► │   ha-learner     │
│  (your home)    │                      │  scan · diff ·   │
└─────────────────┘                      │  interview ·     │
                                         │  patterns        │
                                         └────────┬─────────┘
                                                  │ writes
                                    ┌─────────────▼─────────────┐
                                    │  ~/.ha-ai-learner/        │
                                    │  knowledge.md / .json     │
                                    │  answers · questions      │
                                    │  patterns · changes.log   │
                                    └─────────────┬─────────────┘
                                                  │ serves (stdio)
                                         ┌────────▼─────────┐
                                         │   MCP server     │ ◄── Claude Desktop,
                                         │  13 tools        │     Claude Code, …
                                         └──────────────────┘
```

## Installation

Runs on any machine that can reach your HA instance on the local network (including the HA host itself). Python 3.10+.

```bash
git clone https://github.com/buppy333/ha-ai-learner.git
cd ha-ai-learner
pip install -e .
```

## Setup

1. Create a Home Assistant **long-lived access token**: HA UI → your profile (bottom left) → **Security** tab → *Long-lived access tokens* → **Create token**.
2. Copy `config.example.yaml` to `config.yaml` (or `~/.config/ha-ai-learner/config.yaml`) and fill in your URL + token.

Environment variables work too: `HA_URL`, `HA_TOKEN`, `HA_LEARNER_DATA_DIR`, `HA_LEARNER_ALLOW_CALLS`.

## Usage

```bash
ha-learner scan                # one full discovery scan + knowledge base build
ha-learner scan --patterns     # + learn usage patterns from history
ha-learner watch               # periodic scanning (default: every 60 minutes)
ha-learner interview           # interactive Q&A about unclear entities
ha-learner questions           # list pending questions (JSON)
ha-learner answer switch.sonoff_3 --location "Kitchen" --purpose "coffee machine"
ha-learner find "living room lamp"
ha-learner summary
ha-learner mcp                 # run the MCP server (stdio)
```

The knowledge base is written to `~/.ha-ai-learner/` by default:

| File | Contents |
|---|---|
| `knowledge.md` | The whole home as readable Markdown — areas, entities, devices, services, integrations, HACS, patterns |
| `knowledge.json` | Same, machine-readable |
| `answers.json` | Your answers from the interview flow (permanent) |
| `questions.json` | Currently pending clarifying questions |
| `patterns.json` | Learned usage patterns |
| `changes.log` | Timestamped diff log of every scan |

### Scheduled scanning

- On a Linux/HA box: `ha-learner watch` (as a systemd service or under tmux), or cron:
  `0 * * * * ha-learner scan --patterns`
- An AI client can also refresh on demand via the `rescan` MCP tool.

## Connecting to Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config) — see [`examples/claude_desktop_config.example.json`](examples/claude_desktop_config.example.json):

```json
{
  "mcpServers": {
    "ha-ai-learner": {
      "command": "ha-learner",
      "args": ["mcp"],
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "YOUR_TOKEN"
      }
    }
  }
}
```

For Claude Code: `claude mcp add ha-ai-learner -- ha-learner mcp`

**MCP tools exposed:** `home_summary`, `search_entities`, `get_entity`, `list_areas`, `list_services`, `get_service`, `usage_patterns`, `pending_questions`, `answer_question`, `rescan`, `recent_changes`, `get_live_state`, `call_service`.

### The "identify by asking" loop

This is the feature the project is named after. The learner flags entities it cannot confidently identify — no area, auto-generated name, duplicate names. Your AI assistant calls `pending_questions`, asks you in plain language ("Which room is `switch.sonoff_3` in?"), and stores your reply with `answer_question`. From then on the knowledge base knows — permanently, across rescans.

## Security

- **Read-only by default.** The `call_service` tool (device control) refuses to run unless you set `allow_service_calls: true` in the config (or `HA_LEARNER_ALLOW_CALLS=1`).
- Your token lives in your local config file — never commit it. `config.yaml` is in `.gitignore`.
- The MCP server runs over stdio on your machine; nothing is exposed to the network beyond the calls to your own HA instance.

## Testing

A full end-to-end test runs against a bundled mock HA server — no live Home Assistant needed:

```bash
python3 tests/test_e2e.py
```

It covers scanning, knowledge base generation, change detection, the interview flow, search, and pattern learning. The mock data intentionally uses accented Hungarian entity names to keep everything Unicode-safe.

## How it works, briefly

- `scanner.py` pulls states/services/config over REST and the entity/device/area/floor/label registries + config entries + HACS repositories over WebSocket, and normalizes them into one snapshot.
- `miniws.py` is a minimal, dependency-free RFC 6455 WebSocket client — no extra WS library needed.
- `knowledge.py` persists snapshots, computes human-readable diffs, merges in your answers and learned patterns, and renders the Markdown/JSON knowledge base.
- `interview.py` scores entities for "unclarity" (regexes for generated names, area/duplicate checks) and manages the question/answer lifecycle.
- `patterns.py` mines history for per-entity activity histograms and 5-minute co-activation pairs → candidate routines.
- `mcp_server.py` exposes it all as MCP tools via FastMCP.

## Roadmap

- Entity-graph export (which automations touch which entities)
- Optional local vector index for semantic search
- HACS packaging for one-click install
- Logbook-based pattern mining (in addition to history)

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © Tamás Pénzes
