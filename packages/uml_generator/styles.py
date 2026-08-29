"""
styles — палитра и геометрия из styles.yaml.

  get_theme(name)              → dict палитры
  get_layout(overrides=None)   → dict размеров (yaml + перегрузки)

Тема `css` не хранится в yaml, а собирается из `light` и таблицы `roles`:
каждый цвет превращается в `var(--роль, светлый-hex)`. Одна такая схема годится
и в интерфейс, и в отчёт — подробности в шапке styles.yaml.
"""
import os
from functools import lru_cache

import yaml

_PATH = os.path.join(os.path.dirname(__file__), "styles.yaml")


@lru_cache(maxsize=None)
def _load() -> dict:
    with open(_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


CSS_THEME = "css"


@lru_cache(maxsize=None)
def _css_theme() -> dict:
    """Палитра ролями: `var(--роль, светлый-hex)`. Запасной цвет обязателен —
    без него draw.io рисует чёрным там, где CSS-переменных нет (PNG, редактор)."""
    data = _load()
    light, roles = data["themes"]["light"], data["roles"]
    out: dict = {}
    for key, role in roles.items():
        value = light[key]
        out[key] = ({k: f"var(--{role[k]},{value[k]})" for k in value}
                    if isinstance(role, dict) else f"var(--{role},{value})")
    return out


def get_theme(name: str = "dark") -> dict:
    themes = _load()["themes"]
    if name == CSS_THEME:
        return _css_theme()
    if name not in themes:
        raise ValueError(
            f"Unknown theme: {name!r}. Available: {', '.join([*themes, CSS_THEME])}")
    return themes[name]


def get_layout(overrides: dict | None = None) -> dict:
    cfg = dict(_load()["layout"])
    if overrides:
        unknown = set(overrides) - set(cfg)
        if unknown:
            raise ValueError(f"Unknown layout keys: {', '.join(sorted(unknown))}")
        cfg.update(overrides)
    return cfg
