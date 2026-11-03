from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.shared import Pt

from tutela2 import formato_b
from tutela2.config import Config
from tutela2.letras import MESES, _a_fecha, fecha_larga, numero_titulo
from tutela2.models import DatosAuto, Metadatos
from tutela2.radicado import Juzgado, juzgado_de_radicado, nombre_juzgado

FUENTE = "Bookman Old Style"
TAM = 12.0
MARGENES = {"superior": 70.9, "inferior": 60.0, "izquierdo": 54.0, "derecho": 54.5, "encabezado": 36.0, "pie": 48.9}
PITCH = 16.2
PITCH_SIMPLE = 14.04
SANGRIA_CUERPO = 7.2
SANGRIA_CONSTANCIA = 1.1
SANGRIA_TITULO = 64.0
PIE_FUENTE = "Arial"
PIE_TAM = 8.0

_MARCA = re.compile(r"(⟦[^⟧]*⟧)")


def falta(nombre: str) -> str:
    return f"⟦FALTA: {nombre}⟧"


def _o(valor: str | None, nombre: str) -> str:
    return valor.strip() if valor and valor.strip() else falta(nombre)


def corridas(par, texto: str, fuente: str, tam: float, *, negrita=None, cursiva=None) -> None:
    for trozo in _MARCA.split(texto):
        if not trozo:
            continue
        run = par.add_run(trozo)
        formato_b.fuente(run, fuente, tam, negrita=negrita, cursiva=cursiva)
        if trozo.startswith("⟦"):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def _siguiente_habil(dia):
    dia += timedelta(days=1)
    while dia.weekday() >= 5:
        dia += timedelta(days=1)
    return dia


def auto_por_defecto(md: Metadatos) -> DatosAuto:
    reparto = _a_fecha(md.fechas.reparto_2a)
    return DatosAuto(
        fecha=_siguiente_habil(reparto).isoformat() if reparto else None,
        accionante=md.accionante,
        accionada=", ".join(md.accionadas) or None,
    )


def _juzgado(md: Metadatos) -> Juzgado | None:
    if md.juzgado_a_quo_numero and md.juzgado_a_quo_funcion:
        return Juzgado(
            numero=md.juzgado_a_quo_numero,
            funcion=md.juzgado_a_quo_funcion,
            letras=md.juzgado_a_quo_letras or numero_titulo(md.juzgado_a_quo_numero),
            plural=md.juzgado_a_quo_plural,
        )
    return juzgado_de_radicado(md.cui_1a or "")


def cuando(md: Metadatos, fecha: str | None) -> str:
    reparto = _a_fecha(md.fechas.reparto_2a)
    if reparto is None:
        return falta("fecha de reparto")
    hoy = _a_fecha(fecha)
    if hoy is not None and hoy - reparto == timedelta(days=1):
        return "el día de ayer"
    if hoy is not None and hoy.year == reparto.year:
        return f"el día {reparto.day} de {MESES[reparto.month - 1]} del año en curso"
    return f"el día {fecha_larga(md.fechas.reparto_2a)}"


def _par(doc, texto="", *, alin=WD_ALIGN_PARAGRAPH.LEFT, antes=0.0, pitch=PITCH, negrita=None,
         izq=0.0, der=0.0):
    par = doc.add_paragraph()
    par.alignment = alin
    formato_b.espaciado(par, antes=antes, exacto=pitch)
    if izq:
        par.paragraph_format.left_indent = Pt(izq)
    if der:
        par.paragraph_format.right_indent = Pt(der)
    if texto:
        corridas(par, texto, FUENTE, TAM, negrita=negrita)
    return par


def render_auto(md: Metadatos, datos: DatosAuto, cfg: Config, ruta: Path) -> Path:
    d = cfg.despacho
    doc = Document()
    formato_b.configurar_auto(doc, d.pie_auto, MARGENES)
    formato_b.ajustes_word(doc)
    for par in doc.sections[0].footer.paragraphs:
        for run in par.runs:
            formato_b.fuente(run, PIE_FUENTE, PIE_TAM)
    estilo = doc.styles["Normal"]
    estilo.font.name = FUENTE
    estilo.font.size = Pt(TAM)

    J = WD_ALIGN_PARAGRAPH.JUSTIFY
    C = WD_ALIGN_PARAGRAPH.CENTER
    fecha = fecha_larga(datos.fecha)
    juz = _juzgado(md)
    origen = nombre_juzgado(juz, "digitos") if juz else _o(md.juzgado_a_quo, "juzgado de origen")

    _par(doc, f"Radicado: {_o(md.cui_2a, 'radicado')}")
    _par(doc, f"Accionante: {_o(datos.accionante, 'accionante')}", antes=12)
    _par(doc, f"Accionada: {_o(datos.accionada, 'accionada')}", antes=12)
    constancia = _par(doc, antes=51.4)
    corridas(constancia, "CONSTANCIA", FUENTE, TAM, negrita=True)
    corridas(constancia, ":", FUENTE, TAM)
    _par(
        doc,
        f"Las presentes diligencias fueron recibidas {cuando(md, datos.fecha)}, vía correo "
        f"electrónico por reparto de la Oficina Judicial procedente del {origen}, con "
        "impugnación del fallo de tutela de primera instancia, a Despacho del señor Juez.",
        alin=J, antes=12, izq=SANGRIA_CONSTANCIA,
    )
    _par(doc, f"{d.ciudad}, {fecha}", antes=40.3)
    _par(doc, d.escribiente, antes=24, negrita=True)
    _par(doc, d.cargo_escribiente, pitch=PITCH_SIMPLE)

    logo = doc.add_paragraph()
    logo.alignment = C
    formato_b.espaciado(logo, antes=16.2)
    formato_b.logo(logo)

    _par(doc, d.nombre.replace(" DE MEDELLÍN", ""), alin=C, antes=12, pitch=PITCH_SIMPLE,
         negrita=True, izq=SANGRIA_TITULO, der=SANGRIA_TITULO)
    _par(doc, f"{d.ciudad}, {fecha}", alin=C, antes=14.2, pitch=PITCH_SIMPLE)
    _par(doc, "ASUNTO: AUTO ASUME CONOCIMIENTO DE IMPUGNACIÓN DE TUTELA", alin=C, antes=14.2,
         pitch=PITCH_SIMPLE, negrita=True)
    _par(
        doc,
        "Se asume el conocimiento de las presentes diligencias. En consecuencia, pase el "
        "expediente a Despacho para el pronunciamiento que en derecho corresponda.",
        alin=J, antes=11.5, izq=SANGRIA_CUERPO,
    )
    _par(doc, d.cierre_auto, alin=C, antes=31.1, pitch=PITCH_SIMPLE, negrita=True)
    _par(doc, d.juez, alin=C, antes=96, pitch=PITCH_SIMPLE, negrita=True)
    _par(doc, d.cargo_juez, alin=C, antes=14.4, pitch=PITCH_SIMPLE, negrita=True)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))
    return ruta
