"""Сборка контекста: опись всегда, куски по требованию, честная оценка стоимости."""
import pytest

from materials import MaterialsError, Request, build_context, estimate_tokens
from materials.context import CHARS_PER_TOKEN_DEFAULT


def test_default_context_is_only_the_inventory(store, tmp_path):
    """По умолчанию модель получает карточки, а не простыню целиком."""
    p = tmp_path / "большой.txt"
    p.write_text("\n".join(f"строка {i}" for i in range(5000)), encoding="utf-8")
    store.add(str(p))
    ctx = build_context(store)
    assert ctx.chunks == [] and ctx.text == ctx.inventory
    assert "строка 4999" not in ctx.text
    assert ctx.tokens < 100


def test_requested_chunks_come_with_anchors(store, tmp_path, pdf):
    p = tmp_path / "конспект.md"
    p.write_text("\n".join(f"строка {i}" for i in range(1, 101)), encoding="utf-8")
    text_id = store.add(str(p)).id
    pdf_id = store.add(pdf, name="методичка.pdf").id

    ctx = build_context(store, [(text_id, 40, 42), Request(pdf_id, 2, 2)])
    assert [c.anchor for c in ctx.chunks] == ["«конспект.md», строки 40–42",
                                              "«методичка.pdf», страница 2"]
    assert "--- «конспект.md», строки 40–42 ---\nстрока 40" in ctx.text
    assert "Hod raboty" in ctx.text
    assert ctx.text.startswith(ctx.inventory)      # опись всегда впереди


def test_request_forms(store, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("раз\nдва\nтри\n", encoding="utf-8")
    mid = store.add(str(p)).id
    whole = build_context(store, [mid]).chunks[0]
    assert whole.text == "раз\nдва\nтри" and whole.anchor == "«a.txt», строки 1–3"
    assert build_context(store, [{"id": mid, "start": 2}]).chunks[0].text == "два\nтри"
    with pytest.raises(MaterialsError):
        build_context(store, [42])


def test_оценка_по_умолчанию_грубая_и_сверху():
    """Умолчание — грубая прикидка, а не истина: округление вверх намеренное,
    потому что оценка сверху на границе контекста отказывает зря, а оценка
    снизу даёт начать и оборваться."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("а" * 350) == 100
    assert estimate_tokens("а" * 351) == 101       # округление вверх, оценка сверху
    assert CHARS_PER_TOKEN_DEFAULT == 3.5


def test_коэффициент_задаётся_снаружи():
    """Коэффициент — свойство endpoint'а, а не этого пакета. Кто собирается
    считать конкретным endpoint'ом, передаёт его коэффициент; цена ошибки —
    решение «влезет» по одной линейке при лимите по другой."""
    assert estimate_tokens("а" * 300, 3.0) == 100
    assert estimate_tokens("а" * 300, 2.0) == 150      # кириллица дороже
    assert estimate_tokens("а" * 300, 3.0) > estimate_tokens("а" * 300, 4.0)


def test_негодный_коэффициент_не_роняет_оценку():
    """Ноль пришёл бы делением на ноль посреди сборки контекста, минус — токенами
    со знаком минус в бюджете. Обе линейки ломаются об одну и ту же границу."""
    assert estimate_tokens("а" * 10, 0) == 20
    assert estimate_tokens("а" * 10, -3) == 20


def test_контекст_считается_переданным_коэффициентом(store, tmp_path):
    """Оценка контекста обязана считаться той же линейкой, что и лимит, а по
    самой цифре потом не отличить, чем её мерили, — поэтому коэффициент лежит
    в Context рядом с числом."""
    p = tmp_path / "конспект.md"
    p.write_text("\n".join(f"строка {i}" for i in range(1, 51)), encoding="utf-8")
    store.add(str(p))

    грубо = build_context(store)
    точнее = build_context(store, chars_per_token=2.0)
    assert грубо.chars_per_token == CHARS_PER_TOKEN_DEFAULT
    assert точнее.chars_per_token == 2.0
    assert точнее.tokens > грубо.tokens
    assert грубо.tokens == estimate_tokens(грубо.text, CHARS_PER_TOKEN_DEFAULT)
    assert точнее.tokens == estimate_tokens(точнее.text, 2.0)


def test_линейка_сходится_со_слоем_llm():
    """Шов между пакетами: `Context.tokens` и `llm.estimate` мерят одно и то же.

    Пакеты не связаны ни одним импортом — здесь их сводит ТЕСТ, и только на
    одинаковом коэффициенте endpoint'а. Расхождение допускается на один токен
    (у нас округление вверх, у слоя — к ближайшему); всё, что больше, значит,
    что кто-то опять завёл свою константу.
    """
    llm = pytest.importorskip("llm")
    текст = "Отчёт по лабораторной работе. " * 100
    for cpt in (llm.presets.deepseek().chars_per_token,
                llm.presets.anthropic().chars_per_token,
                llm.presets.openrouter().chars_per_token):
        наш = estimate_tokens(текст, cpt)
        их = llm.usage.estimate_tokens(текст, cpt)
        assert abs(наш - их) <= 1, f"коэффициент {cpt}: {наш} против {их}"


def test_context_of_empty_project(store):
    ctx = build_context(store)
    assert "0 материалов" in ctx.inventory and ctx.tokens > 0
