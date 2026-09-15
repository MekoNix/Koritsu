"""wine_prefix.py — префикс Wine исполнителя: общий в образе и свой на каждый прогон.

Только стандартная библиотека и без импортов пакета: файл запускается при сборке образа
исполнителя сам по себе (`python3 wine_prefix.py prepare <каталог>`), до того как в образ
приезжает остальной код, — так слой с префиксом не пересобирается от каждой правки.

**Общий префикс** (`prepare`). `wineboot --init` создаёт префикс на 770 МБ, из них 700 МБ —
`system32`, и почти всё там — байт в байт файлы пакета из `x86_64-windows`. Каждый такой
файл заменяется символьной ссылкой на файл пакета: Wine открывает DLL по ссылке так же, как
по файлу, а префикс сжимается до 12 МБ. Ссылка `dosdevices/z:` на корень машины удаляется —
диска `Z:` у программы нет (путь `\\\\?\\unix\\` Wine всё равно открывает, границу держит
контейнер).

**Префикс прогона** (`clone`). Wine пишет в префикс на каждом запуске (`*.reg`), а один
wineserver обслуживает один префикс: общий префикс на всех означал бы общий реестр и общий
сервер у параллельных прогонов. Поэтому прогону — свой каталог на tmpfs: дерево каталогов
заново, `*.reg` копией (их Wine перезаписывает), остальные файлы — ссылками на общий префикс,
ссылки — как есть. Это около 2 МБ и десятков миллисекунд. Жёсткие ссылки (`cp -al`) здесь
не годятся: корень контейнера и tmpfs — разные файловые системы; overlay без прав не
монтируется.

Wine отказывается работать с префиксом, который принадлежит не текущему UID, и с каталогом,
родитель которого чужой, если самого префикса ещё нет, — поэтому каталог прогона заводится
до запуска.
"""
from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WINE64 = "/usr/lib/wine/wine64"
WINESERVER = "/usr/lib/wine/wineserver64"
PACKAGE_DLLS = "/usr/lib/x86_64-linux-gnu/wine/x86_64-windows"
# `winedbg.exe=d` — без него необработанное исключение запускает `winedbg --auto`, и тот
# пишет бэктрейс в stdout программы; `mscoree,mshtml=` — не спрашивать Mono и Gecko;
# `winemenubuilder.exe=d` — ярлыков и ассоциаций файлов исполнителю не нужно. Службы Wine
# (`services.exe` и запускаемые им `winedevice`, `plugplay`, `rpcss`, `svchost`, `explorer`)
# консольной программе на kernel32 не нужны: без них холодный старт — 0,2 с вместо 0,7 с, и
# на прогон приходится один wineserver, а не восемь процессов с полусотней потоков.
# Создать префикс без служб нельзя: `wineboot --init` регистрирует их через `services.exe`.
BOOT_DLL_OVERRIDES = "mscoree,mshtml=;winedbg.exe=d;winemenubuilder.exe=d"
DLL_OVERRIDES = (BOOT_DLL_OVERRIDES + ";"
                 "services.exe,winedevice.exe,plugplay.exe,svchost.exe,rpcss.exe,explorer.exe=d")
COPIED = (".reg",)


def wine_env(prefix: Path, home: Path, overrides: str = DLL_OVERRIDES) -> dict:
    """Закрытое окружение запуска Wine: ничего из окружения исполнителя."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(home),
        "LANG": "C.UTF-8",
        "WINEPREFIX": str(prefix),
        "WINEDEBUG": "-all",
        "WINEDLLOVERRIDES": overrides,
    }


def _du(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            total += st.st_blocks * 512
    return total


def prepare(prefix: Path, dlls: Path = Path(PACKAGE_DLLS)) -> dict:
    """Создать общий префикс и заменить совпадающие с пакетом файлы ссылками."""
    prefix = Path(prefix)
    prefix.mkdir(parents=True, exist_ok=True)
    home = Path(os.environ.get("HOME") or "/tmp")
    env = wine_env(prefix, home, BOOT_DLL_OVERRIDES)
    started = time.monotonic()
    subprocess.run([WINE64, "wineboot", "--init"], env=env, check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([WINESERVER, "-w"], env=env, check=False)
    boot_s = time.monotonic() - started
    before = _du(prefix)
    by_name = {p.name.lower(): p for p in dlls.iterdir() if p.is_file()} if dlls.is_dir() else {}
    linked = 0
    for root, _dirs, files in os.walk(prefix / "drive_c"):
        for name in files:
            path = Path(root) / name
            if path.is_symlink():
                continue
            source = by_name.get(name.lower())
            if source is None or path.stat().st_size != source.stat().st_size:
                continue
            if not filecmp.cmp(path, source, shallow=False):
                continue
            path.unlink()
            path.symlink_to(source)
            linked += 1
    z = prefix / "dosdevices" / "z:"
    if z.is_symlink():
        z.unlink()
    return {"boot_s": round(boot_s, 1), "before_mb": before // 2**20,
            "after_mb": _du(prefix) // 2**20, "linked": linked}


def clone(base: Path, target: Path) -> int:
    """Префикс прогона поверх общего. `target` уже заведён и принадлежит нам. Отдаёт байты,
    записанные копиями."""
    base = Path(base)
    target = Path(target)
    copied = 0
    for root, dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        dest_root = target if rel == "." else target / rel
        for name in dirs:
            src = os.path.join(root, name)
            dst = dest_root / name
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            else:
                dst.mkdir(mode=0o700)
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            src = os.path.join(root, name)
            dst = dest_root / name
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            elif name.endswith(COPIED):
                shutil.copyfile(src, dst)
                copied += os.path.getsize(dst)
            else:
                os.symlink(src, dst)
    return copied


def kill_server(prefix: Path, home: Path, tmp: Path = Path("/tmp")) -> None:
    """Погасить wineserver префикса и все процессы Wine при нём, затем убрать каталог сервера.

    Каталог сокета wineserver Wine заводит сам — `/tmp/wine-XXXXXX/server-<dev>-<inode>`, по
    устройству и inode префикса — и после выхода сервера не удаляет. Перенести его в каталог
    прогона нельзя: с заданным `TMPDIR` Wine 10 падает на старте. Поэтому он находится по имени
    и удаляется здесь."""
    try:
        st = os.stat(prefix)
        server = f"server-{st.st_dev:x}-{st.st_ino:x}"
    except OSError:
        server = None
    try:
        subprocess.run([WINESERVER, "-k"], env=wine_env(prefix, home), timeout=10,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    if server is None:
        return
    for holder in tmp.glob("wine-*"):
        target = holder / server
        if target.is_dir() and holder.stat().st_uid == os.getuid():
            shutil.rmtree(target, ignore_errors=True)
            try:
                holder.rmdir()
            except OSError:
                pass


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "prepare":
        info = prepare(Path(argv[1]))
        print(f"префикс {argv[1]}: wineboot {info['boot_s']} с, {info['before_mb']} МБ → "
              f"{info['after_mb']} МБ, ссылок на файлы пакета {info['linked']}")
        return 0
    print("usage: wine_prefix.py prepare <каталог>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
