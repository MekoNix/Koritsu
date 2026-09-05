"""
Проверки проектов: каталог на томе, роли, корзина, уборка, размер.

Главное здесь — не формат ответа, а три обещания тома:

1. каталог лежит по паре uuid (`users/<владелец>/projects/<проект>/`) — иначе
   квота, резервная копия и переезд считают не то;
2. **путь наружу не уезжает никогда** (§3) — это проверяется регуляркой по телу
   каждого ответа, а не глазами по одному полю;
3. корзина держит каталог до срока и сносит его после — ни раньше, ни «когда-
   нибудь».
"""
from __future__ import annotations

import datetime
import os
import re

from sqlalchemy import select

from api.projects import Project, bytes_used, dir_size, project_dir, purge_expired
from api.workspaces import EDITOR, VIEWER
from api.workspaces.service import personal_workspace

from .c_fixtures import (docx_байты, войти, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)

# Кусок абсолютного пути в теле ответа. Ищем и наш временный том, и `/data` из
# записки: тест обязан ловить утечку и на машине, где тома нет.
ПУТЬ_RE = re.compile(r"(/data/|/tmp/|/home/|users/[0-9a-f-]{36}/projects)")


def без_путей(ответ) -> None:
    """Ни один путь на диске не попал в тело. Проверяется целиком, а не по полям.

    По полям было бы дешевле и бесполезнее: утечка приходит новым полем,
    которого в списке проверяемых нет, — ровно так, как её и добавляют.
    """
    беда = ПУТЬ_RE.search(ответ.text)
    assert беда is None, f"в ответе уехал путь: {беда.group(0)} — {ответ.text[:400]}"


# ── создание ─────────────────────────────────────────────────────────────────

def test_создание_кладёт_каталог_по_uuid_владельца(app, клиент, хозяин, settings):
    """Каталог — `{том}/users/<владелец>/projects/<проект>/`, и ничей больше."""
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    ожидаемый = os.path.join(settings.data_dir, "users", хозяин.id, "projects",
                             проект["id"])
    assert os.path.isdir(ожидаемый)
    assert os.path.isfile(os.path.join(ожидаемый, "project.json"))
    with app.state.db.session_scope() as s:
        assert project_dir(s, settings, проект["id"]) == ожидаемый


def test_шаблон_доезжает_тегами_в_карточку(клиент, хозяин):
    """Теги карточки — из манифеста проекта, то есть из принесённого DOCX.

    Из манифеста, а не из значений: до первого прогона значений нет ни одного,
    и карточка, считающая теги по ним, отвечала бы «тегов нет» на проект, у
    которого их четыре. Ровно на этот вопрос смотрит колонка тегов на сайте.
    """
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, шаблон=docx_байты(("цель", "выводы")))
    карточка = клиент.get(f"/api/projects/{проект['id']}")
    assert карточка.status_code == 200
    assert карточка.json()["keys"] == ["цель", "выводы"]   # порядок — шаблона
    без_путей(карточка)


def test_проект_без_шаблона(клиент, хозяин, settings):
    """Без файла оркестратор строит документ с нуля (решение главной сессии).

    Проект при этом полноценный: у него есть `project.json`, манифест и
    артефакт-шаблон, то есть собирать отчёт по нему можно сразу.
    """
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, name="без шаблона")
    каталог = os.path.join(settings.data_dir, "users", проект["owner_id"],
                           "projects", проект["id"])
    import json
    настройки = json.load(open(os.path.join(каталог, "project.json")))
    assert настройки["template_source"] == "blank"
    assert настройки["template"], "шаблон-артефакт не записан"


def test_кривой_шаблон_это_400_и_каталог_убран(клиент, хозяин, settings):
    """Не-DOCX отвергается внятно, а каталог за собой не остаётся.

    Каталог важнее кода ответа: оставшийся пустой каталог никому не принадлежит
    (строки в базе нет — она откатилась) и место занимает навсегда.
    """
    ws = личное_id(клиент)
    ответ = клиент.post("/api/projects", data={"workspace_id": ws, "name": "хлам"},
                        files={"template": ("t.docx", "не docx вовсе".encode(),
                                            "text/plain")})
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "bad_template"
    без_путей(ответ)
    пользователь = os.path.join(settings.data_dir, "users", хозяин.id, "projects")
    assert not os.path.isdir(пользователь) or os.listdir(пользователь) == []


