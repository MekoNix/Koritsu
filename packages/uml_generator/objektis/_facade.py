"""
Фасад objektis: выбор бэкенда по языку.

Правило безопасности: пользовательский код НИКОГДА не выполняется.
Бэкенды должны быть статическими (tree-sitter-трассировка main()).
Динамические бэкенды 1.x (exec в subprocess, dotnet run) удалены.
"""
from .model import ObjectGraph

# язык → модуль статического бэкенда
_BACKENDS: dict[str, str] = {"python": "py_static", "csharp": "cs_static", "cpp": "cpp_static"}


def extract_objects(source: str, language: str, *, files: list[dict] | None = None) -> ObjectGraph:
    """Построить ObjectGraph из исходника без его выполнения.

    Для неизвестного языка возвращает пустой граф с заметкой. На любой ошибке бэкенда тоже возвращает граф с заметкой.
    """
    lang = (language or "").lower()
    mod_name = _BACKENDS.get(lang)
    if mod_name is None:
        return ObjectGraph(notes=[
            f"objektis: статический разбор для языка {language!r} не реализован "
            "(код не выполняется)",
        ])
    try:
        import importlib
        mod = importlib.import_module(f".{mod_name}", __package__)
        return mod.extract(source, files=files)
    except Exception as e:  # noqa: BLE001 — бэкенд не должен ронять генератор
        return ObjectGraph(notes=[f"objektis: {type(e).__name__}: {e}"])
