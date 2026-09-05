#!/usr/bin/env python3
"""
openapi-dump — снять документ OpenAPI со службы, не поднимая сервер.

Зачем не `curl http://127.0.0.1:8000/openapi.json`: генерация клиента не должна
зависеть от того, поднят ли у разработчика API и на каком он порту. Приложение
собирается прямо здесь (`create_app(Settings.from_env())`), документ берётся у
FastAPI (`app.openapi()`) и кладётся рядом — `web/openapi.json`. Дальше по нему
работает `pnpm gen:api` (`openapi-typescript` → `src/api/schema.d.ts`).

Оба файла (`openapi.json` и `schema.d.ts`) коммитятся: клиент обязан быть
воспроизводимым без питона и без службы.

`Settings.from_env()` требует том и секрет, поэтому здесь заводится ВРЕМЕННЫЙ
каталог: снятие схемы не должно ни писать в рабочие данные, ни зависеть от них.
Секрет — заведомо ненастоящий и никуда не уезжает: подписывать им ничего не
будут, приложение только строит маршруты.

Запуск:  python3 web/scripts/openapi-dump.py  [--out web/openapi.json]
Питон — общий venv репозитория (3.12), см. памятку прогона.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# `web/scripts/openapi-dump.py` → корень репозитория на два уровня выше `web/`.
КОРЕНЬ = Path(__file__).resolve().parents[2]
ПАКЕТЫ = КОРЕНЬ / "packages"
ПО_УМОЛЧАНИЮ = КОРЕНЬ / "web" / "openapi.json"

# Секрет нужен только чтобы `Settings.from_env()` не отказала: длина ≥ 32 байт.
СЕКРЕТ = "openapi-dump-only-not-a-real-secret-0123456789"


def main() -> int:
    разбор = argparse.ArgumentParser(description=__doc__)
    разбор.add_argument("--out", default=str(ПО_УМОЛЧАНИЮ),
                        help="куда положить документ (по умолчанию web/openapi.json)")
    аргументы = разбор.parse_args()

    sys.path.insert(0, str(ПАКЕТЫ))

    with tempfile.TemporaryDirectory(prefix="koritsu-openapi-") as том:
        os.environ["KORITSU_DATA_DIR"] = том
        os.environ.setdefault("KORITSU_SECRET", СЕКРЕТ)
        os.environ["KORITSU_ENV"] = "dev"

        from api import Settings, create_app  # импорт после sys.path и окружения

        приложение = create_app(Settings.from_env())
        документ = приложение.openapi()

    путь = Path(аргументы.out)
    путь.parent.mkdir(parents=True, exist_ok=True)
    # `ensure_ascii=False` — в описаниях бывает кириллица; `sort_keys` не ставим:
    # порядок ключей у FastAPI устойчив, а сортировка перемешала бы `paths`.
    путь.write_text(json.dumps(документ, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    операций = sum(1 for п in документ["paths"].values() for м in п
                   if м in ("get", "post", "put", "patch", "delete"))
    print(f"{путь}: путей {len(документ['paths'])}, операций {операций}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
