from __future__ import annotations

import io

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from tutela2 import formato_b

PIE = [
    "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
    "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
    "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
]
PIE_AUTO = ["Línea uno del pie", "Línea dos del pie"]


def reabrir(doc):
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return Document(buf)


def fallo():
    doc = Document()
    formato_b.configurar_fallo(doc, PIE)
    return reabrir(doc)


def test_pagina_y_margenes_del_fallo():
    s = fallo().sections[0]
    assert abs(s.page_width.twips - 11950) <= 1
    assert abs(s.page_height.twips - 19320) <= 1
    assert abs(s.left_margin.pt - 54) <= 0.1
    assert abs(s.right_margin.pt - 54) <= 0.1
    assert abs(s.top_margin.pt - 72) <= 0.1
    assert abs(s.bottom_margin.pt - 73.4) <= 0.1
    assert s.header_distance.pt == 0
    assert abs(s.footer_distance.pt - 22.2) <= 0.1


def test_encabezado_con_logo():
    doc = fallo()
    cab = doc.sections[0].header
    assert len(cab.paragraphs) == 1
    par = cab.paragraphs[0]
    assert par.alignment == 1
    ext = par._p.xpath(".//wp:inline/wp:extent")
    assert len(ext) == 1
    assert abs(int(ext[0].get("cx")) - Pt(199.1)) <= Pt(199.1) * 0.01
    assert abs(int(ext[0].get("cy")) - Pt(66.0)) <= Pt(66.0) * 0.01
    pf = par.paragraph_format
    assert pf.space_before.pt == 0 and pf.space_after.pt == 0
    assert pf.line_spacing == 1.0
    rfonts = par._p.pPr.xpath("./w:rPr/w:rFonts")[0]
    assert rfonts.get(qn("w:ascii")) == "Verdana"
    assert par._p.pPr.xpath("./w:rPr/w:sz")[0].get(qn("w:val")) == "22"


def test_pie_del_fallo():
    pie = fallo().sections[0].footer
    pars = [p for p in pie.paragraphs if p.text in PIE]
    assert [p.text for p in pars] == PIE
    for p in pars:
        assert p.alignment == 1
        assert p.paragraph_format.line_spacing == 1.0
        assert p.paragraph_format.space_before.pt == 0
        assert p.paragraph_format.space_after.pt == 0
        assert abs(p.paragraph_format.right_indent.pt - 12) <= 0.1
        for r in p.runs:
            rf = r._r.rPr.find(qn("w:rFonts"))
            assert rf.get(qn("w:ascii")) == "Cambria"
            assert r._r.rPr.find(qn("w:i")) is not None
            assert r._r.rPr.find(qn("w:sz")).get(qn("w:val")) == "16"
    escalas = [r._r.rPr.find(qn("w:w")) for r in pars[1].runs]
    assert escalas and all(e is not None and e.get(qn("w:val")) == "108" for e in escalas)
    for p in (pars[0], pars[2]):
        assert all(r._r.rPr.find(qn("w:w")) is None for r in p.runs)


def test_numero_de_pagina_en_marco():
    pie = fallo().sections[0].footer
    marcos = pie._element.xpath(".//w:p[w:pPr/w:framePr]")
    assert len(marcos) == 1
    p = marcos[0]
    fp = p.xpath("./w:pPr/w:framePr")[0]
    assert fp.get(qn("w:hAnchor")) == "page"
    assert fp.get(qn("w:vAnchor")) == "page"
    assert abs(int(fp.get(qn("w:x"))) - 10092) <= 20
    assert abs(int(fp.get(qn("w:y"))) - round(868.20 * 20)) <= 20
    assert abs(int(fp.get(qn("w:w"))) - round(16.56 * 20)) <= 20
    assert abs(int(fp.get(qn("w:h"))) - round(12.96 * 20)) <= 20
    assert fp.get(qn("w:hRule")) == "exact"
    assert "PAGE" in "".join(p.xpath(".//w:instrText/text()")) or p.xpath(".//w:fldSimple[@w:instr='PAGE']")
    runs = p.xpath(".//w:r[w:instrText or w:fldChar]")
    assert runs
    for r in runs:
        assert r.xpath("./w:rPr/w:rFonts")[0].get(qn("w:ascii")) == "Times New Roman"
        assert r.xpath("./w:rPr/w:sz")[0].get(qn("w:val")) == "20"


def test_escala():
    doc = Document()
    r = doc.add_paragraph().add_run("x")
    formato_b.escala(r, 114)
    assert r._r.rPr.find(qn("w:w")).get(qn("w:val")) == "114"
    assert 'w:w w:val="114"' in r._r.xml
    r2 = doc.add_paragraph().add_run("y")
    formato_b.escala(r2, 100)
    assert r2._r.rPr is None or r2._r.rPr.find(qn("w:w")) is None


