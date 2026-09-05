"""
Шаблоны отчётов человека: загрузка, список, чужой, удаление, квота, работа по шаблону.

Проверяется здесь ровно то, что обещано в `api/templates/__init__.py`, и в том
же порядке. Два утверждения из этого списка стоят дороже прочих и потому идут
первыми в файле:

* **число тегов в списке — то же, что в работе.** Оно считается общей дверью
  оркестратора (`template_tags`), и разойтись эти два числа могут только молча;
* **чужой шаблон отвечает как несуществующий**: разный ответ рассказывал
  бы, что шаблон с таким идентификатором у кого-то есть.

Пользователь настоящий (`c_fixtures`, живая регистрация); подменён, как
и всюду, только `current_user`.
"""
from __future__ import annotations

import dataclasses
import os
from sqlalchemy import select

from api.templates.models import ReportTemplate

from .c_fixtures import (ПАРОЛЬ, docx_байты, войти, завести,  # noqa: F401
                         клиент, личное_id, создать_проект, сосед, хозяин)

DOCX_ТИП = ("application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document")


def загрузить(клиент, данные: bytes, *, имя: str | None = "ГОСТ 2026",
              файл: str = "шаблон.docx"):
    """Загрузить шаблон формой, как это делает сайт."""
    поля = {"name": имя} if имя is not None else None
    return клиент.post("/api/templates", data=поля,
                       files={"file": (файл, данные, DOCX_ТИП)})


# ── загрузка и список ────────────────────────────────────────────────────────

def test_загруженный_шаблон_виден_в_списке(клиент, хозяин):
    """Карточка несёт имя, размер и число тегов; путей на томе в ней нет."""
    байты = docx_байты(("цель", "выводы", "введение"))
    ответ = загрузить(клиент, байты)
    assert ответ.status_code == 201, ответ.text
    карточка = ответ.json()
    assert карточка["name"] == "ГОСТ 2026"
    assert карточка["bytes"] == len(байты)
    assert карточка["tags"] == 3
    assert "/" not in карточка["sha256"], "в ответе не бывает путей"

    список = клиент.get("/api/templates")
    assert список.status_code == 200
    assert [ш["id"] for ш in список.json()] == [карточка["id"]]


def test_имя_берётся_из_файла_если_его_не_написали(клиент, хозяин):
    """Пустое имя — это имя файла без расширения, а не слово «шаблон».

    Список из пяти «шаблонов» бесполезен ровно так же, как список из пяти
    пустых строк.
    """
    ответ = загрузить(клиент, docx_байты(), имя="", файл="Записка ГОСТ.docx")
    assert ответ.status_code == 201, ответ.text
    assert ответ.json()["name"] == "Записка ГОСТ"


def test_не_docx_отвергается(клиент, хозяин):
    """Файл, на котором упало бы создание проекта, отвергается при загрузке."""
    ответ = загрузить(клиент, "это не docx, а просто байты".encode("utf-8"))
    assert ответ.status_code == 400, ответ.text
    assert ответ.json()["error"]["code"] == "bad_template"


def test_слишком_большой_файл_рвётся_на_потоке(app, клиент, хозяин):
    """Предел тот же, что у материалов (`file_max_bytes`), и режет он до тома."""
    app.state.settings = dataclasses.replace(app.state.settings,
                                             file_max_bytes=64)
    ответ = загрузить(клиент, docx_байты())
    assert ответ.status_code == 413, ответ.text
    assert ответ.json()["error"]["code"] == "file_too_large"


def test_квота_считает_шаблоны(app, клиент, хозяин):
    """Шаблон занимает место человека наравне с проектами.

    Порог один на всё (`user_quota_bytes`): второй порог для файлов вне
    проектов означал бы, что «250 МБ на человека» больше ничего не значит.
    """
    байты = docx_байты()
    app.state.settings = dataclasses.replace(app.state.settings,
                                             user_quota_bytes=len(байты) + 1024)
    первый = загрузить(клиент, байты)
    assert первый.status_code == 201, первый.text

    # Второй такой же уже не влезает: место, занятое первым, посчитано.
    второй = загрузить(клиент, docx_байты(("иное",)), имя="второй")
    assert второй.status_code == 413, второй.text
    assert второй.json()["error"]["code"] == "quota_exceeded"


# ── чужое и удаление ─────────────────────────────────────────────────────────

def test_чужой_шаблон_как_несуществующий(app, клиент, хозяин, сосед):
    """Скачать, удалить и завести работу по чужому — одинаковые `404`."""
    свой = загрузить(клиент, docx_байты()).json()

    войти(app, сосед)
    assert клиент.get("/api/templates").json() == []
    assert клиент.get(f"/api/templates/{свой['id']}/blob").status_code == 404
    assert клиент.delete(f"/api/templates/{свой['id']}").status_code == 404


