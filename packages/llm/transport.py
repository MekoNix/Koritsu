"""
transport — HTTP и разбор SSE. Единственное место, которое знает про сеть.

Почему свой транспорт, а не SDK поставщиков: оба протокола — это POST с JSON и
поток SSE. Свой транспорт делает слой честно независимым (SDK Anthropic знает
про Anthropic, SDK OpenAI — про OpenAI, и оба тянут за собой свои представления
о том, как устроен ответ) и тестируемым без сети: тесты подставляют
httpx.MockTransport и гоняют записанные потоки событий.

Отмена — это закрытие потока (А.4, строка 10 матрицы): другого способа отменить
в обоих протоколах нет. Поэтому `cancel` здесь — вызываемый объект, который
поток спрашивает между кусками, и при True поток закрывается на месте.

Повтор временных ошибок живёт здесь же, и это осознанное место: через транспорт
идут все — обычный вызов, поток, петля инструментов, проба, — и повтор,
положенный сюда, достаётся им всем один раз написанным. Отчёт целиком — это
десятки запросов, и без повтора он падает на первом же 429 «слишком часто» или
на первой пятисотке, хотя и то и другое лечится паузой.
"""
from __future__ import annotations

import datetime
import json
import random
import threading
import time
from email.utils import parsedate_to_datetime

import httpx

from .errors import ErrorKind, LlmError, kind_from_status, looks_like_overflow


# Сколько записок о повторах держать, пока их никто не забрал.
_MAX_NOTES = 20


class Cancelled(Exception):
    """Поток закрыт по требованию вызывающего. Не ошибка — исход."""


class Retry:
    """Политика повторов: сколько раз, сколько ждать и сколько это может длиться.

    Повторяется только то, про что `LlmError.retryable` сказал «да»: 429,
    таймаут, пятисотки и обрывы. `auth` (в том числе 402 «нет денег на ключе»),
    `not_found`, переполнение контекста и обычный 400 наружу уходят с первой
    попытки: повтор их не чинит, а жжёт время и деньги. Своего списка видов
    здесь нет намеренно — два места правды разъедутся в первый же месяц.

    Два потолка, и оба нужны:
      * `attempts` — сколько всего попыток (не повторов): защита от петли;
      * `total_s` — сколько всего может длиться операция со всеми попытками и
        паузами. Он и есть ответ на «повтор не должен молча съесть таймаут
        вызова»: худший случай вызывающего — не `attempts × timeout_s`, а
        `total_s`, и цифра эта видна в описании политики, а не выводится в уме.

    Острый угол этой честности: при умолчаниях (`timeout_s=120`, `total_s=60`)
    попытка, упёршаяся в таймаут соединения, уже съела весь бюджет, и повтора
    не будет. Так и задумано: молча удвоить ожидание хуже, чем вернуть ошибку.
    Кому нужен повтор таймаутов — тот ставит endpoint'у таймаут короче бюджета.

    Отступ растёт вдвое и берётся со случайным разбросом (половина–целое):
    без разброса параллельные вызовы после общей пятисотки возвращаются к
    серверу в такт и валят его повторно. `sleep` и `monotonic` подменяемы —
    иначе тесты политики спали бы по-настоящему.
    """

    def __init__(self, attempts: int = 4, base_delay_s: float = 1.0,
                 max_delay_s: float = 20.0, total_s: float = 60.0,
                 sleep=time.sleep, monotonic=time.monotonic):
        self.attempts = max(1, int(attempts))
        self.base_delay_s = float(base_delay_s)
        self.max_delay_s = float(max_delay_s)
        self.total_s = float(total_s)
        self.sleep = sleep
        self.monotonic = monotonic

    def delay_for(self, error: LlmError, attempt: int, started: float) -> float | None:
        """Сколько ждать перед попыткой `attempt + 1`. None — повтора не будет.

        `Retry-After` сильнее нашей формулы: сервер назвал срок, и приходить
        раньше — гарантированно получить тот же отказ. Но если ждать столько,
        что бюджет всё равно кончится, ждать бессмысленно — отказываем сразу,
        а не через минуту молчания.
        """
        if not error.retryable or attempt >= self.attempts:
            return None
        left = self.total_s - (self.monotonic() - started)
        if left <= 0:
            return None
        if error.retry_after_s is not None:
            delay = max(0.0, error.retry_after_s)
        else:
            grown = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
            delay = random.uniform(grown / 2, grown)
        return delay if delay <= left else None


