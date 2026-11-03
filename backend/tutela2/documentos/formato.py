from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.table import _Cell

from tutela2 import radicado
from tutela2.config import Config
from tutela2.models import Decision, Metadatos

PLANTILLA = Path(__file__).resolve().parent.parent / "assets" / "formato_factor_calidad.docx"
FILAS_PUNTAJE = (21, 22, 24, 26, 27, 28, 29, 30, 31, 32)
COL_PUNTAJE = 4
TIPO_PROCESO = "SENTENCIA DE TUTELA PRIMERA INSTANCIA"
_SUFIJO_DESPACHO = " DE MEDELLÍN"


def _falta(nombre: str) -> str:
    return f"⟦FALTA: {nombre}⟧"


def _fecha(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _escribir(celda: _Cell, texto: str, *, tam: float = 9, falta: bool = False) -> None:
    par = celda.paragraphs[0]
    runs = par.runs
    run = runs[0] if runs else par.add_run()
    for sobrante in runs[1:]:
        sobrante._r.getparent().remove(sobrante._r)
    run.text = texto
    run.font.size = Pt(tam)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0, 0, 0)
    if falta:
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def _celda(tabla, fila: int, col: int) -> _Cell:
    return _Cell(tabla._tbl.tr_lst[fila].tc_lst[col], tabla)


def _poner_fecha(tabla, tcs: list, cols: tuple[int, int, int], iso: str | None, nombre: str) -> None:
    f = _fecha(iso)
    if f is None:
        for c in range(cols[0], cols[2] + 1):
            _escribir(_Cell(tcs[c], tabla), "")
        celda = _Cell(tcs[cols[0]], tabla).merge(_Cell(tcs[cols[2]], tabla))
        for sobrante in celda.paragraphs[1:]:
            sobrante._p.getparent().remove(sobrante._p)
        _escribir(celda, _falta(nombre), tam=6, falta=True)
        return
    for c, valor in zip(cols, (f"{f.day:02d}", f"{f.month:02d}", str(f.year))):
        _escribir(_Cell(tcs[c], tabla), valor)


def _despacho(md: Metadatos) -> tuple[str, bool]:
    juzgado = None
    if md.juzgado_a_quo_numero and md.juzgado_a_quo_funcion and md.juzgado_a_quo_letras:
        juzgado = radicado.Juzgado(
            numero=md.juzgado_a_quo_numero,
            funcion=md.juzgado_a_quo_funcion,
            letras=md.juzgado_a_quo_letras,
            plural=md.juzgado_a_quo_plural,
        )
        texto = radicado.nombre_juzgado(juzgado, "encabezado")
    elif md.juzgado_a_quo and md.juzgado_a_quo.strip():
        texto = " ".join(md.juzgado_a_quo.upper().split())
    else:
        return _falta("despacho"), True
    if texto.endswith(_SUFIJO_DESPACHO):
        texto = texto[: -len(_SUFIJO_DESPACHO)]
    return texto, False


def _limpiar_cola(doc) -> None:
    cuerpo = doc.element.body
    hijos = list(cuerpo)
    tabla = next(h for h in hijos if h.tag == qn("w:tbl"))
    sect = hijos[-1]
    pasado = False
    conservado = False
    for h in hijos:
        if h is tabla:
            pasado = True
            continue
        if not pasado or h is sect:
            continue
        if not conservado and h.tag == qn("w:p"):
            conservado = True
            for sub in list(h):
                h.remove(sub)
            continue
        cuerpo.remove(h)


def render_formato(md: Metadatos, decision: Decision, cfg: Config, ruta: Path) -> Path:
    doc = Document(str(PLANTILLA))
    t = doc.tables[0]
    despacho = cfg.despacho

    hoy = _fecha(decision.fecha_fallo) or date.today()
    _poner_fecha(t, list(t._tbl.tr_lst[0].tc_lst), (2, 4, 6), hoy.isoformat(), "fecha de la evaluación")

    def texto(valor: str | None, nombre: str) -> tuple[str, bool]:
        v = (valor or "").strip()
        return (v, False) if v else (_falta(nombre), True)

    for col, valor, nombre in (
        (1, md.juez_a_quo_apellidos, "apellidos del juez a quo"),
        (5, md.juez_a_quo_nombres, "nombres del juez a quo"),
    ):
        v, f = texto(valor, nombre)
        _escribir(_celda(t, 4, col), v.upper() if not f else v, falta=f)

    desp, f = _despacho(md)
    _escribir(_celda(t, 6, 1), desp, falta=f)
    _escribir(_celda(t, 6, 4), "MEDELLÍN")
    _escribir(_celda(t, 6, 8), "MEDELLÍN")

    fila_fechas = list(t._tbl.tr_lst[10].tc_lst)
    _poner_fecha(t, fila_fechas, (1, 3, 5), md.fechas.admision, "fecha de admisión")
    _poner_fecha(t, fila_fechas, (10, 12, 14), md.fechas.fallo_a_quo, "fecha de la providencia")

    _escribir(_celda(t, 12, 1), TIPO_PROCESO, tam=7)
    cui = radicado.digitos(md.cui_1a or "")
    _escribir(_celda(t, 12, 3), cui or _falta("código único de identificación"), falta=not cui)
    _escribir(_celda(t, 14, 1), "X", tam=10)

    for fila in FILAS_PUNTAJE:
        _escribir(_celda(t, fila, COL_PUNTAJE), "")

    _escribir(_celda(t, 36, 5), despacho.juez, tam=7)
    _escribir(_celda(t, 37, 5), despacho.cargo_evaluador, tam=7)

    _limpiar_cola(doc)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))
    return ruta
