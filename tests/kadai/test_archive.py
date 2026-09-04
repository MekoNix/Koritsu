"""
Опись архива: имена из данных, обязательный честный файл и ни одного пути.

Имена внутри ZIP приходят из данных — ключ тега сочинила модель, имя исходника
тоже. Поэтому `../`, абсолютный путь, `C:`, управляющий символ и пустое имя
обязаны быть невозможны, а не маловероятны: распаковщик у человека чужой.
Второе, что здесь стережётся, — строка про незапущенный код: без неё
компилируемый исходник читается как проверенный, и узнает правду студент на
защите, а не от нас.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import archive

from .conftest import FakeProject

ЗЛЫЕ = ["../../.bashrc", "/etc/passwd", "C:\\autoexec.bat", "..", ".", "",
        "схема\x00.drawio", "имя.", "имя ", "CON", "nul.txt", "a/b"]


@pytest.mark.parametrize("имя", ЗЛЫЕ)
def test_опасное_имя_не_проходит(имя):
    with pytest.raises(kadai.KadaiError):
        kadai.safe_leaf(имя)


def test_имя_проверяется_а_не_подчищается():
    """Подчистив `../` до `..`, мы получили бы другое имя, чем ждал человек, и
    не сказали бы ему об этом. Отказ виден, подмена — нет."""
    with pytest.raises(kadai.KadaiError):
        kadai.in_dir(kadai.DIR_SOURCES, "../sort.py")


def test_обычное_имя_с_кириллицей_проходит():
    assert kadai.in_dir(kadai.DIR_DIAGRAMS, "схема_алгоритма.drawio") == \
        "схемы/схема_алгоритма.drawio"


def test_столкновение_имён_без_учёта_регистра_ошибка():
    """Windows и macOS распакуют это в один файл, и раздел молча исчезнет."""
    entries = [kadai.Entry("схемы/Схема.drawio", {"artifact": "a"}),
               kadai.Entry("схемы/схема.drawio", {"artifact": "b"})]
    with pytest.raises(kadai.KadaiError, match="распаковщик"):
        kadai.check_names(entries)


def test_описи_без_честного_файла_не_бывает():
    with pytest.raises(kadai.KadaiError, match="не запускался"):
        kadai.plan_archive(notice="просто текст")


def test_строка_про_незапущенный_код_есть_всегда():
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    assert kadai.NOT_RUN in текст
    entries = kadai.plan_archive(notice=текст)
    записка = [e for e in entries if e.name == kadai.NOTICE][0]
    assert kadai.NOT_RUN in записка.source["text"]


def test_состав_архива_и_источники_без_путей():
    текст = kadai.notice_text(work_id="w-1", profile="курсовая", wishes="покороче",
                              requirement="отсортировать массив",
                              spent={"units": 100.0, "cap": None, "share": None,
                                     "estimated_share": 0.0},
                              versions={"введение": 3},
                              problems=[kadai.problem("unresolved_ref", "нет ссылки")])
    entries = kadai.plan_archive(notice=текст, report=archive.REPORT_DOCX,
                                 pdf=archive.REPORT_PDF,
                                 template_artifact="aa11",
                                 sources=[("sort.py", "b1")],
                                 diagrams=[("схема_алгоритма", "c1")],
                                 solution=kadai.solution_md([("Введение", "Текст.")]))
    names = [e.name for e in entries]
    assert names == ["отчёт.docx", "отчёт.pdf", "шаблон.docx", "исходники/sort.py",
                     "схемы/схема_алгоритма.drawio", "решение.md", "как-это-собрано.txt"]
    # Источник — только идентификатор, имя готового файла или наш текст.
    # Четвёртый вид источника был бы путём, а путь знает только Project.
    for e in entries:
        assert set(e.source) <= {"artifact", "output", "text"}


def test_схема_едет_в_архив_и_текстом_тоже():
    """Схема лежит в значении блока XML'ем, а не идентификатором — и это не наш выбор.

    Движок отчётов пишет обратно в запись блока `xml`, а не `artifact`
    (`hokoku.wire`: у `diagram` идентификатор наружу не эмитится). Знай опись
    один путь из двух — папка `схемы/` в архиве молча оставалась бы пустой, и
    узнавал бы об этом человек, распаковав его.
    """
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    entries = kadai.plan_archive(notice=текст, report_artifact="a1",
                                 diagrams=[("b-05", "c1")],
                                 diagram_texts=[("b-10", "<mxfile><diagram/></mxfile>")])
    по_имени = {e.name: e.source for e in entries}
    assert по_имени["схемы/b-05.drawio"] == {"artifact": "c1"}
    assert по_имени["схемы/b-10.drawio"] == {"text": "<mxfile><diagram/></mxfile>"}
    # Столкновение имён по-прежнему ошибка, а не «последний победил».
    with pytest.raises(kadai.KadaiError, match="два файла с именем"):
        kadai.plan_archive(notice=текст, report_artifact="a1",
                           diagrams=[("b-10", "c1")],
                           diagram_texts=[("b-10", "<mxfile/>")])


def test_записка_рассказывает_как_собрано():
    текст = kadai.notice_text(work_id="w-1", profile="курсовая", wishes="покороче",
                              stages=[{"name": "приём", "state": "сделано", "note": "18 файлов"}],
                              spent={"units": 41200.0, "cap": 200000.0, "share": 0.21,
                                     "estimated_share": 0.04},
                              versions={"введение": 3})
    assert "покороче" in текст and "введение: v3" in текст
    assert "оценено, а не измерено: 4%" in текст


def test_складывает_архив_проект_а_не_kadai():
    project = FakeProject()
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    имя = kadai.pack(project, kadai.plan_archive(notice=текст,
                                                 report=archive.REPORT_DOCX))
    assert имя == "работа.zip"
    assert project._packed[0]["name"] == "отчёт.docx"


def test_отчёт_живого_режима_едет_артефактом_а_не_файлом():
    """В живом режиме документ собран в памяти и положен `put_artifact`: файла в
    каталоге сборки нет вовсе, и опись обязана называть идентификатор. Назвать
    его именем файла значило бы попросить проект прочитать то, чего нет."""
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    entries = kadai.plan_archive(notice=текст, report_artifact="d0cx",
                                 pdf_artifact="pdf1",
                                 source_texts=[("sort.py", "def sort(a): ...")])
    по_имени = {e.name: e.source for e in entries}
    assert по_имени["отчёт.docx"] == {"artifact": "d0cx"}
    assert по_имени["отчёт.pdf"] == {"artifact": "pdf1"}
    # Код модели живёт блоком работы, а не материалом: в архив он едет текстом.
    assert по_имени["исходники/sort.py"] == {"text": "def sort(a): ..."}


def test_отчёт_нельзя_назвать_дважды():
    """Файл сборки и артефакт вместе — это два ответа на вопрос «откуда байты»,
    и молча выбрать один значило бы положить в архив неизвестно который."""
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    with pytest.raises(kadai.KadaiError, match="ровно один"):
        kadai.plan_archive(notice=текст, report=archive.REPORT_DOCX,
                           report_artifact="d0cx")


def test_имя_исходника_по_языку_а_незнакомый_язык_txt():
    """`.py` на чужом коде обманул бы и редактор, и человека."""
    assert kadai.archive.source_name("b-07", "python") == "b-07.py"
    assert kadai.archive.source_name("b-08", "brainfuck") == "b-08.txt"


def test_без_шва_архива_отказ_с_подписью():
    project = FakeProject(without=["pack"])
    текст = kadai.notice_text(work_id="w-1", profile="курсовая")
    with pytest.raises(kadai.NotReady, match="pack"):
        kadai.pack(project, kadai.plan_archive(notice=текст,
                                               report=archive.REPORT_DOCX))
