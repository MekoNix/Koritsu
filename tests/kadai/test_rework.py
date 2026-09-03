"""
Маршрутизация замечаний: таблица, а не цепочка `if`, и честная колонка бессилия.

Здесь стережётся то, ради чего таблица и заведена: маршрут «код» и маршрут
«условие» обязаны САМИ говорить, что пересчитывают весь текст. Пока это
написано комментарием, оно отстаёт от кода, и через полгода «почему правка
одного абзаца переписала отчёт» отвечается чтением ветки. Плюс два вычисления,
которые действительно вычисляются: кто ссылается на артефакт и что изменилось
между манифестами.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import rework

from .conftest import FakeProject, FakeSpec


def test_каждый_маршрут_называет_где_он_бессилен():
    for kind, route in kadai.ROUTES.items():
        assert route.honest.strip(), f"маршрут {kind} молчит о своих пределах"
        assert route.stages and route.cost


def test_маршрут_схемы_локален_а_маршрут_кода_нет():
    """Текст ссылается на схему через {ref:ключ}, а не через номер, — поэтому
    замена схемы текст не портит. Смена исходника меняет стабильный префикс
    промпта у всех текстовых тегов сразу, и там локального нет."""
    assert kadai.route("схема").full_text is False
    assert kadai.route("код").full_text is True
    assert "все тексты" in kadai.route("схема").keep


def test_про_ветки_схемы_сказано_честно():
    """«Да»/«Нет» во fragmos — свободные ячейки по координатам, а не подписи
    рёбер: замечание «ветки перепутаны» проверить нечем."""
    assert "ветк" in kadai.route("схема").honest


def test_неизвестный_вид_замечания_с_подсказкой():
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.route("схемы")


def test_кто_ссылается_на_артефакт_считается_проходом_по_значениям():
    values = {"схема_алгоритма": {"type": "diagram", "artifact": "c1"},
              "результаты": {"type": "blocks",
                             "blocks": [{"type": "image", "artifact": "c1"},
                                        {"type": "markdown", "text": "…"}]},
              "введение": {"type": "markdown", "text": "текст"}}
    assert kadai.tags_using_artifact(values, "c1") == ["результаты", "схема_алгоритма"]
    assert kadai.tags_using_artifact(values, "нетакого") == []


def test_замечание_к_схеме_без_артефакта_отказ():
    with pytest.raises(kadai.KadaiError, match="какую из схем"):
        kadai.plan_rework("схема")


def test_схема_которой_нет_в_отчёте_названа_прямо():
    план = kadai.plan_rework("схема", values={"введение": {"text": "…"}}, artifact="c1")
    assert план["tags"] == [] and "без толку" in план["note"]


def test_изменение_записи_манифеста_считается_по_входу_тега():
    """Вход тега — тип, промпт, лимиты и depends_on. Метка на вход не влияет, и
    правка подписи в Word не должна стоить перегенерации."""
    старый = {"введение": FakeSpec(prompt="кратко"), "цель": FakeSpec(),
              "убранный": FakeSpec()}
    новый = {"введение": FakeSpec(prompt="подробно"), "цель": FakeSpec(),
             "новый": FakeSpec()}
    diff = kadai.changed_entries(старый, новый)
    assert diff == {"changed": ["введение"], "added": ["новый"], "gone": ["убранный"]}


def test_маршрут_структуры_берёт_изменившиеся_и_добавленные():
    план = kadai.plan_rework("структура",
                             tags={"a": FakeSpec(), "b": FakeSpec(type="code")},
                             new_tags={"a": FakeSpec(prompt="иначе"), "c": FakeSpec()})
    assert план["tags"] == ["a", "c"] and "b" in план["note"]


def test_текстовые_теги_отделены_от_производимых_инструментом():
    tags = {"введение": FakeSpec(), "листинг": FakeSpec(type="code"),
            "схема": FakeSpec(type="diagram"), "таблица": FakeSpec(type="table"),
            "убранный": FakeSpec(missing=True)}
    assert kadai.text_tags(tags) == ["введение"]


def test_маршрут_кода_возвращает_весь_текст_и_говорит_об_этом():
    tags = {"введение": FakeSpec(), "листинг": FakeSpec(type="code")}
    план = kadai.plan_rework("код", tags=tags)
    assert план["tags"] == ["введение"] and план["full_text"] is True
    assert "точечного пересчёта" in план["note"]


def test_журнал_производных_это_шов():
    """Без него по замечанию «схему переделай» неизвестно, из какого исходника
    она построена, и «построю заново как-нибудь» выдаст другую схему за
    исправленную."""
    with pytest.raises(kadai.NotReady, match="derived_of"):
        kadai.inputs_of(FakeProject(without=["derived_of"]), "c1")


def test_замечание_к_куску_требует_ключа():
    """`None` значит «пересчитывается всё». У маршрута «кусок» это прочиталось бы
    как «переписать весь отчёт» — то есть замечание к абзацу оплатило бы прогон."""
    with pytest.raises(kadai.KadaiError, match="ключа тега"):
        kadai.plan_rework("кусок")
    план = kadai.plan_rework("кусок", key="введение")
    assert план["tags"] == ["введение"] and план["full_text"] is False
