"""
build — `python -m hokoku.build job.json --artifacts DIR [--out DIR]`.

Тонкий скрипт: прочитать задание, позвать build_report, напечатать результат. Никакой
логики сверх разбора аргументов и двух колбэков поверх плоского каталога — вся сборка
живёт в report.py, чтобы очередь, скрипт и endpoint не разошлись в умолчаниях.

Два режима `build_report` видны и здесь. С `--out DIR` готовые файлы кладутся туда под
человеческими именами (`workdir`); без него они уезжают в `--artifacts` под именем
из содержимого, и в результате стоят идентификаторы (`store_artifact`) — то же самое,
что увидит служба, когда у неё появится настоящее хранилище. Ровно один из режимов:
`--artifacts` при этом нужен всегда, из него берутся шаблон и картинки.

Результат JSON — на stdout, всё человеческое — на stderr: тогда
`python -m hokoku.build job.json --artifacts a --out . | jq .refs` работает без флагов.

Коды возврата: 0 — документ собран (даже если errors непуст), 1 — не собрался,
2 — задание не прочиталось. Разделение 1 и 2 нужно, чтобы скрипт в CI отличал
«мы не так позвали» от «не собралось».
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from .report import build_report
from .safety import safe_join
from .wire import ARTIFACT_RE


def _resolver(root: str | None):
    """resolve_artifact поверх плоского каталога: байты лежат в DIR/<id>. Идентификатор
    уже проверен схемой значения, safe_join — вторым слоем: каталог называет пользователь."""
    def resolve(art_id: str) -> bytes:
        if root is None:
            raise FileNotFoundError("каталог артефактов не задан (--artifacts)")
        if not ARTIFACT_RE.match(art_id):
            raise ValueError(f"{art_id!r} — не идентификатор артефакта")
        with open(safe_join(root, art_id), "rb") as f:
            return f.read()
    return resolve


def _storer(root: str | None):
    """store_artifact поверх того же плоского каталога: имя артефакта — от содержимого.

    Не `otchet.docx` и не `name`: идентификатор в хранилище обязан пройти ARTIFACT_RE,
    а `options.name` его не обязан — кириллица и пробелы там законны. Хэш годится
    всегда и заодно не даёт двум прогонам затереть друг друга.
    """
    def store(name: str, data: bytes, kind: str) -> str:
        if root is None:
            raise FileNotFoundError("каталог артефактов не задан (--artifacts)")
        art_id = f"af_{hashlib.sha256(data).hexdigest()[:32]}.{kind}"
        os.makedirs(root, exist_ok=True)
        with open(safe_join(root, art_id), "wb") as f:
            f.write(data)
        return art_id
    return store


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m hokoku.build",
                                 description="Собрать отчёт по заданию JSON.")
    ap.add_argument("job", nargs="?", help="файл задания (с --stdin не нужен)")
    ap.add_argument("--artifacts", metavar="DIR", help="плоский каталог артефактов: DIR/<id>")
    ap.add_argument("--out", metavar="DIR",
                    help="куда класть готовые файлы; без него они уедут в --artifacts")
    ap.add_argument("--pretty", action="store_true", help="результат с отступами")
    ap.add_argument("--stdin", action="store_true", help="задание со стандартного ввода")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.stdin:
            job = json.load(sys.stdin)
        elif args.job:
            with open(args.job, encoding="utf-8") as f:
                job = json.load(f)
        else:
            raise ValueError("не назван файл задания (или --stdin)")
    except (OSError, ValueError) as e:
        print(f"задание не прочиталось: {e}", file=sys.stderr)
        return 2

    sink = ({"workdir": args.out} if args.out is not None
            else {"store_artifact": _storer(args.artifacts)})
    try:
        if args.out is None and not args.artifacts:
            raise ValueError("нужен --out или --artifacts: готовые файлы девать некуда")
        result = build_report(job, resolve_artifact=_resolver(args.artifacts), **sink)
    except (ValueError, NotImplementedError) as e:           # так позвали, а не так собралось
        print(f"так звать нельзя: {e}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    if not result["ok"]:
        print(f"не собралось: {result['error']['code']} — {result['error']['message']}",
              file=sys.stderr)
        return 1
    files = ", ".join(o.get("file") or o["artifact"] for o in result["outputs"].values())
    where = os.path.abspath(args.out if args.out is not None else args.artifacts)
    print(f"собрано: {files or '(ничего не просили)'} в {where}; "
          f"незаполненных тегов {len(result['unfilled'])}, ошибок {len(result['errors'])}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
