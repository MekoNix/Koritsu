"""
Запуск службы из командной строки: `python -m api <команда>`.

Четыре команды, и все четыре — то, что иначе делалось бы руками в интерпретаторе:

    serve     поднять uvicorn на `app.app_from_env()`
    worker    крутить очередь заданий (§11: второй контейнер в compose)
    migrate   довести базу до последней миграции и выйти
    purge     физически убрать из корзины всё, чей срок вышел (§2)

Зачем `migrate` отдельной командой, если `create_app` мигрирует сам: на выкате
миграцию запускают **до** запуска процессов, одним разом. Три контейнера,
поднявшиеся одновременно и мигрирующие каждый сам, — это три `ALTER TABLE` на
одной SQLite и «database is locked» у двоих из троих.

Зачем `worker` отдельной командой, а не потоком внутри `serve`: прогон модели
длится минуты, и поток, занятый им внутри uvicorn, — это воркер, которого нельзя
перезапустить, не уронив сайт. Разделив их, мы получаем ещё и правду про
нагрузку: слоты считает воркер, и «очередь встала» перестаёт выглядеть как «сайт
тормозит». Команда мигрирует базу перед началом работы — тем же `migrate`, что
и `serve`; на выкате её всё равно зовут отдельно, до подъёма контейнеров.

Зачем `purge` командой, а не по таймеру внутри процесса: уборка сносит каталоги
с тома, и запускать её обязан тот, кто отвечает за резервную копию, — cron рядом
с restic (§2). Её же зовёт воркер раз в час (§11); команда остаётся для руки и
для установки без воркера.

Настройки берутся из окружения (`Settings.from_env`) и ниоткуда больше — у тома
умолчания нет, поэтому без `KORITSU_DATA_DIR` любая из трёх команд честно падает
с внятным текстом, а не пишет в чей-нибудь `./data`.

Пакеты в проекте не устанавливаются (решение владельца), поэтому запуск из корня
репозитория и с путём:

    PYTHONPATH=packages KORITSU_DATA_DIR=/data KORITSU_SECRET=… \\
        /home/kurisu/koritsu2/.venv/bin/python -m api serve

Коды выхода: 0 — сделано, 1 — служба настроена так, что работать нельзя,
2 — ошибка в параметрах командной строки.
"""
from __future__ import annotations

import argparse
import sys

from .errors import ConfigError
from .settings import Settings

# Куда слушать, если снаружи не сказали. Петля, а не `0.0.0.0`: служба стоит за
# Caddy (§3), и умолчание, открывающее порт наружу, — это забытая настройка,
# которая однажды выставит сайт без прокси и без TLS.
ХОСТ_УМОЛЧАНИЕ = "127.0.0.1"
ПОРТ_УМОЛЧАНИЕ = 8000

ОПИСАНИЕ = "HTTP-служба Koritsu: запуск, миграции, уборка корзины."


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m api",
                                 description=ОПИСАНИЕ)
    команды = ap.add_subparsers(dest="команда", metavar="команда")

    serve = команды.add_parser(
        "serve", help="поднять службу (uvicorn); хост и порт — из окружения")
    serve.add_argument("--host", default=None,
                       help=f"адрес; умолч. KORITSU_HOST или {ХОСТ_УМОЛЧАНИЕ}")
    serve.add_argument("--port", type=int, default=None,
                       help=f"порт; умолч. KORITSU_PORT или {ПОРТ_УМОЛЧАНИЕ}")

    команды.add_parser(
        "worker", help="крутить очередь заданий, пока не попросят остановиться",
        description=(
            "Крутить очередь заданий. Слоты, опрос и потолки — из окружения "
            "(KORITSU_JOB_SLOTS, KORITSU_JOBS_PER_USER, KORITSU_WORKER_POLL_S, "
            "KORITSU_JOB_TIMEOUT_S, KORITSU_JOB_MEMORY_MB). SIGTERM — доделать "
            "текущее и не брать новых."))
    команды.add_parser("migrate", help="довести базу до последней миграции")
    команды.add_parser("purge", help="убрать из корзины всё, чей срок вышел")
    return ap


def настройки() -> Settings:
    """Настройки из окружения. Беда настройки — не трассировка, а строка.

    `ConfigError` ловится в `main`: оператор, поднявший контейнер без
    `KORITSU_SECRET`, должен прочитать одну понятную строку, а не сорок строк
    трассировки, в которых эта строка последняя.
    """
    return Settings.from_env()


