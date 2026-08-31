"""
build — `python -m hokoku.build job.json --artifacts DIR --out DIR`.

Тонкий скрипт: прочитать задание, позвать build_report, напечатать результат. Никакой
логики сверх разбора аргументов и двух колбэков поверх плоского каталога — вся сборка
живёт в report.py, чтобы очередь, скрипт и endpoint не разошлись в умолчаниях.

Результат JSON — на stdout, всё человеческое — на stderr: тогда
`python -m hokoku.build job.json --artifacts a --out . | jq .refs` работает без флагов.

Коды возврата: 0 — документ собран (даже если errors непуст), 1 — не собрался,
2 — задание не прочиталось. Разделение 1 и 2 нужно, чтобы скрипт в CI отличал
«мы не так позвали» от «не собралось».
"""
from __future__ import annotations

import argparse
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


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m hokoku.build",
                                 description="Собрать отчёт по заданию JSON.")
    ap.add_argument("job", nargs="?", help="файл задания (с --stdin не нужен)")
    ap.add_argument("--artifacts", metavar="DIR", help="плоский каталог артефактов: DIR/<id>")
    ap.add_argument("--out", metavar="DIR", required=True, help="куда класть готовые файлы")
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

    try:
        result = build_report(job, resolve_artifact=_resolver(args.artifacts), workdir=args.out)
    except (ValueError, NotImplementedError) as e:           # так позвали, а не так собралось
        print(f"так звать нельзя: {e}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    if not result["ok"]:
        print(f"не собралось: {result['error']['code']} — {result['error']['message']}",
              file=sys.stderr)
        return 1
    files = ", ".join(o["file"] for o in result["outputs"].values())
    print(f"собрано: {files or '(ничего не просили)'} в {os.path.abspath(args.out)}; "
          f"незаполненных тегов {len(result['unfilled'])}, ошибок {len(result['errors'])}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
