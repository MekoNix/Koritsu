"""
stream — поток уровня 2 → пары «ключ тега, значение» по мере закрытия значений.

Уровень 2 просит весь отчёт одним вызовом: `{"цель": {…}, "введение": {…}, …}`.
Это самый дорогой вызов в системе, и он же самый длинный — то есть тот, который
чаще всего обрывается. Если разбирать ответ целиком в конце, обрыв на девятом
теге из двенадцати стоит всех двенадцати: заплачено, а сохранить нечего.
Накопитель отдаёт тег в момент, когда закрылось ЕГО значение, поэтому обрыв
стоит одного недописанного тега.

Счёт скобок здесь не свой: значение целиком отдаётся
`llm.stream_parse.ObjectStream`, который уже умеет считать скобки с учётом
строк, экранов и обрыва посреди многобайтового символа. Своего здесь ровно
столько, сколько в `llm` быть не может: чтение имени ключа. Это «тег готов» —
смысл из предметной области, а слой моделей объявил, что про теги не знает
(разбор — в службе, счётчик скобок — общий и живёт в `llm`).

Разбор снисходителен к обёртке (забор ```json, пояснения модели до объекта) и
строг к содержимому: всё, что не разобралось, попадает в `broken` или `skipped`
и видно вызывающему. Молча потерянный тег — тот же класс дефекта, что молча
проглоченный ключ: отчёт собирается без него, и объяснить нечем.
"""
from __future__ import annotations

import json

from llm.stream_parse import ObjectStream

# Состояния разбора обёртки. Значение разбирает ObjectStream, поэтому состояний
# всего четыре, и все они — про то, что снаружи значения.
_WRAPPER, _KEY, _COLON, _VALUE, _SKIP = "wrapper", "key", "colon", "value", "skip"


