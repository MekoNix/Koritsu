"""
_trace — общее состояние статической трассировки для бэкендов objektis.

Бэкенд (py_static, cs_static, cpp_static) ходит по CST своего языка и
вызывает: new_obj / set_slot / append / forget / note; graph() собирает
ObjectGraph. Значения слотов — текст из исходника; ссылка на известный
объект хранится как его имя и превращается в «→ имя» + ObjectLink.
"""
from dataclasses import dataclass, field as dc_field

from .model import ObjectGraph, ObjectInstance, ObjectLink, Slot

MAX_VALUE_LEN = 60
MAX_CALL_DEPTH = 24     # глубже не заходим: рекурсивный метод иначе не остановить
MAX_ATTR_DEPTH = 8      # вложенность полей-объектов (new_obj → attr_types → new_obj)


@dataclass
class Method:
    params:   list[str]          # без self/this
    defaults: dict[str, str]
    body:     object             # узел тела (block / compound_statement)
    node:     object = None      # весь узел объявления (для init-list и т.п.)


@dataclass
class ClassDef:
    name:    str
    bases:   list[str]
    attrs:   dict[str, str] = dc_field(default_factory=dict)   # поля класса → текст умолчания
    attr_types: dict[str, str] = dc_field(default_factory=dict)  # поля → имя типа (если это класс)
    methods: dict[str, Method] = dc_field(default_factory=dict)
    ctor:    str = "__init__"                                  # имя конструктора в methods


@dataclass
class Obj:
    name:  str
    type:  str
    slots: dict[str, str] = dc_field(default_factory=dict)
    lists: dict[str, list[str]] = dc_field(default_factory=dict)


class TraceState:
    def __init__(self, src: bytes):
        self.src = src
        self.classes: dict[str, ClassDef] = {}
        self.objs: dict[str, Obj] = {}
        self.order: list[str] = []
        self.links: list[ObjectLink] = []
        self.notes: list[str] = []
        self.counters: dict[str, int] = {}
        self.depth = 0

    # ── глубина трассировки ──
    def enter_call(self) -> bool:
        """Можно ли войти в тело метода. False — исчерпана глубина (рекурсия)."""
        if self.depth >= MAX_CALL_DEPTH:
            self.note("objektis: рекурсия или слишком глубокие вызовы — "
                      "часть тел методов не трассирована")
            return False
        self.depth += 1
        return True

    def leave_call(self):
        self.depth -= 1

    # ── утилиты ──
    def text(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def note(self, msg: str):
        if msg not in self.notes:
            self.notes.append(msg)

    def auto_name(self, cls: str) -> str:
        n = self.counters.get(cls, 0) + 1
        self.counters[cls] = n
        return f"{cls[:1].lower()}{cls[1:]}{n}"

    def is_obj(self, v: str) -> bool:
        return v in self.objs

    def canon(self, v: str) -> str:
        """Алиас (`y = m`) → каноническое имя объекта; прочий текст — как есть."""
        o = self.objs.get(v)
        return o.name if o is not None else v

    def fmt(self, v: str) -> str:
        if self.is_obj(v):
            return f"→{self.canon(v)}"
        return v if len(v) <= MAX_VALUE_LEN else v[:MAX_VALUE_LEN - 3] + "..."

    # ── классы ──
    def mro(self, cls_name: str) -> list[ClassDef]:
        out, seen, queue = [], set(), [cls_name]
        while queue:
            n = queue.pop(0)
            if n in seen or n not in self.classes:
                continue
            seen.add(n)
            out.append(self.classes[n])
            queue.extend(self.classes[n].bases)
        return out

    def find_method(self, cls_name: str, mname: str) -> Method | None:
        for c in self.mro(cls_name):
            if mname in c.methods:
                return c.methods[mname]
        return None

    # ── объекты ──
    def new_obj(self, name: str, cls: str, path: tuple[str, ...] = ()) -> Obj:
        """
        Экземпляр класса `cls`. Поля-объекты по значению разворачиваются вложенными
        экземплярами; `path` — цепочка классов, уже развёрнутых выше по этой ветке.
        Она же обрывает рекурсию: при взаимной ссылке (Order ↔ Customer) без неё
        `new_obj` → `attr_types` → `new_obj` уходит до RecursionError.
        """
        if name in self.objs:
            self.forget(name)
        o = Obj(name, cls)
        self.objs[name] = o
        self.order.append(name)
        path = path + (cls,)
        for c in reversed(self.mro(cls)):        # поля класса с умолчаниями
            for k, v in c.attrs.items():
                o.slots[k] = v
                if v == "[]":
                    o.lists[k] = []
            for k, t in c.attr_types.items():   # поле-объект по значению → вложенный экземпляр
                if t not in self.classes or o.slots.get(k) not in ("?", None):
                    continue
                if t in path:
                    self.note(f"objektis: взаимная ссылка полей-объектов "
                              f"({' → '.join(path)} → {t}) — вложенный экземпляр не создан")
                    continue
                if len(path) >= MAX_ATTR_DEPTH:
                    self.note(f"objektis: поля-объекты вложены глубже {MAX_ATTR_DEPTH} — "
                              f"дальше не разворачиваем")
                    continue
                child = self.new_obj(f"{name}.{k}", t, path)
                self.set_slot(o, k, child.name)
        return o

    def alias(self, name: str, target: str):
        if target in self.objs:
            self.objs[name] = self.objs[target]

    def resolve(self, name: str) -> Obj | None:
        return self.objs.get(name)

    def set_slot(self, obj: Obj, attr: str, value: str):
        value = self.canon(value)
        self.links = [l for l in self.links if not (l.source == obj.name and l.label == attr)]
        if self.is_obj(value) and value != obj.name:
            self.links.append(ObjectLink(obj.name, value, attr))
        obj.slots[attr] = value
        if value == "[]":
            obj.lists[attr] = []

    def set_list(self, obj: Obj, attr: str, items: list[str]):
        obj.lists[attr] = []
        self.links = [l for l in self.links
                      if not (l.source == obj.name and l.label.startswith(attr + "["))]
        obj.slots[attr] = "[]"
        for it in items:
            self.append(obj, attr, it)

    def append(self, obj: Obj, attr: str, value: str):
        value = self.canon(value)
        items = obj.lists.setdefault(attr, [])
        items.append(value)
        if self.is_obj(value):
            self.links.append(ObjectLink(obj.name, value, f"{attr}[{len(items) - 1}]", "containment"))
        obj.slots[attr] = "[" + ", ".join(self.fmt(i) for i in items) + "]"

    def forget(self, name: str):
        obj = self.objs.pop(name, None)
        if obj is not None and obj.name == name:
            self.order.remove(name)
            self.links = [l for l in self.links if name not in (l.source, l.target)]

    # ── результат ──
    def graph(self, empty_note: str) -> ObjectGraph:
        instances, seen = [], set()
        for name in self.order:
            obj = self.objs.get(name)
            if obj is None or obj.name != name or name in seen:
                continue
            seen.add(name)
            instances.append(ObjectInstance(
                name=obj.name, type_name=obj.type,
                slots=[Slot(k, f"→ {self.canon(v)}" if self.is_obj(v) else self.fmt(v))
                       for k, v in obj.slots.items()]))
        if not instances and not self.notes:
            self.notes.append(empty_note)
        return ObjectGraph(instances=instances, links=list(self.links), notes=list(self.notes))
