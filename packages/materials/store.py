"""
store — хранилище материалов на диске.

Никакой базы: каталог, внутри по подкаталогу на материал.

    <root>/<id>/source.<ext>   исходный файл, байт в байт
    <root>/<id>/units.json     содержимое, разбитое на строки или страницы
    <root>/<id>/meta.json      метаданные и результат разбора

Идентификатор — первые 16 знаков sha256 от содержимого. Отсюда бесплатно
следует главное свойство: тот же файл, добавленный второй раз (хоть под другим
именем, хоть вынутый из другого PDF), — тот же материал, и разбор второй раз не
считается. Разбор дорогой (OCR, PDF), поэтому он делается один раз при
добавлении и лежит рядом с файлом.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil

from .cards import card as make_card, inventory as make_inventory, preview_of
from .model import Card, Chunk, Material, MaterialsError, UNIT_PAGE, anchor
from ._parse import ext_of, parse

ID_LEN = 16


def material_id(data: bytes) -> str:
    """Устойчивый идентификатор материала: содержимое, а не имя и не время."""
    return hashlib.sha256(data).hexdigest()[:ID_LEN]


class Store:
    """Хранилище материалов одного проекта."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    # ---------------------------------------------------------------- добавление

    def add(self, source: str | bytes, name: str | None = None, do_ocr: bool = True,
            origin: dict | None = None) -> Material:
        """
        Добавить материал: путь к файлу или байты (тогда `name` обязательно).
        Возвращает материал; если такой уже есть — существующий, без повторного
        разбора. Производные материалы (картинки со страниц PDF) добавляются
        сами и перечислены в `material.children`.
        """
        if isinstance(source, bytes):
            if not name:
                raise MaterialsError("для байтов нужно имя материала")
            data = source
        else:
            if not os.path.isfile(source):
                raise MaterialsError(f"файл не найден: {source}")
            with open(source, "rb") as f:
                data = f.read()
            name = name or os.path.basename(source)

        mid = material_id(data)
        existing = self._load(mid)
        if existing is not None:
            return existing                 # тот же файл — та же работа, второй раз не делаем

        parsed = parse(data, name, do_ocr=do_ocr)
        ext = ext_of(name)
        # Превью считаем сейчас и кладём в метаданные: опись потом собирается
        # из одних meta.json, не поднимая содержимое с диска.
        if parsed.units:
            parsed.extra["preview"] = preview_of(parsed.units)
        material = Material(
            id=mid, name=name, kind=parsed.kind, ext=ext, size=len(data),
            added=datetime.datetime.now().isoformat(timespec="seconds"),
            unit=parsed.unit, count=len(parsed.units), lang=parsed.lang,
            origin=origin, notes=list(parsed.notes), extra=dict(parsed.extra),
            seq=self._next_seq())

        folder = os.path.join(self.root, mid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "source" + ext), "wb") as f:
            f.write(data)
        self._write_json(os.path.join(folder, "units.json"), parsed.units)
        self._write_json(os.path.join(folder, "meta.json"), material.to_dict())

        # Дети добавляются после родителя: так их порядок в описи идёт следом,
        # и в origin уже есть, на кого ссылаться.
        for d in parsed.derived:
            child_origin = dict(d.origin)
            child_ocr = bool(child_origin.pop("ocr", True)) and do_ocr
            child_origin["parent"] = mid
            child_origin["parent_name"] = name
            child = self.add(d.data, name=d.name, do_ocr=child_ocr, origin=child_origin)
            if child.id not in material.children:
                material.children.append(child.id)
        if material.children:
            self._write_json(os.path.join(folder, "meta.json"), material.to_dict())
        return material

    # ----------------------------------------------------------------- удаление

    def remove(self, mid: str, *, children: bool = True, keep=()) -> list[str]:
        """Убрать материал: и исходник, и разбор, и метаданные — целиком.
        → идентификаторы всего убранного, родитель первым.

        Нужно службе (`api`): пользователь удаляет загруженный файл, и
        байты обязаны уйти с тома, иначе квота считает то, чего человек уже не
        видит. Здесь, а не в службе, потому что раскладку `<root>/<id>/` знает
        хранилище: второй знающий про неё разошёлся бы с первым на первом же
        добавленном рядом файле.

        Нет такого материала — `MaterialsError`, как и у `get`: удаление
        несуществующего это опечатка вызывающего, а не «уже удалено».

        **Производные уходят вместе с родителем** (`children`: картинки,
        вынутые со страниц PDF; решение владельца 2026-09-04). Иначе удаление
        методички оставляло бы на томе полсотни картинок, которых человек в
        описи больше не видит, а квота — считает.

        Два исключения, и оба про ссылки, а не про родство:

        * `keep` — идентификаторы, которые вызывающий просит не трогать. Про
          ссылки знает он: значения тегов проекта живут в `orchestrator`, а
          этот пакет про проект ничего не знает и знать не должен.
        * ребёнок, которого числит своим ещё кто-то живой, остаётся сам.
          Идентификатор — хеш содержимого, поэтому одна и та же картинка в двух
          методичках это ОДИН материал, записанный в `children` обеих; удалить
          его вместе с первой значило бы вынуть картинку из второй.
        """
        m = self.get(mid)
        беречь = {str(k) for k in keep}
        убрать = [m.id]
        if children:
            прочие = {x.id: x for x in self.list() if x.id != m.id}
            очередь = list(m.children)
            while очередь:
                cid = очередь.pop(0)
                ребёнок = прочие.get(cid)
                if cid in убрать or cid in беречь or ребёнок is None:
                    continue
                чужой = any(cid in x.children for oid, x in прочие.items()
                            if oid != cid and oid not in убрать)
                if чужой:
                    continue
                убрать.append(cid)
                очередь.extend(ребёнок.children)     # внуки, если они заведутся
        # Без `ignore_errors`: каждый каталог здесь только что читался
        # (`get`/`list`), и его исчезновение — беда тома, а не «уже удалено».
        for i in убрать:
            shutil.rmtree(os.path.join(self.root, i))
        return убрать

    # ------------------------------------------------------------------- чтение

    def list(self) -> list[Material]:
        """Все материалы в порядке добавления."""
        out = []
        for mid in os.listdir(self.root):
            m = self._load(mid)
            if m is not None:
                out.append(m)
        return sorted(out, key=lambda m: (m.seq, m.id))

    def get(self, mid: str) -> Material:
        m = self._load(mid)
        if m is None:
            raise MaterialsError(f"материал не найден: {mid}")
        return m

    def units(self, mid: str) -> list[str]:
        """Содержимое кусками (строки или страницы) — как его разобрали."""
        m = self.get(mid)
        path = os.path.join(self.root, m.id, "units.json")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def read(self, mid: str, start: int | None = None, end: int | None = None) -> Chunk:
        """
        Кусок содержимого с якорем. Границы включительные, нумерация с единицы,
        выход за пределы обрезается молча — модель ошибается в номерах, а ронять
        сборку контекста из-за этого незачем; якорь показывает, что отдали.
        """
        m = self.get(mid)
        units = self.units(mid)
        if not units:
            return Chunk(id=m.id, name=m.name, unit=m.unit, start=0, end=0, text="",
                         anchor=anchor(m.name, "", 0, 0))
        lo = max(1, 1 if start is None else int(start))
        hi = min(len(units), len(units) if end is None else int(end))
        if lo > hi:
            lo, hi = min(lo, len(units)), min(lo, len(units))
        joiner = "\n\n" if m.unit == UNIT_PAGE else "\n"
        text = joiner.join(units[lo - 1:hi])
        return Chunk(id=m.id, name=m.name, unit=m.unit, start=lo, end=hi, text=text,
                     anchor=anchor(m.name, m.unit, lo, hi))

    def blob(self, mid: str) -> bytes:
        """Байты исходного файла — то, что вставляется в отчёт по идентификатору."""
        with open(self.path(mid), "rb") as f:
            return f.read()

    def path(self, mid: str) -> str:
        """Путь к исходному файлу материала на диске."""
        m = self.get(mid)
        p = os.path.join(self.root, m.id, "source" + m.ext)
        if not os.path.isfile(p):
            raise MaterialsError(f"файл материала пропал: {m.id}")
        return p

    # -------------------------------------------------------------- для промпта

    def card(self, mid: str) -> Card:
        """Карточка материала: коротко и без модели."""
        return make_card(self.get(mid))

    def tables(self, mid: str) -> list[dict]:
        """Таблицы материала: у PDF [{"page": 4, "rows": …}], у Word —
        [{"paragraph": 7, "rows": …}]: номер единицы, на которой таблица стоит."""
        return list(self.get(mid).extra.get("tables") or ())

    def inventory(self) -> str:
        """Опись проекта — карточки всех материалов подряд."""
        return make_inventory(self.list())

    # -------------------------------------------------------------- внутреннее

    def _load(self, mid: str) -> Material | None:
        path = os.path.join(self.root, mid, "meta.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return Material.from_dict(json.load(f))

    def _next_seq(self) -> int:
        return max((m.seq for m in self.list()), default=0) + 1

    @staticmethod
    def _write_json(path: str, obj) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
