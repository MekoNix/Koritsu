"""
context — сборка того, что уходит в языковую модель.

Правило простое: по умолчанию модель получает только опись материалов
(карточки). Полный текст она запрашивает сама и кусками — так один PDF на
триста страниц не съедает весь бюджет разговора.

Каждый кусок приходит под якорем («методичка.pdf», страница 4), чтобы модель
могла сослаться на источник в отчёте, а человек — проверить.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Chunk, MaterialsError

# Символов на токен — ГРУБОЕ умолчание, а не истина. Настоящий коэффициент есть
# свойство конкретного endpoint'а (у слоя llm он лежит в описании endpoint'а и
# бывает то 3.0, то 3.5), а этот пакет про endpoint'ы не знает и знать не
# должен: ни одного импорта между пакетами нет. Поэтому коэффициент принимается
# снаружи, а здесь лежит только запасное значение — ровно то же 3.5, что стоит
# умолчанием у слоя llm, чтобы посчитанное без endpoint'а хотя бы не спорило с
# тем, что тот же текст получит от llm.estimate.
#
# Цена ошибки, если держать здесь своё число (было 4): «влезет в контекст»
# решается по одной линейке, а лимит и деньги считаются по другой — расхождение
# в 15 % там, где обе цифры называются одним словом «токены».
CHARS_PER_TOKEN_DEFAULT = 3.5


def estimate_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN_DEFAULT) -> int:
    """Оценка в токенах: длина в символах, делённая на коэффициент. Именно оценка.

    `chars_per_token` — коэффициент того endpoint'а, которым собираются считать
    (у слоя llm он лежит в описании endpoint'а). Без него берётся грубое
    умолчание, и цифра годится только на «влезет / не влезет».

    Округление вверх намеренное: это оценка СВЕРХУ. Слой llm на том же тексте
    округляет к ближайшему, так что две цифры расходятся не больше чем на
    токен — на решение «влезет» это не влияет, а разные коэффициенты влияли бы.
    """
    return math.ceil(len(text) / _годный(chars_per_token))


def _годный(chars_per_token: float) -> float:
    """Коэффициент, которым можно делить: ноль и минус дали бы не оценку, а
    деление на ноль и токены со знаком минус. Нижняя граница та же, что у
    llm.usage.estimate_tokens, — чтобы обе линейки ломались одинаково."""
    return max(0.5, float(chars_per_token))


@dataclass
class Request:
    """Запрос куска: идентификатор материала и границы (строки или страницы)."""
    id: str
    start: int | None = None
    end: int | None = None


@dataclass
class Context:
    """Готовый контекст: опись, запрошенные куски и оценка стоимости.

    `chars_per_token` хранится рядом с `tokens` не для красоты: без него по
    одному числу не отличить оценку по коэффициенту endpoint'а от оценки по
    грубому умолчанию, а на границе контекста это разные по силе утверждения.
    """
    inventory: str
    chunks: list[Chunk] = field(default_factory=list)
    text: str = ""
    tokens: int = 0
    chars_per_token: float = CHARS_PER_TOKEN_DEFAULT


def _as_request(item) -> Request:
    """Запрос можно писать как Request, кортеж ('id', 40, 80), dict или просто id."""
    if isinstance(item, Request):
        return item
    if isinstance(item, str):
        return Request(id=item)
    if isinstance(item, dict):
        return Request(id=item["id"], start=item.get("start"), end=item.get("end"))
    if isinstance(item, (tuple, list)) and item:
        return Request(id=item[0],
                       start=item[1] if len(item) > 1 else None,
                       end=item[2] if len(item) > 2 else None)
    raise MaterialsError(f"непонятный запрос куска: {item!r}")


def build_context(store, requests=(),
                  chars_per_token: float = CHARS_PER_TOKEN_DEFAULT) -> Context:
    """
    Собрать контекст по проекту: опись всегда, запрошенные куски — по требованию.
    `requests` — список идентификаторов или запросов с границами.
    `chars_per_token` — коэффициент оценки того endpoint'а, которым собираются
    считать; без него — грубое умолчание (см. CHARS_PER_TOKEN_DEFAULT).
    """
    inv = store.inventory()
    chunks = [store.read(r.id, r.start, r.end) for r in map(_as_request, requests)]

    parts = [inv]
    if chunks:
        parts.append("Запрошенное содержимое:")
        for c in chunks:
            # Якорь идёт заголовком куска: модель цитирует его как есть.
            parts.append(f"--- {c.anchor} ---\n{c.text}")
    text = "\n\n".join(parts)
    # В Context кладётся тот же коэффициент, которым посчитаны токены, а не тот,
    # который передали: иначе поле объясняло бы цифру неверно.
    cpt = _годный(chars_per_token)
    return Context(inventory=inv, chunks=chunks, text=text,
                   tokens=estimate_tokens(text, cpt), chars_per_token=cpt)
