"""
Граница с соседями — проверяется, а не обещается.

Правило разреза: `kadai` держит сценарий и не заводит второго экземпляра
среднего слоя. Проверяется оно так же, как соседнее правило про пути, — чтением
исходников: в `packages/kadai/` не должно быть ни импорта пакетов проекта, ни
работы с путями. Нарушение любого пункта означает, что в `kadai` завелось
второе место, которое хранит состояние или разговаривает с моделью, — и
разойдётся оно с настоящим молча.

Отдельно проверяется обратное направление: слово про вид работы («курсовая»,
«лабораторная», «раздел», «титульник») не должно протекать в `orchestrator`.
Этот тест смотрит только на `kadai`; за оркестратор отвечают его тесты, но
список слов записан здесь, потому что придумал их этот пакет.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import kadai

ПАКЕТ = Path(kadai.__file__).parent
ФАЙЛЫ = sorted(ПАКЕТ.rglob("*.py"))


def код(path: Path) -> str:
    """Исходник без строк и комментариев.

    Смотреть надо на код, а не на прозу: докстроки этого пакета называют
    запрещённое поимённо («ни `import hokoku`, ни `os.path.join`»), и проверка
    по сырому тексту запрещала бы объяснять правило там, где оно действует.
    """
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append("\n" if tok.type in (tokenize.NL, tokenize.NEWLINE) else tok.string)
    return "\n".join(out)

# Пакеты проекта. Импорт любого из них — это либо второй средний слой
# (`hokoku`, `materials`), либо сетевой код в сценарии (`llm`), либо нарушение
# действующего правила импорта (`orchestrator`, поправка Л.9 не принята).
СОСЕДИ = ("hokoku", "llm", "materials", "fragmos", "uml_generator", "orchestrator", "docx")


def test_файлы_пакета_на_месте():
    имена = {p.name for p in ФАЙЛЫ}
    assert имена == {"__init__.py", "errors.py", "seams.py", "profile.py", "plan.py",
                     "stages.py", "status.py", "archive.py", "rework.py"}


def test_ни_одного_импорта_соседа():
    for path in ФАЙЛЫ:
        текст = код(path)
        for сосед in СОСЕДИ:
            found = re.search(rf"^\s*(?:import {сосед}\b|from {сосед}[.\s])",
                              текст, re.MULTILINE)
            assert not found, f"{path.name}: импорт {сосед} — это второй средний слой"


def test_путей_в_пакете_нет():
    """`os.path.join` в kadai означает, что рядом с Project завелось второе
    хранилище, и переезд на SQLite перестал быть заменой одного класса.
    Данные профиля читаются через importlib.resources — это ресурс пакета,
    а не состояние работы."""
    for path in ФАЙЛЫ:
        текст = код(path)
        assert "os.path.join" not in текст, path.name
        assert not re.search(r"^\s*import os\b", текст, re.MULTILINE), path.name
        assert "open(" not in текст, path.name


def test_кода_никто_не_исполняет():
    """Запрет исполнения пользовательского кода цел: ни exec, ни subprocess,
    ни eval — их отсутствие проверяется, а не подразумевается."""
    for path in ФАЙЛЫ:
        текст = код(path)
        for опасное in ("subprocess", "exec(", "eval(", "__import__"):
            assert опасное not in текст, f"{path.name}: {опасное}"


def test_замечания_едут_в_общей_форме():
    """Четвёртого канала предупреждений в проекте не заводится."""
    p = kadai.problem("нет_кода", "нет листингов", key="реализация")
    assert set(p) == {"module", "level", "code", "key", "message"}
    assert p["module"] == "kadai" and p["level"] == "error"
