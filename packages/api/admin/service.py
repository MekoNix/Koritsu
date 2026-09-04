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
cookie, ни почты (§7: почта — то, что при удалении аккаунта обязано исчезнуть).
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
    применяет: расход модели — агент B (`monthly_units`), место на томе —
    материалы (`quota_bytes`).

        месячный = admin.service.лимит(user, "monthly_units",
                                       settings.free_monthly_units)
    """
    значение = (getattr(user, "limits", None) or {}).get(ключ)
    return умолчание if значение is None else значение


def карточка_человека(user, settings: Settings, *, bytes_used: int,
                      spent_units: int) -> dict:
    """Что видит владелец в списке людей.

    Почта здесь есть — и это не противоречие §7. Список читает владелец службы,
    которому иначе некого опознать (UUID не говорит ничего), а в **журнал** она
    по-прежнему не попадает: журнал переживает удаление аккаунта, а эта
    страница показывает то, что в базе есть прямо сейчас.
    """
    def iso(момент):
        return момент.isoformat() if момент is not None else None

    return {
        "id": user.id,
        "email": user.email,
        "plan": user.plan,
        "is_admin": bool(user.is_admin),
        "limits": dict(user.limits or {}),
        "quota_bytes": лимит(user, "quota_bytes", settings.user_quota_bytes),
        "bytes_used": bytes_used,
        "spent_units": spent_units,
        "email_confirmed": user.email_confirmed_at is not None,
        "created_at": iso(user.created_at),
        "deleted_at": iso(user.deleted_at),
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
              is_admin: bool | None = None, limits: dict | None = None):
    """Сменить план, права владельца и личные лимиты. Возвращает строку.

    `limits` присваивается целиком, а не сливается: правка «поставь квоту»,
    молча сохраняющая прошлый месячный лимит, однажды сохранит тот, который
    владелец как раз убирал. Целиком — значит видно, что осталось.
    """
    from ..accounts.models import User

    user = s.get(User, user_id)
    if user is None:
        raise ApiError("not_found", "User not found", 404, where="path.user_id")
    if plan is not None:
        user.plan = plan.strip()[:32]
    if is_admin is not None:
        user.is_admin = bool(is_admin)
    if limits is not None:
        user.limits = dict(limits)
    return user


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


__all__ = ["событие", "записать", "сбросить", "install", "СОБЫТИЯ",
           "ЖурналБезопасности",
           "события", "карточка_события", "люди",
           "карточка_человека", "поправить", "очередь", "лимит",
           "FORBIDDEN",
           "СОБЫТИЙ_ПО_УМОЛЧАНИЮ", "СОБЫТИЙ_МАКСИМУМ"]
