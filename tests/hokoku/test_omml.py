from docx.oxml import parse_xml

from hokoku.omml import latex_to_omml

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _tags(latex):
    el = parse_xml(latex_to_omml(latex))
    return [e.tag.replace(M, "m:") for e in el.iter() if e.tag.startswith(M)]


def _text(latex):
    el = parse_xml(latex_to_omml(latex))
    return "".join(t.text for t in el.iter(M + "t"))


def test_constructs():
    assert "m:sSup" in _tags("x^2") and "m:sSub" in _tags("x_i") and "m:sSubSup" in _tags("x_i^2")
    assert "m:f" in _tags(r"\frac{a}{b}") and "m:rad" in _tags(r"\sqrt{x}") and "m:deg" in _tags(r"\sqrt[3]{x}")
    assert "m:nary" in _tags(r"\sum_{i=1}^n a_i") and "m:limLow" in _tags(r"\lim_{x \to 0} f")
    assert "m:d" in _tags(r"\left( a \right)") and "m:d" in _tags("(a+b)") and "m:acc" in _tags(r"\vec{a}")
    assert "m:func" in _tags(r"\sin{x}") and "m:bar" in _tags(r"\overline{x}")


def test_symbols_and_text():
    assert _text(r"\alpha \leq \beta \cdot \infty") == "α≤β·∞"
    assert _text(r"\text{при } n \to \infty") == "при n→∞"
    assert _text(r"\unknowncmd x") == "unknowncmdx"                      # не падает
    assert _text("3.14 + 2,5") == "3.14+2,5"


def test_nary_body_stops_at_operator():
    el = parse_xml(latex_to_omml(r"\sum_{i=1}^{n} a_i + b"))
    nary = next(e for e in el.iter(M + "nary"))
    body = "".join(t.text for t in nary.find(M + "e").iter(M + "t"))
    assert body == "ai" and _text(r"\sum_{i=1}^{n} a_i + b").endswith("+b")


def test_display_para():
    assert latex_to_omml("x", display=True).startswith("<m:oMathPara")


def test_nary_inside_frac_keeps_its_body():
    """Сумма в числителе дроби: тело оператора должно быть внутри неё, а не рядом."""
    el = parse_xml(latex_to_omml(r"\frac{\sum_{i=1}^{n} x_i}{n}"))
    nary = next(e for e in el.iter(M + "nary"))
    body = "".join(t.text for t in nary.find(M + "e").iter(M + "t"))
    assert body == "xi"
    num = next(e for e in el.iter(M + "num"))
    assert "".join(t.text for t in num.iter(M + "t")) == "i=1nxi"      # всё внутри числителя


def test_nary_inside_sqrt_and_delim():
    for latex in (r"\sqrt{\sum_{i=1}^{n} x_i}", r"\left( \sum_{i=1}^{n} x_i \right)"):
        el = parse_xml(latex_to_omml(latex))
        nary = next(e for e in el.iter(M + "nary"))
        assert "".join(t.text for t in nary.find(M + "e").iter(M + "t")) == "xi", latex


def test_lim_is_a_function_with_body():
    """Предел с телом — m:func, а не голый limLow: иначе Word и LibreOffice рисуют
    «lim_{x→0} \\frac{sin x}{x}» как одну общую дробь «(lim sin x)/x», и формула в сданном
    отчёте читается неверно (замечено при проверке PDF глазами)."""
    x = latex_to_omml(r"\lim_{x \to 0} \frac{\sin x}{x} = 1")
    assert "<m:func><m:fName><m:limLow>" in x
    assert "</m:limLow></m:fName><m:e><m:f>" in x          # дробь внутри тела предела
    el = parse_xml(x)
    func = next(e for e in el.iter(M + "func"))
    body = func.find(M + "e")
    assert [e.tag.replace(M, "m:") for e in body] == ["m:f"]      # тело предела — ровно дробь
    assert "".join(t.text for t in body.iter(M + "t")) == "sinxx"  # sin x над x
    assert _text(r"\lim_{x \to 0} \frac{\sin x}{x} = 1").endswith("=1")   # «= 1» снаружи


def test_lim_without_body_still_works():
    assert "m:limLow" in _tags(r"\lim_{n \to \infty}")
