# Changelog

## 0.1.0 — 2026-07-20

First public release.

- Full Home Assistant discovery over REST + WebSocket: entities, devices,
  areas/floors, labels, services, integrations, HACS add-ons
- Knowledge base generation (Markdown + JSON) with persistent storage
- Change detection between scans with a timestamped `changes.log`
- Interview flow: clarifying questions for unclear entities, answers merge
  into the knowledge base permanently
- Usage-pattern learning from history (active hours, typical on-times,
  co-activation routine candidates)
- MCP server with 13 tools for Claude Desktop / Claude Code / any MCP client
- Read-only by default; device control requires an explicit opt-in
- Dependency-free minimal WebSocket client (RFC 6455)
- End-to-end test suite against a bundled mock HA server