class TagStream:
    """Куски текста ответа → `(ключ, значение)`, как только значение закрылось.

    Правило, ради которого всё: пара отдаётся ровно один раз и ровно тогда,
    когда её объект закрылся. Вызывающий сохраняет её немедленно, и обрыв связи
    следующим куском уже ничего не отменяет.
    """

    def __init__(self):
        self.pairs: list = []        # всё разобранное с начала потока
        self.broken: list = []       # (ключ, сырой текст) — закрылось, но не JSON
        self.skipped: list = []      # (ключ, сырой текст) — значение не объект
        self._mode = _WRAPPER
        self._started = False        # видели ли открывающую скобку обёртки
        self._key: list = []
        self._escaped = False
        self._pending_key = ""
        self._value: ObjectStream | None = None
        self._skip_raw: list = []
        self._skip_depth = 0
        self._skip_string = False
        self._skip_escaped = False

    # ── чтение ──────────────────────────────────────────────────────────────
    def feed(self, text: str) -> list:
        """Кусок ответа → пары, закрывшиеся именно на нём.

        Кусок может оборваться где угодно — посреди имени ключа, между ключом и
        двоеточием, посреди значения, — поэтому всё состояние живёт между
        вызовами. Иначе каждый неудачный разрыв терял бы один тег, а разрывы
        приходят как придётся.
        """
        ready: list = []
        for ch in text or "":
            if self._mode == _WRAPPER:
                self._wrapper(ch)
            elif self._mode == _KEY:
                self._key_char(ch)
            elif self._mode == _COLON:
                self._colon(ch)
            elif self._mode == _VALUE:
                self._value_char(ch, ready)
            else:
                self._skip_char(ch)
        return ready

    def close(self) -> dict:
        """Что осталось незакрытым — для записи прогона «на чём оборвалось».

        Отдаётся сырым текстом, а не значением: он заведомо неполный, и
        достраивать его догадкой значило бы записать в отчёт то, чего модель не
        писала.
        """
        return {"key": self._pending_key or "".join(self._key),
                "text": self._value.pending if self._value is not None else "",
                "broken": list(self.broken), "skipped": list(self.skipped)}

    @property
    def truncated(self) -> bool:
        """Оборвались ли посреди значения (проверяется после конца потока)."""
        return self._mode in (_KEY, _COLON, _VALUE, _SKIP)

    # ── состояния ───────────────────────────────────────────────────────────
    def _wrapper(self, ch: str) -> None:
        """Вне значения: ждём открывающую скобку обёртки, потом имя ключа.

        Кавычки до обёртки ключами не считаются намеренно: модель любит написать
        «Вот "результат":» перед JSON, и без этой оговорки такая фраза стала бы
        ключом, а следующий за ней настоящий объект уехал бы не в тот тег.
        """
        if not self._started:
            if ch == "{":
                self._started = True
            return
        if ch == '"':
            self._mode = _KEY
            self._key = []
            self._escaped = False

    def _key_char(self, ch: str) -> None:
        if self._escaped:
            self._key.append(ch)
            self._escaped = False
            return
        if ch == "\\":
            self._key.append(ch)
            self._escaped = True
            return
        if ch == '"':
            self._pending_key = _unescape("".join(self._key))
            self._mode = _COLON
            return
        self._key.append(ch)

    def _colon(self, ch: str) -> None:
        if ch.isspace():
            return
        if ch != ":":
            # Строка оказалась не именем ключа. Возвращаемся к поиску, а не
            # гадаем: пара с придуманным ключом хуже пропущенной. Накопитель
            # имени чистим здесь же: `close()` берёт «на чём оборвались» из
            # него, и брошенная строка называлась бы тегом обрыва — жалоба на
            # тег, которого модель не писала, в прогоне, дошедшем до конца.
            self._pending_key = ""
            self._key = []
            self._mode = _WRAPPER
            return
        self._value = ObjectStream()
        self._mode = _VALUE

    def _value_char(self, ch: str, ready: list) -> None:
        assert self._value is not None
        if not self._value.pending and not self._value.objects:
            if ch.isspace():
                return
            if ch != "{":
                # Значение тега — всегда объект (`wire.value_schema` даёт
                # `type: object` у всех десяти типов). Скаляр или null тут
                # означает, что модель ответила не по схеме; пропустить его
                # надо аккуратно, иначе следующий ключ прочитается как часть
                # этого значения и пары разъедутся до конца потока.
                self._mode = _SKIP
                self._skip_raw = []
                self._skip_depth = 0
                self._skip_string = False
                self._skip_escaped = False
                self._skip_char(ch)
                return
        broken_before = len(self._value.broken)
        for obj in self._value.feed(ch):
            self.pairs.append((self._pending_key, obj))
            ready.append((self._pending_key, obj))
            self._done()
            return
        if len(self._value.broken) > broken_before:
            # Объект закрылся, но JSON не разобрался: тег потерян, и это видно.
            self.broken.append((self._pending_key, self._value.broken[-1]))
            self._done()

    def _skip_char(self, ch: str) -> None:
        """Пропуск значения-нескаляра до конца — со счётом строк и скобок."""
        if self._skip_string:
            self._skip_raw.append(ch)
            if self._skip_escaped:
                self._skip_escaped = False
            elif ch == "\\":
                self._skip_escaped = True
            elif ch == '"':
                self._skip_string = False
            return
        if ch == '"':
            self._skip_string = True
        elif ch in "{[":
            self._skip_depth += 1
        elif ch in "}]":
            if self._skip_depth == 0:
                self.skipped.append((self._pending_key, "".join(self._skip_raw).strip()))
                self._done()
                return
            self._skip_depth -= 1
        elif ch == "," and self._skip_depth == 0:
            self.skipped.append((self._pending_key, "".join(self._skip_raw).strip()))
            self._done()
            return
        self._skip_raw.append(ch)

    def _done(self) -> None:
        self._pending_key = ""
        self._key = []
        self._value = None
        self._skip_raw = []
        self._mode = _WRAPPER


def _unescape(raw: str) -> str:
    """Имя ключа как его написала модель: `\\u0446` и `\\"` — это JSON, а не текст."""
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


__all__ = ["TagStream"]
