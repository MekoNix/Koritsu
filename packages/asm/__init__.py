"""
asm — модуль «Ассемблер»: настоящий TASM + TLINK в DOSBox-X и трасса отладчиком DebugX.

Пакет уровня ядра: из проекта не импортирует ничего, только стандартную библиотеку (как
`kokuban`). Службе он отдаёт три действия и формы ответа:

    find_tools(env)                              где DOSBox-X, TASM/TLINK и DebugX; None — нет
    build(req, tools, workdir, timeout_s)        сборка: сообщения, листинг, карта, символы
    run(req, tools, workdir, timeout_s, …)       сборка → трасса целиком за один прогон
    memory_at(req, tools, workdir, step, ranges) память на шаге перезапуском до него

**Один прогон — вся трасса.** Браузер ходит по шагам сам: вперёд, назад, до курсора. Сервер
не держит живой отладчик на каждый клик — DOS-программа детерминирована, и трасса, снятая один
раз, отвечает на любой вопрос о шаге. Паузы нет; её место занимает лимит шагов. Ввод программы
задаётся заранее и подаётся ровно в те шаги, где программа читает.

**Почему DebugX, а не Turbo Debugger.** Turbo Debugger полноэкранный: у него нет ни команд из
файла, ни вывода в файл. DebugX читает команды из stdin, пишет в stdout, показывает 32-битные
регистры — и в пакетном DOSBox-X это ровно сценарий и его запись.

Состав пакета:

    tools.py     поиск инструментов
    model.py     формы ответа (dataclass + to_json)
    tasm.py      сообщения TASM/TLINK, листинг, таблица символов
    linkmap.py   карта TLINK: сегменты, точка входа
    debugx.py    разбор вывода DebugX потоком
    feed.py      ввод программы: где читает и что подать
    dosbox.py    запуск DOSBox-X с потолками
    runner.py    сборка, трасса с перезапусками ради ввода, память на шаге
    samples/     настоящий вывод DebugX в DOSBox-X, по которому написан разборщик
"""
from __future__ import annotations

from .model import (BuildMessage, BuildResult, Dump, ListingLine, MemWrite, RunRequest,
                    RunResult, Segment, Step, Symbol, Truncation)
from .runner import АсмОшибка, build, memory_at, run
from .tools import Tools, find_tools

__all__ = ["Tools", "find_tools", "RunRequest", "RunResult", "BuildResult", "BuildMessage",
           "ListingLine", "Segment", "Symbol", "Step", "MemWrite", "Truncation", "Dump",
           "build", "run", "memory_at", "АсмОшибка"]
