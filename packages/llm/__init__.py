"""
llm — работа с языковой моделью, не привязанная к поставщику.

Слой знает про схемы JSON, инструменты и токены. Он **не** знает про hokoku,
манифест и теги — про них знает вызывающая служба. Модель производит значения
тегов (JSON), hokoku детерминированно собирает документ; граница ровно здесь.

Несущая мысль (записка `ref/koritsu-llm-provider-layer-2026-08-29.md`, раздел 0):

    Возможность — свойство пары (endpoint, модель), а не свойство протокола.
    Слой не спрашивает «это Anthropic или OpenAI», он спрашивает
    capabilities(). Ветвление по имени поставщика живёт только в модулях
    backends/ и нигде больше.

Что видит остальной код (Б.1):

    register_endpoint(spec) -> id       описание endpoint'а в реестр
    probe(spec) -> Probe                пробный вызов, шесть шагов (Б.4)
    capabilities(id) -> Caps            объявленное + подтверждённое пробой

    generate_object(id, schema, prompt) -> Result    значения многих тегов
    generate_value(id, schema, prompt)  -> Result    одно значение
    stream_object(id, schema, prompt)   -> куски     то же потоком
    run_tools(id, tools, prompt, on_call) -> Result  петля с инструментами
    estimate(id, prompt, schema) -> Estimate         оценка до отправки
    usage_of(result) -> dict                         нормализованные счётчики

Четыре решения, которые видны в коде и которые стоит знать заранее:

* **Стриминг безусловен внутри.** И generate_*, и stream_* идут одним потоковым
  путём: отмена у обоих HTTP-протоколов — это закрытие потока (у протокола cli
  — снятие подпроцесса, но конец потока наружу тот же), а непотоковый запрос
  с большим max_tokens упирается в таймаут соединения. Наружу — две формы,
  внутри — один путь.
* **Структурированный вывод лестницей (А.3).** Схема в запросе → строгий
  инструмент → режим JSON → разбор из текста. На всех четырёх ступенях значение
  проходит один и тот же валидатор; ступени 3–4 повторяют неудачный разбор до
  двух раз, и повторы считаются в расход.
* **Лимит в приведённых единицах (В.2).** `input×1 + cache_read×0.1 +
  cache_write×1.25 + output×5`, веса из цен endpoint'а. Сырые счётчики хранятся
  все и всегда — приведённые их не заменяют.
* **Картинки модели не отдаются вовсе** (решение владельца 2026-08-29: дорого,
  OCR справляется). Если endpoint объявляет зрение, слой им не пользуется.
"""
from .errors import ErrorKind, LlmError, Stop
from .model import (Caps, Chunk, Declared, EndpointSpec, Estimate, OperatorChannel,
                    Part, PrefixCache, Prices, Probe, Result, Structured, Tool,
                    ToolCall, ToolResult, Usage)
from .registry import (backend_of, capabilities, clear, endpoints, register_endpoint,
                       spec_of, unregister, update_probe)
from .api import (DEFAULT_OBJECT_TOKENS, DEFAULT_VALUE_TOKENS, estimate,
                  generate_object, generate_value, stream_object, usage_of)
from .loop import Limits, run_tools
from .journal import Journal, Limit
from .probing import probe
from .transport import Cancelled, Retry, Transport
from . import jsonschema, layout, presets, stream_parse, usage

__version__ = "2.0.0a3"

__all__ = [
    # описание и проверка endpoint'ов
    "register_endpoint", "probe", "capabilities", "unregister", "clear",
    "endpoints", "spec_of", "backend_of", "update_probe",
    # работа
    "generate_object", "generate_value", "stream_object", "run_tools", "estimate",
    # учёт
    "usage_of", "Journal", "Limit", "Limits",
    # типы
    "EndpointSpec", "Declared", "Prices", "Probe", "Caps", "Usage", "Result",
    "Chunk", "Estimate", "Part", "Tool", "ToolCall", "ToolResult",
    "Structured", "PrefixCache", "OperatorChannel",
    # ошибки и транспорт
    "LlmError", "ErrorKind", "Stop", "Transport", "Cancelled", "Retry",
    # модули
    "presets", "jsonschema", "layout", "stream_parse", "usage",
    "DEFAULT_OBJECT_TOKENS", "DEFAULT_VALUE_TOKENS",
]
