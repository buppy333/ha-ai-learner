"""Configuration loading for HA-AI Learner.

Order of precedence: environment variables > config.yaml > defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATHS = [
    Path("config.yaml"),
    Path.home() / ".config" / "ha-ai-learner" / "config.yaml",
]


@dataclass
class Config:
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""
    data_dir: Path = field(default_factory=lambda: Path.home() / ".ha-ai-learner")
    scan_interval_minutes: int = 60
    history_days: int = 7
    # Entities whose entity_id matches any of these prefixes are ignored.
    ignore_prefixes: tuple = ("persistent_notification.", "update.")
    # Allow the MCP server to call services (turn things on/off). Default: read-only.
    allow_service_calls: bool = False

    @property
    def kb_json(self) -> Path:
        return self.data_dir / "knowledge.json"

    @property
    def kb_markdown(self) -> Path:
        return self.data_dir / "knowledge.md"

    @property
    def answers_file(self) -> Path:
        return self.data_dir / "answers.json"

    @property
    def questions_file(self) -> Path:
        return self.data_dir / "questions.json"

    @property
    def patterns_file(self) -> Path:
        return self.data_dir / "patterns.json"

    @property
    def changes_log(self) -> Path:
        return self.data_dir / "changes.log"

    @property
    def snapshot_file(self) -> Path:
        return self.data_dir / "last_snapshot.json"


def load_config(path: str | os.PathLike | None = None) -> Config:
    cfg = Config()

    candidates = [Path(path)] if path else DEFAULT_CONFIG_PATHS
    for p in candidates:
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            cfg.ha_url = raw.get("ha_url", cfg.ha_url)
            cfg.ha_token = raw.get("ha_token", cfg.ha_token)
            if "data_dir" in raw:
                cfg.data_dir = Path(raw["data_dir"]).expanduser()
            cfg.scan_interval_minutes = int(raw.get("scan_interval_minutes", cfg.scan_interval_minutes))
            cfg.history_days = int(raw.get("history_days", cfg.history_days))
            if "ignore_prefixes" in raw:
                cfg.ignore_prefixes = tuple(raw["ignore_prefixes"])
            cfg.allow_service_calls = bool(raw.get("allow_service_calls", cfg.allow_service_calls))
            break

    # Environment overrides
    cfg.ha_url = os.environ.get("HA_URL", cfg.ha_url).rstrip("/")
    cfg.ha_token = os.environ.get("HA_TOKEN", cfg.ha_token)
    if os.environ.get("HA_LEARNER_DATA_DIR"):
        cfg.data_dir = Path(os.environ["HA_LEARNER_DATA_DIR"]).expanduser()
    if os.environ.get("HA_LEARNER_ALLOW_CALLS"):
        cfg.allow_service_calls = os.environ["HA_LEARNER_ALLOW_CALLS"].lower() in ("1", "true", "yes")

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
