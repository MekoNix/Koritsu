"""
accounts — аккаунты и сессии: кто пришёл и вправе ли он вообще что-то просить.

Всё, что связано с человеком как таковым: регистрация с
подтверждением почты, вход, сессии в базе, выход со всех устройств, сброс
пароля, поля второго фактора и лимиты. Ни проектов, ни файлов, ни
моделей здесь нет и быть не может: `accounts` — самый нижний из трёх подпакетов
службы, и он ничего не знает про соседей.

    models.py    users, email_tokens, sessions, registration_attempts
    service.py   пароли, токены, сессии, лимиты, зависимость `current_user`
    mail.py      протокол `Mailer` и консольная реализация (писем не шлём)
    avatar.py    своя картинка: сигнатура, пересохранение, место на томе
    routes.py    `/api/auth/…` и `/api/users/{id}/avatar`

**Что берут соседи.** Три имени, и других отсюда брать не надо:

    from api.accounts import CurrentUser, current_user, on_user_created

* `current_user(request, session) -> User` — зависимость FastAPI: годная
  сессия из cookie или 401 `unauthenticated`. Она же выставляет
  `request.state.user_id`, который каркас пишет в технический журнал;
* `CurrentUser` — та же зависимость в виде `Annotated[User, Depends(...)]`,
  чтобы обработчик писался в одну строку: `def список(me: CurrentUser)`;
* `on_user_created: list[Callable[[Session, User], None]]` — хуки «пользователь
  заведён». Сюда `workspaces` добавляет функцию, создающую личный workspace.
  Зовутся они внутри той же транзакции, после `flush` (id уже есть) и до
  коммита: беда в хуке откатывает и саму регистрацию.

Почему хук, а не прямой вызов `spaces` отсюда: личный workspace — правило
пространств, и знать о нём аккаунтам незачем. Импорт в обратную сторону связал
бы их в кольцо, и ни один не собрался бы без другого — та же беда, от которой
`api` защищён запретом импортировать себя из `orchestrator`.
"""
from __future__ import annotations

from .mail import ConsoleMailer, Mailer, mailer_for
from .models import EmailToken, RegistrationAttempt, User, UserSession
from .routes import router
from .service import (COOKIE, CurrentUser, current_user, on_user_created,
                      отозвать_все, текущая_сессия)

__all__ = ["current_user", "CurrentUser", "on_user_created", "router",
           "User", "UserSession", "EmailToken", "RegistrationAttempt",
           "Mailer", "ConsoleMailer", "mailer_for", "COOKIE",
           "отозвать_все", "текущая_сессия"]
