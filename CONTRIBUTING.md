# Contributing

Thanks for your interest! This is a small project — the process is simple.

## Getting started

```bash
git clone https://github.com/buppy333/ha-ai-learner.git
cd ha-ai-learner
pip install -e .
python3 tests/test_e2e.py   # must print: ALL TESTS PASSED
```

## Guidelines

- Keep dependencies minimal (currently: httpx, PyYAML, mcp — that's it).
- The e2e test must pass; if you add a feature, extend `tests/mock_ha.py`
  and `tests/test_e2e.py` to cover it.
- User-facing strings and docs are English; the knowledge base itself is
  language-agnostic (and must stay Unicode-safe — the mock data's accented
  entity names are there on purpose).
- Safety first: anything that *controls* the home must stay behind the
  `allow_service_calls` opt-in.

## Good first issues

- More "unclear entity" heuristics (see `interview.py`)
- Additional MCP tools (automations, scenes, logbook)
- HACS packaging
