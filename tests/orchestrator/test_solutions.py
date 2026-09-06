"""
Решения одной работы: свой ход стадий, своё условие, своя папка контекста.

Стережётся то, ради чего решение вообще отделено от работы: две задачи в одной
работе не затирают друг друга, файлы одной не уезжают в промпт другой, материалы
и артефакты остаются общими, а работа, заведённая до появления второго решения,
своего хода стадий не теряет.
"""
from __future__ import annotations

import pytest

import orchestrator
from orchestrator.errors import OrchestratorError

from .conftest import markdown_value

ПЕРВОЕ = "11111111-1111-4111-8111-111111111111"
ВТОРОЕ = "22222222-2222-4222-8222-222222222222"


def test_у_решения_свой_ход_стадий(project):
    """Та самая беда: вторая задача в работе затирала первую."""
    первое = project.create_solution(ПЕРВОЕ)
    второе = project.create_solution(ВТОРОЕ)

    первое.put_state("kadai", {"work": "w-1", "state": "done"})
    второе.put_state("kadai", {"work": "w-2", "state": "running"})

    assert первое.state("kadai")["work"] == "w-1"
    assert второе.state("kadai")["work"] == "w-2"
    # У самой работы записи нет вовсе: она принадлежит решению, а не каталогу.
    assert project.state("kadai") == {}


def test_у_решения_свой_список_блоков(project):
    """Список блоков версионируется у каждого решения свой."""
    первое = project.create_solution(ПЕРВОЕ)
    второе = project.create_solution(ВТОРОЕ)

    первое.set_blocks([{"key": "b-01", "kind": "markdown", "label": "Введение",
                        "value": markdown_value("текст первой задачи")}],
                      source="agent")
    assert [b["key"] for b in первое.blocks()] == ["b-01"]
    assert второе.blocks() == []


def test_условие_решения_не_видно_соседнему(project):
    """Условие лежит записью состояния решения, а не в настройках работы.

    В настройках оно одно на каталог, и второе решение стёрло бы первое молча.
    """
    материал = project.store().add(b"Zadacha 1. Summa chisel.\n", name="z1.txt",
                                   do_ocr=False)
    первое = project.create_solution(ПЕРВОЕ)
    второе = project.create_solution(ВТОРОЕ)

    первое.set_condition(материал.id)
    assert первое.condition() == материал.id
    assert второе.condition() is None
    # Настройки работы условием не занялись: там его больше нет.
    assert project.settings().get("condition") in (None, "")


def test_папка_контекста_решения(project):
    """Файл одного решения во втором не виден, а модель видит только свои.

    `context_ids` — то, что уезжает в промпт: чужая методичка сбивает модель
    ровно так же, как чужое условие, и платит за это человек.
    """
    свой = project.store().add(b"metodichka odin\n", name="m1.txt", do_ocr=False)
    чужой = project.store().add(b"metodichka dva\n", name="m2.txt", do_ocr=False)
    первое = project.create_solution(ПЕРВОЕ)
    второе = project.create_solution(ВТОРОЕ)

    первое.bind_material(свой.id)
    второе.bind_material(чужой.id)

    assert первое.solution_materials() == [свой.id]
    assert второе.solution_materials() == [чужой.id]
    assert первое.context_ids() == {свой.id}
    # Работа целиком по-прежнему видит всё: отчёты и схемы читают опись, как
    # раньше, и `None` здесь означает «отбора нет».
    assert project.context_ids() is None


def test_условие_всегда_в_папке_контекста(project):
    """Без условия решать нечего, а приложено оно бывает и общим файлом работы."""
    условие = project.store().add(b"Zadacha.\n", name="z.txt", do_ocr=False)
    решение = project.create_solution(ПЕРВОЕ)
    решение.set_condition(условие.id)
    assert решение.context_ids() == {условие.id}


def test_общие_файлы_работы_не_приписаны_никому(project):
    """Файл без приписки — общий: его видят отчёты и схемы, как раньше."""
    общий = project.store().add(b"ustav\n", name="u.txt", do_ocr=False)
    решение = project.create_solution(ПЕРВОЕ)
    решение.bind_material(
        project.store().add(b"svoj\n", name="s.txt", do_ocr=False).id)
    assert общий.id in project.common_materials()


def test_снос_решения_не_трогает_материалы(project):
    """Материал принадлежит работе: на него ссылается и соседний документ."""
    файл = project.store().add(b"dannye\n", name="d.txt", do_ocr=False)
    решение = project.create_solution(ПЕРВОЕ)
    решение.bind_material(файл.id)
    решение.put_state("kadai", {"work": "w-1"})

    assert project.drop_solution(ПЕРВОЕ) is True
    assert project.solutions() == []
    assert файл.id in [m.id for m in project.store().list()]
    # Второй снос — то же состояние, а не отказ: просили состояние, в котором
    # решения нет, и оно уже наступило.
    assert project.drop_solution(ПЕРВОЕ) is False


def test_переезд_решения_из_корня_работы(project):
    """Работа, заведённая до появления второго решения, ничего не теряет.

    Ход стадий, задание и пожелания лежали в корне; второе решение читало бы их
    и затирало, поэтому первое переезжает в свой каталог целиком.
    """
    project.put_state("kadai", {"work": "w-старая", "state": "done"})
    project.put_state("kadai-пожелания", {"text": "покороче"})
    project.set_blocks([{"key": "b-01", "kind": "markdown", "label": "Введение",
                         "value": markdown_value("текст старой работы")}],
                       source="agent")

    assert project.adopt_root_kadai(ПЕРВОЕ) is True
    первое = project.for_solution(ПЕРВОЕ)
    assert первое.state("kadai")["work"] == "w-старая"
    assert первое.state("kadai-пожелания")["text"] == "покороче"
    assert [b["key"] for b in первое.blocks()] == ["b-01"]
    # В корне не осталось ничего: второе решение прочло бы это своим.
    assert project.state("kadai") == {}
    assert project.blocks() == []

    # Повторный вызов безобиден: он и есть обычный ход — метод зовётся на
    # каждом чтении списка решений.
    assert project.adopt_root_kadai(ПЕРВОЕ) is False
    assert первое.state("kadai")["work"] == "w-старая"


def test_имя_решения_проверяется_до_первого_join(project):
    """Имя становится звеном пути: подрезать его — значит писать не туда."""
    with pytest.raises(OrchestratorError):
        project.create_solution("../../etc")
    with pytest.raises(OrchestratorError):
        orchestrator.Project(project.path, solution="a/b")


def test_журнал_расхода_у_решения_общий(project):
    """`for_solution` передаёт журнал тем же объектом, а не заводит второй.

    `Limit.spent` считает по записям своего журнала, и второй экземпляр не
    увидел бы того, что записал первый, — потолок перестал бы работать ровно во
    время прогона.
    """
    журнал = project.journal()
    вид = project.for_solution(ПЕРВОЕ)
    assert вид.journal() is журнал
