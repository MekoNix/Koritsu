"""
schema — какие теги просить у модели и по какой схеме.

Два вопроса, ответы на которые не принадлежат ни `hokoku`, ни `llm`. Форму
значения знает `hokoku.wire`, форму всего ответа — `hokoku.manifest_schema`; а
вот **какие теги вообще просить** — знание про проект (что уже стоит, что правит
человек), и живёт оно здесь.

Цена ошибки в отборе конкретная. Схема, собранная из всего манифеста, попросила
бы модель заполнить теги, которых нет в шаблоне (`missing: true`), и теги,
которые заполняет человек или файл (`source_hint != "agent"`), — а `required`
в такой схеме соврал бы: модель обязана вернуть то, чего у неё никто не просил,
и вернёт выдумку. Токены на это тратятся настоящие.
"""
from __future__ import annotations

import hokoku

from .errors import OrchestratorError, hint


def tag_schema(spec: hokoku.TagSpec) -> dict:
    """Схема одного значения — уровень 1.

    Второго описания формы значения здесь нет и быть не должно: `value_schema`
    строится из `dataclasses.fields` самих значений, поэтому поле, добавленное
    в `hokoku.model`, попадает в схему само. Копия разошлась бы с ним молча.
    """
    return hokoku.value_schema(spec.type, for_model=True)


def report_schema(manifest: hokoku.Manifest, *, keys) -> dict:
    """Схема всего ответа — уровень 2: `{ключ тега: схема его типа}`.

    Порядок ключей — порядок документа (`extract_tags` отдаёт теги в порядке
    появления, `Manifest.tags` — обычный `dict` и порядок хранит). Это важно не
    для валидности, а для потока: модель заполняет объект по порядку, значит
    первые закрывшиеся значения — начало документа, и частичный результат при
    обрыве осмыслен, а не случаен.
    """
    keys = list(keys)
    if not keys:
        raise OrchestratorError("нечего просить у модели: ни одного заполняемого тега")
    return hokoku.manifest_schema(manifest, keys=keys)


def fillable(manifest: hokoku.Manifest, *, keys=None) -> list[str]:
    """Теги, которые вообще просят у модели, в порядке документа.

    Отсеиваются: `missing` (тега нет в шаблоне — запись бережём ради промпта, но
    заполнять нечего) и `source_hint != "agent"` (номер группы и подпись
    руководителя модель не сочиняет).

    `keys` — явное сужение вызывающего; неизвестный ключ здесь ошибка, а не
    молчание: «заполни тег, которого нет» иначе кончилось бы пустым прогоном за
    настоящие деньги.

    Чего этот отбор не знает и знать не может: **кто написал то, что лежит
    сейчас**. `source_hint` манифеста говорит, кто заполняет тег вообще, а
    `source` версии — кто написал это значение, и второе живёт в проекте, а не в
    манифесте. Отбор по нему делает `fill._held_by`; складывать сюда ещё и
    проект значило бы завести в схеме знание про хранилище.
    """
    if keys is not None:
        keys = [hokoku.wire.norm_key(str(k)) for k in keys]
        for key in keys:
            if key not in manifest.tags:
                raise OrchestratorError(
                    f"тега {key!r} нет в манифесте{hint(key, manifest.tags)}")
        wanted = set(keys)
    else:
        wanted = None
    return [key for key, spec in manifest.tags.items()
            if not spec.missing and spec.source_hint == "agent"
            and (wanted is None or key in wanted)]


def spec_of(manifest: hokoku.Manifest, key: str) -> hokoku.TagSpec:
    """Запись манифеста по ключу — с подсказкой вместо KeyError."""
    key = hokoku.wire.norm_key(str(key))
    spec = manifest.tags.get(key)
    if spec is None:
        raise OrchestratorError(f"тега {key!r} нет в манифесте{hint(key, manifest.tags)}")
    return spec


__all__ = ["tag_schema", "report_schema", "fillable", "spec_of"]
