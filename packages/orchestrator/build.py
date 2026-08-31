"""
build — состояние проекта → задание `hokoku.build_report` → готовый отчёт.

Второго способа собрать отчёт не заводится (прямой запрет З записки о wire):
всё идёт через `build_report`, потому что между `render` и заданием девять
действий с умолчаниями (проверка шаблона, потолки, артефакты, PDF не роняя
DOCX), и второй сборщик разошёлся бы с первым в каждом из девяти.

Здесь же — то место, где значения модели проходят проверку **целиком**, а не по
одному тегу. Посреди прогона уровня 2 полная проверка врёт: «обязательный тег
без значения» верно про всё, до чего поток ещё не дошёл. Перед сборкой она,
наоборот, единственно верная — именно её результат отвечает на вопрос «годен ли
отчёт», и именно эти замечания видит человек.
"""
from __future__ import annotations

import hokoku

from .errors import OrchestratorError

_OUTPUTS = ("docx", "pdf")


def job_of(project, *, keys=None, outputs=("docx",), on_error: str = "skip",
           name: str | None = None, style: dict | None = None) -> dict:
    """Задание для `build_report` из состояния проекта.

    Значения берутся текущими версиями — не «последними от модели» и не
    «последними от человека»: текущая версия и есть то, что показано человеку,
    и собранный документ обязан совпадать с показанным.

    `template.sha256` кладём всегда: `build_report` сверит его с байтами и
    откажется собирать по подменённому шаблону. Без сверки отчёт, собранный по
    другому шаблону, ничем не отличается от собранного по нужному — до тех пор,
    пока его не откроют.
    """
    outputs = list(outputs)
    if not outputs or any(o not in _OUTPUTS for o in outputs):
        raise OrchestratorError(f"outputs — непустой список из {', '.join(_OUTPUTS)}")
    manifest = project.manifest()
    art = project.template_artifact()
    template = {"artifact": art, "manifest_version": manifest.manifest_version}
    if manifest.template_sha256:
        template["sha256"] = manifest.template_sha256
    options: dict = {"outputs": outputs, "on_error": on_error}
    if name:
        options["name"] = name
    if style:
        options["style"] = style
    return {"wire_version": hokoku.WIRE_VERSION, "template": template,
            "values": project.values(keys=keys), "options": options}


def check(project, *, keys=None) -> list:
    """Полная проверка текущих значений против шаблона и манифеста, до сборки.

    Тот же `hokoku.validate`, что зовётся на каждом теге в `fill` — второго
    валидатора нет и быть не должно. Разница только в охвате: здесь виден весь
    отчёт сразу, поэтому здесь и только здесь честны замечания про
    незаполненные обязательные теги и про `depends_on`, который ещё не заполнен.
    """
    stored = project.values(keys=keys)
    values, errors = hokoku.values_from_json(
        stored, resolve_artifact=project.resolve_artifact)
    problems = [{"module": "hokoku", "level": "error", "code": "wire",
                 "key": e["key"], "message": e["message"]} for e in errors]
    return problems + hokoku.validate(project.template(), values, project.manifest())


def build(project, *, keys=None, outputs=("docx",), on_error: str = "skip",
          name: str | None = None, style: dict | None = None) -> dict:
    """Прогон целиком: значения → проверка → `build_report` → файлы в `out/`.

    `problems` отдаются рядом с результатом, а не вместо него, и сборка на них
    не останавливается. Причина та же, по которой `build_report` считает `ok`
    признаком «DOCX собран»: отчёт с тремя замечаниями и одним пустым тегом
    полезнее человеку, чем отказ, — он его открывает, видит пометки и правит
    руками. Отказ отдал бы ему пустоту за уже потраченные на модель деньги.

    Режим `workdir` — единственный поддержанный (`hokoku/report.py:77`);
    `store_artifact` появится вместе с хранилищем и заменит `out/`.
    """
    problems = check(project, keys=keys)
    job = job_of(project, keys=keys, outputs=outputs, on_error=on_error,
                 name=name, style=style)
    report = hokoku.build_report(job, resolve_artifact=project.resolve_artifact,
                                 workdir=project.outdir())
    return {"ok": bool(report.get("ok")), "problems": problems, "report": report,
            "workdir": project.outdir()}


__all__ = ["job_of", "check", "build"]
