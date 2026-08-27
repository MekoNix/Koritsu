"""
C# backend для objektis: source-rewriting Main() через tree-sitter +
helper-класс на C#, компиляция и запуск через `dotnet run`, парсинг JSON-дампа.

Алгоритм:
  1. Парсим студенческий код tree-sitter'ом.
  2. Находим метод Main() — точку входа.
  3. В теле Main вставляем:
     • после каждой локальной декларации   →  __Objektis.Track("name", name);
     • оборачиваем всё тело в try/finally  →  гарантирует Dump() даже при exception
  4. Дописываем рядом __Objektis.cs — статический helper, который через
     reflection обходит все tracked-инстансы + transitively reachable user-type
     объекты, пишет JSON в файл по пути из env OBJEKTIS_DUMP.
  5. Создаём временный .csproj, dotnet run, читаем JSON.
"""
import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .model import ObjectGraph, ObjectInstance, ObjectLink, Slot


# ── Helper C# code (записывается рядом со студенческими файлами) ──────────────

_HELPER_CS = r"""
// Вспомогательный класс для objektis.
// Сгенерирован автоматически. Не редактировать вручную.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.Json;

internal static class __Objektis
{
    static readonly List<KeyValuePair<string, object>> _named = new();
    static readonly Dictionary<int, string> _idToName = new();

    static int IdOf(object o) =>
        System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(o);

    public static T Track<T>(string name, T obj)
    {
        if (obj == null) return obj;
        if (!IsUserType(obj)) return obj;
        var id = IdOf(obj);
        if (!_idToName.ContainsKey(id))
        {
            _named.Add(new KeyValuePair<string, object>(name, obj));
            _idToName[id] = name;
        }
        return obj;
    }

    static bool IsUserType(object o)
    {
        if (o == null) return false;
        var t = o.GetType();
        if (t.IsPrimitive || t == typeof(string) || t.IsEnum) return false;
        if (t.Namespace != null && t.Namespace.StartsWith("System")) return false;
        return t.Assembly == typeof(__Objektis).Assembly;
    }

    static string FmtScalar(object v)
    {
        if (v == null) return "null";
        if (v is bool b) return b ? "True" : "False";
        if (v is char c) return "'" + c + "'";
        if (v is string s)
        {
            var q = "\"" + s + "\"";
            return q.Length > 60 ? q.Substring(0, 57) + "...\"" : q;
        }
        var t = v.GetType();
        if (t.IsPrimitive || v is decimal) return v.ToString();
        if (t.IsEnum) return t.Name + "." + v.ToString();
        return "<" + t.Name + ">";
    }

    static IEnumerable<(string name, object value)> IterMembers(object obj)
    {
        var t = obj.GetType();
        var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        foreach (var f in t.GetFields(flags))
        {
            object v;
            try { v = f.GetValue(obj); } catch { continue; }
            var fn = f.Name;
            // Auto-property backing field "<Name>k__BackingField" → "Name"
            if (fn.StartsWith("<") && fn.Contains(">k__BackingField"))
            {
                var idx = fn.IndexOf(">");
                if (idx > 1) fn = fn.Substring(1, idx - 1);
            }
            yield return (fn, v);
        }
    }

    static void EnqueueIfUser(object v, HashSet<int> seen, Queue<object> q, List<object> all)
    {
        if (!IsUserType(v)) return;
        var id = IdOf(v);
        if (seen.Add(id)) { q.Enqueue(v); all.Add(v); }
    }

    static void EnqueueChildren(object v, HashSet<int> seen, Queue<object> q, List<object> all)
    {
        if (v == null || v is string) return;
        if (v is IEnumerable enumerable && !(v is string))
        {
            try
            {
                foreach (var item in enumerable)
                {
                    if (item != null) EnqueueIfUser(item, seen, q, all);
                }
            }
            catch { }
        }
    }

    static string WalkValue(object value, string owner, string field,
                            Dictionary<int, string> nameMap,
                            List<Dictionary<string, string>> links)
    {
        if (value == null) return "null";

        if (IsUserType(value) && nameMap.TryGetValue(IdOf(value), out var target))
        {
            links.Add(new Dictionary<string, string>
            {
                ["source"] = owner, ["target"] = target,
                ["label"] = field, ["kind"] = "association",
            });
            return "→ " + target;
        }

        if (value is string) return FmtScalar(value);

        if (value is IEnumerable en)
        {
            var parts = new List<string>();
            int i = 0;
            try
            {
                foreach (var item in en)
                {
                    if (item != null && IsUserType(item) &&
                        nameMap.TryGetValue(IdOf(item), out var t2))
                    {
                        links.Add(new Dictionary<string, string>
                        {
                            ["source"] = owner, ["target"] = t2,
                            ["label"] = field + "[" + i + "]", ["kind"] = "containment",
                        });
                        parts.Add("→" + t2);
                    }
                    else
                    {
                        parts.Add(FmtScalar(item));
                    }
                    i++;
                    if (i > 4) { parts.Add("...(" + i + "+)"); break; }
                }
            }
            catch { }
            return "[" + string.Join(", ", parts) + "]";
        }

        return FmtScalar(value);
    }

    public static void Dump()
    {
        var path = Environment.GetEnvironmentVariable("OBJEKTIS_DUMP");
        if (string.IsNullOrEmpty(path)) return;

        var notes = new List<string>();
        var seen = new HashSet<int>();
        var allInsts = new List<object>();
        var queue = new Queue<object>();

        foreach (var kv in _named)
        {
            if (seen.Add(IdOf(kv.Value)))
            {
                queue.Enqueue(kv.Value);
                allInsts.Add(kv.Value);
            }
        }

        while (queue.Count > 0)
        {
            var obj = queue.Dequeue();
            foreach (var (_, fval) in IterMembers(obj))
            {
                if (fval == null) continue;
                EnqueueIfUser(fval, seen, queue, allInsts);
                EnqueueChildren(fval, seen, queue, allInsts);
            }
        }

        var nameMap = new Dictionary<int, string>(_idToName);
        var counters = new Dictionary<string, int>();
        foreach (var obj in allInsts)
        {
            var id = IdOf(obj);
            if (!nameMap.ContainsKey(id))
            {
                var typeName = obj.GetType().Name;
                counters.TryGetValue(typeName, out var c);
                counters[typeName] = c + 1;
                var lower = char.ToLower(typeName[0]) + typeName.Substring(1);
                nameMap[id] = lower + (c + 1);
            }
        }

        var links = new List<Dictionary<string, string>>();
        var instances = new List<Dictionary<string, object>>();
        foreach (var obj in allInsts)
        {
            var owner = nameMap[IdOf(obj)];
            var slots = new List<Dictionary<string, string>>();
            foreach (var (fname, fval) in IterMembers(obj))
            {
                slots.Add(new Dictionary<string, string>
                {
                    ["name"] = fname,
                    ["value"] = WalkValue(fval, owner, fname, nameMap, links),
                });
            }
            instances.Add(new Dictionary<string, object>
            {
                ["name"] = owner,
                ["type_name"] = obj.GetType().Name,
                ["slots"] = slots,
                ["multiplicity"] = "",
                ["is_summary"] = false,
            });
        }

        // Дедупликация рёбер по (source, target, label)
        var seenLink = new HashSet<string>();
        var dedupedLinks = new List<Dictionary<string, string>>();
        foreach (var l in links)
        {
            var key = l["source"] + "" + l["target"] + "" + l["label"];
            if (seenLink.Add(key)) dedupedLinks.Add(l);
        }

        var payload = new Dictionary<string, object>
        {
            ["instances"] = instances,
            ["links"] = dedupedLinks,
            ["notes"] = notes,
        };

        try
        {
            File.WriteAllText(path, JsonSerializer.Serialize(payload));
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("__Objektis dump failed: " + ex.Message);
        }
    }
}
"""