def test_путь_не_уезжает_ни_в_одном_ответе(клиент, хозяин):
    """Обход всех маршрутов проекта: тела проверяются целиком."""
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    pid = проект["id"]
    for ответ in (клиент.get("/api/projects", params={"workspace_id": ws}),
                  клиент.get(f"/api/projects/{pid}"),
                  клиент.get(f"/api/projects/{pid}/values"),
                  клиент.patch(f"/api/projects/{pid}", json={"name": "новое"}),
                  клиент.delete(f"/api/projects/{pid}")):
        assert ответ.status_code == 200, ответ.text
        без_путей(ответ)


# ── роли ─────────────────────────────────────────────────────────────────────

def test_чужой_проект_это_404(app, клиент, хозяин, сосед):
    """Не участник пространства не узнаёт даже, что такой проект есть (§3)."""
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    войти(app, сосед)
    ответ = клиент.get(f"/api/projects/{проект['id']}")
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"


def test_viewer_читает_editor_пишет(app, клиент, хозяин, сосед):
    """`viewer` получает `GET` и не получает `PUT`; `editor` получает оба."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    pid = проект["id"]
    клиент.post(f"/api/workspaces/{ws}/members",
                json={"email": сосед.email, "role": VIEWER})

    войти(app, сосед)
    assert клиент.get(f"/api/projects/{pid}/values").status_code == 200
    отказ = клиент.put(f"/api/projects/{pid}/values/цель",
                       json={"type": "markdown", "text": "нельзя"})
    assert отказ.status_code == 403
    assert отказ.json()["error"]["code"] == "forbidden"

    войти(app, хозяин)
    клиент.patch(f"/api/workspaces/{ws}/members/{сосед.id}", json={"role": EDITOR})
    войти(app, сосед)
    можно = клиент.put(f"/api/projects/{pid}/values/цель",
                       json={"type": "markdown", "text": "можно"})
    assert можно.status_code == 200, можно.text
    assert можно.json()["source"] == "manual", "значение рукой человека"


def test_значение_возвращается_чтением(клиент, хозяин):
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, шаблон=docx_байты())["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "изучить"})
    значения = клиент.get(f"/api/projects/{pid}/values").json()["values"]
    assert значения["цель"]["text"] == "изучить"
    # Ключи карточки — теги шаблона целиком, заполненные и нет: список слева
    # на сайте не сокращается по мере работы, он в ней не меняется вовсе.
    assert клиент.get(f"/api/projects/{pid}").json()["keys"] == ["цель", "выводы"]


def test_значение_не_объект_это_400(клиент, хозяин):
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, шаблон=docx_байты())["id"]
    ответ = клиент.put(f"/api/projects/{pid}/values/цель", json=["не объект"])
    assert ответ.status_code in (400, 422)


# ── теги шаблона ─────────────────────────────────────────────────────────────

def test_теги_нового_проекта_видны_и_пусты(клиент, хозяин):
    """Новый проект: теги шаблона на месте, все незаполненные.

    Это тот самый вопрос, ради которого маршрут заведён: до первого прогона
    значений нет ни одного, а колонка тегов обязана показать все четыре — иначе
    человеку нечего нажимать.
    """
    ws = личное_id(клиент)
    pid = создать_проект(
        клиент, ws,
        шаблон=docx_байты(("цель", "теория", "листинг", "выводы")))["id"]
    ответ = клиент.get(f"/api/projects/{pid}/tags")
    assert ответ.status_code == 200, ответ.text
    теги = ответ.json()["tags"]
    assert [т["key"] for т in теги] == ["цель", "теория", "листинг", "выводы"]
    assert all(т["filled"] is False for т in теги)
    assert all(т["source"] is None and т["version"] is None for т in теги)
    assert all("type" in т and "label" in т and "required" in т for т in теги)
    без_путей(ответ)


def test_тег_после_значения_заполнен(клиент, хозяин):
    """Записали значение рукой — тег заполнен, с источником и номером версии."""
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, шаблон=docx_байты(("цель", "выводы")))["id"]
    клиент.put(f"/api/projects/{pid}/values/цель",
               json={"type": "markdown", "text": "изучить сортировки"})
    теги = {т["key"]: т for т in
            клиент.get(f"/api/projects/{pid}/tags").json()["tags"]}
    assert теги["цель"]["filled"] is True
    assert теги["цель"]["source"] == "manual"
    assert теги["цель"]["version"] == 1
    assert теги["цель"]["at"]
    assert теги["выводы"]["filled"] is False


def test_теги_проекта_без_шаблона_пусты(клиент, хозяин):
    """Документ с нуля — тегов нет, и это пустой список, а не отказ."""
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, name="без шаблона")["id"]
    ответ = клиент.get(f"/api/projects/{pid}/tags")
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["tags"] == []


def test_теги_чужого_проекта_это_404(app, клиент, хозяин, сосед):
    """Право у маршрута то же, что у соседей: не участник — «нет такого»."""
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, шаблон=docx_байты())["id"]
    войти(app, сосед)
    assert клиент.get(f"/api/projects/{pid}/tags").status_code == 404


# ── корзина и уборка ─────────────────────────────────────────────────────────

def test_корзина_каталог_на_месте_восстановление(app, клиент, хозяин, settings):
    """Удаление — это метка в базе, а не `rm -rf`: десять дней передумать (§2)."""
    ws = личное_id(клиент)
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    pid = проект["id"]
    каталог = os.path.join(settings.data_dir, "users", хозяин.id, "projects", pid)

    удалено = клиент.delete(f"/api/projects/{pid}").json()
    assert удалено["deleted_at"] and удалено["purge_after"] > удалено["deleted_at"]
    assert os.path.isdir(каталог), "каталог снесли в момент удаления"

    обычный = клиент.get("/api/projects", params={"workspace_id": ws}).json()
    assert обычный["projects"] == []
    в_корзине = клиент.get("/api/projects",
                           params={"workspace_id": ws, "trash": True}).json()
    assert [p["id"] for p in в_корзине["projects"]] == [pid]
    assert клиент.get(f"/api/projects/{pid}").status_code == 409

    вернули = клиент.post(f"/api/projects/{pid}/restore")
    assert вернули.status_code == 200 and вернули.json()["deleted_at"] is None
    assert клиент.get(f"/api/projects/{pid}").status_code == 200


def test_purge_expired_сносит_только_просроченное(app, клиент, хозяин, settings):
    """Каталог исчезает после `purge_after`, и ни секундой раньше."""
    ws = личное_id(клиент)
    живой = создать_проект(клиент, ws, name="живой", шаблон=docx_байты())["id"]
    старый = создать_проект(клиент, ws, name="старый", шаблон=docx_байты())["id"]
    клиент.delete(f"/api/projects/{старый}")
    клиент.delete(f"/api/projects/{живой}")

    каталог = lambda pid: os.path.join(  # noqa: E731
        settings.data_dir, "users", хозяин.id, "projects", pid)

    with app.state.db.session_scope() as s:
        # Пока срок не вышел, уборка не трогает ничего — даже того, что в корзине.
        assert purge_expired(s, settings) == []
    assert os.path.isdir(каталог(старый)) and os.path.isdir(каталог(живой))

    # Отматываем срок одному проекту: так же это увидит воркер через десять дней.
    with app.state.db.session_scope() as s:
        p = s.get(Project, старый)
        p.purge_after = datetime.datetime.now(datetime.timezone.utc) \
            - datetime.timedelta(seconds=1)
    with app.state.db.session_scope() as s:
        assert purge_expired(s, settings) == [старый]
        assert s.get(Project, старый) is None
        assert s.get(Project, живой) is not None
    assert not os.path.exists(каталог(старый)), "каталог просроченного остался"
    assert os.path.isdir(каталог(живой)), "снесли каталог, чей срок не вышел"


def test_удаление_пространства_кладёт_проекты_в_корзину(app, клиент, хозяин):
    """Пространство в корзине — и проекты в корзине; вернулось — вернулись."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    pid = создать_проект(клиент, ws, шаблон=docx_байты())["id"]

    assert клиент.delete(f"/api/workspaces/{ws}").status_code == 200
    with app.state.db.session_scope() as s:
        assert s.get(Project, pid).deleted_at is not None

    # Проект из удалённого пространства поодиночке не достаётся: он всё равно
    # никому не виден, и «Восстановить» соврало бы.
    отказ = клиент.post(f"/api/projects/{pid}/restore")
    assert отказ.status_code == 409 and отказ.json()["error"]["code"] == "in_trash"

    assert клиент.post(f"/api/workspaces/{ws}/restore").status_code == 200
    with app.state.db.session_scope() as s:
        assert s.get(Project, pid).deleted_at is None


