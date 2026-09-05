"""
Умолчания панели агента в профиле: `default_endpoint` и `agent_overwrite`.

Эти два поля правятся тем же `PATCH /api/auth/me`, что и ник, и
отдаются тем же `me`. Проверяется здесь ровно то, что обещано в модели и в
`ProfileIn`, и ни строкой больше:

* пропущенное поле означает «не трогать», а не «стереть» — это договор формы
  правки, и держится он не докстрокой, а вот этим тестом;
* пустая строка в `default_endpoint` — «сбросить выбор» (`NULL`), потому что
  `None` уже занято смыслом «поле не пришло»;
* пресет проверяется тем же списком, что и заведение ключа: сохранённое
  умолчание, которого не бывает, — это отказ в прогоне вместо работы.

Пользователь настоящий (`c_fixtures`); подменён, как и всюду, `current_user`.
"""
from __future__ import annotations

from .c_fixtures import войти, завести, клиент, сосед, хозяин  # noqa: F401


def профиль(клиент) -> dict:
    ответ = клиент.get("/api/auth/me")
    assert ответ.status_code == 200, ответ.text
    return ответ.json()["user"]


def test_умолчания_пустые_у_нового_человека(клиент, хозяин):
    """Пока человек ничего не выбрал, выбирает сайт: «свой ключ, потом общий»."""
    я = профиль(клиент)
    assert я["default_endpoint"] is None
    assert я["agent_overwrite"] is False


def test_пресет_и_переписывание_сохраняются(клиент, хозяин):
    """Сохранённое возвращается в `me`: выбор человека живёт в службе, а не во
    вкладке браузера, иначе на втором устройстве его нет."""
    ответ = клиент.patch("/api/auth/me",
                         json={"default_endpoint": "deepseek",
                               "agent_overwrite": True})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["user"]["default_endpoint"] == "deepseek"

    я = профиль(клиент)
    assert я["default_endpoint"] == "deepseek"
    assert я["agent_overwrite"] is True


def test_пропущенное_поле_не_трогается(клиент, хозяин):
    """Тело правки описывает изменение, а не человека целиком."""
    клиент.patch("/api/auth/me", json={"default_endpoint": "deepseek",
                                       "agent_overwrite": True})
    ответ = клиент.patch("/api/auth/me", json={"agent_overwrite": False})
    assert ответ.status_code == 200, ответ.text

    я = профиль(клиент)
    assert я["default_endpoint"] == "deepseek", "пресет никто не просил стирать"
    assert я["agent_overwrite"] is False


def test_пустая_строка_сбрасывает_пресет(клиент, хозяин):
    """«Ничего не выбрано» человеку выразить надо: он вправе вернуться к
    правилу сайта."""
    клиент.patch("/api/auth/me", json={"default_endpoint": "deepseek"})
    ответ = клиент.patch("/api/auth/me", json={"default_endpoint": ""})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["user"]["default_endpoint"] is None


def test_незнакомый_пресет_не_сохраняется(клиент, хозяин):
    """Умолчание, которого не бывает, — это отказ в прогоне вместо работы."""
    ответ = клиент.patch("/api/auth/me",
                         json={"default_endpoint": "чужой-поставщик"})
    assert ответ.status_code == 400, ответ.text
    беда = ответ.json()["error"]
    assert беда["code"] == "unknown_provider"
    assert беда["where"] == "body.default_endpoint"
    assert профиль(клиент)["default_endpoint"] is None


def test_умолчания_свои_у_каждого(app, клиент, хозяин, сосед):
    """Выбор одного человека не виден другому: поле у аккаунта, а не у службы."""
    клиент.patch("/api/auth/me", json={"default_endpoint": "deepseek"})
    войти(app, сосед)
    assert профиль(клиент)["default_endpoint"] is None
