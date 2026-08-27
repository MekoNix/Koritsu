"""styles — настройки оформления из styles.yaml с перегрузкой (глубокое слияние)."""
from __future__ import annotations

import copy
import os
from functools import lru_cache

import yaml

_PATH = os.path.join(os.path.dirname(__file__), "styles.yaml")


@lru_cache(maxsize=None)
def _load() -> dict:
    with open(_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_style(overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(_load())
    for section, vals in (overrides or {}).items():
        if section not in cfg:
            raise ValueError(f"Unknown style section: {section!r}")
        if isinstance(vals, dict):
            cfg[section].update(vals)
        else:
            cfg[section] = vals
    return cfg