def test_удаление_уносит_и_файл(app, клиент, хозяин):
    """После удаления нет ни строки, ни байтов на томе: место возвращается."""
    from api.templates import service

    шаблон = загрузить(клиент, docx_байты()).json()
    путь = service.путь(app.state.settings, хозяин.id, шаблон["id"])
    assert os.path.isfile(путь)

    assert клиент.delete(f"/api/templates/{шаблон['id']}").status_code == 204
    assert not os.path.exists(путь)
    assert клиент.get("/api/templates").json() == []
    with app.state.db.session_scope() as s:
        assert list(s.scalars(select(ReportTemplate))) == []


def test_скачивание_отдаёт_те_же_байты(клиент, хозяин):
    """Оригинал байт в байт, с именем шаблона и без угадывания типа браузером."""
    байты = docx_байты()
    шаблон = загрузить(клиент, байты).json()
    ответ = клиент.get(f"/api/templates/{шаблон['id']}/blob")
    assert ответ.status_code == 200
    assert ответ.content == байты
    assert ответ.headers["x-content-type-options"] == "nosniff"
    assert "ГОСТ" in ответ.headers["content-disposition"] or \
        "%D0%93" in ответ.headers["content-disposition"]


def test_ключом_сюда_нельзя(app, клиент, хозяин):
    """Личные файлы аккаунта — только сессией сайта (`ТОЛЬКО_СЕССИЯ`).

    Ключ выдаётся настоящий, а подмена вошедшего снимается: иначе запрос вообще
    не доходит до разбора ключа, и тест проверял бы подмену, а не заслон.
    """
    from api import tokens as ключи

    строка = клиент.post("/api/tokens",
                         json={"name": "скрипт",
                               "scopes": list(ключи.ПРАВА)}).json()["token"]
    app.dependency_overrides.clear()
    клиент.headers["Authorization"] = f"Bearer {строка}"

    ответ = клиент.get("/api/templates")
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "token_not_allowed"


# ── работа по своему шаблону ─────────────────────────────────────────────────

def test_проект_по_template_id_видит_те_же_теги(клиент, хозяин):
    """Работа, заведённая по сохранённому шаблону, несёт его теги.

    Это и есть то самое утверждение, ради которого число тегов в списке
    считается общей дверью оркестратора: разойтись эти два числа могут только
    молча.
    """
    шаблон = загрузить(клиент, docx_байты(("цель", "выводы"))).json()
    ws = личное_id(клиент)
    ответ = клиент.post("/api/projects",
                        data={"workspace_id": ws, "name": "по шаблону",
                              "template_id": шаблон["id"]})
    assert ответ.status_code == 201, ответ.text
    assert sorted(ответ.json()["keys"]) == ["выводы", "цель"]
    assert шаблон["tags"] == 2


def test_файл_и_template_id_вместе_отказ(клиент, хозяин):
    """Молча выбранный за человека шаблон — это чужой ГОСТ в готовой работе."""
    шаблон = загрузить(клиент, docx_байты()).json()
    ws = личное_id(клиент)
    ответ = клиент.post(
        "/api/projects",
        data={"workspace_id": ws, "name": "оба", "template_id": шаблон["id"]},
        files={"template": ("шаблон.docx", docx_байты(), DOCX_ТИП)})
    assert ответ.status_code == 400, ответ.text
    assert ответ.json()["error"]["code"] == "bad_template"


def test_чужой_template_id_не_заводит_работу(app, клиент, хозяин, сосед):
    """Чужой идентификатор в создании работы — `404`, а не чужой шаблон."""
    свой = загрузить(клиент, docx_байты()).json()
    войти(app, сосед)
    ws = личное_id(клиент)
    ответ = клиент.post("/api/projects",
                        data={"workspace_id": ws, "name": "чужое",
                              "template_id": свой["id"]})
    assert ответ.status_code == 404, ответ.text


def test_удалённый_шаблон_не_ломает_готовые_работы(клиент, хозяин):
    """Байты копируются в проект, а не берутся по ссылке."""
    шаблон = загрузить(клиент, docx_байты(("цель",))).json()
    ws = личное_id(клиент)
    проект = клиент.post("/api/projects",
                         data={"workspace_id": ws, "name": "жива",
                               "template_id": шаблон["id"]}).json()

    assert клиент.delete(f"/api/templates/{шаблон['id']}").status_code == 204
    ответ = клиент.get(f"/api/projects/{проект['id']}")
    assert ответ.status_code == 200
    assert ответ.json()["keys"] == ["цель"]
