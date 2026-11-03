from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.enum.text import WD_COLOR_INDEX
from docx.table import _Cell

from tutela2.config import Config
from tutela2.documentos.formato import FILAS_PUNTAJE, render_formato
from tutela2.models import Decision, Fechas, Metadatos

CUI = "05001408809900260099900"


def metadatos(**extra) -> Metadatos:
    base = dict(
        cui_1a=CUI,
        juzgado_a_quo_numero=99,
        juzgado_a_quo_funcion="control_garantias",
        juzgado_a_quo_letras="Noventa y Nueve",
        juez_a_quo_apellidos="Pérez Ruiz",
        juez_a_quo_nombres="Ana María",
        fechas=Fechas(admision="2026-01-05", fallo_a_quo="2026-01-20"),
    )
    base.update(extra)
    return Metadatos(**base)


def generar(tmp_path, md=None, **decision):
    ruta = render_formato(
        md or metadatos(),
        Decision(accion="decidir", fecha_fallo="2026-02-03", **decision),
        Config(),
        tmp_path / "sub" / "formato.docx",
    )
    return Document(str(ruta))


def celda(doc, fila, col):
    t = doc.tables[0]
    return _Cell(t._tbl.tr_lst[fila].tc_lst[col], t)


def textos(doc):
    t = doc.tables[0]
    return [c.text for r in t._tbl.tr_lst for c in (_Cell(tc, t) for tc in r.tc_lst)]


def test_encabezado_y_secciones(tmp_path):
    doc = generar(tmp_path)
    todo = "\n".join(textos(doc))
    for texto in (
        "INFORMACIÓN DEL EVALUADO",
        "IDENTIFICACIÓN DEL PROCESO O ACCIÓN OBJETO DE EVALUACIÓN",
        "ANÁLISIS TÉCNICO Y JURÍDICO DE LA DECISIÓN",
        "DIRECCIÓN DEL PROCESO (Hasta 22 puntos)",
        "ANÁLISIS DE LA DECISIÓN : (Hasta 20 puntos)",
        "PUNTAJE TOTAL ASIGNADO",
        "MOTIVACIÓN DE LA EVALUACIÓN (Diligenciar obligatoriamente)",
        "PONENTE (Para Corporaciones)",
        "EVALUADOR",
        "TUTELAS O SIN AUDIENCIA",
        "Identificación del Problema Jurídico.",
        "Síntesis de la providencia o motivación breve y precisa",
    ):
        assert texto in todo
    for texto in ("3.1.", "3.2.", "3.3.", "3.4.", "3.5", "0 - 42", "0 - 22", "0 - 12"):
        assert texto in todo


def test_pagina_y_sin_instructivo(tmp_path):
    doc = generar(tmp_path)
    s = doc.sections[0]
    assert round(s.page_width.pt) == 612
    assert round(s.page_height.pt) == 936
    assert not any("INSTRUCTIVO" in p.text for p in doc.paragraphs)
    assert len(doc.tables) == 1


def test_prellenado_exacto(tmp_path):
    doc = generar(tmp_path)
    assert [celda(doc, 0, c).text for c in (2, 4, 6)] == ["03", "02", "2026"]
    assert celda(doc, 4, 1).text == "PÉREZ RUIZ"
    assert celda(doc, 4, 5).text == "ANA MARÍA"
    assert celda(doc, 6, 1).text == "JUZGADO 99 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS"
    assert celda(doc, 6, 4).text == "MEDELLÍN"
    assert celda(doc, 6, 8).text == "MEDELLÍN"
    assert [celda(doc, 10, c).text for c in (1, 3, 5)] == ["05", "01", "2026"]
    assert [celda(doc, 10, c).text for c in (10, 12, 14)] == ["20", "01", "2026"]
    assert celda(doc, 12, 1).text == "SENTENCIA DE TUTELA PRIMERA INSTANCIA"
    assert celda(doc, 12, 3).text == CUI
    assert celda(doc, 14, 1).text == "X"
    marcadas = [c for c in range(15) if "X" in celda(doc, 14, c).text]
    assert marcadas == [1]
    assert celda(doc, 36, 5).text == "SANTIAGO ALEJANDRO CADAVID DUQUE"
    assert celda(doc, 37, 5).text == "Juez 3° Penal del Circuito de Conocimiento"


def test_juzgado_plural_y_sufijo(tmp_path):
    md = metadatos(juzgado_a_quo_funcion="conocimiento", juzgado_a_quo_plural=True)
    doc = generar(tmp_path, md)
    assert celda(doc, 6, 1).text == "JUZGADO 99 PENAL MUNICIPAL CON FUNCIONES DE CONOCIMIENTO"


def test_juzgado_desde_texto(tmp_path):
    md = metadatos(
        juzgado_a_quo_numero=None,
        juzgado_a_quo="Juzgado 7 Penal Municipal con Función de Control de Garantías de Medellín",
    )
    doc = generar(tmp_path, md)
    assert celda(doc, 6, 1).text == "JUZGADO 7 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS"


def test_puntajes_y_motivacion_en_blanco(tmp_path):
    doc = generar(tmp_path)
    for fila in FILAS_PUNTAJE:
        assert celda(doc, fila, 4).text.strip() == ""
    assert celda(doc, 34, 0).text.strip() == ""
    cuerpo = "".join(p.text for p in doc.paragraphs)
    assert cuerpo.strip() == ""


def test_faltantes_resaltados(tmp_path):
    md = metadatos(
        cui_1a=None,
        juez_a_quo_apellidos=None,
        juez_a_quo_nombres=None,
        juzgado_a_quo_numero=None,
        fechas=Fechas(),
    )
    doc = generar(tmp_path, md)
    marcas = []
    for fila, col in ((4, 1), (4, 5), (6, 1), (10, 1), (10, 6), (12, 3)):
        c = celda(doc, fila, col)
        assert c.text.startswith("⟦FALTA: ")
        marcas.append(c.paragraphs[0].runs[0].font.highlight_color)
    assert all(m == WD_COLOR_INDEX.YELLOW for m in marcas)


def test_fecha_evaluacion_por_defecto_es_hoy(tmp_path):
    from datetime import date

    ruta = render_formato(
        metadatos(), Decision(accion="decidir"), Config(), tmp_path / "f.docx"
    )
    hoy = date.today()
    doc = Document(str(ruta))
    assert [celda(doc, 0, c).text for c in (2, 4, 6)] == [f"{hoy.day:02d}", f"{hoy.month:02d}", str(hoy.year)]


def test_crea_directorio_y_devuelve_ruta(tmp_path):
    ruta = render_formato(metadatos(), Decision(accion="decidir"), Config(), tmp_path / "a" / "b" / "x.docx")
    assert ruta.exists() and ruta.name == "x.docx"


def test_numbering_lvl_respeta_orden_ooxml(tmp_path):
    orden = ["start", "numFmt", "lvlRestart", "pStyle", "isLgl", "suff", "lvlText",
             "lvlPicBulletId", "legacy", "lvlJc", "pPr", "rPr"]
    doc = generar(tmp_path)
    numbering = doc.part.numbering_part.element
    niveles = numbering.xpath("//w:lvl")
    assert niveles
    for lvl in niveles:
        hijos = [h.tag.split("}")[1] for h in lvl]
        assert hijos == sorted(hijos, key=orden.index)


def test_celdas_no_aplica_con_rayado_diagonal(tmp_path):
    doc = generar(tmp_path)
    shd = doc.tables[0]._tbl.xpath(".//w:shd")
    assert shd and all(s.get(qn("w:val")) == "thinDiagStripe" for s in shd)
