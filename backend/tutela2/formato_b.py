from __future__ import annotations

from pathlib import Path

from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

LOGO = Path(__file__).parent / "assets" / "rama_judicial_logo.png"

_SIGUIENTES_ESCALA = (
    "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
    "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em",
    "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath",
)
_ORDEN_TBLPR = (
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
    "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd",
    "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
)
_BORDES = ("top", "left", "bottom", "right", "insideH", "insideV")


def _twips(pt: float) -> str:
    return str(round(pt * 20))


def fuente(run, nombre: str, tam: float, *, negrita=None, cursiva=None, subrayado=None) -> None:
    run.font.size = Pt(tam)
    run.font.name = nombre
    rfonts = run._r.get_or_add_rPr().get_or_add_rFonts()
    for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{atributo}"), nombre)
    if negrita is not None:
        run.font.bold = negrita
    if cursiva is not None:
        run.font.italic = cursiva
    if subrayado is not None:
        run.font.underline = subrayado


def escala(run, porcentaje: int) -> None:
    if porcentaje == 100:
        return
    rpr = run._r.get_or_add_rPr()
    for previo in rpr.findall(qn("w:w")):
        rpr.remove(previo)
    w = OxmlElement("w:w")
    w.set(qn("w:val"), str(porcentaje))
    rpr.insert_element_before(w, *_SIGUIENTES_ESCALA)


def espaciado(
    par,
    *,
    antes: float = 0,
    despues: float = 0,
    multiple: float | None = None,
    exacto: float | None = None,
) -> None:
    fmt = par.paragraph_format
    fmt.space_before = Pt(antes)
    fmt.space_after = Pt(despues)
    if exacto is not None:
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing = Pt(exacto)
    else:
        fmt.line_spacing = multiple if multiple is not None else 1.0


def logo(par, ancho_pt: float = 199.1, alto_pt: float = 66.0) -> None:
    par.add_run().add_picture(str(LOGO), width=Pt(ancho_pt), height=Pt(alto_pt))


def campo_pagina(par) -> None:
    def corrida(*hijos):
        r = par.add_run()
        for h in hijos:
            r._r.append(h)
        return r

    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separador = OxmlElement("w:fldChar")
    separador.set(qn("w:fldCharType"), "separate")
    fin = OxmlElement("w:fldChar")
    fin.set(qn("w:fldCharType"), "end")
    corrida(inicio)
    corrida(instr)
    corrida(separador)
    par.add_run("1")
    corrida(fin)


def _tbl_pr_insertar(tabla, elemento) -> None:
    pr = tabla._tbl.tblPr
    etiqueta = elemento.tag
    for previo in pr.findall(etiqueta):
        pr.remove(previo)
    pos = [qn(t) for t in _ORDEN_TBLPR].index(etiqueta)
    pr.insert_element_before(elemento, *_ORDEN_TBLPR[pos + 1:])


def bordes_tabla(tabla, sz_octavos: int = 4) -> None:
    bordes = OxmlElement("w:tblBorders")
    for nombre in _BORDES:
        b = OxmlElement(f"w:{nombre}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(sz_octavos))
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "000000")
        bordes.append(b)
    _tbl_pr_insertar(tabla, bordes)


def sangria_tabla(tabla, pt: float) -> None:
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), _twips(pt))
    ind.set(qn("w:type"), "dxa")
    _tbl_pr_insertar(tabla, ind)


def alto_minimo_fila(fila, pt: float) -> None:
    fila.height = Pt(pt)
    fila.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST


def anchos_columnas(tabla, anchos_pt: list[float]) -> None:
    tabla.autofit = False
    cols = tabla._tbl.tblGrid.findall(qn("w:gridCol"))
    for col, ancho in zip(cols, anchos_pt):
        col.set(qn("w:w"), _twips(ancho))
    for fila in tabla.rows:
        for celda, ancho in zip(fila.cells, anchos_pt):
            celda.width = Pt(ancho)
    total = OxmlElement("w:tblW")
    total.set(qn("w:w"), _twips(sum(anchos_pt)))
    total.set(qn("w:type"), "dxa")
    _tbl_pr_insertar(tabla, total)


def _pagina(seccion, ancho_pt: float, alto_pt: float) -> None:
    seccion.page_width = Pt(ancho_pt)
    seccion.page_height = Pt(alto_pt)


