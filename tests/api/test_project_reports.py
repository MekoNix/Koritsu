"""
Отчёты работы: `/api/projects/{id}/reports` и `?report=` у значений и тегов.

Стережётся здесь главное обещание: в работе несколько отчётов, у каждого свой
бланк и свои значения, и ни один из них не затирает соседа. Плюс то, что при
этом обязано остаться общим (материалы, артефакты) и то, что обязано уйти вместе
с отчётом (значения, история).
"""
from __future__ import annotations

import pytest

from .c_fixtures import (  # noqa: F401
    docx_байты, клиент, личное_id, позвать, создать_проект, войти, сосед,
    хозяин,
)


def приложить(клиент, project_id: str, данные: bytes, имя: str) -> str:
    """Приложить бланк к работе и вернуть его идентификатор."""
    ответ = клиент.post(
        f"/api/projects/{project_id}/templates",
        data={"name": имя},
        files={"file": (f"{имя}.docx", данные,
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document")})
    assert ответ.status_code in (200, 201), ответ.text
    return ответ.json()["id"]


def завести_отчёт(клиент, project_id: str, *, template_id=None, name="") -> dict:
    тело = {"name": name}
    if template_id:
        тело["template_id"] = template_id
    ответ = клиент.post(f"/api/projects/{project_id}/reports", json=тело)
    assert ответ.status_code == 201, ответ.text
    return ответ.json()


@pytest.fixture
def работа(клиент, хозяин):
    """Работа с бланком — то, из чего заводят отчёты."""
    return создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())


def test_пустой_список_у_новой_работы(клиент, работа):
    ответ = клиент.get(f"/api/projects/{работа['id']}/reports")
    assert ответ.status_code == 200, ответ.text
    assert ответ.json() == []


def test_два_отчёта_с_разными_бланками_и_значениями(клиент, работа):
    """Главное обещание: значения одного отчёта не видны в другом."""
    pid = работа["id"]
    первый_бланк = приложить(клиент, pid, docx_байты(("цель", "выводы")), "ГОСТ")
    второй_бланк = приложить(клиент, pid, docx_байты(("аннотация",)), "Приложение")

    первый = завести_отчёт(клиент, pid, template_id=первый_бланк, name="Глава 1")
    второй = завести_отчёт(клиент, pid, template_id=второй_бланк)

    # Теги у каждого свои — из своего бланка.
    теги_1 = клиент.get(f"/api/projects/{pid}/tags?report={первый['id']}").json()
    теги_2 = клиент.get(f"/api/projects/{pid}/tags?report={второй['id']}").json()
    assert [т["key"] for т in теги_1["tags"]] == ["цель", "выводы"]
    assert [т["key"] for т in теги_2["tags"]] == ["аннотация"]

    # Значения — тоже свои.
    assert клиент.put(f"/api/projects/{pid}/values/цель?report={первый['id']}",
                      json={"type": "markdown", "text": "первая"}).status_code == 200
    assert клиент.put(f"/api/projects/{pid}/values/аннотация?report={второй['id']}",
                      json={"type": "markdown", "text": "вторая"}).status_code == 200

    было_1 = клиент.get(f"/api/projects/{pid}/values?report={первый['id']}").json()
    было_2 = клиент.get(f"/api/projects/{pid}/values?report={второй['id']}").json()
    assert было_1["values"]["цель"]["text"] == "первая"
    assert "аннотация" not in было_1["values"]
    assert было_2["values"]["аннотация"]["text"] == "вторая"
    assert "цель" not in было_2["values"]

    # Номер считает служба, имя оставляем клиенту.
    список = клиент.get(f"/api/projects/{pid}/reports").json()
    assert [(о["n"], о["name"], о["template_name"]) for о in список] == [
        (1, "Глава 1", "ГОСТ"), (2, "", "Приложение")]


def test_история_версий_принадлежит_отчёту(клиент, работа):
    pid = работа["id"]
    бланк = приложить(клиент, pid, docx_байты(("цель",)), "ГОСТ")
    первый = завести_отчёт(клиент, pid, template_id=бланк)
    второй = завести_отчёт(клиент, pid, template_id=бланк)

    for текст in ("раз", "два"):
        клиент.put(f"/api/projects/{pid}/values/цель?report={первый['id']}",
                   json={"type": "markdown", "text": текст})

    свои = клиент.get(
        f"/api/projects/{pid}/values/цель/versions?report={первый['id']}")
    assert свои.status_code == 200
    assert [в["n"] for в in свои.json()["versions"]] == [1, 2]
    # У соседа истории нет вовсе: «у тега нет версий» — это 404, не пустой список.
    чужие = клиент.get(
        f"/api/projects/{pid}/values/цель/versions?report={второй['id']}")
    assert чужие.status_code == 404


def test_удаление_отчёта_не_трогает_соседа(клиент, работа):
    pid = работа["id"]
    бланк = приложить(клиент, pid, docx_байты(("цель",)), "ГОСТ")
    первый = завести_отчёт(клиент, pid, template_id=бланк)
    второй = завести_отчёт(клиент, pid, template_id=бланк)
    клиент.put(f"/api/projects/{pid}/values/цель?report={первый['id']}",
               json={"type": "markdown", "text": "остаётся"})

    удалено = клиент.delete(f"/api/projects/{pid}/reports/{второй['id']}")
    assert удалено.status_code == 204, удалено.text

    список = клиент.get(f"/api/projects/{pid}/reports").json()
    assert [о["id"] for о in список] == [первый["id"]]
    значения = клиент.get(f"/api/projects/{pid}/values?report={первый['id']}").json()
    assert значения["values"]["цель"]["text"] == "остаётся"
    # Бланк с полки работы удаление отчёта не трогает.
    бланки = клиент.get(f"/api/projects/{pid}/templates").json()
    assert [б["id"] for б in бланки] == [бланк]


def test_удаление_уносит_значения_отчёта(клиент, работа):
    """Заведённый заново отчёт не наследует значений удалённого."""
    pid = работа["id"]
    бланк = приложить(клиент, pid, docx_байты(("цель",)), "ГОСТ")
    # Первый отчёт работы живёт в корневом документе, поэтому проверяем на
    # втором: у него свой каталог, который и должен уйти.
    завести_отчёт(клиент, pid, template_id=бланк)
    отчёт = завести_отчёт(клиент, pid, template_id=бланк)
    клиент.put(f"/api/projects/{pid}/values/цель?report={отчёт['id']}",
               json={"type": "markdown", "text": "пропадёт"})
    assert клиент.delete(
        f"/api/projects/{pid}/reports/{отчёт['id']}").status_code == 204

    новый = завести_отчёт(клиент, pid, template_id=бланк)
    значения = клиент.get(f"/api/projects/{pid}/values?report={новый['id']}").json()
    assert значения["values"] == {}


def test_старый_отчёт_читает_значения_работы(клиент, работа):
    """Запись журнала, заведённая до каталогов документов, ничего не теряет."""
    pid = работа["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "написано раньше"})
    старый = клиент.post(f"/api/projects/{pid}/runs",
                         json={"module": "reports", "name": ""})
    assert старый.status_code == 201, старый.text

    список = клиент.get(f"/api/projects/{pid}/reports").json()
    assert [о["id"] for о in список] == [старый.json()["id"]]
    значения = клиент.get(
        f"/api/projects/{pid}/values?report={старый.json()['id']}").json()
    assert значения["values"]["цель"]["text"] == "написано раньше"


def test_вторая_запись_журнала_получает_свой_документ(клиент, работа):
    """Две записи «отчёт» из карточки работы не делят один набор значений."""
    pid = работа["id"]
    первый = клиент.post(f"/api/projects/{pid}/runs",
                         json={"module": "reports", "name": ""}).json()
    второй = клиент.post(f"/api/projects/{pid}/runs",
                         json={"module": "reports", "name": ""}).json()
    # Список разводит их по документам — до этого оба смотрели бы в корень.
    assert len(клиент.get(f"/api/projects/{pid}/reports").json()) == 2

    клиент.put(f"/api/projects/{pid}/values/цель?report={первый['id']}",
               json={"type": "markdown", "text": "первая"})
    чужие = клиент.get(f"/api/projects/{pid}/values?report={второй['id']}").json()
    assert чужие["values"] == {}


def test_бланк_отчёта_меняется_отдельно(клиент, работа):
    """«Собирать по нему» действует на названный отчёт, а не на всю работу."""
    pid = работа["id"]
    первый_бланк = приложить(клиент, pid, docx_байты(("цель",)), "ГОСТ")
    второй_бланк = приложить(клиент, pid, docx_байты(("аннотация",)), "Другой")
    первый = завести_отчёт(клиент, pid, template_id=первый_бланк)
    второй = завести_отчёт(клиент, pid, template_id=первый_бланк)

    ответ = клиент.post(
        f"/api/projects/{pid}/templates/{второй_бланк}/use?report={второй['id']}")
    assert ответ.status_code == 200, ответ.text

    ключи = lambda rid: [  # noqa: E731
        т["key"] for т in
        клиент.get(f"/api/projects/{pid}/tags?report={rid}").json()["tags"]]
    assert "аннотация" in ключи(второй["id"])
    assert ключи(первый["id"]) == ["цель"]
    # Пометка «по нему собирается» — тоже про отчёт.
    свои = клиент.get(f"/api/projects/{pid}/templates?report={второй['id']}").json()
    выбран = {б["id"]: б["active"] for б in свои}
    assert выбран[второй_бланк] is True and выбран[первый_бланк] is False


def test_чужой_бланк_не_годится(клиент, работа):
    """Завести отчёт можно только по бланку, приложенному к этой работе."""
    pid = работа["id"]
    чужая = создать_проект(клиент, личное_id(клиент), name="другая",
                           шаблон=docx_байты())
    чужой_бланк = приложить(клиент, чужая["id"], docx_байты(("цель",)), "Чужой")
    ответ = клиент.post(f"/api/projects/{pid}/reports",
                        json={"template_id": чужой_бланк})
    assert ответ.status_code == 404, ответ.text


def test_отчёт_без_бланка(клиент, работа):
    """Без бланка: первый остаётся на бланке работы, следующий строится с нуля."""
    pid = работа["id"]
    первый = завести_отчёт(клиент, pid)
    теги = клиент.get(f"/api/projects/{pid}/tags?report={первый['id']}").json()
    assert [т["key"] for т in теги["tags"]] == ["цель", "выводы"]

    второй = завести_отчёт(клиент, pid)
    теги = клиент.get(f"/api/projects/{pid}/tags?report={второй['id']}").json()
    assert теги["tags"] == []
    assert второй["template_name"] == ""


# ── первый отчёт и корневой документ работы ──────────────────────────────────

def test_первый_отчёт_наследует_документ_работы(клиент, работа):
    """Написанное в работе до отчётов видно из первого же отчёта.

    Работа живёт до всяких отчётов: её заводят с бланком, в ней пишут значения.
    Отдельный пустой документ первому отчёту означал бы, что всё это разом
    пропало с экрана, оставшись целым на томе.
    """
    pid = работа["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "написано до отчётов"})

    первый = завести_отчёт(клиент, pid, name="Глава 1")
    значения = клиент.get(
        f"/api/projects/{pid}/values?report={первый['id']}").json()
    assert значения["values"]["цель"]["text"] == "написано до отчётов"
    # Тот же документ виден и по адресу работы без отчёта: своего каталога у
    # первого отчёта нет вовсе, и заводить его незачем.
    корень = клиент.get(f"/api/projects/{pid}/values").json()
    assert корень["values"]["цель"]["text"] == "написано до отчётов"

    # Второй получает свой каталог и начинает с пустого набора значений.
    второй = завести_отчёт(клиент, pid)
    чужие = клиент.get(f"/api/projects/{pid}/values?report={второй['id']}").json()
    assert чужие["values"] == {}


def test_первый_отчёт_с_бланком_меняет_бланк_корня(клиент, работа):
    """Бланк первого отчёта — это бланк работы, и значения при этом целы.

    Назначается он тем же путём, что «собирать по этому бланку»: новый манифест
    строится поверх старого, поэтому написанное остаётся на месте, а тег,
    которого в новом бланке нет, просто не показывается.
    """
    pid = работа["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "остаётся"})
    другой = приложить(клиент, pid, docx_байты(("цель", "аннотация")), "Другой")

    первый = завести_отчёт(клиент, pid, template_id=другой)
    assert первый["template_name"] == "Другой"

    ключи = [т["key"] for т in клиент.get(
        f"/api/projects/{pid}/tags?report={первый['id']}").json()["tags"]]
    assert ключи == ["цель", "аннотация"]
    значения = клиент.get(
        f"/api/projects/{pid}/values?report={первый['id']}").json()
    assert значения["values"]["цель"]["text"] == "остаётся"
    # Бланк выбран у самой работы: список бланков помечает его выбранным и без
    # `?report=`.
    бланки = клиент.get(f"/api/projects/{pid}/templates").json()
    assert {б["id"]: б["active"] for б in бланки} == {другой: True}


def test_отчёт_после_удаления_первого_снова_забирает_корень(клиент, работа):
    """У работы один собственный документ, и он достаётся старшей записи.

    Удаление отчёта без каталога сносит только запись журнала: корневой документ
    принадлежит работе, а не отчёту, и стирать написанное вместе со строкой
    нельзя. Поэтому следующий заведённый отчёт снова забирает его целым — то же
    правило, а не исключение из него.
    """
    pid = работа["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "написано в работе"})
    первый = завести_отчёт(клиент, pid)
    assert клиент.delete(
        f"/api/projects/{pid}/reports/{первый['id']}").status_code == 204
    assert клиент.get(f"/api/projects/{pid}/reports").json() == []

    снова = завести_отчёт(клиент, pid)
    значения = клиент.get(
        f"/api/projects/{pid}/values?report={снова['id']}").json()
    assert значения["values"]["цель"]["text"] == "написано в работе"

    # А отчёт, заведённый следом, остаётся при своём каталоге: корень свободен
    # только пока записей об отчётах нет вовсе.
    свой = завести_отчёт(клиент, pid)
    assert клиент.get(
        f"/api/projects/{pid}/values?report={свой['id']}").json()["values"] == {}


def test_кривой_отчёт_в_запросе(клиент, работа):
    """Мусор вместо идентификатора умирает на входе, а не на томе."""
    ответ = клиент.get(f"/api/projects/{работа['id']}/values?report=../чужое")
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "invalid_id"


def test_чужого_отчёта_не_видно(клиент, работа):
    ответ = клиент.delete(
        f"/api/projects/{работа['id']}/reports/"
        "00000000-0000-4000-8000-000000000000")
    assert ответ.status_code == 404


def test_роли(app, клиент, работа, сосед):
    """Смотреть — viewer, заводить и сносить — editor."""
    pid = работа["id"]
    ws = личное_id(клиент)
    позвать(app, клиент, ws, сосед, role="viewer")
    отчёт = завести_отчёт(клиент, pid)

    войти(app, сосед)
    assert клиент.get(f"/api/projects/{pid}/reports").status_code == 200
    assert клиент.post(f"/api/projects/{pid}/reports", json={}).status_code == 403
    assert клиент.delete(
        f"/api/projects/{pid}/reports/{отчёт['id']}").status_code == 403


# ── превью первой страницы ───────────────────────────────────────────────────

def pdf_байты(страниц: int = 2) -> bytes:
    """Настоящий PDF на нужное число страниц — рисуется той же библиотекой."""
    import pymupdf

    документ = pymupdf.open()
    for номер in range(страниц):
        страница = документ.new_page()
        страница.insert_text((72, 72), f"page {номер + 1}")
    данные = документ.tobytes()
    документ.close()
    return данные


class _Контекст:
    """Столько от `JobContext`, сколько читает `запомнить_превью`.

    Подделкой, а не настоящим заданием: превью пишется после того, как документ
    собран, то есть после LibreOffice, которого в проверке быть не должно —
    иначе она проверяла бы чужую программу, а не нашу запись.
    """

    def __init__(self, app, project_id: str, report: str):
        self.job_id = "job-превью"
        self.report = report
        self.session_scope = app.state.db.session_scope
        self.job = type("Задание", (), {"project_id": project_id})()


def test_первая_страница_становится_png():
    """PDF → PNG первой страницы заданной ширины, а не всего документа."""
    import pymupdf

    from api.runs.handlers.build import ШИРИНА_ПРЕВЬЮ, первая_страница

    картинка = первая_страница(pdf_байты(страниц=3))
    assert картинка[:8] == b"\x89PNG\r\n\x1a\n"
    снимок = pymupdf.Pixmap(картинка)
    assert снимок.width == ШИРИНА_ПРЕВЬЮ
    # Пропорция страницы сохранена: обрезанную страницу не узнать.
    assert снимок.height > снимок.width


def test_превью_записывается_у_отчёта(app, клиент, работа):
    """Идентификатор картинки ложится в ту запись, из которой шла сборка."""
    import orchestrator

    from api.projects.models import ProjectRun
    from api.projects.service import project_dir
    from api.runs.handlers.build import запомнить_превью

    pid = работа["id"]
    бланк = приложить(клиент, pid, docx_байты(("цель",)), "ГОСТ")
    отчёт = завести_отчёт(клиент, pid, template_id=бланк)

    with app.state.db.session_scope() as s:
        каталог = project_dir(s, app.state.settings, pid)
    проект = orchestrator.Project(каталог, report=отчёт["id"])
    pdf = проект.put_artifact(pdf_байты(), name="собранное")

    art = запомнить_превью(_Контекст(app, pid, отчёт["id"]), проект, pdf)
    assert art
    with app.state.db.session_scope() as s:
        assert s.get(ProjectRun, отчёт["id"]).preview_artifact_id == art
    # Картинка лежит артефактом работы и достаётся тем же маршрутом, что и всё
    # прочее её содержимое, — и переживает перезагрузку страницы.
    ответ = клиент.get(f"/api/projects/{pid}/artifacts/{art}")
    assert ответ.status_code == 200 and ответ.content[:4] == b"\x89PNG"
    список = клиент.get(f"/api/projects/{pid}/reports").json()
    assert список[0]["preview_artifact_id"] == art


def test_превью_не_пишется_без_отчёта(app, клиент, работа):
    """Сборка не из отчёта картинку не запоминает: записать её некуда."""
    import orchestrator

    from api.projects.service import project_dir
    from api.runs.handlers.build import запомнить_превью

    with app.state.db.session_scope() as s:
        каталог = project_dir(s, app.state.settings, работа["id"])
    проект = orchestrator.Project(каталог)
    pdf = проект.put_artifact(pdf_байты(), name="собранное")
    assert запомнить_превью(_Контекст(app, работа["id"], ""), проект, pdf) == ""
