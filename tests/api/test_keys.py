"""
Ключи моделей: шифрование на диске, `last4` наружу, свой ключ против общего.

Главное, что здесь проверяется, — отрицательные утверждения: ключа нет в ответе,
ключа нет в базе, ключа нет в журнале. Их легко пообещать в докстроке и невозможно
удержать без теста: достаточно одной новой строки `беды.exception(...)` с объектом
строки внутри, чтобы ключ уехал в журнал, и заметить это без проверки нельзя.

Пользователь — настоящий (`c_fixtures`, живая регистрация); подменён, как и
всюду здесь, только `current_user`.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from api import keys
from api.keys import crypto
from api.keys.models import ModelKey

from .c_fixtures import войти, завести, клиент, сосед, хозяин  # noqa: F401

# Ключ, похожий на настоящий: у DeepSeek и OpenAI они именно такой формы.
КЛЮЧ = "sk-0123456789abcdef0123456789abcdef"
ДРУГОЙ = "sk-fedcba9876543210fedcba9876543210"


def строки(app, user_id: str) -> list[ModelKey]:
    """Всё, что лежит в базе про этого человека, включая отозванное."""
    with app.state.db.session_scope() as s:
        return list(s.scalars(select(ModelKey).where(ModelKey.user_id == user_id)))


# ── список поставщиков ───────────────────────────────────────────────────────

def test_поставщики_только_с_ключом(клиент, хозяин):
    """Пресеты, зовущие локальную команду, ключа не имеют и в список не идут."""
    ответ = клиент.get("/api/keys/providers")
    assert ответ.status_code == 200
    список = ответ.json()["providers"]
    assert "deepseek" in список and "anthropic" in список
    assert "claude_cli_proba" not in список


def test_key_source_говорит_чем_платить(клиент, хозяин, monkeypatch):
    """`key_source` на каждый пресет: `none` → `shared` → `own`.

    Экран прогона выбирает пресет ДО нажатия, и выбрать тот, которым платить
    нечем, — это отказ вместо работы. Свой ключ сайт видит списком, общий ключ
    службы не виден ниоткуда, кроме этого поля, поэтому оно и проверяется на
    всех трёх состояниях подряд, а не на одном.
    """
    источник = lambda: клиент.get("/api/keys/providers").json()["key_source"]  # noqa: E731

    assert источник()["deepseek"] == "none", "ни своего, ни общего"

    monkeypatch.setenv(keys.service.ОБЩИЙ_ПРЕФИКС + "DEEPSEEK", "sk-общий-владельца")
    assert источник()["deepseek"] == "shared"
    assert источник()["anthropic"] == "none", "общий у одного не красит соседей"

    assert клиент.post("/api/keys",
                       json={"provider": "deepseek", "key": КЛЮЧ}).status_code == 201
    assert источник()["deepseek"] == "own", "свой ключ впереди общего"
    # Ключ не уезжает вместе с источником — то же отрицательное утверждение,
    # что и во всём этом файле.
    assert КЛЮЧ not in клиент.get("/api/keys/providers").text


def test_неизвестный_поставщик(клиент, хозяин):
    ответ = клиент.post("/api/keys", json={"provider": "chatgpt", "key": КЛЮЧ})
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "unknown_provider"
    # В тексте перечислены годные — клиенту иначе нечего показать человеку.
    assert "deepseek" in ответ.json()["error"]["message"]


@pytest.mark.parametrize("плохой", ["", "коротк", "sk с пробелом", "x" * 600])
def test_ключ_кривой_формы(клиент, хозяин, плохой):
    ответ = клиент.post("/api/keys", json={"provider": "deepseek", "key": плохой})
    assert ответ.status_code in (400, 422)
    assert КЛЮЧ not in ответ.text


# ── завести и показать ───────────────────────────────────────────────────────

def test_завести_и_увидеть_только_хвост(клиент, хозяин):
    ответ = клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    assert ответ.status_code == 201, ответ.text
    строка = ответ.json()
    assert строка["provider"] == "deepseek"
    assert строка["last4"] == КЛЮЧ[-4:]
    assert строка["revoked_at"] is None
    # Ни ключа, ни шифртекста, ни имени поля под них.
    assert КЛЮЧ not in ответ.text and "ciphertext" not in ответ.text

    список = клиент.get("/api/keys").json()
    assert [к["id"] for к in список] == [строка["id"]]
    assert КЛЮЧ not in клиент.get("/api/keys").text


def test_шифртекст_в_базе_не_содержит_ключа(app, клиент, хозяин):
    """Свой ключ шифруется на диске секретом сервера."""
    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    (строка,) = строки(app, хозяин.id)

    assert КЛЮЧ not in строка.ciphertext
    # Ни куска: подстрока в шифртексте означала бы, что шифрования нет.
    assert КЛЮЧ[3:12] not in строка.ciphertext
    assert строка.ciphertext.startswith(f"{crypto.ВЕРСИЯ}:")
    assert строка.last4 == КЛЮЧ[-4:]


def test_secret_for_возвращает_исходный(app, клиент, хозяин, settings):
    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, settings, хозяин.id, "deepseek") == КЛЮЧ
        # Чужого поставщика — нет, и это не беда, а «ключа нет».
        assert keys.secret_for(s, settings, хозяин.id, "anthropic") is None


def test_чужой_ключ_не_читается(app, клиент, хозяин, сосед, settings):
    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, settings, сосед.id, "deepseek") is None


def test_другой_секрет_сервера_не_расшифровывает(app, клиент, хозяин, settings):
    """Смена `KORITSU_SECRET` делает ключи нечитаемыми — и это `None`, а не
    падение: беда службы не должна выглядеть как беда поставщика."""
    from dataclasses import replace

    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    чужие = replace(settings, secret="совсем-другой-секрет-длиной-побольше-32")
    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, чужие, хозяин.id, "deepseek") is None


# ── отзыв ────────────────────────────────────────────────────────────────────

def test_отозванный_не_возвращается(app, клиент, хозяин, settings):
    key_id = клиент.post("/api/keys",
                         json={"provider": "deepseek", "key": КЛЮЧ}).json()["id"]
    assert клиент.delete(f"/api/keys/{key_id}").status_code == 204

    assert клиент.get("/api/keys").json() == []
    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, settings, хозяин.id, "deepseek") is None

    # Строка при этом остаётся: отзыв — событие безопасности, и он переживает
    # саму запись о ключе.
    (строка,) = строки(app, хозяин.id)
    assert строка.revoked_at is not None


def test_новый_ключ_отзывает_прежний(app, клиент, хозяин, settings):
    """Два живых ключа одного поставщика — вопрос «какой сейчас работает», на
    который у человека нет ответа."""
    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    клиент.post("/api/keys", json={"provider": "deepseek", "key": ДРУГОЙ})

    живые = клиент.get("/api/keys").json()
    assert [к["last4"] for к in живые] == [ДРУГОЙ[-4:]]
    assert len(строки(app, хозяин.id)) == 2

    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, settings, хозяин.id, "deepseek") == ДРУГОЙ


def test_чужой_ключ_отозвать_нельзя(app, клиент, хозяин, сосед):
    """Чужой и несуществующий — одинаково `404`."""
    key_id = клиент.post("/api/keys",
                         json={"provider": "deepseek", "key": КЛЮЧ}).json()["id"]
    войти(app, сосед)
    assert клиент.delete(f"/api/keys/{key_id}").status_code == 404
    assert клиент.delete("/api/keys/нет-такого").status_code == 404


# ── свой ключ против общего ──────────────────────────────────────────────────

def test_resolve_key_падает_на_общий(app, клиент, хозяин, settings, monkeypatch):
    """И свой, и общий. Свой вперёд — он оплачен человеком."""
    with app.state.db.session_scope() as s:
        assert keys.resolve_key(settings, s, хозяин.id, "deepseek") is None
        assert keys.source_of(settings, s, хозяин.id, "deepseek") == "none"

    monkeypatch.setenv(keys.service.ОБЩИЙ_ПРЕФИКС + "DEEPSEEK", "sk-общий-владельца")
    with app.state.db.session_scope() as s:
        assert keys.resolve_key(settings, s, хозяин.id,
                                "deepseek") == "sk-общий-владельца"
        assert keys.source_of(settings, s, хозяин.id, "deepseek") == "shared"

    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    with app.state.db.session_scope() as s:
        assert keys.resolve_key(settings, s, хозяин.id, "deepseek") == КЛЮЧ
        assert keys.source_of(settings, s, хозяин.id, "deepseek") == "own"


def test_пустая_переменная_это_не_ключ(monkeypatch):
    """`KORITSU_PROVIDER_KEY_DEEPSEEK=` в compose означает «не задано»."""
    monkeypatch.setenv(keys.service.ОБЩИЙ_ПРЕФИКС + "DEEPSEEK", "   ")
    assert keys.common_key("deepseek") is None


# ── журнал ───────────────────────────────────────────────────────────────────

def test_ключа_нет_в_журнале(app, клиент, хозяин, settings, caplog):
    """Ни текстом, ни шифртекстом — во всём, что служба пишет за эти запросы."""
    caplog.set_level(logging.DEBUG)

    ответ = клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    клиент.get("/api/keys")
    key_id = ответ.json()["id"]
    with app.state.db.session_scope() as s:
        keys.resolve_key(settings, s, хозяин.id, "deepseek")
    клиент.delete(f"/api/keys/{key_id}")

    записано = "\n".join(з.getMessage() for з in caplog.records)
    (строка,) = строки(app, хозяин.id)
    assert КЛЮЧ not in записано
    assert КЛЮЧ[3:12] not in записано
    assert строка.ciphertext not in записано
    assert settings.secret not in записано


def test_нечитаемый_ключ_жалуется_без_шифртекста(app, клиент, хозяин, settings,
                                                 caplog):
    """Про беду сказать надо (иначе человек ищет её у поставщика), про
    содержимое строки — нельзя."""
    from dataclasses import replace

    клиент.post("/api/keys", json={"provider": "deepseek", "key": КЛЮЧ})
    (строка,) = строки(app, хозяин.id)

    caplog.set_level(logging.DEBUG)
    чужие = replace(settings, secret="совсем-другой-секрет-длиной-побольше-32")
    with app.state.db.session_scope() as s:
        assert keys.secret_for(s, чужие, хозяин.id, "deepseek") is None

    записано = "\n".join(з.getMessage() for з in caplog.records)
    assert строка.id in записано               # найти строку человек сможет
    assert строка.ciphertext not in записано   # прочитать её — нет
    assert КЛЮЧ not in записано


# ── шифрование само по себе ──────────────────────────────────────────────────

def test_шифртекст_каждый_раз_разный():
    """Fernet кладёт свой вектор инициализации: одинаковый шифртекст на
    одинаковом ключе выдавал бы, что у двоих людей ключ один и тот же."""
    первый = crypto.зашифровать("секрет" * 8, КЛЮЧ)
    второй = crypto.зашифровать("секрет" * 8, КЛЮЧ)
    assert первый != второй
    assert crypto.расшифровать("секрет" * 8, первый) == КЛЮЧ
    assert crypto.расшифровать("секрет" * 8, второй) == КЛЮЧ


def test_неизвестная_версия_схемы():
    """Метка версии впереди затем и стоит, чтобы чужую схему не пытались читать
    этой."""
    with pytest.raises(crypto.КлючНеЧитается):
        crypto.расшифровать("секрет" * 8, "v99:" + "x" * 40)
    with pytest.raises(crypto.КлючНеЧитается):
        crypto.расшифровать("секрет" * 8, "без-версии")


def test_ключ_от_секрета_и_соли_вместе():
    """Смена соли делает ключи нечитаемыми — значит, соль правда участвует."""
    сохранённая = crypto.СОЛЬ
    шифр = crypto.зашифровать("секрет" * 8, КЛЮЧ)
    try:
        crypto.СОЛЬ = "другая-соль".encode()
        crypto._кэш.clear()
        with pytest.raises(crypto.КлючНеЧитается):
            crypto.расшифровать("секрет" * 8, шифр)
    finally:
        crypto.СОЛЬ = сохранённая
        crypto._кэш.clear()
    assert crypto.расшифровать("секрет" * 8, шифр) == КЛЮЧ


def test_хвост_короткого_ключа():
    assert crypto.хвост("abcdefgh") == "efgh"
    assert crypto.хвост("ab") == "ab"


# ── доступ ───────────────────────────────────────────────────────────────────

def test_без_входа_401(app, клиент):
    app.dependency_overrides.clear()
    assert клиент.get("/api/keys").status_code == 401
    assert клиент.post("/api/keys",
                       json={"provider": "deepseek", "key": КЛЮЧ}).status_code == 401
