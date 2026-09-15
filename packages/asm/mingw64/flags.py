"""flags.py — что человек может добавить к командам `as` и `ld`, и чего нельзя в исходнике.

Команды сборки — те, которыми собирают лабу под MSYS2:

    as -a=prog.lst prog.s -o prog.obj
    ld -o prog.exe prog.obj -L<lib> -lkernel32

`-a=`, `-o`, `-L` и `-lkernel32` ставит ядро. Ключи человека идут перед ними и проверяются
**перечнем разрешённого**, а не регуляркой формы: у GNU-инструментов много ключей, которые
читают или пишут файлы машины (`@файл`, `-T`, `--plugin`, `-Map`, `--listing-…`, `-I` на
чужой каталог), и любой не перечисленный ключ — отказ с понятным текстом.

`as`:  -g  --gdwarf-2 … --gdwarf-5  --warn  --fatal-warnings  -I .
`ld`:  -e <символ>  --entry=<символ>  --subsystem console  -s  -S  --image-base=<0x…>
       -lkernel32 (его и так добавляет ядро; другие библиотеки не подключаются)

Ключ со значением можно писать слитно (`-emain`, `--subsystem=console`) или отдельным словом;
в итоге он приводится к одной форме.

**Исходник.** `.include` и `.incbin` читают любой файл машины по пути из исходника, и байты
уезжают человеку в листинге и дампе. Программа — один файл, подключать ей нечего, поэтому эти
директивы запрещены. Запрещено и то, чем их можно собрать в обход проверки: `.altmacro`
(подстановка параметров без `\\`) и имя команды из подстановки макроса (`\\a "…"`, `.inc\\()bin`).
"""
from __future__ import annotations

import re
from typing import Sequence

from ..model import АсмОшибка
from .gas import _Scan, head, statements

FLAGS_MAX = 16

_AS_SWITCHES = ("-g", "--gdwarf-2", "--gdwarf-3", "--gdwarf-4", "--gdwarf-5", "--warn",
                "--fatal-warnings")
_LD_SWITCHES = ("-s", "-S")
_SYMBOL = re.compile(r"^[A-Za-z_.$?@][A-Za-z0-9_.$?@]{0,127}$")
_IMAGE_BASE = re.compile(r"^0[xX][0-9A-Fa-f]{1,16}$")

AS_ALLOWED = "-g, --gdwarf-2…5, --warn, --fatal-warnings, -I ."
LD_ALLOWED = "-e <символ>, --entry=<символ>, --subsystem console, -s, -S, --image-base=0x…"

_FORBIDDEN_DIRECTIVES = {".include": "подключение файла", ".incbin": "подключение файла",
                         ".altmacro": "макросы без \\"}
_INCLUDE_WORD = re.compile(r"\.inc(?:lude|bin)\b", re.IGNORECASE)


def _tokens(flags: Sequence[str], tool: str) -> list[str]:
    if isinstance(flags, (str, bytes)):
        raise АсмОшибка(f"Ключи {tool} — список")
    out: list[str] = []
    for flag in flags or ():
        if not isinstance(flag, str):
            raise АсмОшибка(f"Ключ {tool} — строка: {flag!r}")
        # Запуск без оболочки: пробел внутри элемента — это просто два слова, «-e main».
        out.extend(flag.split())
    if len(out) > FLAGS_MAX:
        raise АсмОшибка(f"У {tool} больше {FLAGS_MAX} ключей")
    return out


def _refuse(tool: str, flag: str, allowed: str) -> АсмОшибка:
    return АсмОшибка(f"Ключ {tool} {flag[:40]!r} не разрешён. Можно: {allowed}")


def _value(tokens: list[str], k: int, flag: str, tool: str) -> tuple[str, int]:
    if k + 1 >= len(tokens):
        raise АсмОшибка(f"У ключа {tool} {flag} нет значения")
    return tokens[k + 1], k + 2


def check_as(flags: Sequence[str]) -> list[str]:
    tokens = _tokens(flags, "as")
    out: list[str] = []
    k = 0
    while k < len(tokens):
        flag = tokens[k]
        if flag in _AS_SWITCHES:
            out.append(flag)
            k += 1
        elif flag == "-I" or flag.startswith("-I"):
            if flag == "-I":
                value, k = _value(tokens, k, flag, "as")
            else:
                value, k = flag[2:], k + 1
            # Каталог прогона — единственный, где есть файлы программы.
            if value not in (".", "./"):
                raise АсмОшибка("Ключ as -I — только каталог программы: -I .")
            out += ["-I", "."]
        else:
            raise _refuse("as", flag, AS_ALLOWED)
    return out


