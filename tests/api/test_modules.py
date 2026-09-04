"""
Реестр модулей: что интерфейсу позволено показать, и по какому шаблону.

Решение брифа: неготовые модули в интерфейсе не показываются вовсе — ни
заглушкой «скоро», ни серым пунктом. Значит `GET /api/modules` — не витрина
всего, что есть в коде, а список того, что можно показать, и разница между
этими двумя утверждениями проверяется здесь.

Второе, что проверяется, — шаблон: у модуля есть карточка, роутер лежит под
своим префиксом, `operation_id` начинается с имени модуля, а описания в OpenAPI
английские. Правила эти написаны в докстроке `api/modules/__init__.py`, но
докстрока никого не останавливает; останавливает тест.

Третье — правило разреза, и оно самое дорогое: служба зовёт `fragmos` и
`uml_generator` **только через `orchestrator`**. Общий тест
(`tests/kyotsu/test_border.py`) проверяет его по всему пакету; здесь он
проверяется ещё раз и с другой стороны — потому что модули схем и есть то
место, где нарушить его удобнее всего.
"""
from __future__ import annotations

import io
import re
import tokenize
import zipfile
from pathlib import Path

import pytest
from docx import Document

import api
from api import modules
from api.modules import artifacts

from .c_fixtures import войти, завести, клиент, хозяин                # noqa: F401

# Две формы, под которыми модулю позволено вешать маршруты. Третьей нет: по этим
# двум его находит и человек, и сайдбар.
ФОРМЫ = ("/{id}", "/projects/{{project_id}}/{id}")


def операции(схема: dict):
    методы = ("get", "post", "put", "patch", "delete")
    for путь, узел in схема["paths"].items():
        for метод, операция in узел.items():
            if метод in методы:
                yield путь, метод, операция


# ── что отдаётся наружу ──────────────────────────────────────────────────────

def test_реестр_отдаёт_только_готовые(клиент, хозяин):
    """Неготовый модуль не помечается флагом, а отсутствует.

    Флаг означал бы, что решение «показывать или нет» принимает интерфейс, — и
    принял бы он его по-своему в каждом месте, где строится меню.
    """
    ответ = клиент.get("/api/modules")
    assert ответ.status_code == 200, ответ.text
    выданные = ответ.json()
    assert [m["id"] for m in выданные] == [m.id for m in modules.all_modules()
                                           if m.ready]
    assert all(not m.ready for m in modules.all_modules()
               if m.id not in {v["id"] for v in выданные})


def test_карточка_модуля_это_три_поля(клиент, хозяин):
    """`{id, title, routes}` — ровно то, из чего строится пункт сайдбара.

    Флага `ready` в карточке нет намеренно: второй способ узнать то же самое
    однажды покажет человеку неготовый модуль.
    """
    for карточка in клиент.get("/api/modules").json():
        assert set(карточка) == {"id", "title", "routes"}
        assert карточка["title"] and карточка["title"].isascii()
        assert карточка["routes"].startswith("/api/")


def test_первые_три_модуля_на_месте(клиент, хозяин):
    """Отчёты, блок-схемы и UML — то, что уже работает. Порядок — порядок
    сайдбара, и он не случайный: отчёты первые, потому что ради них всё."""
    assert [m["id"] for m in клиент.get("/api/modules").json()] == [
        "reports", "flowcharts", "uml"]


def test_пустых_заготовок_не_держим():
    """Решение плана: `cards`, `board`, `asm` появятся строкой, когда появится
    их код. Модуль без роутера при этом законен (`reports` работает маршрутами
    проектов), а модуль без кода — нет."""
    for info, роутер in modules.with_routers():
        assert info.ready, f"неготовый модуль в реестре: {info.id}"
        if роутер is None:
            assert info.id == "reports", info.id


# ── шаблон модуля ────────────────────────────────────────────────────────────

def test_маршруты_модуля_лежат_под_его_префиксом():
    """Иначе `GET /api/modules` врёт: карточка говорит, где искать, а маршруты
    лежат в другом месте."""
    for info, роутер in modules.with_routers():
        if роутер is None:
            continue
        свои = tuple(форма.format(id=info.id) for форма in ФОРМЫ)
        for маршрут in роутер.routes:
            assert маршрут.path.startswith(свои), f"{info.id}: {маршрут.path}"


def test_operation_id_с_префиксом_модуля(app):
    """В клиенте сайта они лежат в одном пространстве имён, и `preview` там
    будет ровно один — иначе генератор оставит какой-нибудь из двух."""
    пути = {}
    for info, роутер in modules.with_routers():
        if роутер is not None:
            for маршрут in роутер.routes:
                пути[маршрут.path] = info.id

    for путь, метод, операция in операции(app.openapi()):
        модуль = пути.get(путь.removeprefix("/api"))
        if модуль is None:
            continue
        assert операция["operationId"].startswith(модуль), \
            f"{метод.upper()} {путь}: {операция['operationId']}"


