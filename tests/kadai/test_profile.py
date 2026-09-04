"""
Строение работы: целиком из ответа модели, и четыре сита до первого дорогого вызова.

Здесь стерегутся два решения владельца 2026-09-04. Первое несущее: **вида работы
в коде нет**. Ни файла-профиля, ни умолчания, ни палитры разделов — работой
бывает что угодно, хоть учёт продажи носков, и всякое слово о видах работ,
записанное в пакете, было бы утверждением о том, чего мы не знаем. Второе:
**обязательные разделы называет модель**, и сито проверяет структуру против
того, что она сама же и объявила.

Остальные тесты стерегут то, что молча ломается: тип раздела мимо перечня
движка; раздел, которого `hokoku` не умеет и который стал бы обычным текстом;
ключ, который не станет тегом или схлопнется с соседним. Каждая из этих бед
даёт собранный и правильно выглядящий отчёт — и потому ловится здесь, до
сборки скелета, а не глазами на готовом документе.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import kadai

ОБРАЗЕЦ = Path(__file__).parent / "образец-строения.yaml"


# ── вид работы не фиксирован ─────────────────────────────────────────────────

def test_строение_складывается_целиком_из_ответа_модели(profile):
    """Ни имени вида работы, ни видов разделов, ни обязательности код не знает:
    всё это пришло из ответа модели по условию."""
    assert profile.name == "учёт продажи носков"
    assert sorted(profile.kinds) == ["выводы", "выгрузка", "остатки", "предисловие", "схема"]
    assert [name for name, k in profile.kinds.items() if k.required] == ["остатки", "выводы"]
    assert profile.needs == {"code": True, "tables": True, "diagrams": True}


def test_вид_раздела_называет_модель_а_тип_берётся_из_перечня_движка(profile, structure):
    """Тип, угаданный по имени раздела, — известная беда: модель напишет про
    схему прозой, а отчёт соберётся. Поэтому полей два, и второе — перечислимо."""
    by_key = {s.key: s for s in kadai.sections_of(profile, structure)}
    assert by_key["схема_учёта"].kind == "схема" and by_key["схема_учёта"].type == "diagram"
    assert by_key["остатки"].type == "table"
    assert by_key["зачем"].kind == "предисловие"        # слово модели, не наше
    assert set(kadai.SECTION_TYPES) >= {"markdown", "code", "table", "diagram"}


def test_вид_раздела_может_быть_любым_словом(profile, structure):
    """Закрытый список видов означал бы, что вид работы всё-таки известен заранее."""
    structure["sections"].append({"key": "носки_по_цветам", "title": "Носки по цветам",
                                  "kind": "разбивка по цветам", "type": "table"})
    свежий = kadai.compose({**{"work_kind": "учёт продажи носков"},
                            "sections": structure["sections"],
                            "expects": {"code": False, "tables": True, "diagrams": False}},
                           stages=kadai.STAGE_NAMES)
    assert kadai.check_structure(свежий, structure) == []
    assert свежий.kind("разбивка по цветам").type == "table"


def test_работа_без_кода_таблиц_и_схем_теряет_стадию_решения():
    """Там, где производить нечего, петле работать не над чем, и показать стадию
    сделанной значило бы соврать полоской хода о работе, которой не было."""
    записка = kadai.compose({"work_kind": "объяснительная записка",
                             "expects": {"code": False, "tables": False, "diagrams": False},
                             "sections": [{"key": "суть", "title": "Суть",
                                           "kind": "суть", "type": "markdown"}]},
                            stages=kadai.STAGE_NAMES)
    assert "решение" not in записка.stages
    assert list(записка.stages) == [s for s in kadai.STAGE_NAMES if s != "решение"]


# ── четыре сита ──────────────────────────────────────────────────────────────

def test_запрещённый_вид_отвергается_с_объяснением(profile, structure):
    """Приложений по ГОСТ и библиографии в hokoku нет. Молча они стали бы
    обычным текстом: заголовок есть, нумерации «А.1» и ссылок «[3]» нет."""
    structure["sections"].append({"key": "приложение_а", "title": "Приложение А",
                                  "kind": "приложение", "type": "markdown"})
    беды = kadai.check_structure(profile, structure)
    assert [p["code"] for p in беды] == ["вид_запрещён"]
    assert "нумерации" in беды[0]["message"]


def test_тип_мимо_перечня_движка_ловится(profile, structure):
    """«video» молча стало бы обычным текстом: заголовок был бы, содержимого нет."""
    structure["sections"][1]["type"] = "video"
    беда = kadai.check_structure(profile, structure)[0]
    assert беда["code"] == "тип_неизвестен" and "table" in беда["message"]


def test_вид_объявленный_двумя_типами_отвергается():
    """Раздел, который в одном месте схема, а в другом текст, — это строение,
    отвечающее на один вопрос дважды. Выбрать за модель нельзя."""
    with pytest.raises(kadai.KadaiError, match="ответ один"):
        kadai.compose({"work_kind": "сводка", "sections": [
            {"key": "a", "title": "А", "kind": "сводка", "type": "table"},
            {"key": "b", "title": "Б", "kind": "сводка", "type": "markdown"}]},
            stages=kadai.STAGE_NAMES)


def test_неизвестный_вид_ловится_с_подсказкой(profile, structure):
    """Структуру правит и человек, и интерфейс — там ни схемы, ни compose не было."""
    structure["sections"][1]["kind"] = "остатк"
    беда = kadai.check_structure(profile, structure)[0]
    assert беда["code"] == "вид_неизвестен" and "похоже на" in беда["message"]


def test_ключ_который_не_станет_тегом(profile, structure):
    """`hokoku.tags.TAG_RE` не пустит в ключ ни пробела, ни двоеточия. Без этого
    сита раздел просто не появился бы в документе."""
    structure["sections"][0]["key"] = "зачем это"
    assert "ключ_не_тег" in [p["code"] for p in kadai.check_structure(profile, structure)]


def test_ключи_схлопывающиеся_после_нормализации(profile, structure):
    """«й» разложенная (NFD) и составная (NFC) — один ключ после norm_key.
    Скелет собрался бы, блок был бы один, а разделов человек ждёт два."""
    structure["sections"][0]["key"] = "фойе"
    structure["sections"][1]["key"] = "фо" + "и" + "̆" + "е"
    assert "ключ_повторён" in [p["code"] for p in kadai.check_structure(profile, structure)]


def test_обязательный_раздел_называет_модель_и_сито_его_стережёт(profile, structure):
    """Обязательность — утверждение модели о работе (`required_kinds`), а не наше
    о виде работы. Проверить его всё равно надо: структуру правят и после ответа."""
    structure["sections"] = [s for s in structure["sections"] if s["kind"] != "остатки"]
    беды = kadai.check_structure(profile, structure)
    коды = [p["code"] for p in беды]
    assert "нет_обязательного" in коды and "нет_таблиц" in коды
    assert 'вида "остатки"' in [p["message"] for p in беды if p["code"] == "нет_обязательного"][0]


def test_работа_без_обещанного_кода_и_схем_отвергается(profile, structure):
    """Не оформление, а признак того, что условие поняли неверно, — и потому сито."""
    structure["sections"] = [s for s in structure["sections"]
                             if s["type"] not in ("code", "diagram")]
    коды = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "нет_кода" in коды and "нет_схем" in коды


def test_нижней_границы_объёма_нет_а_верхняя_есть(profile, structure):
    """«Работы короче шести разделов не бывает» — утверждение про один вид работы;
    верхняя граница про движок: весь текст пишется одним проходом."""
    structure["sections"] = structure["sections"][:1]
    assert [p["code"] for p in kadai.check_structure(profile, structure)
            if p["code"] in ("мало_разделов", "много_разделов")] == []
    много = {"sections": [{"key": f"r{i}", "title": f"Р{i}", "kind": "предисловие",
                           "type": "markdown"}
                          for i in range(kadai.MAX_SECTIONS + 1)]}
    assert "много_разделов" in [p["code"] for p in kadai.check_structure(profile, много)]


def test_лишнее_поле_раздела_не_проходит_молча(profile, structure):
    structure["sections"][0]["level"] = 2
    assert "лишнее_поле" in [p["code"] for p in kadai.check_structure(profile, structure)]


def test_sections_of_отказывает_целиком_а_не_отдаёт_половину(profile, structure):
    """Половина разделов — худшее из возможного: отчёт вышел бы короче
    задуманного, и объяснить, куда делись разделы, было бы нечем."""
    structure["sections"][0]["kind"] = "приложение"
    with pytest.raises(kadai.KadaiError):
        kadai.sections_of(profile, structure)


# ── ответ модели: что принимается, а что отказ ───────────────────────────────

def test_схема_вопроса_закрывает_перечень_типов_а_вид_оставляет_свободным():
    """`strict` у поставщика гасит целый класс ответов до того, как за них
    заплачено. Вид раздела при этом перечислить нельзя: его называет условие."""
    schema = kadai.structure_schema()
    поля = schema["properties"]["sections"]["items"]["properties"]
    assert поля["type"]["enum"] == list(kadai.SECTION_TYPES)
    assert "enum" not in поля["kind"]
    assert schema["required"] == ["work_kind", "sections"]


def test_вопрос_называет_запреты_и_потолок_вслух():
    """Сито отвергнет запрещённый вид с внятным текстом, но заплачено за ответ
    уже будет: одна строка запроса дешевле одного лишнего вызова модели."""
    текст = kadai.structure_request(wishes="покороче")
    assert "приложение" in текст and "библиография" in текст
    assert str(kadai.MAX_SECTIONS) in текст and "пожелания" in текст.lower()


def test_обязательным_нельзя_объявить_вид_которого_в_строении_нет():
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.compose({"work_kind": "сводка", "required_kinds": ["остатк"],
                       "sections": [{"key": "o", "title": "О", "kind": "остатки",
                                     "type": "table"}]}, stages=kadai.STAGE_NAMES)


def test_неизвестное_поле_ответа_ошибка_а_не_молчание():
    with pytest.raises(kadai.KadaiError, match="неизвестное поле"):
        kadai.compose({"work_kind": "сводка", "sections": [], "разделы": []},
                      stages=kadai.STAGE_NAMES)


def test_сочинённое_строение_переживает_запись_в_проект(profile):
    """Считает работу один процесс, показывает другой: строение обязано
    записываться и читаться одним и тем же разбором, иначе форма разойдётся."""
    туда_обратно = kadai.parse(kadai.profile.as_dict(profile), source="запись")
    assert туда_обратно == profile


# ── форма записи проверяется на образце, а не только на себе самой ───────────

def test_образец_формы_читается_данными():
    """Файл-образец лежит в тестах, а не в пакете (решение владельца 2026-09-04):
    умолчания у вида работы нет, а форма записи проверки требует."""
    строение = kadai.parse(yaml.safe_load(ОБРАЗЕЦ.read_text("utf-8")), source="образец")
    assert строение.name == "учёт продажи носков"
    assert строение.kind("остатки").type == "table" and строение.kind("остатки").required
    assert "решение" in строение.stages and строение.stages[0] == "приём"
    assert kadai.parse(kadai.profile.as_dict(строение)) == строение


def test_неизвестное_поле_записи_ошибка_с_подсказкой():
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.parse({"name": "х", "stage": []})


def test_вид_нельзя_разрешить_и_запретить_разом():
    with pytest.raises(kadai.KadaiError, match="kinds"):
        kadai.parse({"kinds": {"схема": {}}, "forbidden": {"схема": "нельзя"}})
