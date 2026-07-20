"""Command-line interface for HA-AI Learner.

  ha-learner scan                  – one full discovery scan (+ diff + KB rebuild)
  ha-learner watch                 – scan periodically (scan_interval_minutes)
  ha-learner learn-patterns        – mine usage patterns from history
  ha-learner questions             – list pending clarifying questions
  ha-learner interview             – interactive Q&A in the terminal
  ha-learner answer <entity_id> …  – store one answer
  ha-learner find "<query>"        – search the knowledge base
  ha-learner summary               – knowledge base overview
  ha-learner mcp                   – run the MCP server (stdio)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from .config import load_config
from .knowledge import KnowledgeBase
from . import interview as iv

log = logging.getLogger("ha-learner")


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def _do_scan(cfg, kb: KnowledgeBase, with_patterns: bool = False) -> None:
    from .scanner import scan
    print(f"Scanning {cfg.ha_url} …", file=sys.stderr)
    snapshot = await scan(cfg)
    changes = kb.update_from_scan(snapshot)
    qs = iv.refresh_questions(cfg, kb)
    print(f"Done. {len(snapshot['entities'])} entities, {len(snapshot['devices'])} devices, "
          f"{len(snapshot['services'])} services.", file=sys.stderr)
    if changes:
        print("Changes:", file=sys.stderr)
        for c in changes:
            print(f"  {c}", file=sys.stderr)
    if qs:
        print(f"{len(qs)} clarifying question(s) pending — run: ha-learner interview",
              file=sys.stderr)
    if with_patterns:
        await _do_patterns(cfg, kb)
    print(f"Knowledge base: {cfg.kb_markdown}", file=sys.stderr)


async def _do_patterns(cfg, kb: KnowledgeBase) -> None:
    from .patterns import learn_patterns
    print("Learning usage patterns from history…", file=sys.stderr)
    pats = await learn_patterns(cfg, kb.snapshot)
    kb.set_patterns(pats)
    print(f"Patterns for {len(pats.get('entities', {}))} entities, "
          f"{len(pats.get('routines', []))} candidate routine(s).", file=sys.stderr)


def cmd_scan(args, cfg, kb):
    asyncio.run(_do_scan(cfg, kb, with_patterns=args.patterns))


def cmd_watch(args, cfg, kb):
    interval = (args.interval or cfg.scan_interval_minutes) * 60
    print(f"Watching every {interval // 60} minute(s). Ctrl+C to stop.", file=sys.stderr)
    while True:
        try:
            asyncio.run(_do_scan(cfg, kb, with_patterns=args.patterns))
        except Exception as exc:  # keep the loop alive
            print(f"Error during scan: {exc}", file=sys.stderr)
        time.sleep(interval)


def cmd_patterns(args, cfg, kb):
    if not kb.snapshot:
        print("Run a scan first: ha-learner scan", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_do_patterns(cfg, kb))


def cmd_questions(args, cfg, kb):
    _print(iv.pending_questions(cfg))


def cmd_interview(args, cfg, kb):
    qs = iv.pending_questions(cfg)
    if not qs:
        print("No pending questions. (Run a scan to refresh.)")
        return
    print(f"{len(qs)} entities need clarification. Enter = skip, 'q' = quit.\n")
    for q in qs:
        print(f"▶ {q['entity_id']}  ('{q['name']}', device: {q.get('device') or '?'}, "
              f"integration: {q.get('integration') or '?'}, state: {q.get('state')})")
        for reason in q["reasons"]:
            print(f"   reason: {reason}")
        loc = input("   Which room is it in? > ").strip()
        if loc.lower() == "q":
            break
        purpose = input("   What does it control / measure? > ").strip()
        if purpose.lower() == "q":
            break
        if loc or purpose:
            iv.answer(cfg, kb, q["entity_id"], location=loc or None, purpose=purpose or None)
            print("   ✔ saved\n")
        else:
            print("   skipped\n")


def cmd_answer(args, cfg, kb):
    result = iv.answer(cfg, kb, args.entity_id,
                       location=args.location, purpose=args.purpose, note=args.note)
    _print({args.entity_id: result})


def cmd_find(args, cfg, kb):
    _print(kb.search(args.query, limit=args.limit))


def cmd_summary(args, cfg, kb):
    _print(kb.summary())


def cmd_mcp(args, cfg, kb):
    from .mcp_server import main as mcp_main
    mcp_main()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="ha-learner", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to config.yaml", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="one full discovery scan")
    s.add_argument("--patterns", action="store_true", help="also learn usage patterns from history")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("watch", help="periodic scanning")
    s.add_argument("--interval", type=int, help="minutes (overrides config)")
    s.add_argument("--patterns", action="store_true")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("learn-patterns", help="learn usage patterns from history")
    s.set_defaults(func=cmd_patterns)

    s = sub.add_parser("questions", help="list pending questions")
    s.set_defaults(func=cmd_questions)

    s = sub.add_parser("interview", help="interactive Q&A in the terminal")
    s.set_defaults(func=cmd_interview)

    s = sub.add_parser("answer", help="store one answer")
    s.add_argument("entity_id")
    s.add_argument("--location")
    s.add_argument("--purpose")
    s.add_argument("--note")
    s.set_defaults(func=cmd_answer)

    s = sub.add_parser("find", help="search the knowledge base")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_find)

    s = sub.add_parser("summary", help="knowledge base overview")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("mcp", help="run the MCP server (stdio)")
    s.set_defaults(func=cmd_mcp)

    args = p.parse_args()
    cfg = load_config(args.config)
    kb = KnowledgeBase(cfg)
    args.func(args, cfg, kb)


if __name__ == "__main__":
    main()
