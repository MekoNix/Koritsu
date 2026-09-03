"""
builder — sub-package для генерации draw.io flowchart XML.

Публичный API:
  generate_xml(code, language, *, files, mode_id, cfg_overrides, warnings) → str  — XML строкой
  generate_from_code(code, language, out_path, mode_id, cfg_overrides, warnings) → str  — путь
  generate_from_files(files, language, out_path, mode_id, cfg_overrides, warnings) → str  — путь
  DEFAULT_CFG — словарь конфигурации по умолчанию

Схема наружу отдаётся строкой: `uml_generator.build_xml` делает так же, а вызывающему
(службе, прогону отчёта) файл на диске не нужен — ему нужен XML. Путевые обёртки
остаются, но общего `/tmp` в умолчании больше нет: два одновременных вызова писали
в один и тот же `/tmp/fragmos_out.xml` и затирали друг друга без единой ошибки.
"""

import os
from ._drawpyo import drawpyo

from .config import DEFAULT_CFG
from .renderer import Renderer

__all__ = [
    "generate_xml", "generate_from_code", "generate_from_files", "DEFAULT_CFG", "Renderer",
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


class _File(drawpyo.File):
    """drawpyo.File с воспроизводимым заголовком.

    Штатный `modified` — время записи, из-за него одинаковый вход давал
    разные файлы (ни кэшировать, ни сравнить в тесте). Дата фиксированная:
    draw.io атрибут не использует, а вывод становится побайтно стабильным.
    """

    @property
    def modified(self) -> str:
        return "1970-01-01T00:00:00"


def _stable_ids(f):
    """Сквозная нумерация id вместо адресов в памяти (`id(obj)` у drawpyo).

    Служебные mxCell 0 и 1, создаваемые Page.__init__, не трогаем. Рёбра
    ссылаются на объекты, а не на id, поэтому перенумеровать можно перед
    самой записью."""
    n = 0
    for page_num, page in enumerate(f.pages, start=1):
        page.id = page_num
        page.diagram._id = f'page{page_num}'     # id вкладки <diagram …>
        for obj in page.objects:
            if getattr(obj, '_id', None) in (0, 1):
                continue
            n += 1
            obj._id = f'n{n}'


def _pages_xml(nodes, cfg) -> str:
    """Рендерит nodes в drawpyo-файл (одна страница на функцию) → XML строкой."""
    f = _File()

    for page_name, func_nodes in _split_functions(nodes):
        # name= обязательно в конструкторе: drawpyo создаёт внутренний
        # Diagram(name=self.name) сразу в Page.__init__, и постфактум
        # `page.name = ...` уже не повлияет на XML вкладки. Без этого
        # все страницы выходят как "Page-1", "Page-2"…
        page = drawpyo.Page(file=f, name=page_name or "Схема")
        Renderer(page, cfg).render(func_nodes, cfg['page_center_x'], cfg['page_top_y'])

    _stable_ids(f)
    return f.xml


def _save(xml: str, out_path: str) -> str:
    """XML в файл — ровно то же, что писал drawpyo, включая кодировку."""
    directory = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(directory, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(xml)
    return out_path


def _render_ast(ast_dict, mode_id, cfg_overrides) -> str:
    from ..parser import parse_ast_to_flowchart

    cfg, nodes = parse_ast_to_flowchart(ast_dict, mode_id=mode_id)
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return _pages_xml(nodes, cfg)


def _merge_files(files, language: str, gen) -> dict:
    """AST нескольких файлов в один program-узел.

    Каждый файл парсится отдельно — иначе tree-sitter ругается на повторные
    #include и inline-определения через границы файлов.

    Генератор передаётся снаружи один на все файлы: в нём копятся замечания о
    том, что в схему не вошло, и заводить по генератору на файл значило бы
    растерять их по дороге.
    """
    pairs = []
    for item in files:
        if isinstance(item, dict):
            name, code = item.get("filename") or "", item.get("code") or ""
        else:
            name, code = item
        if (code or "").strip():
            pairs.append((name, code))
    if not pairs:
        raise ValueError("generate_xml: пустой список файлов")

    merged_body: list = []
    for name, code in pairs:
        gen.filename = name
        try:
            ast_dict = gen.generate(code)
        except SyntaxError as exc:
            # Файл с ошибками парсинга пропускаем — остальные диаграмма
            # всё равно получит. Иначе один бракованный файл утащил бы
            # за собой всю flowchart. Молча пропускать нельзя: пропавшую
            # функцию на схеме из десяти страниц не замечает никто, и
            # «схема неполна» выясняется на защите.
            gen._warn("file_not_parsed",
                      f"в схему не вошло: файл {name or '<без имени>'} не "
                      f"разобрался как {language} ({exc})")
            continue
        merged_body.extend(ast_dict.get("body") or [])
    gen.filename = ''

    return {"type": "program", "body": merged_body, "metadata": {"language": language}}


def generate_xml(code: str = None, language: str = 'python', *,
                 files=None,
                 mode_id: str = 'default',
                 cfg_overrides: dict = None,
                 warnings: list = None) -> str:
    """
    Исходный код → draw.io XML строкой. На диск ничего не пишется.

    Args:
        code:          исходный код (ровно одно из code и files)
        language:      'python' | 'csharp' | 'cpp'
        files:         многофайловый вход: итерируемое из (filename, code) или
                       dict с полями {"filename", "code"}. Нужен C++/Qt- и
                       C#-WinForms-проектам, где `main()` сам по себе пуст.
        mode_id:       режим из modes.yaml ('default' | 'loopLimit' | 'plain')
        cfg_overrides: перегрузки конфигурации (см. config.DEFAULT_CFG)
        warnings:      список, куда дописать `kyotsu.Notice` о том, что в схему
                       не вошло (файл не разобрался, `goto case` без цели).
                       None — не собирать.

    Returns:
        XML многостраничного mxfile (одна страница на функцию).

    Почему замечания списком-приёмником, а не вторым значением: схема наружу
    отдаётся **строкой**, и вызывающему (службе, прогону отчёта) нужен XML, а не
    пара. Сменить возврат на кортеж значило бы сломать всех сегодняшних
    вызывающих ради тех, кому замечания не нужны; так их спрашивает тот, кому
    есть где показать, и не спрашивает остальные.
    """
    from ..ast_generators import get_ast_generator

    if (code is None) == (files is None):
        raise ValueError("generate_xml: нужно ровно одно из code и files")
    gen = get_ast_generator(language)
    if files is not None:
        ast_dict = _merge_files(files, language, gen)
    else:
        ast_dict = gen.generate(code)
    if warnings is not None:
        warnings.extend(gen.warnings)
    return _render_ast(ast_dict, mode_id, cfg_overrides)


def generate_from_code(code: str, language: str, out_path: str,
                       mode_id: str = 'default',
                       cfg_overrides: dict = None,
                       warnings: list = None) -> str:
    """
    То же, что generate_xml(code, language, …), но с сохранением в файл.

    `out_path` обязателен: умолчание `/tmp/fragmos_out.xml` было общим на машину —
    два вызова затирали друг друга, а убирать файл за собой никто не убирал.

    Returns:
        Путь к созданному XML-файлу.
    """
    return _save(generate_xml(code, language, mode_id=mode_id,
                             cfg_overrides=cfg_overrides, warnings=warnings),
                 out_path)


def generate_from_files(files, language: str, out_path: str,
                        mode_id: str = 'default',
                        cfg_overrides: dict = None,
                        warnings: list = None) -> str:
    """
    То же, что generate_xml(files=…), но с сохранением в файл.

    Returns:
        Путь к созданному XML-файлу.
    """
    return _save(generate_xml(None, language, files=files, mode_id=mode_id,
                              cfg_overrides=cfg_overrides, warnings=warnings),
                 out_path)
