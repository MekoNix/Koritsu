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


def test_ключ_раздела_это_имя_и_форма_его_не_отказ(doors):
    """Ключ раздела придумала модель, а адрес блоку выдаёт служба: ни пробел в
    ключе, ни второй ключ, схлопывающийся с первым после нормализации, стадию не
    роняют.

    Сказать о них надо — по ключу человек ищет раздел в замечаниях, и два ключа,
    различающиеся только нормализацией, он прочтёт как один раздел, — но
    выбросить оплаченное строение работы из-за названия раздела не за что.
    """
    строение = dict(doors.строение)
    строение["sections"] = строение["sections"] + [
        {"key": "введение", "title": "Введение ещё раз", "kind": "введение",
         "type": "markdown", "prompt": "ещё раз о том же"},
        {"key": "список литературы", "title": "Источники", "kind": "заключение",
         "type": "markdown", "prompt": "откуда взято"}]
    doors.строение = строение
    session = прогнать(doors)
    assert session.work.state == "done"
    беды = {p["code"]: p for p in session.work.problems}
    assert беды["ключ_повторён"]["level"] == "warning"
    assert беды["ключ_не_тег"]["level"] == "warning"


def test_ссылка_в_никуда_чинится_перезапуском_блока_а_сборка_идёт(doors):
    """Ссылка на несуществующий блок даёт «?» в готовом документе — но отказ
    собрать работу стоит человеку целого прогона, а беда чинится одним блоком.

    Поэтому блок с плохой ссылкой пишется заново (ровно один раз), работа
    собирается, а человеку остаётся строка о том, что произошло.
    """
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="тексты")
    записи = doors.project.blocks()
    ключ = записи[1]["key"]
    записи[1]["value"] = markdown("см. {ref:b-99}")
    doors.project.set_blocks(записи, source="agent")

    kadai.run.run(session)
    assert session.work.state == "done"
    assert session.work.stage("сборка").state == kadai.DONE
    assert doors.project._packed is not None                      # до архива дошло
    # Блок переписан проходом текста: ссылки в никуда в работе не осталось.
    новый = {b["key"]: b for b in doors.project.blocks()}[ключ]
    assert "{ref:b-99}" not in новый["value"]["text"]
    assert len(doors.texts) == 2                                  # починка — ровно одна
    беда = [p for p in session.work.problems if p["code"] == "unresolved_ref"][0]
    assert беда["level"] == "warning" and беда["key"] == ключ
    assert "b-99" in беда["message"] and "написан заново" in беда["message"]


def test_ссылку_в_никуда_из_подписи_снимают_и_работу_всё_равно_собирают(doors):
    """Подпись таблицы проход текста не пишет: переписывать там нечего.

    Значит остаётся второе — снять ссылку и собрать работу. Текст без номера
    рисунка человек поправит глазами; несобранную работу — нет.

    Что сборка прошла со снятой ссылкой, видно по тому, что она прошла вообще:
    ссылка в никуда — ошибка сита, и с ней стадия споткнулась бы до сборки.
    Запись же на диске остаётся прежней: значение таблицы и схемы возвращать в
    запись нельзя (схема живёт в ней идентификатором артефакта), и в замечании
    человеку про это сказано.
    """
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="тексты")
    записи = doors.project.blocks()
    таблица = [r for r in записи if r["kind"] == "table"][0]
    таблица["value"] = {**таблица["value"], "caption": "Замеры, см. {ref:b-99}"}
    doors.project.set_blocks(записи, source="agent")

    kadai.run.run(session)
    assert session.work.state == "done"
    assert doors.project._packed is not None                      # до архива дошло
    assert len(doors.texts) == 1                                  # прохода текста не было
    беда = [p for p in session.work.problems if p["code"] == "unresolved_ref"][0]
    assert беда["level"] == "warning" and "убрана" in беда["message"]


