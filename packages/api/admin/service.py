"""
service — что показывает админка и как в базу попадает журнал безопасности.

Две несвязанные обязанности в одном модуле, и это намеренно: обе про одно
место — таблицу `security_events`. `событие` её пишет, `события` читает, и
живут они рядом, чтобы форма записи и форма показа не разошлись.

**`событие` не имеет права уронить запрос.** Журнал — это наблюдение, а не
работа: беда при записи события отказа входа не должна превращать отказ входа в
пятисотку. Поэтому запись обёрнута, а её беда уходит в технический журнал.

**Событие копится в запросе и пишется после ответа.** Не потому, что так
быстрее, а потому, что иначе нельзя. Писать его сессией запроса не годится:
события случаются там, где запрос кончается отказом, а отказ откатывает сессию
запроса (`db.session` ловит исключение и делает `rollback`) — и в журнале
безопасности не оказалось бы ровно тех строк, ради которых он заведён. Писать
своим соединением прямо на месте не годится тоже: на SQLite это второй писатель
при открытой транзакции первого, то есть пять секунд ожидания и
`database is locked` (проверено: вход с записью сессии и события разом).

Отсюда две половины. `записать` кладёт событие в список на `request.state`
(`СОБЫТИЯ`), а middleware `ЖурналБезопасности` — когда запрос отработал целиком
и сессия закрыта — пишет накопленное одной своей транзакцией. Список живёт в
`scope["state"]`, то есть один на запрос, как `request_id` и `user_id` журнала.

**Секретов в `detail` не бывает.** Ни пароля, ни строки ключа, ни значения
cookie, ни почты (почта — то, что при удалении аккаунта обязано исчезнуть).
Следит за этим `_почистить`, а не обещание: место, пишущее событие, однажды
передаст `token=…`, и лучше, если это отсечёт код.

**Расход и квота в списке людей — считаются, а не хранятся.** Расход — сумма
`jobs.spent_units` за календарный месяц, и складывает её не этот модуль, а
`jobs.service.расход_за_месяц`: то же число называет человеку `GET /api/usage`
(`runs.limits`), и два запроса, написанные порознь, разошлись бы молча. Квота —
обход каталогов владельца (`projects.bytes_used`). Хранить их полями значило бы
завести два счётчика, которые обязаны совпадать с правдой, и не совпадали бы:
первый же прогон, упавший до записи итога, оставил бы расход, которого не было.
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import now
from ..errors import ApiError
from ..settings import Settings
from .models import SecurityEvent

FORBIDDEN = "forbidden"

# Под каким именем события копятся в `request.state` до конца запроса.
СОБЫТИЯ = "события_безопасности"

# Что не пишется в `detail` ни при каких обстоятельствах. По имени поля, а не
# по содержимому: угадывать секрет в значении — гиблое дело, а назвать поле
# `token` и положить туда не токен ещё никто не догадался.
ЗАПРЕЩЁННЫЕ_ПОЛЯ = ("password", "token", "secret", "cookie", "email", "key")

# Сколько событий отдаётся за раз по умолчанию и максимум. Потолок нужен: без
# него первый же запрос админки на живой базе тянет в память годовой журнал.
СОБЫТИЙ_ПО_УМОЛЧАНИЮ = 100
СОБЫТИЙ_МАКСИМУМ = 1000

# За сколько дней считается сводка для графиков и докуда её можно растянуть.
# Потолок тот же по смыслу, что у событий: без него запрос `?days=100000`
# заставляет службу перебрать все задания за всю жизнь ради одного графика.
СВОДКА_ДНЕЙ_ПО_УМОЛЧАНИЮ = 30
СВОДКА_ДНЕЙ_МАКСИМУМ = 365

_беды = logging.getLogger("api.error")


# ── запись ───────────────────────────────────────────────────────────────────

def _почистить(поля: dict) -> dict:
    """Выбросить из подробностей всё, чему в журнале не место."""
    return {k: v for k, v in поля.items()
            if not any(запрет in k.lower() for запрет in ЗАПРЕЩЁННЫЕ_ПОЛЯ)}


def записать(request, kind: str, *, user_id: str | None = None,
             ip: str = "", **detail) -> None:
    """Отложить событие безопасности до конца запроса. Не бросает никогда.

    `request` нужен ради двух вещей: адреса клиента и места, куда отложить.
    Без него (вызов из консольной команды, из теста без приложения) событие
    просто не пишется — таблица привязана к приложению, а не к процессу.
    """
    app = getattr(request, "app", None)
    if getattr(getattr(app, "state", None), "db", None) is None:
        return
    try:
        if not ip:
            from ..accounts.service import client_ip
            ip = client_ip(request, app.state.settings)
        очередь = getattr(request.state, СОБЫТИЯ, None)
        if очередь is None:
            очередь = []
            setattr(request.state, СОБЫТИЯ, очередь)
        очередь.append({"user_id": user_id or None, "ip": ip or "",
                        "kind": kind[:32], "detail": _почистить(detail)})
    except Exception:                                        # noqa: BLE001
        # Наблюдение не имеет права ломать работу — см. докстроку модуля.
        _беды.exception("не удалось записать событие безопасности %s", kind)


def сбросить(scope) -> None:
    """Записать накопленное за запрос. Зовёт middleware, больше никто.

    Одной транзакцией на запрос, а не по строке: событий за запрос бывает одно,
    редко два, и второе соединение к SQLite стоит дороже самой записи.
    """
    состояние = scope.get("state") or {}
    очередь = состояние.get(СОБЫТИЯ)
    if not очередь:
        return
    состояние[СОБЫТИЯ] = []
    try:
        with scope["app"].state.db.session_scope() as s:
            for поля in очередь:
                s.add(SecurityEvent(**поля))
    except Exception:                                        # noqa: BLE001
        _беды.exception("не удалось записать события безопасности")


class ЖурналБезопасности:
    """Middleware, дописывающий события в базу — после того, как всё кончилось.

    **Голый ASGI, а не `@app.middleware("http")`**, и это не стиль, а
    единственный работающий способ. `BaseHTTPMiddleware` (то, во что
    превращается декоратор) возвращает управление, как только ответ **начал**
    отправляться, — а сессия запроса к этому моменту ещё не коммитнута:
    зависимость `db.session` закрывается глубже, уже после. Запись своим
    соединением в этот миг встаёт на замок SQLite вместе с той самой сессией,
    которую она ждёт, и обе стоят пять секунд до `database is locked`
    (наблюдалось на регистрации: запрос 5,1 с и потерянное событие). Голый
    ASGI-слой ждёт внутреннее приложение целиком, то есть и закрытие сессии.

    **Снаружи заслона CSRF.** Заслон, отказавший запросу, до обработчика не
    доходит и своим `return` минует всё, что стоит внутри него, — включая этот
    сброс, а событие об отказе писать надо именно тогда. Middleware,
    добавленный позже, оказывается снаружи, поэтому `install` зовётся после
    `csrf.install`.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            сбросить(scope)


