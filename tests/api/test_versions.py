"""
История значений и возврат: теги и список блоков живого режима.

Проверяется главное свойство хранилища версий, ради которого оно устроено
именно так: **перезаписи не бывает**. Возврат к прошлой версии дописывает новую,
а не уменьшает номер, — иначе двое, глядя на «версию 3», видели бы разные
значения.

И второе: разрез ролей. Смотреть историю может всякий, кто видит проект
(`viewer`), а менять то, что покажется в отчёте, — только `editor`.
"""
from __future__ import annotations

import orchestrator
from api.projects.service import project_dir
from api.workspaces import EDITOR, VIEWER

from .c_fixtures import (docx_байты, войти, клиент, личное_id,  # noqa: F401
                         позвать, создать_проект, сосед, хозяин)

ЦЕЛЬ_1 = {"type": "markdown", "text": "Первая редакция цели."}
ЦЕЛЬ_2 = {"type": "markdown", "text": "Вторая редакция цели."}
ЦЕЛЬ_3 = {"type": "markdown", "text": "Третья редакция цели."}

БЛОКИ_1 = [{"key": "b-01", "kind": "markdown", "label": "Введение",
            "value": {"type": "markdown", "text": "Первый список."}}]
БЛОКИ_2 = [{"key": "b-01", "kind": "markdown", "label": "Введение",
            "value": {"type": "markdown", "text": "Второй список."}},
           {"key": "b-02", "kind": "markdown", "label": "Вывод",
            "value": {"type": "markdown", "text": "Приписали блок."}}]


def проект(клиент) -> dict:
    return создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())


def на_томе(app, project_id: str) -> orchestrator.Project:
    """Тот же каталог проекта, но открытый мимо службы: живой режим блоков
    маршрута записи ещё не имеет, и заводить его ради теста незачем."""
    with app.state.db.session_scope() as s:
        return orchestrator.Project(
            project_dir(s, app.state.settings, project_id))