def test_ссылка_в_никуда_после_перезапуска_блока_снимается(doors):
    """Одна попытка, а не сколько получится: вторая стоит столько же и кончается
    тем же — модель уже видела список блоков, когда сослалась мимо.

    Не помогла первая — ссылка снимается, текст остаётся, работа собирается.
    """
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="тексты")
    записи = doors.project.blocks()
    ключ = записи[1]["key"]
    записи[1]["value"] = markdown("см. {ref:b-99}")
    doors.project.set_blocks(записи, source="agent")

    # Модель, которая на переписывании настаивает на своей же ссылке.
    def упрямый(*, overwrite=False, **kw):
        doors.texts.append({"overwrite": overwrite})
        свежие = doors.project.blocks()
        for record in свежие:
            if record["key"] == ключ:
                record["value"] = markdown("всё равно см. {ref:b-99}")
        doors.project.set_blocks(свежие, source="agent", note="упрямый проход")
        from .conftest import FakeResult
        return FakeResult(ok=True, filled=[ключ])

    kadai.run.run(session, until="тексты")
    doors.write_texts = упрямый
    session.services.extra["write_texts"] = упрямый
    kadai.run.run(session)

    assert session.work.state == "done"
    текст = {b["key"]: b for b in doors.project.blocks()}[ключ]["value"]["text"]
    assert "{ref:b-99}" not in текст and "всё равно см." in текст
    беда = [p for p in session.work.problems if p["code"] == "unresolved_ref"][0]
    assert беда["level"] == "warning" and "убрана" in беда["message"]


def test_остановка_человека_не_глотается_починкой_ссылки(doors):
    """Починка ссылки — попытка, а не обязанность стадии: отказ прохода текста её
    не роняет, иначе сборка потерялась бы ради одной ссылки.

    Остановка человека отказом двери не является. Проглоти её сценарий — стадия
    дошла бы до конца и заплатила за всё, а остановка сработала бы только
    следующей.
    """
    session = kadai.run.new(doors.services())
    kadai.run.run(session, until="тексты")
    записи = doors.project.blocks()
    записи[1]["value"] = markdown("см. {ref:b-99}")
    doors.project.set_blocks(записи, source="agent")

    class Остановлено(Exception):
        """То, чем дверь помечает остановку: класса сценарий не знает, признак — знает."""

        stopped = True

    def остановлен(**kw):
        raise Остановлено("человек остановил прогон")

    session.services.extra["write_texts"] = остановлен
    with pytest.raises(Остановлено):
        kadai.run.run(session)
    assert doors.project._packed is None          # до архива не дошло


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


def test_заготовка_под_инструмент_доделывается_добавочным_ходом_и_называется_вслух(doors):
    """Раздел, объявленный схемой, прозой не заполняется: проход текста такую
    заготовку не берёт вовсе, и она уехала бы в готовую работу заглушкой.

    Поэтому оставшиеся заготовки пересчитываются, и на них даётся **один**
    добавочный ход с точным заданием и своим потолком ходов. Один, а не «пока не
    выйдет»: второй стоил бы столько же и имел бы тот же шанс кончиться тем же.
    Что осталось — замечание с именем раздела: незакрытый раздел, о котором
    сказано, человек доделает сам, а необъявленный он найдёт на защите.
    """
    doors.строение = {
        **doors.строение,
        "expects": {"code": True, "tables": True, "diagrams": True},
        "sections": doors.строение["sections"] + [
            {"key": "схема", "title": "Схема алгоритма", "kind": "схема",
             "type": "diagram", "prompt": "как движутся данные"}]}
    session = прогнать(doors)
    assert len(doors.solved) == 2                 # петля и один добор, не больше
    добор = doors.solved[1]
    assert "Схема алгоритма" in добор["task"] and "replace_block" in добор["task"]
    assert добор["max_steps"] == 4                # потолок по числу незакрытых разделов
    беда = [p for p in session.work.problems if p["code"] == "заготовка_осталась"][0]
    assert беда["level"] == "warning" and "Схема алгоритма" in беда["message"]
    # Заглушка читалась бы как решение, поэтому в `решение.md` её нет.
    решение = {e["name"]: e for e in doors.project._packs["работа.zip"]}["решение.md"]
    assert "черновик" not in решение["text"]