class Transport:
    """Обёртка над httpx.Client. Один экземпляр на endpoint, живёт долго.

    `client` можно передать снаружи — так тесты подставляют MockTransport, а
    боевой код получает обычный клиент с таймаутом.

    `retry` — политика повторов, по умолчанию обычная `Retry()`. Выключается
    явно (`Retry(attempts=1)`), а не отсутствием: повтор по умолчанию нужен
    всем, кто ходит через транспорт, и включать его в каждом месте вызова
    означало бы забыть в половине из них.

    `on_retry` — куда сообщать о каждом повторе. Повтор без следа — это
    необъяснимая задержка в отчёте и потерянная причина: журналу нужно знать,
    что вызов стоил трёх попыток и почему.
    """

    def __init__(self, base_url: str, headers: dict | None = None,
                 timeout_s: float = 120.0, client: httpx.Client | None = None,
                 retry: Retry | None = None, on_retry=None):
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout_s = timeout_s
        self._client = client
        self._own_client = client is None
        self.retry = retry or Retry()
        self._on_retry = on_retry
        # Записки о повторах и идентификатор последнего ответа копятся по
        # потокам исполнения: транспорт один на endpoint и живёт долго, а
        # забрать их должен тот, кто сделал вызов, — иначе чужой повтор (и
        # чужой идентификатор) припишется чужому же ходу.
        self._local = threading.local()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(self.timeout_s))
        return self._client

    def close(self) -> None:
        if self._client is not None and self._own_client:
            self._client.close()
            self._client = None

    # ── повторы ─────────────────────────────────────────────────────────────
    def take_retries(self) -> list:
        """Забрать записки о повторах этого потока исполнения и очистить их.

        Забирают, а не подсматривают: записка нужна ровно одному ходу журнала,
        и оставленная в транспорте она приписалась бы ещё и следующему.
        """
        notes = getattr(self._local, "notes", None)
        self._local.notes = []
        return notes or []

    # ── идентификатор ответа ────────────────────────────────────────────────
    def take_request_id(self) -> str | None:
        """Забрать идентификатор последнего ответа этого потока и очистить его.

        Идентификатор — единственная зацепка при разборе «списали деньги, а
        ответа нет», и в записи журнала он обязан быть у **успешного** вызова
        тоже: разбирают как раз те, что вернулись с 200 и пустотой.

        Забирают, а не подсматривают, ровно как записки о повторах: оставленный
        в транспорте идентификатор приписался бы и следующему вызову — в том
        числе тому, который упал, не дойдя до заголовков. Чужой идентификатор в
        записи хуже пустого: по нему поставщику предъявят не тот запрос.
        """
        value = getattr(self._local, "request_id", None)
        self._local.request_id = None
        return value

    def _note_request_id(self, request_id) -> None:
        """Идентификатор ответа — в состояние потока исполнения.

        Пишется на каждой попытке, включая неудачную: у повторов идентификатор
        свой, и разбирать поставщику придётся последнюю попытку.

        Каждая попытка **начинается** со сброса в None (`_note_request_id(None)`
        в начале запроса). Иначе вызов, не дошедший до заголовков, унаследовал
        бы идентификатор предыдущего: забирают его не всегда — `complete()`
        поднимает ошибку внутри 200-потока, не дойдя до места забора, — и
        оставленный идентификатор приписался бы чужому запросу. Чужой
        идентификатор в записи хуже пустого.
        """
        self._local.request_id = request_id

    def _note_retry(self, attempt: int, delay: float, error: LlmError, path: str) -> None:
        """Повтор записывается всегда. Молчаливый повтор = задержка без причины."""
        note = {"attempt": attempt, "delay_s": round(delay, 3), "kind": error.kind,
                "status": error.status, "request_id": error.request_id,
                "path": path, "reason": (error.message or "")[:200]}
        notes = getattr(self._local, "notes", None)
        if notes is None:
            notes = self._local.notes = []
        notes.append(note)
        # Записки забирает не всякий: обычный generate_object про них не знает.
        # Хвост обрезаем, иначе долгоживущий транспорт копил бы их месяцами —
        # а кому нужнее, тот забирает сразу, и хвост ему ни к чему.
        if len(notes) > _MAX_NOTES:
            del notes[:-_MAX_NOTES]
        if self._on_retry is not None:
            self._on_retry(note)

    def _retrying(self, path: str, attempt_fn):
        """Общий повтор для непотоковых вызовов: попытка целиком или заново.

        Здесь повторять безопасно ровно потому, что ответа наружу ещё не
        отдавали: пока ответ не разобран, вызывающий про попытки не знает.
        """
        started = self.retry.monotonic()
        attempt = 0
        while True:
            attempt += 1
            try:
                return attempt_fn()
            except LlmError as exc:
                delay = self.retry.delay_for(exc, attempt, started)
                if delay is None:
                    raise
                self._note_retry(attempt, delay, exc, path)
                self.retry.sleep(delay)

    # ── обычный запрос ──────────────────────────────────────────────────────
    def post_json(self, path: str, body: dict, endpoint_id: str = "") -> tuple:
        """POST с JSON-ответом. Возвращает (тело, request_id).

        Непотоковый путь нужен ровно двум местам: пробе (шаг 2) и счётчику
        токенов Anthropic. Вся работа идёт потоком (А.4).
        """
        return self._retrying(path, lambda: self._post_json_once(path, body, endpoint_id))

    def _post_json_once(self, path: str, body: dict, endpoint_id: str) -> tuple:
        """Одна попытка POST. Повтор — снаружи, в `_retrying`."""
        self._note_request_id(None)
        url = f"{self.base_url}{path}"
        try:
            resp = self._get_client().post(url, json=body, headers=self.headers,
                                           timeout=self.timeout_s)
        except httpx.TimeoutException as exc:
            raise LlmError(ErrorKind.TIMEOUT, str(exc) or "истёк таймаут",
                           endpoint=endpoint_id)
        except httpx.HTTPError as exc:
            raise LlmError(ErrorKind.TRANSPORT, str(exc) or "сетевая ошибка",
                           endpoint=endpoint_id)
        request_id = _request_id(resp.headers)
        self._note_request_id(request_id)
        if resp.status_code >= 400:
            raise _http_error(resp.status_code, resp.text, request_id, endpoint_id,
                              headers=resp.headers)
        try:
            return resp.json(), request_id
        except (ValueError, json.JSONDecodeError) as exc:
            raise LlmError(ErrorKind.BAD_RESPONSE, f"ответ не JSON: {exc}",
                           request_id=request_id, endpoint=endpoint_id)

    def get_json(self, path: str, endpoint_id: str = "") -> tuple:
        """GET с JSON-ответом. Нужен одному шагу пробы — списку моделей.

        Отдельный метод, а не обращение к клиенту напрямую, ровно по той же
        причине, по какой существует post_json: заголовки (и ключ в них) живут
        в транспорте в одном месте, и добывать их вторично неоткуда.
        """
        return self._retrying(path, lambda: self._get_json_once(path, endpoint_id))

    def _get_json_once(self, path: str, endpoint_id: str) -> tuple:
        """Одна попытка GET. Повтор — снаружи, в `_retrying`."""
        self._note_request_id(None)
        url = f"{self.base_url}{path}"
        try:
            resp = self._get_client().get(url, headers=self.headers,
                                          timeout=self.timeout_s)
        except httpx.TimeoutException as exc:
            raise LlmError(ErrorKind.TIMEOUT, str(exc) or "истёк таймаут",
                           endpoint=endpoint_id)
        except httpx.HTTPError as exc:
            raise LlmError(ErrorKind.TRANSPORT, str(exc) or "сетевая ошибка",
                           endpoint=endpoint_id)
        request_id = _request_id(resp.headers)
        self._note_request_id(request_id)
        if resp.status_code >= 400:
            raise _http_error(resp.status_code, resp.text, request_id, endpoint_id,
                              headers=resp.headers)
        try:
            return resp.json(), request_id
        except (ValueError, json.JSONDecodeError) as exc:
            raise LlmError(ErrorKind.BAD_RESPONSE, f"ответ не JSON: {exc}",
                           request_id=request_id, endpoint=endpoint_id)

    # ── поток ───────────────────────────────────────────────────────────────
    def stream_sse(self, path: str, body: dict, endpoint_id: str = "", cancel=None):
        """Итератор событий SSE: (имя события | None, разобранное тело).

        `cancel` — вызываемый объект без аргументов; спрашивается перед каждым
        событием. Вернул True — поднимаем Cancelled и закрываем соединение.
        Именно закрытие соединения и есть отмена у обоих поставщиков.

        `data: [DONE]` (маркер конца у OpenAI-совместимых) сюда не пропускается:
        это деталь протокола, а не событие.

        **Что делаем с обрывом посреди уже начатого потока — и почему.** Повтор
        здесь допускается только до первого отданного события, то есть пока
        беда случилась на соединении, заголовках или коде ответа (а 429 и 5xx
        приходят именно там, до потока). Как только наружу ушло хотя бы одно
        событие, обрыв уходит наружу ошибкой и повтора не будет — по трём
        причинам, каждой из которых хватило бы:
          * поставщик уже посчитал и выставил счёт за отданные токены, а вторая
            попытка выставит его снова: расход в журнале станет враньём;
          * отданное уже напечатано вызывающему (stream_object показывает куски
            по мере генерации), и повтор с нуля означал бы либо дубль текста,
            либо требование стереть напечатанное;
          * половина ответа могла быть побочным действием — вызовом инструмента,
            который уже исполнен.
        Правильное лечение обрыва в середине — не повтор куска, а новый вызов
        решением уровнем выше, где видно, что уже сделано.

        Ошибка, приехавшая **событием внутри** потока (шлюз отдал 200, а беда
        случилась позже), сюда не попадает вовсе: её распознаёт бэкенд, разбирая
        событие, и по тому же правилу она наружу уходит без повтора.
        """
        started = self.retry.monotonic()
        attempt = 0
        while True:
            attempt += 1
            delivered = False
            try:
                for event in self._stream_once(path, body, endpoint_id, cancel):
                    delivered = True
                    yield event
                return
            except Cancelled:
                raise
            except LlmError as exc:
                delay = None if delivered else self.retry.delay_for(exc, attempt, started)
                if delay is None:
                    raise
                self._note_retry(attempt, delay, exc, path)
                self.retry.sleep(delay)

    def _stream_once(self, path: str, body: dict, endpoint_id: str, cancel):
        """Одна попытка потока. Повтор — снаружи, в `stream_sse`."""
        self._note_request_id(None)
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.setdefault("Accept", "text/event-stream")
        try:
            with self._get_client().stream("POST", url, json=body, headers=headers,
                                           timeout=self.timeout_s) as resp:
                request_id = _request_id(resp.headers)
                self._note_request_id(request_id)
                if resp.status_code >= 400:
                    resp.read()
                    raise _http_error(resp.status_code, resp.text, request_id,
                                      endpoint_id, headers=resp.headers)
                for event_name, data in _iter_sse(resp.iter_lines()):
                    if cancel is not None and cancel():
                        raise Cancelled()
                    if data == "[DONE]":
                        return
                    try:
                        payload = json.loads(data)
                    except (ValueError, json.JSONDecodeError):
                        # Битую строку в потоке пропускаем, а не роняем весь
                        # прогон: у совместимых серверов встречается мусор
                        # (комментарии, keep-alive), а ответ при этом целый.
                        continue
                    yield event_name, payload
        except Cancelled:
            raise
        except httpx.TimeoutException as exc:
            raise LlmError(ErrorKind.TIMEOUT, str(exc) or "истёк таймаут потока",
                           endpoint=endpoint_id)
        except httpx.HTTPError as exc:
            raise LlmError(ErrorKind.TRANSPORT, str(exc) or "обрыв потока",
                           endpoint=endpoint_id)


