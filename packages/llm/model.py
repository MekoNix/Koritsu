"""
model — типы слоя: описание endpoint'а, возможности, ответ, счётчики.

Несущая мысль всего пакета (записка, раздел 0): **возможность — свойство пары
(endpoint, модель), а не свойство протокола.** Поэтому `protocol` здесь — только
«как разговаривать по проводу», а что endpoint умеет, лежит отдельно в
`declared` (заявка владельца) и `probe` (что подтвердил пробный вызов).
Код никогда не спрашивает «это DeepSeek?» — он спрашивает capabilities().

Ключ в EndpointSpec **не хранится**: лежит имя переменной окружения и/или путь
к файлу, значение достаётся в момент вызова. Так ключ не попадает ни в repr,
ни в журнал, ни в сохранённые настройки.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


# ── ступени лестницы структурированного вывода (А.3) ─────────────────────────
class Structured:
    """Ступени лестницы А.3, от сильной к слабой. Порядок значим: LADDER.

    Порядок взят из записки (А.3), а не из «сначала режим JSON»: строгий
    инструмент даёт почти те же гарантии, что схема (модель не может выдумать
    ключ), тогда как json_object гарантирует только валидный JSON — ключи и
    типы всё равно проверяет наш валидатор. Поэтому tool_strict выше.
    """

    JSON_SCHEMA = "json_schema"    # 1. схема в запросе, ключ выдумать нельзя
    TOOL_STRICT = "tool_strict"    # 2. строгий инструмент с той же схемой
    JSON_OBJECT = "json_object"    # 3. режим JSON, ключи проверяем сами
    TEXT = "text"                  # 4. свободный текст, разбираем сами
    NONE = "none"                  # ничего не объявлено → работаем как TEXT

    LADDER = (JSON_SCHEMA, TOOL_STRICT, JSON_OBJECT, TEXT)

    @staticmethod
    def rank(step: str) -> int:
        """Индекс ступени; неизвестное и NONE — на дно лестницы."""
        try:
            return Structured.LADDER.index(step)
        except ValueError:
            return len(Structured.LADDER) - 1


class PrefixCache:
    BREAKPOINTS = "breakpoints"    # управляемый кэш (cache_control)
    AUTOMATIC = "automatic"        # автокэш, управлять нечем
    NONE = "none"


class OperatorChannel:
    MESSAGES_SYSTEM = "messages_system"   # role: system внутри messages
    SYSTEM_FIRST = "system_first"         # только первое системное сообщение
    NONE = "none"


# Порядок по силе канала. Нужен ровно затем, чтобы проба умела понижать и не
# умела повышать (`merged_caps`): без него «понизить» пришлось бы писать
# перечислением пар, и первая же новая ступень его бы разошлась.
_CHANNEL_ORDER = (OperatorChannel.NONE, OperatorChannel.SYSTEM_FIRST,
                  OperatorChannel.MESSAGES_SYSTEM)


def _channel_rank(value: str) -> int:
    """Сила канала числом. Незнакомое значение считаем самым слабым: неизвестное
    свойство не должно открывать ворота."""
    return _CHANNEL_ORDER.index(value) if value in _CHANNEL_ORDER else 0


@dataclass
class Prices:
    """Цены за миллион токенов. Необязательны.

    Незаполненная цена означает «деньги по этому endpoint'у не считаем», а не
    «считаем нулём» — поэтому None, а не 0.0. Из цен же берутся веса
    приведённых единиц (usage.units): если цен нет, работают умолчания.
    """

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    currency: str = "USD"

    def filled(self) -> bool:
        """Цены годны для счёта денег только если известны вход и выход."""
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def as_snapshot(self) -> dict | None:
        """Снимок цены для записи в журнал (В.4).

        Зачем снимок: цена в настройках меняется, и без копии в записи прошлые
        месяцы пересчитаются задним числом по новому прайсу.
        """
        if not self.filled():
            return None
        return {
            "input_per_mtok": self.input_per_mtok,
            "output_per_mtok": self.output_per_mtok,
            "cache_read_per_mtok": self.cache_read_per_mtok,
            "cache_write_per_mtok": self.cache_write_per_mtok,
            "currency": self.currency,
        }


@dataclass
class Declared:
    """Заявка владельца endpoint'а: что он, по его словам, умеет.

    Это **не** проверенное знание. Всё, что подтвердит проба, переедет в Probe
    и перекроет заявку там, где противоречит (Б.4). Интерфейс обязан показывать
    заявку и подтверждение разными значками (вопрос Ж.6).
    """

    structured_output: str = Structured.NONE
    streaming: bool = True
    prefix_cache: str = PrefixCache.NONE
    effort: bool = False
    operator_channel: str = OperatorChannel.SYSTEM_FIRST
    tools: bool = False
    usage_in_stream: bool = False
    # Нужен ли особый флаг, чтобы usage пришёл в потоке (у OpenAI-совместимых
    # это stream_options.include_usage). Шлём его только когда объявлено:
    # часть совместимых серверов на незнакомое поле отвечает 400.
    usage_stream_flag: bool = True
    # Кэш посчитан ВНУТРИ входных токенов или снаружи? Наша конвенция (В.2) —
    # снаружи. Если endpoint считает внутри, бэкенд обязан вычесть, иначе
    # кэшированные токены посчитаются дважды и приведённые единицы соврут.
    cache_inside_input: bool = False
    vision: bool = False   # объявляться может, но слой картинки НЕ отправляет
    # Счётчики endpoint'а описывают не только НАШ вызов. Так бывает, когда между
    # нами и моделью сидит посредник со своими обращениями к ней: у бэкенда cli
    # это сама Claude Code, у неё свой системный промпт и свои служебные вызовы,
    # и в её отчёте о расходе они неотделимы от нашего хода. Поле не меняет
    # арифметику — оно ставит на КАЖДУЮ запись журнала пометку
    # `usage_with_agent_overhead` (structured.degraded_for). Без неё цифры
    # расхода выглядели бы обычными, а объяснить их через месяц было бы нечем;
    # молчаливо завышенный учёт хуже отсутствующего.
    usage_contaminated: bool = False
    # За именем модели стоит не один поставщик, а маршрутизатор: шлюз выбирает
    # исполнителя на каждом запросе (у OpenRouter это прямо так и устроено).
    # Тогда наша несущая мысль обостряется — возможность оказывается свойством
    # не пары (endpoint, модель), а тройки (endpoint, модель, ПОСТАВЩИК), и всё,
    # что проба измерила, измерено на ТОМ прогоне и на том исполнителе.
    # Поле ничего не запрещает: оно ставит на результат пробы пометку
    # `Probe.provider_routed`, чтобы измеренное не читалось как свойство
    # endpoint'а навсегда. Данные, а не ветвление: пресет заполняет форму,
    # код по имени поставщика не развилкуется.
    provider_routed: bool = False


@dataclass
class Probe:
    """Результат пробного вызова (Б.4). Пустой `at` — проба не проводилась."""

    at: str | None = None
    ok: bool = False
    # Шаг 1: нашлось ли имя модели среди тех, что отдаёт API endpoint'а.
    # None — списка нет или он недоступен, сверять было не с чем. False не
    # отменяет пробу: вызовы с незаявленным именем сегодня проходят, — но это
    # ровно тот случай, который завтра станет отказом на боевом вызове.
    model_listed: bool | None = None
    structured_output: str | None = None   # достигнутая ступень лестницы
    streaming: bool | None = None
    usage_in_stream: bool | None = None
    usage_stream_flag_needed: bool | None = None
    tools: bool | None = None
    # Устояло ли указание оператора против текста, который пришёл раньше и
    # притворялся указанием. None — шаг не проводился. Проба поведенческая,
    # поэтому в `merged_caps` она умеет только понижать (см. там же).
    operator_channel: str | None = None
    prefix_cache_works: bool | None = None   # None — шаг не проводился/неубедителен
    # Отдаёт ли endpoint счётчики кэша ВООБЩЕ. Это отдельный вопрос от «попал ли
    # кэш», и различать их обязательно: у endpoint'а без счётчиков кэша промах
    # и отсутствие отчёта выглядят одинаково — ноль в `cache_read`, — но значат
    # разное. Первое опровергает заявку, второе означает «измерить нечем», и
    # записать его как опровержение значило бы выдумать знание.
    # None — шаг не проводился; False — шаг был, счётчиков кэша в usage нет.
    prefix_cache_reported: bool | None = None
    # Мерили на посреднике (см. `Declared.provider_routed`): результат описывает
    # ТОТ прогон, а не endpoint навсегда. Ставится по заявке пресета и, помимо
    # неё, по факту — если ответ назвал фактического поставщика.
    provider_routed: bool = False
    providers_seen: list = field(default_factory=list)   # кого назвал ответ
    # Предупреждения, которые пробу не отменяют, но молчать о них нельзя: имя
    # модели не найдено в списке API, endpoint оказался посредником. Отдельно
    # от `steps`, потому что шаг может пройти («вызовы идут»), а расхождение
    # при этом остаться — и узнать о нём отказом на боевом вызове мы не хотим.
    warnings: list = field(default_factory=list)
    # Уточнённый по измеренному usage коэффициент «символов на токен» (В.3).
    # None — уточнить не удалось: usage не пришёл ни на одном шаге, и трогать
    # заявленный коэффициент нечем. Применяется через EndpointSpec.apply_probe.
    chars_per_token: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    steps: list = field(default_factory=list)   # по записи на каждый шаг Б.4


@dataclass
class EndpointSpec:
    """Описание endpoint'а (Б.3). Ключ — по ссылке, не значением."""

    id: str
    protocol: str                       # "anthropic" | "openai"
    base_url: str
    model: str
    label: str = ""
    api_key_env: str | None = None      # имя переменной окружения
    api_key_file: str | None = None     # путь к файлу с ключом (запасной путь)
    context_tokens: int | None = None
    max_output_tokens: int = 4096
    declared: Declared = field(default_factory=Declared)
    prices: Prices = field(default_factory=Prices)
    probe: Probe = field(default_factory=Probe)
    timeout_s: float = 120.0
    own_key: bool = False               # ключ пользователя: считаем, но не против тарифа
    extra_headers: dict = field(default_factory=dict)
    # Поля тела запроса, которых нет в общем контракте, но которых требует
    # конкретный endpoint (у шлюза OpenRouter это `provider` и `usage`).
    # Это **данные, а не ветвление**: вместо «если это OpenRouter — добавь
    # provider» пресет просто заполняет форму, и код остаётся одинаковым.
    # Правило слияния: ключи, которые бэкенд собрал сам, всегда сильнее —
    # extra_body заполняет только то, чего в теле ещё нет (setdefault по
    # верхнему уровню, без вглубь). Иначе описание endpoint'а смогло бы
    # подменить `model`, `messages` или `stream` и сломать слой изнутри.
    # Учитывается бэкендом openai_compat; у anthropic-протокола нужды в нём
    # пока нет, и там поле намеренно не читается.
    extra_body: dict = field(default_factory=dict)
    # Символов на токен — коэффициент грубой оценки, когда usage не пришёл (В.3).
    # Начальное значение — заявка пресета. Проба уточняет его по тем шагам, где
    # usage всё-таки пришёл, и кладёт уточнённое сюда через apply_probe().
    chars_per_token: float = 3.5

    def resolve_key(self) -> str:
        """Достаёт ключ в момент вызова: сначала переменная, потом файл.

        Ключ не кэшируется в объекте намеренно: EndpointSpec попадает в логи,
        repr и сохранённые настройки, и значение ключа туда попасть не должно.
        """
        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if value and value.strip():
                return self._проверить_ключ(value.strip(), self.id)
        if self.api_key_file:
            path = os.path.expanduser(self.api_key_file)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    value = fh.read().strip()
                if value:
                    return self._проверить_ключ(value, self.id)
        from .errors import ErrorKind, LlmError
        where = " / ".join(x for x in (self.api_key_env, self.api_key_file) if x)
        raise LlmError(ErrorKind.AUTH, f"ключ не найден ({where or 'источник не задан'})",
                       endpoint=self.id)

    @staticmethod
    def _проверить_ключ(value: str, endpoint: str) -> str:
        """Ключ уезжает в заголовок HTTP, а туда нельзя ничего, кроме ASCII.

        Без этой проверки ключ с кириллицей (обычная беда копирования: русская
        «с» вместо латинской, лишний символ из переписки) валит запрос сырым
        UnicodeEncodeError из httpx — не нашей ошибкой и не в том месте.
        """
        try:
            value.encode("ascii")
        except UnicodeEncodeError as e:
            from .errors import ErrorKind, LlmError
            плохие = sorted({c for c in value if ord(c) > 127})
            raise LlmError(ErrorKind.AUTH,
                           "в ключе есть символы вне латиницы "
                           f"({', '.join(repr(c) for c in плохие[:5])}) — скорее всего "
                           "он скопирован с лишним знаком", endpoint=endpoint) from e
        return value

    def apply_probe(self, probe: Probe) -> None:
        """Единственная дверь, через которую результат пробы попадает в описание.

        Дверей было бы две — проба кладёт `spec.probe` сама, а реестр отдельно, —
        и они бы разошлись: то, что применяется помимо самого Probe (сейчас это
        уточнённый коэффициент оценки), появилось бы в одном пути и не появилось
        в другом. Тогда одинаковая на вид проба давала бы разный расход в
        зависимости от того, кто её положил.

        `chars_per_token` перекрывается только измеренным значением: None
        означает «usage не пришёл, уточнять нечем», и заявка пресета остаётся.
        """
        self.probe = probe
        if probe.chars_per_token:
            self.chars_per_token = probe.chars_per_token

    def has_key(self) -> bool:
        """Есть ли ключ — без его показа наружу. Для интерфейса и пробы."""
        try:
            self.resolve_key()
            return True
        except Exception:
            return False


