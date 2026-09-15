"""pe.py — разбор PE32+ (`Magic 0x20B`), который собрал `x86_64-w64-mingw32-ld`.

Только `struct` из стандартной библиотеки: ядро не тянет сторонних пакетов, а нужно от образа
немного — база, точка входа, секции, таблица импорта и таблица символов COFF.

Раскладка, которую даёт ld 2.44 на лабе (`samples/lab.pe-header.txt`, `lab.objdump.txt`):

    ImageBase 0000000140000000, AddressOfEntryPoint 1000 (начало .text, если нет -e)
    .text  0000000140001000  код программы, в конце заглушки `jmp [rip+__imp_X]`
    .data  0000000140002000   .rdata 0000000140003000   .idata 0000000140004000 (импорт, IAT)

**Импорт.** Программа зовёт `call WriteFile`, это заглушка в `.text`, а заглушка прыгает через
ячейку IAT. Ячейка — то место, по которому трассировщик узнаёт функцию: `imports` отображает VA
ячейки в `kernel32.WriteFile` (имя DLL строчными и без `.dll`).

**Где в образе секции объектного файла.** Листинг `as` знает смещение от начала секции
`prog.obj`, а трасса — VA. ld кладёт в секцию образа сначала `prog.obj`, потом члены
библиотеки импорта, но полагаться на «с нуля» нельзя: `.rdata` образа начинается служебными
таблицами ld. Точный ответ лежит в таблице символов COFF, которую ld оставляет в образе (без
`-s`): у каждого входного файла есть символы секций (`.text`, класс STATIC, со
вспомогательной записью `scnlen`), и их значение — смещение куска этого файла в секции образа.
Символы `prog.obj` идут первыми, до второй записи `.file`. Таблицы нет — берётся начало секции
образа с тем же именем.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..model import АсмОшибка

MACHINE_AMD64 = 0x8664
MAGIC_PE32_PLUS = 0x20B

SCN_CNT_CODE = 0x00000020
SCN_CNT_INITIALIZED_DATA = 0x00000040
SCN_CNT_UNINITIALIZED_DATA = 0x00000080
SCN_MEM_DISCARDABLE = 0x02000000
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000

SYM_CLASS_STATIC = 3
SYM_CLASS_FILE = 103

DIR_IMPORT = 1

# Потолки разбора: образ приходит из ld, но собран из чужого исходника, и зациклить разборщик
# кривой таблицей не должно быть возможно.
IMPORT_DLLS_MAX = 256
IMPORT_THUNKS_MAX = 4096
NAME_MAX = 512
SYMBOLS_MAX = 200_000


def _fail(what: str) -> АсмОшибка:
    return АсмОшибка(f"Образ PE не разобран: {what}")


@dataclass(frozen=True)
class Section:
    name: str
    rva: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    flags: int

    @property
    def executable(self) -> bool:
        return bool(self.flags & (SCN_MEM_EXECUTE | SCN_CNT_CODE))

    @property
    def writable(self) -> bool:
        return bool(self.flags & SCN_MEM_WRITE)

    @property
    def size(self) -> int:
        """Размер в памяти. У секции без `VirtualSize` (так бывает у старых линковщиков) —
        размер на диске."""
        return self.virtual_size or self.raw_size

    @property
    def cls(self) -> str:
        """Класс секции для окон: CODE, DATA, BSS, RDATA, IMPORT, RELOC, DEBUG."""
        name = self.name.lower()
        if name == ".idata":
            return "IMPORT"
        if name == ".reloc":
            return "RELOC"
        if name.startswith((".debug", ".zdebug")) or (self.flags & SCN_MEM_DISCARDABLE
                                                      and not self.executable):
            return "DEBUG"
        if self.executable:
            return "CODE"
        if name == ".bss" or (self.flags & SCN_CNT_UNINITIALIZED_DATA
                              and not self.flags & SCN_CNT_INITIALIZED_DATA):
            return "BSS"
        if self.writable:
            return "DATA"
        return "RDATA"


@dataclass(frozen=True)
class CoffSymbol:
    index: int
    name: str
    value: int
    section: int          # 1… — номер секции образа; 0 — внешний; -1 — абсолютный; -2 — отладочный
    type: int
    storage: int
    aux: int


@dataclass
class PeImage:
    path: Path
    data: bytes
    image_base: int
    entry_rva: int
    subsystem: int
    dll_characteristics: int
    stack_reserve: int
    stack_commit: int
    sections: list[Section]
    imports: dict[int, str] = field(default_factory=dict)
    symbols: list[CoffSymbol] = field(default_factory=list)

    @property
    def entry(self) -> int:
        return self.image_base + self.entry_rva

    def va(self, section: Section) -> int:
        return self.image_base + section.rva

    def section_at(self, va: int) -> Section | None:
        rva = va - self.image_base
        for s in self.sections:
            if s.rva <= rva < s.rva + max(s.size, 1):
                return s
        return None

    def read(self, va: int, length: int) -> bytes:
        """Байты образа по VA так, как их положит загрузчик: за концом данных на диске —
        нули (так выглядят `.bss` и хвост выровненной секции). Вне секций — `АсмОшибка`."""
        s = self.section_at(va)
        if s is None or length < 0:
            raise _fail(f"адрес {va:016X} вне секций")
        start = va - self.image_base - s.rva
        length = min(length, s.size - start)
        have = max(0, min(length, s.raw_size - start))
        chunk = self.data[s.raw_offset + start: s.raw_offset + start + have] if have else b""
        return chunk + bytes(length - len(chunk))

    def symbol_va(self, sym: CoffSymbol) -> int | None:
        if 1 <= sym.section <= len(self.sections):
            return self.image_base + self.sections[sym.section - 1].rva + sym.value
        return None

    def object_section_bases(self) -> dict[str, int]:
        """VA начала каждой секции `prog.obj` в образе, по символам секций первого файла
        (см. шапку модуля). Пусто, если таблицы символов нет."""
        bases: dict[str, int] = {}
        files = 0
        for sym in self.symbols:
            if sym.storage == SYM_CLASS_FILE:
                files += 1
                if files > 1:
                    break
                continue
            if (sym.storage == SYM_CLASS_STATIC and sym.aux >= 1 and sym.name.startswith(".")
                    and sym.name not in bases):
                va = self.symbol_va(sym)
                if va is not None:
                    bases[sym.name] = va
        return bases

    def find_symbol(self, name: str) -> CoffSymbol | None:
        for sym in self.symbols:
            if sym.name == name and sym.section >= 1:
                return sym
        return None


def _unpack(fmt: str, data: bytes, offset: int, what: str) -> tuple:
    try:
        return struct.unpack_from(fmt, data, offset)
    except struct.error:
        raise _fail(f"файл обрывается в {what}") from None


def _cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        return ""
    end = data.find(b"\0", offset, offset + NAME_MAX)
    if end < 0:
        end = min(len(data), offset + NAME_MAX)
    return data[offset:end].decode("ascii", "replace")


def parse(path: Path) -> PeImage:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise _fail(f"не прочитан: {e}") from None
    return parse_bytes(data, Path(path))


def parse_bytes(data: bytes, path: Path = Path("prog.exe")) -> PeImage:
    if data[:2] != b"MZ":
        raise _fail("нет подписи MZ")
    (lfanew,) = _unpack("<I", data, 0x3C, "заголовке DOS")
    if data[lfanew:lfanew + 4] != b"PE\0\0":
        raise _fail("нет подписи PE")
    machine, nsections, _stamp, sym_ptr, nsyms, opt_size, _chars = _unpack(
        "<HHIIIHH", data, lfanew + 4, "заголовке COFF")
    if machine != MACHINE_AMD64:
        raise _fail(f"машина {machine:04X}, а нужна x86-64 (8664)")
    opt = lfanew + 24
    (magic,) = _unpack("<H", data, opt, "необязательном заголовке")
    if magic != MAGIC_PE32_PLUS:
        raise _fail(f"Magic {magic:04X}, а у PE32+ — 020B")
    (_magic, _lmaj, _lmin, _code_size, _init_size, _uninit_size, entry_rva, _base_of_code,
     image_base, _sect_align, _file_align, _os_maj, _os_min, _img_maj, _img_min, _sub_maj,
     _sub_min, _win32, _image_size, _headers_size, _checksum, subsystem, dll_chars,
     stack_reserve, stack_commit, _heap_reserve, _heap_commit, _loader_flags,
     ndirs) = _unpack("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII", data, opt, "необязательном заголовке")
    dirs: list[tuple[int, int]] = []
    for k in range(min(ndirs, 16)):
        dirs.append(_unpack("<II", data, opt + 112 + 8 * k, "каталогах данных"))

    strtab = sym_ptr + nsyms * 18 if sym_ptr else 0

    def long_name(offset: int) -> str:
        return _cstring(data, strtab + offset) if strtab else ""

    sections: list[Section] = []
    sec_off = opt + opt_size
    for k in range(nsections):
        raw_name, vsize, rva, raw_size, raw_ptr, _rel, _lines, _nrel, _nlines, flags = _unpack(
            "<8sIIIIIIHHI", data, sec_off + 40 * k, "таблице секций")
        name = raw_name.rstrip(b"\0").decode("ascii", "replace")
        # Длинные имена (`.debug_info`) в образе лежат в таблице строк: имя секции — `/4`.
        if name.startswith("/") and name[1:].isdigit():
            name = long_name(int(name[1:])) or name
        sections.append(Section(name=name, rva=rva, virtual_size=vsize, raw_offset=raw_ptr,
                                raw_size=raw_size, flags=flags))

    image = PeImage(path=path, data=data, image_base=image_base, entry_rva=entry_rva,
                    subsystem=subsystem, dll_characteristics=dll_chars,
                    stack_reserve=stack_reserve, stack_commit=stack_commit, sections=sections)
    if len(dirs) > DIR_IMPORT and dirs[DIR_IMPORT][0]:
        image.imports = _imports(image, dirs[DIR_IMPORT][0])
    if sym_ptr and nsyms:
        image.symbols = _symbols(data, sym_ptr, min(nsyms, SYMBOLS_MAX), long_name)
    return image


def _file_offset(image: PeImage, rva: int) -> int | None:
    for s in image.sections:
        if s.rva <= rva < s.rva + max(s.size, s.raw_size):
            off = rva - s.rva
            return s.raw_offset + off if off < s.raw_size else None
    return None


def _imports(image: PeImage, import_rva: int) -> dict[int, str]:
    data = image.data
    out: dict[int, str] = {}
    desc = _file_offset(image, import_rva)
    if desc is None:
        return out
    for n in range(IMPORT_DLLS_MAX):
        lookup_rva, _stamp, _forwarder, name_rva, iat_rva = _unpack(
            "<IIIII", data, desc + 20 * n, "таблице импорта")
        if not (lookup_rva or name_rva or iat_rva):
            break
        name_off = _file_offset(image, name_rva)
        dll = _cstring(data, name_off) if name_off is not None else ""
        dll = dll.lower()
        if dll.endswith(".dll"):
            dll = dll[:-4]
        # Имена функций — по таблице поиска; если её нет (так бывает), по самой IAT до загрузки.
        table = _file_offset(image, lookup_rva or iat_rva)
        if table is None:
            continue
        for k in range(IMPORT_THUNKS_MAX):
            (thunk,) = _unpack("<Q", data, table + 8 * k, "таблице импорта")
            if thunk == 0:
                break
            if thunk & (1 << 63):
                func = f"#{thunk & 0xFFFF}"
            else:
                hint_off = _file_offset(image, thunk & 0x7FFFFFFF)
                func = _cstring(data, hint_off + 2) if hint_off is not None else f"?{k}"
            out[image.image_base + iat_rva + 8 * k] = f"{dll}.{func}" if dll else func
    return out


def _symbols(data: bytes, sym_ptr: int, nsyms: int, long_name) -> list[CoffSymbol]:
    out: list[CoffSymbol] = []
    k = 0
    while k < nsyms:
        if sym_ptr + (k + 1) * 18 > len(data):
            break
        raw_name, value, section, typ, storage, naux = struct.unpack_from(
            "<8sIhHBB", data, sym_ptr + k * 18)
        if raw_name[:4] == b"\0\0\0\0":
            name = long_name(struct.unpack_from("<I", raw_name, 4)[0])
        else:
            name = raw_name.rstrip(b"\0").decode("ascii", "replace")
        out.append(CoffSymbol(index=k, name=name, value=value, section=section, type=typ,
                              storage=storage, aux=naux))
        k += 1 + naux
    return out


__all__ = ["PeImage", "Section", "CoffSymbol", "parse", "parse_bytes"]
