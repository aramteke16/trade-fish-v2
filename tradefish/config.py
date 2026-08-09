"""Config resolution: settings DB overrides env, env overrides settings.yaml."""

import os
from functools import lru_cache

import yaml
from dotenv import load_dotenv

from tradefish import db
from tradefish.db import ROOT

load_dotenv(ROOT / ".env")


@lru_cache
def yaml_settings() -> dict:
    with open(ROOT / "config" / "settings.yaml") as f:
        return yaml.safe_load(f)


def get(key: str, default: str | None = None) -> str | None:
    """Runtime value by env-style key, e.g. get("DEEPSEEK_API_KEY")."""
    value = db.get_setting(key)
    if value is not None:
        return value
    return os.environ.get(key, default)


def strategy(key: str):
    """Strategy parameter from yaml, DB-overridable, e.g. strategy("top_k")."""
    value = db.get_setting(f"strategy.{key}")
    if value is not None:
        return type(yaml_settings()["strategy"][key])(value)
    return yaml_settings()["strategy"][key]


def universe() -> list[str]:
    with open(ROOT / "config" / "universe.txt") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def costs() -> dict:
    return yaml_settings()["costs"]


def scheduler_config() -> dict:
    return yaml_settings()["scheduler"]
