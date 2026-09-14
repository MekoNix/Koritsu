"""
Схемы трёх режимов и слова, которыми просят: договор, на котором держится забор.

Схема — не описание ответа, а его граница. На первой ступени лестницы
структурированного вывода она едет в запрос, и закрытый объект
(`additionalProperties: false`, все поля обязательны) означает, что модель
физически не может вернуть ключ, которого мы не объявили. Что бы ни было
написано на доске, наружу выйдет только объявленное — это и есть защита от
инъекции со стороны ответа, в пару к рамке со стороны запроса.

Отсюда два свойства, которые здесь и проверяются:

* **закрыто и обязательно везде**, на любой глубине: приоткрытый вложенный
  объект возвращает модели свободу ровно там, где её труднее всего заметить;
* **`ok` трёхзначен**: `true`, `false` и `null` — «по строке не понять». Без
  третьего значения `false` на нераспознанной строке становится ложным
  обвинением, а `true` — подтверждением того, чего никто не видел.

Правила (`rules`) и просьба (`request`) разделены не для красоты: `rules` уезжает
системным сообщением и не меняется от вызова к вызову — на этом держится кэш
префикса, — а `request` меняется каждым нажатием.
"""
from __future__ import annotations

import pytest

import kokuban


def закрыт(узел) -> None:
    """Объект схемы закрыт и обязателен целиком, на любой глубине."""
    if isinstance(узел, dict) and узел.get("type") == "object":
        assert узел.get("additionalProperties") is False, узел
        assert sorted(узел.get("required", [])) == \
               sorted(узел.get("properties", {})), узел
    if isinstance(узел, dict):
        for значение in узел.values():
            закрыт(значение)
    elif isinstance(узел, list):
        for значение in узел:
            закрыт(значение)


@pytest.mark.parametrize("режим", kokuban.MODES)
def test_схема_режима_закрыта_целиком(режим):
    закрыт(kokuban.schema(режим))


def test_схема_проверки_называет_ровно_четыре_поля():
    """Форма ответа — договор с сайтом и службой: лишнее поле ломает обоих."""
    схема = kokuban.schema("check")
    assert sorted(схема["required"]) == ["checked", "remarks", "steps", "verdict"]
    assert схема["properties"]["verdict"]["enum"] == list(kokuban.VERDICTS)


def test_у_шага_три_состояния():
    """`null` обязателен: «не понять» — это не «неверно»."""
    шаг = kokuban.schema("check")["properties"]["steps"]["items"]
    assert шаг["properties"]["ok"]["type"] == ["boolean", "null"]
    assert sorted(шаг["required"]) == ["note", "ok", "step"]


def test_виды_замечаний_перечислены_и_закрыты():
    замечание = kokuban.schema("check")["properties"]["remarks"]["items"]
    assert замечание["properties"]["kind"]["enum"] == list(kokuban.REMARK_KINDS)
    assert "missing" in kokuban.REMARK_KINDS


def test_подсказка_это_проверка_плюс_одно_поле():
    """Подсказку не с чем связать без разбора решения, а второй вызов ради
    разбора стоил бы вдвое при той же работе модели."""
    проверка, подсказка = kokuban.schema("check"), kokuban.schema("hint")
    assert set(подсказка["properties"]) == set(проверка["properties"]) | {"hint"}
    assert sorted(подсказка["properties"]["hint"]["required"]) == ["step", "text"]


def test_задача_просит_только_задачу():
    """В режиме `drill` вердикта о решении не выносится — его и не просят."""
    задача = kokuban.schema("drill")
    assert list(задача["properties"]) == ["drill"]
    assert sorted(задача["properties"]["drill"]["required"]) == [
        "answer", "hint", "task", "topic", "why"]


def test_схема_отдаётся_копией():
    """Лестница правит схему на строгой ступени; правка общего словаря уехала бы
    в следующий вызов другого режима."""
    своя = kokuban.schema("check")
    своя["properties"]["verdict"]["enum"] = ["что угодно"]
    assert kokuban.schema("check")["properties"]["verdict"]["enum"] == \
           list(kokuban.VERDICTS)


def test_незнакомый_режим_становится_проверкой():
    """Отказ здесь был бы отказом на опечатке в чужом поле; проверка — умолчание."""
    assert kokuban.schema("никакой") == kokuban.schema("check")
    assert kokuban.rules("никакой", "никакой") == kokuban.rules("check", "explain")


def test_правила_объясняют_что_такое_шаг_и_что_значит_ok():
    """Не объясни — и модель начнёт отвечать про синтаксис отдельных строк."""
    правила = kokuban.rules("check", "explain")
    assert "переход" in правила.lower()
    assert "кадр" in правила.lower()
    assert kokuban.DEPTH["explain"] in правила
    assert kokuban.MODE_RULES["check"] in правила


def test_уровень_помощи_меняет_правила_а_не_схему():
    """Смысл уровня — сколько сказать, а не сколько раз спросить."""
    assert kokuban.rules("check", "hint") != kokuban.rules("check", "solution")
    assert kokuban.schema("check") == kokuban.schema("check")
    assert kokuban.DEPTH["hint"] in kokuban.rules("check", "hint")


def test_просьба_подсказать_называет_строку():
    """Подсказка без места приложения — это «подскажи что-нибудь»."""
    просьба = kokuban.request("hint", "hint", "da9bb7")
    assert "[da9bb7]" in просьба
    assert "hint" in просьба
    # Без строки просьба не разваливается: место выбирает репетитор.
    assert "застряло" in kokuban.request("hint", "hint")


def test_просьба_дать_задачу_не_просит_вердикта():
    просьба = kokuban.request("drill", "explain")
    assert "drill" in просьба
    assert "verdict" not in просьба
