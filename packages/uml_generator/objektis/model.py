"""
Общий IR для диаграммы объектов (UML Object Diagram).

Статические бэкенды возвращают ObjectGraph;
builder.py превращает его в drawio XML.
"""
from dataclasses import dataclass, field as dc_field


@dataclass
class Slot:
    """Слот инстанса = имя поля + строковое значение."""
    name:  str
    value: str  # уже сериализованное представление: "42", "\"hello\"", "[1,2,3]", "<Task#3>"


@dataclass
class ObjectInstance:
    """Один экземпляр класса в snapshot'е."""
    name:        str               # переменная: "t1", "manager", "tasks[0]"
    type_name:   str               # класс: "Task", "TaskManager"
    slots:       list[Slot] = dc_field(default_factory=list)
    multiplicity: str       = ""   # "" | "*" | "5" — для свернутых коллекций
    is_summary:  bool       = False  # True если это представитель цикла/коллекции


@dataclass
class ObjectLink:
    """Ребро между инстансами (a.field = b)."""
    source: str   # имя инстанса-источника
    target: str   # имя инстанса-приёмника
    label:  str   # имя поля или роль ("parent", "items[0]", "owner")
    kind:   str = "association"  # "association" | "containment"


@dataclass
class ObjectGraph:
    """Полный snapshot: все инстансы + все links + опциональные заметки."""
    instances: list[ObjectInstance] = dc_field(default_factory=list)
    links:     list[ObjectLink]     = dc_field(default_factory=list)
    notes:     list[str]            = dc_field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.instances
