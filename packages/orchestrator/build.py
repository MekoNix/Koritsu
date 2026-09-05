"""
build — состояние проекта → задание `hokoku.build_report` → готовый отчёт.

Второго способа собрать отчёт не заводится: всё идёт через `build_report`,
потому что между `render` и заданием девять действий с умолчаниями
(проверка шаблона, потолки, артефакты, PDF не роняя DOCX), и второй
сборщик разошёлся бы с первым в каждом из девяти.

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

    Сюда же — замечания тех, кто построил схемы, стоящие в отчёте
    (`_diagram_notices`). Их проводит служба, а не `hokoku`: пакеты друг о
    друге не знают, а вопрос «что не так с отчётом» задаётся один раз и ответ
    на него должен быть один.
    """
    stored = project.values(keys=keys)
    values, errors = hokoku.values_from_json(
        stored, resolve_artifact=project.resolve_artifact)
    problems = [hokoku.Problem(module="hokoku", level="error", code="wire",
                               key=e["key"], message=e["message"]) for e in errors]
    return (problems + hokoku.validate(project.template(), values, project.manifest())
            + _diagram_notices(project, stored))


def _diagram_notices(project, stored: dict) -> list:
    """Замечания генераторов схем, которые стоят в текущих значениях.

    `fragmos` сказал «в схему не вошло: goto case» в момент постройки — то есть
    ходов за десять до сборки, в другом прогоне и, возможно, в прошлом месяце.
    Замечание лежит рядом с артефактом (`Project.artifact_notices`), и берётся
    оно только для схем, которые в отчёт действительно попали: сказать про
    брошенную схему значит гонять человека чинить то, чего в отчёте нет.

    Одна схема в двух тегах даёт два замечания — по одному на тег, а не одно:
    показываются они рядом с тегом, и «которого из двух» человек угадывать не
    должен. Ключ тега приписывается тут же: сам `fragmos` про теги не знает.
    """
    out: list = []
    for key, value in stored.items():
        if not isinstance(value, dict) or value.get("type") != "diagram":
            continue
        art = value.get("artifact")
        if not isinstance(art, str) or not art:
            continue                    # схема задана xml'ем: артефакта нет, замечаний тоже
        for n in project.artifact_notices(art):
            out.append(hokoku.Problem(module=n.module, level=n.level, code=n.code,
                                      message=f"схема тега {key!r}: {n.message}",
                                      file=n.file, line=n.line, key=key))
    return out


def build(project, *, keys=None, outputs=("docx",), on_error: str = "skip",
          name: str | None = None, style: dict | None = None,
          store: bool = False) -> dict:
    """Прогон целиком: значения → проверка → `build_report` → файлы в `out/`.

    `store=True` — тот самый переезд, которого этот код ждал: собранное едет не
    в `out/`, а в хранилище артефактов проекта (`Project.put_artifact`), и в
    результате вместо `outputs.docx.file` стоит `outputs.docx.artifact`. Так
    работает служба: файл в каталоге `out/` живёт на томе безымянно, а
    артефакт адресуется идентификатором, по которому его скачивают, ставят в
    значение тега и кладут в архив. Форма результата у режимов одна с точностью
    до этого ключа, поэтому показывающему результат человеку режим знать
    незачем — и `workdir` остаётся умолчанием для лаборатории и командной
    строки.

    `problems` отдаются рядом с результатом, а не вместо него, и сборка на них
    не останавливается. Причина та же, по которой `build_report` считает `ok`
    признаком «DOCX собран»: отчёт с тремя замечаниями и одним пустым тегом
    полезнее человеку, чем отказ, — он его открывает, видит пометки и правит
    руками. Отказ отдал бы ему пустоту за уже потраченные на модель деньги.

    Из двух режимов `build_report` берётся `workdir`: у проекта есть каталог
    (`out/`), а хранилища артефактов с записью — ещё нет. `store_artifact`
    реализован и ждёт его; переезд стоит одной строки здесь, потому что форма
    результата у режимов одна с точностью до `file` против `artifact`.
    """
    problems = check(project, keys=keys)
    job = job_of(project, keys=keys, outputs=outputs, on_error=on_error,
                 name=name, style=style)
    if store:
        # Имя и вид приходят от `build_report` и здесь не нужны: артефакт
        # адресуется содержимым, а не именем (`Project.put_artifact`). Имя всё
        # же передаём — оно читается в отладке и ни на что не влияет.
        report = hokoku.build_report(
            job, resolve_artifact=project.resolve_artifact,
            store_artifact=lambda имя, данные, вид: project.put_artifact(
                данные, name=имя))
        return {"ok": bool(report.get("ok")), "problems": problems,
                "report": report, "workdir": None}
    report = hokoku.build_report(job, resolve_artifact=project.resolve_artifact,
                                 workdir=project.outdir())
    return {"ok": bool(report.get("ok")), "problems": problems, "report": report,
            "workdir": project.outdir()}


__all__ = ["job_of", "check", "build"]