# ── Tree-sitter helpers ───────────────────────────────────────────────────────

def _ts_text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_of_type(node, *types):
    for c in node.children:
        if c.type in types:
            return c
    return None


def _descendants_of_type(node, target_type: str) -> list:
    result = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == target_type:
            result.append(n)
        stack.extend(n.children)
    return result


def _has_descendant_of_type(node, target_type: str) -> bool:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == target_type:
            return True
        stack.extend(n.children)
    return False


# ── Source rewriting ──────────────────────────────────────────────────────────

def _find_main_method(root, src: bytes):
    """Найти method_declaration с именем Main в дереве."""
    for md in _descendants_of_type(root, "method_declaration"):
        name_node = md.child_by_field_name("name")
        if name_node and _ts_text(name_node, src) == "Main":
            return md
    return None


def _find_local_decls_in_body(body_node, src: bytes) -> list[tuple[int, str]]:
    """Вернуть [(stmt_end_byte, var_name), ...] для каждого local var в Main body.
    Идём только по верхнеуровневым statement'ам тела (без рекурсии в блоки),
    чтобы не плодить трекеры внутри лямбд/циклов."""
    results = []
    for stmt in body_node.children:
        if stmt.type != "local_declaration_statement":
            continue
        var_decl = _child_of_type(stmt, "variable_declaration")
        if var_decl is None:
            continue
        for vd in var_decl.children:
            if vd.type != "variable_declarator":
                continue
            name_node = vd.child_by_field_name("name") or _child_of_type(vd, "identifier")
            if name_node is None:
                continue
            name = _ts_text(name_node, src).strip()
            if name:
                results.append((stmt.end_byte, name))
                break  # один трекер на statement
    return results


