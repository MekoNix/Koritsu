"""
service — жизнь шаблона отчёта: принять DOCX, показать список, отдать байты, снести.

Коды отказа, которые выдаёт этот модуль:

    bad_template    400  принесённый файл не читается как DOCX с тегами
    invalid_name    400  имя пустое
    quota_exceeded  413  файл не влезает в квоту человека
    not_found       404  чужой (или несуществующий) шаблон

**Теги считает оркестратор, а не мы** (`orchestrator.template_tags`). Это та же
самая функция, которой строится манифест при создании проекта, и в этом весь
смысл: число тегов в списке шаблонов обязано совпадать с числом тегов в работе,
заведённой по этому шаблону. Свой разбор DOCX рядом разошёлся бы с манифестом на
первой же правке `hokoku.extract_tags` — и разошёлся бы молча.

**Разбор он же и проверка.** Отдельного «а точно ли это DOCX» здесь нет: файл,
на котором `template_tags` поднял беду, — это файл, на котором упало бы и
создание проекта, и отказывать в нём надо при загрузке, а не через неделю при
первой работе. Наружу беда уходит как `bad_template` без подробностей: в её
тексте бывает путь на томе.

**Байты — на томе, строка — в базе.** Каталог даёт пакет проектов
(`projects.service.templates_dir`), потому что раскладку тома знает она; имя
файла — идентификатор строки, то есть uuid4, уже проверенный `check_id`. Имени
от человека в пути нет и быть не может: оно приходит из запроса.

**Квота — общая с проектами** (`materials.service.проверить_квоту`). Не свой
порог: два порога на одного человека разошлись бы, и «250 МБ» перестало бы
что-либо значить. Шаблоны в этот счёт входят — `projects.service.bytes_used`
обходит и их каталог.

**Тот же файл дважды — два шаблона.** Дедупликации по `sha256` здесь нет
намеренно, в отличие от материалов: материал адресуется содержимым и один и тот
же PDF в проекте — один материал, а шаблон человек называет сам, и два имени у
одних байтов («ГОСТ 2024» и «ГОСТ 2024 без приложения») — это две разные вещи в
его списке. Цена — вторые те же байты в квоте, и она честно видна.
"""
from __future__ import annotations

import os

import orchestrator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..ids import check_id
from ..log import беды
from ..materials.service import проверить_квоту
from ..projects.service import templates_dir
from ..settings import Settings
from ..workspaces.service import iso
from .models import NAME_LEN, SHA_LEN, ReportTemplate

BAD_TEMPLATE = "bad_template"
INVALID_NAME = "invalid_name"
NOT_FOUND = "not_found"

# Расширение файла на томе. Не про распознавание (никто его не спрашивает), а
# про то, что каталог тома иногда читают глазами — и `.bin` там ни о чём не
# говорит.
РАСШИРЕНИЕ = ".docx"


# ── том ──────────────────────────────────────────────────────────────────────

def путь(settings: Settings, user_id: str, template_id: str) -> str:
    """Где лежат байты этого шаблона. Наружу путь не уезжает никогда.

    Оба куска пути — uuid4 из базы, и оба проходят `check_id` до склейки:
    `templates_dir` проверяет владельца, `check_id` здесь — сам шаблон.
    """
    return os.path.join(templates_dir(settings, user_id),
                        check_id(template_id, where="path.template_id")
                        + РАСШИРЕНИЕ)


def байты(settings: Settings, шаблон: ReportTemplate) -> bytes:
    """Содержимое шаблона с тома. Файла нет — `404`, как и строки нет.

    Пропавший файл при живой строке — это беда тома, и разбираться в ней по
    журналу нам; человеку же «шаблона нет» и «файл пропал» — одно событие.
    """
    try:
        with open(путь(settings, шаблон.user_id, шаблон.id), "rb") as f:
            return f.read()
    except OSError:
        беды.exception("шаблон %s: файла нет на томе", шаблон.id)
        raise ApiError(NOT_FOUND, "Template not found", 404,
                       where="path.template_id") from None


# ── приём ────────────────────────────────────────────────────────────────────

def число_тегов(данные: bytes) -> int:
    """Сколько тегов в этом DOCX. Не DOCX — `400 bad_template`."""
    try:
        return len(orchestrator.template_tags(данные))
    except Exception:                                        # noqa: BLE001
        # Подробности — в журнал: в тексте беды движка отчётов бывает путь.
        беды.exception("шаблон не разобрался")
        raise ApiError(BAD_TEMPLATE, "Template is not a readable DOCX file",
                       400, where="body.file") from None


