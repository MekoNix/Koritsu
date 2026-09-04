"""
Профиль вида работы: данные, а не код, и четыре сита до первого дорогого вызова.

Тесты стерегут то, что молча ломается: тип тега, назначенный моделью вместо
профиля; раздел, которого `hokoku` не умеет и который стал бы обычным
markdown'ом; ключ, который не станет тегом или схлопнется с соседним. Каждая из
этих бед даёт собранный и правильно выглядящий отчёт — и потому ловится здесь,
до сборки шаблона, а не глазами на кафедре.
"""
from __future__ import annotations

import pytest

import kadai


def test_профиль_читается_данными_и_называет_стадии(profile):
    assert profile.name == "курсовая"
    assert "решение" in profile.stages and profile.stages[0] == "приём"
    # Заготовка DOCX названа именем файла, а не путём: «другая кафедра» —
    # это замена файла, а не правка кода.
    assert profile.base.endswith(".docx") and "/" not in profile.base


def test_тип_тега_берётся_из_профиля_а_не_из_структуры(profile, structure):
    """Тип, угаданный по метке, — известная беда: модель напишет про схему прозой,
    а отчёт соберётся. Профиль знает тип по виду раздела, и угадывать нечего."""
    by_key = {s.key: s for s in kadai.sections_of(profile, structure)}
    assert by_key["схема_алгоритма"].type == "diagram"
    assert by_key["листинг_сортировки"].type == "code"
    assert by_key["оглавление"].type == "toc"
    assert by_key["введение"].limits["max_chars"] > 0


def test_запрещённый_вид_отвергается_с_объяснением(profile, structure):
    """Приложений по ГОСТ и библиографии в hokoku нет. Молча они стали бы
    markdown-тегами: заголовок есть, нумерации «А.1» и ссылок «[3]» нет."""
    structure["sections"].append({"key": "приложение_а", "title": "Приложение А",
                                  "kind": "приложение"})
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert codes == ["вид_запрещён"]
    problem = kadai.check_structure(profile, structure)[0]
    assert "нумерации" in problem["message"]


def test_неизвестный_вид_ловится_с_подсказкой(profile, structure):
    structure["sections"][2]["kind"] = "введени"
    problem = kadai.check_structure(profile, structure)[0]
    assert problem["code"] == "вид_неизвестен" and "похоже на" in problem["message"]


def test_ключ_который_не_станет_тегом(profile, structure):
    """`hokoku.tags.TAG_RE` не пустит в ключ ни пробела, ни двоеточия. Без этого
    сита раздел просто не появился бы в документе, и узнали бы мы об этом от
    check_manifest — когда DOCX уже собран."""
    structure["sections"][2]["key"] = "введение в тему"
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "ключ_не_тег" in codes


def test_ключи_схлопывающиеся_после_нормализации(profile, structure):
    """«й» разложенная (NFD) и составная (NFC) — один тег после norm_key.
    Шаблон собрался бы, тег был бы один, а разделов человек ждёт два."""
    structure["sections"][2]["key"] = "фойе"
    structure["sections"][3]["key"] = "фо" + "и" + "̆" + "е"
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "ключ_повторён" in codes


def test_обязательный_раздел_и_повтор_единственного(profile, structure):
    structure["sections"] = [s for s in structure["sections"] if s["kind"] != "заключение"]
    structure["sections"].append({"key": "введение2", "title": "Ещё введение",
                                  "kind": "введение"})
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "нет_обязательного" in codes and "вид_повторён" in codes


def test_курсовая_без_кода_и_схем_отвергается(profile, structure):
    """Не оформление, а признак неверно понятого условия — и потому сито,
    а не предупреждение."""
    structure["sections"] = [s for s in structure["sections"]
                             if s["kind"] not in ("листинг", "схема")]
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "нет_кода" in codes and "нет_схем" in codes


def test_число_разделов_проверяется_а_знаки_нет(profile, structure):
    """Знаки проверяются лимитами манифеста на готовых значениях: здесь значений
    ещё нет, и обещать проверку объёма было бы враньём."""
    structure["sections"] = structure["sections"][:3]
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "мало_разделов" in codes


def test_лишнее_поле_раздела_не_проходит_молча(profile, structure):
    structure["sections"][0]["type"] = "image"
    codes = [p["code"] for p in kadai.check_structure(profile, structure)]
    assert "лишнее_поле" in codes


def test_sections_of_отказывает_целиком_а_не_отдаёт_половину(profile, structure):
    structure["sections"][0]["kind"] = "приложение"
    with pytest.raises(kadai.KadaiError):
        kadai.sections_of(profile, structure)


