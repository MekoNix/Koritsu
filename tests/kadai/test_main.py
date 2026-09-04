"""
`python -m kadai`: пять команд и одна чужая функция, собирающая двери.

Главное, что здесь стережётся, — направление зависимости. Имени соседа в пакете
нет ни разу, даже строкой: фабрику дверей называет тот, кто запускает
(`KADAI_SERVICES=модуль:функция`), или передаёт обёртка аргументом
(`main(argv, services_factory=…)`). Тесты пользуются вторым способом и потому
обходятся без окружения вовсе — а заодно проверяют, что подпись, обещанная
обёртке, действительно та, по которой CLI зовёт.

Второе — снимок: `status` печатает ровно ту форму, которую будет отдавать API.
Вторая форма «покрасивее для CLI» разошлась бы с первой молча.
"""
from __future__ import annotations

import json

import pytest

import kadai
from kadai import __main__ as cli

from .conftest import FakeDoors, FakeProject


class ФабрикаДверей:
    """Подделка того, что напишет обёртка в оркестраторе.

    Подпись повторена дословно: `factory(path, *, endpoint, create=False)`.
    Каталог здесь — просто ключ: путей `kadai` не строит, и знать, что это
    каталог, ему незачем.
    """

    def __init__(self):
        self.проекты: dict = {}
        self.двери: dict = {}
        self.вызовы: list = []

    def __call__(self, path, *, endpoint="", create=False):
        self.вызовы.append({"path": path, "endpoint": endpoint, "create": create})
        if create and path in self.проекты:
            raise kadai.KadaiError(f"в {path} уже есть проект")
        if path not in self.проекты:
            if not create:
                raise kadai.KadaiError(f"каталога проекта нет: {path}")
            self.проекты[path] = FakeProject()
            self.двери[path] = FakeDoors(self.проекты[path])
        return self.двери[path].services()


@pytest.fixture
def фабрика():
    return ФабрикаДверей()


@pytest.fixture
def условие_файлом(tmp_path):
    путь = tmp_path / "условие.txt"
    путь.write_text("Написать программу сортировки и отчёт.", encoding="utf-8")
    return str(путь)


def завести(фабрика, tmp_path, условие_файлом, *args):
    код = cli.main(["new", str(tmp_path / "работа"), "--condition", условие_файлом,
                    *args], services_factory=фабрика)
    assert код == 0
    return str(tmp_path / "работа")


def test_new_кладёт_условие_и_заводит_работу(фабрика, tmp_path, условие_файлом, capsys):
    каталог = завести(фабрика, tmp_path, условие_файлом, "--wish", "покороче")
    проект = фабрика.проекты[каталог]
    assert проект.condition() is not None
    assert фабрика.вызовы[0]["create"] is True
    задание = kadai.task(проект)
    assert задание["wishes"]["text"] == "покороче"
    assert "работа w-" in capsys.readouterr().out


def test_run_доводит_до_архива_и_печатает_где_стоим(фабрика, tmp_path, условие_файлом,
                                                    capsys):
    каталог = завести(фабрика, tmp_path, условие_файлом)
    capsys.readouterr()
    assert cli.main(["run", каталог], services_factory=фабрика) == 0
    вывод = capsys.readouterr().out
    assert "done" in вывод and "zip: работа.zip" in вывод


def test_run_до_стадии_останавливается_на_ней(фабрика, tmp_path, условие_файлом):
    каталог = завести(фабрика, tmp_path, условие_файлом)
    cli.main(["run", каталог, "--until", "шаблон"], services_factory=фабрика)
    задание = kadai.task(фабрика.проекты[каталог])
    assert задание.get("structure")               # строение сочинено
    assert not фабрика.двери[каталог].solved      # петля не начиналась


