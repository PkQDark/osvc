"""Загрузка config.yaml + telegram.key (см. BOT_DESIGN.md §6)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"
DEFAULT_TOKEN_PATH = BASE_DIR / "telegram.key"
DEFAULT_CSV_PATH = BASE_DIR / "payments.csv"
DEFAULT_DB_PATH = BASE_DIR / "state.db"


@dataclass
class Config:
    token: str
    timezone: str
    reminder_hours: list[int]
    payment_account: str
    csv_path: Path
    db_path: Path


def load_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    csv_path: str | Path = DEFAULT_CSV_PATH,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> Config:
    config_path = Path(config_path)
    token_path = Path(token_path)

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"{token_path} пуст — положи туда токен бота от @BotFather")

    # env TZ имеет приоритет над config.yaml (см. §4; systemd unit его тоже задаёт)
    timezone = os.environ.get("TZ") or raw["timezone"]

    return Config(
        token=token,
        timezone=timezone,
        reminder_hours=list(raw["reminder_hours"]),
        payment_account=raw["payment_account"],
        csv_path=Path(csv_path),
        db_path=Path(db_path),
    )
