"""
Цепочка миграций: одна голова, вверх с нуля, вниз до нуля и снова вверх.

Проверяется здесь то, чего не видно ни в одном другом тесте набора. Все они
работают на базе, поднятой `create_app`, то есть один раз выполненным
`upgrade head` на пустом файле, — а на живом томе миграция ложится на базу с
данными, и ровно там она и ломается. Три вещи, которые тут закрепляются:

* **голова одна.** Ветвей в цепочке несколько; вторая голова означает, что
  `upgrade head` падает с `Multiple head revisions are present`, а `create_app`
  зовёт его при сборке — то есть служба не поднимается вовсе;
* **схема и модели сходятся.** `alembic check` пишет «no new operations», если
  `Base.metadata` описывает ровно то, что стоит в базе. Расхождение означает
  забытую миграцию, и обнаруживается оно иначе — пятисоткой на живом сайте, в
  запросе к колонке, которой нет;
* **вниз тоже работает.** Откат нужен ровно один раз — когда выкат оказался
  плохим, — и проверять его в этот момент поздно. На SQLite это не формальность:
  `batch_alter_table` пересоздаёт таблицу, и откат, который не умеет назвать
  снимаемое ограничение, падает молча до тех пор, пока его не позовут.

Зовётся Alembic **программно** (`alembic.command`), а не через оболочку: shell
тянет за собой `alembic.ini`, `PYTHONPATH` и рабочий каталог, то есть проверял
бы окружение машины, а не цепочку. Настройки приходят те же, что у службы, —
через `db.alembic_config`.
"""
from __future__ import annotations

import io

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text

from api import Settings
from api.db import Db, alembic_config, current_revision

# Порядок ревизий, включая слияние ветвей. Список пишется руками намеренно: он и есть
# утверждение теста — «цепочка выглядит вот так», — а не пересказ того, что
# сейчас лежит в каталоге.
ЦЕПОЧКА = (
    "0001_root",                 # якорь: общий корень для трёх ветвей
    "5f7bb4acb03d",              # users, email_tokens, sessions, лимиты
    "70d001e82586",              # workspaces, members, projects
    "d89510c0e548",              # слияние двух ветвей
    "be5b0b0dd8f6",              # model_keys
    "c3a71f0d94e6",              # model_keys.user_id → users.id CASCADE
    "3cb2572ff488",              # jobs, job_events
    "7f7799c6dac1",              # api_tokens, security_events, is_admin
    "eef3027c39f2",              # notifications
    "a1c47b30f5e2",              # users.blocked_at (блокировка аккаунта)
    "f5872fd9890d",              # users.nickname, users.nickname_key
    "b2d7c1a54e39",              # templates, users.default_endpoint/overwrite
    "c8f1a2b46d73",              # projects.module, project_runs, project_templates
    "e7a4c19b3d02",              # workspace_members.status (приглашения)
    "f3d6a08b5c14",              # project_diagrams (код и параметры схем)
)

ГОЛОВА = ЦЕПОЧКА[-1]


@pytest.fixture
def том(tmp_path) -> Settings:
    """Чистый временный том под свою базу. У каждого теста здесь свой."""
    return Settings.for_tests(tmp_path / "том")


@pytest.fixture
def cfg(том):
    return alembic_config(том)


def головы_базы(settings: Settings) -> set[str]:
    """Какие ревизии стоят на базе. Множество, а не одна: пока ветви не сведены,
    их в `alembic_version` честно две — то самое состояние, в котором ветви
    живут до слияния."""
    from alembic.runtime.migration import MigrationContext

    db = Db(settings)
    try:
        with db.engine.connect() as conn:
            return set(MigrationContext.configure(conn).get_current_heads())
    finally:
        db.dispose()


def таблицы(settings: Settings) -> set[str]:
    """Имена таблиц в базе. `sqlite_*` — служебные самой SQLite, не наши."""
    db = Db(settings)
    try:
        with db.engine.connect() as conn:
            строки = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"))
            return {имя for (имя,) in строки if not имя.startswith("sqlite_")}
    finally:
        db.dispose()


