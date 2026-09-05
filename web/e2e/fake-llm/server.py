#!/usr/bin/env python3
"""
Поддельная модель для стенда сайта: говорит по протоколу `openai`, не думая.

    python3 web/e2e/fake-llm/server.py --port 8016

Зачем это есть. Сайт проверяется сквозными прогонами — от кнопки до текста тега
в потоке SSE, — а прогон зовёт модель. Ключей у проверок нет и не должно быть,
сети на стенде тоже нет. Значит нужен кто-то, кто ответит вместо поставщика; и
подставлять его надо там, где у сети есть шов, — по адресу. Служба ходит сюда
обычным путём (`KORITSU_LLM_BASE_URL_DEEPSEEK`, только `dev`), а разговор ведёт
настоящий `llm.backends.openai_compat`: проверяется служба, а не подделка.

    Чем этот сервер отличается от `tests/api/b_fixtures.py`
    ------------------------------------------------------

Юнит-тесты подменяют **провод** (`llm.registry.backends.make`) и живут в одном
процессе с обработчиком. На стенде так нельзя: обработчик задания уезжает в
отдельный процесс с вычищенным окружением, и памяти с подделкой там нет. Поэтому
здесь подделан не провод, а сервер на другом его конце: HTTP, SSE, `usage`,
коды ошибок.

    Что он отвечает и откуда это знает
    ----------------------------------

Ничего не выдумывая про домен: **форму ответа он берёт из самого запроса**.

* схема приехала полем (`response_format.json_schema`) — ответ строится по ней;
* схема приехала инструментом (`tool_choice: set_values`) — тем же построением,
  но вызовом инструмента;
* схемы в запросе нет (ступень `json_object` — так объявлен пресет `deepseek`),
  но слой пересказал её словами в промпте («Требуемая структура ответа: …»,
  `llm.structured.schema_hint`) — описание разбирается обратно в схему;
* ничего из этого нет — ответ словами.

Отсюда одно важное свойство: сервер не знает ни про теги, ни про стадии
`kadai`, ни про уровни оркестратора. Появится новый вид прогона со своей схемой
— он ответит и на него, потому что отвечает он не «на fill_tag», а на форму,
которую у него попросили. Имена тегов он всё же вычитывает из промпта
(«Заполни тег [цель]») — но только затем, чтобы текст в ответе был про дело и
его можно было узнать глазами на экране.

    Ошибки по требованию
    --------------------

В любом месте запроса (промпт, задача агента, имя проекта — что угодно, что
доедет до модели) маркер:

    [[FAKE:429]]   ответить 429 (слой повторит по своей политике и сдастся)
    [[FAKE:500]]   ответить 500
    [[FAKE:ERR]]   отдать 200 и положить ошибку **полем внутри потока** —
                   так делают шлюзы, и это отдельный путь в разборе (Б.2)

Так проверяется, как сайт показывает беду прогона, — без единого настоящего
отказа поставщика.

    Чего здесь намеренно нет
    ------------------------

Ни `pip install`, ни зависимостей: только стандартная библиотека, потому что
стенд поднимается одной строкой и обязан работать на голом Python 3.12.
Никакого состояния между запросами: два одинаковых запроса дают один и тот же
ответ, и проверка, упавшая один раз, падает всегда.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── что можно настроить снаружи ──────────────────────────────────────────────
# Задержка между кусками потока: без неё текст приезжает на сайт одним кадром, и
# «текст по мере генерации» проверить нечем. Тридцать миллисекунд — заметно
# глазу и не растягивает сквозную проверку на минуты.
ЗАДЕРЖКА_МС = int(os.environ.get("FAKE_DELAY_MS") or 30)
# Знаков в куске потока. Настоящие поставщики шлют куски рванее, но нам важна не
# похожесть, а то, что кусков больше одного.
КУСОК = int(os.environ.get("FAKE_CHUNK") or 48)

МАРКЕР_RE = re.compile(r"\[\[FAKE:(\d{3}|ERR)\]\]")
ТЕГ_RE = re.compile(r"Заполни тег \[([^\]\n]+)\]")
ТЕГИ_RE = re.compile(r"Заполни (?:теги|блоки): ([^\n]+)")
КЛЮЧ_В_СКОБКАХ_RE = re.compile(r"\[([^\]\s]+)\]")

# Строка описания схемы словами (`llm.jsonschema.describe`):
#     - text (строка, обязательно) — пояснение
ПОЛЕ_RE = re.compile(
    r"^(?P<отступ>\s*)- (?P<имя>\S+) \((?P<тип>.+?), (?P<нужно>обязательно|необязательно)\)"
    r"(?: — (?P<пояснение>.*))?$")
ВАРИАНТ_RE = re.compile(r"^(?P<отступ>\s*)- вариант (?P<тип>.+):$")
ЭЛЕМЕНТЫ_RE = re.compile(r"^(?P<отступ>\s*)элементы списка: (?P<тип>.+)$")
НАЧАЛО_ОПИСАНИЯ = "Требуемая структура ответа:"

# Поля, в которых лежит само содержимое значения (`hokoku.model`): текст в них
# пишется про объект целиком, а не про поле.
СОДЕРЖАНИЕ = ("text", "markdown", "code", "caption", "title", "alt")

СЛОВА_ТИПОВ = {"строка": "string", "число": "number", "целое число": "integer",
               "да/нет": "boolean", "объект": "object", "список": "array",
               "пусто": "null"}


# ── разбор запроса ───────────────────────────────────────────────────────────

def промпт(тело: dict) -> str:
    """Весь текст запроса одной строкой: по нему решается, что отвечать."""
    куски = []
    for сообщение in тело.get("messages") or []:
        содержимое = сообщение.get("content")
        if isinstance(содержимое, str):
            куски.append(содержимое)
        elif isinstance(содержимое, list):
            # Формат «части сообщения»: наш слой его не шлёт, но чужой клиент,
            # ткнувшийся в этот сервер, не должен получить пустоту.
            куски.extend(ч.get("text") or "" for ч in содержимое
                         if isinstance(ч, dict))
    return "\n\n".join(куски)


def маркер(тело: dict) -> str | None:
    """Просьба ответить бедой — из любого места запроса, а не только из промпта.

    Из любого: маркер человек ставит там, где ему удобно его поставить с сайта,
    — в задаче агента, в имени проекта, в тексте материала. Искать его только в
    промпте значило бы объяснять на сайте, куда именно его писать.
    """
    найдено = МАРКЕР_RE.search(json.dumps(тело, ensure_ascii=False))
    return найдено.group(1) if найдено else None


def имена_тегов(текст: str) -> list[str]:
    """Теги, которые просят заполнить. Нужны только для человекочитаемости.

    Ответ от них не зависит: форму ответа диктует схема. Но текст «Раздел
    «цель» написан прогоном…» на экране проверяющего стоит этих трёх строк.
    """
    один = ТЕГ_RE.search(текст)
    if один:
        return [один.group(1).strip()]
    много = ТЕГИ_RE.search(текст)
    if много:
        return [к.strip() for к in КЛЮЧ_В_СКОБКАХ_RE.findall(много.group(1))]
    return []


# ── описание схемы словами → схема ───────────────────────────────────────────

def тип_по_словам(слова: str) -> dict:
    """«ровно 'markdown'», «строка из: 'a', 'b'», «целое число» → кусок схемы.

    Обратный ход к `llm.jsonschema._type_words`. Он неполон и полным быть не
    может (описание словами — не сериализация), но покрывает всё, что слой
    сегодня описывает: константы, перечисления, объединения, простые типы.
    """
    слова = слова.strip()
    if слова.startswith("ровно "):
        return {"const": _значение(слова[len("ровно "):])}
    if слова.startswith("один из вариантов: "):
        # Объединение без общей формы: берём первый вариант — он в `anyOf`
        # первый и у слоя, а выбирать «поумнее» тут не из чего.
        return тип_по_словам(слова[len("один из вариантов: "):].split(", ")[0])
    if " из: " in слова:
        основа, перечисление = слова.split(" из: ", 1)
        схема = тип_по_словам(основа)
        схема["enum"] = [_значение(x) for x in перечисление.split(", ")]
        return схема
    if слова.startswith("объект "):
        # «объект 'markdown'» — помеченный вариант; сама метка приедет полем
        # `type` вложенными строками, здесь важно только «это объект».
        return {"type": "object"}
    if " или " in слова:
        # «строка или пусто»: берём первую ветку — пустое значение слой считает
        # за «поля нет», а нам надо ответить, а не промолчать.
        return тип_по_словам(слова.split(" или ")[0])
    return {"type": СЛОВА_ТИПОВ.get(слова, "string")}


def _значение(текст: str):
    """`'markdown'` → `markdown`. Не разобралось — оставляем как есть строкой."""
    try:
        return ast.literal_eval(текст.strip())
    except (ValueError, SyntaxError):
        return текст.strip().strip("'\"")


def схема_из_описания(текст: str) -> dict | None:
    """Блок «Требуемая структура ответа» → схема. `None` — блока нет.

    Разбор по отступам: `describe` печатает вложенное с шагом в два пробела и
    ничего больше про вложенность не сообщает.
    """
    начало = текст.find(НАЧАЛО_ОПИСАНИЯ)
    if начало < 0:
        return None
    строки = []
    for строка in текст[начало + len(НАЧАЛО_ОПИСАНИЯ):].splitlines():
        if not строка.strip():
            if строки:
                break            # описание кончилось — дальше идёт хвост-указание
            continue
        строки.append(строка.rstrip())
    if not строки:
        return None
    схема, _ = _собрать(строки, 0, _отступ(строки[0]))
    return схема or None


def _отступ(строка: str) -> int:
    return len(строка) - len(строка.lstrip(" "))


def _собрать(строки: list[str], i: int, уровень: int):
    """Строки одного уровня → схема объекта (или списка). → (схема, i)."""
    свойства: dict = {}
    обязательные: list[str] = []
    элементы = None
    while i < len(строки):
        строка = строки[i]
        отступ = _отступ(строка)
        if отступ < уровень:
            break
        поле = ПОЛЕ_RE.match(строка)
        вариант = ВАРИАНТ_RE.match(строка)
        список = ЭЛЕМЕНТЫ_RE.match(строка)
        if поле:
            i += 1
            под = тип_по_словам(поле.group("тип"))
            i = _вложить(строки, i, отступ, под)
            свойства[поле.group("имя")] = под
            if поле.group("нужно") == "обязательно":
                обязательные.append(поле.group("имя"))
            continue
        if вариант:
            # Помеченное объединение: берём первый вариант целиком и уходим —
            # остальные ветки описывают то же значение другим типом.
            i += 1
            под = тип_по_словам(вариант.group("тип"))
            i = _вложить(строки, i, отступ, под)
            return под, len(строки)
        if список:
            i += 1
            элементы = тип_по_словам(список.group("тип"))
            i = _вложить(строки, i, отступ, элементы)
            continue
        i += 1                    # «других ключей быть не должно» и прочий хвост
    if элементы is not None:
        return {"type": "array", "items": элементы}, i
    if not свойства:
        return None, i
    return {"type": "object", "properties": свойства,
            "required": обязательные}, i


def _вложить(строки: list[str], i: int, отступ: int, под: dict) -> int:
    """Разобрать вложенные строки (отступ больше) в уже созданный кусок схемы."""
    if i >= len(строки) or _отступ(строки[i]) <= отступ:
        return i
    вложенное, i = _собрать(строки, i, _отступ(строки[i]))
    if вложенное:
        под.update(вложенное)
    return i


# ── ответ по схеме ───────────────────────────────────────────────────────────

def по_схеме(схема: dict, теги: list[str], имя: str = "") -> object:
    """Значение, годное по этой схеме. Строки — осмысленные, остальное — простое.

    «Годное» здесь честное: константы ставятся те, что просили, обязательные
    поля заполняются все, лишних не добавляется. Иначе служба отвергла бы ответ
    своим же валидатором, и стенд проверял бы разбор ошибок вместо прогона.
    """
    if not isinstance(схема, dict):
        return текст_про(имя, теги)
    if "const" in схема:
        return схема["const"]
    if схема.get("enum"):
        return схема["enum"][0]
    if схема.get("anyOf"):
        return по_схеме(схема["anyOf"][0], теги, имя)
    тип = схема.get("type")
    if isinstance(тип, list):
        тип = next((т for т in тип if т != "null"), "string")
    if тип == "object":
        свойства = схема.get("properties") or {}
        нужны = схема.get("required")
        # Схемы `strictify` перечисляют в `required` вообще всё, а
        # необязательное выражают null'ом «этого поля я не задаю»
        # (`llm.jsonschema.drop_unset` снимет их у службы).
        нужны = list(нужны) if нужны else list(свойства)
        # Про что писать в текстовом поле: про сам объект, а не про поле. У
        # значения тега поле называется `text`, и «раздел text» на экране
        # проверяющего не значит ничего, а «раздел цель» — значит.
        предмет = имя or (теги[0] if теги else "")
        готово = {}
        for ключ in свойства:
            if ключ not in нужны:
                continue
            под = свойства[ключ]
            if _только_пусто(под):
                готово[ключ] = None
            else:
                готово[ключ] = по_схеме(
                    под, теги, предмет if ключ in СОДЕРЖАНИЕ else ключ)
        return готово
    if тип == "array":
        items = схема.get("items") or {"type": "string"}
        сколько = max(1, int(схема.get("minItems") or 1))
        return [по_схеме(items, теги, имя) for _ in range(сколько)]
    if тип == "integer":
        return int(схема.get("minimum") or 1)
    if тип == "number":
        return float(схема.get("minimum") or 1)
    if тип == "boolean":
        return True
    if тип == "null":
        return None
    return текст_про(имя, теги)


def _только_пусто(схема: dict) -> bool:
    """Поле, у которого кроме `null` ничего не разрешено, — заполнять нечем."""
    тип = схема.get("type")
    return тип == "null" or (isinstance(тип, list) and set(тип) == {"null"})


def текст_про(имя: str, теги: list[str]) -> str:
    """Русский текст, по которому видно, что он про это поле и этот прогон.

    Без заголовков, списков и разметки: тег бывает `inline` — стоит внутри
    строки шаблона, — и заголовок в таком значении служба справедливо считает
    замечанием (`hokoku.validate`).
    """
    про = имя.strip() or (теги[0] if теги else "работу")
    return (f"Это поддельный ответ модели для стенда: раздел «{про}» "
            "написан не поставщиком, а сервером web/e2e/fake-llm. Текст нужен "
            "только затем, чтобы прогон дошёл до конца и был виден на экране. "
            f"Проверяемое здесь — путь от кнопки до значения тега «{про}», "
            "а не содержание работы.")


def прозой(текст: str, теги: list[str]) -> str:
    """Ответ словами — когда схемы не просили вовсе (вопрос без формы)."""
    про = ", ".join(теги) if теги else "заданный вопрос"
    return (f"Поддельная модель отвечает про {про}. Сети и ключей на стенде "
            "нет: ответ собран сервером web/e2e/fake-llm по форме запроса. "
            "Одного абзаца достаточно, чтобы служба записала расход, закрыла "
            "прогон и отдала текст в поток SSE.")


def придумать(тело: dict) -> tuple[str, list[dict]]:
    """Что ответить на этот запрос. → (текст, вызовы инструментов)."""
    текст_запроса = промпт(тело)
    теги = имена_тегов(текст_запроса)

    формат = тело.get("response_format") or {}
    if формат.get("type") == "json_schema":
        схема = ((формат.get("json_schema") or {}).get("schema")) or {}
        return json.dumps(по_схеме(схема, теги), ensure_ascii=False), []

    выбор = тело.get("tool_choice")
    если_инструмент = (выбор.get("function") or {}).get("name") \
        if isinstance(выбор, dict) else None
    if если_инструмент:
        схема = _схема_инструмента(тело, если_инструмент)
        аргументы = json.dumps(по_схеме(схема, теги), ensure_ascii=False)
        return "", [{"id": "call_fake_1", "name": если_инструмент,
                     "arguments": аргументы}]

    схема = схема_из_описания(текст_запроса)
    if схема is not None:
        return json.dumps(по_схеме(схема, теги), ensure_ascii=False), []

    # Инструменты объявлены, но никого звать не заставляли (уровень 3): отвечаем
    # словами и тем заканчиваем петлю. Звать инструменты «за модель» подделке
    # нечем — их смысл она не знает, а угаданный вызов записал бы в проект чушь.
    return прозой(текст_запроса, теги), []


def _схема_инструмента(тело: dict, имя: str) -> dict:
    for инструмент in тело.get("tools") or []:
        функция = инструмент.get("function") or {}
        if функция.get("name") == имя:
            return функция.get("parameters") or {}
    return {}


# ── протокол ────────────────────────────────────────────────────────────────

def счётчики(тело: dict, ответ: str) -> dict:
    """`usage` по длине текста: цифры выдуманные, но связанные с запросом.

    Связанные намеренно: на сайте видно расход, и одинаковое число на любом
    прогоне выглядело бы как «расход не считается».
    """
    вход = max(1, len(промпт(тело)) // 3)
    выход = max(1, len(ответ) // 3)
    return {"prompt_tokens": вход, "completion_tokens": выход,
            "total_tokens": вход + выход,
            # Тот же путь, которым читается автокэш DeepSeek
            # (`openai_compat._usage_from`): пусть на стенде он тоже не пустой.
            "prompt_tokens_details": {"cached_tokens": 0}}


def кадр(тело: dict, дельта: dict, finish=None, usage=None) -> dict:
    кадр_ = {"id": "fake-chatcmpl", "object": "chat.completion.chunk",
             "created": int(time.time()), "model": тело.get("model") or "fake",
             "choices": [{"index": 0, "delta": дельта, "finish_reason": finish}]}
    if usage is not None:
        кадр_["usage"] = usage
    return кадр_


def куски(текст: str, размер: int):
    for i in range(0, len(текст), размер):
        yield текст[i:i + размер]


class Обработчик(BaseHTTPRequestHandler):
    """Один endpoint протокола `openai` и две вспомогательные ручки."""

    protocol_version = "HTTP/1.1"
    server_version = "koritsu-fake-llm"

    # ── ответы ──────────────────────────────────────────────────────────────
    def _json(self, код: int, тело: dict) -> None:
        данные = json.dumps(тело, ensure_ascii=False).encode("utf-8")
        self.send_response(код)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(данные)))
        self.send_header("x-request-id", "fake-req")
        self.end_headers()
        self.wfile.write(данные)

    def _отказ(self, код: int) -> None:
        """Отказ в форме поставщика: слой читает `error.message` (`_http_error`)."""
        if код == 429:
            # `Retry-After` маленький: политика повторов (`llm.transport.Retry`)
            # его слушается, и без него стенд ждал бы секунды на ровном месте.
            self.send_response(429)
            self.send_header("Retry-After", "1")
            тело = {"error": {"message": "поддельный отказ: слишком часто "
                                         "([[FAKE:429]])", "type": "rate_limit"}}
            данные = json.dumps(тело, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(данные)))
            self.end_headers()
            self.wfile.write(данные)
            return
        self._json(код, {"error": {"message": f"поддельная беда {код} "
                                              f"([[FAKE:{код}]])",
                                   "type": "server_error"}})

    def _поток(self, тело: dict, текст: str, вызовы: list[dict]) -> None:
        """SSE, как его шлёт совместимый сервер: кадры, `[DONE]`, `usage` в конце.

        Обрыв на той стороне — не беда, а обычный исход: отмена задания у
        Koritsu и есть закрытие потока (`llm.transport`, А.4). Ловим и молчим,
        иначе журнал стенда заполняется трассировками ровно там, где всё
        сработало как задумано.
        """
        try:
            self._поток_кадрами(тело, текст, вызовы)
        except (BrokenPipeError, ConnectionResetError):
            print("[fake-llm] поток закрыт с той стороны (отмена?)", flush=True)

    def _поток_кадрами(self, тело: dict, текст: str, вызовы: list[dict]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("x-request-id", "fake-req")
        # Длину потока заранее не знает никто — только `chunked`.
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def послать(кадр_: dict) -> None:
            строка = f"data: {json.dumps(кадр_, ensure_ascii=False)}\n\n".encode()
            self.wfile.write(f"{len(строка):X}\r\n".encode())
            self.wfile.write(строка + b"\r\n")
            self.wfile.flush()

        послать(кадр(тело, {"role": "assistant", "content": ""}))
        for кусок in куски(текст, КУСОК):
            time.sleep(ЗАДЕРЖКА_МС / 1000)
            послать(кадр(тело, {"content": кусок}))
        for номер, вызов in enumerate(вызовы):
            # Имя приходит один раз, аргументы — по кускам: ровно так их
            # склеивает `openai_compat._accumulate_call`, и склейку эту тоже
            # надо проверять настоящую.
            послать(кадр(тело, {"tool_calls": [
                {"index": номер, "id": вызов["id"], "type": "function",
                 "function": {"name": вызов["name"], "arguments": ""}}]}))
            for кусок in куски(вызов["arguments"], КУСОК):
                time.sleep(ЗАДЕРЖКА_МС / 1000)
                послать(кадр(тело, {"tool_calls": [
                    {"index": номер, "function": {"arguments": кусок}}]}))
        finish = "tool_calls" if вызовы else "stop"
        послать(кадр(тело, {}, finish=finish,
                     usage=счётчики(тело, текст or json.dumps(вызовы))))
        конец = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(конец):X}\r\n".encode() + конец + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _поток_с_бедой(self, тело: dict) -> None:
        """200, кадр текста — и ошибка полем внутри потока (так делают шлюзы)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for кадр_ in (кадр(тело, {"role": "assistant", "content": "начало ответа…"}),
                      {"error": {"message": "поддельная беда внутри потока "
                                            "([[FAKE:ERR]])", "code": 500}}):
            строка = f"data: {json.dumps(кадр_, ensure_ascii=False)}\n\n".encode()
            self.wfile.write(f"{len(строка):X}\r\n".encode() + строка + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")

    # ── маршруты ────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                                # noqa: N802
        путь = self.path.split("?")[0].rstrip("/")
        if путь in ("/health", ""):
            self._json(200, {"status": "ok", "server": "fake-llm"})
        elif путь == "/v1/models":
            # Первый шаг пробы (`python -m llm probe`) спрашивает список моделей.
            self._json(200, {"object": "list",
                             "data": [{"id": "deepseek-chat", "object": "model"},
                                      {"id": "fake-model", "object": "model"}]})
        else:
            self._json(404, {"error": {"message": f"нет такой ручки: {путь}"}})

    def do_POST(self) -> None:                               # noqa: N802
        путь = self.path.split("?")[0].rstrip("/")
        длина = int(self.headers.get("Content-Length") or 0)
        сырое = self.rfile.read(длина) if длина else b"{}"
        try:
            тело = json.loads(сырое.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._json(400, {"error": {"message": "тело запроса — не JSON"}})
            return
        if путь not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": {"message": f"нет такой ручки: {путь}"}})
            return

        просят = маркер(тело)
        if просят in ("429", "500", "502", "503"):
            self._сказать(тело, f"отказ {просят} по маркеру")
            self._отказ(int(просят))
            return
        if просят == "ERR":
            self._сказать(тело, "беда внутри потока по маркеру")
            self._поток_с_бедой(тело)
            return

        текст, вызовы = придумать(тело)
        self._сказать(тело, f"{len(текст)} знаков"
                            + (f", вызовов {len(вызовы)}" if вызовы else ""))
        if тело.get("stream"):
            self._поток(тело, текст, вызовы)
            return
        # Непотоковый ответ нужен пробе (шаг 2) и любому, кто спросит без
        # `stream`: форма другая, содержание то же.
        сообщение: dict = {"role": "assistant", "content": текст or None}
        if вызовы:
            сообщение["tool_calls"] = [
                {"id": в["id"], "type": "function",
                 "function": {"name": в["name"], "arguments": в["arguments"]}}
                for в in вызовы]
        self._json(200, {
            "id": "fake-chatcmpl", "object": "chat.completion",
            "created": int(time.time()), "model": тело.get("model") or "fake",
            "choices": [{"index": 0, "message": сообщение,
                         "finish_reason": "tool_calls" if вызовы else "stop"}],
            "usage": счётчики(тело, текст)})

    # ── журнал ──────────────────────────────────────────────────────────────
    def _сказать(self, тело: dict, что: str) -> None:
        теги = имена_тегов(промпт(тело))
        print(f"[fake-llm] {self.command} {self.path} "
              f"теги={','.join(теги) or '—'} поток={bool(тело.get('stream'))} "
              f"→ {что}", flush=True)

    def log_message(self, формат, *args):                    # noqa: N802
        """Обычный журнал http.server молчит: свои строки печатает `_сказать`,
        а каждый запрос дважды в логе стенда только мешает читать."""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="fake-llm", description="поддельная модель для стенда сайта")
    ap.add_argument("--host", default=os.environ.get("FAKE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("FAKE_PORT") or 8016))
    args = ap.parse_args(argv)

    сервер = ThreadingHTTPServer((args.host, args.port), Обработчик)
    print(f"[fake-llm] слушаю http://{args.host}:{args.port} "
          f"(куски по {КУСОК} знаков, задержка {ЗАДЕРЖКА_МС} мс)", flush=True)
    try:
        сервер.serve_forever()
    except KeyboardInterrupt:
        print("[fake-llm] остановлен", flush=True)
    finally:
        сервер.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
