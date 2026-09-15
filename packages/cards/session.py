"""session.py — порядок карточек захода и сравнение двух версий набора.

**Заход** — список ключей. Сначала фильтры, потом порядок, потом размер:

1. `topics` — id тем; `None` в списке — карточки без темы; `topics=None` — все.
2. `include` по последним ответам человека: `all` — все, `unknown` — последний ответ не
   «Да» (или ответа не было), `wrong` — последний ответ «Нет».
3. `order`:
   - `file` — как в файле;
   - `random` — всё перемешано;
   - `topic_seq` — группы тем подряд, внутри как в файле;
   - `topic_random` — группы тем подряд, внутри перемешано;
   - `topics_shuffled` — группы тем в случайном порядке, внутри как в файле.
   Группы идут так: карточки без темы, затем темы в порядке набора.
4. `size` — сколько взять; `None` или `<= 0` — все.

**Размер режет по-разному.** Порядки «подряд» (`file`, `topic_seq`, `topics_shuffled`)
берут первые `size` карточек получившегося порядка: это и есть «по файлу». У `topic_random`
сначала выбираются `size` случайных карточек из всех отобранных, и уже они раскладываются по
темам: иначе заход на 20 карточек из набора в 200 всегда был бы одной первой темой.

Перемешивание стабильно: всё случайное идёт из одного `random.Random(seed)` в
фиксированной последовательности, и те же входы дают тот же заход. Повтор «Нет» внутри
захода — дело проигрывателя, а не плана.
"""
from __future__ import annotations

import random

from .model import INCLUDE, ORDERS, Card, CardSet, same_text


def _groups(s: CardSet, cards: list[Card]) -> list[list[Card]]:
    order: list[str | None] = [None] + [t.id for t in s.topics]
    by: dict[str | None, list[Card]] = {}
    for c in cards:
        if c.topic not in by and c.topic not in order:
            order.append(c.topic)
        by.setdefault(c.topic, []).append(c)
    return [by[k] for k in order if k in by]


def plan_session(s: CardSet, last: dict[str, bool | None], *, size: int | None, order: str,
                 topics: list[str] | None, include: str, seed: int) -> list[str]:
    """Набор, последние ответы по ключам и настройки захода → ключи карточек по порядку."""
    if order not in ORDERS:
        raise ValueError(f"неизвестный порядок {order!r}, допустимы: {', '.join(ORDERS)}")
    if include not in INCLUDE:
        raise ValueError(f"неизвестный include {include!r}, допустимы: {', '.join(INCLUDE)}")
    rng = random.Random(seed)
    last = last or {}

    cards = list(s.cards)
    if topics is not None:
        allowed = set(topics)
        cards = [c for c in cards if c.topic in allowed]
    if include == "unknown":
        cards = [c for c in cards if last.get(c.key) is not True]
    elif include == "wrong":
        cards = [c for c in cards if last.get(c.key) is False]
    limit = size if size is not None and size > 0 else None

    if order == "file":
        out = cards
    elif order == "random":
        out = cards[:]
        rng.shuffle(out)
    elif order == "topic_seq":
        out = [c for g in _groups(s, cards) for c in g]
    elif order == "topic_random":
        if limit is not None and limit < len(cards):
            chosen = set(rng.sample(range(len(cards)), limit))
            cards = [c for i, c in enumerate(cards) if i in chosen]
        groups = _groups(s, cards)
        for g in groups:
            rng.shuffle(g)
        out = [c for g in groups for c in g]
    else:  # topics_shuffled
        groups = _groups(s, cards)
        rng.shuffle(groups)
        out = [c for g in groups for c in g]

    if limit is not None:
        out = out[:limit]
    return [c.key for c in out]


def diff(old: CardSet, new: CardSet) -> dict:
    """Две версии набора → `{added, changed, removed}` — списки ключей.

    `changed` — ключ тот же, а текст вопроса или ответа другой (с точностью до NFC и
    пробелов). Разбор и тема на «изменилась» не влияют: прогресс привязан к вопросу и ответу.
    `added` и `changed` — в порядке новой версии, `removed` — старой.
    """
    old_by = {c.key: c for c in old.cards}
    new_keys = {c.key for c in new.cards}
    added = [c.key for c in new.cards if c.key not in old_by]
    changed = [c.key for c in new.cards if c.key in old_by
               and not (same_text(c.q, old_by[c.key].q) and same_text(c.a, old_by[c.key].a))]
    removed = [c.key for c in old.cards if c.key not in new_keys]
    return {"added": added, "changed": changed, "removed": removed}


__all__ = ["plan_session", "diff"]
