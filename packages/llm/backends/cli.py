"""
backends.cli — модель зовётся командой `claude`, а не по HTTP.

**Это временный бэкенд для проб, а не боевой.** Он существует по одной причине
(решение владельца 2026-08-31): ключа к API нет, а пробовать надо уже сейчас, и
подписка Claude Code — единственный доступный путь к модели. Всё, что ниже,
написано с оглядкой на то, что путь этот кривой и его придётся выбросить, как
только появится ключ.

Почему кривой — три вещи, каждой из которых хватило бы:

  * **между нами и моделью сидит агент.** `claude -p` — это не тонкий клиент к
    Messages API, а Claude Code с собственным системным промптом, собственными
    служебными обращениями к модели и собственными инструментами. Его расход
    неотделим от нашего в его же отчёте (см. «Учёт» ниже);
  * **у него есть руки.** Инструменты, файловая система, сеть. А в промпт едет
    недоверенный текст студента. Поэтому половина этого файла — про то, как
    руки отобрать (см. «Безопасность»);
  * **гарантий формата нет.** Ступень лестницы здесь честно последняя, `text`
    (см. «Структурированный вывод»).

Что проверено ЖИВЫМ вызовом 2026-08-31 (и потому написано как знание), помечено
словом «проверено». Всё прочее — заявка.

── Как устроен вызов ────────────────────────────────────────────────────────

    claude -p --output-format json --model <модель>
           --tools "" --restricted --strict-mcp-config
           --setting-sources "" --disable-slash-commands
           --no-session-persistence
           --system-prompt-file <файл во временном каталоге>
    промпт — в stdin, рабочий каталог — свежий временный, окружение — по списку

Промпт идёт **в stdin, а не в argv**, и это не вкусовщина. Наш промпт — манифест
плюс материалы, десятки килобайт, а один аргумент argv в Linux ограничен
`MAX_ARG_STRLEN` = 128 КиБ (проверено: `/bin/true` с аргументом в 130 000 байт
запускается, с 200 000 — `OSError: Argument list too long`, при том что общий
`ARG_MAX` равен 2 МиБ и на глаз кажется достаточным). Системная часть раскладки
по той же причине едет **файлом** (`--system-prompt-file`), а не аргументом:
манифест сам по себе может перевалить за тот же потолок. Проверено: stdin
читается, `--system-prompt-file` существует и работает, хотя в `--help` его нет.

── Безопасность ─────────────────────────────────────────────────────────────

`--tools ""` — «disable all tools» из встроенного набора. Проверено: на просьбу
прочитать соседний файл модель отвечает «НЕТ ИНСТРУМЕНТОВ», `permission_denials`
пуст, `num_turns` = 1.

`--disallowed-tools '*'` здесь НЕ используется намеренно, хотя первая проба
владельца шла с ним. Этот параметр — список правил запрета для системы
разрешений («Bash(git *)», «Edit»), а не выключатель набора инструментов, и то,
что `*` совпадёт с именем каждого, нигде не обещано. Незаявленная защита, которая
выглядит защитой, хуже отсутствующей: с ней перестают искать настоящую. Набор
выключается `--tools ""`, а `--restricted` вдобавок убирает всё, что запускает
команды и код, запирает файловые инструменты в рабочих каталогах и отказывается
от `bypassPermissions`.

`--dangerously-skip-permissions` не используется никогда и в этом файле не
упоминается больше нигде.

`--strict-mcp-config` (никаких чужих MCP-серверов), `--setting-sources ""` (ни
пользовательские, ни проектные, ни локальные настройки), `--disable-slash-commands`
(никаких навыков), `--no-session-persistence` (разговор не ложится на диск).

Рабочий каталог — **свежий временный**, а не репозиторий пользователя: даже если
однажды какой-то инструмент проскочит, смотреть ему будет не на что. Туда же
уезжает `TMPDIR`, и каталог убирается всегда — и на таймауте, и на отмене.

Окружение собирается по **списку разрешённого**, а не вычитанием запрещённого:
список запрещённого устаревает молча. Переменные `CLAUDE*` родительского
процесса не передаются вовсе — они говорят подпроцессу, что он внутри агентской
сессии; единственная, которую мы ставим сами, — потолок вывода (ниже).

`permission_denials` — тревога, а не запись в журнал. У нас инструментов нет,
значит непустой список означает не «попытку отбили», а «наши предположения о
поведении команды устарели». Такой ответ **не принимается**: наружу уходит
ошибка `unsupported`, потому что тихо взять ответ у агента, который лез не туда,
— ровно тот молчаливый дефект, ради которого всё остальное и написано.

── Учёт: что мы пишем в Usage и почему ──────────────────────────────────────

Замеры (проверено, короткий промпт в 10 токенов):

    без --system-prompt-file: usage.input_tokens 10, cache_creation 8071,
                              modelUsage.inputTokens 916, $0.0174
    с    --system-prompt-file: usage.input_tokens 252, cache_creation 0,
                              modelUsage.inputTokens 1151, $0.0016

Первая строка и есть то самое загрязнение: 8071 токена — это собственный
системный промпт Claude Code, а не наш. **Главное лечение сделано у источника, а
не в арифметике**: `--system-prompt-file` не дописывает к её промпту, а заменяет
его целиком, и загрязнение из восьми тысяч токенов исчезает вместе с ним. Один
пустяковый вызов подешевел в одиннадцать раз.

Остаётся два хвоста, которые убрать нечем:

  * ~250 токенов на вызов — то, что Claude Code добавляет к нашему системному
    промпту сама (окружение, служебная обвязка);
  * ~900 токенов на вызов — её собственные обращения к модели помимо нашего
    хода. Видны как разница `modelUsage.inputTokens − usage.input_tokens`.

Решение принято такое:

  **`Usage` считает вызов подпроцесса ЦЕЛИКОМ и складывается из `modelUsage` —
  той самой ведомости, из которой сама Claude Code считает `total_cost_usd`.**

То есть в `input` попадает и наш промпт, и служебные обращения посредника. Так
сделано потому, что альтернатива — записать только наш ход (`usage.input_tokens`)
— это молчаливое ЗАНИЖЕНИЕ: деньги за служебные обращения потрачены настоящие,
а лимит их бы не увидел, и расход утёк бы мимо учёта — та же дыра, которую
докстрока `Backend.stream` объявляет закрытой для отменённых вызовов.

Чтобы занижения не сменить завышением молчаливым, сказано вслух в трёх местах:

  1. `Declared.usage_contaminated = True` → в `degraded` **каждой** записи
     журнала появляется пометка `usage_with_agent_overhead`. Поле `degraded` для
     того и заведено — «объяснение цифр в журнале»;
  2. `raw_usage["учёт_koritsu"]` — разбор той же суммы на части: сколько в ней
     нашего хода, сколько накладных посредника, сколько его кэша. Вычесть
     обратно есть чем, и задним числом тоже;
  3. `raw_usage` рядом хранит счётчики команды дословно, её `total_cost_usd` и
     `session_id`.

Цены у пресета намеренно **не заполнены**, и потому `Result.cost` равен `None`
(«деньги по этому endpoint'у не считаем»). Причина не в лени: платится здесь не
за токены, а подпиской, и табличка «цена за миллион» описывала бы не ту сделку,
которая происходит. Настоящая цифра, посчитанная самой командой, лежит в
`raw_usage` под своим именем и ни на что не притворяется.

Отдельно про `own_key`: пресет ставит `own_key=True`. Расход идёт по подписке
владельца, а не против тарифа продукта, — журнал такой расход считает и
показывает, но в лимит не берёт (см. `Journal.total_units`).

── Структурированный вывод ──────────────────────────────────────────────────

Ступень честная последняя — `text`. Не потому, что лень: у команды есть
`--json-schema`, и он работает (проверено: вернулся `{"done":true,"count":3}` и
разобранный объект в поле `structured_output`). Но:

  * внутри он реализован **инструментом**, и схема уезжает как `input_schema`
    инструмента. А ключи свойств такой схемы Anthropic принимает только по
    шаблону `^[a-zA-Z0-9_.-]{1,64}$` (проверено: 400 «Property keys should match
    pattern»). Ключи нашей схемы отчёта — это имена тегов шаблона, то есть
    кириллица (`{{цель}}`, `{{схема}}`, `{{выводы}}`). Значит на боевой схеме
    Koritsu этот путь отказывает целиком, а не иногда;
  * без схемы модель заворачивает ответ в забор ```json (проверено владельцем
    2026-08-30 на просьбе «верни ровно этот JSON и ничего больше»).

Забор снимает `structured.extract_json` — третьего разбора здесь нет и не будет.
Свой ответ команда отдаёт полем `result`; оно уходит одним куском `text`, и
дальше всё как у прочих: `run_ladder` разбирает, валидатор проверяет, повторы
считаются в расход.

── Чего этот бэкенд не умеет ────────────────────────────────────────────────

Не «пока не написано», а не умеет по устройству:

  * **инструменты** (`Request.tools`, ступень `tool_strict`) и **историю**
    обмена. Инструменты у команды свои, наши ей передать нечем; ход всегда один.
    Попытка — громкий отказ `unsupported`, а не молчаливое игнорирование;
  * **температуру** и **stop-последовательности** — флагов нет. Тоже отказ:
    вызывающий их задал явно, и сделать вид, что задали, нельзя;
  * **кэш префикса** — никакого. Проверено: с нашим системным промптом
    `cache_creation` и `cache_read` равны нулю, брейкпойнт поставить нечем.
    Значит весь манифест с материалами оплачивается полностью на каждом вызове;
  * **потоковость** — объявлена `False`. `--output-format stream-json` у команды
    есть, но это её собственный агентский протокол событий (сообщения, вызовы
    инструментов, подзадачи), а не поток модели; брать его сейчас значит завести
    третий разбор событий ради ответа, который и так приезжает разом. Наружу
    поток остаётся рабочим: `Backend.stream` отдаёт один кусок `text`, следом
    usage и stop — инвариант конца потока тот же, что у обоих HTTP-бэкендов;
  * **`effort`** — флаг `--effort` у команды есть, живьём не проверялся, и
    объявлен `False`. Любопытное наблюдение мимо: Haiku тратит токены на
    размышления и без нашей просьбы (52–288 `thinking_tokens` в замерах), так что
    «без thinking, просто api» здесь не выполняется в принципе;
  * **точный подсчёт токенов до отправки** — `count_tokens` нет, работает
    эвристика по символам;
  * **проба Б.4** — она построена на POST по HTTP, которого тут нет вовсе.
    Поэтому возможности заполнены рукой по живым замерам, а `probing.probe`
    отказывается честно и сразу.

Потолок вывода (`Request.max_tokens`) **соблюдается** — через переменную
окружения `CLAUDE_CODE_MAX_OUTPUT_TOKENS` (проверено: при значении 24 команда
вернула `is_error: true` и текст «Claude's response exceeded the 24 output token
maximum»). Такой исход приводится к `Stop.MAX_TOKENS`, и лестница отвечает на
него как положено — «нужен больший max_tokens, а не повтор». Цена: недописанный
ответ при этом теряется, команда отдаёт вместо него текст ошибки.

── Повторы ──────────────────────────────────────────────────────────────────

HTTP-кода тут нет, есть код возврата процесса, таймаут и текст ошибки. Повтор
здесь безопаснее, чем у потока по проводу: наружу до конца процесса не уходит ни
одного куска, значит повторяется всё или ничего — печатать дважды нечего.

Повторяется ровно два случая: наш таймаут и ошибка, в тексте которой команда
назвала код («API Error: 429», «API Error: 503») — код читается тем же
`kind_from_status`, что и у HTTP, и `LlmError.retryable` сам решает, стоит ли.
Всё остальное — `bad_response`: команда ходит к API сама и свои временные беды
уже перепробовала, а к нам приезжает её приговор. Повторять приговор значит
второй раз оплатить весь системный промпт.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from ..errors import ErrorKind, LlmError, Stop, kind_from_status, looks_like_overflow
from ..model import Chunk, Structured
from ..transport import Cancelled, Retry
from .. import layout
from .base import Backend, Request

# Постоянная часть командной строки. Данные, а не ветвление: что здесь написано,
# владелец мог бы набрать руками, и каждый флаг объяснён в разделе
# «Безопасность» докстроки модуля.
ФЛАГИ = (
    "-p",
    "--output-format", "json",
    "--tools", "",                 # встроенных инструментов нет вовсе
    "--restricted",                # и запускать команды/код тоже нечем
    "--strict-mcp-config",         # чужих MCP-серверов нет
    "--setting-sources", "",       # ни пользовательских, ни проектных настроек
    "--disable-slash-commands",    # навыков нет
    "--no-session-persistence",    # разговор не ложится на диск
)

# Переменные окружения, которые подпроцесс получает. Список РАЗРЕШЁННОГО:
# список запрещённого устаревает молча, и первая же новая переменная проедет.
# HOME нужен для входа по подписке, сертификатные и прокси-переменные — чтобы
# команда вообще дошла до сети в чужой сети.
ОКРУЖЕНИЕ = (
    "HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
)
# Ключ к API, если он всё-таки есть: тогда команда возьмёт его вместо подписки.
ОКРУЖЕНИЕ_ПРЕФИКСЫ = ("ANTHROPIC_",)

# Переменная, которой команда ограничивает длину ответа. Единственная из
# семейства CLAUDE*, которую мы ставим; родительские в подпроцесс не едут.
ПОТОЛОК_ВЫВОДА = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"

# Промпт-замена: он нужен не ради содержания, а ради того, чтобы собственный
# системный промпт Claude Code был ЗАМЕНЁН, а не дополнен. Пустой файл оставил
# бы неясным, что она подставит вместо него. Бизнес-правил тут нет и быть не
# должно — они приезжают куском раскладки с ролью `rules`.
ЗАМЕНА_ПРОМПТА = ("Ты — языковая модель, которую вызывает Koritsu. "
                  "Инструментов, файлов и сети у тебя нет: отвечай только текстом.")

# Как часто спрашиваем отмену, пока процесс идёт, и сколько ждём после сигнала.
ОПРОС_С = 0.1
ДОБИТЬ_С = 3.0

_КОД_ОШИБКИ = re.compile(r"API Error:?\s*(\d{3})")

# Причины остановки: команда пропускает наружу stop_reason Anthropic, но своих
# значений у неё тоже хватает. Своя табличка, а не общая с бэкендом anthropic:
# наборы разные, и общая означала бы, что правку одного проверяют на другом.
_ОСТАНОВКА = {
    "end_turn": Stop.END_TURN,
    "stop_sequence": Stop.END_TURN,
    "max_tokens": Stop.MAX_TOKENS,
    "tool_use": Stop.TOOL_USE,
    "refusal": Stop.REFUSED,
}


def _остановка(reason) -> str | None:
    if not reason:
        return None
    return _ОСТАНОВКА.get(reason, Stop.END_TURN)


def _это_потолок_вывода(text: str) -> bool:
    """Ошибка «ответ длиннее потолка» — это исход max_tokens, а не беда.

    Отличать обязательно: лестница на `Stop.MAX_TOKENS` отвечает «нужен больший
    max_tokens, а не повтор», а на обычной ошибке пошла бы повторять — и
    обрезала бы ответ в том же месте за вторые деньги.
    """
    low = (text or "").lower()
    return "output token maximum" in low or ПОТОЛОК_ВЫВОДА.lower() in low


class CliRunner:
    """Замена транспорта для протокола без сети: провод здесь — труба подпроцесса.

    Занимает то же место, что `Transport` у HTTP-бэкендов, и по той же причине:
    механика провода (запуск, таймаут, отмена, уборка) отделена от смысла
    ответа. Смысл разбирает бэкенд — он же и решает, повторять ли, потому что
    «повторять ли» читается из текста ошибки, а текст — это уже смысл.

    Записки о повторах и идентификатор ответа копятся по потокам исполнения,
    ровно как в `Transport`: забирает их тот, кто сделал вызов, иначе чужой
    повтор припишется чужому ходу.
    """

    def __init__(self, command: str = "claude", retry: Retry | None = None, on_retry=None):
        self.command = command or "claude"
        self.retry = retry or Retry()
        self._on_retry = on_retry
        self._local = threading.local()

    # ── что забирает вызывающий ─────────────────────────────────────────────
    def take_retries(self) -> list:
        notes = getattr(self._local, "notes", None)
        self._local.notes = []
        return notes or []

    def take_request_id(self) -> str | None:
        value = getattr(self._local, "request_id", None)
        self._local.request_id = None
        return value

    def note_request_id(self, request_id) -> None:
        """Идентификатор вызова. У команды это `session_id` — единственное, что
        можно предъявить при разборе «списали, а ответа нет»."""
        self._local.request_id = request_id

    def note_retry(self, attempt: int, delay: float, error: LlmError, where: str) -> None:
        note = {"attempt": attempt, "delay_s": round(delay, 3), "kind": error.kind,
                "status": error.status, "request_id": error.request_id,
                "path": where, "reason": (error.message or "")[:200]}
        notes = getattr(self._local, "notes", None)
        if notes is None:
            notes = self._local.notes = []
        notes.append(note)
        if len(notes) > 20:
            del notes[:-20]
        if self._on_retry is not None:
            self._on_retry(note)

    # ── сам запуск ──────────────────────────────────────────────────────────
    def executable(self) -> str | None:
        """Путь к команде или None. Отдельным методом, чтобы «команды нет»
        отвечалось `not_found` до всякой временной возни, а не падало OSError."""
        if os.path.sep in self.command:
            return self.command if os.access(self.command, os.X_OK) else None
        return shutil.which(self.command)

    def run_once(self, argv, stdin_text: str, cwd: str, env: dict, timeout_s: float,
                 cancel=None, endpoint_id: str = "") -> tuple:
        """Одна попытка. Возвращает (код возврата, stdout, stderr).

        Читать трубы приходится в отдельном потоке, а не после `wait()`: ответ
        бывает и в сотни килобайт, труба переполняется на 64 КиБ, и подпроцесс
        встанет насмерть, дожидаясь, пока мы прочитаем, — а мы будем ждать, пока
        он закончится. Главный поток тем временем опрашивает отмену и срок.

        Подпроцесс запускается в **своей группе процессов** (`start_new_session`)
        и добивается по группе: команда — это node, который запускает своих
        детей, и убитый в одиночку родитель оставил бы их держать трубы.
        """
        try:
            proc = subprocess.Popen(
                list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=cwd, env=dict(env), text=True,
                encoding="utf-8", errors="replace", start_new_session=True)
        except OSError as exc:
            raise LlmError(ErrorKind.NOT_FOUND,
                           f"не удалось запустить {argv[0]!r}: {exc}",
                           endpoint=endpoint_id)

        итог: dict = {}

        def перекачать():
            try:
                итог["out"], итог["err"] = proc.communicate(input=stdin_text)
            except BaseException as exc:            # noqa: BLE001 — уносим наружу
                итог["exc"] = exc

        поток = threading.Thread(target=перекачать, daemon=True)
        поток.start()
        срок = time.monotonic() + float(timeout_s)
        while True:
            поток.join(ОПРОС_С)
            if not поток.is_alive():
                break
            if cancel is not None and cancel():
                self._добить(proc, поток)
                raise Cancelled()
            if time.monotonic() >= срок:
                self._добить(proc, поток)
                raise LlmError(ErrorKind.TIMEOUT,
                               f"команда {self.command!r} не уложилась в {timeout_s:g} с",
                               endpoint=endpoint_id)
        if "exc" in итог:
            raise LlmError(ErrorKind.TRANSPORT,
                           f"не удалось прочитать вывод команды: {итог['exc']}",
                           endpoint=endpoint_id)
        return proc.returncode, итог.get("out") or "", итог.get("err") or ""

    @staticmethod
    def _добить(proc, поток) -> None:
        """Сначала по-хорошему всей группе, потом насмерть. Ошибки глотаем:
        процесс мог закончиться сам между проверкой и сигналом."""
        for сигнал in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(proc.pid), сигнал)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
            поток.join(ДОБИТЬ_С if сигнал == signal.SIGTERM else 1.0)
            if not поток.is_alive():
                return


class CliBackend(Backend):
    """Бэкенд протокола `cli`. Разбор смысла ответа и решение о повторе.

    `spec.base_url` здесь — **имя или путь команды** (обычно `claude`): у этого
    протокола «куда идти» и есть команда. Ключ не нужен и не спрашивается —
    вход у команды свой, по подписке.
    """

    protocol = "cli"
    # Пусто намеренно: probing.probe спрашивает именно это, чтобы понять, есть
    # ли у бэкенда непотоковый POST, на котором вся проба Б.4 и держится.
    complete_path = ""
    stream_path = ""

    def headers(self) -> dict:
        """HTTP тут нет, заголовков тоже. Метод существует ради контракта базы."""
        return {}

    def transport(self):
        """«Транспорт» протокола cli — запускатель подпроцесса.

        Подменяется снаружи ровно так же, как httpx-клиент у HTTP-бэкендов
        (`register_endpoint(spec, transport=...)`), и ради того же: тесты не
        должны звать настоящую команду — это деньги и секунды.
        """
        if self._transport is None:
            self._transport = CliRunner(command=self.spec.base_url)
        return self._transport

    def supported_step(self, wanted: str) -> str:
        """Ниже заявленного не поднимаемся; заявлено `text` (см. докстроку)."""
        declared = self.spec.probe.structured_output or self.spec.declared.structured_output
        floor = Structured.rank(declared if declared != Structured.NONE else Structured.TEXT)
        return Structured.LADDER[max(Structured.rank(wanted), floor)]

    def parse_response(self, payload: dict):
        raise LlmError(ErrorKind.UNSUPPORTED,
                       "у протокола cli нет непотокового ответа: команда запускается "
                       "один раз и её вывод разбирает iter_stream",
                       endpoint=self.spec.id)

    # ── сборка вызова ───────────────────────────────────────────────────────
    def build_body(self, request: Request, stream: bool = True) -> dict:
        """Раскладка Б.5 → что именно мы запустим. «Тело» здесь — план запуска.

        Отказы тут громкие и это осознанно: возможности, которых у команды нет,
        нельзя молча проглотить. Вызывающий, попросивший инструмент или
        температуру, должен получить отказ, а не ответ, посчитанный не по его
        просьбе (записка, раздел 0: молчаливая деградация — худший класс).
        """
        if request.tools or request.structured_step == Structured.TOOL_STRICT:
            raise LlmError(ErrorKind.UNSUPPORTED,
                           "endpoint через команду claude не принимает наши инструменты: "
                           "у неё свои, и передать ей чужие нечем",
                           endpoint=self.spec.id)
        if request.history:
            raise LlmError(ErrorKind.UNSUPPORTED,
                           "endpoint через команду claude ведёт ровно один ход: "
                           "истории обмена ей не передать",
                           endpoint=self.spec.id)
        if request.temperature is not None:
            raise LlmError(ErrorKind.UNSUPPORTED,
                           "у команды claude нет параметра температуры",
                           endpoint=self.spec.id)
        if request.stop_sequences:
            raise LlmError(ErrorKind.UNSUPPORTED,
                           "у команды claude нет stop-последовательностей",
                           endpoint=self.spec.id)

        system_parts, user_parts = layout.split(request.parts)
        # Метка рамки одна на весь запрос — куски рендерятся по одному, и метка,
        # взятая покусочно, разъедется между ними (см. Backend.request_mark).
        mark = self.request_mark(request)
        системное = "\n\n".join(
            [ЗАМЕНА_ПРОМПТА] + [layout.render_text(p, mark) for p in system_parts])
        промпт = "\n\n".join(layout.render_text(p, mark) for p in user_parts)
        return {
            "model": self.spec.model,
            "system": системное,
            "prompt": промпт or ".",
            "max_output_tokens": max(1, int(request.max_tokens)),
        }

    def child_env(self, work_dir: str, body: dict) -> dict:
        """Окружение подпроцесса: список разрешённого плюс два наших значения."""
        env = {name: value for name, value in os.environ.items()
               if name in ОКРУЖЕНИЕ
               or any(name.startswith(p) for p in ОКРУЖЕНИЕ_ПРЕФИКСЫ)}
        # Временные файлы команды — в тот же каталог, который мы уберём.
        env["TMPDIR"] = work_dir
        env[ПОТОЛОК_ВЫВОДА] = str(body["max_output_tokens"])
        return env

    # ── запуск и повторы ────────────────────────────────────────────────────
    def open_events(self, body: dict, cancel=None):
        """Один запуск команды → одно событие с её разобранным JSON.

        Генератор, а не готовый список: тело выполнится внутри `try` в
        `Backend.stream`, и отмена с ошибкой уедут наружу тем же путём, что у
        HTTP-бэкендов, — иначе конец потока пришлось бы описывать второй раз.
        """
        yield ("result", self._запустить(body, cancel))

    def _запустить(self, body: dict, cancel) -> dict:
        """Запуск с повторами. Повторять безопасно: наружу до конца процесса не
        ушло ни одного куска, значит повторяется всё или ничего — печатать
        дважды нечего, и правило «после первого отданного события не повторяем»
        (Transport.stream_sse) здесь просто не наступает.

        Беда приезжает двумя разными дорогами, и обе обязаны попадать в повтор:

          * исключением — команду не запустить, наш таймаут, вывод не разобрать;
          * **внутри разобранного JSON** — ненулевой код возврата и
            `is_error: true` с текстом «API Error: 429». Это самая частая
            дорога, и повторять по ней надо ровно так же: беда та же самая,
            просто приехала полем, а не кодом. Проверять `retryable` только у
            исключений значило бы, что 429 не повторяется никогда.

        Что именно повторяемо, решает `LlmError.retryable` — своего списка видов
        здесь нет, два места правды разъехались бы за месяц.
        """
        runner = self.transport()
        retry = getattr(runner, "retry", None) or Retry()
        начало = retry.monotonic()
        попытка = 0
        while True:
            попытка += 1
            try:
                payload = self._попытка(body, cancel, runner)
            except Cancelled:
                raise
            except LlmError as exc:
                задержка = retry.delay_for(exc, попытка, начало)
                if задержка is None:
                    raise
                runner.note_retry(попытка, задержка, exc, self.spec.base_url)
                retry.sleep(задержка)
                continue
            беда = self._беда(payload)
            if беда is None:
                return payload
            задержка = retry.delay_for(беда, попытка, начало)
            if задержка is None:
                # Повторять нечего — отдаём ответ как есть. Разберёт его
                # `iter_stream`: там же лежат и счётчики неудачного вызова, а
                # они потрачены настоящие и в журнал попасть обязаны.
                return payload
            runner.note_retry(попытка, задержка, беда, self.spec.base_url)
            retry.sleep(задержка)

    def _попытка(self, body: dict, cancel, runner) -> dict:
        exe = runner.executable()
        if not exe:
            raise LlmError(ErrorKind.NOT_FOUND,
                           f"команда {self.spec.base_url!r} не найдена — этот endpoint "
                           f"работает только через неё",
                           endpoint=self.spec.id)
        runner.note_request_id(None)
        # Каталог свой на каждую попытку и убирается всегда — в том числе на
        # таймауте и отмене (там наружу летит исключение прямо изнутри with).
        with tempfile.TemporaryDirectory(prefix="llm_cli_") as work_dir:
            файл_промпта = os.path.join(work_dir, "system.txt")
            with open(файл_промпта, "w", encoding="utf-8") as fh:
                fh.write(body["system"])
            argv = ([exe] + list(ФЛАГИ)
                    + ["--model", body["model"], "--system-prompt-file", файл_промпта])
            код, out, err = runner.run_once(
                argv, body["prompt"], work_dir, self.child_env(work_dir, body),
                self.spec.timeout_s, cancel=cancel, endpoint_id=self.spec.id)
        return self._разобрать(код, out, err)

    def _разобрать(self, код: int, out: str, err: str) -> dict:
        """stdout команды → её JSON. Ошибка внутри JSON сюда не относится.

        Разделение важное: ненулевой код возврата с разобранным JSON — обычное
        дело (так приезжает ошибка API), и решает её `iter_stream`. Сюда
        попадает только то, после чего разбирать нечего.
        """
        текст = (out or "").strip()
        if not текст:
            хвост = (err or "").strip()[-400:]
            raise LlmError(ErrorKind.BAD_RESPONSE,
                           f"команда claude завершилась с кодом {код} и ничего не "
                           f"напечатала" + (f": {хвост}" if хвост else ""),
                           endpoint=self.spec.id)
        try:
            payload = json.loads(текст)
        except (ValueError, json.JSONDecodeError) as exc:
            raise LlmError(ErrorKind.BAD_RESPONSE,
                           f"вывод команды claude не JSON (код {код}, {exc}): "
                           f"{текст[:300]}",
                           endpoint=self.spec.id)
        if not isinstance(payload, dict):
            raise LlmError(ErrorKind.BAD_RESPONSE,
                           f"вывод команды claude — не объект, а {type(payload).__name__}",
                           endpoint=self.spec.id)
        return payload

    # ── разбор ответа ───────────────────────────────────────────────────────
    def iter_stream(self, events, state: dict):
        """JSON команды → наши Chunk'и.

        Порядок проверок содержательный: сначала счётчики (расход состоялся, чем
        бы дело ни кончилось, и обязан попасть в state ДО любого выхода —
        ровно та же причина, что расписана в `AnthropicBackend.iter_stream`),
        потом тревога о разрешениях, потом ошибка, и только потом текст.
        """
        for _name, payload in events:
            self._счётчики(state, payload)
            self.transport().note_request_id(payload.get("session_id") or None)

            denials = payload.get("permission_denials") or []
            if denials:
                # Инструментов у подпроцесса нет — значит попыток их звать быть
                # не могло. Раз они есть, наши предположения о команде устарели,
                # и ответ такого прогона брать нельзя.
                yield Chunk(kind="error", raw={"permission_denials": denials},
                            error=LlmError(
                                ErrorKind.UNSUPPORTED,
                                f"команда claude сообщила о попытках вызвать инструменты "
                                f"({len(denials)} шт.), хотя инструменты выключены; "
                                f"ответ не принят",
                                endpoint=self.spec.id,
                                raw={"permission_denials": denials}))
                return

            if payload.get("is_error"):
                беда = self._беда(payload)
                if беда is None:
                    # Не беда, а исход: ответ упёрся в потолок вывода. Лестница
                    # знает, что лечится это большим max_tokens, а не повтором.
                    state["stop"] = Stop.MAX_TOKENS
                    return
                yield Chunk(kind="error", raw={"result": self._текст(payload)},
                            error=беда)
                return

            результат = self._текст(payload)
            state["stop"] = _остановка(payload.get("stop_reason"))
            if результат:
                state["text_chars"] = state.get("text_chars", 0) + len(результат)
                yield Chunk(kind="text", text=результат)

    def _счётчики(self, state: dict, payload: dict) -> None:
        """Счётчики команды → наш Usage, и разбор загрязнения рядом с ними.

        Считаем по `modelUsage` — ведомости, из которой сама команда считает
        `total_cost_usd`: там весь расход вызова, включая её служебные обращения
        к модели. Почему именно так — раздел «Учёт» в докстроке модуля.

        Если счётчиков нет вовсе, `raw_usage` остаётся ПУСТЫМ, и это не
        небрежность: `Backend.stream` по пустому raw_usage включает запасной
        подсчёт (В.3). Положи туда что-нибудь — и вместо оценки в журнал уедет
        нулевой расход, то есть бесплатный вызов.
        """
        ход = payload.get("usage") or {}
        ведомость = payload.get("modelUsage") or {}
        вход = выход = чтение = запись = 0
        for строка in ведомость.values():
            if not isinstance(строка, dict):
                continue
            вход += int(строка.get("inputTokens") or 0)
            выход += int(строка.get("outputTokens") or 0)
            чтение += int(строка.get("cacheReadInputTokens") or 0)
            запись += int(строка.get("cacheCreationInputTokens") or 0)
        if not ведомость:
            # Ведомости нет — берём счётчики хода: они беднее (служебных
            # обращений в них не видно), но это лучше, чем ничего.
            вход = int(ход.get("input_tokens") or 0)
            выход = int(ход.get("output_tokens") or 0)
            чтение = int(ход.get("cache_read_input_tokens") or 0)
            запись = int(ход.get("cache_creation_input_tokens") or 0)
        if not (вход or выход or чтение or запись):
            return

        размышления = (ход.get("output_tokens_details") or {}).get("thinking_tokens")
        state["usage"] = self.finish_usage(вход, выход, чтение, запись,
                                           reasoning=размышления)
        наш_вход = int(ход.get("input_tokens") or 0)
        наш_выход = int(ход.get("output_tokens") or 0)
        raw = dict(ход)
        raw["modelUsage"] = ведомость
        for имя in ("total_cost_usd", "session_id", "num_turns", "stop_reason",
                    "duration_ms", "is_error", "permission_denials"):
            if имя in payload:
                raw[имя] = payload[имя]
        raw["учёт_koritsu"] = {
            "загрязнено": True,
            "почему": ("счётчики описывают весь запуск claude, включая её "
                       "собственные служебные обращения к модели"),
            "наш_ход_вход": наш_вход,
            "наш_ход_выход": наш_выход,
            "накладные_вход": max(0, вход - наш_вход),
            "накладные_выход": max(0, выход - наш_выход),
            "чужой_кэш_записи": запись,
            "деньги_за_весь_запуск_usd": payload.get("total_cost_usd"),
        }
        state["raw_usage"] = raw

    @staticmethod
    def _текст(payload: dict) -> str:
        """Поле `result` строкой. С `--json-schema` там приезжает разобранный
        объект; этой ступенью мы не пользуемся, но приехать она может — тогда
        обратно в текст, чтобы дальше всё шло одним путём."""
        значение = payload.get("result")
        if значение is None:
            return ""
        if isinstance(значение, str):
            return значение
        return json.dumps(значение, ensure_ascii=False)

    def _беда(self, payload: dict) -> LlmError | None:
        """Ошибка внутри разобранного JSON, если она там есть.

        Одно место на два вызывающих: решение о повторе (`_запустить`) и разбор
        ответа (`iter_stream`). Двумя они бы разъехались, и повторялось бы не
        то, что потом объявляется бедой.

        `None` означает не только «всё хорошо», но и «упёрлись в потолок
        вывода»: это исход, а не беда, и повторять его нельзя — ответ обрежется
        в том же месте за вторые деньги.
        """
        if not payload.get("is_error"):
            return None
        текст = self._текст(payload)
        if _это_потолок_вывода(текст):
            return None
        return self._ошибка(текст)

    def _ошибка(self, текст: str) -> LlmError:
        """Текст ошибки команды → LlmError. Здесь и только здесь он читается.

        Код в тексте («API Error: 429») читается тем же `kind_from_status`, что
        и HTTP-код: у ошибки один и тот же смысл, откуда бы она ни приехала, и
        второй таблицы соответствий заводить нельзя.

        Текст без кода — `bad_response`, а НЕ `transport`: команда ходит к API
        сама и временные беды уже перепробовала, к нам приезжает её приговор.
        Повторять приговор значит второй раз оплатить весь системный промпт.
        """
        совпало = _КОД_ОШИБКИ.search(текст or "")
        if совпало:
            код = int(совпало.group(1))
            вид = kind_from_status(код)
            if код == 400 and looks_like_overflow(текст):
                вид = ErrorKind.CONTEXT_OVERFLOW
            return LlmError(вид, (текст or "")[:500], status=код,
                            endpoint=self.spec.id)
        return LlmError(ErrorKind.BAD_RESPONSE,
                        (текст or "")[:500] or "команда claude вернула ошибку без описания",
                        endpoint=self.spec.id)


__all__ = ["CliBackend", "CliRunner", "ФЛАГИ", "ОКРУЖЕНИЕ", "ПОТОЛОК_ВЫВОДА"]