# ── команды ──────────────────────────────────────────────────────────────────

def serve(args) -> int:
    """Поднять uvicorn на фабрике приложения.

    `--factory`, а не готовое приложение: `app_from_env()` читает окружение и
    мигрирует базу, и делать это на импорте модуля значило бы трогать том всякий
    раз, когда кто-нибудь просто импортирует пакет.

    `uvicorn` импортируется здесь, а не наверху файла: `migrate` и `purge`
    должны работать в контейнере, где веб-сервера может не быть вовсе.
    """
    import uvicorn                                    # noqa: PLC0415

    import os

    s = настройки()
    host = args.host or os.environ.get("KORITSU_HOST") or ХОСТ_УМОЛЧАНИЕ
    порт = args.port if args.port is not None else _порт(os.environ)
    print(f"koritsu: {host}:{порт}, том {s.data_dir}, режим {s.env}")
    uvicorn.run("api.app:app_from_env", factory=True, host=host,
                port=порт)
    return 0


def worker(args) -> int:
    """Крутить очередь заданий, пока не пришёл `SIGTERM`.

    База доводится до последней миграции здесь же: воркер поднимается тем же
    compose, что и служба, и контейнер, стартовавший на вчерашней схеме, падал
    бы на первом же задании — а падал бы он в фоне, где этого никто не видит.

    Останавливается мягко: `docker compose stop` шлёт `SIGTERM`, воркер
    доделывает начатое и не берёт новых. Время на это даёт `docker stop
    --timeout`; в compose его ставят по `KORITSU_JOB_TIMEOUT_S`.
    """
    from .db import migrate as довести                      # noqa: PLC0415
    from .jobs.worker import Worker                         # noqa: PLC0415
    from .log import setup                                  # noqa: PLC0415

    s = настройки()
    setup(s)
    довести(s)
    print(f"koritsu worker: том {s.data_dir}, слотов {s.job_slots}, "
          f"на человека {s.jobs_per_user}")
    return Worker(s).run_forever()


def migrate(args) -> int:
    """Довести базу до последней миграции и выйти."""
    from .db import current_revision, migrate as довести   # noqa: PLC0415

    s = настройки()
    довести(s)
    print(f"koritsu: база {s.db_url} на миграции {current_revision(s)}")
    return 0


def purge(args) -> int:
    """Физически убрать из корзины всё, чей срок вышел (§2: десять дней).

    Печатает, что именно убрано: команда сносит каталоги с тома, и «сделано» без
    списка — это ровно то сообщение, после которого никто не может сказать,
    пропала ли чужая работа по сроку или по ошибке.
    """
    from .db import Db                                     # noqa: PLC0415
    from .projects.service import purge_expired            # noqa: PLC0415

    s = настройки()
    db = Db(s)
    try:
        with db.session_scope() as сессия:
            убрано = purge_expired(сессия, s)
    finally:
        db.dispose()

    if not убрано:
        print("koritsu: убирать нечего — сроки в корзине ещё не вышли")
    else:
        print(f"koritsu: убрано проектов — {len(убрано)}")
        for project_id in убрано:
            print(f"  {project_id}")
    return 0


КОМАНДЫ = {"serve": serve, "worker": worker, "migrate": migrate,
           "purge": purge}


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.команда is None:
        ap.print_help()
        return 2
    try:
        return КОМАНДЫ[args.команда](args)
    except ConfigError as беда:
        # Настройка, а не поломка: текст по-русски и читает его оператор
        # (`errors`: наружу английский, внутрь русский).
        print(f"koritsu: {беда}", file=sys.stderr)
        return 1


def _порт(env) -> int:
    """Порт из окружения. Мусор — беда настройки, а не умолчание.

    Та же строгость, что у чисел в `settings.py`, и по той же причине:
    `KORITSU_PORT=восемь тысяч`, понятый как 8000, означает службу, поднятую не
    там, где её ищет прокси, — и ни одной строки о том, почему.
    """
    сырое = (env.get("KORITSU_PORT") or "").strip()
    if not сырое:
        return ПОРТ_УМОЛЧАНИЕ
    try:
        return int(сырое)
    except ValueError:
        raise ConfigError(f"KORITSU_PORT — целое число, а не {сырое!r}") from None


if __name__ == "__main__":
    raise SystemExit(main())