@dataclass
class Caps:
    """Возможности пары (endpoint, модель): заявка, перекрытая пробой.

    Собирается в registry.capabilities(). Правило Б.4: проба перекрывает заявку
    там, где противоречит; если проба чего-то не проверила — остаётся заявленное.
    Поле `confirmed` говорит, что именно подтверждено, чтобы интерфейс не рисовал
    зелёную галочку там, где мы ничего не проверяли (Ж.6).
    """

    endpoint: str = ""
    model: str = ""
    protocol: str = ""
    structured_output: str = Structured.NONE
    streaming: bool = True
    prefix_cache: str = PrefixCache.NONE
    effort: bool = False
    operator_channel: str = OperatorChannel.SYSTEM_FIRST
    tools: bool = False
    usage_in_stream: bool = False
    usage_contaminated: bool = False   # в счётчиках сидит расход посредника
    # Endpoint — посредник, выбирающий исполнителя на каждом запросе. Всё
    # измеренное про него — про тот прогон, а не про endpoint навсегда
    # (`Declared.provider_routed`). Ворота этим полем не управляются: оно
    # объясняет цифры и подтверждения, а не разрешает и не запрещает.
    provider_routed: bool = False
    context_tokens: int | None = None
    max_output_tokens: int = 4096
    confirmed: set = field(default_factory=set)   # имена подтверждённых пробой полей
    probed: bool = False

    def is_confirmed(self, name: str) -> bool:
        """Подтверждено пробой (True) или только объявлено владельцем (False)."""
        return name in self.confirmed

    def supports_object(self) -> bool:
        """Годится ли endpoint для выдачи объекта по схеме хоть как-нибудь.

        Годится всегда: последняя ступень лестницы — разбор из текста. Метод
        существует ради читаемости вызывающего кода и симметрии с supports_tools.
        """
        return True

    def supports_tools(self) -> bool:
        return bool(self.tools)


