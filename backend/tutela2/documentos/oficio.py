from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from tutela2 import formato_b
from tutela2.config import Config
from tutela2.documentos.auto import _o, corridas
from tutela2.letras import fecha_larga
from tutela2.models import Metadatos

FUENTE = "Verdana"
TAM = 12.0
MARGEN_IZQ = 85.1
MARGEN_DER = 66.0
MARGEN_SUP = 60.0
MARGEN_INF = 36.0
PITCH = 16.8
PITCH_CUERPO = 21.96
SANGRIA_TITULO = 35.0
SANGRIA_DATOS = 35.4

DESTINATARIO = (
    "Señores",
    "HONORABLES MAGISTRADOS",
    "Corte Constitucional – Sala de Revisión",
    "Calle 12 N° 7 – 65",
    "Bogotá D. C.",
)


def _par(doc, partes, *, alin=WD_ALIGN_PARAGRAPH.LEFT, antes=0.0, pitch=PITCH, izq=0.0, der=0.0):
    par = doc.add_paragraph()
    par.alignment = alin
    formato_b.espaciado(par, antes=antes, exacto=pitch)
    if izq:
        par.paragraph_format.left_indent = Pt(izq)
    if der:
        par.paragraph_format.right_indent = Pt(der)
    for texto, negrita, cursiva in partes:
        corridas(par, texto, FUENTE, TAM, negrita=negrita, cursiva=cursiva)
    return par


def render_oficio(md: Metadatos, fecha: str | None, cfg: Config, ruta: Path) -> Path:
    d = cfg.despacho
    doc = Document()
    formato_b.configurar_oficio(doc)
    formato_b.ajustes_word(doc)
    seccion = doc.sections[0]
    seccion.left_margin = Pt(MARGEN_IZQ)
    seccion.right_margin = Pt(MARGEN_DER)
    seccion.top_margin = Pt(MARGEN_SUP)
    seccion.bottom_margin = Pt(MARGEN_INF)
    estilo = doc.styles["Normal"]
    estilo.font.name = FUENTE
    estilo.font.size = Pt(TAM)

    C = WD_ALIGN_PARAGRAPH.CENTER
    logo = doc.add_paragraph()
    logo.alignment = C
    formato_b.espaciado(logo, antes=38)
    formato_b.logo(logo)

    accionante = _o(md.accionante, "accionante")
    accionadas = _o(", ".join(md.accionadas), "accionado")
    _par(doc, [(d.nombre.replace(" DE MEDELLÍN", ""), True, True)], alin=C, antes=0,
         izq=SANGRIA_TITULO, der=SANGRIA_TITULO)
    _par(doc, [(f"{d.ciudad}, {fecha_larga(fecha)}", None, None)], alin=C, antes=12)
    _par(doc, [("Asunto: ", None, None), ("REMISIÓN EXPEDIENTE DE TUTELA EN REVISIÓN", None, None)],
         antes=16.8)
    for i, linea in enumerate(DESTINATARIO):
        _par(doc, [(linea, True, None)], antes=16.8 if i == 0 else 0)
    _par(doc, [("Cordial Saludo", None, None)], antes=43.7)
    _par(
        doc,
        [(
            "De manera comedida y de conformidad con lo preceptuado en el artículo 31 del "
            "Decreto 2591 de 1991, les remito para su eventual revisión la acción de tutela "
            "relacionada a continuación.",
            None, None,
        )],
        alin=WD_ALIGN_PARAGRAPH.JUSTIFY, antes=22.3, pitch=PITCH_CUERPO,
    )
    _par(doc, [(f"Radicado: {_o(md.cui_2a, 'radicado')}", True, None)], antes=33.3, izq=SANGRIA_DATOS)
    _par(doc, [(f"Accionante: {accionante.upper()}", True, None)], izq=SANGRIA_DATOS)
    _par(doc, [(f"Accionado: {accionadas.upper()}", True, None)], izq=SANGRIA_DATOS)
    _par(doc, [(d.firmante_oficio, True, None)], antes=155.8, izq=SANGRIA_DATOS)
    _par(doc, [(d.cargo_firmante_oficio, True, None)], izq=SANGRIA_DATOS)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(ruta))
    return ruta
