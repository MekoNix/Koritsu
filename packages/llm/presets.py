"""
presets — готовые описания endpoint'ов. **Данные, а не ветвление.**

Разница принципиальна. Слой нигде не спрашивает «это DeepSeek?»: он спрашивает
capabilities(). Пресет — это просто заполненная за пользователя форма Б.3,
которую он мог бы набрать руками, и ничем от набранной руками не отличается.
Если завтра выяснится, что endpoint умеет не то, что здесь написано, правится
одна строка данных, а не код.

**Всё в поле `declared` — это заявка, а не проверенное знание.** Проба (Б.4)
перекроет её там, где противоречит. Пометки в комментариях говорят, что именно
здесь не проверено живым вызовом.
"""
from __future__ import annotations

from .model import Declared, EndpointSpec, OperatorChannel, PrefixCache, Prices, Structured


def deepseek(endpoint_id: str = "ep_deepseek", model: str = "deepseek-chat",
             **overrides) -> EndpointSpec:
    """DeepSeek — первый рабочий endpoint (решение владельца 2026-08-29).

    «Без thinking, просто api»: модель без размышлений, `reasoning_effort` не
    объявляем и не шлём.

    Что здесь ЗАЯВЛЕНО, но НЕ проверено живым вызовом (ключа в окружении сборки
    не было; проверяется командой `python -m llm probe --preset deepseek`):

      * `structured_output: json_object` — заявлено скромно намеренно. Лестница
        (А.3) при пробе сама поднимется выше, если endpoint примет json_schema
        или строгий инструмент; занизить безопаснее, чем завысить, потому что
        завышенная заявка даёт 400 на первом же боевом вызове.
      * `tools: True` — протокол их описывает, зовёт ли модель, покажет проба.
      * `prefix_cache: automatic` — у DeepSeek есть автокэш со своими именами
        счётчиков (`prompt_cache_hit_tokens`); читаются они терпимо, но что
        именно приходит и входит ли кэш в `prompt_tokens`, проверяет проба.
      * `cache_inside_input: True` — предполагаем худшее из двух: если кэш
        считается внутри входа и мы не вычтем, кэшированные токены посчитаются
        дважды и приведённые единицы соврут вдвое. Ошибка в эту сторону даёт
        недосчёт, а не переcчёт, и проба её поправит.
      * `usage_in_stream` / `usage_stream_flag` — приходит ли usage в потоке и
        нужен ли для этого `stream_options.include_usage`. Шаг 3 пробы
        проверяет оба случая; при отсутствии usage работает запасной подсчёт.

    Цены не заполнены: без них деньги по endpoint'у не считаются (это честнее
    выдуманных чисел), а веса приведённых единиц берутся из умолчаний.
    Заполнить — `prices=Prices(input_per_mtok=…, output_per_mtok=…)`.
    """
    spec = EndpointSpec(
        id=endpoint_id,
        label="DeepSeek",
        protocol="openai",
        base_url="https://api.deepseek.com",
        model=model,
        api_key_env="DEEPSEEK_API_KEY",
        api_key_file="~/.config/koritsu/deepseek.key",
        context_tokens=64000,
        max_output_tokens=8192,
        declared=Declared(
            structured_output=Structured.JSON_OBJECT,
            streaming=True,
            prefix_cache=PrefixCache.AUTOMATIC,
            effort=False,                       # «без thinking, просто api»
            # Решение владельца 2026-09-03 на основании пробы: указание оператора,
            # поставленное системным сообщением ПОСЛЕ подложенного «забудь
            # инструкции», устояло 2 из 2 (`probing._step_operator`). Структурной
            # гарантии у формата OpenAI нет — `system` лежит в том же `messages`,
            # — поэтому канал здесь не данность, а исполнение:
            # `openai_compat._operator_reminder` повторяет указание после
            # недоверенного текста. Проба умеет эту заявку понизить и не умеет
            # повысить (`model.merged_caps`), так что отзыв стоит одной строки.
            operator_channel=OperatorChannel.MESSAGES_SYSTEM,
            tools=True,
            usage_in_stream=False,
            usage_stream_flag=True,
            cache_inside_input=True,
        ),
        prices=Prices(),
        chars_per_token=3.0,   # смешанный русско-английский текст; калибруется
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


def anthropic(endpoint_id: str = "ep_anthropic", model: str = "claude-opus-5",
              **overrides) -> EndpointSpec:
    """Anthropic — второй endpoint; он и проверяет независимость слоя.

    Возможности объявлены полными, но это тоже заявка: они верны для
    api.anthropic.com и **не** верны для произвольного Anthropic-совместимого
    прокси (у прокси может не быть cache_control). Возможности — свойство пары
    (endpoint, модель), не протокола.

    Оговорки, которые важны и на самом Anthropic:
      * `operator_channel: messages_system` есть не на всех моделях (на Sonnet 5
        это 400) — при смене модели поле надо менять вместе с ней;
      * `effort` объявлен, но менять его между «весь отчёт» и «один тег» нельзя:
        смена effort обнуляет кэш, и обещанная дешёвая перегенерация исчезает.
        Один effort на оба маршрута, зафиксированный на endpoint'е.

    Цены — Opus 5 на 2026-08. Они попадут снимком в каждую запись журнала, и
    прошлые месяцы не пересчитаются при изменении прайса.
    """
    spec = EndpointSpec(
        id=endpoint_id,
        label="Anthropic",
        protocol="anthropic",
        base_url="https://api.anthropic.com",
        model=model,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_file="~/.config/koritsu/anthropic.key",
        context_tokens=1000000,
        max_output_tokens=64000,
        declared=Declared(
            structured_output=Structured.JSON_SCHEMA,
            streaming=True,
            prefix_cache=PrefixCache.BREAKPOINTS,
            effort=True,
            operator_channel=OperatorChannel.MESSAGES_SYSTEM,
            tools=True,
            usage_in_stream=True,
            usage_stream_flag=False,      # у этого протокола флага нет
            cache_inside_input=False,     # кэш приходит снаружи входа
        ),
        prices=Prices(input_per_mtok=5.0, output_per_mtok=25.0,
                      cache_read_per_mtok=0.5, cache_write_per_mtok=6.25),
        chars_per_token=3.5,
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


# ── OpenRouter ───────────────────────────────────────────────────────────────
# Что известно про модели шлюза на 2026-08-30. Снято живым запросом к
# https://openrouter.ai/api/v1/models и .../models/<id>/endpoints — цены там
# приходят строкой за ОДИН токен, здесь они переведены в цену за миллион.
#
# Таблица нужна ровно затем, чтобы цены не пережили смену модели. Пресет с
# заполненными ценами и подменённой моделью врал бы про деньги молча, а
# незаполненные цены честно означают «по этому endpoint'у деньги не считаем».
# `context` и `max_output` — тоже свойство модели, а не шлюза.
OPENROUTER_МОДЕЛИ = {
    # Дешёвая, миллион контекста, все провайдеры умеют структурированный вывод
    # и инструменты, размышления не обязательны, температуру и stop принимает.
    "google/gemini-2.5-flash-lite": {
        "prices": Prices(input_per_mtok=0.10, output_per_mtok=0.40,
                         cache_read_per_mtok=0.01, cache_write_per_mtok=0.0833),
        "context": 1048576, "max_output": 65535, "chars_per_token": 3.0,
    },
    # Сильнее в русском и в строгих схемах, но размышления у неё обязательны
    # (`reasoning.mandatory: true`), а `temperature` и `stop` она НЕ принимает:
    # вместе с require_parameters (ниже) запрос с температурой останется без
    # провайдеров и получит 503.
    "openai/gpt-5-mini": {
        "prices": Prices(input_per_mtok=0.25, output_per_mtok=2.00,
                         cache_read_per_mtok=0.025),
        "context": 400000, "max_output": 128000, "chars_per_token": 3.0,
    },
    # Самое дешёвое сочетание «миллион контекста + структурированный вывод».
    # Раздают её 17 провайдеров, и у четверых (GMICloud, SiliconFlow, Novita,
    # Azure) структурированного вывода нет, а окно у Cloudflare втрое меньше
    # заявленного — то есть без require_parameters ниже брать её нельзя.
    "deepseek/deepseek-v4-flash": {
        "prices": Prices(input_per_mtok=0.0801, output_per_mtok=0.1602,
                         cache_read_per_mtok=0.016),
        "context": 1048576, "max_output": 384000, "chars_per_token": 3.0,
    },
    # Та же семья, что и у прямого пресета deepseek, — ею и сравнивают шлюз с
    # прямым доступом. Осторожно: её раздают 14 провайдеров, и у части из них
    # нет ни структурированного вывода, ни инструментов (см. докстроку ниже).
    "deepseek/deepseek-v3.2": {
        "prices": Prices(input_per_mtok=0.269, output_per_mtok=0.40,
                         cache_read_per_mtok=0.1345),
        "context": 163840, "max_output": 65536, "chars_per_token": 3.0,
    },
}


def openrouter(endpoint_id: str = "ep_openrouter",
               model: str = "google/gemini-2.5-flash-lite", **overrides) -> EndpointSpec:
    """OpenRouter — шлюз ко многим поставщикам по протоколу chat/completions.

    Решение владельца 2026-08-29: своего сервера пока нет, endpoint — внешний
    API. OpenRouter выбран первым рабочим: один ключ, один адрес, много моделей.

    **Главная особенность, ради которой стоит читать эту докстроку.** Через
    шлюз наша несущая мысль обостряется: возможность оказывается свойством не
    пары, а тройки — (endpoint, модель, ПРОВАЙДЕР). Одну и ту же модель шлюз
    раздаёт от разных поставщиков, и умеют они разное. Проверено запросом к
    `/api/v1/models/deepseek/deepseek-v3.2/endpoints` 2026-08-30: из 14
    провайдеров четверо (GMICloud, DigitalOcean, Novita, SambaNova) не
    поддерживают `response_format`, трое не поддерживают `tools`, а окно
    контекста у них гуляет от 32 768 до 163 840 токенов. Документация говорит
    то же прямо: «Support is determined per endpoint, not just per model»
    (https://openrouter.ai/docs/guides/features/structured-outputs).

    Две разные беды, которые легко перепутать. Если структурированного вывода
    не умеет **модель**, шлюз отвечает ошибкой — это видно сразу. А если его не
    умеет **провайдер** внутри умеющей модели, то по умолчанию он получает
    запрос и **молча выбрасывает непонятое поле**: «providers that don't
    support all the LLM parameters specified in your request can still receive
    the request, but will ignore unknown parameters»
    (https://openrouter.ai/docs/guides/routing/provider-selection). Вторая беда
    и опасна: маршрутизация по умолчанию балансирует по цене, то есть тянет
    ровно к самому дешёвому провайдеру, а у самых дешёвых возможностей меньше
    всего. Проба зафиксировала бы ступень `json_schema`, попав на умеющего, а
    боевой запрос уехал бы к неумеющему и вернул свободный текст вместо
    объекта — без единой ошибки, по которой это было бы заметно.

    Отсюда `provider: {"require_parameters": True}` в extra_body: он запрещает
    маршрутизацию к провайдерам, которые не поддерживают все параметры
    запроса. Цена решения — 503 «нет подходящего провайдера» вместо тихой
    деградации. Это ровно тот обмен, который слою нужен: громкий отказ лучше
    молчаливой лжи. Кто хочет прибить одного провайдера намертво, добавляет
    `provider: {"only": ["google-ai-studio"], "allow_fallbacks": False}`.

    Что ПРОВЕРЕНО по первоисточникам 2026-08-30 (и потому написано как знание):

      * адрес и протокол: `https://openrouter.ai/api/v1/chat/completions`,
        спецификация OpenAI; `/api/v1/models` отдаёт список моделей с ценами,
        так что шаг 1 пробы работает и цены можно заполнять автоматически;
      * форма ошибки: `{"error": {"code": <число>, "message": ..., "metadata":
        ...}}`, причём `code` совпадает с HTTP-кодом (проверено живым
        запросом без ключа: 401 и такое же тело). Коды: 400, 401, 402, 403,
        408, 429, 502, 503;
      * **ошибка может приехать при HTTP 200** — «any error occurred while the
        LLM is producing the output will be emitted in the response body or as
        an SSE data event». Ради этого в openai_compat заведён разбор поля
        `error` внутри потока;
      * `usage` приходит ВСЕГДА и в потоке тоже, а `stream_options:
        {include_usage: true}` и `usage: {include: true}` объявлены
        устаревшими и «have no effect»
        (https://openrouter.ai/docs/cookbook/administration/usage-accounting).
        Поэтому `usage_in_stream=True`, а `usage_stream_flag=False`: лишнее
        поле — риск на ровном месте, а пользы от него больше нет;
      * счётчики кэша: `prompt_tokens_details.cached_tokens` (чтение) и
        `prompt_tokens_details.cache_write_tokens` (запись), и **кэш посчитан
        ВНУТРИ входа**: в примере документации `prompt_tokens: 10339` при
        `cached_tokens: 10318`, а `total_tokens` равен сумме входа и выхода.
        Значит `cache_inside_input=True` здесь не осторожная догадка, как у
        DeepSeek, а прочитанное в первоисточнике;
      * заголовки `HTTP-Referer` и `X-OpenRouter-Title` (он же `X-Title`)
        **необязательны** для самого вызова: они нужны только чтобы приложение
        попало в рейтинги openrouter.ai. Шлём из них только имя: адреса у
        проекта пока нет, а выдуманный `HTTP-Referer` — это неверные сведения
        о себе, уезжающие наружу в каждом живом запросе. Появится адрес —
        добавится строкой: `openrouter(extra_headers={..., "HTTP-Referer": ...})`.

    Что ЗАЯВЛЕНО и покажет живая проба (`python -m llm probe --preset
    openrouter`):

      * `structured_output: json_object` — занижено намеренно, как у DeepSeek.
        По таблице моделей `google/gemini-2.5-flash-lite` поддерживает и
        `structured_outputs`, и `response_format`, то есть лестница на пробе
        должна подняться до `json_schema`. Но «поддерживает» в таблице шлюза и
        «сработало на нашей схеме» — разные утверждения, и второе проверяется
        только вызовом;
      * `tools: True` — протокол их описывает и провайдеры объявляют; зовёт ли
        модель инструмент на самом деле, показывает шаг 5;
      * `prefix_cache: automatic` — у Gemini 2.5 и новее кэш неявный, без
        пометок. Шлюз к тому же держит «липкую» маршрутизацию (10 минут), но
        шаг 6 на автокэше неубедителен по определению;
      * `effort: False` — «без thinking, просто api», как решено по DeepSeek.
        У модели по умолчанию размышления выключены; при смене модели на
        `openai/gpt-5-mini` это перестанет быть правдой (там размышления
        обязательны), и поле придётся менять вместе с моделью.

    Ещё три мелочи, о которые спотыкаются не сразу:

      * `strict: true` — просьба, а не гарантия: «some guarantee
        schema-conforming output, while others translate your schema into
        their own structured-output format or treat it as a strong hint». Наш
        валидатор на всех четырёх ступенях остаётся обязательным, и это ровно
        то, как лестница (А.3) и устроена;
      * у части моделей в `/api/v1/models` есть `pricing.overrides` — цена
        меняется после порога длины промпта (например, дороже после 200 000
        входных токенов) или по часам UTC. У четырёх моделей отсюда его на
        2026-08-30 нет, но при смене модели это надо проверять: длинный вход —
        как раз наш случай;
      * кэш живёт «липкой» маршрутизацией: шлюз десять минут возит запросы к
        тому же провайдеру, узнавая разговор по хэшу первых сообщений.
        Раскладка Б.5 с её постоянным порядком кусков этому помогает сама
        собой. Но `provider.order` липкость выключает — потому его здесь и нет.

    Цены — снимок на 2026-08-30 из `/api/v1/models` и только для моделей из
    OPENROUTER_МОДЕЛИ. Незнакомая модель остаётся без цен намеренно.
    """
    known = OPENROUTER_МОДЕЛИ.get(model, {})
    spec = EndpointSpec(
        id=endpoint_id,
        label="OpenRouter",
        protocol="openai",
        base_url="https://openrouter.ai/api",
        model=model,
        api_key_env="OPENROUTER_API_KEY",
        api_key_file="~/.config/koritsu/openrouter.key",
        context_tokens=known.get("context"),
        max_output_tokens=known.get("max_output", 4096),
        declared=Declared(
            structured_output=Structured.JSON_OBJECT,
            streaming=True,
            prefix_cache=PrefixCache.AUTOMATIC,
            effort=False,                       # «без thinking, просто api»
            # То же решение и то же основание, что у deepseek (см. там): проба
            # 2026-09-03, устояло 2 из 2, канал исполняется повтором указания
            # после недоверенного текста. Оговорка сильнее, чем у deepseek:
            # OpenRouter — посредник, и за одним именем модели у него может
            # стоять разный поставщик. Значит измеряли поведение конкретного
            # прогона, а не свойство endpoint'а навсегда.
            operator_channel=OperatorChannel.MESSAGES_SYSTEM,
            tools=True,
            usage_in_stream=True,               # приходит всегда, флага не надо
            usage_stream_flag=False,            # флаг объявлен устаревшим
            cache_inside_input=True,            # прочитано в документации
        ),
        prices=known.get("prices") or Prices(),
        chars_per_token=known.get("chars_per_token", 3.0),
        extra_headers={
            # Необязательная визитка для рейтингов openrouter.ai: ни на
            # маршрутизацию, ни на возможности она не влияет.
            # `X-OpenRouter-Title` — каноническое имя; прежнее `X-Title`
            # шлюз тоже принимает, но как совместимость со старым.
            # `HTTP-Referer` здесь НЕТ намеренно: адреса у проекта пока не
            # существует, а заглушка уезжала бы наружу в каждом живом запросе
            # как заведомо неверные сведения о себе. Необязательный заголовок
            # лучше не слать, чем слать неправду; добавить, когда адрес будет.
            "X-OpenRouter-Title": "Koritsu",
        },
        extra_body={
            # Единственное поле, которое здесь работает, а не украшает:
            # без него провайдер без `response_format` молча вернёт текст.
            "provider": {"require_parameters": True},
        },
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


def claude_cli_proba(endpoint_id: str = "ep_claude_cli_proba", model: str = "haiku",
                     **overrides) -> EndpointSpec:
    """Claude через команду `claude` — **временный пресет для проб, не боевой**.

    Решение владельца 2026-08-31: ключа к API нет, а пробовать надо уже сейчас,
    поэтому kadai ходит к Haiku через командную строку. Имя пресета и метка
    endpoint'а названы так, чтобы это было видно в каждой записи журнала и в
    каждом списке endpoint'ов: не «claude», а «claude_cli_proba».

    Как устроен вызов, чем отобраны инструменты, что решено с загрязнённым
    учётом и чего этот путь не умеет в принципе — всё в докстроке
    `llm.backends.cli`. Здесь только заполненная форма Б.3 и пометки, что в ней
    знание, а что заявка.

    `base_url` у протокола `cli` — **имя или путь команды**, а не адрес: «куда
    идти» здесь и есть команда. Ключа нет: вход у команды свой, по подписке, —
    поэтому `api_key_env` и `api_key_file` пусты, и `resolve_key` не зовётся.

    Что ПРОВЕРЕНО живым вызовом 2026-08-31 (и потому написано как знание):

      * `structured_output: text` — гарантий формата нет. `--json-schema` у
        команды есть и работает, но внутри он инструмент, а ключи свойств
        схемы инструмента Anthropic принимает только латиницей
        (`^[a-zA-Z0-9_.-]{1,64}$`); ключи схемы отчёта Koritsu — имена тегов
        шаблона, то есть кириллица. Без схемы модель заворачивает ответ в забор
        ```json, и его снимает `structured.extract_json`;
      * `streaming: False` — `--output-format stream-json` существует, но это
        агентский протокол событий самой Claude Code, а не поток модели; сейчас
        он не берётся (решение объяснено в докстроке бэкенда). Наружу поток
        по-прежнему работает: один кусок текста, следом usage и stop;
      * `prefix_cache: none` — с нашим системным промптом `cache_creation` и
        `cache_read` равны нулю, ставить брейкпойнт нечем. Весь манифест с
        материалами оплачивается полностью на каждом вызове;
      * `tools: False` — свои инструменты у команды выключены нами намеренно, а
        наши ей передать нечем. Попытка — громкий отказ, не молчание;
      * `usage_contaminated: True` — счётчики описывают весь запуск команды,
        включая её служебные обращения к модели. Пометка ставит
        `usage_with_agent_overhead` в `degraded` каждой записи журнала;
      * `cache_inside_input: False` — кэш приходит отдельными полями, как у
        протокола Anthropic, вычитать нечего;
      * `context_tokens` / `max_output_tokens` — 200 000 и 32 000, взяты из
        `modelUsage.contextWindow` и `maxOutputTokens` живого ответа.

    Что ЗАЯВЛЕНО и живьём НЕ проверено:

      * `operator_channel: system_first` — занижено намеренно. Механика на самом
        деле сильнее: `--system-prompt-file` **заменяет** собственный промпт
        Claude Code, а не дописывается к нему, значит наши правила едут первыми
        и одни (в отличие от `--append-system-prompt`, который владелец называл
        деградацией, — им мы не пользуемся). Но что указание оттуда весомее
        текста студента, никто не проверял, а завышенная заявка на операторский
        канал — это защита, которой нет;
      * `effort: False` — флаг `--effort` есть, не пробовался. Наблюдение мимо
        заявки: Haiku тратит токены на размышления и без просьбы (52–288
        `thinking_tokens` в замерах), так что «без thinking» здесь неправда в
        любом случае — они видны в `Usage.reasoning`.

    `own_key=True`: расход идёт по подписке владельца, а не против тарифа
    продукта. Журнал его считает и показывает, но в лимит не берёт.

    Цены не заполнены намеренно: платится подпиской, а не за токены, и табличка
    «цена за миллион» описывала бы не ту сделку. Настоящая цифра запуска —
    `raw_usage["учёт_koritsu"]["деньги_за_весь_запуск_usd"]`.

    Пробы Б.4 у этого пресета нет: она построена на POST по HTTP, которого у
    протокола `cli` не существует. `python -m llm probe --preset claude_cli_proba`
    честно так и скажет, а не притворится проверкой.
    """
    spec = EndpointSpec(
        id=endpoint_id,
        label="Claude CLI (проба, не боевой)",
        protocol="cli",
        base_url="claude",             # у протокола cli это команда, а не адрес
        model=model,
        api_key_env=None,              # вход у команды свой, по подписке
        api_key_file=None,
        context_tokens=200000,
        max_output_tokens=32000,
        declared=Declared(
            structured_output=Structured.TEXT,
            streaming=False,
            prefix_cache=PrefixCache.NONE,
            effort=False,
            operator_channel=OperatorChannel.SYSTEM_FIRST,
            tools=False,
            usage_in_stream=True,       # счётчики приезжают в том же JSON
            usage_stream_flag=False,    # флага у этого провода нет
            cache_inside_input=False,
            usage_contaminated=True,
        ),
        prices=Prices(),
        own_key=True,
        # Команда сама ходит к API и сама повторяет временные беды; наш таймаут
        # поверх её собственного должен быть заметно длиннее сетевого.
        timeout_s=300.0,
        chars_per_token=3.0,
    )
    for name, value in overrides.items():
        setattr(spec, name, value)
    return spec


PRESETS = {"deepseek": deepseek, "anthropic": anthropic,
           "openrouter": openrouter, "claude_cli_proba": claude_cli_proba}


def make(name: str, **overrides) -> EndpointSpec:
    factory = PRESETS.get(name)
    if factory is None:
        raise KeyError(f"нет пресета {name!r}; есть: {', '.join(sorted(PRESETS))}")
    return factory(**overrides)


__all__ = ["deepseek", "anthropic", "openrouter", "claude_cli_proba",
           "OPENROUTER_МОДЕЛИ", "PRESETS", "make"]