def _rewrite_source(source: str) -> tuple[str, list[str]]:
    """Вставить треккеры в Main + обернуть тело в try/finally.
    Возвращает (новый_исходник, заметки).
    На любых ошибках возвращает оригинал + пометки."""
    try:
        from .._ts import get_parser
    except ImportError as e:
        return source, [f"objektis/csharp: tree-sitter не установлен ({e})"]

    parser = get_parser("c_sharp")
    src = source.encode("utf-8")
    tree = parser.parse(src)

    main = _find_main_method(tree.root_node, src)
    if main is None:
        return source, ["objektis/csharp: метод Main() не найден — пропускаем трекинг"]

    body = main.child_by_field_name("body")
    if body is None or body.type != "block":
        return source, ["objektis/csharp: тело Main не является блоком"]

    inserts: list[tuple[int, str]] = []

    for stmt_end, var_name in _find_local_decls_in_body(body, src):
        inserts.append((
            stmt_end,
            f'\n            try {{ __Objektis.Track("{var_name}", '
            f'(object){var_name}); }} catch {{ }}',
        ))

    open_after = body.start_byte + 1
    close_before = body.end_byte - 1
    inserts.append((open_after, '\n            try {'))
    inserts.append((
        close_before,
        '\n            } finally { __Objektis.Dump(); }\n        ',
    ))

    inserts.sort(key=lambda x: -x[0])
    new_src = bytearray(src)
    for offset, text in inserts:
        new_src[offset:offset] = text.encode("utf-8")

    return new_src.decode("utf-8"), []


# ── Project assembly + run ────────────────────────────────────────────────────

_CSPROJ = (
    '<Project Sdk="Microsoft.NET.Sdk">\n'
    "  <PropertyGroup>\n"
    "    <OutputType>Exe</OutputType>\n"
    "    <TargetFramework>net8.0</TargetFramework>\n"
    "    <Nullable>disable</Nullable>\n"
    "    <RootNamespace>Lab</RootNamespace>\n"
    "    <LangVersion>latest</LangVersion>\n"
    "  </PropertyGroup>\n"
    "</Project>\n"
)


def extract(
    source: str,
    *,
    files: Optional[list[dict]] = None,
    timeout: float = 60.0,
) -> ObjectGraph:
    """См. описание в _facade.extract_objects."""
    if not source and not files:
        return ObjectGraph(notes=["objektis/csharp: пустой исходник"])

    dotnet = shutil.which("dotnet")
    if not dotnet:
        return ObjectGraph(notes=["objektis/csharp: dotnet не найден в PATH"])

    # Нормализуем входы в список (filename, code).
    project_files: list[tuple[str, str]] = []
    if files:
        for f in files:
            if not isinstance(f, dict):
                continue
            fn = f.get("filename") or f.get("name") or ""
            code = f.get("code") or f.get("content") or ""
            if fn and code:
                project_files.append((os.path.basename(fn), code))
    if not project_files and source:
        project_files = [("Program.cs", source)]

    if not project_files:
        return ObjectGraph(notes=["objektis/csharp: нет файлов для компиляции"])

    # Найти файл с Main(): rewrite только его, остальные — как есть.
    rewritten: list[tuple[str, str]] = []
    notes: list[str] = []
    main_file_found = False

    for fn, code in project_files:
        if not main_file_found and "Main" in code:  # быстрый префильтр
            new_code, file_notes = _rewrite_source(code)
            notes.extend(file_notes)
            if new_code != code:
                main_file_found = True
                rewritten.append((fn, new_code))
                continue
        rewritten.append((fn, code))

    if not main_file_found:
        notes.append("objektis/csharp: ни в одном файле не удалось найти Main()")

    with tempfile.TemporaryDirectory(prefix="objektis_cs_") as tmp:
        # Записываем .csproj + студенческие файлы + helper.
        with open(os.path.join(tmp, "Lab.csproj"), "w", encoding="utf-8") as f:
            f.write(_CSPROJ)
        for fn, code in rewritten:
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write(code)
        with open(os.path.join(tmp, "__Objektis.cs"), "w", encoding="utf-8") as f:
            f.write(_HELPER_CS)

        dump_path = os.path.join(tmp, "dump.json")
        env = dict(os.environ)
        env["OBJEKTIS_DUMP"] = dump_path

        try:
            proc = subprocess.run(
                [dotnet, "run", "--project", tmp,
                 "--configuration", "Release",
                 "-v", "quiet",
                 "--nologo"],
                capture_output=True, text=True, timeout=timeout,
                cwd=tmp, env=env,
            )
        except subprocess.TimeoutExpired:
            return ObjectGraph(notes=[
                f"objektis/csharp: timeout ({timeout}s) — программа не завершилась",
                *notes,
            ])
        except OSError as e:
            return ObjectGraph(notes=[f"objektis/csharp: cannot run dotnet: {e}", *notes])

        if not os.path.isfile(dump_path):
            err_tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            return ObjectGraph(notes=[
                f"objektis/csharp: dotnet rc={proc.returncode}, dump не создан",
                *err_tail,
                *notes,
            ])

        try:
            with open(dump_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return ObjectGraph(notes=[
                f"objektis/csharp: парсинг dump.json: {e}", *notes,
            ])

    return _from_payload(payload, extra_notes=notes)


def _from_payload(payload: dict, extra_notes: list[str] | None = None) -> ObjectGraph:
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

    notes = list(payload.get("notes", []))
    if extra_notes:
        notes = list(extra_notes) + notes

    return ObjectGraph(instances=instances, links=links, notes=notes)
