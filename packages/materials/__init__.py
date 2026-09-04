"""
materials — хранилище материалов пользователя и сборка контекста для модели.

Материалы бывают любые: методичка в PDF, отчёт о продажах в CSV, конспект по
химии, скриншот прибора, исходник программы. Пакет ничего не знает о предметной
области — он умеет только «сохранить, разобрать, показать коротко, отдать кусок».

    store = Store("проект/материалы")
    store.add("методичка.docx")           # разбор считается один раз
    print(store.inventory())              # опись — это и есть промпт по умолчанию
    ctx = build_context(store, [("a1b2…", 4, 6)])   # плюс запрошенные куски
    print(ctx.tokens)                     # грубая оценка стоимости

Два решения, на которых держится пакет:

  * Картинки модели не отдаём. У пользователя их бывает 40–60, зрение на таком
    объёме стоит слишком дорого. С картинки берём распознанный текст (OCR) и
    короткую карточку, а сама картинка остаётся файлом и вставляется в отчёт по
    идентификатору (`store.path(id)` / `store.blob(id)`).
  * Токены дороги. В промпт по умолчанию уходят только карточки; полный текст
    модель запрашивает сама, кусками, и каждый кусок приходит с якорем.

Значения полей — коды по-английски (`kind`: text/pdf/docx/image/unknown,
`unit`: line/page/paragraph, `lang`: cyrillic/latin/mixed): они уходят в данные — в карточку службы, в ответ
инструмента модели, в `meta.json` на томе. Подписи для человека лежат рядом с
кодами (`KIND_WORDS`, `UNIT_WORDS`), и по ним пишутся карточка и якорь: якорь
уезжает в отчёт студента, и «page 4» там был бы опиской, а не переводом.

OCR — системный tesseract подпроцессом, если он установлен. Если нет — материал
сохраняется, разбор не падает, в карточке честно написано «текст не распознан».
Тяжёлых зависимостей (torch, paddle) в пакете нет и не будет.
"""
from .cards import card, human_size, inventory
from .context import (CHARS_PER_TOKEN_DEFAULT, Context, Request, build_context,
                      estimate_tokens)
from .model import (Card, Chunk, Derived, Material, MaterialsError, Parsed, anchor,
                    KIND_DOCX, KIND_IMAGE, KIND_PDF, KIND_TEXT, KIND_UNKNOWN,
                    KIND_WORDS, LANG_CYRILLIC, LANG_LATIN, LANG_MIXED, LANG_WORDS,
                    UNIT_LINE, UNIT_MANY, UNIT_PAGE, UNIT_PARAGRAPH, UNIT_WORDS)
from ._parse import parse, supported
from .store import Store, material_id
from . import ocr

__all__ = [
    "Store", "material_id",
    "Material", "Card", "Chunk", "Parsed", "Derived", "MaterialsError", "anchor",
    "KIND_TEXT", "KIND_PDF", "KIND_DOCX", "KIND_IMAGE", "KIND_UNKNOWN",
    "UNIT_LINE", "UNIT_PAGE", "UNIT_PARAGRAPH",
    "LANG_CYRILLIC", "LANG_LATIN", "LANG_MIXED",
    "KIND_WORDS", "LANG_WORDS", "UNIT_WORDS", "UNIT_MANY",
    "parse", "supported", "card", "inventory", "human_size",
    "build_context", "estimate_tokens", "Context", "Request", "ocr",
    "CHARS_PER_TOKEN_DEFAULT",
]