@dataclass
class Usage:
    """Нормализованные счётчики. Конвенция: `input` — только НЕкэшированный вход.

    Кэш всегда снаружи входа (В.2). У Anthropic так и приходит; endpoint,
    который считает кэш внутри prompt_tokens, приводится вычитанием в бэкенде
    (declared.cache_inside_input). Без этой конвенции формула приведённых
    единиц врёт вдвое.

    `measured=False` означает, что usage не пришёл и числа оценены эвристикой.
    Флаг обязателен: без него оценки и измерения смешаются в отчётности и
    объяснить её через месяц будет нечем.
    """

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int | None = None
    measured: bool = True

    def __add__(self, other):
        """Сумма по вызовам: нужна для повторов лестницы и петли инструментов.

        `measured` складывается по И: если хоть один вызов оценён, сумма оценка.
        """
        if not isinstance(other, Usage):
            return NotImplemented
        reasoning = None
        if self.reasoning is not None or other.reasoning is not None:
            reasoning = (self.reasoning or 0) + (other.reasoning or 0)
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            reasoning=reasoning,
            measured=self.measured and other.measured,
        )

    def as_dict(self) -> dict:
        return {"input": self.input, "output": self.output,
                "cache_read": self.cache_read, "cache_write": self.cache_write,
                "reasoning": self.reasoning, "measured": self.measured}