# ── голова ───────────────────────────────────────────────────────────────────

def test_голова_ровно_одна(cfg):
    """Вторая голова — это служба, которая не поднимается: `create_app` зовёт
    `upgrade head` при сборке, и на двух головах он падает."""
    головы = ScriptDirectory.from_config(cfg).get_heads()
    assert головы == [ГОЛОВА], f"голов не одна: {головы}"


def test_цепочка_та_самая(cfg):
    """Порядок ревизий от корня до головы. Слияние — с двумя родителями."""
    скрипты = ScriptDirectory.from_config(cfg)
    все = {s.revision for s in скрипты.walk_revisions()}
    assert все == set(ЦЕПОЧКА), f"лишние или пропавшие: {все ^ set(ЦЕПОЧКА)}"

    слияние = скрипты.get_revision("d89510c0e548")
    assert set(слияние.down_revision) == {"5f7bb4acb03d", "70d001e82586"}


# ── вверх, проверка, вниз, снова вверх ───────────────────────────────────────

def test_с_нуля_до_головы(том, cfg):
    """`upgrade head` на пустом томе. Каталога тома ещё нет — его заводит сама
    миграция (`ensure_volume`), иначе SQLite падает «unable to open database»."""
    command.upgrade(cfg, "head")
    assert current_revision(том) == ГОЛОВА
    assert {"users", "sessions", "workspaces", "projects", "model_keys",
            "jobs", "job_events"} <= таблицы(том)


def test_check_не_видит_новых_операций(том, cfg):
    """`alembic check`: модели и база описывают одно и то же.

    Расхождение здесь — это забытая миграция, и без этой проверки оно всплывает
    пятисоткой на живом сайте, в запросе к колонке, которой в базе нет.

    Вывод перехватывается через `cfg.stdout`, а не `capsys`: `alembic.Config`
    запоминает `sys.stdout` в умолчании аргумента, то есть настоящий поток, ещё
    до того, как pytest успевает его подменить.
    """
    command.upgrade(cfg, "head")
    cfg.stdout = io.StringIO()
    command.check(cfg)                       # падает сама, если что-то новое
    assert "No new upgrade operations detected" in cfg.stdout.getvalue()


def test_вниз_до_нуля_и_снова_вверх(том, cfg):
    """Откат нужен один раз — когда выкат оказался плохим. Проверять его в этот
    момент поздно."""
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    assert current_revision(том) is None
    осталось = таблицы(том)
    # `alembic_version` остаётся всегда: это её собственная бухгалтерия.
    assert осталось <= {"alembic_version"}, f"после отката осталось: {осталось}"

    command.upgrade(cfg, "head")
    assert current_revision(том) == ГОЛОВА


def test_каждая_ступень_по_одной(том, cfg):
    """Вверх по одной ревизии: не только «head», но и каждый промежуточный шаг.

    Разница видна на слиянии: `upgrade head` перепрыгивает через него одним
    движением, а живой выкат ставит ревизии по очереди, и ветвь, не собирающаяся
    в одиночку, обнаруживается только так.
    """
    ожидаемые = [
        {"0001_root"},
        {"5f7bb4acb03d"},
        # Две головы разом — то самое состояние, ради которого заведено
        # слияние: обе ветви подняты, сливающей ревизии ещё нет.
        {"5f7bb4acb03d", "70d001e82586"},
        {"d89510c0e548"},
        {"be5b0b0dd8f6"},
        {"c3a71f0d94e6"},
        {"3cb2572ff488"},
        {"7f7799c6dac1"},
        {"eef3027c39f2"},
        {"a1c47b30f5e2"},
        {"f5872fd9890d"},
        {"b2d7c1a54e39"},
        {"c8f1a2b46d73"},
        {"e7a4c19b3d02"},
        {ГОЛОВА},
    ]
    for ревизия, головы in zip(ЦЕПОЧКА, ожидаемые):
        command.upgrade(cfg, ревизия)
        assert головы_базы(том) == головы, ревизия


