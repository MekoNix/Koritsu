"""
mail — один способ отправить письмо и одна его реализация: консоль.

Правило ночи (владелец, 2026-09-03): **писем не слать, Resend не подключать**.
Подтверждение почты работает «консольным» бэкендом, который печатает ссылку в
журнал. Отсюда весь модуль: протокол `Mailer` и `ConsoleMailer`.

Протокол, а не одна функция, — потому что мест, где письмо отправляется, будет
несколько (подтверждение, сброс пароля, «отчёт готов» из §7), а способов
отправки — два (Resend и SMTP как запасной, решение §8). Без протокола второй
способ добавляется правкой каждого места; с ним — одним классом здесь.

**Место для Resend** — `mailer_for(settings)`: он выбирает реализацию по
настройкам. Когда ключ Resend появится, здесь встанет `ResendMailer`, а всё
остальное не заметит подмены. Настройки для него (`KORITSU_RESEND_KEY`,
адрес отправителя) сейчас нет намеренно: пустая настройка под неподключённую
службу — это приглашение однажды подключить её молча.

**Что попадает в журнал.** Каркас (`log.py`, §3) запрещает писать в технический
журнал содержимое тел и строку запроса — «в них уезжает токен подтверждения
почты». Здесь это правило не нарушается, а обходится по назначению: журнал
`api.mail` — это не технический поток, а *подмена почтового ящика*. Ссылку
с токеном в него пишет консольный бэкенд, потому что иначе разработчику неоткуда
её взять — письма-то нет. На живом сайте этого бэкенда не будет: там письмо
уходит в почту, а в журнале останется только «кому и какое». Пароля здесь нет
никогда и ни в каком виде — в письме его нет и быть не может.
"""
from __future__ import annotations

import logging
from typing import Protocol

from ..settings import Settings

# Отдельный маршрут журнала: его читают глазами, а не разбирают, и в dev он
# заменяет почтовый ящик.
журнал = logging.getLogger("api.mail")


class Mailer(Protocol):
    """Кто умеет отправить письмо. Один метод — больше службе не нужно."""

    def send(self, to: str, subject: str, body: str) -> None:
        ...


class ConsoleMailer:
    """Письмо, которое никуда не уходит, а печатается в журнал.

    Уровень INFO, а не DEBUG: в `prod` уровень журнала INFO (`log.setup`), и
    сообщение уровня DEBUG было бы не видно — то есть при случайно оставшемся
    консольном бэкенде люди не получали бы писем **и** этого никто бы не заметил.
    """

    def send(self, to: str, subject: str, body: str) -> None:
        журнал.info("письмо to=%s subject=%s\n%s", to, subject, body)


def mailer_for(settings: Settings) -> Mailer:
    """Чем отправлять письма при этих настройках.

    Пока всегда консольный. Здесь же появится Resend (решение §8) — одной
    веткой, когда у службы будет ключ и домен с DNS-записями.
    """
    _настроить_журнал()
    return ConsoleMailer()


def _настроить_журнал() -> None:
    """Дать журналу почты обработчик, если его ещё нет.

    Тем же способом, что `log.setup` даёт его техническому потоку, и по той же
    причине: логгер без обработчика молчит, а молчащий консольный бэкенд — это
    подтверждение почты, которое невозможно пройти, и ни одной строки о том,
    почему. Корневой логгер не трогаем: перенастроить его значило бы молча
    поменять журнал всему, что окажется в процессе.
    """
    журнал.setLevel(logging.INFO)
    if not журнал.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        журнал.addHandler(handler)


# ── тексты писем ─────────────────────────────────────────────────────────────
#
# По-английски (§7: «всё на английском: коды, тексты ошибок, документация»).
# Перевод — дело интерфейса; письмо, впрочем, интерфейсом не переводится, и это
# место, где владельцу стоит однажды сказать, на каком языке пишем людям.

CONFIRM_SUBJECT = "Confirm your Koritsu account"
RESET_SUBJECT = "Reset your Koritsu password"


def confirm_link(settings: Settings, token: str) -> str:
    """Ссылка подтверждения почты. Адрес сайта — из настроек, не из запроса.

    Из настроек намеренно: собрать ссылку по заголовку `Host` значит позволить
    кому угодно прислать запрос с чужим `Host` и получить письмо со ссылкой на
    свой сайт — с настоящим токеном внутри.
    """
    return f"{settings.base_url}/confirm?token={token}"


def reset_link(settings: Settings, token: str) -> str:
    """Ссылка сброса пароля. По той же причине — из настроек."""
    return f"{settings.base_url}/reset?token={token}"


def confirm_body(link: str) -> str:
    return ("Welcome to Koritsu.\n\n"
            f"Confirm your email address: {link}\n\n"
            "The link expires in 24 hours. "
            "If you did not create an account, ignore this message.")


def reset_body(link: str) -> str:
    return ("Someone asked to reset the password of your Koritsu account.\n\n"
            f"Set a new password: {link}\n\n"
            "The link expires in 1 hour. "
            "If it was not you, ignore this message — nothing has changed.")


__all__ = ["Mailer", "ConsoleMailer", "mailer_for", "confirm_link",
           "reset_link", "confirm_body", "reset_body", "CONFIRM_SUBJECT",
           "RESET_SUBJECT", "журнал"]