def test_в_удалённое_пространство_проект_не_создать(клиент, хозяин):
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    клиент.delete(f"/api/workspaces/{ws}")
    ответ = клиент.post("/api/projects", data={"workspace_id": ws, "name": "нет"})
    assert ответ.status_code == 404, "удалённое пространство не отличимо от чужого"


# ── размер и квота ───────────────────────────────────────────────────────────

def test_bytes_used_считает_по_владельцу(app, клиент, хозяин, сосед, settings):
    """Экспорт для агента D: сумма каталогов проектов **создателя** (§1).

    Проект соседа в общем пространстве ест место соседа, а не владельца
    пространства, — ровно этого и требует решение о квоте на владельца.
    """
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    создать_проект(клиент, ws, name="мой", шаблон=docx_байты())
    клиент.post(f"/api/workspaces/{ws}/members",
                json={"email": сосед.email, "role": EDITOR})

    with app.state.db.session_scope() as s:
        мой = bytes_used(s, settings, хозяин.id)
        чужой = bytes_used(s, settings, сосед.id)
    assert мой > 0, "каталог проекта весит хоть что-то"
    assert чужой == 0

    войти(app, сосед)
    создать_проект(клиент, ws, name="соседский", шаблон=docx_байты())
    with app.state.db.session_scope() as s:
        assert bytes_used(s, settings, хозяин.id) == мой, "чужой проект в мою квоту"
        assert bytes_used(s, settings, сосед.id) > 0