def имя_шаблона(сырое: str, имя_файла: str) -> str:
    """Имя для списка: своё, а если его не написали — имя файла без расширения.

    Пустое имя отвергается, а не заменяется словом «шаблон»: список из пяти
    «шаблонов» бесполезен ровно так же, как список из пяти пустых строк, а
    имя файла у загрузки есть всегда.
    """
    имя = (сырое or "").strip()
    if not имя:
        основа, _ = os.path.splitext((имя_файла or "").strip())
        имя = основа.strip()
    if not имя:
        raise ApiError(INVALID_NAME, "Template name is required", 400,
                       where="body.name")
    return имя[:NAME_LEN]


def добавить(s: Session, settings: Settings, user_id: str, *, имя: str,
             имя_файла: str, данные: bytes) -> ReportTemplate:
    """Принять DOCX человека: разбор, квота, байты на том, строка в базе.

    Порядок шагов — он же порядок отказов, и он не случаен: сначала дешёвое имя,
    потом разбор (он же проверка, что это вообще DOCX), потом обход тома ради
    квоты и только в конце запись. Обратный порядок оставлял бы на томе файлы,
    отвергнутые следующей же проверкой.

    Строка заводится до записи файла, чтобы имя файла взялось из её `id`: при
    беде на диске сессия откатится сама (сессия на запрос, `db.session`), а
    обратный порядок оставил бы на томе байты, о которых база не знает.
    """
    название = имя_шаблона(имя, имя_файла)
    тегов = число_тегов(данные)
    проверить_квоту(s, settings, user_id, len(данные))

    шаблон = ReportTemplate(user_id=user_id, name=название, bytes=len(данные),
                            tags=тегов,
                            sha256=orchestrator.artifact_id(данные)[:SHA_LEN])
    s.add(шаблон)
    s.flush()

    цель = путь(settings, user_id, шаблон.id)
    os.makedirs(os.path.dirname(цель), exist_ok=True)
    with open(цель, "wb") as f:
        f.write(данные)
    return шаблон


# ── чтение и уборка ──────────────────────────────────────────────────────────

def мои(s: Session, user_id: str) -> list[ReportTemplate]:
    """Шаблоны человека, новые сверху."""
    return list(s.scalars(
        select(ReportTemplate).where(ReportTemplate.user_id == user_id)
        .order_by(ReportTemplate.created_at.desc())))


def найти(s: Session, user_id: str, template_id: str, *,
          where: str = "path.template_id") -> ReportTemplate:
    """Свой шаблон или `404`.

    Чужой и несуществующий отвечают одинаково (тот же довод, что у чужого
    проекта): разный ответ рассказывал бы, что шаблон с таким идентификатором
    у кого-то есть.

    `where` — где спрашивающий назвал шаблон. Аргументом, потому что зовут эту
    функцию из двух мест: свои маршруты называют его в пути, а создание проекта
    (`projects.routes`) — полем формы, и отказ обязан указывать на то поле,
    которое человек и правда заполнял.
    """
    шаблон = s.get(ReportTemplate, check_id(template_id, where=where))
    if шаблон is None or шаблон.user_id != user_id:
        raise ApiError(NOT_FOUND, "Template not found", 404, where=where)
    return шаблон


def удалить(s: Session, settings: Settings, user_id: str,
            template_id: str) -> None:
    """Снести шаблон: файл с тома, строку из базы.

    Сначала диск, потом база — тот же порядок, что у уборки проектов
    (`projects.service.purge_expired`) и по той же причине: обратный оставил бы
    на томе файл, про который никто больше не знает, то есть место, занятое
    навсегда.

    Работы, заведённые по этому шаблону, удаление не трогает: при создании
    проекта байты **копируются** в его артефакты, и связи со строкой у проекта
    нет. Иначе «убрал шаблон из списка» означало бы «сломал десять работ».
    """
    шаблон = найти(s, user_id, template_id)
    try:
        os.remove(путь(settings, user_id, шаблон.id))
    except OSError:
        pass                       # файла нет — строку всё равно убираем
    s.delete(шаблон)
    s.flush()


def карточка(шаблон: ReportTemplate) -> dict:
    """Шаблон наружу. Путей здесь нет и быть не может."""
    return {"id": шаблон.id, "name": шаблон.name, "bytes": int(шаблон.bytes),
            "tags": int(шаблон.tags), "sha256": шаблон.sha256,
            "created_at": iso(шаблон.created_at)}


__all__ = ["путь", "байты", "добавить", "мои", "найти", "удалить", "карточка",
           "число_тегов", "имя_шаблона", "BAD_TEMPLATE", "INVALID_NAME",
           "NOT_FOUND", "РАСШИРЕНИЕ"]
