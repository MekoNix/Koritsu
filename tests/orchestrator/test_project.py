"""
Состояние проекта: версии значений, артефакты, журнал.

Стережётся здесь ровно то, ради чего проект вообще заведён отдельным объектом:
запись значения не теряет предыдущее, «кто поставил» не выдумывается, а расход
переживает перезапуск процесса.
"""
from __future__ import annotations

import hashlib
import os
import pathlib

import pytest

import llm
import materials
import orchestrator
from orchestrator.errors import OrchestratorError

from .conftest import markdown_value, template_bytes


def test_создание_даёт_манифест_по_тегам_шаблона(tmp_path):
    p = orchestrator.Project.create(str(tmp_path / "п"), template=template_bytes())
    assert list(p.manifest().tags) == ["цель", "введение", "таблица"]
    # Шаблон — обычный артефакт: особого пути к нему нет, достаётся тем же
    # resolve_artifact, что и картинки.
    assert p.resolve_artifact(p.template_artifact()) == p.template()


def test_версия_растёт_а_прошлая_читается(project):
    первая = project.set_value("цель", markdown_value("первый текст"), source="agent",
                               run="r1")
    вторая = project.set_value("цель", markdown_value("второй текст"), source="manual")
    assert (первая.n, вторая.n) == (1, 2)
    # Текущее значение — последнее...
    assert project.value("цель")["text"] == "второй текст"
    # ...а прошлое не потеряно и читается по номеру.
    шапка, значение = project.version("цель", 1)
    assert значение["text"] == "первый текст"
    assert (шапка.source, шапка.run) == ("agent", "r1")
    assert [v.n for v in project.versions("цель")] == [1, 2]
    assert [v.source for v in project.versions("цель")] == ["agent", "manual"]


def test_создание_поверх_проекта_не_стирает_решений(tmp_path):
    """`create` звала `manifest_from_template` без `base`, и повторный вызов
    сносил промпты, лимиты, `depends_on` и поправленные типы: значения при этом
    оставались и ссылались на решения, которых больше нет."""
    root = str(tmp_path / "п")
    p = orchestrator.Project.create(root, template=template_bytes())
    m = p.manifest()
    m.tags["цель"].prompt = "Сформулируй цель работы"
    p.save_manifest(m)

    with pytest.raises(OrchestratorError) as exc:
        orchestrator.Project.create(root, template=template_bytes())
    # Отказ, а не молчаливое обновление: «создать» и «сменить шаблон» — разные
    # намерения, и второе обязано звучать вслух.
    assert "update_template" in str(exc.value)
    assert p.manifest().tags["цель"].prompt == "Сформулируй цель работы"


def test_смена_шаблона_бережёт_решения_человека(project):
    """Политика hokoku: тег убрали — ставим `missing`, но НЕ удаляем, потому что
    промпт и значения обязаны пережить случайную правку шаблона в Word."""
    m = project.manifest()
    m.tags["цель"].prompt = "Сформулируй цель работы"
    project.save_manifest(m)
    было = project.manifest().manifest_version

    новый_шаблон = template_bytes(tags=("цель", "выводы"))
    project.update_template(новый_шаблон)

    m = project.manifest()
    assert m.tags["цель"].prompt == "Сформулируй цель работы"
    assert m.tags["введение"].missing is True and m.tags["таблица"].missing is True
    assert "выводы" in m.tags
    assert m.manifest_version > было
    assert m.template_sha256 == hashlib.sha256(новый_шаблон).hexdigest()
    assert project.template() == новый_шаблон


def test_счётчик_правок_манифеста_растёт(project):
    """`manifest_version` уезжает в шапку каждой версии значения и в задание
    сборки и отвечает на вопрос «по какому манифесту это получено». Постоянная
    единица отвечала на него неверно — а выглядела как ответ."""
    assert project.manifest().manifest_version == 1
    m = project.manifest()
    m.tags["цель"].prompt = "Сформулируй цель работы"
    project.save_manifest(m)
    assert project.manifest().manifest_version == 2

    # Счётчик считает правки, а не сохранения: запись без изменений его не двигает,
    # иначе «версия 7» ничего не сказала бы про то, менялось ли что-нибудь.
    project.save_manifest(project.manifest())
    assert project.manifest().manifest_version == 2