def install(app) -> None:
    """Повесить сброс журнала. Зовётся из `create_app` — см. `ЖурналБезопасности`."""
    app.add_middleware(ЖурналБезопасности)


def событие(request, kind: str, **поля) -> None:
    """Тот же вызов, что у `accounts.service.событие`, но в таблицу.

    Форма аргументов повторена нарочно: оба журнала пишутся одним вызовом из
    одного места, и разные подписи означали бы, что однажды в один из них
    попадёт не то. `user` и `ip` вынимаются из полей — они колонки, а не
    подробности, и искать «все события этого человека» по JSON нельзя.
    """
    поля = dict(поля)
    записать(request, kind, user_id=поля.pop("user", None),
             ip=str(поля.pop("ip", "") or ""), **поля)


# ── чтение ───────────────────────────────────────────────────────────────────

def события(s: Session, *, kind: str | None = None,
            limit: int = СОБЫТИЙ_ПО_УМОЛЧАНИЮ) -> list[SecurityEvent]:
    """Последние события, новые сверху; при желании — только одного вида."""
    запрос = select(SecurityEvent).order_by(SecurityEvent.created_at.desc(),
                                            SecurityEvent.id.desc())
    if kind:
        запрос = запрос.where(SecurityEvent.kind == kind)
    return list(s.scalars(запрос.limit(max(1, min(limit, СОБЫТИЙ_МАКСИМУМ)))))


