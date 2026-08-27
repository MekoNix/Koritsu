"""
Фасад objektis: выбор бэкенда по языку.

Вынесен в отдельный файл (не в __init__.py), чтобы тесты могли импортировать
его без триггера __init__.py пакета fragmos (который тянет drawpyo).
"""
from .model import ObjectGraph


def extract_objects(
    source: str,
    language: str,
    *,
    files: list[dict] | None = None,
    timeout: float = 10.0,
) -> ObjectGraph:
    """См. описание в objektis/__init__.py."""
    lang = (language or "").lower()

    try:
        if lang == "python":
            from .py_dynamic import extract as _extract_py
            return _extract_py(source, timeout=timeout)
        if lang == "csharp":
            from .cs_dynamic import extract as _extract_cs
            return _extract_cs(source, files=files, timeout=timeout)
        if lang == "cpp":
            from .cpp_static import extract as _extract_cpp
            return _extract_cpp(source, files=files)
    except Exception as e:
        return ObjectGraph(notes=[f"objektis: {type(e).__name__}: {e}"])

    return ObjectGraph(notes=[f"objektis: язык {language!r} не поддерживается"])
