"""
Отбор тегов и схемы для модели.

Цена ошибки в отборе конкретная: схема из всего манифеста попросила бы модель
заполнить теги, которых нет в шаблоне и которые заполняет человек, а `required`
в такой схеме соврал бы — модель обязана вернуть то, чего у неё никто не просил,
и вернёт выдумку за настоящие токены.
"""
from __future__ import annotations

import pytest

import hokoku
import llm
import orchestrator
from orchestrator.errors import OrchestratorError


def test_отбираются_только_теги_модели(project):
    m = project.manifest()
    m.tags["введение"].source_hint = "manual"      # это пишет человек
    m.tags["таблица"].missing = True               # тега больше нет в шаблоне
    project.save_manifest(m)
    assert orchestrator.fillable(project.manifest()) == ["цель"]


def test_порядок_тегов_это_порядок_документа(project):
    """Он важен не для валидности, а для потока: первые закрывшиеся значения —
    начало документа, и частичный результат при обрыве осмыслен."""
    assert orchestrator.fillable(project.manifest()) == ["цель", "введение", "таблица"]
    схема = orchestrator.report_schema(project.manifest(),
                                       keys=orchestrator.fillable(project.manifest()))
    assert list(схема["properties"]) == ["цель", "введение", "таблица"]
    assert схема["additionalProperties"] is False


def test_схемы_годятся_слою_моделей(project):
    """Схема, которую слой не примет, обнаружилась бы первым живым вызовом."""
    m = project.manifest()
    llm.jsonschema.check_schema(orchestrator.report_schema(
        m, keys=orchestrator.fillable(m)))
    for key, spec in m.tags.items():
        llm.jsonschema.check_schema(orchestrator.tag_schema(spec))


def test_неизвестный_ключ_отказ_с_подсказкой(project):
    with pytest.raises(OrchestratorError) as exc:
        orchestrator.fillable(project.manifest(), keys=["цел"])
    assert "похоже на" in str(exc.value) and "цель" in str(exc.value)


def test_просить_нечего_это_отказ_а_не_пустой_вызов(project):
    m = project.manifest()
    for spec in m.tags.values():
        spec.source_hint = "manual"
    project.save_manifest(m)
    with pytest.raises(OrchestratorError):
        orchestrator.fill_report(project, endpoint="ep_test")


# ── сторож: схема для валидатора против схемы для поставщика ──────────────────

def _all_schemas() -> dict:
    """Все схемы, которые уезжают к поставщику, — по одной на каждый способ спросить.

    Собраны в одном месте нарочно: пара «годна валидатору / годна поставщику»
    разъезжается не на схеме целиком, а на одном поле одного типа, и заметить это
    можно только прогнав их все разом.
    """
    m = hokoku.Manifest(tags={f"тег_{t}": hokoku.TagSpec(type=t)
                              for t in hokoku.MANIFEST_TYPES})
    out = {f"tag_schema({t})": orchestrator.tag_schema(hokoku.TagSpec(type=t))
           for t in hokoku.MANIFEST_TYPES}                       # уровень 1
    out["any_value_schema()"] = orchestrator.any_value_schema()  # уровень 3
    out["report_schema(все типы)"] = orchestrator.report_schema(m, keys=list(m.tags))
    return out


def _typeless(schema: dict, where: str = "корень") -> list:
    """Подсхемы без объявленного типа. `enum` без `type` наш валидатор понимает, а
    строгий режим поставщика отвечает на такое поле 400 — и узнали бы мы об этом
    живым вызовом, а не тестом."""
    bad = []
    if not any(k in schema for k in ("type", "const", "anyOf")):
        bad.append(f"{where}: {sorted(schema)}")
    for i, branch in enumerate(schema.get("anyOf") or ()):
        bad += _typeless(branch, f"{where}.anyOf[{i}]")
    for name, sub in (schema.get("properties") or {}).items():
        bad += _typeless(sub, f"{where}.{name}")
    if isinstance(schema.get("items"), dict):
        bad += _typeless(schema["items"], f"{where}.items")
    return bad


def test_сторож_все_схемы_модели_годятся_поставщику():
    """Тот самый сторож, которого не было: каждая схема, уезжающая наружу, проходит
    `check_schema` и `strictify` — и до строгого режима, и после него.

    Живёт он здесь, а не в `tests/hokoku`, по правилу разреза: `hokoku` про `llm` не
    знает, а оркестратор — единственный, кому позволено видеть обоих.
    """
    for где, схема in _all_schemas().items():
        llm.jsonschema.check_schema(схема)
        строгая = llm.jsonschema.strictify(схема)
        llm.jsonschema.check_schema(строгая)
        # strictify зовут и на уже строгой схеме — второй проход обязан ничего не менять
        assert llm.jsonschema.strictify(строгая) == строгая, где
        assert _typeless(схема) == [], где
        assert _typeless(строгая) == [], где


def test_сторож_выравнивание_с_явным_типом():
    """`image.align` / `diagram.align` и элементы `table.align` уезжали как typeless
    `{"enum": [...]}` — ровно то место, где пара разъезжалась молча."""
    for тип in ("image", "diagram"):
        assert orchestrator.tag_schema(hokoku.TagSpec(type=тип))["properties"]["align"] == \
            {"type": "string", "enum": ["left", "center", "right"]}
    таблица = orchestrator.tag_schema(hokoku.TagSpec(type="table"))["properties"]["align"]
    assert таблица["items"] == {"type": "string", "enum": ["left", "center", "right"]}
    # «промолчать» модели даёт strictify, дописывая null необязательному полю сам
    строгая = llm.jsonschema.strictify(orchestrator.tag_schema(hokoku.TagSpec(type="image")))
    assert строгая["properties"]["align"]["type"] == ["string", "null"]
    assert None in строгая["properties"]["align"]["enum"]


def test_сторож_схема_без_имени_типа_поставщику_не_годится():
    """Различие задумано и задокументировано: `value_schema()` — валидатор и
    документация (в корне `$schema` и `anyOf`), а схема для модели это
    `value_schema(тип)` по одному тегу или `any_value_schema()` объединением.

    Тест пинает именно эту границу. Если `value_schema()` вдруг станет годной
    поставщику, он упадёт — и это повод решить, что теперь отдавать модели, а не
    узнать о перемене через полгода по чужому 400.
    """
    with pytest.raises(llm.jsonschema.SchemaError, match=r"\$schema"):
        llm.jsonschema.check_schema(hokoku.value_schema())
    варианты = orchestrator.any_value_schema()["anyOf"]
    assert {v["properties"]["type"]["const"] for v in варианты} == set(hokoku.VALUE_TYPES)


def test_сторож_отвергает_поле_без_типа():
    """Проверка самого сторожа: поле без типа обязано его ронять, и на всех трёх
    глубинах — свойство, вариант объединения, элемент списка. Иначе он зелен всегда
    и не стережёт ничего.

    Схема здесь написана руками нарочно: подложить такое поле в `wire._TYPES` нельзя
    (`_Field` заморожен), а сторож без собственной проверки — украшение.
    """
    прежняя = {"type": "string", "enum": ["left", "center", "right"]}
    без_типа = {"enum": ["left", "center", "right"]}             # как было до правки
    assert _typeless({"type": "object", "properties": {"align": прежняя}}) == []
    assert len(_typeless({"type": "object", "properties": {"align": без_типа}})) == 1
    assert len(_typeless({"anyOf": [{"type": "string"}, без_типа]})) == 1
    assert len(_typeless({"type": "array", "items": без_типа})) == 1