def карточка_события(строка: SecurityEvent) -> dict:
    return {"id": строка.id, "user_id": строка.user_id, "ip": строка.ip,
            "kind": строка.kind, "detail": dict(строка.detail or {}),
            "created_at": строка.created_at.isoformat()
            if строка.created_at else None}


# ── люди ─────────────────────────────────────────────────────────────────────

def лимит(user, ключ: str, умолчание):
    """Личное значение лимита, если владелец его поставил, иначе умолчание.

    Единственный способ прочитать `users.limits`, и заводить второй нельзя.
    Поле — мешок JSON, а не колонка на лимит, потому что лимиты ещё не
    закрыты владельцем (цены и планы он решает вместе): колонка на каждый
    означала бы миграцию на каждое его решение. Читают его те, кто лимит и
    применяет: расход модели (`monthly_units`) и место на томе
    (`quota_bytes`).

        месячный = admin.service.лимит(user, "monthly_units",
                                       settings.free_monthly_units)
    """
    значение = (getattr(user, "limits", None) or {}).get(ключ)
    return умолчание if значение is None else значение


def карточка_человека(user, settings: Settings, *, bytes_used: int,
                      spent_units: int) -> dict:
    """Что видит владелец в списке людей.

    Ник рядом с почтой: людей владелец различает по нику, а почта
    осталась тем, по чему человека находят и приглашают.

    Почта здесь есть, и это не противоречие. Список читает владелец службы,
    которому иначе некого опознать (UUID не говорит ничего), а в **журнал** она
    по-прежнему не попадает: журнал переживает удаление аккаунта, а эта
    страница показывает то, что в базе есть прямо сейчас.

    `quota_bytes` — то самое число, по которому отказывают в загрузке файла
    (`materials.service.проверить_квоту`), а не «настройка службы»: считает его
    одна дверь `runs.limits.квота_человека` — план из справочника, поверх него
    личный лимит. Пока их было два, карточка обещала одно, а отказ приходил по
    другому.
    """
    from ..runs.limits import квота_человека                    # noqa: PLC0415

    def iso(момент):
        return момент.isoformat() if момент is not None else None

    return {
        "id": user.id,
        "email": user.email,
        "nickname": user.nickname,
        "plan": user.plan,
        "is_admin": bool(user.is_admin),
        "limits": dict(user.limits or {}),
        "quota_bytes": квота_человека(settings, user),
        "bytes_used": bytes_used,
        "spent_units": spent_units,
        "email_confirmed": user.email_confirmed_at is not None,
        "created_at": iso(user.created_at),
        "deleted_at": iso(user.deleted_at),
        "blocked_at": iso(user.blocked_at),
    }


def люди(s: Session, settings: Settings, *, limit: int = 200) -> list[dict]:
    """Список людей с планом, квотой и расходом за месяц."""
    from ..accounts.models import User
    from ..jobs.service import расход_за_месяц
    from ..projects import bytes_used

    расход = расход_за_месяц(s)
    строки = list(s.scalars(select(User).order_by(User.created_at.desc())
                            .limit(max(1, min(limit, 1000)))))
    return [карточка_человека(u, settings, bytes_used=bytes_used(s, settings, u.id),
                              spent_units=расход.get(u.id, 0))
            for u in строки]


