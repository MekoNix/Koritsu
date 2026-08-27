"""
modes — режимы отображения (modes.yaml) и текстовые стили (styles.yaml).

  get_mode(mode_id)   → dict режима: {'style', 'blocks', 'description'}
  get_style(name)     → TextStyle
  list_modes()        → [mode_id, ...]
"""

import os
import yaml

from .text_style import TextStyle, build_styles

_DIR = os.path.dirname(__file__)
_MODES_PATH = os.path.join(_DIR, 'modes.yaml')
_STYLES_PATH = os.path.join(_DIR, 'styles.yaml')

_modes: dict | None = None
_styles: dict | None = None


def _load_yaml(path: str, key: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)[key]


def get_style(name: str) -> TextStyle:
    """Скомпилированный TextStyle по имени из styles.yaml."""
    global _styles
    if _styles is None:
        _styles = build_styles(_load_yaml(_STYLES_PATH, 'styles'))
    style = _styles.get(name)
    if style is None:
        raise ValueError(f"Unknown style: {name!r}. Available: {', '.join(_styles)}")
    return style


def get_mode(mode_id: str) -> dict:
    """Режим из modes.yaml.

    Raises:
        ValueError: если mode_id не определён.
    """
    global _modes
    if _modes is None:
        _modes = _load_yaml(_MODES_PATH, 'modes')
    mode = _modes.get(mode_id)
    if mode is None:
        raise ValueError(f"Unknown mode: {mode_id!r}. Available: {', '.join(_modes)}")
    return mode


def list_modes() -> list:
    get_mode('default')
    return list(_modes)
