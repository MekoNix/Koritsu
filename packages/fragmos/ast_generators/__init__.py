from .python_ast import PythonAST
from .cpp_ast import CppAST
from .csharp_ast import CSharpAST
from .base import ASTGenerator

_GENERATORS = {
    "python": PythonAST,
    "cpp": CppAST,
    "c++": CppAST,
    "csharp": CSharpAST,
    "c#": CSharpAST,
}


def get_ast_generator(language: str) -> ASTGenerator:
    key = language.lower().strip()
    cls = _GENERATORS.get(key)
    if cls is None:
        supported = ", ".join(_GENERATORS.keys())
        raise ValueError(f"Unsupported language: '{language}'. Supported: {supported}")
    return cls()
