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


def прогнать(doors):
    """Работа, доведённая до архива: замечание бывает только к сделанному."""
    session = kadai.run.new(doors.services())
    return kadai.run.run(session)


def тексты(project) -> dict:
    return {b["key"]: b["value"].get("text", "") for b in project.blocks()
            if b["kind"] in ("markdown", "text")}


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


# ── исполнение замечания на дверях ───────────────────────────────────────────

def test_замечание_к_одному_блоку_пересчитывает_один_блок(doors):
    """Минимальный пересчёт «этого куска»: блок возвращается в черновик с
    замечанием человека, и проход текста пишет ровно его. Остальные тексты
    остаются буква в букву — иначе замечание к абзацу оплатило бы весь отчёт."""
    session = прогнать(doors)
    было = тексты(doors.project)
    ключ = [k for k, v in было.items() if v.startswith("Написано моделью")][0]
    итог = rework.apply(session, note="суховато, добавь пример", block=ключ)

    assert итог["kind"] == "кусок"
    assert итог["stages"] == ("тексты", "сборка", "архив")
    стало = тексты(doors.project)
    assert {k: v for k, v in стало.items() if k != ключ} == \
        {k: v for k, v in было.items() if k != ключ}
    assert doors.texts == [{"overwrite": False}, {"overwrite": False}]
    assert len(doors.solved) == 1                 # петлю ради абзаца не звали
    assert session.work.state == "done"


def test_замечание_к_блоку_с_таблицей_идёт_петлёй_а_текст_не_трогает(doors):
    """Правка нетекстового блока локальна: текст ссылается на него через
    `{ref:}`, а номер ставит сборщик, — значит замена содержимого не делает
    текст неверным."""
    session = прогнать(doors)
    было = тексты(doors.project)
    ключ = [b["key"] for b in doors.project.blocks() if b["kind"] == "table"][0]
    итог = rework.apply(session, note="добавь колонку с памятью", block=ключ)

    assert итог["kind"] == "схема"
    assert "решение" in итог["stages"] and "тексты" not in итог["stages"]
    assert тексты(doors.project) == было
    assert ключ in doors.solved[-1]["task"] and "добавь колонку" in doors.solved[-1]["task"]


def test_замечание_к_коду_честно_переписывает_весь_текст(doors):
    """Смена кода меняет вход у всех текстовых блоков сразу. Половина отчёта по
    старому коду — дефект, а не экономия, и вырождение записано словами."""
    session = прогнать(doors)
    ключ = [b["key"] for b in doors.project.blocks() if b["kind"] == "code"][0]
    итог = rework.apply(session, note="сортировка не та", block=ключ)

    assert итог["kind"] == "код"
    assert "текст пересчитывается весь" in итог["note"]
    assert "текст точечно не пересчитывается" in итог["honest"]
    assert len(doors.texts) == 2                  # второй проход целиком, а не по блоку


def test_замечание_к_строению_честно_называет_потерю(doors):
    """`make_template` выдаёт ключи заново, и перенести правку человека по ключу
    нельзя: тот же ключ в новом строении означает другой раздел."""
    session = прогнать(doors)
    записи = doors.project.blocks()
    записи[1] = {**записи[1], "source": "manual"}
    doors.project.set_blocks(записи, source="manual", note="правка человека")

    итог = rework.apply(session, note="добавь раздел про сложность", kind="структура")
    assert "не переедут" in итог["note"] and "rollback_blocks" in итог["note"]
    assert "строение_заново" in [p["code"] for p in session.work.problems]


def test_замечание_без_блока_и_без_вида_не_угадывается(doors):
    """Разбирать слова замечания нельзя: «тут всё не то» не содержит ни одного
    слова любого списка, и угаданный маршрут переписал бы не то."""
    session = прогнать(doors)
    with pytest.raises(kadai.KadaiError, match="назовите блок"):
        rework.apply(session, note="тут всё не то")


def test_замечание_к_блоку_которого_нет_подсказывает(doors):
    session = прогнать(doors)
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        rework.apply(session, note="перепиши", block="b-1")


def test_блок_человека_не_переписывается_даже_по_прямой_просьбе(doors):
    """Замечание к своему же абзацу — это правка в Word, а не прогон модели.

    Отказ, а не прогон впустую: дверь свой блок не тронет (и правильно), а
    работа упёрлась бы в «писать нечего» и встала бы `failed` — по замечанию,
    которое человек мог выполнить сам за минуту.
    """
    session = прогнать(doors)
    записи = doors.project.blocks()
    ключ = [b["key"] for b in записи if b["kind"] == "markdown"][1]
    записи = [{**b, "source": "manual"} if b["key"] == ключ else b for b in записи]
    было = [b for b in записи if b["key"] == ключ][0]["value"]["text"]
    doors.project.set_blocks(записи, source="manual", note="правка человека")

    with pytest.raises(kadai.KadaiError, match="написан человеком"):
        rework.apply(session, note="перепиши покороче", block=ключ)
    стало = [b for b in doors.project.blocks() if b["key"] == ключ][0]["value"]["text"]
    assert стало == было and session.work.state == "done"
