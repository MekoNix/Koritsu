"""
profile — вид работы данными: какие разделы бывают, какие обязательны, какие стадии нужны.

Профиль отвечает на «а если завтра лабораторная» файлом, а не веткой `if`
(записка Б.3, решение владельца Л.6). Здесь — только чтение этих данных и
проверка сочинённой моделью структуры против них.

**Тип тега назначает профиль, а не модель.** Это первое из четырёх сит записки
В.4 и самое дешёвое из всех: `manifest_from_template` предлагает тип по метке и
помечает догадку (`guessed`), умолчание — `markdown`. Раздел, объявленный
моделью как схема, но названный так, что метка не совпала, стал бы markdown'ом:
модель написала бы про схему прозой, а отчёт собрался бы. Профиль знает тип по
виду раздела, и угадывать становится нечего.

**Список видов закрыт.** Модель, которую просят сочинить структуру курсовой,
почти наверняка предложит «Приложение А» и «Список литературы». Ни приложений по
ГОСТ, ни библиографии в `hokoku` нет; молча они стали бы обычными
markdown-тегами — заголовок есть, нумерации «А.1» и ссылок «[3]» нет. Поэтому
запрещённые виды отвергаются с текстом, объясняющим, чего именно не будет, до
того, как начнётся дорогая стадия.

**Два предварительных сита — копии чужих правил, и это сказано вслух.** Ключ
раздела нормализуется NFC (сила — `hokoku.tags.norm_key`) и обязан быть
выразим тегом (сила — `hokoku.tags.TAG_RE`: ни пробелов, ни `{}:|#/`).
Окончательное слово в обоих случаях за `hokoku`, но проверить надо здесь:
иначе два ключа схлопнутся в один тег или ключ не станет тегом вовсе, и
узнаем мы об этом от `check_manifest` — уже после того, как DOCX собран.
Дверь `orchestrator.norm_key` убрала бы копию; пока её нет, копия помечена.

Чего здесь нет: сочинения структуры (это модель через шов «структура») и
построения DOCX (шов «шаблон»).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from importlib import resources

import yaml

from .errors import KadaiError, hint, problem

# Поля файла профиля. Неизвестное поле — ошибка с подсказкой, а не молчание:
# `volumes:` вместо `volume:` не ограничивал бы ничего, и заметить это было бы
# нечем (тот же приём, что у `manifest.LIMIT_KEYS`).
PROFILE_KEYS = ("name", "title", "base", "stages", "needs", "volume", "kinds", "forbidden")
KIND_KEYS = ("type", "required", "many", "numbered", "limits")

# Поля раздела в сочинённой структуре. Всё остальное модель придумала сама, и
# принять это молча значило бы отдать ей право решать за профиль.
SECTION_KEYS = ("key", "title", "kind", "prompt")

# Знаки, которых не может быть в ключе тега. Сила — `hokoku.tags.TAG_RE`
# (`\{\{\s*([^\s{}:|#/]+)…`): ключ с пробелом или двоеточием тегом не станет.
BAD_KEY_CHARS = set(" \t\n\r{}:|#/")


def norm_key(key: str) -> str:
    """Ключ в NFC без краёв. Копия `hokoku.tags.norm_key` — намеренная, см. заголовок модуля.

    Без неё два раздела, различающиеся только нормализацией «й», станут одним
    тегом при сборке шаблона, а `values_from_json` сочтёт это ошибкой записи —
    когда шаблон уже собран и оплачен.
    """
    return unicodedata.normalize("NFC", str(key).strip())


@dataclass(frozen=True)
class Kind:
    """Вид раздела: что он такое в терминах тега отчёта."""

    name: str
    type: str = "markdown"
    required: bool = False
    many: bool = False
    numbered: bool = True
    limits: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """Вид работы целиком. Неизменяемый: профиль — данные, и правка его на месте
    посреди прогона означала бы, что половина работы сделана по одному виду, а
    половина по другому."""

    name: str
    title: str
    base: str
    stages: tuple
    needs: dict = field(default_factory=dict)
    volume: dict = field(default_factory=dict)
    kinds: dict = field(default_factory=dict)        # имя вида → Kind
    forbidden: dict = field(default_factory=dict)    # имя вида → почему нельзя

    def kind(self, name: str) -> Kind:
        try:
            return self.kinds[name]
        except KeyError:
            raise KadaiError(f'вида раздела "{name}" в профиле "{self.name}" нет'
                             f'{hint(name, self.kinds)}') from None


@dataclass(frozen=True)
class Section:
    """Раздел сочинённой структуры, уже сверенный с профилем.

    Отдаётся шву «шаблон» списком: `make_template` строит по нему DOCX и
    манифест. Тип, лимиты и нумерация здесь уже не от модели, а от профиля —
    именно поэтому объект и заводится, а не таскается сырой словарь.
    """

    key: str
    title: str
    kind: str
    type: str
    required: bool
    numbered: bool
    limits: dict = field(default_factory=dict)
    prompt: str = ""


def available() -> list[str]:
    """Какие профили есть. Список из файлов, а не из константы: константа разошлась бы."""
    return sorted(p.name[:-5] for p in resources.files(__package__).joinpath("profiles").iterdir()
                  if p.name.endswith(".yaml"))


def load(name: str) -> Profile:
    """Профиль по имени.

    `importlib.resources`, а не `os.path.join`: правило разреза (записка Б.2)
    проверяется грепом, и `os.path.join` в `kadai` не должно встречаться вовсе —
    иначе первая же строка с путём открывает дорогу второму хранилищу.
    """
    if name not in available():
        raise KadaiError(f'профиля "{name}" нет{hint(name, available())}; '
                         f'есть: {", ".join(available())}')
    text = resources.files(__package__).joinpath("profiles", f"{name}.yaml").read_text("utf-8")
    return parse(yaml.safe_load(text), source=f"{name}.yaml")


def parse(raw: dict, *, source: str = "профиль") -> Profile:
    """Разбор профиля из уже прочитанного YAML. Неизвестное поле — ошибка."""
    if not isinstance(raw, dict):
        raise KadaiError(f"{source}: ожидался словарь, пришло {type(raw).__name__}")
    for field_name in raw:
        if field_name not in PROFILE_KEYS:
            raise KadaiError(f"{source}: неизвестное поле {field_name!r}"
                             f"{hint(field_name, PROFILE_KEYS)}")
    kinds = {}
    for kind_name, body in (raw.get("kinds") or {}).items():
        body = body or {}
        for key in body:
            if key not in KIND_KEYS:
                raise KadaiError(f"{source}: вид {kind_name!r}: неизвестное поле {key!r}"
                                 f"{hint(key, KIND_KEYS)}")
        kinds[kind_name] = Kind(name=kind_name, **body)
    forbidden = dict(raw.get("forbidden") or {})
    both = sorted(set(kinds) & set(forbidden))
    if both:
        # Вид, разрешённый и запрещённый одновременно, — это профиль, который
        # отвечает на один вопрос дважды. Молча выбрать один из ответов нельзя:
        # выбор был бы наш, а не владельца профиля.
        raise KadaiError(f"{source}: виды объявлены и в kinds, и в forbidden: {', '.join(both)}")
    return Profile(name=raw.get("name") or "", title=raw.get("title") or "",
                   base=raw.get("base") or "", stages=tuple(raw.get("stages") or ()),
                   needs=dict(raw.get("needs") or {}), volume=dict(raw.get("volume") or {}),
                   kinds=kinds, forbidden=forbidden)


def base_template(profile: Profile) -> bytes:
    """Байты заготовки DOCX профиля — или отказ по шву «шаблон».

    Заготовки сегодня нет ни у одного профиля, и взять её негде: собрать
    титульник кафедры нечем, пока в `hokoku` нет построения документа без
    шаблона. Молча вернуть пустые байты нельзя — `Project.create` принял бы их,
    манифест вышел бы пустым, а отчёт собрался бы из одного листа.
    """
    from .seams import not_ready          # ленивый импорт: seams знает про profile
    if not profile.base:
        raise not_ready("шаблон", f'профиль "{profile.name}" заготовки не называет.')
    path = resources.files(__package__).joinpath("profiles", profile.base)
    if not path.is_file():
        raise not_ready("шаблон", f"заготовки {profile.base} рядом с профилем нет.")
    return path.read_bytes()


# ── сито 1: структура против профиля ─────────────────────────────────────────

def check_structure(profile: Profile, structure) -> list:
    """Замечания к сочинённой структуре. Пустой список — структура годна.

    Первое из четырёх сит записки В.4 и самое дорогое по цене пропущенной беды:
    оно ловит «структура сочинена по неверно понятому условию» настолько,
    насколько это вообще ловится техникой. Токенов не стоит ни одно.

    Возвращает замечания, а не бросает: их показывают человеку и отдают модели
    на переделку целиком, а для этого нужны все сразу, а не первое.
    """
    out: list = []
    sections = (structure or {}).get("sections") if isinstance(structure, dict) else None
    if not isinstance(sections, list) or not sections:
        return [problem("нет_разделов", "структура пуста: разделов нет вовсе")]

    seen: dict = {}
    counts: dict = {}
    for i, raw in enumerate(sections):
        if not isinstance(raw, dict):
            out.append(problem("раздел_не_словарь", f"раздел №{i + 1}: ожидался словарь"))
            continue
        for extra in raw:
            if extra not in SECTION_KEYS:
                out.append(problem("лишнее_поле", f"раздел №{i + 1}: поле {extra!r} "
                                                  f"профилем не предусмотрено{hint(extra, SECTION_KEYS)}"))
        kind = raw.get("kind")
        if kind in profile.forbidden:
            out.append(problem("вид_запрещён", profile.forbidden[kind], key=raw.get("key")))
            continue
        if kind not in profile.kinds:
            out.append(problem("вид_неизвестен",
                               f'вида раздела "{kind}" в профиле "{profile.name}" нет'
                               f"{hint(kind, list(profile.kinds) + list(profile.forbidden))}",
                               key=raw.get("key")))
            continue
        counts[kind] = counts.get(kind, 0) + 1
        out += _check_key(raw.get("key"), i, seen)
    out += _check_counts(profile, counts)
    out += _check_volume(profile, len(sections))
    out += _check_needs(profile, counts)
    return out


def _check_key(key, i: int, seen: dict) -> list:
    """Ключ: непустой, выразимый тегом, уникальный после NFC. Сила — hokoku, см. заголовок."""
    out = []
    if not isinstance(key, str) or not key.strip():
        return [problem("нет_ключа", f"раздел №{i + 1}: ключ пуст")]
    norm = norm_key(key)
    bad = sorted(BAD_KEY_CHARS & set(norm))
    if bad:
        out.append(problem("ключ_не_тег", f'ключ "{key}" не станет тегом: в нём '
                                          f"{', '.join(repr(c) for c in bad)}", key=key))
    if norm in seen:
        # Схлопывание ключей — самая тихая из бед этого сита: шаблон соберётся,
        # тег будет один, а разделов человек ждёт два.
        out.append(problem("ключ_повторён", f'ключ "{key}" совпадает с "{seen[norm]}" '
                                            f"после нормализации", key=key))
    else:
        seen[norm] = key
    return out


def _check_counts(profile: Profile, counts: dict) -> list:
    out = []
    for name, kind in profile.kinds.items():
        n = counts.get(name, 0)
        if kind.required and n == 0:
            out.append(problem("нет_обязательного", f'в структуре нет раздела вида "{name}", '
                                                    f'а профиль "{profile.name}" его требует'))
        if not kind.many and n > 1:
            out.append(problem("вид_повторён", f'вид "{name}" встречается {n} раза, '
                                               f"а он бывает один"))
    return out


def _check_volume(profile: Profile, n: int) -> list:
    """Только число разделов. Знаки проверяются на готовых значениях лимитами манифеста —
    здесь их проверить нечем, значений ещё нет."""
    lo, hi = profile.volume.get("sections_min"), profile.volume.get("sections_max")
    if lo is not None and n < lo:
        return [problem("мало_разделов", f"разделов {n}, а профиль ждёт не меньше {lo}")]
    if hi is not None and n > hi:
        return [problem("много_разделов", f"разделов {n}, а профиль ждёт не больше {hi}")]
    return []


def _check_needs(profile: Profile, counts: dict) -> list:
    """Обязательное по существу: курсовая без единого листинга — это не оформление,
    а признак того, что условие поняли неверно."""
    out = []
    by_type = {name: counts.get(name, 0) for name in profile.kinds}
    def total(type_name):
        return sum(n for name, n in by_type.items() if profile.kinds[name].type == type_name)
    if profile.needs.get("code") and total("code") == 0:
        out.append(problem("нет_кода", "работа этого вида требует кода, а разделов с "
                                       "листингом в структуре нет"))
    if profile.needs.get("diagrams") and total("diagram") == 0:
        out.append(problem("нет_схем", "работа этого вида требует схем, а разделов со "
                                       "схемой в структуре нет"))
    return out


def sections_of(profile: Profile, structure) -> list[Section]:
    """Структура → разделы с типами и лимитами профиля. На ошибке — отказ, а не половина.

    Половина разделов — худшее из возможного: шаблон собрался бы, отчёт вышел бы
    короче задуманного, и объяснить, куда делись разделы, было бы нечем.
    """
    problems = [p for p in check_structure(profile, structure) if p["level"] == "error"]
    if problems:
        raise KadaiError("структура не годится: " + "; ".join(p["message"] for p in problems))
    out = []
    for raw in structure["sections"]:
        kind = profile.kind(raw["kind"])
        out.append(Section(key=norm_key(raw["key"]), title=str(raw.get("title") or raw["key"]),
                           kind=kind.name, type=kind.type, required=kind.required,
                           numbered=kind.numbered, limits=dict(kind.limits),
                           prompt=str(raw.get("prompt") or "")))
    return out


__all__ = ["Profile", "Kind", "Section", "PROFILE_KEYS", "SECTION_KEYS",
           "available", "load", "parse", "base_template", "check_structure",
           "sections_of", "norm_key"]
