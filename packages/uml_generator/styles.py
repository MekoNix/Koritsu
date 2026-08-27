"""
styles — палитра и геометрия из styles.yaml.

  get_theme(name)              → dict палитры
  get_layout(overrides=None)   → dict размеров (yaml + перегрузки)
"""
import os
from functools import lru_cache

import yaml

_PATH = os.path.join(os.path.dirname(__file__), "styles.yaml")


@lru_cache(maxsize=None)
def _load() -> dict:
    with open(_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_theme(name: str = "dark") -> dict:
    themes = _load()["themes"]
    if name not in themes:
        raise ValueError(f"Unknown theme: {name!r}. Available: {', '.join(themes)}")
    return themes[name]


def get_layout(overrides: dict | None = None) -> dict:
    cfg = dict(_load()["layout"])
    if overrides:
        unknown = set(overrides) - set(cfg)
        if unknown:
            raise ValueError(f"Unknown layout keys: {', '.join(sorted(unknown))}")
        cfg.update(overrides)
    return cfg