def поправить(s: Session, user_id: str, *, plan: str | None = None,
              is_admin: bool | None = None, limits: dict | None = None,
              blocked: bool | None = None, request=None):
    """Сменить план, права владельца, личные лимиты и блокировку. Даёт строку.

    `limits` присваивается целиком, а не сливается: правка «поставь квоту»,
    молча сохраняющая прошлый месячный лимит, однажды сохранит тот, который
    владелец как раз убирал. Целиком — значит видно, что осталось.

    **План проверяется по справочнику** (`runs.limits.ПЛАНЫ`):
    неизвестный — `400 unknown_plan`. До справочника план вписывался свободной
    строкой, и «pro » с пробелом молча оставлял человека на потолке `free`.

    **Блокировка отзывает все сессии человека, и это не украшение.** Без
    отзыва заблокированный доработал бы в уже открытой вкладке до истечения
    cookie; проверка в `current_user` его, конечно, не пустит, но сессия,
    которую никто не гасил, — это строка в базе, по которой он числится
    вошедшим. Разблокировка сессий не возвращает: войти заново — одно действие,
    а воскрешать чужие открытые вкладки служба не должна.

    `request` нужен только для события безопасности; без него (вызов из
    консоли или из теста без приложения) правка идёт молча — журнал привязан к
    запросу, а не к процессу (`записать`).
    """
    from ..accounts.models import User
    from ..accounts.service import отозвать_все
    from ..accounts.service import событие as в_оба_журнала
    from ..runs.limits import UNKNOWN_PLAN, известен, нормальный_план
    from .models import ACCOUNT_BLOCKED, ACCOUNT_UNBLOCKED

    user = s.get(User, user_id)
    if user is None:
        raise ApiError("not_found", "User not found", 404, where="path.user_id")
    if plan is not None:
        if not известен(plan):
            raise ApiError(UNKNOWN_PLAN, f"Unknown plan {plan!r}", 400,
                           where="body.plan")
        user.plan = нормальный_план(plan)
    if is_admin is not None:
        user.is_admin = bool(is_admin)
    if limits is not None:
        user.limits = dict(limits)
    if blocked is not None and blocked != (user.blocked_at is not None):
        user.blocked_at = now() if blocked else None
        if blocked:
            отозвать_все(s, user)
        # Через `accounts.service.событие`, а не через здешнее: то пишет в
        # оба журнала разом (stderr и таблица), и второго места, где событие
        # превращается в запись, у службы нет.
        в_оба_журнала(request,
                      ACCOUNT_BLOCKED if blocked else ACCOUNT_UNBLOCKED,
                      user=user.id)
    return user


EMAIL_TAKEN = "email_taken"


def завести_человека(s: Session, settings: Settings, *, email: str,
                     plan: str | None = None, nickname: str | None = None,
                     request=None) -> tuple[object, str]:
    """Завести аккаунт руками владельца. Даёт `(строка, ссылка сброса)`.

    Писем служба не шлёт, поэтому человека заводит владелец, а ссылку отдаёт
    ему сам — один раз, как строку ключа.

    **Пароля у такого аккаунта нет.** Не пустой и не общий: в `password_hash`
    ложится хеш случайной строки, которой не знает никто, включая нас. Пустое
    поле означало бы вход без пароля, а известное умолчание («koritsu123») —
    вход по угаданному паролю в каждый заведённый так аккаунт.

    **Почта считается подтверждённой сразу.** Владелец знает, кого заводит, а
    подтверждение всё равно случится: ссылку сброса человек открывает из своего
    ящика. Требовать сверх этого ещё и подтверждения значило бы послать письмо,
    которого служба не шлёт.

    **Ссылка — обычный сброс пароля** (`accounts.выдать_токен`, назначение
    `RESET`), тот же час жизни и тот же маршрут `/auth/reset`. Второго
    механизма «приглашение» не заводится: он отличался бы от сброса только
    именем, и однажды один из двух починили бы, а другой нет.

    Дубль почты — `409 email_taken`, и здесь это не утечка (в отличие от
    открытой регистрации, правило 1): спрашивает владелец службы, который и
    так видит весь список людей.
    """
    from ..accounts import mail
    from ..accounts.models import RESET, User
    from ..accounts.service import (выдать_токен, годная_почта, ключ_ника,
                                    новый_токен, нормальная_почта,
                                    проверить_ник, создать_пользователя,
                                    требовать_свободный_ник)
    from ..accounts.service import событие as в_оба_журнала
    from ..runs.limits import UNKNOWN_PLAN, известен, нормальный_план
    from .models import USER_CREATED_BY_ADMIN

    почта = нормальная_почта(email)
    if not годная_почта(почта):
        raise ApiError("validation_failed", "Not a valid email address", 422,
                       where="body.email")
    # По всей таблице, а не по живым: почту держит уникальный ключ базы, и
    # аккаунт в корзине (`deleted_at`) отдал бы `IntegrityError` и пятисотку
    # вместо внятного отказа.
    if s.scalar(select(User).where(User.email == почта)) is not None:
        raise ApiError(EMAIL_TAKEN, "This email is already registered", 409,
                       where="body.email")

    if plan is not None and not известен(plan):
        raise ApiError(UNKNOWN_PLAN, f"Unknown plan {plan!r}", 400,
                       where="body.plan")

    ник = None
    if nickname:
        ник = проверить_ник(nickname)
        требовать_свободный_ник(s, ключ_ника(ник))

    # Пароль, которого не знает никто: 32 случайных байта, выброшенные сразу
    # после хеширования. Аккаунт открывается только по ссылке сброса.
    user = создать_пользователя(s, почта, новый_токен(), ник)
    user.email_confirmed_at = now()
    if plan is not None:
        user.plan = нормальный_план(plan)

    токен = выдать_токен(s, user, RESET)
    в_оба_журнала(request, USER_CREATED_BY_ADMIN, user=user.id)
    return user, mail.reset_link(settings, токен)