def test_каждая_ступень_вниз_по_одной(том, cfg):
    """Вниз по одной ревизии, от головы до нуля.

    `downgrade base` (тест выше) проверяет, что цепочка снимается **целиком**, и
    останавливается на первом же падении — то есть про ступени за ним не
    говорит ничего. Здесь спуск разобран по шагам: после каждого проверяется,
    какая ревизия осталась стоять. Ступень, которая снимается, но забывает
    сказать об этом `alembic_version` (или снимает вместе с собой лишнюю
    таблицу), видна только так.

    Слияние спускается в две головы разом — то же состояние, в котором ветви
    жили до него, только пройденное в обратную сторону.
    """
    command.upgrade(cfg, "head")

    ожидаемые = [
        ("7f7799c6dac1", {"7f7799c6dac1"}),        # снята ступень уведомлений
        ("3cb2572ff488", {"3cb2572ff488"}),        # снята ступень ключей и журнала
        ("c3a71f0d94e6", {"c3a71f0d94e6"}),        # снята очередь
        ("be5b0b0dd8f6", {"be5b0b0dd8f6"}),        # снят каскад ключей моделей
        ("d89510c0e548", {"d89510c0e548"}),        # снята таблица ключей моделей
        ("70d001e82586", {"5f7bb4acb03d", "70d001e82586"}),   # слияние разошлось
    ]
    for куда, головы in ожидаемые:
        command.downgrade(cfg, куда)
        assert головы_базы(том) == головы, куда

    command.downgrade(cfg, "base")
    assert головы_базы(том) == set()
    assert таблицы(том) <= {"alembic_version"}


# ── то, ради чего заведены миграции ключей и уведомлений ─────────────────────

def test_ступень_ключей_и_журнала_откатывается_в_одиночку(том, cfg):
    """Ступень ключей и журнала снимается одна: нет ни ключей, ни журнала,
    ни колонок у `users`.

    Колонки проверяются отдельно от таблиц: `is_admin` и `limits` добавлены
    через `batch_alter_table`, то есть таблица `users` при откате
    пересоздаётся целиком — и потерять на этом можно не свои колонки, а чужие.
    """
    command.upgrade(cfg, "7f7799c6dac1")
    command.downgrade(cfg, "-1")

    assert current_revision(том) == "3cb2572ff488"
    осталось = таблицы(том)
    assert "api_tokens" not in осталось and "security_events" not in осталось
    assert {"users", "jobs", "job_events", "projects"} <= осталось

    db = Db(том)
    try:
        with db.engine.connect() as conn:
            столбцы = {строка[1] for строка in
                       conn.execute(text("PRAGMA table_info(users)"))}
    finally:
        db.dispose()
    assert "is_admin" not in столбцы and "limits" not in столбцы
    # Чужое пережило пересборку таблицы: без этого откат «своего» уносил бы
    # аккаунты вместе с планом и замком входа.
    assert {"email", "password_hash", "plan", "failed_logins"} <= столбцы


def test_ступень_уведомлений_откатывается_в_одиночку(том, cfg):
    """Ступень уведомлений снимается одна: таблицы нет, чужие целы.

    Поднимаемся именно до неё, а не до `head`: поверх легли ещё три
    ревизии, и «голова минус один» с тех пор снимает не эту ступень, а
    последнюю. Ревизия названа явно — тест про **эту** ступень, а не про то,
    что лежит сверху сегодня.
    """
    command.upgrade(cfg, "eef3027c39f2")
    command.downgrade(cfg, "-1")

    assert current_revision(том) == "7f7799c6dac1"
    осталось = таблицы(том)
    assert "notifications" not in осталось
    assert {"users", "jobs", "api_tokens", "security_events"} <= осталось


