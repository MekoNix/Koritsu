"""
errors — единое перечисление исходов и ошибок на все endpoint'ы.

Смысл файла: вызывающий код **никогда** не разбирает текст сообщения поставщика.
Каждый бэкенд обязан привести своё «как придётся» к этим двум перечислениям,
поэтому бизнес-логика сравнивает с константой, а не с подстрокой.

Причина остановки (`stop`) и ошибка (`kind`) — разные вещи:
`refused` (модель отказалась) — законный исход прогона, у него есть usage и его
надо записать в журнал; `transport` — ошибка, usage нет. Поэтому `refused`
присутствует в обоих перечислениях: как исход и как повод бросить LlmError,
если вызывающий просил строгий режим.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class Stop:
    """Нормализованные причины остановки (поле `stop` в Result)."""

    END_TURN = "end_turn"        # модель закончила сама
    MAX_TOKENS = "max_tokens"    # упёрлись в потолок вывода
    TOOL_USE = "tool_use"        # модель зовёт инструмент, ход не закончен
    REFUSED = "refused"          # отказ по безопасности — исход, не ошибка
    CANCELLED = "cancelled"      # отмена: закрыли поток
    ERROR = "error"              # всё остальное, подробности в LlmError

    ALL = (END_TURN, MAX_TOKENS, TOOL_USE, REFUSED, CANCELLED, ERROR)


class ErrorKind:
    """Нормализованные ошибки. Ретраить осмысленно только RETRYABLE."""

    AUTH = "auth"                        # ключ не принят
    NOT_FOUND = "not_found"              # нет такой модели / адреса
    RATE_LIMIT = "rate_limit"            # лимит поставщика
    CONTEXT_OVERFLOW = "context_overflow"  # запрос не влез в контекст
    TIMEOUT = "timeout"                  # не дождались
    REFUSED = "refused"                  # модель отказалась отвечать
    BAD_RESPONSE = "bad_response"        # JSON не разобрался N раз подряд
    TRANSPORT = "transport"              # сеть, обрыв, битый SSE, 5xx
    LIMIT_EXCEEDED = "limit_exceeded"    # наш лимит в приведённых единицах
    CANCELLED = "cancelled"              # отменено вызывающим
    UNSUPPORTED = "unsupported"          # возможность не объявлена и не эмулируется

    # Виды, которые лечатся паузой. Спрашивать надо не это множество, а
    # LlmError.retryable: у ошибки есть ещё и код ответа, и «прочие 4xx»,
    # приведённые к transport, повторять нельзя.
    RETRYABLE = (RATE_LIMIT, TIMEOUT, TRANSPORT)

    ALL = (AUTH, NOT_FOUND, RATE_LIMIT, CONTEXT_OVERFLOW, TIMEOUT, REFUSED,
           BAD_RESPONSE, TRANSPORT, LIMIT_EXCEEDED, CANCELLED, UNSUPPORTED)


@dataclass
class LlmError(Exception):
    """Ошибка слоя. `kind` — из ErrorKind, `message` — для человека.

    `retryable` вычисляется из kind и кода ответа, а не задаётся вручную: иначе
    два места правды и вызывающий будет ретраить `auth` до посинения.
    `request_id` — идентификатор запроса у поставщика, единственная зацепка
    при разборе «почему у нас списали деньги, а ответа нет».
    """

    kind: str
    message: str = ""
    status: int | None = None          # HTTP-код, если ошибка пришла по проводу
    request_id: str | None = None
    endpoint: str | None = None
    raw: dict = field(default_factory=dict)   # тело ошибки поставщика как есть
    # Сколько секунд просил подождать сам сервер (заголовок Retry-After; у 429
    # он обычно есть). Хранится отдельно от `raw`, потому что это не описание
    # беды, а указание, что с ней делать: угадывать отступ, когда сервер уже
    # назвал его, — верный способ прийти в тот же лимит второй раз.
    retry_after_s: float | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, f"{self.kind}: {self.message}")

    @property
    def retryable(self) -> bool:
        """Единственное место, где решается, имеет ли смысл повторять.

        Вид ошибки — основа, но одного его мало: «прочие 4xx» приведены к
        `transport` (тело мы ещё не разбирали), а среди них сидит обычный 400
        «плохой запрос». Повтор того же тела даст ровно тот же ответ, поэтому
        клиентские коды, кроме 408 и 429, наружу уходят с первой попытки.
        """
        if (self.status is not None and 400 <= self.status < 500
                and self.status not in (408, 429)):
            return False
        return self.kind in ErrorKind.RETRYABLE

    def __str__(self) -> str:
        head = f"{self.kind}: {self.message}" if self.message else self.kind
        return head + (f" (endpoint {self.endpoint})" if self.endpoint else "")


def kind_from_status(status: int) -> str:
    """HTTP-код → ErrorKind. Общая часть для обоих протоколов.

    401/403/402 → auth, 404 → not_found, 429 → rate_limit, 408/504 → timeout,
    прочие 4xx → transport (не bad_response: тело мы ещё не разбирали),
    5xx → transport (ретраить можно).
    Тонкость: 400 у обоих поставщиков означает и «плохой запрос», и «слишком
    длинный контекст». Разделяет их бэкенд по тексту ошибки — это
    единственное место, где текст поставщика вообще читается.
    """
    if status in (401, 403):
        return ErrorKind.AUTH
    if status == 402:
        # Денег на ключе нет. Формально это не «ключ не принят», но по делу
        # исход тот же: человеку идти пополнять, а ретраить бессмысленно.
        # В `transport` его пускать нельзя именно поэтому — тот ретраится.
        # Проверено на OpenRouter (2026-08-30): «Your account or API key has
        # insufficient credits» — https://openrouter.ai/docs/api_reference/
        # errors-and-debugging. Код общий, а не особенность одного поставщика.
        return ErrorKind.AUTH
    if status == 404:
        return ErrorKind.NOT_FOUND
    if status == 429:
        return ErrorKind.RATE_LIMIT
    if status in (408, 504):
        return ErrorKind.TIMEOUT
    return ErrorKind.TRANSPORT


_OVERFLOW_MARKERS = (
    "context length", "context_length", "too long", "maximum context",
    "context window", "prompt is too long", "max_tokens_to_sample",
    "слишком длин",
)


def looks_like_overflow(text: str) -> bool:
    """Единственное место, где мы читаем текст ошибки поставщика.

    Причина: и Anthropic, и OpenAI-совместимые отдают переполнение контекста
    как 400 с текстом, отдельного кода нет. Список маркеров заведомо неполон —
    промах даёт `transport`, что честнее выдумывания.
    """
    low = (text or "").lower()
    return any(m in low for m in _OVERFLOW_MARKERS)
