"""
_drawpyo.py — импорт drawpyo, не перехватывающий корневой логгер.

drawpyo при импорте зовёт `logging.basicConfig(level=INFO)` (см.
drawpyo/utils/logger.py), после чего любая программа, подключившая
fragmos, начинает сыпать в stderr INFO-строками — и своими, и чужими.
Снимаем состояние корневого логгера до импорта и возвращаем обратно,
а сам логгер drawpyo приглушаем до WARNING: захочет хост-программа
видеть его сообщения — включит явно.

Весь пакет импортирует drawpyo ТОЛЬКО отсюда:
    from ._drawpyo import drawpyo
"""

import logging

_root = logging.getLogger()
_handlers = list(_root.handlers)
_level = _root.level

import drawpyo  # noqa: E402  — basicConfig срабатывает здесь

_root.handlers[:] = _handlers
_root.setLevel(_level)
logging.getLogger('drawpyo').setLevel(logging.WARNING)

__all__ = ['drawpyo']
