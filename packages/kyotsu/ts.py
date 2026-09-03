"""
ts.py — единая точка получения tree-sitter парсера.

Грамматики — отдельные pip-пакеты (tree-sitter-python / -cpp / -c-sharp),
API tree-sitter >= 0.23: Parser(Language(<capsule>)). Парсеры кэшируются.

Один на весь проект: до 2.0.0a4.2 этот файл лежал двумя байт-в-байт копиями
(`uml_generator/_ts.py` и `fragmos/ast_generators/ts.py`). Кэш парсеров при
этом тоже был двойной — грамматика грузилась дважды за прогон.
"""

import importlib
from functools import lru_cache

from tree_sitter import Language, Parser

_MODULES = {
    'python': 'tree_sitter_python',
    'cpp': 'tree_sitter_cpp',
    'c_sharp': 'tree_sitter_c_sharp',
}


@lru_cache(maxsize=None)
def get_language(name: str) -> Language:
    mod = importlib.import_module(_MODULES[name])
    return Language(mod.language())


@lru_cache(maxsize=None)
def get_parser(name: str) -> Parser:
    return Parser(get_language(name))
