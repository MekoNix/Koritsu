"""
Сквозной сценарий: условие текстом → семь стадий → архив с кодом, схемой и отчётом.

Здесь всё настоящее, кроме провода к модели: настоящий `orchestrator.Project`
на диске, настоящий `kadai` со всеми семью стадиями, настоящий `hokoku`,
настоящий `fragmos`, настоящий drawio и настоящий LibreOffice. Подделан ровно
один слой — поток ответов модели (`conftest.FakeBackend`), и ответы заскриптованы
по шагам: разбор задания → строение → ходы петли → тексты.

Зачем это отдельно от тестов A, B и C. Каждый из них проверяет свою половину на
подделке соседа: `kadai` — на подделанных дверях, `orchestrator` — на своих
вызовах без сценария, `hokoku` — на списке блоков без проекта. Ни один из них не
может поймать расхождение **между** ними: имя поля значения, форма записи блока,
пометка `source`, порядок стадий, потолок ходов. Пойманное здесь и есть то, чего
поодиночке не видно.

Что стережётся, кроме «прогон дошёл до конца»:

* **код агент сочиняет сам и рисует по нему схему** — `put_source` кладёт
  исходник материалом, `make_flowchart` строит по этому же идентификатору;
* **код в архиве помечен незапускавшимся** — строка обязательна и проверяется
  описью, а не обещанием;
* **правка человека переживает прогон** — блок с пометкой `manual` не трогает
  ни проход текста, ни пересчёт по замечанию;
* **замечание к одному блоку пересчитывает один блок** — а не весь отчёт;
* **условие сканом останавливает работу** до решения, и распознанное лежит в
  снимке;
* **дверь, которой не дали, отказывает именем шва** — а не пустотой.

Схема рисуется по-настоящему (`drawio` в этой среде отвечает, проверено), PDF
собирается LibreOffice. Обе вещи по построению необязательны: без PDF архив
собирается, и в замечаниях работы написано, почему его нет.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from docx import Document

import fragmos
import kadai
import llm
import orchestrator
from orchestrator import kadai as обёртка

from .conftest import LOOSE, script
from .test_agent import done, turn
# Подставной tesseract и картинка — те же, что в тестах дверей: подделывается
# только распознавание, а путь материала от файла до снимка настоящий.
from .test_kadai_doors import fake_tesseract, png            # noqa: F401

УСЛОВИЕ = ("Курсовая работа. Написать на Python программу сортировки массива, "
           "снять замеры времени на разных размерах входа и оформить отчёт "
           "со схемой алгоритма.")

# Без завершающего перевода строки: `materials` хранит текст строками, и
# `store().read()` склеивает их через «\n» — значит вернётся ровно этот текст.
# Схема в тесте строится по нему же, иначе идентификатор артефакта разойдётся.
КОД = ("def сортировка(a):\n"
       "    for i in range(len(a)):\n"
       "        for j in range(len(a) - 1):\n"
       "            if a[j] > a[j + 1]:\n"
       "                a[j], a[j + 1] = a[j + 1], a[j]\n"
       "    return a")

ТРЕБОВАНИЕ = {
    "kind": "курсовая", "topic": "Сортировка массива пузырьком",
    "to_do": ["написать программу сортировки", "снять замеры", "нарисовать схему"],
    "given": ["язык Python"],
    "missing": ["размеры входа для замеров"],
}

СТРОЕНИЕ = {
    "work_kind": "курсовая",
    "expects": {"code": True, "tables": True, "diagrams": True},
    "required_kinds": ["введение", "постановка", "реализация", "заключение"],
    "sections": [
        {"key": "введение", "title": "Введение", "kind": "введение",
         "prompt": "зачем эта работа"},
        {"key": "постановка", "title": "Постановка задачи", "kind": "постановка",
         "prompt": "что дано и что требуется"},
        {"key": "реализация", "title": "Реализация", "kind": "реализация",
         "prompt": "как устроено решение"},
        {"key": "листинг", "title": "Листинг программы", "kind": "листинг",
         "prompt": "код сортировки"},
        {"key": "схема", "title": "Схема алгоритма", "kind": "схема",
         "prompt": "блок-схема сортировки"},
        {"key": "замеры", "title": "Замеры", "kind": "таблица",
         "prompt": "время на разных размерах"},
        {"key": "заключение", "title": "Заключение", "kind": "заключение",
         "prompt": "что вышло"},
    ],
}

# Ключи блоков, которые из этого строения соберёт `make_template`: по два на
# раздел, заголовок и место под содержимое. Выписаны здесь, потому что дальше
# ими адресуют и модель, и человек, и замечание.
ВВЕДЕНИЕ, ПОСТАНОВКА = "b-02", "b-04"
РЕАЛИЗАЦИЯ, ЛИСТИНГ, СХЕМА, ТАБЛИЦА, ЗАКЛЮЧЕНИЕ = "b-06", "b-08", "b-10", "b-12", "b-14"

ПОСТАНОВКА_ЧЕЛОВЕКА = "Постановку я написал сам: отсортировать массив по возрастанию."


def тексты(**блоки) -> str:
    return json.dumps(блоки, ensure_ascii=False)


@pytest.fixture
def сценарий(endpoint):
    """Endpoint с объявленными инструментами: без них петля отказывает до вызова."""
    def register(*scripts):
        return endpoint(*scripts, step=LOOSE,
                        declared=llm.Declared(structured_output=LOOSE, tools=True))
    return register


def архив(project) -> zipfile.ZipFile:
    путь = Path(project.outdir()) / "работа.zip"
    return zipfile.ZipFile(путь)


def абзацы(data: bytes) -> list[str]:
    """Текст абзацев включая поля SEQ/REF — python-docx их сам не отдаёт."""
    from docx.oxml.ns import qn
    return ["".join(t.text or "" for t in p._p.iter(qn("w:t")))
            for p in Document(io.BytesIO(data)).paragraphs]


# ── условие текстом: полный проход ───────────────────────────────────────────

def test_от_условия_текстом_до_архива(tmp_path, сценарий):
    """Семь стадий подряд на настоящем проекте. Длинно намеренно: короче не бывает.

    Разрезать это на семь тестов значило бы проверять каждую стадию на выходе
    подделанной предыдущей — то есть ровно то, что уже проверено порознь.
    """
    art = orchestrator.artifact_id(
        fragmos.generate_xml(КОД, "python").encode("utf-8"))
    mid = orchestrator.artifact_id(КОД.encode("utf-8"))
    ep, backend = сценарий(
        script(json.dumps(ТРЕБОВАНИЕ, ensure_ascii=False)),      # 1. разбор задания
        script(json.dumps(СТРОЕНИЕ, ensure_ascii=False)),        # 2. строение
        turn(("put_source", {"name": "сортировка.py", "lang": "python",
                             "text": КОД})),                     # 3. петля
        turn(("make_flowchart", {"id": mid, "language": "python"})),
        turn(("replace_block", {"key": ЛИСТИНГ, "label": "Листинг сортировки",
                                "value": {"type": "code", "text": КОД, "lang": "python",
                                          "caption": "Сортировка пузырьком"}})),
        turn(("replace_block", {"key": СХЕМА, "label": "Схема алгоритма",
                                "value": {"type": "diagram", "artifact": art,
                                          "caption": "Алгоритм сортировки"}})),
        turn(("replace_block", {"key": ТАБЛИЦА, "label": "Замеры",
                                "value": {"type": "table", "caption": "Замеры времени",
                                          "rows": [["n", "мс"], ["1000", "120"],
                                                   ["2000", "480"]]}})),
        done("код написан, схема построена, замеры сведены"),
        script(тексты(**{                                        # 4. тексты одним проходом
            ВВЕДЕНИЕ: "Работа посвящена сортировке массива.",
            РЕАЛИЗАЦИЯ: ("Решение приведено в листинге {ref:" + ЛИСТИНГ + "}, "
                         "его алгоритм — на рисунке {ref:" + СХЕМА + "}."),
            ЗАКЛЮЧЕНИЕ: "Сортировка работает за квадратичное время."})),
        script(тексты(**{ВВЕДЕНИЕ: "Введение переписано короче."})),   # 5. по замечанию
    )

    services = обёртка.services(str(tmp_path / "работа"), endpoint=ep, create=True)
    project = services.project
    project.add_material(УСЛОВИЕ.encode("utf-8"), "условие.txt", do_ocr=False,
                         condition=True)
    session = kadai.run.new(services, wishes=kadai.Wishes(text="покороче, без воды"))

    # ── стадии 1–3: приём, разбор задания, строение ─────────────────────────
    kadai.run.run(session, until="шаблон")
    снимок = kadai.run.snapshot(session)
    состояния = {s["name"]: s["state"] for s in снимок["stages"]}
    assert [состояния[n] for n in kadai.STAGE_NAMES[:3]] == ["сделано"] * 3
    assert [состояния[n] for n in kadai.STAGE_NAMES[3:]] == ["ждёт"] * 4
    assert снимок["condition_text"].startswith("Курсовая работа.")
    assert снимок["state"] == "running"          # условие текстом — показывать нечего
    # Вид работы сочинён по условию, а не взят из папки профилей.
    assert session.plan.profile.name == "курсовая"
    assert [b["key"] for b in project.blocks()] == [f"b-{n:02d}" for n in range(1, 15)]

    # ── человек правит один блок: дальше его не должен трогать никто ────────
    записи = [{**b, "source": "manual",
               "value": {"type": "markdown", "text": ПОСТАНОВКА_ЧЕЛОВЕКА}}
              if b["key"] == ПОСТАНОВКА else b for b in project.blocks()]
    project.set_blocks(записи, source="manual", note="правка человека")

    # ── стадии 4–7: решение, тексты, сборка, архив ──────────────────────────
    kadai.run.run(session)
    assert session.work.state == "done", session.work.problems
    блоки = {b["key"]: b for b in project.blocks()}
    assert блоки[ЛИСТИНГ]["kind"] == "code" and блоки[СХЕМА]["kind"] == "diagram"
    assert блоки[ТАБЛИЦА]["kind"] == "table"
    # Код агент сочинил сам и положил материалом — по нему же построена схема,
    # и журнал производных это помнит: без него замечание «схему переделай»
    # не знает, из какого исходника она вышла.
    assert project.store().read(mid).text == КОД
    производная = project.derived_of(art)
    assert производная["tool"] == "make_flowchart" and производная["inputs"] == [mid]
    # Правку человека не тронул ни проход текста, ни что-либо ещё.
    assert блоки[ПОСТАНОВКА]["value"]["text"] == ПОСТАНОВКА_ЧЕЛОВЕКА
    assert блоки[ПОСТАНОВКА]["source"] == "manual"

    # ── архив ───────────────────────────────────────────────────────────────
    with архив(project) as zf:
        имена = set(zf.namelist())
        assert {"отчёт.docx", "шаблон.docx", "решение.md",
                "исходники/b-08.py", "схемы/b-10.drawio",
                kadai.NOTICE} <= имена
        собрано = zf.read(kadai.NOTICE).decode("utf-8")
        assert kadai.NOT_RUN in собрано and "не запускался" in собрано
        assert "покороче, без воды" in собрано           # пожелания дословно
        assert "Сортировка массива пузырьком" in собрано  # как поняли задание
        assert zf.read("исходники/b-08.py").decode("utf-8") == КОД
        assert zf.read("схемы/b-10.drawio").startswith(b"<mxfile")
        # PDF по построению необязателен (LibreOffice может не отозваться), но
        # молчать о его отсутствии нельзя: тогда в замечаниях есть «без_pdf».
        коды = [p.get("code") for p in session.work.problems]
        assert ("отчёт.pdf" in имена) is ("без_pdf" not in коды)
        отчёт = zf.read("отчёт.docx")

    # Подписи и номера считает сборщик по списку блоков, а не мы.
    строки = абзацы(отчёт)
    assert "Листинг 1 — Сортировка пузырьком" in строки
    assert "Рисунок 1 — Алгоритм сортировки" in строки
    assert "Таблица 1 — Замеры времени" in строки
    assert "Решение приведено в листинге 1, его алгоритм — на рисунке 1." in строки
    assert ПОСТАНОВКА_ЧЕЛОВЕКА in строки

    # ── замечание к одному блоку: пересчитывается один блок ─────────────────
    было = len(project.block_versions())
    итог = kadai.rework.apply(session, note="введение слишком длинное",
                              block=ВВЕДЕНИЕ)
    assert итог["kind"] == "кусок" and итог["stages"] == kadai.REPLAY["кусок"]
    стало = {b["key"]: b["value"].get("text") for b in project.blocks()}
    assert стало[ВВЕДЕНИЕ] == "Введение переписано короче."
    assert стало[РЕАЛИЗАЦИЯ] == блоки[РЕАЛИЗАЦИЯ]["value"]["text"]   # соседей не трогали
    assert стало[ПОСТАНОВКА] == ПОСТАНОВКА_ЧЕЛОВЕКА                  # и своё тем более
    # Две версии на замечание: «блок вернули в черновик» и «текст написан».
    assert len(project.block_versions()) == было + 2
    assert backend.scripts == []                 # ни одного лишнего вызова модели


# ── условие сканом: работа встаёт и показывает распознанное ──────────────────

def test_условие_сканом_останавливает_работу_на_показ(tmp_path, сценарий,
                                                      fake_tesseract):
    """Решение владельца 2026-08-31: распознанное показывается ДО решения.

    Ошибка OCR в одной формуле даёт безупречно решённую **чужую** задачу, и
    заметить её может только человек. Поэтому работа встаёт сама — не по
    пожеланию, а по требованию стадии, — и текст лежит в снимке, а не «его можно
    запросить отдельно»: то, за чем надо идти вторым запросом, не показывают.
    """
    ep, backend = сценарий()
    services = обёртка.services(str(tmp_path / "работа"), endpoint=ep, create=True)
    services.project.add_material(png(), "условие.png", condition=True)
    session = kadai.run.new(services)

    kadai.run.run(session)
    снимок = kadai.run.snapshot(session)
    assert снимок["state"] == "waiting_user"
    assert снимок["hold"]["show"] == "распознанное условие"
    assert снимок["condition_text"].startswith(fake_tesseract.splitlines()[0])
    assert снимок["condition"]["ocr"] is True
    # Дальше стадии «приём» работа не ушла и денег не потратила.
    assert снимок["stages"][1]["state"] == "ждёт"
    assert backend.requests == []


# ── шов, которого не дали ────────────────────────────────────────────────────

def test_дверь_которой_не_дали_отказывает_именем_шва(tmp_path):
    """Правдоподобная пустота вместо отказа доехала бы до человека результатом.

    Проверяется на настоящем проекте: `Services` без единой двери — это то же
    самое состояние, что «сосед ещё не дописал», и отличаться оно должно
    адресом правки, а не `AttributeError`.
    """
    project = orchestrator.Project.create(str(tmp_path / "работа"),
                                          template=обёртка.blank_template())
    project.add_material(УСЛОВИЕ.encode("utf-8"), "условие.txt", do_ocr=False,
                         condition=True)
    session = kadai.run.new(kadai.Services(project=project))

    with pytest.raises(kadai.NotReady) as поймали:
        kadai.run.run(session)
    текст = str(поймали.value)
    assert "структура" in текст and "ask(" in текст
    # Стадия «приём» при этом прошла: отказ пришёл там, где дверь понадобилась.
    assert session.work.stage("приём").state == "сделано"
