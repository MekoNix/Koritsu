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

**Один DOCX — один шаблон.** Повторная загрузка тех же байтов не заводит
второй шаблон: находится прежний и возвращается он же (маршрут отвечает на это
`200`, а не `201`). Дедупликация — по `sha256` содержимого и в пределах одного
человека: чужие шаблоны не видны и не сличаются, иначе по ответу «этот файл у
вас уже есть» можно было бы узнать про чужой список.

Довод против («два имени у одних байтов — две разные вещи в списке») не
выдержал первого же живого прогона: два одинаковых пункта в списке человек
читает как сбой, а не как замысел, и вторые те же байты он всё равно оплачивает
квотой. Переименовать шаблон, если нужно другое имя, дешевле, чем держать копию.
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
from .models import NAME_LEN, SHA_LEN, ProjectTemplate, ReportTemplate

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
             имя_файла: str, данные: bytes) -> tuple[ReportTemplate, bool]:
    """Принять DOCX человека: разбор, поиск того же файла, квота, том, строка.

    → `(шаблон, новый ли он)`. Второе значение нужно маршруту, чтобы ответить
    `201` на заведённый и `200` на найденный: «создано» и «уже было» — разные
    события, и различать их клиент обязан не по совпадению имён.

    Порядок шагов — он же порядок отказов, и он не случаен: сначала дешёвое имя,
    потом разбор (он же проверка, что это вообще DOCX), потом поиск тех же
    байтов, потом обход тома ради квоты и только в конце запись. Обратный
    порядок оставлял бы на томе файлы, отвергнутые следующей же проверкой, а
    квота считалась бы за файл, который и не собирались класть.

    Строка заводится до записи файла, чтобы имя файла взялось из её `id`: при
    беде на диске сессия откатится сама (сессия на запрос, `db.session`), а
    обратный порядок оставил бы на томе байты, о которых база не знает.
    """
    название = имя_шаблона(имя, имя_файла)
    тегов = число_тегов(данные)

    # Тот же файл — тот же шаблон. Имя при этом остаётся прежним: человек
    # называл этот файл сам, и переписать имя загрузкой-двойником значило бы
    # переименовать шаблон, о котором он в эту минуту не думал.
    прежний = по_содержимому(s, user_id, orchestrator.artifact_id(данные)[:SHA_LEN])
    if прежний is not None:
        return прежний, False

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
    return шаблон, True


def по_содержимому(s: Session, user_id: str,
                   sha256: str) -> ReportTemplate | None:
    """Свой шаблон с такими байтами — или `None`.

    Ищется **среди своих**: сличать с чужими значило бы отвечать «этот файл уже
    есть» про чужой список, то есть рассказывать о нём.
    """
    return s.scalars(
        select(ReportTemplate)
        .where(ReportTemplate.user_id == user_id,
               ReportTemplate.sha256 == sha256)
        .order_by(ReportTemplate.created_at)).first()


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


# ── шаблоны работы ───────────────────────────────────────────────────────────

def приложить(s: Session, project_id: str,
              шаблон: ReportTemplate) -> tuple[ProjectTemplate, bool]:
    """Приложить шаблон к работе. → `(связка, новая ли она)`.

    Приложить тот же шаблон второй раз — то же состояние, а не второй пункт
    списка: пара уникальна (`ProjectTemplate`), и повторная просьба возвращает
    прежнюю связку. Отказывать было бы хуже: человек, нажавший «добавить» второй
    раз, добивается ровно того, что уже есть.
    """
    прежняя = s.scalars(
        select(ProjectTemplate)
        .where(ProjectTemplate.project_id == project_id,
               ProjectTemplate.template_id == шаблон.id)).first()
    if прежняя is not None:
        return прежняя, False
    связка = ProjectTemplate(project_id=project_id, template_id=шаблон.id)
    s.add(связка)
    s.flush()
    return связка, True


def шаблоны_проекта(s: Session, project_id: str) -> list[ReportTemplate]:
    """Шаблоны, приложенные к работе, в порядке добавления.

    В порядке добавления, а не по дате загрузки файла: список читается как
    «что мы сюда положили», и файл трёхмесячной давности, приложенный сегодня,
    стоит последним — там, где его и оставили.
    """
    запрос = (select(ReportTemplate)
              .join(ProjectTemplate,
                    ProjectTemplate.template_id == ReportTemplate.id)
              .where(ProjectTemplate.project_id == project_id)
              .order_by(ProjectTemplate.created_at))
    return list(s.scalars(запрос))


def отвязать(s: Session, project_id: str, template_id: str) -> None:
    """Убрать шаблон из списка работы. Сам файл остаётся у человека.

    Убирается связка, а не шаблон: тот же DOCX приложен к трём работам, и
    «убрать отсюда» не может означать «стереть у себя с полки». Стирает файл
    отдельное действие — `DELETE /api/templates/{id}`.
    """
    связка = s.scalars(
        select(ProjectTemplate)
        .where(ProjectTemplate.project_id == project_id,
               ProjectTemplate.template_id == check_id(
                   template_id, where="path.template_id"))).first()
    if связка is None:
        raise ApiError(NOT_FOUND, "Template is not attached to this project",
                       404, where="path.template_id")
    s.delete(связка)
    s.flush()


