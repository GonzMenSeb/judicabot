from __future__ import annotations

import pytest
from docx import Document

from tutela2.config import Config
from tutela2.documentos.auto import auto_por_defecto, cuando, render_auto
from tutela2.documentos.oficio import render_oficio
from tutela2.models import DatosAuto, Fechas, Metadatos

CUI_2A = "05001408801820260053001"
CFG = Config()


def md(**kw) -> Metadatos:
    base = dict(
        cui_1a="05001408801820260053000",
        cui_2a=CUI_2A,
        accionante="Ana Prueba Pérez",
        accionadas=["Banco Ejemplo", "Entidad Dos"],
        fechas=Fechas(reparto_2a="2026-09-28"),
    )
    base.update(kw)
    return Metadatos(**base)


def textos(doc) -> list[str]:
    return [p.text for p in doc.paragraphs]


def fuentes(doc) -> set[str]:
    return {r.font.name for p in doc.paragraphs for r in p.runs if r.font.name}


@pytest.fixture
def auto(tmp_path):
    m = md()
    ruta = render_auto(m, auto_por_defecto(m), CFG, tmp_path / "auto.docx")
    return Document(str(ruta))


@pytest.fixture
def oficio(tmp_path):
    ruta = render_oficio(md(), "2026-10-07", CFG, tmp_path / "oficio.docx")
    return Document(str(ruta))


def test_auto_por_defecto():
    d = auto_por_defecto(md())
    assert d == DatosAuto(fecha="2026-09-29", accionante="Ana Prueba Pérez", accionada="Banco Ejemplo, Entidad Dos")
    assert auto_por_defecto(md(fechas=Fechas())).fecha is None


@pytest.mark.parametrize("reparto,esperada", [("2026-09-11", "2026-09-14"), ("2026-09-12", "2026-09-14"), ("2026-09-14", "2026-09-15")])
def test_auto_por_defecto_salta_fin_de_semana(reparto, esperada):
    assert auto_por_defecto(md(fechas=Fechas(reparto_2a=reparto))).fecha == esperada
    assert cuando(md(fechas=Fechas(reparto_2a="2026-09-11")), "2026-09-14") == "el día 11 de septiembre del año en curso"


def test_auto_pagina_y_fuentes(auto):
    s = auto.sections[0]
    assert abs(s.page_width.pt - 612.48) <= 0.1
    assert abs(s.page_height.pt - 936.48) <= 0.1
    assert fuentes(auto) == {"Bookman Old Style"}


def test_auto_textos_literales(auto):
    t = textos(auto)
    assert "Radicado: " + CUI_2A in t
    assert "Accionante: Ana Prueba Pérez" in t
    assert "Accionada: Banco Ejemplo, Entidad Dos" in t
    assert "CONSTANCIA:" in t
    assert (
        "Las presentes diligencias fueron recibidas el día de ayer, vía correo electrónico por "
        "reparto de la Oficina Judicial procedente del Juzgado 18 Penal Municipal con Función de "
        "Control de Garantías de Medellín, con impugnación del fallo de tutela de primera "
        "instancia, a Despacho del señor Juez." in t
    )
    assert t.count("Medellín, veintinueve (29) de septiembre de dos mil veintiséis (2026)") == 2
    assert "John Mendoza" in t and "Escribiente" in t
    assert "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO" in t
    assert "ASUNTO: AUTO ASUME CONOCIMIENTO DE IMPUGNACIÓN DE TUTELA" in t
    assert (
        "Se asume el conocimiento de las presentes diligencias. En consecuencia, pase el "
        "expediente a Despacho para el pronunciamiento que en derecho corresponda." in t
    )
    assert t[-2:] == ["SANTIAGO ALEJANDRO CADAVID DUQUE", "JUEZ"]
    assert "NOTIFÍQUESE Y CÚMPLASE" in t


def test_auto_logo_y_pie(auto):
    assert len(auto.inline_shapes) == 1
    pie = [p.text for p in auto.sections[0].footer.paragraphs]
    assert pie == CFG.despacho.pie_auto