@dataclass
class ToolCall:
    """Вызов инструмента, каким его увидела наша петля (одинаково у обоих)."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    raw_arguments: str = ""      # как пришло; аргументы могут не разобраться


@dataclass
class ToolResult:
    """Ответ инструмента модели. `is_error` — штатный путь, а не исключение.

    Почему так: недоступность инструмента должна приходить ответом `is_error`,
    а не исчезновением инструмента из списка — иначе поведение непредсказуемо
    (записка, Д.3).
    """

    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Tool:
    """Объявление инструмента. Схема — то же подмножество JSON Schema."""

    name: str
    description: str = ""
    schema: dict = field(default_factory=dict)
    strict: bool = True


@dataclass
class Result:
    """Единый ответ слоя (Б.2) — одинаковый у любого поставщика."""

    ok: bool = True
    text: str = ""
    value: object = None                     # разобранный объект, если просили схему
    usage: Usage = field(default_factory=Usage)
    stop: str = "end_turn"
    endpoint: str = ""
    model: str = ""
    degraded: list = field(default_factory=list)   # чего не было и что обошли
    attempts: int = 1
    latency_ms: int = 0
    raw_usage: dict = field(default_factory=dict)  # как вернул endpoint, дословно
    request_id: str | None = None
    units: float = 0.0                       # приведённые единицы (В.2)
    cost: float | None = None                # деньги, если цены заполнены
    structured_step: str | None = None       # ступень лестницы, которой добились
    tool_calls: list = field(default_factory=list)
    error: object = None                     # LlmError, если ok=False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "value": self.value, "text": self.text,
            "usage": self.usage.as_dict(), "stop": self.stop,
            "endpoint": self.endpoint, "model": self.model,
            "degraded": list(self.degraded), "attempts": self.attempts,
            "latency_ms": self.latency_ms, "raw_usage": self.raw_usage,
            "units": self.units, "cost": self.cost,
            "structured_step": self.structured_step,
            "request_id": self.request_id,
        }


@dataclass
class Chunk:
    """Кусок потока. `kind`: text | tool_call | usage | stop | error."""

    kind: str
    text: str = ""
    tool_call: object = None
    usage: object = None
    stop: str | None = None
    error: object = None
    raw: dict = field(default_factory=dict)


@dataclass
class Estimate:
    """Оценка до отправки (В.3). `method` различает счёт и догадку.

    Интерфейс пишет «≈» в обоих случаях, но внутри разница есть: на границе
    лимита отказ по оценке и отказ по расчёту — разной силы утверждения.
    """

    tokens: int
    method: str = "estimated"     # "counted" | "estimated"
    output_tokens: int = 0
    units: float = 0.0


# Роли, недоверенные по умолчанию. Умолчание — не определение: недоверенность
# принадлежит куску, а не имени роли. Роль `files` попала сюда потому, что
# другого содержимого, кроме чужого файла, у неё не бывает; `manifest` и
# `neighbors` недоверенны в отчёте, но не обязаны быть такими у другого
# вызывающего, поэтому он ставит признак сам (`Part(untrusted=True)`).
UNTRUSTED_ROLES = ("files",)


@dataclass
class Part:
    """Кусок промпта для раскладки Б.5.

    `role`: "rules" | "manifest" | "files" | "neighbors" | "request" —
    смысл куска, а не место в диалоге. Куда его положить и где поставить
    брейкпойнт, решает бэкенд; вызывающий код брейкпойнтов не видит.
    `stable=True` — кусок не меняется от вызова к вызову, его можно кэшировать.

    `untrusted=True` — текст куска написан не нами, и вокруг него ставится
    рамка со случайной меткой (`layout.frame_untrusted`). Признак явный, а не
    выведенный из роли, ровно потому, что чужой текст приезжает не только
    ролью `files`: метки тегов в `manifest` берутся из DOCX-шаблона, который
    кладёт студент, а значения в `neighbors` могли быть списаны из его файла.
    Пока признак жил в имени роли, поставить рамку на них было нельзя, не
    заведя второго пути рендера, — а второй путь рано или поздно расходится с
    первым молча.

    `untrusted=None` (умолчание) — «не сказано», и тогда признак берётся по
    роли из `UNTRUSTED_ROLES`; после `__post_init__` поле всегда bool, так что
    читающий код видит один ответ, а не два. Цена этого умолчания — один
    случай: `dataclasses.replace(part, role="files")` у куска, которому
    недоверенность уже вычислили в False, оставит False. Менять роль готового
    куска и так значит собирать его заново.
    """

    role: str
    text: str
    stable: bool = False
    name: str | None = None       # имя файла для рамки (недоверенный вход)
    untrusted: bool | None = None  # None — по роли (UNTRUSTED_ROLES)

    def __post_init__(self):
        if self.untrusted is None:
            self.untrusted = self.role in UNTRUSTED_ROLES


def merged_caps(spec: EndpointSpec) -> Caps:
    """Заявка + проба → Caps. Проба перекрывает заявку там, где противоречит.

    Обратное неверно: если проба возможность не проверила (None), объявленное
    остаётся в силе. Именно поэтому здесь всюду `is not None`, а не `or`.
    """
    d, p = spec.declared, spec.probe
    confirmed = set()

    def pick(probed, declared_value, name):
        if probed is not None:
            confirmed.add(name)
            return probed
        return declared_value

    caps = Caps(
        endpoint=spec.id,
        model=spec.model,
        protocol=spec.protocol,
        structured_output=pick(p.structured_output, d.structured_output, "structured_output"),
        streaming=pick(p.streaming, d.streaming, "streaming"),
        prefix_cache=d.prefix_cache,
        effort=d.effort,
        operator_channel=d.operator_channel,
        tools=pick(p.tools, d.tools, "tools"),
        usage_in_stream=pick(p.usage_in_stream, d.usage_in_stream, "usage_in_stream"),
        # Загрязнение счётчиков пробой не проверяется и проверено быть не может:
        # чтобы отличить наш расход от расхода посредника, нужен второй,
        # независимый счёт того же вызова, а его нет. Значит это заявка — и
        # остаётся заявкой навсегда.
        usage_contaminated=d.usage_contaminated,
        # Посредничество проба умеет только ПОДТВЕРДИТЬ: ответ, назвавший
        # фактического поставщика, доказывает маршрутизацию, а молчание ответа
        # не доказывает её отсутствия (шлюз вправе не называть исполнителя).
        # Поэтому «или», а не pick: заявку владельца проба здесь не снимает.
        provider_routed=bool(d.provider_routed or p.provider_routed),
        context_tokens=spec.context_tokens,
        max_output_tokens=spec.max_output_tokens,
        probed=bool(p.at),
    )
    # Операторский канал: пробой можно **понизить, но не повысить**. Проба
    # поведенческая — она показывает, что модель послушалась оператора в этот
    # раз, а не что канал устоит против настоящей инъекции. Ошибка в сторону
    # строгости стоит осторожности; ошибка в сторону разрешения — это уровень 3
    # на endpoint'е, который канал не держит. Поэтому повышение остаётся
    # решением владельца, а проба его только опровергает.
    if p.operator_channel is not None and \
            _channel_rank(p.operator_channel) < _channel_rank(d.operator_channel):
        caps.operator_channel = p.operator_channel
        confirmed.add("operator_channel")
    # Кэш: пробой подтверждается только положительный результат. Отрицательный
    # на автокэше неубедителен (Б.4, шаг 7), поэтому заявку он не отменяет.
    # `prefix_cache_reported is False` — «endpoint о кэше не отчитывается» —
    # тоже не отменяет: это отсутствие измерения, а не измеренное отсутствие.
    # Заявка остаётся заявкой и остаётся НЕподтверждённой; почему именно, видно
    # в шаге пробы и в отчёте.
    if p.prefix_cache_works is True:
        confirmed.add("prefix_cache")
    elif p.prefix_cache_works is False and d.prefix_cache == PrefixCache.BREAKPOINTS:
        caps.prefix_cache = PrefixCache.NONE
        confirmed.add("prefix_cache")
    if p.provider_routed:
        confirmed.add("provider_routed")
    caps.confirmed = confirmed
    return caps


__all__ = ["Structured", "PrefixCache", "OperatorChannel", "Prices", "Declared",
           "Probe", "EndpointSpec", "Caps", "Usage", "ToolCall", "ToolResult",
           "Tool", "Result", "Chunk", "Estimate", "Part", "merged_caps", "replace"]