def check_ld(flags: Sequence[str]) -> list[str]:
    tokens = _tokens(flags, "ld")
    out: list[str] = []
    k = 0
    while k < len(tokens):
        flag = tokens[k]
        if flag in _LD_SWITCHES:
            out.append(flag)
            k += 1
        elif flag == "-e" or (flag.startswith("-e") and not flag.startswith("--")):
            if flag == "-e":
                value, k = _value(tokens, k, flag, "ld")
            else:
                value, k = flag[2:], k + 1
            if not _SYMBOL.match(value):
                raise АсмОшибка(f"Точка входа ld — имя символа, а не {value[:40]!r}")
            out += ["-e", value]
        elif flag == "--entry" or flag.startswith("--entry="):
            if flag == "--entry":
                value, k = _value(tokens, k, flag, "ld")
            else:
                value, k = flag.split("=", 1)[1], k + 1
            if not _SYMBOL.match(value):
                raise АсмОшибка(f"Точка входа ld — имя символа, а не {value[:40]!r}")
            out.append(f"--entry={value}")
        elif flag == "--subsystem" or flag.startswith("--subsystem="):
            if flag == "--subsystem":
                value, k = _value(tokens, k, flag, "ld")
            else:
                value, k = flag.split("=", 1)[1], k + 1
            # Окна у программы нет: трасса ведёт только консольные.
            if value != "console":
                raise АсмОшибка("Подсистема ld — только console")
            out += ["--subsystem", "console"]
        elif flag == "--image-base" or flag.startswith("--image-base="):
            if flag == "--image-base":
                value, k = _value(tokens, k, flag, "ld")
            else:
                value, k = flag.split("=", 1)[1], k + 1
            if not _IMAGE_BASE.match(value):
                raise АсмОшибка("База образа ld — шестнадцатеричное число: --image-base=0x140000000")
            out.append(f"--image-base={value}")
        elif flag == "-l" or flag.startswith("-l"):
            if flag == "-l":
                value, k = _value(tokens, k, flag, "ld")
            else:
                value, k = flag[2:], k + 1
            if value != "kernel32":
                raise АсмОшибка(f"Библиотека {value[:40]!r} не подключается: доступна только kernel32")
            # kernel32 ядро добавляет само, после prog.obj, где ей и место.
        else:
            raise _refuse("ld", flag, LD_ALLOWED)
    return out


def check_flags(tool: str, flags: Sequence[str]) -> list[str]:
    if tool == "as":
        return check_as(flags)
    if tool == "ld":
        return check_ld(flags)
    raise АсмОшибка(f"У MinGW x64 нет инструмента {tool!r}")


def source_problem(source: str) -> tuple[int, str] | None:
    """`(строка, текст)`, если исходник читает файлы машины (см. шапку модуля); иначе `None`.

    Это ошибка сборки программы, а не ядра: `build.py` показывает её сообщением `as` на строке,
    и `as` не запускается."""
    scan = _Scan()
    for number, line in enumerate(source.split("\n"), start=1):
        for stmt in statements(line, scan):
            word, _args = head(stmt)
            if not word:
                continue
            low = word.lower()
            if low in _FORBIDDEN_DIRECTIVES:
                return number, (f"директива {word} не поддерживается ({_FORBIDDEN_DIRECTIVES[low]}) "
                                f"— программа собирается из одного файла")
            if "\\" in word or "&" in word:
                return number, (f"имя команды или директивы из подстановки макроса "
                                f"({word[:40]}) не поддерживается")
            if not _only_in_strings(stmt):
                return number, ".include и .incbin не поддерживаются — программа собирается из одного файла"
    return None


def _only_in_strings(stmt: str) -> bool:
    """`.ascii "x.include"` — просто текст: слово внутри кавычек не директива."""
    outside = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stmt)
    return _INCLUDE_WORD.search(outside) is None


__all__ = ["check_flags", "check_as", "check_ld", "source_problem", "FLAGS_MAX", "AS_ALLOWED",
           "LD_ALLOWED"]