def test_второй_писатель_не_затирает_первого(project, monkeypatch):
    """Номер версии читается по каталогу, а потом пишется файл: между чтением и
    записью успевает второй писатель, и `os.replace` — атомарный и потому
    бесшумный — затирает первую версию целиком. Замер на двух процессах: 120
    записей → 76 файлов, ни одной ошибки.

    Гонка здесь не разыгрывается потоками (тогда тест был бы то красным, то
    зелёным), а воспроизводится точно: `_head` возвращает устаревшее значение —
    ровно то, что видит писатель, опоздавший на чужую запись."""
    monkeypatch.setattr(orchestrator.Project, "_head", lambda self, folder: None)

    project.set_value("цель", markdown_value("первый"), source="manual")
    project.set_value("цель", markdown_value("второй"), source="agent")

    # Обе версии на месте: столкновение забирает следующий номер, а не чужой файл.
    assert [v.n for v in project.versions("цель")] == [1, 2]
    assert [project.version("цель", n)[1]["text"] for n in (1, 2)] == ["первый", "второй"]
    assert [v.source for v in project.versions("цель")] == ["manual", "agent"]


def test_вернуть_старую_версию_это_новая_версия(project):
    project.set_value("цель", markdown_value("хорошее"), source="agent")
    project.set_value("цель", markdown_value("плохое"), source="agent")
    вернули = project.rollback("цель", 1)
    assert вернули.n == 3                      # номер растёт, а не уменьшается
    assert project.value("цель")["text"] == "хорошее"
    # «Вернуть» видно в истории: иначе двое, глядя на «версию 3», видели бы разное.
    assert any("вернули версию 1" in f for f in вернули.flags)
    assert project.version("цель", 2)[1]["text"] == "плохое"


def test_неизвестный_source_отказ_с_подсказкой(project):
    with pytest.raises(OrchestratorError) as exc:
        project.set_value("цель", markdown_value("текст"), source="agnet")
    assert "agent" in str(exc.value)


def test_ключ_тега_не_становится_путём(project):
    """Ключ приходит снаружи; каталог из него не должен уводить за пределы проекта."""
    m = project.manifest()
    m.tags["../побег"] = m.tags["цель"]
    project.save_manifest(m)
    project.set_value("../побег", markdown_value("текст"), source="manual")
    assert project.value("../побег")["text"] == "текст"
    # Ключ восстанавливается из шапки версии, а не из имени каталога.
    assert "../побег" in project.keys()
    written = [d.name for d in (pathlib.Path(project.path) / "values").iterdir()]
    assert all(".." not in name and "/" not in name for name in written)
    # Главное — не имя, а куда оно ведёт: каждый каталог значений обязан
    # разрешаться внутрь проекта. Прежняя проверка (`(path + "/..")` не
    # кончается на «побег») была тавтологией и оставалась истинной при любом
    # коде — то есть побег из проекта она пропустила бы молча.
    корень = pathlib.Path(project.path).resolve(strict=True)
    for каталог in (pathlib.Path(project.path) / "values").iterdir():
        assert корень in каталог.resolve(strict=True).parents


def test_поломка_материалов_не_выдаётся_за_пропажу_артефакта(project, monkeypatch):
    """`resolve_artifact` глушил ЛЮБОЕ исключение материалов и отвечал «артефакта
    нет ни в материалах, ни в artifacts/». Цена: настоящая ошибка ввода-вывода
    выглядит как опечатка в идентификаторе, и человек ищет пропавший файл вместо
    того, чтобы чинить диск."""
    material = project.store().list()[0]

    def взрыв(self, mid):
        # Хранилище отвечает как настоящее: своё — сломанным диском, чужое —
        # «материала нет». Различить их и обязан `resolve_artifact`.
        if mid == material.id:
            raise OSError("ошибка чтения с диска")
        raise materials.MaterialsError(f"материал не найден: {mid}")

    monkeypatch.setattr(materials.Store, "blob", взрыв)
    with pytest.raises(OSError):
        project.resolve_artifact(material.id)

    # А «в материалах такого нет» по-прежнему не беда: ищем дальше, в artifacts/.
    art = project.put_artifact(b"<mxfile/>")
    assert project.resolve_artifact(art) == b"<mxfile/>"


