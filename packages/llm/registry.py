"""
registry — реестр endpoint'ов и их возможностей.

Реестр в памяти: пакет намеренно не знает, где живут настройки. В продукте
описания endpoint'ов лежат в SQLite (ключ отдельно и зашифрованно), и служба
настроек будет складывать их сюда при старте. Пакету достаточно «есть список
описаний, у каждого id».

Здесь же живёт кэш транспортов: httpx.Client переиспользуется между вызовами
одного endpoint'а — иначе на каждый запрос новое TCP-соединение и новый TLS.
"""
from __future__ import annotations

import threading

from .errors import ErrorKind, LlmError
from .model import Caps, EndpointSpec, merged_caps
from . import backends

_lock = threading.RLock()
_specs: dict = {}
_backends: dict = {}


def register_endpoint(spec: EndpointSpec, transport=None) -> str:
    """Добавляет endpoint в реестр. Возвращает его id.

    Пробный вызов здесь **не** делается: он ходит в сеть, а регистрация должна
    работать и без неё (в тестах, при старте без интернета, при восстановлении
    настроек). Проба вызывается отдельно — probing.probe(spec) — и её результат
    возвращается сюда одной дверью: update_probe(id, result).

    `transport` — для тестов и для случая, когда клиент создаётся снаружи.
    """
    if not spec.id:
        raise LlmError(ErrorKind.UNSUPPORTED, "у endpoint'а должен быть id")
    with _lock:
        _specs[spec.id] = spec
        # Транспорт пересоздаём: описание могло поменяться (адрес, таймаут).
        _backends[spec.id] = backends.make(spec, transport)
    return spec.id


def unregister(endpoint_id: str) -> None:
    with _lock:
        _specs.pop(endpoint_id, None)
        _backends.pop(endpoint_id, None)


def clear() -> None:
    """Опустошает реестр. Нужен тестам, чтобы прогоны не влияли друг на друга."""
    with _lock:
        _specs.clear()
        _backends.clear()


def spec_of(endpoint_id: str) -> EndpointSpec:
    with _lock:
        spec = _specs.get(endpoint_id)
    if spec is None:
        raise LlmError(ErrorKind.NOT_FOUND, f"endpoint {endpoint_id!r} не зарегистрирован")
    return spec


def backend_of(endpoint_id: str):
    with _lock:
        backend = _backends.get(endpoint_id)
    if backend is None:
        raise LlmError(ErrorKind.NOT_FOUND, f"endpoint {endpoint_id!r} не зарегистрирован")
    return backend


def endpoints() -> list:
    with _lock:
        return list(_specs.values())


def capabilities(endpoint_id: str) -> Caps:
    """Что умеет пара (endpoint, модель): заявка владельца, перекрытая пробой.

    Единственная функция, которую бизнес-логика имеет право спрашивать про
    возможности. Ветвление по имени поставщика вместо неё — ошибка, которую
    придётся выкорчёвывать.
    """
    return merged_caps(spec_of(endpoint_id))


def update_probe(endpoint_id: str, probe) -> None:
    """Кладёт результат пробы в описание. Возможности пересчитаются сами.

    Единственная дверь для результата пробы: `probing` ходит сюда, а не пишет
    `spec.probe` напрямую. Присваивание мимо реестра работало ровно до первой
    вещи, которую проба меняет ПОМИМО поля probe (сейчас это уточнённый
    коэффициент оценки расхода): она появилась бы в одном пути и не появилась
    в другом, и одинаковые на вид пробы давали бы разный расход.
    """
    spec_of(endpoint_id).apply_probe(probe)


__all__ = ["register_endpoint", "unregister", "clear", "spec_of", "backend_of",
           "endpoints", "capabilities", "update_probe"]