def test_уведомление_уходит_с_человеком(том, cfg):
    """Удалили аккаунт — удалено всё, что с ним связано. Колокольчик тоже.

    Поведение на живой базе, а не описание в схеме: `PRAGMA foreign_keys` в
    SQLite выключен по умолчанию и включается на каждом соединении
    (`db.make_engine`).
    """
    command.upgrade(cfg, "head")
    db = Db(том)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, nickname, nickname_key, "
                "password_hash, plan, totp_enabled, failed_logins, "
                "is_admin, limits, created_at, updated_at) "
                "VALUES ('u1', 'кто@пример.рф', 'кто', 'кто', 'хеш', "
                "'free', 0, 0, 0, '{}', "
                "'2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
            conn.execute(text(
                "INSERT INTO notifications (id, user_id, kind, data, "
                "created_at, updated_at) VALUES ('n1', 'u1', 'job_finished', "
                "'{}', '2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = 'u1'"))
            осталось = conn.execute(
                text("SELECT count(*) FROM notifications")).scalar()
        assert осталось == 0
    finally:
        db.dispose()


# ── то, ради чего заведена миграция слияния ──────────────────────────────────

def test_ключ_на_users_с_каскадом(том, cfg):
    """`model_keys.user_id` смотрит на `users.id` и уходит вместе с человеком.

    Удалили аккаунт — удалено всё, что с ним связано. Без каскада
    шифртексты ушедшего остались бы строками, у которых больше нет владельца.
    """
    command.upgrade(cfg, "head")
    db = Db(том)
    try:
        with db.engine.connect() as conn:
            ключи = list(conn.execute(text("PRAGMA foreign_key_list(model_keys)")))
        assert len(ключи) == 1, ключи
        строка = ключи[0]
        assert строка[2] == "users" and строка[3] == "user_id"
        assert строка[4] == "id" and строка[6] == "CASCADE"

        # Индекс пережил пересборку таблицы: `batch_alter_table`
        # копирует таблицу целиком, и потерянный индекс здесь означал бы
        # медленный список ключей, о котором никто бы не узнал.
        with db.engine.connect() as conn:
            индексы = {имя for (имя,) in conn.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='model_keys'"))}
        assert "ix_model_keys_user_provider" in индексы
    finally:
        db.dispose()


def test_каскад_работает_на_живой_базе(том, cfg):
    """Не описание в схеме, а поведение: удалили строку `users` — ключей нет.

    Проверяется через `Db`, а не через голое соединение: `PRAGMA foreign_keys`
    в SQLite выключен по умолчанию и включается на каждом соединении
    (`db.make_engine`), поэтому «каскад описан» и «каскад работает» — два разных
    утверждения, и второе дороже.
    """
    command.upgrade(cfg, "head")
    db = Db(том)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, nickname, nickname_key, "
                "password_hash, plan, totp_enabled, failed_logins, "
                "created_at, updated_at) "
                "VALUES ('u1', 'кто@пример.рф', 'кто', 'кто', 'хеш', "
                "'free', 0, 0, "
                "'2026-09-03 00:00:00', '2026-09-03 00:00:00')"))
            conn.execute(text(
                "INSERT INTO model_keys (id, user_id, provider, ciphertext, "
                "last4, created_at, updated_at) "
                "VALUES ('k1', 'u1', 'deepseek', 'v1:шифр', 'cdef', "
                "'2026-09-03 00:00:00', '2026-09-03 00:00:00')"))
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = 'u1'"))
            осталось = conn.execute(text(
                "SELECT count(*) FROM model_keys")).scalar()
        assert осталось == 0
    finally:
        db.dispose()


def test_откат_снимает_ключ(том, cfg):
    """Шаг с внешним ключом откатывается: ключа нет, таблица цела.

    Спуск назван ревизией, а не `-1`: головой цепочки этот шаг перестал быть,
    как только к ней прибавилась очередь, и `-1` проверял бы уже чужой откат.
    """
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "be5b0b0dd8f6")

    assert current_revision(том) == "be5b0b0dd8f6"
    db = Db(том)
    try:
        with db.engine.connect() as conn:
            ключи = list(conn.execute(text("PRAGMA foreign_key_list(model_keys)")))
            столбцы = {строка[1] for строка in
                       conn.execute(text("PRAGMA table_info(model_keys)"))}
    finally:
        db.dispose()
    assert ключи == []
    assert {"user_id", "provider", "ciphertext", "last4"} <= столбцы


# ── то, ради чего заведена миграция очереди ──────────────────────────────────