def test_артефакт_ищется_и_в_материалах_и_в_artifacts(project):
    material = project.store().list()[0]
    assert project.resolve_artifact(material.id).startswith(b"def ")
    art = project.put_artifact(b"<mxfile/>", name="схема")
    assert project.resolve_artifact(art) == b"<mxfile/>"
    # Адресация по содержимому: те же байты — тот же идентификатор.
    assert project.put_artifact(b"<mxfile/>") == art
    with pytest.raises(OrchestratorError):
        project.resolve_artifact("нетакого")


def test_журнал_переживает_перезапуск(project):
    """Расход считается по журналу; забудь его при открытии — месячный потолок
    сбрасывался бы каждым запуском процесса."""
    spec = llm.EndpointSpec(id="ep", protocol="openai",
                            base_url="https://x.invalid", model="m")
    result = llm.Result(ok=True, endpoint="ep", model="m")
    result.units = 42.0
    project.journal().add(result, spec, {"run": "r1"})

    другой = orchestrator.Project(project.path)
    assert len(другой.journal().entries) == 1
    assert другой.journal().total_units() == 42.0
    assert другой.spent()["calls"] == 1


def test_лимит_считает_прошлый_расход(project):
    settings = project.settings()
    settings["cap_units"] = 100.0
    project.save_settings(settings)
    assert project.limit().remaining() == 100.0

    spec = llm.EndpointSpec(id="ep", protocol="openai",
                            base_url="https://x.invalid", model="m")
    result = llm.Result(ok=True, endpoint="ep", model="m")
    result.units = 90.0
    project.journal().add(result, spec, None)
    assert project.limit().remaining() == 10.0


def test_прогон_записывается_с_меткой(project):
    run = project.start_run(level=2, endpoint="ep_test")
    run.mark = "abcdef123456"
    project.save_run(run)
    project.finish_run(run, "done")
    прочитан = project.run(run.id)
    assert (прочитан.mark, прочитан.outcome, прочитан.level) == ("abcdef123456", "done", 2)


def test_проект_без_шаблона_строит_документ_сам(tmp_path):
    """`template=None` — «проект без шаблона»: документ с нуля, а не отказ.

    Нужно это службе (`api`): человек, у которого методички под рукой нет,
    всё равно заводит проект. Знание о том, как выглядит документ с нуля, лежит
    здесь, а не в службе, — она про `hokoku` не знает и знать не должна.
    """
    p = orchestrator.Project.create(str(tmp_path / "пусто"), name="без шаблона")

    # Тегов в построенном документе нет, значит и манифест пуст: заполнять
    # нечего, пока человек не принёс свой шаблон.
    assert list(p.manifest().tags) == []
    # Происхождение записано: пустой документ можно молча заменить принесённым,
    # чужой — нельзя, там решения человека.
    assert p.settings()["template_source"] == "blank"
    assert p.resolve_artifact(p.template_artifact()) == p.template()

    # И это настоящий DOCX: он собирается и открывается.
    итог = orchestrator.build(p)
    assert итог["ok"] is True
    путь = os.path.join(итог["workdir"], итог["report"]["outputs"]["docx"]["file"])
    assert os.path.isfile(путь)

    # А принесённый потом шаблон снимает пометку «наш».
    p.update_template(template_bytes())
    assert p.settings()["template_source"] == "given"
    assert list(p.manifest().tags) == ["цель", "введение", "таблица"]
