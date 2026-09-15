"""
cards_generate — агент пишет набор карточек в черновик человека.

    payload   {"endpoint": "deepseek", "draft_id": "<32hex>", "append": false,
               "workspace_id": "<uuid>",
               "target": {"project_id": "<uuid>", "set_id": "<uuid>"} | null,
               "prompt": "…", "questions": "…", "material_ids": ["<16hex>", …],
               "count": 40, "per_topic": null, "length": "short" | "full",
               "language": "ru", "topic": "Интеграл Римана" | null}
    result    {"draft_id": "<32hex>", "outcome": "done", "title": "…",
               "language": "ru", "stats": {"cards": 40, "topics": 5, …},
               "problems": 0, "usage": {…}, "run_id": "…", "key_source": "own"}

**Черновик заводит постановка** (`POST /api/cards/generate`), пустым и со
статусом `running`; задание его заполняет. Текст черновика — файл JSON набора
(`docs/cards-format.md`), тот же, что при загрузке. Пишется он по ходу работы — после
каждой разобранной части, — поэтому отменённое или оборванное задание оставляет
в черновике то, что успело. Статус черновика в конце: `done`, `cancelled` или
`failed` со словами беды.

**Догенерация** — тот же вид: `append` означает, что черновик уже был, и агент
получает его текст (`append_to`) и тему (`topic`), а возвращает текст черновика
целиком.

**Материалы — файлы неявной работы «Тренажёр»**, разобранные обычным заданием
`parse`. Тексты берутся из хранилища работы и режутся по потолку знаков на файл.

**Промпт, разбиение входа, разбор и переспрос частей — у оркестратора**
(`orchestrator.cards_agent`): служба называет вход и черновик и не строит ни
одного куска промпта. Ключ поставщика расшифровывается `keys.resolve_key` в
обрамлении прогона (`common.Прогон`), и агент получает зарегистрированный
endpoint, а не ключ текстом.

**События потока.** `progress` — карточек готово из заказанных, `note` — тема
(«тема 2 из 5 · Название»); `text` — по ходу. Терминальные события пишет воркер.
"""
from __future__ import annotations

from ...errors import ApiError, NOT_FOUND
from ...jobs.registry import CARDS_GENERATE, register
from .common import Прогон, беда_словами, отменено

CARDS_GENERATE_FAILED = "cards_generate_failed"

# Исходы агента, после которых черновик считается написанным.
ГОДНЫЕ_ИСХОДЫ = ("done", "interrupted")


def _тексты_материалов(ctx, ids, предел: int) -> list[dict]:
    """Материалы работы по идентификаторам → `[{id, name, text}]`."""
    склад = ctx.project.store()
    out = []
    for mid in ids or ():
        try:
            материал = склад.get(str(mid))
            текст = склад.read(материал.id).text or ""
        except Exception:                                    # noqa: BLE001
            raise ApiError(NOT_FOUND, f"Material {mid} is not here", 404,
                           where="body.payload.material_ids") from None
        out.append({"id": материал.id, "name": материал.name,
                    "text": текст[:предел]})
    return out


def _название_набора(ctx, цель) -> str:
    """Название набора, который дополняют. Нет цели или беда — пусто."""
    if not isinstance(цель, dict) or not цель.get("set_id"):
        return ""
    import orchestrator                                          # noqa: PLC0415
    from orchestrator import cards as набор                      # noqa: PLC0415

    from ...projects.service import project_dir                  # noqa: PLC0415

    try:
        with ctx.session_scope() as s:
            каталог = project_dir(s, ctx.settings, str(цель["project_id"]))
        вид = orchestrator.Project(каталог).for_solution(str(цель["set_id"]))
        _, карточки = набор.read_set(вид)
        return карточки.title if карточки is not None else ""
    except Exception:                                            # noqa: BLE001
        return ""