# ── очередь ──────────────────────────────────────────────────────────────────

def очередь(s: Session, settings: Settings) -> dict:
    """Состояние очереди: сколько чего ждёт и работает, слоты, воркеры.

    Считается по таблице `jobs` целиком, а не по своим заданиям: это страница
    владельца, и вопрос на ней — «жива ли машина», а не «что с моим отчётом».
    """
    from ..accounts.service import в_utc
    from ..jobs.models import QUEUED, RUNNING, Job

    строки = s.execute(
        select(Job.status, Job.kind, func.count())
        .where(Job.status.in_((QUEUED, RUNNING)))
        .group_by(Job.status, Job.kind)).all()

    по_видам: dict[str, dict[str, int]] = {}
    итого = {QUEUED: 0, RUNNING: 0}
    for status, kind, сколько in строки:
        по_видам.setdefault(kind, {QUEUED: 0, RUNNING: 0})[status] = int(сколько)
        итого[status] += int(сколько)

    сейчас = now()
    воркеры = []
    for job in s.scalars(select(Job).where(Job.status == RUNNING)):
        если_бился = в_utc(job.heartbeat_at)
        воркеры.append({
            "worker_id": job.worker_id,
            "job_id": job.id,
            "kind": job.kind,
            "heartbeat_age_s": None if если_бился is None
            else round((сейчас - если_бился).total_seconds(), 1),
        })

    return {
        "queued": итого[QUEUED],
        "running": итого[RUNNING],
        "by_kind": {kind: {"queued": v[QUEUED], "running": v[RUNNING]}
                    for kind, v in sorted(по_видам.items())},
        "slots": {"per_machine": settings.job_slots,
                  "per_user": settings.jobs_per_user},
        "workers": sorted(воркеры, key=lambda w: (w["worker_id"] or "")),
        # Сколько секунд без сердцебиения означают «воркера больше нет» — то же
        # число, по которому воркер поднимает потерянные задания.
        "lost_after_s": settings.job_timeout_s,
    }


# ── сводка для графиков ──────────────────────────────────────────────────────

def _день(момент) -> str | None:
    """Календарный день UTC строкой `ГГГГ-ММ-ДД`, как его видит график."""
    from ..accounts.service import в_utc

    приведённый = в_utc(момент)
    return None if приведённый is None else приведённый.date().isoformat()