def test_корзина_считается_в_квоте(app, клиент, хозяин, settings):
    """Пока каталог на диске, место занято: иначе квоту обходят по кругу."""
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, шаблон=docx_байты())["id"]
    with app.state.db.session_scope() as s:
        до = bytes_used(s, settings, хозяин.id)
    клиент.delete(f"/api/projects/{pid}")
    with app.state.db.session_scope() as s:
        assert bytes_used(s, settings, хозяин.id) == до


def test_dir_size_на_пустом_месте(tmp_path):
    """Каталога нет — ноль, а не беда: уборка могла пройти раньше нас."""
    assert dir_size(str(tmp_path / "которого-нет")) == 0
    (tmp_path / "файл").write_bytes(b"12345")
    assert dir_size(str(tmp_path)) == 5


def test_проекты_чужого_пространства_не_перечислить(app, клиент, хозяин, сосед):
    ws = личное_id(клиент)
    создать_проект(клиент, ws, шаблон=docx_байты())
    войти(app, сосед)
    ответ = клиент.get("/api/projects", params={"workspace_id": ws})
    assert ответ.status_code == 404


def test_переименование_доезжает_до_project_json(app, клиент, хозяин, settings):
    """Имя лежит и в базе, и в `project.json` — их правит один обработчик."""
    import json
    ws = личное_id(клиент)
    pid = создать_проект(клиент, ws, name="старое", шаблон=docx_байты())["id"]
    assert клиент.patch(f"/api/projects/{pid}", json={"name": "новое"}).status_code == 200
    with app.state.db.session_scope() as s:
        assert s.get(Project, pid).name == "новое"
        путь = project_dir(s, settings, pid)
    assert json.load(open(os.path.join(путь, "project.json")))["name"] == "новое"


def test_личное_пространство_хозяина_видно_в_базе(app, хозяин):
    """Мелочь, но она держит всё остальное: без личного некуда класть проекты."""
    with app.state.db.session_scope() as s:
        assert personal_workspace(s, хозяин.id) is not None
        сколько = len(s.scalars(select(Project)).all())
    assert сколько == 0
