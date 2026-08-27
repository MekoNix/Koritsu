"""
builder — sub-package для генерации draw.io flowchart XML.

Публичный API:
  generate_from_code(code, language, out_path, mode_id, cfg_overrides) → str
  generate_from_files(files, language, out_path, mode_id, cfg_overrides) → str
  DEFAULT_CFG — словарь конфигурации по умолчанию
"""

import os
import drawpyo

from .config import DEFAULT_CFG
from .renderer import Renderer

__all__ = [
    "generate_from_code", "generate_from_files", "DEFAULT_CFG", "Renderer",
]


def _split_functions(nodes):
    """
    Разбивает список узлов на группы по границам START/STOP.
    Возвращает список (page_name, nodes).
    """
    result = []
    current = []
    current_name = "Схема"

    for node in nodes:
        if node['type'] == 'start':
            if current:
                result.append((current_name, current))
            current = [node]
            # `page_name` — отдельное от `value` поле, чтобы вкладка
            # страницы могла отличаться от подписи на блоке (например,
            # main-функция: подпись «Начало», вкладка «Main()»).
            current_name = node.get('page_name') or node['value']
        elif node['type'] == 'stop':
            current.append(node)
            result.append((current_name, current))
            current = []
            current_name = "Схема"
        else:
            current.append(node)

    if current:
        result.append((current_name, current))

    return result if result else [("Схема", nodes)]


def _write_pages(nodes, cfg, out_path):
    """Рендерит nodes в drawpyo-файл (одна страница на функцию) и сохраняет."""
    if os.path.exists(out_path):
        os.remove(out_path)

    f = drawpyo.File()
    f.file_name = os.path.basename(out_path)
    f.file_path = os.path.dirname(os.path.abspath(out_path))

    for page_name, func_nodes in _split_functions(nodes):
        # name= обязательно в конструкторе: drawpyo создаёт внутренний
        # Diagram(name=self.name) сразу в Page.__init__, и постфактум
        # `page.name = ...` уже не повлияет на XML вкладки. Без этого
        # все страницы выходят как "Page-1", "Page-2"…
        page = drawpyo.Page(file=f, name=page_name or "Схема")
        Renderer(page, cfg).render(func_nodes, cfg['page_center_x'], cfg['page_top_y'])

    f.write()
    return out_path


def _render_ast(ast_dict, mode_id, cfg_overrides, out_path):
    from ..parser import parse_ast_to_flowchart

    cfg, nodes = parse_ast_to_flowchart(ast_dict, mode_id=mode_id)
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return _write_pages(nodes, cfg, out_path)


def generate_from_code(code: str, language: str = 'python',
                       out_path: str = '/tmp/fragmos_out.xml',
                       mode_id: str = 'default',
                       cfg_overrides: dict = None) -> str:
    """
    Полный pipeline: исходный код → XML flowchart.

    Args:
        code:          исходный код
        language:      'python' | 'csharp' | 'cpp'
        out_path:      путь для сохранения XML
        mode_id:       режим из modes.yaml ('default' | 'loopLimit' | 'plain')
        cfg_overrides: перегрузки конфигурации (см. config.DEFAULT_CFG)

    Returns:
        Путь к созданному XML-файлу.
    """
    from ..ast_generators import get_ast_generator

    ast_dict = get_ast_generator(language).generate(code)
    return _render_ast(ast_dict, mode_id, cfg_overrides, out_path)


def generate_from_files(files, language: str = 'python',
                        out_path: str = '/tmp/fragmos_out.xml',
                        mode_id: str = 'default',
                        cfg_overrides: dict = None) -> str:
    """
    Multi-file pipeline: парсит каждый файл отдельно (чтобы tree-sitter
    не ругался на повторные #include / inline-определения через границы
    файлов) и склеивает AST в один program-узел.

    Используется для C++/Qt-проектов и C#-WinForms-проектов, где код
    разнесён по нескольким файлам, и `int main()` в main-файле сам по
    себе не содержит ничего, кроме точки входа.

    Args:
        files:         итерируемое из (filename, code) или dict с
                       полями {"filename","code"}.
        Остальные параметры — как у generate_from_code.

    Returns:
        Путь к созданному XML-файлу.
    """
    from ..ast_generators import get_ast_generator

    pairs = []
    for item in files:
        if isinstance(item, dict):
            name, code = item.get("filename") or "", item.get("code") or ""
        else:
            name, code = item
        if (code or "").strip():
            pairs.append((name, code))
    if not pairs:
        raise ValueError("generate_from_files: пустой список файлов")

    gen = get_ast_generator(language)
    merged_body: list = []
    for _name, code in pairs:
        try:
            ast_dict = gen.generate(code)
        except SyntaxError:
            # Файл с ошибками парсинга пропускаем — остальные диаграмма
            # всё равно получит. Иначе один бракованный файл утащил бы
            # за собой всю flowchart.
            continue
        merged_body.extend(ast_dict.get("body") or [])

    ast_dict = {
        "type": "program",
        "body": merged_body,
        "metadata": {"language": language},
    }
    return _render_ast(ast_dict, mode_id, cfg_overrides, out_path)
