"""
Python backend для objektis: запуск кода в subprocess + сбор графа объектов
через gc.get_objects() в дочернем процессе.

Изоляция через subprocess нужна для безопасности (user code arbitrary) и
устойчивости (sys.exit, бесконечные циклы → timeout).
"""
import json
import os
import subprocess
import sys
import tempfile

from .model import ObjectGraph, ObjectInstance, ObjectLink, Slot


_RUNNER_PATH = os.path.join(os.path.dirname(__file__), "_runner.py")


def extract(source: str, *, timeout: float = 10.0) -> ObjectGraph:
    """
    Запустить Python-исходник в subprocess, собрать ObjectGraph.

    На любой ошибке возвращает граф с заметкой в .notes (не падает).
    """
    if not source or not source.strip():
        return ObjectGraph(notes=["objektis/python: пустой исходник"])

    with tempfile.TemporaryDirectory(prefix="objektis_") as tmp:
        user_path = os.path.join(tmp, "main.py")
        dump_path = os.path.join(tmp, "dump.json")
        with open(user_path, "w", encoding="utf-8") as f:
            f.write(source)

        try:
            proc = subprocess.run(
                [sys.executable, _RUNNER_PATH, user_path, dump_path],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ObjectGraph(notes=[
                f"objektis/python: timeout ({timeout}s) — код не завершился",
            ])
        except FileNotFoundError as e:
            return ObjectGraph(notes=[f"objektis/python: {e}"])

        if not os.path.isfile(dump_path):
            err_tail = (proc.stderr or "").strip().splitlines()[-3:]
            return ObjectGraph(notes=[
                f"objektis/python: runner не создал дамп (rc={proc.returncode})",
                *err_tail,
            ])

        try:
            with open(dump_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return ObjectGraph(notes=[f"objektis/python: парсинг dump.json: {e}"])

    return _from_payload(payload)


def _from_payload(payload: dict) -> ObjectGraph:
    """Превратить JSON-дамп от _runner в ObjectGraph."""
    instances = []
    for raw in payload.get("instances", []):
        slots = [
            Slot(name=s.get("name", ""), value=s.get("value", ""))
            for s in raw.get("slots", [])
        ]
        instances.append(ObjectInstance(
            name=raw.get("name", ""),
            type_name=raw.get("type_name", ""),
            slots=slots,
            multiplicity=raw.get("multiplicity", ""),
            is_summary=bool(raw.get("is_summary", False)),
        ))

    links = []
    for raw in payload.get("links", []):
        links.append(ObjectLink(
            source=raw.get("source", ""),
            target=raw.get("target", ""),
            label=raw.get("label", ""),
            kind=raw.get("kind", "association"),
        ))

    return ObjectGraph(
        instances=instances, links=links,
        notes=list(payload.get("notes", [])),
    )