def test_escala_respeta_orden_del_esquema():
    doc = Document()
    r = doc.add_paragraph().add_run("x")
    formato_b.fuente(r, "Bookman Old Style", 12, negrita=True)
    formato_b.escala(r, 114)
    tags = [c.tag.split("}")[1] for c in r._r.rPr]
    assert tags.index("w") < tags.index("sz")


def test_fuente():
    doc = Document()
    r = doc.add_paragraph().add_run("x")
    formato_b.fuente(r, "Cambria", 8, cursiva=True, subrayado=True)
    rf = r._r.rPr.find(qn("w:rFonts"))
    for a in ("ascii", "hAnsi", "eastAsia", "cs"):
        assert rf.get(qn(f"w:{a}")) == "Cambria"
    assert r._r.rPr.find(qn("w:sz")).get(qn("w:val")) == "16"
    assert r.italic is True and r.underline is True


def test_espaciado():
    doc = Document()
    p = doc.add_paragraph()
    formato_b.espaciado(p, antes=14, despues=2, multiple=1.5)
    assert p.paragraph_format.space_before.pt == 14
    assert p.paragraph_format.space_after.pt == 2
    assert p.paragraph_format.line_spacing == 1.5
    q = doc.add_paragraph()
    formato_b.espaciado(q, exacto=20)
    assert q.paragraph_format.line_spacing.pt == 20
    assert q.paragraph_format.line_spacing_rule == 4
    s = doc.add_paragraph()
    formato_b.espaciado(s)
    assert s.paragraph_format.line_spacing == 1.0


def test_bordes_tabla():
    doc = Document()
    t = doc.add_table(rows=1, cols=2)
    formato_b.bordes_tabla(t)
    b = t._tbl.tblPr.find(qn("w:tblBorders"))
    nombres = [c.tag.split("}")[1] for c in b]
    assert sorted(nombres) == sorted(["top", "left", "bottom", "right", "insideH", "insideV"])
    for c in b:
        assert c.get(qn("w:val")) == "single"
        assert c.get(qn("w:sz")) == "4"
        assert c.get(qn("w:color")) == "000000"


def test_sangria_alto_y_anchos():
    doc = Document()
    t = doc.add_table(rows=2, cols=2)
    formato_b.sangria_tabla(t, 54.02)
    formato_b.alto_minimo_fila(t.rows[0], 21.8)
    formato_b.anchos_columnas(t, [120.39, 269.69])
    t = reabrir(doc).tables[0]
    ind = t._tbl.tblPr.find(qn("w:tblInd"))
    assert abs(int(ind.get(qn("w:w"))) - round(54.02 * 20)) <= 1
    assert ind.get(qn("w:type")) == "dxa"
    assert abs(t.rows[0].height.pt - 21.8) <= 0.1
    assert t.rows[0].height_rule == 1
    assert t.autofit is False
    grid = [int(g.get(qn("w:w"))) for g in t._tbl.tblGrid]
    assert [abs(g - round(a * 20)) <= 1 for g, a in zip(grid, (120.39, 269.69))] == [True, True]
    for fila in t.rows:
        assert abs(fila.cells[0].width.pt - 120.39) <= 0.1
        assert abs(fila.cells[1].width.pt - 269.69) <= 0.1


def test_configurar_auto():
    doc = Document()
    formato_b.configurar_auto(doc, PIE_AUTO, margenes={"superior": 70, "inferior": 60, "izquierdo": 80, "derecho": 50})
    s = reabrir(doc).sections[0]
    assert abs(s.page_width.pt - 612.48) <= 0.1
    assert abs(s.page_height.pt - 936.48) <= 0.1
    assert abs(s.top_margin.pt - 70) <= 0.1
    assert abs(s.left_margin.pt - 80) <= 0.1
    pars = [p for p in s.footer.paragraphs if p.text]
    assert [p.text for p in pars] == PIE_AUTO
    assert all(p.alignment == 1 for p in pars)


def test_configurar_oficio():
    doc = Document()
    formato_b.configurar_oficio(doc)
    s = reabrir(doc).sections[0]
    assert abs(s.page_width.pt - 612) <= 0.1
    assert abs(s.page_height.pt - 1008) <= 0.1


def test_logo_existe():
    assert formato_b.LOGO.is_file()


def test_ajustes_word_zoom_percent():
    doc = Document()
    formato_b.ajustes_word(doc)
    formato_b.ajustes_word(doc)
    zooms = reabrir(doc).settings.element.findall(qn("w:zoom"))
    assert len(zooms) == 1
    assert zooms[0].get(qn("w:percent")) == "100"