def test_неизвестное_поле_профиля_ошибка_с_подсказкой():
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.parse({"name": "х", "volumes": {}})


def test_вид_нельзя_разрешить_и_запретить_разом():
    with pytest.raises(kadai.KadaiError, match="kinds"):
        kadai.parse({"kinds": {"схема": {}}, "forbidden": {"схема": "нельзя"}})


def test_профиля_нет_ошибка_с_подсказкой():
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.load("kursovay")


def test_заготовки_docx_ещё_нет_и_это_сказано_вслух(profile):
    """Пустые байты вместо заготовки прошли бы `Project.create` насквозь:
    манифест вышел бы пустым, а отчёт собрался бы из одного листа."""
    with pytest.raises(kadai.NotReady, match="заготовки"):
        kadai.base_template(profile)


# ── вид работы не фиксирован: строение сочиняется, профиль складывается ──────

def test_схема_вопроса_закрывает_перечень_видов_раздела(profile):
    """`strict` у поставщика гасит целый класс ответов до того, как за них
    заплачено: «Приложение А» просто не выразимо. Сито при этом остаётся —
    строение приходит и от человека, и из файла, где схемы не было."""
    schema = kadai.structure_schema(profile)
    виды = schema["properties"]["sections"]["items"]["properties"]["kind"]["enum"]
    assert "листинг" in виды and "приложение" not in виды
    assert schema["required"] == ["work_kind", "sections"]


def test_вопрос_называет_запреты_вслух(profile):
    """Сито отвергнет запрещённый вид с внятным текстом, но заплачено за ответ
    уже будет: одна строка запроса дешевле одного лишнего вызова модели."""
    текст = kadai.structure_request(profile, wishes="покороче")
    assert "приложение" in текст and "библиография" in текст


def test_профиль_складывается_из_ответа_модели(profile):
    """Обязательные разделы и потребность в коде приходят из ответа; палитра
    видов, их типы и запреты — из умолчания."""
    сочинённый = kadai.compose(profile, {
        "work_kind": "лабораторная",
        "expects": {"code": True, "tables": False, "diagrams": False},
        "required_kinds": ["постановка", "реализация"],
        "sections": []})
    assert сочинённый.name == "лабораторная"
    assert сочинённый.kind("постановка").required and not сочинённый.kind("введение").required
    assert сочинённый.kind("листинг").type == "code"        # тип назначает профиль
    assert сочинённый.forbidden == profile.forbidden
    assert сочинённый.needs == {"code": True, "tables": False, "diagrams": False}


def test_работа_без_кода_таблиц_и_схем_теряет_стадию_решения(profile):
    реферат = kadai.compose(profile, {
        "work_kind": "реферат",
        "expects": {"code": False, "tables": False, "diagrams": False},
        "sections": []})
    assert "решение" not in реферат.stages
    assert list(реферат.stages) == [s for s in profile.stages if s != "решение"]


def test_нижняя_граница_объёма_не_переносится_на_чужой_вид_работы(profile):
    """«Не меньше шести разделов» — утверждение про курсовую. Применить его к
    лабораторной значило бы отвергнуть законное строение словами про профиль,
    которого у этого вида работы нет."""
    лаба = kadai.compose(profile, {"work_kind": "лабораторная", "sections": []})
    assert "sections_min" not in лаба.volume
    assert лаба.volume["sections_max"] == profile.volume["sections_max"]
    своя = kadai.compose(profile, {"work_kind": "курсовая", "sections": []})
    assert своя.volume["sections_min"] == profile.volume["sections_min"]


def test_обязательным_нельзя_объявить_вид_которого_нет(profile):
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.compose(profile, {"work_kind": "курсовая", "sections": [],
                                "required_kinds": ["введени"]})


def test_неизвестное_поле_ответа_ошибка_а_не_молчание(profile):
    with pytest.raises(kadai.KadaiError, match="неизвестное поле"):
        kadai.compose(profile, {"work_kind": "курсовая", "sections": [],
                                "разделы": []})


def test_сочинённый_профиль_переживает_запись_в_проект(profile):
    """Считает работу один процесс, показывает другой: профиль обязан
    записываться и читаться одним и тем же разбором, иначе форма разойдётся."""
    сочинённый = kadai.compose(profile, {
        "work_kind": "расчётная работа",
        "expects": {"code": True, "tables": True, "diagrams": False},
        "required_kinds": ["результаты"], "sections": []})
    туда_обратно = kadai.parse(kadai.profile.as_dict(сочинённый), source="запись")
    assert туда_обратно == сочинённый