def сводка(s: Session, *, days: int = СВОДКА_ДНЕЙ_ПО_УМОЛЧАНИЮ) -> dict:
    """Расход, задания и регистрации за последние `days` дней — для графиков.

    Зачем отдельный маршрут. Списку людей и очереди нечего сказать про время:
    первый знает расход за календарный месяц одним числом, вторая — что в
    очереди прямо сейчас. Вопрос владельца «растёт ли расход и когда приходят
    люди» по ним не отвечается вовсе, а собирать его на сайте из списка
    заданий нельзя — маршрута «все задания всех» нет и заводить его ради
    графика значило бы отдать наружу чужие `payload`.

    **Дни идут подряд, включая пустые.** Ряд, в котором пропущены дни без
    заданий, рисуется графиком как ровная линия, а провал в выходные
    превращается в отрезок между пятницей и понедельником — то есть в неправду.
    Поэтому ряд плотный: сколько дней просили, столько точек и вернётся.

    **День — календарный день UTC**, как и месяц расхода (`jobs.начало_месяца`):
    сутки, считаемые в часовом поясе машины, поехали бы при переезде контейнера.

    **Считается по строкам, а не группировкой в SQL.** Резать метку времени по
    суткам умеют оба движка, но по-разному (`date()` у SQLite, `date_trunc` у
    Postgres), и запрос вышел бы диалектным. Строк здесь столько, сколько
    заданий завели за период, а период ограничен `СВОДКА_ДНЕЙ_МАКСИМУМ`; берутся
    четыре колонки, а не строки целиком, — `payload` и `result` в память не
    едут.

    «Активные» — те, у кого за период есть хоть одно задание, а не все
    заведённые: цифра «сколько людей пользуется» иначе не отличалась бы от
    цифры «сколько зарегистрировалось».
    """
    from ..accounts.models import User
    from ..jobs.models import FAILED, Job

    дней = max(1, min(int(days), СВОДКА_ДНЕЙ_МАКСИМУМ))
    сегодня = now().date()
    первый = сегодня - datetime.timedelta(days=дней - 1)
    порог = datetime.datetime.combine(первый, datetime.time.min,
                                      tzinfo=datetime.timezone.utc)
    оси = [(первый + datetime.timedelta(days=i)).isoformat() for i in range(дней)]

    расход: dict[str, int] = {}
    по_видам: dict[str, dict[str, int]] = {}
    активные: set[str] = set()
    строки = s.execute(select(Job.created_at, Job.spent_units, Job.kind,
                              Job.status, Job.user_id)
                       .where(Job.created_at >= порог)).all()
    for создано, потрачено, вид, состояние, чей in строки:
        день = _день(создано)
        if день is not None:
            расход[день] = расход.get(день, 0) + int(потрачено or 0)
        счёт = по_видам.setdefault(вид, {"count": 0, "failed": 0})
        счёт["count"] += 1
        if состояние == FAILED:
            счёт["failed"] += 1
        if чей:
            активные.add(чей)

    регистрации: dict[str, int] = {}
    for (создано,) in s.execute(select(User.created_at)
                                .where(User.created_at >= порог)).all():
        день = _день(создано)
        if день is not None:
            регистрации[день] = регистрации.get(день, 0) + 1

    return {
        "days": дней,
        "since": порог.isoformat(),
        "usage_by_day": [{"day": д, "units": расход.get(д, 0)} for д in оси],
        "jobs_by_kind": [{"kind": вид, "count": счёт["count"],
                          "failed": счёт["failed"]}
                         for вид, счёт in sorted(по_видам.items())],
        "registrations_by_day": [{"day": д, "count": регистрации.get(д, 0)}
                                 for д in оси],
        "active_users": len(активные),
    }


__all__ = ["событие", "записать", "сбросить", "install", "СОБЫТИЯ",
           "ЖурналБезопасности",
           "события", "карточка_события", "люди",
           "карточка_человека", "поправить", "завести_человека", "очередь",
           "сводка", "лимит",
           "FORBIDDEN", "EMAIL_TAKEN",
           "СОБЫТИЙ_ПО_УМОЛЧАНИЮ", "СОБЫТИЙ_МАКСИМУМ",
           "СВОДКА_ДНЕЙ_ПО_УМОЛЧАНИЮ", "СВОДКА_ДНЕЙ_МАКСИМУМ"]