def test_описания_модулей_английские_и_свои(app):
    """Умолчание FastAPI — русская докстрока обработчика: она написана внутрь
    кода, а уезжает в подсказку метода на сайте."""
    свои = {"modules", "flowcharts", "uml", "artifacts"}
    for путь, метод, операция in операции(app.openapi()):
        if not свои & set(операция.get("tags", ())):
            continue
        где = f"{метод.upper()} {путь}"
        assert операция.get("summary", "").isascii(), где
        assert операция.get("description", ""), где
        assert операция["description"].isascii(), где


def test_реестр_не_растёт_от_числа_приложений(settings):
    """`collect()` зовётся на каждое приложение, а тестов сотни: неидемпотентная
    запись дала бы к третьему приложению три `flowcharts` в сайдбаре."""
    было = len(modules.all_modules())
    api.create_app(settings)
    api.create_app(settings)
    assert len(modules.all_modules()) == было


# ── общее скачивание артефактов ──────────────────────────────────────────────
#
# Маршрут один на трёх производителей: схемы, сборку отчёта и экспорт. Тип он
# определяет по содержимому, потому что имени у артефакта нет вовсе, — и вот
# это определение и проверяется здесь, отдельно от HTTP: тип, угаданный
# неправильно, виден не отказом, а тем, что скачанный файл не открывается.

def docx_байты() -> bytes:
    doc = Document()
    doc.add_paragraph("Отчёт")
    буфер = io.BytesIO()
    doc.save(буфер)
    return буфер.getvalue()


def zip_байты(имена=("материалы/a.py", "схемы/b.xml")) -> bytes:
    буфер = io.BytesIO()
    with zipfile.ZipFile(буфер, "w") as архив:
        for имя in имена:
            архив.writestr(имя, "содержимое")
    return буфер.getvalue()


@pytest.mark.parametrize("данные, ожидаем", [
    (b"<mxfile host=\"app\"><diagram/></mxfile>", "application/xml"),
    (b"<?xml version=\"1.0\"?><mxGraphModel/>", "application/xml"),
    (b"%PDF-1.7\n1 0 obj\n", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff\xe0", "image/jpeg"),
    (b"\x00\x01\x02\x03", "application/octet-stream"),
])
def test_тип_артефакта_по_первым_байтам(данные, ожидаем):
    assert artifacts.вид(данные)[0] == ожидаем


def test_zip_экспорта_не_выдаётся_за_word():
    """Оба начинаются с `PK`, и различает их опись внутри архива.

    Цена ошибки несимметрична: zip, отданный как DOCX, Word откроет и скажет,
    что файл повреждён, — человек решит, что сломалась сборка отчёта, а сломан
    был заголовок.
    """
    assert artifacts.вид(docx_байты()) == artifacts.DOCX
    assert artifacts.вид(zip_байты()) == artifacts.ZIP
    # Битый архив — не наше дело: отдаём как zip, разбирается тот, кто скачал.
    assert artifacts.вид(b"PK\x03\x04not-an-archive") == artifacts.ZIP


def test_расширение_имени_совпадает_с_типом():
    """Имя собирается из идентификатора и расширения: по нему человек различает
    файлы в папке «Загрузки», и расширение обязано соответствовать типу."""
    for данные, (_тип, расширение) in ((docx_байты(), artifacts.DOCX),
                                       (zip_байты(), artifacts.ZIP)):
        assert artifacts.вид(данные)[1] == расширение


# ── правило разреза ──────────────────────────────────────────────────────────

def _код(path: Path) -> str:
    """Исходник без строк и комментариев — как в `tests/kyotsu/test_border.py`.

    Без этого совпало бы упоминание `fragmos` в докстроке, и тест ловил бы
    прозу вместо кода.
    """
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append("\n" if tok.type in (tokenize.NL, tokenize.NEWLINE) else tok.string)
    return "\n".join(out)


def test_служба_зовёт_строителей_схем_только_через_оркестратор():
    """Прямой импорт `fragmos` сюда попадёт не по недосмотру, а мимо решения.

    Цена нарушения не абстрактная: служба, знающая про `fragmos`, перестаёт
    собираться без tree-sitter — и `GET /api/modules` начинает требовать
    грамматик, чтобы отдать три строки JSON.
    """
    корень = Path(api.__file__).parent
    запрещено = re.compile(r"^\s*(?:import (?:fragmos|uml_generator)\b"
                           r"|from (?:fragmos|uml_generator)[.\s])", re.MULTILINE)
    виновные = [str(p.relative_to(корень)) for p in sorted(корень.rglob("*.py"))
                if запрещено.search(_код(p))]
    assert not виновные, виновные
