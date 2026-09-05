"""
report — build_report: чистый JSON внутрь, чистый JSON наружу.

Единица работы для очереди, скрипта и будущего endpoint'а: у неё есть вход (задание),
выход (результат), бюджет времени и отменяемость по таймауту. Между `render` и заданием
девять действий, которые иначе каждый вызывающий напишет сам и по-своему: достать шаблон,
проверить его (`render` этого не делает — шаблон с макросом проехал бы насквозь), разобрать
значения, достать артефакты, проверить потолки, позвать `render` с правильными умолчаниями,
собрать PDF не роняя DOCX, положить файлы и переложить результат в JSON.

Умолчания намеренно строже, чем у `render`: это точка входа для недоверенного ввода —
on_error="skip", strict_paths=True, короткий таймаут схемы, validate_docx всегда.

Готовые файлы наружу байтами не отдаём: тогда результат перестал бы быть JSON, его нельзя
было бы ни в журнал записать, ни в очередь положить, ни отдать по HTTP как есть. Отсюда два
режима, ровно один за вызов: `workdir` — вызывающий называет каталог и получает в ответе
имена файлов; `store_artifact` — вызывающий даёт функцию `(name, data, kind) -> artifact_id`,
байты уезжают в его хранилище, а в ответе идентификаторы и ни одного пути.

Хранилища внутри `hokoku` нет и не будет: пакет остаётся библиотекой без состояния. Про
`materials`, `out/` и SQLite он не знает ничего — знает только, что байты кому-то отдал и
получил взамен строку, которая проходит `ARTIFACT_RE` и потому годится обратно во вход.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import time

from .model import (Blocks, Code, Diagram, Formula, HokokuError, Image, Markdown, Problem, Table,
                    Text, Toc)
from .pdf import docx_bytes_to_pdf
from .render import render
from .safety import DocxValidationError, safe_name, validate_docx
from .styles import get_style
from .tags import extract_tags
from .wire import ARTIFACT_RE, WIRE_VERSION, WireError, values_from_json

# Потолки нужны (модель попросит таблицу на 10 000 строк не задумываясь), но щедрые: ни один
# не должен срабатывать на обычном отчёте — журнал замеров на 300 строк это обычный
# отчёт. Задание может попросить меньше, больше — нет.
HARD_LIMITS = {"max_values": 1000, "max_value_chars": 200_000, "max_table_rows": 2000,
               "max_table_cols": 64, "max_blocks_items": 500,
               "max_artifact_bytes": 64 * 1024 * 1024,
               "max_total_artifact_bytes": 256 * 1024 * 1024}
DEFAULT_LIMITS = dict(HARD_LIMITS)

# Таймауты, в отличие от потолков, по умолчанию короче предела: незадавшаяся схема не должна
# съедать бюджет очереди целиком.
HARD_TIMEOUTS = {"drawio": 300.0, "pdf": 300.0, "total": 900.0}
DEFAULT_TIMEOUTS = {"drawio": 60.0, "pdf": 90.0, "total": 300.0}

_JOB_KEYS = ("wire_version", "template", "values", "options")
_TEMPLATE_KEYS = ("artifact", "sha256", "manifest_version")
_OPTION_KEYS = ("on_error", "outputs", "strict_paths", "name", "style", "limits", "timeouts")
_OUTPUTS = ("docx", "pdf")


class _JobError(Exception):
    """Отказ уровня задания: документ не собран, в ответе `error.code`."""

    def __init__(self, code: str, message: str, key: str | None = None):
        super().__init__(message)
        self.code, self.key = code, key


def build_report(job: dict, *,
                 resolve_artifact,                  # (artifact_id) -> bytes; обязателен
                 store_artifact=None,               # (name, data, kind) -> artifact_id
                 workdir: str | None = None,        # куда класть файлы, если хранилища нет
                 images_dir: str | None = None,     # каталог файлов проекта для ![](имя)
                 ) -> dict:
    """Задание JSON → результат JSON. Ровно один из `store_artifact` и `workdir`.

    Два режима — не удобство, а развилка «чистый JSON наружу» против «ни хранилища
    внутри»: готовый DOCX это байты, а байты нельзя ни положить в JSON, ни назвать
    идентификатором, не имея хранилища. `workdir` — путь скрипта и лаборатории
    (`outputs.docx.file`, имя без пути), `store_artifact` — путь службы
    (`outputs.docx.artifact`, и на диске рядом с вызывающим не появляется ничего).

    Задать оба сразу или ни одного — `ValueError`, а не догадка: молча выбранный режим
    это готовый отчёт, оставшийся не там, где его будут искать.

    `ok` означает ровно одно: DOCX собран. Отчёт с тремя записями в `errors` и одним
    `unfilled` — это `ok: true`: файл есть, и его можно показать человеку с пометками.
    """
    t0 = time.perf_counter()
    if store_artifact is not None and workdir is not None:
        raise ValueError("нужен ровно один из store_artifact и workdir, а заданы оба: "
                         "workdir кладёт файлы в каталог, store_artifact — в хранилище")
    if store_artifact is None and workdir is None:
        raise ValueError("нужен ровно один из store_artifact и workdir, а не задан ни один: "
                         "готовый DOCX это байты, и деть их без одного из двух некуда")
    if store_artifact is not None and not callable(store_artifact):
        raise ValueError("store_artifact — функция (name, data, kind) -> artifact_id")
    if not callable(resolve_artifact):
        raise ValueError("resolve_artifact обязателен: байты шаблона и картинок брать больше неоткуда")
    timings: dict = {}
    try:
        return _build(job, resolve_artifact, store_artifact, workdir, images_dir, t0, timings)
    except _JobError as e:
        out = {"ok": False, "wire_version": WIRE_VERSION,
               "error": {"code": e.code, "message": str(e)},
               "timings_ms": _timings(timings, t0)}
        if e.key is not None:
            out["error"]["key"] = e.key
        return out


def _build(job, resolve_artifact, store_artifact, workdir, images_dir, t0,
           timings) -> dict:
    if not isinstance(job, dict):
        raise _JobError("bad_job", f"задание должно быть объектом JSON, а не {type(job).__name__}")
    _known_keys(job, _JOB_KEYS, "задании")
    version = job.get("wire_version", WIRE_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise _JobError("bad_job", "wire_version — целое число")
    if version != WIRE_VERSION:
        # версия конверта и версия значения проверяются независимо и никогда не спорят:
        # задание версии 1 со значением версии 2 законно, значение просто полежало дольше
        raise _JobError("unknown_wire_version",
                        f"задание версии {version}, hokoku знает версию {WIRE_VERSION}")
    opts = _options(job.get("options") or {})
    artifacts = _Artifacts(resolve_artifact, opts["limits"])

    mark = time.perf_counter()
    template, template_info = _template(job.get("template"), artifacts)
    timings["template"] = _ms(mark)

    mark = time.perf_counter()
    try:
        values, errors = values_from_json(job.get("values") or {}, resolve_artifact=artifacts)
    except WireError as e:
        # не набор значений, а список или строка: это форма задания, а не беда одного тега
        raise _JobError("bad_job", f"values: {e}") from None
    if artifacts.violation:
        raise _JobError("limit_exceeded", artifacts.violation)
    _check_limits(values, opts["limits"])
    timings["wire"] = _ms(mark)
    if errors and opts["on_error"] == "raise":
        raise _JobError("render_failed", errors[0]["message"], errors[0]["key"])

    left = opts["timeouts"]["total"] - (time.perf_counter() - t0)
    if left <= 0:
        raise _JobError("timeout", "бюджет задания вышел до сборки (timeouts.total)")
    mark = time.perf_counter()
    try:
        res = render(template, values, None, images_dir=images_dir, style=opts["style"],
                     strict_paths=opts["strict_paths"], on_error=opts["on_error"],
                     drawio_timeout=min(opts["timeouts"]["drawio"], left))
    except Exception as e:                                   # noqa: BLE001 — наружу только JSON
        raise _JobError("render_failed", f"{type(e).__name__}: {e}") from None
    timings["render"] = _ms(mark)
    errors += [{"key": e.get("key"), "stage": "render", "message": e.get("message")}
               for e in res.errors]

    outputs = _write_outputs(res.data, opts, store_artifact, workdir, t0,
                             errors, timings)
    return {"ok": True, "wire_version": WIRE_VERSION, "outputs": outputs,
            "template": template_info,
            "unfilled": list(res.unfilled), "unknown_keys": list(res.unknown_keys),
            "errors": errors, "refs": dict(res.refs),
            "unresolved_refs": list(res.unresolved_refs),
            "counts": {"figures": res.figures, "tables": res.tables, "formulas": res.formulas,
                       "listings": res.listings},
            "timings_ms": _timings(timings, t0),
            "warnings": [w.to_dict() for w in _warnings(res, template)]}


# ── шаблон, опции, потолки ────────────────────────────────────────────────────

def _template(tpl, artifacts) -> tuple[bytes, dict]:
    if not isinstance(tpl, dict):
        raise _JobError("bad_job", 'нет "template": {"artifact": "…"} — шаблон обязателен')
    _known_keys(tpl, _TEMPLATE_KEYS, "template")
    art = tpl.get("artifact")
    if not isinstance(art, str) or not art:
        raise _JobError("bad_job", 'template.artifact — идентификатор шаблона в хранилище')
    try:
        data = artifacts(art)
    except Exception as e:                                   # noqa: BLE001 — хранилище чужое
        if artifacts.violation:
            raise _JobError("limit_exceeded", artifacts.violation) from None
        raise _JobError("bad_template", f"шаблон {art!r} не достался: {type(e).__name__}: {e}") from None
    digest = hashlib.sha256(data).hexdigest()
    want = tpl.get("sha256")
    if want is not None and str(want).lower() != digest:
        # шаблон подменили: собирать по нему — значит выдать не тот документ за тот
        raise _JobError("bad_template", f"sha256 шаблона не сошлась: ждали {want}, получили {digest}")
    try:
        validate_docx(data)
    except DocxValidationError as e:
        raise _JobError("template_rejected", str(e)) from None
    info = {"artifact": art, "sha256": digest}
    if "manifest_version" in tpl:
        # build_report манифест не проверяет (это дело validate), но версия обязана
        # доехать до журнала: иначе непонятно, по какому манифесту собран отчёт
        info["manifest_version"] = tpl["manifest_version"]
    return data, info


def _options(opts: dict) -> dict:
    if not isinstance(opts, dict):
        raise _JobError("bad_job", "options — объект JSON")
    _known_keys(opts, _OPTION_KEYS, "options")
    on_error = opts.get("on_error", "skip")
    if on_error not in ("skip", "raise"):
        raise _JobError("bad_job", f'options.on_error: "skip" или "raise", а не {on_error!r}')
    outputs = opts.get("outputs", ["docx"])
    if not isinstance(outputs, list) or not outputs or any(o not in _OUTPUTS for o in outputs):
        raise _JobError("bad_job", f'options.outputs — непустой список из {", ".join(_OUTPUTS)}')
    strict = opts.get("strict_paths", True)
    if not isinstance(strict, bool):
        raise _JobError("bad_job", "options.strict_paths — true или false")
    name = opts.get("name", "otchet")
    if not isinstance(name, str):
        raise _JobError("bad_job", "options.name — строка, основа имени файлов")
    style = opts.get("style") or {}
    if not isinstance(style, dict):
        raise _JobError("bad_job", "options.style — объект, как разделы styles.yaml")
    try:
        get_style(style)                                     # путей в стилях нет, пускать безопасно
    except ValueError as e:
        raise _JobError("bad_job", f"options.style: {e}") from None
    return {"on_error": on_error, "outputs": outputs, "strict_paths": strict,
            "name": safe_name(name, ".docx")[:-len(".docx")] or "otchet", "style": style,
            "limits": _ceiling(opts.get("limits"), DEFAULT_LIMITS, HARD_LIMITS, "limits"),
            "timeouts": _ceiling(opts.get("timeouts"), DEFAULT_TIMEOUTS, HARD_TIMEOUTS, "timeouts")}


def _ceiling(given, defaults: dict, hard: dict, what: str) -> dict:
    """Два уровня: значение из задания и жёсткий предел службы. Берём минимум — задание
    может попросить меньше, но не больше."""
    out = dict(defaults)
    if given is None:
        return out
    if not isinstance(given, dict):
        raise _JobError("bad_job", f"options.{what} — объект JSON")
    _known_keys(given, tuple(defaults), f"options.{what}")
    for key, val in given.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
            raise _JobError("bad_job", f"options.{what}.{key}: {val!r} — положительное число")
        out[key] = min(val, hard[key])
    return out


class _Artifacts:
    """resolve_artifact с учётом потолков на байты. Потолок проверяется до сборки и даёт
    отказ, а не молчаливую обрезку: обрезка — тот же класс дефекта, что исчезающие ключи."""

    def __init__(self, resolve, limits: dict):
        self.resolve, self.limits = resolve, limits
        self.total = 0
        self.violation: str | None = None

    def __call__(self, art_id: str) -> bytes:
        data = self.resolve(art_id)
        size = len(data) if isinstance(data, (bytes, bytearray)) else 0
        self.total += size
        if size > self.limits["max_artifact_bytes"]:
            self.violation = (f"артефакт {art_id!r}: {size} байт, потолок "
                              f"{self.limits['max_artifact_bytes']} (max_artifact_bytes)")
        elif self.total > self.limits["max_total_artifact_bytes"]:
            self.violation = (f"артефакты задания: {self.total} байт, потолок "
                              f"{self.limits['max_total_artifact_bytes']} (max_total_artifact_bytes)")
        if self.violation:
            raise HokokuError(self.violation)
        return data


def _check_limits(values: dict, limits: dict) -> None:
    if len(values) > limits["max_values"]:
        raise _JobError("limit_exceeded",
                        f"значений {len(values)}, потолок {limits['max_values']} (max_values)")
    for key, value in values.items():
        _check_value(key, value, limits)


def _check_value(key: str, v, limits: dict) -> None:
    chars = _chars(v)
    if chars > limits["max_value_chars"]:
        raise _JobError("limit_exceeded", f"знаков {chars}, потолок {limits['max_value_chars']} "
                                          "(max_value_chars)", key)
    if isinstance(v, Table):
        if len(v.rows) > limits["max_table_rows"]:
            raise _JobError("limit_exceeded", f"строк таблицы {len(v.rows)}, потолок "
                            f"{limits['max_table_rows']} (max_table_rows)", key)
        cols = max((len(r) for r in v.rows), default=0)
        if cols > limits["max_table_cols"]:
            raise _JobError("limit_exceeded", f"колонок {cols}, потолок "
                            f"{limits['max_table_cols']} (max_table_cols)", key)
    if isinstance(v, Blocks):
        if len(v.items) > limits["max_blocks_items"]:
            raise _JobError("limit_exceeded", f"блоков {len(v.items)}, потолок "
                            f"{limits['max_blocks_items']} (max_blocks_items)", key)
        for item in v.items:
            _check_value(key, item, limits)


def _chars(v) -> int:
    """Сколько знаков человек написал в значении. XML схемы сюда не входит: его писал
    генератор, а не человек, и его размер стережёт потолок на байты артефакта.

    Подпись — такой же написанный текст, как остальные, и в документе она на виду; пока
    её здесь не было, `max_chars` (и потолок службы, и `limits` манифеста — счёт один
    на всех) недосчитывал знаки, а `Image`/`Diagram` не считались вовсе.
    """
    if isinstance(v, (Text, Markdown)):
        return len(v.text)
    if isinstance(v, Code):
        return len(v.text) + _caption_chars(v)
    if isinstance(v, Formula):
        return len(v.latex)
    if isinstance(v, Table):
        return _caption_chars(v) + sum(len(str(c)) for row in v.rows for c in row)
    if isinstance(v, (Image, Diagram)):
        return _caption_chars(v)
    if isinstance(v, Toc):
        return len(v.title or "")
    if isinstance(v, Blocks):
        return sum(_chars(i) for i in v.items)
    if isinstance(v, str):
        return len(v)
    return 0


def _caption_chars(v) -> int:
    """Знаки подписи. `caption` бывает не строкой: None — номер без текста, False — вовсе
    без подписи; считать в них нечего."""
    return len(v.caption) if isinstance(v.caption, str) else 0


# ── файлы, предупреждения, мелочи ─────────────────────────────────────────────

def _write_outputs(data: bytes, opts: dict, store_artifact, workdir: str | None,
                   t0: float, errors: list, timings: dict) -> dict:
    """Готовые байты → в каталог или в хранилище. Ветвится ровно здесь и больше нигде:
    выше `build_report` про диск не знает, а сборка PDF в обоих режимах одна и та же."""
    put = _sink(store_artifact, workdir)
    outputs = {}
    if "docx" in opts["outputs"]:
        outputs["docx"] = put(safe_name(opts["name"], ".docx"), data, "docx")
    if "pdf" in opts["outputs"]:
        mark = time.perf_counter()
        try:
            left = opts["timeouts"]["total"] - (time.perf_counter() - t0)
            if left <= 0:
                raise HokokuError("бюджет задания вышел до сборки PDF (timeouts.total)")
            pdf = docx_bytes_to_pdf(data, timeout=min(opts["timeouts"]["pdf"], left))
            outputs["pdf"] = put(safe_name(opts["name"], ".pdf"), pdf, "pdf")
        except _JobError:
            # хранилище не приняло байты — это не «PDF не собрался», это отказ службы,
            # и глотать его в errors нельзя: следом за ним соврёт и docx.artifact
            raise
        except Exception as e:                               # noqa: BLE001 — DOCX уже собран
            # PDF не собрался (нет LibreOffice, таймаут) — ронять из-за этого готовый DOCX нельзя
            if opts["on_error"] == "raise":
                raise _JobError("render_failed", f"PDF: {type(e).__name__}: {e}") from None
            errors.append({"key": None, "stage": "pdf", "message": f"{type(e).__name__}: {e}"})
        timings["pdf"] = _ms(mark)
    return outputs


def _sink(store_artifact, workdir: str | None):
    """(имя, байты, вид) → запись `outputs`. Два режима, одна форма ответа с точностью
    до одного ключа: `file` против `artifact`, а `bytes` и `sha256` общие — тому, кто
    показывает результат человеку, режим знать незачем."""
    if store_artifact is None:
        os.makedirs(workdir, exist_ok=True)

        def to_dir(name: str, data: bytes, kind: str) -> dict:
            # в ответе имя, а не путь: каталог назвал вызывающий, склеить он умеет сам,
            # а путь на диске в JSON — то же самое, чего мы не пускаем внутрь
            with open(os.path.join(workdir, name), "wb") as f:
                f.write(data)
            return {"file": name, **_digest(data)}
        return to_dir

    def to_store(name: str, data: bytes, kind: str) -> dict:
        try:
            art = store_artifact(name, data, kind)
        except Exception as e:                               # noqa: BLE001 — хранилище чужое
            raise _JobError("internal", f"store_artifact({name!r}, …, {kind!r}) "
                                        f"не принял байты: {type(e).__name__}: {e}") from None
        # Идентификатор проверяем той же регуляркой, что и на входе: возвращённый наружу
        # он завтра приедет обратно в `values[…].artifact`, и хранилище, отдавшее путь
        # или строку с «..», сделало бы дырой не себя, а нас.
        if not isinstance(art, str) or not ARTIFACT_RE.match(art) or ".." in art:
            raise _JobError("internal", f"store_artifact вернул {art!r} — это не идентификатор "
                                        "артефакта (буквы, цифры, «_.-», до 64 знаков)")
        return {"artifact": art, **_digest(data)}
    return to_store


def _digest(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _warnings(res, template: bytes) -> list[Problem]:
    """Единый канал предупреждений проекта: `model.Problem` (он же `kyotsu.Notice`
    плюс тег). Ошибкой это не является: набор значений может быть шире шаблона
    (переключили шаблон, значения остались), а битая ссылка видна в готовом документе.

    Наружу (в JSON результата `build_report`) уезжает `to_dict()` — ровно те же
    ключи, что и раньше: `module`, `level`, `code`, `key`, `message`, `suggest`.
    Пустой `suggest` остаётся пустым списком, а не исчезает: `[]` значит «похожих
    тегов не нашлось», и это ответ, а не отсутствие ответа.
    """
    out: list[Problem] = []
    if res.unknown_keys:
        try:
            tags = [t.key for t in extract_tags(template)]
        except Exception:                                    # noqa: BLE001 — подсказка необязательна
            tags = []
        for key in res.unknown_keys:
            near = difflib.get_close_matches(key, tags, n=2, cutoff=0.6)
            out.append(Problem(module="hokoku", level="warning", code="unknown_key", key=key,
                               message=f"значение {key!r} не нашло тега в шаблоне",
                               suggest=near))
    for name in res.unresolved_refs:
        out.append(Problem(module="hokoku", level="warning", code="unresolved_ref", key=name,
                           message=f"ссылка {{ref:{name}}} никуда не ведёт: "
                                   "в документе стоит «?»"))
    return out


def _known_keys(d: dict, allowed, what: str) -> None:
    """Неизвестный ключ — отказ, а не молчание: молча проигнорированная опция это отчёт,
    собранный не по тому заданию, и объяснить это потом нечем."""
    for key in d:
        if key not in allowed:
            near = difflib.get_close_matches(str(key), list(allowed), n=1, cutoff=0.6)
            hint = f' (похоже на "{near[0]}")' if near else ""
            raise _JobError("bad_job", f"неизвестный ключ {key!r} в {what}{hint}")


def _ms(mark: float) -> int:
    return int((time.perf_counter() - mark) * 1000)


def _timings(timings: dict, t0: float) -> dict:
    return {"total": _ms(t0), **timings}