def test_auto_juzgado_conocimiento_por_metadatos(tmp_path):
    m = md(juzgado_a_quo_numero=47, juzgado_a_quo_funcion="conocimiento", juzgado_a_quo_letras="Cuarenta y Siete")
    doc = Document(str(render_auto(m, auto_por_defecto(m), CFG, tmp_path / "a.docx")))
    assert any("del Juzgado 47 Penal Municipal con Función de Conocimiento de Medellín," in p for p in textos(doc))


@pytest.mark.parametrize(
    "reparto,fecha,esperado",
    [
        ("2026-09-28", "2026-09-29", "el día de ayer"),
        ("2026-09-17", "2026-09-29", "el día 17 de septiembre del año en curso"),
        ("2025-12-30", "2026-01-05", "el día treinta (30) de diciembre de dos mil veinticinco (2025)"),
        (None, "2026-09-29", "⟦FALTA: fecha de reparto⟧"),
    ],
)
def test_cuando(reparto, fecha, esperado):
    assert cuando(md(fechas=Fechas(reparto_2a=reparto)), fecha) == esperado


def test_auto_faltantes_resaltados(tmp_path):
    m = md(fechas=Fechas(), accionante=None, accionadas=[])
    doc = Document(str(render_auto(m, auto_por_defecto(m), CFG, tmp_path / "a.docx")))
    marcadas = [r.text for p in doc.paragraphs for r in p.runs if r.font.highlight_color is not None]
    assert "⟦FALTA: accionante⟧" in marcadas
    assert "⟦FALTA: accionada⟧" in marcadas
    assert "⟦FALTA: fecha de reparto⟧" in marcadas
    assert "⟦FALTA: fecha⟧" in marcadas


def test_oficio_pagina_y_fuentes(oficio):
    s = oficio.sections[0]
    assert abs(s.page_width.pt - 612.0) <= 0.1
    assert abs(s.page_height.pt - 1008.0) <= 0.1
    assert fuentes(oficio) == {"Verdana"}


def test_oficio_textos_literales(oficio):
    t = textos(oficio)
    assert "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO" in t
    assert "Medellín, siete (07) de octubre de dos mil veintiséis (2026)" in t
    assert "Asunto: REMISIÓN EXPEDIENTE DE TUTELA EN REVISIÓN" in t
    for linea in ("Señores", "HONORABLES MAGISTRADOS", "Corte Constitucional – Sala de Revisión",
                  "Calle 12 N° 7 – 65", "Bogotá D. C.", "Cordial Saludo"):
        assert linea in t
    assert (
        "De manera comedida y de conformidad con lo preceptuado en el artículo 31 del Decreto 2591 "
        "de 1991, les remito para su eventual revisión la acción de tutela relacionada a continuación." in t
    )
    assert "Radicado: " + CUI_2A in t
    assert "Accionante: ANA PRUEBA PÉREZ" in t
    assert "Accionado: BANCO EJEMPLO, ENTIDAD DOS" in t
    assert t[-2:] == ["JOHN MANUEL MENDOZA", "Escribiente"]


def test_oficio_asunto_en_redonda_y_encabezado_negrita_cursiva(oficio):
    enc = oficio.paragraphs[1]
    assert enc.text.startswith("JUZGADO") and all(r.font.bold and r.font.italic for r in enc.runs)
    par = next(p for p in oficio.paragraphs if p.text.startswith("Asunto:"))
    normal, resto = par.runs
    assert normal.text == "Asunto: " and not normal.font.bold and not normal.font.italic
    assert not resto.font.bold and not resto.font.italic


def test_oficio_logo_arriba_y_sin_firma(oficio):
    assert len(oficio.inline_shapes) == 1
    assert oficio.paragraphs[0]._p.xpath(".//wp:inline")


def test_oficio_fecha_faltante_resaltada(tmp_path):
    doc = Document(str(render_oficio(md(), None, CFG, tmp_path / "o.docx")))
    assert any(r.text == "⟦FALTA: fecha⟧" and r.font.highlight_color is not None
               for p in doc.paragraphs for r in p.runs)