def общий_проект(app, клиент, сосед, роль: str) -> dict:
    """Проект в общем пространстве, где сосед — с названной ролью."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    позвать(app, клиент, ws, сосед, роль)
    return создать_проект(клиент, ws, шаблон=docx_байты())


# ── версии значения тега ─────────────────────────────────────────────────────

def test_каждая_правка_это_новая_версия(app, клиент, хозяин):
    p = проект(клиент)
    for значение in (ЦЕЛЬ_1, ЦЕЛЬ_2, ЦЕЛЬ_3):
        assert клиент.put(f"/api/projects/{p['id']}/values/цель",
                          json=значение).status_code == 200

    тело = клиент.get(f"/api/projects/{p['id']}/values/цель/versions").json()
    assert тело["key"] == "цель"
    assert [v["n"] for v in тело["versions"]] == [1, 2, 3]
    # Версия самоописана: без этого через месяц не объяснить, откуда значение.
    assert all(v["source"] == "manual" for v in тело["versions"])
    assert all("prompt_hash" in v and "manifest_version" in v
               for v in тело["versions"])
    # Значений в списке нет: историю читают, чтобы выбрать, а не чтобы прочесть.
    assert all("value" not in v for v in тело["versions"])


def test_прошлая_версия_читается_целиком(app, клиент, хозяин):
    p = проект(клиент)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_1)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_2)

    тело = клиент.get(f"/api/projects/{p['id']}/values/цель/versions/1").json()
    assert тело["value"] == ЦЕЛЬ_1 and тело["version"]["n"] == 1


def test_возврат_дописывает_версию_а_не_уменьшает_номер(app, клиент, хозяин):
    """Иначе номер версии молча уменьшился бы, и два человека, глядя на
    «версию 3», видели бы разные значения."""
    p = проект(клиент)
    for значение in (ЦЕЛЬ_1, ЦЕЛЬ_2, ЦЕЛЬ_3):
        клиент.put(f"/api/projects/{p['id']}/values/цель", json=значение)

    ответ = клиент.post(f"/api/projects/{p['id']}/values/цель/rollback",
                        json={"n": 1})
    assert ответ.status_code == 200, ответ.text
    тело = ответ.json()
    assert тело["restored_from"] == 1 and тело["version"]["n"] == 4
    assert "вернули версию 1" in тело["version"]["flags"]
    # Текущее значение — то, к которому вернулись; история цела.
    значения = клиент.get(f"/api/projects/{p['id']}/values").json()["values"]
    assert значения["цель"] == ЦЕЛЬ_1
    список = клиент.get(f"/api/projects/{p['id']}/values/цель/versions").json()
    assert [v["n"] for v in список["versions"]] == [1, 2, 3, 4]


def test_версии_нет_это_404(app, клиент, хозяин):
    p = проект(клиент)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_1)

    нет_версии = клиент.get(f"/api/projects/{p['id']}/values/цель/versions/7")
    assert нет_версии.status_code == 404
    нет_тега = клиент.get(f"/api/projects/{p['id']}/values/выводы/versions")
    assert нет_тега.status_code == 404
    assert нет_тега.json()["error"]["code"] == "not_found"
    откат = клиент.post(f"/api/projects/{p['id']}/values/цель/rollback",
                        json={"n": 7})
    assert откат.status_code == 404 and откат.json()["error"]["where"] == "body.n"


# ── роли ─────────────────────────────────────────────────────────────────────

def test_читатель_видит_историю_но_не_возвращает(app, клиент, хозяин, сосед):
    """Смотреть историю может всякий, кто видит проект; менять то, что попадёт
    в отчёт, — только тот, кому доверили писать."""
    p = общий_проект(app, клиент, сосед, VIEWER)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_1)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_2)

    войти(app, сосед)
    assert клиент.get(f"/api/projects/{p['id']}/values/цель/versions"
                      ).status_code == 200
    ответ = клиент.post(f"/api/projects/{p['id']}/values/цель/rollback",
                        json={"n": 1})
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "forbidden"


def test_редактор_возвращает(app, клиент, хозяин, сосед):
    p = общий_проект(app, клиент, сосед, EDITOR)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_1)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_2)

    войти(app, сосед)
    ответ = клиент.post(f"/api/projects/{p['id']}/values/цель/rollback",
                        json={"n": 1})
    assert ответ.status_code == 200, ответ.text


def test_чужой_проект_это_404(app, клиент, хозяин, сосед):
    p = проект(клиент)
    клиент.put(f"/api/projects/{p['id']}/values/цель", json=ЦЕЛЬ_1)
    войти(app, сосед)
    assert клиент.get(f"/api/projects/{p['id']}/values/цель/versions"
                      ).status_code == 404


# ── версии списка блоков ─────────────────────────────────────────────────────

def test_список_блоков_версионируется_целиком(app, клиент, хозяин):
    """Версия отдельного блока не отвечала бы на перестановку: половина правок
    живого режима меняет не значение блока, а порядок."""
    p = проект(клиент)
    том = на_томе(app, p["id"])
    том.set_blocks(БЛОКИ_1, source="manual", note="первый список")
    том.set_blocks(БЛОКИ_2, source="agent", note="приписали блок")

    текущий = клиент.get(f"/api/projects/{p['id']}/blocks").json()["blocks"]
    assert [b["key"] for b in текущий] == ["b-01", "b-02"]

    версии = клиент.get(f"/api/projects/{p['id']}/blocks/versions").json()
    assert [v["n"] for v in версии["versions"]] == [1, 2]
    assert [v["count"] for v in версии["versions"]] == [1, 2]
    assert версии["versions"][1]["note"] == "приписали блок"


def test_возврат_списка_блоков_тоже_дописывает(app, клиент, хозяин):
    p = проект(клиент)
    том = на_томе(app, p["id"])
    том.set_blocks(БЛОКИ_1, source="manual", note="первый список")
    том.set_blocks(БЛОКИ_2, source="agent", note="приписали блок")

    ответ = клиент.post(f"/api/projects/{p['id']}/blocks/rollback",
                        json={"n": 1})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["version"]["n"] == 3
    текущий = клиент.get(f"/api/projects/{p['id']}/blocks").json()["blocks"]
    assert [b["key"] for b in текущий] == ["b-01"]
    # Прошлое читается, а не только текущее.
    вторая = клиент.get(f"/api/projects/{p['id']}/blocks/versions/2").json()
    assert [b["key"] for b in вторая["blocks"]] == ["b-01", "b-02"]


def test_проект_без_списка_блоков_отвечает_пустотой(app, клиент, хозяин):
    """Пустой список — законное состояние, а не `404`: проект с шаблоном живёт
    тегами, и блоков у него нет вовсе."""
    p = проект(клиент)
    assert клиент.get(f"/api/projects/{p['id']}/blocks").json() == {"blocks": []}
    assert клиент.get(f"/api/projects/{p['id']}/blocks/versions"
                      ).json() == {"versions": []}
    ответ = клиент.post(f"/api/projects/{p['id']}/blocks/rollback",
                        json={"n": 1})
    assert ответ.status_code == 404