def текущий_шаблон(проект, *, report: str = "") -> str:
    """Идентификатор артефакта бланка, по которому работа собирается сейчас.

    Пустая строка — бланка нет вовсе (работа заведена «с нуля») или каталога
    нет на томе: и то и другое значит «выбранного нет», а падать на чтении
    списка нельзя.

    Сличается он с `ReportTemplate.sha256` — те же 16 знаков хеша содержимого
    (`models.SHA_LEN` объясняет, почему они те же). Отдельного поля «какой
    выбран» в базе нет намеренно: правда о том, чем работа собирается, лежит в
    её `project.json`, и вторая запись рядом разошлась бы с ней при первой же
    смене бланка мимо службы.
    """
    try:
        return orchestrator.Project(проект.dir,
                                    report=report).template_artifact()
    except Exception:                                        # noqa: BLE001
        return ""


def приложенный(s: Session, project_id: str, template_id: str, *,
                where: str = "path.template_id") -> ReportTemplate:
    """Бланк, приложенный к этой работе, — или `404`.

    Только из приложенных: список приложенных и есть то, из чего выбирают, а
    любой другой идентификатор означал бы работу по бланку, которого в ней
    никто не видел.

    Отдельной функцией, потому что спрашивают об этом двое: «собирать по нему»
    и заведение отчёта, у которого свой бланк. Вторая такая же проверка рядом
    разошлась бы с первой на первом же уточнении.
    """
    связка = s.scalars(
        select(ProjectTemplate)
        .where(ProjectTemplate.project_id == project_id,
               ProjectTemplate.template_id == check_id(
                   template_id, where=where))).first()
    if связка is None:
        raise ApiError(NOT_FOUND, "Template is not attached to this project",
                       404, where=where)
    return по_ид(s, template_id, where=where)


def выбрать(s: Session, settings: Settings, проект,
            template_id: str, *, report: str = "") -> ReportTemplate:
    """Собирать работу по этому приложенному бланку. → сам шаблон.

    Решения человека о тегах переносит `Project.update_template` — он строит
    новый манифест поверх старого. Беда оттуда наружу идёт как `bad_template`
    без подробностей: в её тексте бывает путь на томе.
    """
    шаблон = приложенный(s, проект.id, template_id)
    данные = байты(settings, шаблон)
    try:
        orchestrator.Project(проект.dir, report=report).update_template(данные)
    except ApiError:
        raise
    except Exception:                                        # noqa: BLE001
        беды.exception("работа %s: бланк %s не встал", проект.id, шаблон.id)
        raise ApiError(BAD_TEMPLATE, "Template cannot be used for this work",
                       400, where="path.template_id") from None
    return шаблон


def по_ид(s: Session, template_id: str, *,
          where: str = "body.template_id") -> ReportTemplate:
    """Шаблон по идентификатору, без вопроса о владельце. Нет — `404`.

    Владельца **не** спрашивает намеренно, в отличие от `найти`: список
    шаблонов работы читают все участники пространства, и строку приложенного
    чужого бланка нужно уметь показать. Прикладывать при этом можно только
    своё — эту проверку делает маршрут, `найти`.
    """
    шаблон = s.get(ReportTemplate, check_id(template_id, where=where))
    if шаблон is None:
        raise ApiError(NOT_FOUND, "Template not found", 404, where=where)
    return шаблон


# ── наружу ───────────────────────────────────────────────────────────────────

def карточка(шаблон: ReportTemplate, *, активный: bool | None = None) -> dict:
    """Шаблон наружу. Путей здесь нет и быть не может.

    `активный` ставится только там, где вопрос имеет смысл, — в списке шаблонов
    работы. В личной полке его нет вовсе: шаблон лежит сам по себе и ни в какой
    работе не «выбран», а `false` на каждой строке читался бы как «не выбран
    нигде», что неправда.
    """
    карта = {"id": шаблон.id, "name": шаблон.name, "bytes": int(шаблон.bytes),
             "tags": int(шаблон.tags), "sha256": шаблон.sha256,
             "user_id": шаблон.user_id, "created_at": iso(шаблон.created_at)}
    if активный is not None:
        карта["active"] = bool(активный)
    return карта


__all__ = ["путь", "байты", "добавить", "мои", "найти", "по_ид", "удалить",
           "карточка", "число_тегов", "имя_шаблона", "по_содержимому",
           "приложить", "шаблоны_проекта", "отвязать", "текущий_шаблон",
           "приложенный", "выбрать", "BAD_TEMPLATE", "INVALID_NAME", "NOT_FOUND",
           "РАСШИРЕНИЕ"]