def сгенерировать(ctx) -> dict:
    """Позвать агента и записать написанное в черновик."""
    from ...modules.cards.routes import (ИДЁТ, НЕ_ВЫШЛО,          # noqa: PLC0415
                                         ОТМЕНЁН, СДЕЛАН, черновики, сводка)
    from orchestrator import cards as набор                      # noqa: PLC0415

    payload = ctx.job.payload or {}
    settings = ctx.settings
    drafts = черновики(settings, ctx.job.user_id)
    ид = str(payload.get("draft_id") or "")
    мета = drafts.read(ид) if drafts.exists(ид) else None
    if мета is None:
        raise ApiError(NOT_FOUND, "Draft not found", 404,
                       where="body.payload.draft_id")

    def записать(текст, проблемы=None, stats=None) -> None:
        """Колбэк агента: текст черновика целиком после очередной части."""
        drafts.update(ид, text=str(текст or ""), status=ИДЁТ,
                      stats=dict(stats or {}))

    try:
        материалы = _тексты_материалов(ctx, payload.get("material_ids"),
                                       settings.cards_material_chars_max)
        потолок = settings.cards_generate_max
        params = {
            "prompt": str(payload.get("prompt") or ""),
            "questions": str(payload.get("questions") or ""),
            "materials": материалы,
            "count": min(int(payload.get("count") or 1), потолок),
            "per_topic": (min(int(payload["per_topic"]), потолок)
                          if payload.get("per_topic") else None),
            "length": "full" if payload.get("length") == "full" else "short",
            "language": str(payload.get("language") or "ru"),
            "title": _название_набора(ctx, payload.get("target")),
            "append_to": drafts.text(ид) if payload.get("append") else "",
            "topic": payload.get("topic") or None,
        }
        with Прогон(ctx) as прогон:
            ctx.progress(0, int(params["count"]), note="")
            if ctx.cancelled():
                drafts.update(ид, status=ОТМЕНЁН)
                return отменено(ctx, "cards")
            from orchestrator.cards_agent import generate        # noqa: PLC0415

            итог = generate(params, endpoint=прогон.ep, project=прогон.project,
                            progress=ctx.progress, emit=ctx.emit,
                            cancelled=прогон.отмена, write_draft=записать,
                            draft_path=drafts.path(ид))
            источник = прогон.источник
    except ApiError as беда:
        drafts.update(ид, status=НЕ_ВЫШЛО, error=беда.message
                      if hasattr(беда, "message") else str(беда))
        raise
    except Exception as беда:                                    # noqa: BLE001
        слова = беда_словами(беда)
        drafts.update(ид, status=НЕ_ВЫШЛО, error=слова)
        raise ApiError(CARDS_GENERATE_FAILED, слова, 422,
                       where="body.payload") from None

    итог = итог if isinstance(итог, dict) else {}
    исход = str(итог.get("outcome") or ("done" if итог.get("ok") else "error"))
    текст = итог.get("text")
    if isinstance(текст, str):
        drafts.update(ид, text=текст)
    текст = drafts.text(ид)
    карточки, проблемы = набор.parse_draft(текст, str(мета.get("filename") or ""))
    числа = сводка(карточки, проблемы)
    имя = str(итог.get("title") or "")

    if исход == "cancelled" or ctx.cancelled():
        drafts.update(ид, status=ОТМЕНЁН, stats=числа, title=имя)
    elif исход in ГОДНЫЕ_ИСХОДЫ or числа["cards"]:
        drafts.update(ид, status=СДЕЛАН, stats=числа, title=имя,
                      error=None if исход == "done" else исход)
    else:
        слова = ("Агент не написал ни одной карточки"
                 if исход != "refused" else "Модель отказалась отвечать")
        drafts.update(ид, status=НЕ_ВЫШЛО, stats=числа, error=слова)
        raise ApiError(CARDS_GENERATE_FAILED, слова, 422, where="body.payload")

    return {"draft_id": ид, "outcome": исход, "title": имя,
            "language": str(итог.get("language") or params["language"]),
            "stats": числа, "problems": len(проблемы),
            "usage": dict(итог.get("usage") or {}),
            "run_id": итог.get("run_id"), "key_source": источник}


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(CARDS_GENERATE, needs_secret=True)(сгенерировать)


__all__ = ["сгенерировать", "_зарегистрировать", "CARDS_GENERATE_FAILED"]