def test_status_печатает_снимок_формы_записки(фабрика, tmp_path, условие_файлом, capsys):
    каталог = завести(фабрика, tmp_path, условие_файлом)
    cli.main(["run", каталог], services_factory=фабрика)
    capsys.readouterr()
    assert cli.main(["status", каталог], services_factory=фабрика) == 0
    снимок = json.loads(capsys.readouterr().out)
    assert set(снимок) >= {"work", "state", "stage", "stages", "current", "hold",
                           "spent", "problems", "outputs", "since", "events",
                           "condition_text"}
    assert снимок["state"] == "done" and снимок["outputs"]["zip"] == "работа.zip"
    # Ни одного пути в снимке: готовые файлы называются именем.
    assert "/" not in json.dumps(снимок["outputs"], ensure_ascii=False)


def test_rework_печатает_маршрут_и_честную_оговорку(фабрика, tmp_path, условие_файлом,
                                                    capsys):
    каталог = завести(фабрика, tmp_path, условие_файлом)
    cli.main(["run", каталог], services_factory=фабрика)
    ключ = [b["key"] for b in фабрика.проекты[каталог].blocks()
            if b["kind"] == "table"][0]
    capsys.readouterr()
    код = cli.main(["rework", каталог, "--note", "добавь колонку", "--block", ключ],
                   services_factory=фабрика)
    вывод = capsys.readouterr().out
    assert код == 0 and "схема" in вывод and "честно:" in вывод


def test_archive_собирает_заново_не_трогая_модель(фабрика, tmp_path, условие_файлом):
    каталог = завести(фабрика, tmp_path, условие_файлом)
    cli.main(["run", каталог], services_factory=фабрика)
    двери = фабрика.двери[каталог]
    было = (len(двери.asked), len(двери.solved), len(двери.texts))
    assert cli.main(["archive", каталог], services_factory=фабрика) == 0
    assert (len(двери.asked), len(двери.solved), len(двери.texts)) == было
    assert фабрика.проекты[каталог]._packed                # архив собран второй раз


def test_без_переменной_окружения_внятный_отказ(monkeypatch, tmp_path, capsys):
    """Умолчания «возьми orchestrator» нет намеренно: это и есть имя соседа в
    коде, только записанное неявно."""
    monkeypatch.delenv(cli.ENV_FACTORY, raising=False)
    код = cli.main(["status", str(tmp_path)])
    assert код == 1 and cli.ENV_FACTORY in capsys.readouterr().err


def test_фабрика_читается_из_окружения(monkeypatch, tmp_path, условие_файлом, capsys):
    monkeypatch.setenv(cli.ENV_FACTORY, "tests.kadai.test_main:_фабрика_из_окружения")
    код = cli.main(["new", str(tmp_path / "из-окружения"),
                    "--condition", условие_файлом])
    assert код == 0 and "заведена" in capsys.readouterr().out


def test_непонятная_фабрика_называет_переменную(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(cli.ENV_FACTORY, "нет.такого:модуля")
    assert cli.main(["status", str(tmp_path)]) == 1
    assert cli.ENV_FACTORY in capsys.readouterr().err


def test_отказ_шва_отличим_от_ошибки_вызывающего(фабрика, tmp_path, условие_файлом,
                                                 capsys):
    """3 — «сосед не готов», 1 — «позвали неправильно». Путать их нельзя:
    первое чинится не здесь и ждёт."""
    каталог = завести(фабрика, tmp_path, условие_файлом)
    двери = фабрика.двери[каталог]
    фабрика.двери[каталог] = _БезПроверкиКода(двери)
    assert cli.main(["run", каталог], services_factory=фабрика) == 3
    assert "check_code" in capsys.readouterr().err


class _БезПроверкиКода:
    """Двери без `check_code` — так выглядит сегодняшняя жизнь: двери ещё нет."""

    def __init__(self, двери):
        self.двери = двери

    def services(self):
        return self.двери.services(check_code=None)


_ОБЩАЯ = ФабрикаДверей()


def _фабрика_из_окружения(path, *, endpoint="", create=False):
    """Фабрика, которую тест находит по имени модуля — как её найдёт `python -m kadai`."""
    return _ОБЩАЯ(path, endpoint=endpoint, create=create)
