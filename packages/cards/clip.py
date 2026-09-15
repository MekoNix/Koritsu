"""clip.py — одна карточка текстом Markdown для кнопки «Скопировать».

    Что такое первообразная?

    ---

    Функция $F$, для которой $F' = f$.

    > Частая ошибка — забыть константу.

Вопрос, черта, ответ, разбор цитатой. Это не формат файла набора (файл — JSON), а текст,
который удобно вставить в заметки или чат: без id и без подписей на языке интерфейса.
"""
from __future__ import annotations

from .model import Card


def card_markdown(c: Card) -> str:
    """Карточка → Markdown: вопрос, `---`, ответ и разбор цитатой."""
    parts = [c.q.strip("\n"), "---", c.a.strip("\n")]
    if c.note and c.note.strip():
        parts.append("\n".join(f"> {ln}" if ln.strip() else ">"
                               for ln in c.note.strip("\n").split("\n")))
    return "\n\n".join(parts) + "\n"


__all__ = ["card_markdown"]
