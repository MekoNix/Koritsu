from hokoku.markdown import CodeBlock, Hr, ImgBlock, Para, TableBlock, parse, parse_inline


def _t(spans):
    return "".join(s.text for s in spans)


def _merged(spans):
    """Соседние span'ы с одинаковыми атрибутами склеиваем, пробелы по краям убираем."""
    out = []
    for x in spans:
        key = (x.bold, x.italic, x.code, x.strike, x.link)
        if out and out[-1][1:] == key:
            out[-1] = (out[-1][0] + x.text, *key)
        else:
            out.append((x.text, *key))
    return [(t.strip(), *k) for t, *k in out if t.strip()]


def test_inline():
    s = parse_inline("a **b** *c* `d` ~~e~~ ***f*** [g](https://x) https://y.z \\*lit\\*")
    assert _merged(s) == [
        ("a", False, False, False, False, None), ("b", True, False, False, False, None),
        ("c", False, True, False, False, None), ("d", False, False, True, False, None),
        ("e", False, False, False, True, None), ("f", True, True, False, False, None),
        ("g", False, False, False, False, "https://x"), ("https://y.z", False, False, False, False, "https://y.z"),
        ("*lit*", False, False, False, False, None)]


def test_underscores_inside_words_are_not_emphasis():
    assert _t(parse_inline("snake_case_name и __b__")) == "snake_case_name и b"


def test_blocks():
    b = parse("# H1\n\npara one\ncontinues\n\n- a\n- b\n  more\n  1. x\n\n```c\nint x;\n```\n---\n![cap](i.png)\n\n| h | k |\n|:-:|--:|\n| 1 | 2 |\n\n> q1\n> q2\n")
    kinds = [type(x).__name__ + (":" + x.kind if isinstance(x, Para) else "") for x in b]
    assert kinds == ["Para:h1", "Para:p", "Para:ul", "Para:ul", "Para:ol", "CodeBlock", "Hr", "ImgBlock",
                     "TableBlock", "Para:quote"]
    assert _t(b[1].spans) == "para one continues"
    assert _t(b[3].spans) == "b more" and b[4].level == 1
    assert b[5] == CodeBlock("int x;", "c")
    assert b[7] == ImgBlock("i.png", "cap")
    assert b[8].align == ["center", "right"] and _t(b[8].rows[1][1]) == "2"
    assert _t(b[9].spans) == "q1 q2"


def test_table_escaped_pipe_and_ragged_rows():
    b = parse("| a | b |\n|---|---|\n| x \\| y |\n")
    assert _t(b[0].rows[1][0]) == "x | y" and len(b[0].rows[1]) == 2
