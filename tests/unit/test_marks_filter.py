"""Filter `marks`: symbool achter 3PMSF en M+S, en de tekst blijft geëscaped."""

from __future__ import annotations

from wisselweer.web.templating import templates

marks = templates.env.filters["marks"]


def test_symbool_achter_3pmsf_en_ms_met_woorddeel_op_een_regel():
    out = str(marks("Met 3PMSF-symbool, alleen M+S is te weinig."))
    assert out.count('class="mark-inline"') == 2
    assert '<span class="mark-keep">3PMSF<svg' in out and "</svg>-symbool,</span>" in out
    assert '<span class="mark-keep">M+S<svg' in out
    assert 'aria-hidden="true"' in out


def test_tekst_wordt_geescaped():
    out = str(marks('<script>alert("x")</script> 3PMSF'))
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert out.count("<svg") == 1


def test_zonder_symbool_ongewijzigd():
    assert str(marks("Zomerbanden & meer")) == "Zomerbanden &amp; meer"
