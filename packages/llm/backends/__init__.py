"""
backends — единственное место в пакете, где вообще есть разница между
поставщиками. Всё остальное спрашивает capabilities() и про протокол не знает.
"""
from .base import Backend, Request, make

__all__ = ["Backend", "Request", "make"]
