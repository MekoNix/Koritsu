"""
Запуск слоя из командной строки: `python -m llm <команда>`.

Пока команда одна — проба endpoint'а. Она вынесена в CLI намеренно: проба ходит
в сеть и стоит денег, поэтому её запускает человек осознанно, а не какой-нибудь
код при старте.

Пакеты по-прежнему не устанавливаются (импорт по пути), поэтому нужны и
PYTHONPATH, и python из venv проекта — иначе не найдётся ни llm, ни httpx.
Запускать из корня репозитория:

    DEEPSEEK_API_KEY=… PYTHONPATH=packages \\
        ./.venv/bin/python -m llm probe --preset deepseek

Ключ можно не передавать в командной строке, а положить в
~/.config/koritsu/deepseek.key — он читается, когда переменной нет.

Коды выхода: 0 — проба прошла, 1 — не прошла, 2 — ошибка в параметрах,
3 — ключа нет ни в переменной, ни в файле.
"""
from __future__ import annotations

import sys

from . import probing

КОМАНДЫ = {"probe": probing.main}

ПОДСКАЗКА = ("Использование: python -m llm <команда> [параметры]\n"
             "Команды:\n"
             "  probe   пробный вызов endpoint'а (Б.4); ходит в сеть\n"
             "\nПодробности: python -m llm probe --help")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(ПОДСКАЗКА)
        return 0 if argv else 2
    команда = КОМАНДЫ.get(argv[0])
    if команда is None:
        print(f"неизвестная команда {argv[0]!r}\n\n{ПОДСКАЗКА}", file=sys.stderr)
        return 2
    return команда(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
