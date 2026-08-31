"""
Разбор потока уровня 2 по закрытым значениям.

Цена ошибки здесь считается прямо: неверно посчитанная скобка сдвигает границу
значения, дальше ломается разбор всего остатка потока, и отчёт молча теряет
теги — не один, а все после сбоя. Поэтому проверяются не «типичные» ответы, а
рваные: разрыв посреди ключа, посреди экранированной кавычки, скобки внутри
человеческого текста, значение не той формы.
"""
from __future__ import annotations

import json

from orchestrator.stream import TagStream


def _по_буквам(text: str) -> list:
    """Самый злой разрыв из возможных: по одному символу в куске."""
    stream = TagStream()
    out = []
    for ch in text:
        out.extend(stream.feed(ch))
    return out


def test_тег_отдаётся_в_момент_закрытия_своего_значения():
    stream = TagStream()
    assert stream.feed('{"цель": {"type": "markdown", "text": "раз"}') == [
        ("цель", {"type": "markdown", "text": "раз"})]
    # Второй тег ещё не закрылся — отдавать нечего.
    assert stream.feed(', "введение": {"type": "markdown",') == []
    assert stream.feed(' "text": "два"}}') == [
        ("введение", {"type": "markdown", "text": "два"})]


def test_разрыв_куска_где_угодно_ничего_не_теряет():
    text = json.dumps({"цель": {"type": "markdown", "text": "а"},
                       "введение": {"type": "markdown", "text": "б"}},
                      ensure_ascii=False)
    assert [k for k, _ in _по_буквам(text)] == ["цель", "введение"]


def test_скобки_и_кавычки_внутри_текста_не_сбивают_границу():
    """Значения тегов — сплошь человеческий текст, в котором бывает всё."""
    внутри = 'формула {x} и «кавычки», а ещё \\"экран\\" и }'
    text = ('{"цель": {"type": "markdown", "text": "' + внутри + '"},'
            ' "введение": {"type": "text", "text": "после"}}')
    pairs = _по_буквам(text)
    assert [k for k, _ in pairs] == ["цель", "введение"]
    assert pairs[0][1]["text"].endswith("}")
    assert pairs[1][1]["text"] == "после"


def test_забор_и_пояснения_модели_не_мешают():
    text = ('Вот "результат" работы:\n```json\n'
            '{"цель": {"type": "text", "text": "готово"}}\n```')
    assert _по_буквам(text) == [("цель", {"type": "text", "text": "готово"})]


def test_значение_не_объект_пропускается_а_следующий_ключ_не_съезжает():
    """`null` вместо значения — законная ошибка модели. Проглоти его как попало,
    и следующий ключ прочитается как часть этого значения: пары разъедутся до
    конца потока, то есть отчёт потеряет всё после первой такой ошибки."""
    text = ('{"цель": null, "введение": {"type": "text", "text": "цело"}}')
    stream = TagStream()
    pairs = []
    for ch in text:
        pairs.extend(stream.feed(ch))
    assert pairs == [("введение", {"type": "text", "text": "цело"})]
    assert stream.close()["skipped"] == [("цель", "null")]


def test_битое_значение_видно_а_не_теряется():
    text = '{"цель": {"type": "markdown", "text": }, "введение": {"type": "text", "text": "ц"}}'
    stream = TagStream()
    pairs = []
    for ch in text:
        pairs.extend(stream.feed(ch))
    assert [k for k, _ in pairs] == ["введение"]
    broken = stream.close()["broken"]
    assert broken and broken[0][0] == "цель"


def test_обрыв_на_середине_называет_тег_и_остаток():
    stream = TagStream()
    stream.feed('{"цель": {"type": "markdown", "text": "начал писать')
    tail = stream.close()
    assert stream.truncated is True
    assert tail["key"] == "цель"
    assert "начал писать" in tail["text"]


def test_хвостовая_проза_не_становится_тегом_обрыва():
    """Строка, за которой не оказалось двоеточия, ключом не была. Оставь её в
    накопителе — и `close()` назовёт «на чём оборвались» тег, которого модель не
    писала: прогон, дошедший до конца, получил бы жалобу на выдуманный тег."""
    stream = TagStream()
    stream.feed('{"цель": {"type": "text", "text": "к"}} Итог: "готово" — всё.')
    tail = stream.close()
    assert stream.truncated is False
    assert tail["key"] == ""


def test_экранированный_ключ_разбирается_как_json():
    stream = TagStream()
    pairs = stream.feed('{"\\u0446\\u0435\\u043b\\u044c": {"type": "text", "text": "к"}}')
    assert pairs == [("цель", {"type": "text", "text": "к"})]