def test_очередь_откатывается_в_одиночку(том, cfg):
    """Шаг очереди снимается один: обеих её таблиц нет, чужие целы.

    Откат головы — первое, что делают, когда выкат оказался плохим, и проверять
    его после выката поздно.
    """
    # Поднимаемся до самой очереди, а не до головы: за ней теперь стоят чужие
    # ступени, и «шаг назад от головы» проверял бы уже не её. Тест про то, что
    # снимается именно ступень очереди, — значит и снимать надо её.
    command.upgrade(cfg, "3cb2572ff488")
    command.downgrade(cfg, "-1")

    assert current_revision(том) == "c3a71f0d94e6"
    осталось = таблицы(том)
    assert "jobs" not in осталось and "job_events" not in осталось
    assert {"users", "projects", "model_keys"} <= осталось


def test_задание_уходит_с_человеком_и_событие_с_заданием(том, cfg):
    """Не описание каскада в схеме, а его поведение на живой базе.

    Удалили аккаунт — удалено всё, что с ним связано. Задание несёт
    в `payload` работу человека, а событие — текст, который ему написала модель;
    остаться без владельца не должно ни то, ни другое. Проверяется через `Db`, а
    не голым соединением: `PRAGMA foreign_keys` в SQLite выключен по умолчанию.
    """
    command.upgrade(cfg, "head")
    db = Db(том)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, nickname, nickname_key, "
                "password_hash, plan, totp_enabled, failed_logins, "
                "created_at, updated_at) "
                "VALUES ('u1', 'кто@пример.рф', 'кто', 'кто', 'хеш', "
                "'free', 0, 0, "
                "'2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
            conn.execute(text(
                "INSERT INTO jobs (id, user_id, project_id, kind, status, "
                "payload, cancel_requested, last_seen_at, spent_units, "
                "attempt, created_at, updated_at) "
                "VALUES ('j1', 'u1', NULL, 'probe', 'done', '{}', 0, "
                "'2026-09-04 00:00:00', 0, 0, "
                "'2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
            conn.execute(text(
                "INSERT INTO job_events (id, job_id, seq, kind, data, "
                "created_at) VALUES ('e1', 'j1', 1, 'text', '{}', "
                "'2026-09-04 00:00:00')"))
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = 'u1'"))
            заданий = conn.execute(text("SELECT count(*) FROM jobs")).scalar()
            событий = conn.execute(
                text("SELECT count(*) FROM job_events")).scalar()
        assert (заданий, событий) == (0, 0)
    finally:
        db.dispose()


def test_два_события_с_одним_номером_не_ложатся(том, cfg):
    """Уникальность `(job_id, seq)` — заслон от двух писателей одного задания.

    Без неё два процесса, взявшие один номер, разъехались бы молча, а клиент
    увидел бы в потоке дыру там, где на самом деле лежат два события.
    """
    from sqlalchemy.exc import IntegrityError

    command.upgrade(cfg, "head")
    db = Db(том)
    try:
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, nickname, nickname_key, "
                "password_hash, plan, totp_enabled, failed_logins, "
                "created_at, updated_at) "
                "VALUES ('u1', 'кто@пример.рф', 'кто', 'кто', 'хеш', "
                "'free', 0, 0, "
                "'2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
            conn.execute(text(
                "INSERT INTO jobs (id, user_id, project_id, kind, status, "
                "payload, cancel_requested, last_seen_at, spent_units, "
                "attempt, created_at, updated_at) "
                "VALUES ('j1', 'u1', NULL, 'probe', 'running', '{}', 0, "
                "'2026-09-04 00:00:00', 0, 0, "
                "'2026-09-04 00:00:00', '2026-09-04 00:00:00')"))
            conn.execute(text(
                "INSERT INTO job_events (id, job_id, seq, kind, data, "
                "created_at) VALUES ('e1', 'j1', 1, 'text', '{}', "
                "'2026-09-04 00:00:00')"))
        with pytest.raises(IntegrityError):
            with db.engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO job_events (id, job_id, seq, kind, data, "
                    "created_at) VALUES ('e2', 'j1', 1, 'text', '{}', "
                    "'2026-09-04 00:00:00')"))
    finally:
        db.dispose()