def _iter_sse(lines):
    """Разбор SSE из строк: накапливаем `event:` и `data:` до пустой строки.

    Тонкость, из-за которой это не одна строка кода: `data:` может приходить
    несколькими строками подряд, и они склеиваются через \\n (так в спецификации
    SSE). Anthropic шлёт `event:`, OpenAI-совместимые — нет, поэтому имя события
    необязательно.
    """
    event_name = None
    data_lines: list = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name, data_lines = None, []
            continue
        if line.startswith(":"):
            continue                      # комментарий / keep-alive
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield event_name, "\n".join(data_lines)


def _request_id(headers) -> str | None:
    """Идентификатор запроса — единственная зацепка при разборе с поставщиком.

    У Anthropic это `request-id`, у OpenAI-совместимых `x-request-id`, а у
    прокси бывает `cf-ray`. Берём первое, что нашлось: имя нам не важно,
    важно, чтобы в журнале что-то было.
    """
    for name in ("request-id", "x-request-id", "x-amzn-requestid", "cf-ray"):
        value = headers.get(name)
        if value:
            return value
    return None


def _retry_after(headers) -> float | None:
    """Заголовок Retry-After → секунды. Спецификация разрешает две записи.

    Секунды приходят числом, но у части шлюзов — HTTP-датой, и не разобрать её
    значит выкинуть единственную точную цифру, какая у нас есть, и заменить её
    догадкой. Дата в прошлом (часы разъехались) даёт 0 — «можно сразу».
    """
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    value = str(raw).strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds())


def _http_error(status: int, text: str, request_id, endpoint_id: str,
                headers=None) -> LlmError:
    """HTTP-ошибка → LlmError. Здесь и только здесь читается текст поставщика.

    Причина исключения: и Anthropic, и OpenAI-совместимые отдают переполнение
    контекста как 400 с текстом, отдельного кода для него нет.
    """
    raw: dict = {}
    message = (text or "").strip()
    try:
        raw = json.loads(text)
        if isinstance(raw, dict):
            err = raw.get("error")
            if isinstance(err, dict):
                message = err.get("message") or message
            elif isinstance(err, str):
                message = err
    except (ValueError, json.JSONDecodeError):
        raw = {}
    kind = kind_from_status(status)
    if status == 400 and looks_like_overflow(message):
        kind = ErrorKind.CONTEXT_OVERFLOW
    return LlmError(kind, message[:500] or f"HTTP {status}", status=status,
                    request_id=request_id, endpoint=endpoint_id,
                    raw=raw if isinstance(raw, dict) else {},
                    retry_after_s=_retry_after(headers))


__all__ = ["Transport", "Cancelled", "Retry"]
