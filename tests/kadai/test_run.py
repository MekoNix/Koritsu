"""
Семь стадий на подделанных дверях: от условия до архива.

Здесь стерегутся решения, каждое из которых иначе тихо
превращается в свою противоположность:

* **вид работы не фиксирован, и умолчания у него нет** — строение сочиняется по
  условию целиком, а работа без кода, таблиц и схем теряет стадию «решение», а
  не проходит её вхолостую;
* **текст одним проходом** — ровно один вызов двери на всю работу, и написанное
  человеком он не трогает;
* **код проверяется статически и помечен незапускавшимся** — без двери проверки
  стадия честно отказывает, а в архиве строка про это обязательна;
* **распознанное условие показывается человеку до решения** — текст лежит в
  снимке, а работа стоит и ждёт.

Двери подделаны целиком, сети нет и быть не может: ни одна функция пакета не
знает, как позвать модель.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import run as run_mod

from .conftest import FakeDoors, FakeProject, markdown


def прогнать(doors, **kw):
    """Завести работу и пройти её до конца. Возвращает сессию."""
    session = kadai.run.new(doors.services(**kw.pop("двери", {})), **kw)
    return kadai.run.run(session)


def открыть(doors):
    """Работа, открытая заново: состояние читается из проекта, а не из памяти."""
    return kadai.run.load(doors.services())


# ── профиль и строение ───────────────────────────────────────────────────────

def test_строение_сочиняется_из_условия_а_умолчания_нет(doors):
    """Заводится работа с пустым строением: имя вида работы, виды разделов и
    обязательность приходят из ответа модели, и больше им взяться неоткуда."""
    session = kadai.run.new(doors.services())
    assert session.plan.profile.name == "" and session.plan.profile.kinds == {}
    assert list(session.plan.stages) == list(kadai.STAGE_NAMES)   # все семь видны
    kadai.run.run(session)
    assert session.plan.profile.name == "отчёт с программой"
    обязательные = [name for name, k in session.plan.profile.kinds.items() if k.required]
    assert sorted(обязательные) == ["введение", "заключение", "реализация"]
    # Вид раздела — слово модели, тип — из перечня движка: пара, а не одно поле.
    assert session.plan.profile.kind("замеры").type == "table"


def test_работе_без_кода_и_схем_стадия_решения_не_нужна(doors):
    """Там, где производить нечего, петле работать не над чем, и показать стадию
    сделанной значило бы соврать полоской хода о работе, которой не было."""
    doors.строение = {**doors.строение,
                      "work_kind": "объяснительная записка",
                      "expects": {"code": False, "tables": False, "diagrams": False},
                      "required_kinds": ["введение", "заключение"],
                      "sections": [s for s in doors.строение["sections"]
                                   if s["kind"] in ("введение", "реализация", "заключение")]}
    session = прогнать(doors)
    assert session.work.stage("решение").state == kadai.SKIPPED
    assert not doors.solved                       # петлю не звали вовсе
    assert session.work.state == "done"


def test_строение_мимо_профиля_роняет_стадию_до_дорогих_вызовов(doors):
    """Первое сито и самое дешёвое: «Приложение А» и «Список литературы» модель
    предложит почти наверняка, а нумерации «А.1» и ссылок «[3]» в движке нет."""
    doors.строение = {**doors.строение,
                      "sections": [{"key": "прил", "title": "Приложение А",
                                    "kind": "приложение"}]}
    with pytest.raises(kadai.KadaiError, match="споткнулась"):
        прогнать(doors)


def test_ключи_разделов_схлопнувшиеся_после_нормализации_отвергаются(doors):
    """Два ключа, различающиеся только формой NFC, стали бы одним блоком, и
    второй раздел исчез бы молча."""
    строение = dict(doors.строение)
    строение["sections"] = строение["sections"] + [
        {"key": "введение", "title": "Введение ещё раз", "kind": "введение"}]
    doors.строение = строение
    with pytest.raises(kadai.KadaiError, match="споткнулась"):
        прогнать(doors)


def test_ссылка_в_никуда_останавливает_сборку_и_называет_блок(doors):
    """Ссылка на ненумерованный блок — ошибка, а не предупреждение, и потому
    прогон с ней до архива не доходит.

    «?» в готовом документе хуже отказа: увидит его человек, а не служба, и
    увидит уже после того, как за работу заплачено.
    """
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="тексты")
    записи = doors.project.blocks()
    записи[1]["value"] = markdown("см. {ref:b-99}")
    doors.project.set_blocks(записи, source="agent")

    with pytest.raises(kadai.KadaiError, match="b-99"):
        kadai.run.run(session)
    assert session.work.stage("сборка").state == kadai.STUMBLED
    assert session.work.stage("архив").state == kadai.WAITING     # до архива не дошло
    беда = [p for p in session.work.problems if p["code"] == "unresolved_ref"][0]
    assert беда["level"] == "error" and беда["key"] == записи[1]["key"]
    assert doors.project._packed is None                          # архива нет вовсе


def test_потолок_ходов_петли_сценарий_называет_свой(doors):
    """50 ходов — своё число, а не унаследованное.

    Умолчание слоя сменилось бы вместе со слоем и молча: сценарий платит за
    прогон, и знаменатель полоски хода на стадии «решение» берётся отсюда же.
    """
    прогнать(doors)
    assert run_mod.MAX_STEPS == 50
    assert doors.solved[0]["max_steps"] == 50
    решение = [s for s in kadai.run.snapshot(открыть(doors))["stages"]
               if s["name"] == "решение"][0]
    assert решение["progress"]["total"] == 50 and решение["progress"]["unit"] == "шаг"


def test_потолок_ходов_можно_назвать_свой(doors):
    прогнать(doors, limits={"max_steps": 7})
    assert doors.solved[0]["max_steps"] == 7


# ── условие ──────────────────────────────────────────────────────────────────

def test_условие_сканом_кладётся_в_снимок_и_останавливает_прогон():
    """Ошибка распознавания в формуле даёт безупречно решённую **чужую** задачу,
    и заметить её может только человек — значит текст обязан быть в снимке, а
    работа обязана стоять и ждать."""
    project = FakeProject()
    project.add_material("Дано: массив из N чисел.".encode("utf-8"), "условие.png",
                         condition=True)
    doors = FakeDoors(project)
    session = kadai.run.new(doors.services())
    kadai.run.run(session)
    снимок = kadai.run.snapshot(session)
    assert снимок["state"] == "waiting_user"
    assert снимок["hold"]["show"] == "распознанное условие"
    assert снимок["condition_text"] == "Дано: массив из N чисел."
    assert снимок["condition"]["ocr"] is True
    # Тот же текст лежит в проекте, а не только в памяти процесса: считает
    # работу один процесс, показывает другой.
    assert project.state("kadai")["condition"]["text"] == "Дано: массив из N чисел."


def test_прогон_продолжается_после_подтверждения_условия():
    project = FakeProject()
    project.add_material(b"skan", "skan.png", condition=True)
    doors = FakeDoors(project)
    session = kadai.run.new(doors.services())
    kadai.run.run(session)
    assert session.work.state == "waiting_user"
    kadai.run.run(session)                        # человек подтвердил и запустил снова
    assert session.work.state == "done"


def test_без_условия_работа_спотыкается_а_не_решает_пустоту():
    doors = FakeDoors(FakeProject())
    with pytest.raises(kadai.KadaiError, match="условие"):
        прогнать(doors)


# ── текст одним проходом ─────────────────────────────────────────────────────

def test_текст_пишется_одним_проходом(doors):
    """Абзацы, написанные по одному, связны поодиночке и рассогласованы вместе;
    здесь это проверяется счётом вызовов."""
    прогнать(doors)
    assert doors.texts == [{"overwrite": False}]
    # Петля текста не писала: её дело — код, таблицы и схемы.
    assert all("Связный текст сейчас НЕ пиши" in s["task"] for s in doors.solved)


def test_проход_текста_не_трогает_написанное_человеком(doors):
    """Пропажу своего абзаца человек обнаружит в готовом отчёте, и правило
    «written by human — не переписывать» держит дверь. Сценарий обязан просить
    её об этом (`overwrite=False`), а не наоборот."""
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="шаблон")
    записи = doors.project.blocks()
    записи[1] = {**записи[1], "value": markdown("Это я написал сам."),
                 "source": "manual"}
    doors.project.set_blocks(записи, source="manual", note="правка человека")
    kadai.run.run(session)
    свой = [b for b in doors.project.blocks() if b["source"] == "manual"][0]
    assert свой["value"]["text"] == "Это я написал сам."
    assert doors.texts == [{"overwrite": False}]


# ── проверка кода ────────────────────────────────────────────────────────────

def test_без_двери_проверки_кода_стадия_отказывает_с_именем_шва(doors):
    """Код без проверки, объявленный проверенным, — то самое молчание, которое
    человек прочтёт как обещание."""
    with pytest.raises(kadai.NotReady, match="check_code"):
        прогнать(doors, двери={"check_code": None})


def test_беда_статической_проверки_роняет_сборку(doors):
    doors.code_problems = [kadai.problem("синтаксис", "не закрыта скобка")]
    with pytest.raises(kadai.KadaiError, match="споткнулась"):
        прогнать(doors)


def test_код_проверяется_целиком_и_с_языком(doors):
    прогнать(doors)
    assert doors.checked and doors.checked[0]["language"] == "python"
    assert "def sort" in doors.checked[0]["text"]


# ── сборка и архив ───────────────────────────────────────────────────────────

def test_полный_прогон_доходит_до_архива(doors):
    session = прогнать(doors)
    assert session.work.state == "done"
    assert [s.state for s in session.work.stages] == [kadai.DONE] * 7
    assert session.work.outputs["zip"] == "работа.zip"


def test_в_архиве_всё_по_описи_и_пометка_про_незапущенный_код(doors):
    прогнать(doors)
    опись = {e["name"]: e for e in doors.project._packed}
    assert set(опись) == {"отчёт.docx", "отчёт.pdf", "шаблон.docx",
                          "исходники/b-08.py", "решение.md", "как-это-собрано.txt"}
    # Отчёт и шаблон едут идентификаторами: файла в каталоге сборки нет вовсе.
    assert "artifact" in опись["отчёт.docx"] and "artifact" in опись["шаблон.docx"]
    записка = опись["как-это-собрано.txt"]["text"]
    assert kadai.NOT_RUN in записка
    assert "Вид работы: отчёт с программой" in записка and "Расход:" in записка
    # `решение.md` — производная от блоков, а не второй источник правды.
    assert "## Введение" in опись["решение.md"]["text"]


def test_pdf_не_собрался_архив_всё_равно_собран(doors):
    doors.pdf = None
    session = прогнать(doors)
    имена = {e["name"] for e in doors.project._packed}
    assert "отчёт.pdf" not in имена and "отчёт.docx" in имена
    коды = [p["code"] for p in session.work.problems]
    assert "без_pdf" in коды                      # промолчать про это нельзя


def test_собранный_отчёт_записан_в_журнал_производных(doors):
    """Без записи «чем и из чего построено» замечание «переделай» — правка вслепую."""
    прогнать(doors)
    docx = kadai.task(doors.project)["made"]["docx"]
    assert doors.project.derived_of(docx)["tool"] == "hokoku.live.assemble"


# ── остановки и отказы ───────────────────────────────────────────────────────

def test_просьба_показать_строение_останавливает_прогон(doors):
    session = kadai.run.new(doors.services(),
                            wishes=kadai.Wishes(show_structure=True))
    kadai.run.run(session)
    assert session.work.state == "waiting_user"
    assert session.work.hold.show == "структуру отчёта"
    assert not doors.solved                       # дорогая стадия не началась
    kadai.run.run(session)
    assert session.work.state == "done"


def test_отказ_двери_называет_шов_а_не_возвращает_пустоту(doors):
    """Пустой результат доехал бы до человека под видом работы."""
    services = doors.services()
    голые = kadai.Services(project=doors.project, extra=dict(services.extra))
    session = kadai.run.new(голые)
    with pytest.raises(kadai.NotReady) as поймали:
        kadai.run.run(session)
    assert "ask(" in str(поймали.value)


def test_молчание_модели_роняет_стадию_и_остаётся_в_проекте(doors):
    doors.требование = None                       # ответа не будет
    doors.ask = lambda *a, **k: type("Нет", (), {"ok": False, "value": None,
                                                 "problems": []})()
    session = kadai.run.new(doors.services(ask=doors.ask))
    with pytest.raises(kadai.KadaiError, match="споткнулась"):
        kadai.run.run(session)
    снимок = doors.project.state("kadai")
    assert снимок["state"] == "failed"
    assert снимок["problems"][0]["code"] == "модель_не_ответила"


def test_работа_переживает_перезагрузку_процесса(doors):
    """Считает работу один процесс, показывает другой: всё, что переживает
    вызов, обязано лежать в проекте, а не в памяти."""
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="шаблон")
    заново = kadai.run.load(doors.services())
    assert заново.work.id == session.work.id
    assert заново.plan.profile.name == "отчёт с программой"
    assert заново.work.stage("шаблон").state == kadai.DONE
    kadai.run.run(заново)
    assert заново.work.state == "done"


def test_условие_и_пожелания_едут_данными_а_не_вопросом(doors):
    """Текст, приехавший вопросом, для модели указание, а текст в рамке —
    данные. В чужом файле бывает написано «забудь предыдущие указания»."""
    session = kadai.run.new(doors.services(),
                            wishes=kadai.Wishes(text="покороче, пожалуйста"))
    kadai.run.run(session, until="разбор задания")
    вопрос = doors.asked[0]
    имена = [имя for имя, _ in вопрос["data"]]
    assert имена == ["условие задачи", "пожелания человека"]
    assert "покороче" not in вопрос["question"]


def test_расход_едет_в_снимок_из_проекта(doors):
    session = прогнать(doors)
    assert kadai.run.snapshot(session)["spent"]["units"] == 41200.0


def test_стадии_знают_свой_знаменатель_или_не_рисуют_полоску(doors):
    session = прогнать(doors)
    по_имени = {s["name"]: s for s in kadai.run.snapshot(session)["stages"]}
    assert по_имени["тексты"]["progress"]["unit"] == "блок"
    assert "progress" not in по_имени["разбор задания"]


def test_граница_until_держится_даже_если_стадия_пропущена(doors):
    """«Дойди до решения» у работы, которой решение не нужно, не должно оплатить
    всё остальное: граница считается по имени стадии, а не по тому, делали её
    или пропустили."""
    doors.строение = {**doors.строение, "work_kind": "объяснительная записка",
                      "expects": {"code": False, "tables": False, "diagrams": False}}
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="решение")
    assert session.work.stage("решение").state == kadai.SKIPPED
    assert session.work.stage("тексты").state == kadai.WAITING
    assert not doors.texts


def test_писать_нечего_это_не_беда_а_состояние(doors):
    """Человек мог написать всё сам: звать дверь ради отказа «писать нечего»
    значило бы уронить работу на том, что она уже готова."""
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="решение")
    записи = [{**b, "source": "manual"} for b in doors.project.blocks()]
    doors.project.set_blocks(записи, source="manual", note="всё написал человек")
    kadai.run.run(session)
    assert session.work.state == "done" and not doors.texts
    assert "писать нечего" in session.work.stage("тексты").note


def test_модуль_знает_исполнение_каждой_стадии():
    """Стадия без исполнения молча не пошла бы, а работа встала бы навсегда."""
    assert set(run_mod.STAGE_FUNS) == set(kadai.STAGE_NAMES)
