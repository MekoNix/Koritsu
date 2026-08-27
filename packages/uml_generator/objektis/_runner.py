"""
Standalone runner для objektis Python backend.

Вызывается как:
    python -m uml_generator.objektis._runner <user_main.py> <dump.json>

или напрямую:
    python _runner.py <user_main.py> <dump.json>

Делает следующее:
  1. exec'ает user_main.py в свежем namespace с __name__='__main__'.
  2. После выполнения собирает все instance'ы пользовательских классов
     (тех, что определены в __main__) через gc.get_objects().
  3. Сериализует граф в JSON и пишет в dump.json.

Никогда не пробрасывает исключения наружу — даже при крахе user-кода
пытается дампнуть то, что есть. Возвращает 0 если дамп записан, 1 иначе.
"""
import gc
import json
import sys
import traceback


_MAX_VALUE_LEN = 60


def _fmt_scalar(v) -> str:
    """Печать примитивных значений в человекочитаемом виде, обрезая длину."""
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        s = repr(v)
        if len(s) > _MAX_VALUE_LEN:
            s = s[: _MAX_VALUE_LEN - 3] + "...'"
        return s
    if isinstance(v, bytes):
        s = repr(v)
        if len(s) > _MAX_VALUE_LEN:
            s = s[: _MAX_VALUE_LEN - 3] + "...'"
        return s
    return f"<{type(v).__name__}>"


def _walk_value(value, owner_name: str, field_name: str,
                named: dict, links: list) -> str:
    """
    Превращает значение поля в человекочитаемую строку и
    регистрирует links/containment'ы в общий список.
    """
    if id(value) in named:
        target = named[id(value)]
        links.append({
            "source": owner_name, "target": target,
            "label": field_name, "kind": "association",
        })
        return f"→ {target}"

    if isinstance(value, (list, tuple)):
        bracket_l, bracket_r = ("[", "]") if isinstance(value, list) else ("(", ")")
        parts = []
        for i, item in enumerate(value):
            if id(item) in named:
                target = named[id(item)]
                links.append({
                    "source": owner_name, "target": target,
                    "label": f"{field_name}[{i}]", "kind": "containment",
                })
                parts.append(f"→{target}")
            else:
                parts.append(_fmt_scalar(item))
            if i >= 4 and len(value) > 5:
                parts.append(f"...({len(value)})")
                break
        return bracket_l + ", ".join(parts) + bracket_r

    if isinstance(value, dict):
        parts = []
        for i, (k, item) in enumerate(value.items()):
            key_repr = _fmt_scalar(k)
            if id(item) in named:
                target = named[id(item)]
                links.append({
                    "source": owner_name, "target": target,
                    "label": f"{field_name}[{key_repr}]", "kind": "containment",
                })
                parts.append(f"{key_repr}: →{target}")
            else:
                parts.append(f"{key_repr}: {_fmt_scalar(item)}")
            if i >= 3 and len(value) > 4:
                parts.append(f"...({len(value)})")
                break
        return "{" + ", ".join(parts) + "}"

    if isinstance(value, set):
        parts = []
        for i, item in enumerate(value):
            if id(item) in named:
                target = named[id(item)]
                links.append({
                    "source": owner_name, "target": target,
                    "label": field_name, "kind": "containment",
                })
                parts.append(f"→{target}")
            else:
                parts.append(_fmt_scalar(item))
            if i >= 4 and len(value) > 5:
                parts.append(f"...({len(value)})")
                break
        return "{" + ", ".join(parts) + "}"

    return _fmt_scalar(value)


def _read_state(obj) -> dict:
    """Достать поля инстанса: __dict__ если есть, иначе __slots__."""
    if hasattr(obj, "__dict__"):
        try:
            return dict(obj.__dict__)
        except Exception:
            pass
    if hasattr(type(obj), "__slots__"):
        result = {}
        for s in getattr(type(obj), "__slots__", ()):
            try:
                result[s] = getattr(obj, s)
            except AttributeError:
                pass
        return result
    return {}


def _collect(ns: dict, notes: list) -> dict:
    """
    Сборка графа из namespace после exec().
    ns — модульный dict, в котором выполнялся пользовательский код.
    """
    user_classes = set()
    for v in ns.values():
        if isinstance(v, type) and v.__module__ == "__main__":
            user_classes.add(v)

    if not user_classes:
        notes.append("В коде не найдено пользовательских классов")
        return {"instances": [], "links": [], "notes": notes}

    # Предварительно даём имена тем инстансам, что лежат прямо в namespace.
    named: dict[int, str] = {}
    for name, v in ns.items():
        if name.startswith("_"):
            continue
        if type(v) in user_classes:
            named[id(v)] = name

    # Все остальные инстансы достаём через gc.
    gc.collect()
    all_insts = []
    seen_ids = set()
    for obj in gc.get_objects():
        if type(obj) in user_classes and id(obj) not in seen_ids:
            seen_ids.add(id(obj))
            all_insts.append(obj)

    # Auto-имена для тех, что не в namespace.
    counters: dict[str, int] = {}
    for obj in all_insts:
        if id(obj) in named:
            continue
        type_name = type(obj).__name__
        counters[type_name] = counters.get(type_name, 0) + 1
        named[id(obj)] = f"{type_name[:1].lower()}{type_name[1:]}{counters[type_name]}"

    # Собираем slots + links.
    instances = []
    links: list = []
    for obj in all_insts:
        name = named[id(obj)]
        slots = []
        state = _read_state(obj)
        for fname, fval in state.items():
            value_repr = _walk_value(fval, name, fname, named, links)
            slots.append({"name": fname, "value": value_repr})
        instances.append({
            "name": name,
            "type_name": type(obj).__name__,
            "slots": slots,
            "multiplicity": "",
            "is_summary": False,
        })

    # Дедуп links: (source, target, label) уникальны.
    seen = set()
    deduped = []
    for link in links:
        key = (link["source"], link["target"], link["label"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)

    return {"instances": instances, "links": deduped, "notes": notes}


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: _runner.py <user_main.py> <dump.json>", file=sys.stderr)
        return 1
    user_path, dump_path = sys.argv[1], sys.argv[2]

    notes: list = []
    ns: dict = {"__name__": "__main__", "__builtins__": __builtins__}

    try:
        with open(user_path, encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        notes.append(f"не удалось прочитать {user_path}: {e}")
        graph = {"instances": [], "links": [], "notes": notes}
    else:
        try:
            compiled = compile(code, user_path, "exec")
            exec(compiled, ns)
        except SystemExit:
            pass
        except BaseException:
            tb = traceback.format_exc(limit=3)
            notes.append(f"user code raised: {tb.splitlines()[-1] if tb else '?'}")
        graph = _collect(ns, notes)

    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False)
    except OSError as e:
        print(f"failed to write dump: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
