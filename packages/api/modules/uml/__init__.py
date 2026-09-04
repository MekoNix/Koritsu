"""
uml — модуль диаграмм UML: классы и объекты из чужого исходника.

Два вида схем и один модуль, потому что вход у них общий (исходники, язык,
палитра), а вопрос разный: диаграмма классов показывает, какие типы объявлены,
диаграмма объектов — какие экземпляры код создаёт и как они связаны. Первую
строит `uml_generator` разбором, вторую — `objektis` статической трассировкой;
обе через фасад `orchestrator.diagrams`, потому что напрямую службе к ним хода
нет (правило разреза).

Наружу пакет отдаёт `MODULE` и `router` — ровно то, что просит реестр
(`api/modules/__init__.py`).
"""
from __future__ import annotations

from .. import ModuleInfo
from .routes import router

MODULE = ModuleInfo(id="uml", title="UML diagrams", ready=True,
                    routes_prefix="/api/uml")

__all__ = ["MODULE", "router"]