def test_исходники_едут_из_папки_решения_а_общий_файл_работы_нет(doors):
    """Код, по которому строилась схема, живёт материалом, а не блоком работы:
    архив из одних блоков оставил бы человека без файла, который можно открыть и
    собрать. Файл, приложенный ко всей работе, исходником этого решения не
    становится — в `исходники/` он был бы неправдой.
    """
    doors.project.add_material("print('своё')\n".encode("utf-8"), "ввод.py")
    doors.project.add_common("print('чужое')\n".encode("utf-8"), "общий.py")
    прогнать(doors)
    имена = {e["name"] for e in doors.project._packs["работа.zip"]}
    assert "исходники/ввод.py" in имена and "исходники/общий.py" not in имена
    assert "исходники/b-08.py" in имена           # листинг работы едет рядом с файлом


def test_ход_стадии_уезжает_наружу_дверью(doors):
    """Стадия идёт минутами, и всё это время человек видит неподвижную полоску.

    Поэтому те же слова, что ложатся в работу, уезжают наружу в момент, когда они
    написаны. Дверь необязательна (командной строке докладывать некому), а
    счётчик ставится только со знаменателем: доля без числа — это враньё полоской.
    """
    ходы = []
    прогнать(doors, двери={"on_step": ходы.append})
    assert {x["stage"] for x in ходы} == set(kadai.STAGE_NAMES)
    assert all(x["tool"] == "" and x["ok"] is True for x in ходы)
    assert all(("n" in x) == ("total" in x) for x in ходы)
    assert any("сочиняю строение работы" in x["note"] for x in ходы)
    петля = [x for x in ходы if x["stage"] == "решение" and "total" in x]
    assert петля and петля[0]["total"] == run_mod.MAX_STEPS


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


def test_условие_словами_старше_файла_и_прогон_на_нём_не_встаёт():
    """Подтверждённый человеком текст и есть ответ на вопрос «верно ли распознано».

    Значит решают по нему, а не по тому, что вынулось из файла, и на проверке
    распознанного работа не стоит. Обратный порядок означал бы, что правка
    условия не действует, пока человек не приложит новый файл, — а правит он его
    словами.
    """
    project = FakeProject()
    project.add_material("Дано: масив из N чиcел.".encode("utf-8"), "условие.png",
                         condition=True)
    project.set_condition_text("Дано: массив из N чисел. Отсортировать.")
    doors = FakeDoors(project)
    session = kadai.run.new(doors.services())
    kadai.run.run(session)
    assert session.work.state == "done"
    assert session.work.condition_text == "Дано: массив из N чисел. Отсортировать."
    assert kadai.run.snapshot(session)["condition_text"].startswith("Дано: массив")


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
    опись = {e["name"]: e for e in doors.project._packs["работа.zip"]}
    assert set(опись) == {"отчёт.docx", "отчёт.pdf", "шаблон.docx",
                          "исходники/b-08.py", "решение.md", ".metadata"}
    # Отчёт и шаблон едут идентификаторами: файла в каталоге сборки нет вовсе.
    assert "artifact" in опись["отчёт.docx"] and "artifact" in опись["шаблон.docx"]
    записка = опись[".metadata"]["text"]
    assert kadai.NOT_RUN in записка
    assert "Вид работы: отчёт с программой" in записка and "Расход:" in записка
    # Условие в записи о сборке дословно: без него ответ не с чем сверить.
    assert "Написать программу сортировки и отчёт." in записка
    # `решение.md` — производная от блоков, а не второй источник правды.
    assert "## Введение" in опись["решение.md"]["text"]


def test_архивов_два_и_на_сдачу_едет_только_работа(doors):
    """Полный отвечает на вопрос «откуда это взялось», второй — то, что сдают.

    Собираются оба сразу: выбирает человек, когда скачивает, а спросить его до
    прогона значило бы гонять решение второй раз ради другого ZIP. Бланк,
    `решение.md` и запись о сборке из архива на сдачу убраны не ради объёма —
    их принимали за часть работы и несли вместе с ней.
    """
    session = прогнать(doors)
    assert set(doors.project._packs) == {"работа.zip", "отчёт-и-код.zip"}
    assert session.work.outputs["zip"] == "работа.zip"
    assert session.work.outputs["zip_light"] == "отчёт-и-код.zip"
    лёгкий = {e["name"] for e in doors.project._packs["отчёт-и-код.zip"]}
    assert лёгкий == {"отчёт.docx", "отчёт.pdf", "исходники/b-08.py"}


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
