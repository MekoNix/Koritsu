"""
`python -m kadai` — пять команд: завести работу, пройти стадии, показать статус, переделать, собрать архив.

    python -m kadai new <каталог> --condition файл [--wish "…"] [--endpoint имя]
    python -m kadai run <каталог> [--until стадия]
    python -m kadai status <каталог>
    python -m kadai rework <каталог> --note "…" [--block b-NN] [--kind вид]
    python -m kadai archive <каталог>

**Откуда берутся двери.** Собрать `Services` умеет только `orchestrator`
(`kadai_services`), а импортировать его отсюда нельзя — правило разреза. Поэтому
фабрика дверей приходит извне и называется переменной окружения:

    KADAI_SERVICES=orchestrator.doors:kadai_services python -m kadai run ./работа

Имя соседа встречается здесь дважды и оба раза в тексте для человека — в этой
строке примера и в подсказке, если переменную забыли. В коде его нет: ни
импорта, ни умолчания. Умолчания нет намеренно — «если не сказали, возьми
`orchestrator`» и есть имя соседа в коде, только записанное неявно, и второй
сборщик дверей о нём не узнал бы. Тонкая обёртка (`python -m orchestrator.kadai`)
переменной не ставит вовсе: она передаёт фабрику прямо в
`main(argv, services_factory=…)`.

Подпись фабрики, которую ждут обе стороны:

    factory(path: str, *, endpoint: str = "", create: bool = False) -> kadai.Services

`create=True` — только у `new`: создание проекта поверх существующего обязано
отказывать, и решать это должен тот, кто знает, что такое каталог проекта.

**Путей этот файл не строит.** Единственная работа с файловой системой —
прочитать байты условия (`Path.read_bytes`) и отдать их проекту вместе с именем.
Куда они лягут, знает `Project`, и `kadai` этого не спрашивает.

Коды возврата: 0 — сделано; 1 — сценарий позван неправильно или стадия
споткнулась; 3 — шов к соседу не сведён (`NotReady`): чинится не здесь, и путать
это с ошибкой вызывающего нельзя.
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from os import environ
from pathlib import Path

from . import rework as rework_mod, run as run_mod
from .errors import KadaiError, NotReady
from .plan import Wishes
from .seams import method
from .stages import STAGE_NAMES, reopen, stage_now

ENV_FACTORY = "KADAI_SERVICES"


def main(argv=None, *, services_factory=None, prog: str = "python -m kadai") -> int:
    """Точка входа CLI. `services_factory` передаёт обёртка, знающая оркестратор.

    Аргумент, а не только переменная окружения: обёртке незачем ставить
    переменную самой себе, а тестам — заводить окружение ради вызова одной
    функции. Переменная остаётся для `python -m kadai` руками.

    `prog` — чем эту программу зовут на самом деле. Обёртка запускается своим
    именем (`python -m orchestrator.kadai`), и подсказка «дальше: python -m
    kadai run …», напечатанная ей, звала бы человека к команде, которая без
    переменной окружения не работает. Имени соседа в этом пакете при этом
    по-прежнему нет: строку приносит тот, кто запустил.
    """
    parser = _parser(prog)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    args._prog = prog
    try:
        factory = services_factory or _factory_from_env()
        return _COMMANDS[args.команда](args, factory)
    except NotReady as exc:
        print(f"жду соседа: {exc}", file=sys.stderr)
        return 3
    except KadaiError as exc:
        print(f"не вышло: {exc}", file=sys.stderr)
        return 1


def _parser(prog: str = "python -m kadai") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog,
                                description="одна задача → готовый архив")
    sub = p.add_subparsers(dest="команда", required=True)

    новая = sub.add_parser("new", help="завести работу: условие и пожелания")
    новая.add_argument("каталог")
    новая.add_argument("--condition", required=True, help="файл условия задачи")
    новая.add_argument("--wish", default="", help="пожелания словами")
    новая.add_argument("--endpoint", default="", help="какой моделью работать")
    новая.add_argument("--material", action="append", default=[],
                       help="ещё файл в работу (можно несколько раз)")
    новая.add_argument("--show-task", action="store_true",
                       help="остановиться и показать, как понято задание")
    новая.add_argument("--show-structure", action="store_true",
                       help="остановиться и показать строение работы")
    новая.add_argument("--no-ocr", action="store_true",
                       help="не распознавать скан (текстовый слой или ничего)")

    прогон = sub.add_parser("run", help="пройти стадии")
    прогон.add_argument("каталог")
    прогон.add_argument("--endpoint", default="")
    прогон.add_argument("--until", choices=list(STAGE_NAMES), default=None,
                        help="последняя стадия, которую делаем")
    прогон.add_argument("--max-steps", type=int, default=None,
                        help="потолок ходов петли (он же знаменатель полоски)")

    снимок = sub.add_parser("status", help="снимок работы в JSON (записка Е.4)")
    снимок.add_argument("каталог")
    снимок.add_argument("--endpoint", default="")
    снимок.add_argument("--since", type=int, default=0,
                        help="показать события после этого номера")

    правка = sub.add_parser("rework", help="переделать по замечанию")
    правка.add_argument("каталог")
    правка.add_argument("--endpoint", default="")
    правка.add_argument("--note", required=True, help="замечание словами")
    правка.add_argument("--block", default=None, help="ключ блока: b-07")
    правка.add_argument("--kind", default=None,
                        help="вид замечания, если блок не назван: "
                             "схема, кусок, код, структура, условие")

    архив = sub.add_parser("archive", help="собрать архив (заново, если уже собран)")
    архив.add_argument("каталог")
    архив.add_argument("--endpoint", default="")
    return p


# ── команды ──────────────────────────────────────────────────────────────────

def _new(args, factory) -> int:
    services = factory(args.каталог, endpoint=args.endpoint, create=True)
    принять = method(services.project, "add_material", "разбор условия")
    for имя in args.material:
        путь = Path(имя)
        принять(путь.read_bytes(), путь.name, do_ocr=not args.no_ocr)
    условие = Path(args.condition)
    material = принять(условие.read_bytes(), условие.name,
                       do_ocr=not args.no_ocr, condition=True)
    wishes = Wishes(text=args.wish, show_task=args.show_task,
                    show_structure=args.show_structure)
    session = run_mod.new(services, wishes=wishes)
    print(f"работа {session.work.id} заведена: условие {material.name} "
          f"({material.id})")
    print(f"дальше: {args._prog} run " + args.каталог)
    return 0


def _run(args, factory) -> int:
    session = _session(args, factory)
    run_mod.run(session, until=args.until)
    _print_state(session, args._prog)
    return 0


def _status(args, factory) -> int:
    """Снимок в JSON — ключ в ключ по записке Е.4. Печатается как есть.

    Как есть, а не «покрасивее»: этот же снимок будет отдавать API, и вторая
    форма для CLI означала бы две формы, которые расходятся молча.
    """
    session = _session(args, factory)
    снимок = run_mod.snapshot(session, since=args.since)
    print(json.dumps(снимок, ensure_ascii=False, indent=2))
    return 0


def _rework(args, factory) -> int:
    session = _session(args, factory)
    итог = rework_mod.apply(session, note=args.note, block=args.block, kind=args.kind)
    print(f"замечание вида «{итог['kind']}»: переигрываем "
          + ", ".join(итог["stages"]))
    if итог.get("note"):
        print("  " + итог["note"])
    # Оговорка маршрута печатается всегда: это единственное место, где написано,
    # чего пересчёт не умеет, и промолчать здесь значило бы выдать исправление,
    # которое могло стать хуже, за проверенное.
    print("  честно: " + итог["honest"])
    _print_state(session, args._prog)
    return 0


def _archive(args, factory) -> int:
    session = _session(args, factory)
    стадия = session.work.stage("архив")
    if стадия.state == "сделано":
        стадия.state, стадия.note = "ждёт", "собираем архив заново"
        if session.work.state in ("done", "failed"):
            reopen(session.work, note="архив собирается заново")
    run_mod.run(session, until="архив")
    _print_state(session, args._prog)
    return 0


_COMMANDS = {"new": _new, "run": _run, "status": _status, "rework": _rework,
             "archive": _archive}


# ── общее ────────────────────────────────────────────────────────────────────

def _session(args, factory):
    services = factory(args.каталог, endpoint=getattr(args, "endpoint", ""))
    limits = ({"max_steps": args.max_steps}
              if getattr(args, "max_steps", None) else {})
    return run_mod.load(services, limits=limits)


def _factory_from_env():
    """Фабрика дверей по переменной окружения `KADAI_SERVICES=модуль:функция`."""
    spec = str(environ.get(ENV_FACTORY) or "").strip()
    if not spec:
        raise KadaiError(
            f"не сказано, кто собирает двери: поставьте {ENV_FACTORY}=модуль:функция "
            "(например orchestrator.doors:kadai_services). Своего умолчания у kadai "
            "нет: он не знает имён соседей и знать не должен")
    модуль, _, имя = spec.partition(":")
    if not модуль or not имя:
        raise KadaiError(f"{ENV_FACTORY}={spec!r} — ожидалось «модуль:функция»")
    try:
        фабрика = getattr(import_module(модуль), имя)
    except (ImportError, AttributeError) as exc:
        raise KadaiError(f"{ENV_FACTORY}={spec!r}: {exc}") from None
    return фабрика


def _print_state(session, prog: str = "python -m kadai") -> None:
    """Где стоим — тремя строками. Подробности спрашиваются `status`."""
    work = session.work
    print(f"работа {work.id}: {work.state}, стадия «{stage_now(work)}»")
    if work.hold is not None:
        print(f"  ждём вас: {work.hold.show}"
              + (f" — {work.hold.note}" if work.hold.note else ""))
        if work.condition_text and work.hold.show == "распознанное условие":
            print("  ── распознанный текст условия ──")
            print("\n".join("  " + line for line in work.condition_text.splitlines()))
    if work.state == "failed":
        # `failed` — конечное состояние: прогон уровня 3 не возобновляется, и
        # «продолжу как-нибудь» доплатило бы за ходы, результат которых потерян.
        # Путь вперёд один, и человек должен его увидеть здесь, а не искать.
        print("  продолжить нечем: переделайте замечанием — "
              f"{prog} rework <каталог> --note «…» [--block b-NN]")
    for имя, значение in work.outputs.items():
        print(f"  {имя}: {значение}")
    for p in work.problems[-5:]:
        print(f"  [{p.get('level')}] {p.get('module')}/{p.get('code')}: {p.get('message')}")


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main())