def _linea_pie(par, texto: str, *, pt_derecha: float = 0, porcentaje: int = 100, estilo=True) -> None:
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    espaciado(par)
    if pt_derecha:
        par.paragraph_format.right_indent = Pt(pt_derecha)
    run = par.add_run(texto)
    if estilo:
        fuente(run, "Cambria", 8, cursiva=True)
    escala(run, porcentaje)


def _marco_numero_pagina(par) -> None:
    ppr = par._p.get_or_add_pPr()
    marco = OxmlElement("w:framePr")
    marco.set(qn("w:w"), _twips(16.56))
    marco.set(qn("w:h"), _twips(12.96))
    marco.set(qn("w:hRule"), "exact")
    marco.set(qn("w:hSpace"), "0")
    marco.set(qn("w:wrap"), "notBeside")
    marco.set(qn("w:vAnchor"), "page")
    marco.set(qn("w:hAnchor"), "page")
    marco.set(qn("w:x"), _twips(504.58))
    marco.set(qn("w:y"), _twips(868.20))
    ppr.insert_element_before(marco, "w:widowControl", "w:numPr", "w:suppressLineNumbers",
                              "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens",
                              "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct",
                              "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
                              "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
                              "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
                              "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
                              "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def modo_compatibilidad(doc, valor: int) -> None:
    for ajuste in doc.settings.element.iter(qn("w:compatSetting")):
        if ajuste.get(qn("w:name")) == "compatibilityMode":
            ajuste.set(qn("w:val"), str(valor))


def configurar_fallo(doc, pie: list[str]) -> None:
    modo_compatibilidad(doc, 15)
    seccion = doc.sections[0]
    _pagina(seccion, 597.48, 966.0)
    seccion.left_margin = Pt(54)
    seccion.right_margin = Pt(54)
    seccion.top_margin = Pt(72)
    seccion.bottom_margin = Pt(73.4)
    seccion.header_distance = Pt(0)
    seccion.footer_distance = Pt(22.2)

    seccion.header.is_linked_to_previous = False
    cab = seccion.header.paragraphs[0]
    cab.alignment = WD_ALIGN_PARAGRAPH.CENTER
    espaciado(cab)
    logo(cab)
    marca = OxmlElement("w:rPr")
    cab._p.get_or_add_pPr().append(marca)
    rfonts = OxmlElement("w:rFonts")
    for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{atributo}"), "Verdana")
    marca.append(rfonts)
    for etiqueta in ("w:sz", "w:szCs"):
        e = OxmlElement(etiqueta)
        e.set(qn("w:val"), "22")
        marca.append(e)

    seccion.footer.is_linked_to_previous = False
    pies = seccion.footer
    numero = pies.paragraphs[0]
    _marco_numero_pagina(numero)
    espaciado(numero)
    campo_pagina(numero)
    for run in numero.runs:
        fuente(run, "Times New Roman", 10)
    for indice, texto in enumerate(pie):
        _linea_pie(
            pies.add_paragraph(),
            texto,
            pt_derecha=12,
            porcentaje=108 if indice == 1 else 100,
        )


def configurar_auto(doc, pie: list[str], margenes: dict[str, float] | None = None) -> None:
    seccion = doc.sections[0]
    _pagina(seccion, 612.48, 936.48)
    nombres = {
        "superior": "top_margin",
        "inferior": "bottom_margin",
        "izquierdo": "left_margin",
        "derecho": "right_margin",
        "encabezado": "header_distance",
        "pie": "footer_distance",
    }
    for clave, valor in (margenes or {}).items():
        setattr(seccion, nombres[clave], Pt(valor))
    seccion.footer.is_linked_to_previous = False
    pies = seccion.footer
    for indice, texto in enumerate(pie):
        par = pies.paragraphs[0] if indice == 0 else pies.add_paragraph()
        _linea_pie(par, texto, estilo=False)


def configurar_oficio(doc) -> None:
    _pagina(doc.sections[0], 612.0, 1008.0)


def ajustes_word(doc) -> None:
    ajustes = doc.settings.element
    zoom = ajustes.find(qn("w:zoom"))
    if zoom is None:
        zoom = OxmlElement("w:zoom")
        previos = [e for e in (ajustes.find(qn("w:writeProtection")), ajustes.find(qn("w:view"))) if e is not None]
        if previos:
            previos[-1].addnext(zoom)
        else:
            ajustes.insert(0, zoom)
    zoom.set(qn("w:percent"), "100")
