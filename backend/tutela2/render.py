from __future__ import annotations

import functools
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, TypeVar

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from pydantic import BaseModel

from tutela2 import fallos, formato_b, formulas, normas, prompts, vista
from tutela2.config import Config
from tutela2.formulas import encabezado_decision as decision_encabezado
from tutela2.letras import fecha_larga, numero_a_letras
from tutela2.models import (
    AperturaLLM,
    CasoConcretoLLM,
    CitaVerificada,
    ConsideracionesLLM,
    Decision,
    Fechas,
    Ingesta,
    LlamadaIA,
    Metadatos,
)

__all__ = ["decision_encabezado", "fecha_larga", "numero_a_letras"]

log = logging.getLogger(__name__)

FUENTE = "Bookman Old Style"

GEN = {
    "A": {
        "III": "FALLO RECURRIDO",
        "IV": "IMPUGNACIÓN",
        "V": "CONSIDERACIONES DEL JUZGADO",
        "merito": "administrando justicia en nombre del Pueblo y por mandato Constitucional,",
        "pagina_cm": (21.6, 33.0),
    },
    "B": {
        "III": "LA SENTENCIA IMPUGNADA",
        "IV": "LA IMPUGNACIÓN",
        "V": "CONSIDERACIONES",
        "merito": "administrando justicia en nombre de la República y por autoridad de la Ley,",
        "pagina_cm": (21.1, 34.1),
    },
}

ROLES_ES = {
    "acta_reparto_2a": "acta de reparto de segunda instancia",
    "escrito_tutela": "escrito de tutela",
    "auto_admisorio": "auto admisorio de la tutela",
    "fallo_a_quo": "fallo de tutela de primera instancia",
    "impugnacion": "escrito de impugnación",
    "auto_concede_impugnacion": "auto que concede la impugnación",
}

ZONAS = {
    "I": (4.44, 10.58, 14.15),
    "III": (4.44, 4.08, 12.0),
    "V_plantilla": (11.42, 23.88, 12.0),
    "V_modelo": (14.18, 0.0, 12.0),
    "VI": (14.18, 0.0, 14.15),
}
ESCALA_TITULO = {
    "ASUNTO": 114,
    "ANTECEDENTES DEL CASO": 114,
    "LA SENTENCIA IMPUGNADA": 114,
    "LA IMPUGNACIÓN": 114,
    "CONSIDERACIONES": 119,
    "RESUELVE": 114,
}
ETIQUETA_ESCALADA = {"LA SENTENCIA IMPUGNADA", "LA IMPUGNACIÓN", "CONSIDERACIONES"}
TRAS_TITULO = {
    "ASUNTO": (None, 14.15),
    "ANTECEDENTES DEL CASO": (1.5, 14.15),
    "LA SENTENCIA IMPUGNADA": (None, 12.0),
    "LA IMPUGNACIÓN": (None, 12.0),
    "CONSIDERACIONES": (1.0, 12.0),
    "CASO CONCRETO": (None, 14.15),
    "OTRAS DETERMINACIONES": (None, 14.15),
    "RESUELVE": (1.0, 12.0),
}
ESCALAS_FILA = {
    "radicado": (109, 109),
    "accionante": (114, 100),
    "accionada": (109, 100),
    "vinculada": (114, 114),
    "procedencia": (114, 114),
    "derechos": (109, 109),
    "decision": (109, 114),
}
ANCHOS_TABLA = [120.39, 250.73]
CITA_IZQ, CITA_DER, CITA_TAM = 42.62, 49.95, 11
ALTO_FIRMA = 64.6
SANGRIA_TITULO = 18.9
HUECO_ETIQUETA = 14.28
ANCHO_ETIQUETA = {
    "I.": 8.9, "II.": 13.7, "III.": 20.9, "IV.": 19.8, "V.": 15.0, "VI.": 17.6, "VII.": 22.4, "VIII.": 27.3,
}

_CITA = re.compile(r"\[\[CITA:\s*([^\]\s]+)\s*\]\]")
_IMAGEN = re.compile(r"\[\[IMAGEN([^\]]*)\]\]")
_MARCA = re.compile(r"(⟦[^⟧]*⟧)")

_ALINEACION = {
    "j": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "c": WD_ALIGN_PARAGRAPH.CENTER,
    "i": WD_ALIGN_PARAGRAPH.LEFT,
    "d": WD_ALIGN_PARAGRAPH.RIGHT,
}

M = TypeVar("M", bound=BaseModel)


def _como(cls: type[M], valor: Any) -> M:
    return valor if isinstance(valor, cls) else cls.model_validate(valor)


def _falta(nombre: str) -> str:
    return f"⟦FALTA: {nombre}⟧"


def _o(valor: str | None, nombre: str) -> str:
    return valor.strip() if valor and valor.strip() else _falta(nombre)



def _romano(n: int) -> str:
    salida = ""
    for valor, simbolo in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= valor:
            salida += simbolo
            n -= valor
    return salida



def _referencia_local(cv: CitaVerificada) -> str:
    if cv.tipo and cv.numero and cv.anio:
        base = f"Sentencia {cv.tipo}-{cv.numero:03d} de {cv.anio}"
    else:
        base = f"Sentencia {cv.sentencia_original}"
    return f"{base}, con ponencia del Magistrado {cv.mp_dataset.title()}" if cv.mp_dataset else base


def _referencia(cv: CitaVerificada) -> str:
    try:
        from tutela2.citas import formatear_referencia
    except ImportError:
        return _referencia_local(cv)
    return formatear_referencia(cv)



def _negritas_en(texto: str, negritas) -> list[tuple[str, bool]]:
    spans: list[list[int]] = []
    for n in negritas:
        i = texto.find(n) if n else -1
        if i >= 0:
            spans.append([i, i + len(n)])
    spans.sort()
    fusion: list[list[int]] = []
    for ini, fin in spans:
        if fusion and ini <= fusion[-1][1]:
            fusion[-1][1] = max(fusion[-1][1], fin)
        else:
            fusion.append([ini, fin])
    salida, pos = [], 0
    for ini, fin in fusion:
        if ini > pos:
            salida.append((texto[pos:ini], False))
        salida.append((texto[ini:fin], True))
        pos = fin
    if pos < len(texto):
        salida.append((texto[pos:], False))
    return salida


def _tam_marca(par, tam: float) -> None:
    ppr = par._p.get_or_add_pPr()
    rpr = OxmlElement("w:rPr")
    for etiqueta in ("w:sz", "w:szCs"):
        e = OxmlElement(etiqueta)
        e.set(qn("w:val"), str(round(tam * 2)))
        rpr.append(e)
    ppr.append(rpr)


def _bloque(tipo: str):
    def decorar(f):
        @functools.wraps(f)
        def envoltura(d, *args, **kwargs):
            with d.reg.como(tipo):
                return f(d, *args, **kwargs)

        return envoltura

    return decorar


def _idioma_es(doc) -> None:
    for lang in doc.styles.element.iter(qn("w:lang")):
        lang.set(qn("w:val"), "es-CO")
        lang.set(qn("w:eastAsia"), "es-CO")


class _Docx:
    def __init__(
        self,
        cfg: Config,
        citas: dict[str, CitaVerificada] | None = None,
        titulo: str = "",
        fallo: bool = False,
    ):
        self.cfg = cfg
        self.citas = citas or {}
        self.citadas: set[str] = set()
        self.seccion = 0
        self.b = fallo and cfg.plantilla_gen == "B"
        self.zona_actual = ZONAS["I"]
        self.primero: float | None = None
        self.antes_titulo: float | None = None
        self.pendiente = 0.0
        self.reg = vista.Registro()
        self.doc = Document()
        formato_b.ajustes_word(self.doc)
        _idioma_es(self.doc)
        self.doc.core_properties.author = cfg.despacho.nombre_cuerpo
        self.doc.core_properties.title = titulo
        self._formato()

    def _formato(self) -> None:
        normal = self.doc.styles["Normal"]
        normal.font.name = FUENTE
        normal.font.size = Pt(12)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
        if self.b:
            formato_b.configurar_fallo(self.doc, self.cfg.despacho.pie_fallo)
            normal.paragraph_format.space_before = Pt(0)
            normal.paragraph_format.space_after = Pt(0)
            normal.paragraph_format.line_spacing = 1.0
            return

        gen = GEN[self.cfg.plantilla_gen]
        seccion = self.doc.sections[0]
        seccion.page_width, seccion.page_height = (Cm(x) for x in gen["pagina_cm"])
        seccion.left_margin = seccion.right_margin = Cm(2.5)
        seccion.top_margin = seccion.bottom_margin = Cm(2.5)
        normal.paragraph_format.space_after = Pt(8)
        normal.paragraph_format.line_spacing = 1.15

        pie = seccion.footer
        pie.is_linked_to_previous = False
        primero = pie.paragraphs[0]
        if self.cfg.plantilla_gen == "B":
            primero.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = primero.add_run("1")
            run.font.size = Pt(9)
            campo = OxmlElement("w:fldSimple")
            campo.set(qn("w:instr"), "PAGE")
            run._r.addprevious(campo)
            campo.append(run._r)
            primero = pie.add_paragraph()
        primero.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.escribir(primero, self.cfg.despacho.pie, tam=9)

    def escribir(self, par, texto: str, *, negrita: bool = False, cursiva: bool = False, tam: float | None = None) -> None:
        for trozo in _MARCA.split(texto):
            if not trozo:
                continue
            run = par.add_run(trozo)
            self.reg.segmento(par._p, trozo, negrita, cursiva)
            run.bold = negrita or None
            run.italic = cursiva or None
            if tam:
                run.font.size = Pt(tam)
            if trozo.startswith("⟦"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def parrafo(
        self,
        texto: str = "",
        *,
        alinear: str = "j",
        negrita: bool = False,
        cursiva: bool = False,
        tam: float | None = None,
        sangria: float = 0.0,
        antes: float | None = None,
        mantener: bool = False,
    ):
        par = self.doc.add_paragraph()
        par.alignment = _ALINEACION[alinear]
        formato = par.paragraph_format
        if sangria:
            formato.left_indent = Cm(sangria)
        if antes is not None:
            formato.space_before = Pt(antes)
        formato.keep_with_next = mantener or None
        self.escribir(par, texto, negrita=negrita, cursiva=cursiva, tam=tam)
        return par

    def corridas(
        self,
        par,
        texto: str,
        *,
        tam: float = 12,
        negrita: bool = False,
        cursiva: bool = False,
        subrayado: bool = False,
        esc: int = 100,
        negritas=(),
    ) -> None:
        for segmento, resaltado in _negritas_en(texto, negritas):
            for trozo in _MARCA.split(segmento):
                if not trozo:
                    continue
                run = par.add_run(trozo)
                self.reg.segmento(par._p, trozo, negrita or resaltado, cursiva)
                formato_b.fuente(
                    run,
                    FUENTE,
                    tam,
                    negrita=True if (negrita or resaltado) else None,
                    cursiva=True if cursiva else None,
                    subrayado=True if subrayado else None,
                )
                formato_b.escala(run, esc)
                if trozo.startswith("⟦"):
                    run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def par_b(
        self,
        *,
        alinear: str = "j",
        izq: float = 0.0,
        der: float = 0.0,
        primera: float = 0.0,
        antes: float = 0.0,
        despues: float = 0.0,
        multiple: float | None = 1.0,
        exacto: float | None = None,
        mantener: bool = False,
        marca: float | None = None,
    ):
        par = self.doc.add_paragraph()
        par.alignment = _ALINEACION[alinear]
        formato = par.paragraph_format
        if izq:
            formato.left_indent = Pt(izq)
        if der:
            formato.right_indent = Pt(der)
        if primera:
            formato.first_line_indent = Pt(primera)
        formato_b.espaciado(par, antes=max(antes - self.pendiente, 0), despues=despues, multiple=multiple, exacto=exacto)
        self.pendiente = despues
        if mantener:
            formato.keep_with_next = True
        if marca:
            _tam_marca(par, marca)
        return par

    def vacio(self, multiple: float | None = 1.0, **kw):
        return self.par_b(multiple=multiple, **kw)

    def zona(self, nombre: str) -> None:
        if self.b:
            self.zona_actual = ZONAS[nombre]

    def _antes_zona(self) -> float:
        antes = self.zona_actual[2]
        if self.primero is not None:
            antes, self.primero = self.primero, None
        return antes

    def cuerpo(self, texto: str, *, esc: int = 100, alinear: str = "j", negritas=(), antes: float | None = None):
        izq, der, _ = self.zona_actual
        par = self.par_b(
            alinear=alinear,
            izq=izq,
            der=der,
            antes=self._antes_zona() if antes is None else antes,
            multiple=1.5,
        )
        self.corridas(par, texto, esc=esc, negritas=negritas)
        return par

    def plantilla(self, texto: str):
        return self.cuerpo(texto) if self.b else self.parrafo(texto)

    @_bloque("encabezado")
    def subtitulo(self, texto: str):
        if not self.b:
            return self.parrafo(texto, alinear="i", negrita=True, mantener=True)
        izq, der, _ = self.zona_actual
        par = self.par_b(alinear="i", izq=izq, der=der, antes=self._antes_zona(), multiple=1.5, mantener=True)
        self.corridas(par, texto, negrita=True)
        return par

    @_bloque("titulo")
    def titulo(self, texto: str, numerar: bool = True) -> None:
        self.reg.abrir_seccion(texto)
        etiqueta = ""
        if numerar:
            self.seccion += 1
            etiqueta = f"{_romano(self.seccion)}."
        if not self.b:
            self.parrafo(f"{etiqueta} {texto}" if etiqueta else texto, alinear="c", negrita=True, antes=14, mantener=True)
            return
        esc = ESCALA_TITULO.get(texto, 100)
        antes = 21.3 if self.antes_titulo is None else self.antes_titulo
        self.antes_titulo = None
        par = self.par_b(alinear="c", izq=SANGRIA_TITULO, antes=antes, mantener=True)
        if etiqueta:
            ancho = ANCHO_ETIQUETA.get(etiqueta)
            if ancho:
                par.paragraph_format.first_line_indent = Pt(-(ancho + HUECO_ETIQUETA))
                par.paragraph_format.tab_stops.add_tab_stop(Pt(SANGRIA_TITULO))
            self.corridas(par, etiqueta, negrita=True, esc=esc if texto in ETIQUETA_ESCALADA else 100)
            self.corridas(par, "\t" + texto, negrita=True, esc=esc)
        else:
            self.corridas(par, texto, negrita=True, esc=esc)
        vacio, primero = TRAS_TITULO.get(texto, (1.0, None))
        if vacio is not None:
            self.vacio(vacio, mantener=True)
        self.primero = primero

    @_bloque("lista")
    def item(self, texto: str) -> None:
        par = self.doc.add_paragraph(style="List Bullet")
        self.escribir(par, texto, tam=10)

    @_bloque("cita_bloque")
    def cita_bloque(self, texto: str) -> None:
        texto = f"“{' '.join(texto.split())}”"
        if not self.b:
            par = self.parrafo(texto, cursiva=True, tam=11, sangria=1.5)
            par.paragraph_format.right_indent = Cm(1.5)
            return
        par = self.par_b(izq=CITA_IZQ, der=CITA_DER, antes=12, despues=12, multiple=1.5)
        self.corridas(par, texto, tam=CITA_TAM, cursiva=True, subrayado=True)

    def _referencia(self, id_: str) -> str:
        cv = self.citas.get(id_)
        if cv is None:
            return f"⟦CITA NO VERIFICADA: {id_}⟧"
        if cv.estado == "rechazada":
            return f"⟦CITA NO VERIFICADA: {cv.sentencia_original}⟧"
        return _referencia(cv)

    def _bloques_citados(self, texto: str) -> None:
        for id_ in _CITA.findall(texto):
            if id_ in self.citadas:
                continue
            self.citadas.add(id_)
            cv = self.citas.get(id_)
            if cv is not None and cv.estado != "rechazada":
                with self.reg.como(cita=id_):
                    self.cita_bloque(cv.texto_citado)

    def _citas_en(self, texto: str) -> tuple[str, list[tuple[int, int, str]]]:
        partes: list[str] = []
        spans: list[tuple[int, int, str]] = []
        pos = largo = 0
        for m in _CITA.finditer(texto):
            previo = texto[pos : m.start()]
            referencia = self._referencia(m.group(1))
            spans.append((largo + len(previo), largo + len(previo) + len(referencia), m.group(1)))
            partes += [previo, referencia]
            largo += len(previo) + len(referencia)
            pos = m.end()
        partes.append(texto[pos:])
        return "".join(partes), spans

    def prosa(self, texto: str, *, citar: bool = False, esc: int = 100, modelo: bool = False) -> None:
        with self.reg.como(origen="modelo" if modelo else self.reg.origen):
            self._prosa(texto, citar=citar, esc=esc)

    def _prosa(self, texto: str, *, citar: bool, esc: int) -> None:
        for bloque in re.split(r"\n\s*\n", texto.strip()):
            bloque = " ".join(bloque.split())
            for i, parte in enumerate(_IMAGEN.split(bloque)):
                if i % 2:
                    marcador = f"⟦INSERTAR IMAGEN: {parte.strip()}⟧"
                    if self.b:
                        self.cuerpo(marcador, alinear="i")
                    else:
                        self.parrafo(marcador, alinear="i")
                elif parte.strip():
                    limpio, spans = self._citas_en(parte.strip())
                    with self.reg.como(spans=spans):
                        if self.b:
                            self.cuerpo(limpio, esc=esc)
                        else:
                            self.parrafo(limpio)
                    if citar:
                        self._bloques_citados(parte)

    @_bloque("tabla")
    def tabla(
        self,
        filas: list[list[str]],
        anchos: list[float],
        *,
        cabecera: list[str] | None = None,
        bordes: bool = True,
        tam: float = 10,
        etiquetas: bool = False,
    ) -> None:
        todas = ([cabecera] if cabecera else []) + filas
        tabla = self.doc.add_table(rows=len(todas), cols=len(anchos))
        if bordes:
            tabla.style = "Table Grid"
        tabla.autofit = False
        for columna, ancho in zip(tabla.columns, anchos):
            columna.width = Cm(ancho)
        for i, fila in enumerate(todas):
            for j, valor in enumerate(fila):
                celda = tabla.cell(i, j)
                celda.width = Cm(anchos[j])
                par = celda.paragraphs[0]
                par.paragraph_format.space_after = Pt(2)
                par.paragraph_format.line_spacing = 1.0
                self.escribir(par, str(valor), negrita=(bool(cabecera) and i == 0) or (etiquetas and j == 0), tam=tam)
        self.parrafo("", tam=4)

    @_bloque("tabla")
    def tabla_encabezado(self, filas: list[tuple[str, str, str]]) -> None:
        tabla = self.doc.add_table(rows=len(filas), cols=2)
        formato_b.anchos_columnas(tabla, ANCHOS_TABLA)
        formato_b.bordes_tabla(tabla, 4)
        formato_b.sangria_tabla(tabla, 54.02)
        for fila, (clave, etiqueta, valor) in zip(tabla.rows, filas):
            formato_b.alto_minimo_fila(fila, 21.8)
            esc_etiqueta, esc_valor = ESCALAS_FILA[clave]
            for celda, texto, negrita, esc in (
                (fila.cells[0], etiqueta, True, esc_etiqueta),
                (fila.cells[1], valor, False, esc_valor),
            ):
                par = celda.paragraphs[0]
                par.alignment = WD_ALIGN_PARAGRAPH.LEFT
                formato_b.espaciado(par)
                self.corridas(par, texto, negrita=negrita, esc=esc)

    def guardar(self, ruta: Path | str) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(ruta)
        return ruta

    def guardar_con_vista(self, ruta: Path | str, tipo: str) -> Path:
        ruta = self.guardar(ruta)
        destino = ruta.parent / vista.ARCHIVOS[tipo]
        try:
            self._escribir_vista(ruta, tipo, destino)
        except Exception:
            log.exception("No se pudo escribir la vista previa de %s", ruta.name)
            destino.unlink(missing_ok=True)
        return ruta

    def _escribir_vista(self, ruta: Path, tipo: str, destino: Path) -> None:
        bloques = vista.bloques_cuerpo(self.reg, self.doc)
        citadas = {s["cita_id"] for b in bloques for s in b["segmentos"] if "cita_id" in s}
        citas = [vista.cita_vista(cv, _referencia(cv)) for cv in self.citas.values()]
        citas += [
            {"id": i, "texto": "", "fuente": i, "cobertura": None, "estado": "rechazada", "detalle": None}
            for i in sorted(citadas - self.citas.keys())
        ]
        sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
        datos = vista.armar(tipo, sha, bloques, vista.textos_pie(self.doc), citas, self.cfg.plantilla_gen)
        vista.guardar(datos, destino)


@dataclass
class _Caso:
    md: Metadatos
    apertura: AperturaLLM | None
    consideraciones: ConsideracionesLLM | None
    citas: list[CitaVerificada]
    caso: CasoConcretoLLM | None
    decision: Decision | None
    decision_raw: dict
    alertas: dict[str, list[str]]
    errores: list[str]
    bitacora: list[LlamadaIA]
    fallos: list[dict] = field(default_factory=list)

    @property
    def citas_por_id(self) -> dict[str, CitaVerificada]:
        return {c.id: c for c in self.citas}


def _vacio(valor: Any) -> bool:
    return valor in (None, "", []) or valor == Fechas()


def _rellenar(md: Metadatos, otro: Metadatos) -> Metadatos:
    faltan = {
        campo: getattr(otro, campo)
        for campo in Metadatos.model_fields
        if _vacio(getattr(md, campo)) and not _vacio(getattr(otro, campo))
    }
    return md.model_copy(update=faltan)


def _opcional(cls: type[M], valor: Any) -> M | None:
    return _como(cls, valor) if valor else None


def _leer(estado: dict) -> _Caso:
    apertura = _opcional(AperturaLLM, estado.get("apertura"))
    md = _como(Metadatos, estado.get("metadatos") or {})
    ingesta = estado.get("ingesta")
    if ingesta:
        md = _rellenar(md, _como(Ingesta, ingesta).metadatos)
    if apertura:
        md = _rellenar(md, Metadatos.model_validate(apertura.metadatos.model_dump()))

    decision, raw = None, {}
    for item in reversed(estado.get("decisiones") or []):
        candidata = _como(Decision, item)
        if candidata.accion == "decidir":
            decision = candidata
            raw = item if isinstance(item, dict) else item.model_dump()
            break

    return _Caso(
        md=md,
        apertura=apertura,
        consideraciones=_opcional(ConsideracionesLLM, estado.get("consideraciones")),
        citas=[_como(CitaVerificada, c) for c in estado.get("citas") or []],
        caso=_opcional(CasoConcretoLLM, estado.get("caso")),
        decision=decision,
        decision_raw=raw,
        alertas={k: list(v) for k, v in (estado.get("alertas") or {}).items()},
        errores=list(estado.get("errores") or []),
        bitacora=[_como(LlamadaIA, b) for b in estado.get("bitacora") or []],
        fallos=fallos.leer(estado.get("caso_dir")),
    )



def _encabezado(d: _Docx, c: _Caso, *, fecha: str | None, con_decision: bool) -> None:
    if d.b:
        par = d.par_b(alinear="i", izq=197.21, primera=-140.43, antes=10, multiple=1.14)
        d.corridas(par, d.cfg.despacho.nombre.upper(), negrita=True, esc=114)
        if fecha:
            par = d.par_b(alinear="c", antes=11.3)
            d.corridas(par, f"{d.cfg.despacho.ciudad}, {fecha_larga(fecha)}", esc=109)
        d.vacio(antes=11.5 if fecha else 0)
        d.tabla_encabezado(formulas.filas_encabezado(c.md, c.decision if con_decision else None))
        d.vacio()
        d.vacio()
        d.antes_titulo = 0.0
        return
    d.parrafo(d.cfg.despacho.nombre, alinear="c", negrita=True)
    if fecha:
        d.parrafo(f"{d.cfg.despacho.ciudad}, {fecha_larga(fecha)}", alinear="c")
    filas = [["ASUNTO", "TUTELA DE SEGUNDA INSTANCIA"]]
    filas += [[etiqueta.upper(), valor] for _, etiqueta, valor in formulas.filas_encabezado(c.md, c.decision if con_decision else None)]
    d.tabla(filas, [4.5, 11.6], bordes=False, tam=12, etiquetas=True)


def _consideraciones(d: _Docx, c: _Caso) -> None:
    gen = d.cfg.plantilla_gen
    d.titulo(GEN[gen]["V"])
    if gen == "B":
        d.zona("V_plantilla")
        d.subtitulo(formulas.SUBTITULO_COMPETENCIA)
        d.plantilla(formulas.COMPETENCIA_1)
        d.plantilla(formulas.competencia_2(c.md))
        d.subtitulo(formulas.SUBTITULO_PROCEDIBILIDAD)
        d.plantilla(formulas.PROCEDIBILIDAD_P1)
        d.plantilla(formulas.PROCEDIBILIDAD_P2)
        d.zona("V_modelo")
    cons = c.consideraciones
    if cons is None:
        d.prosa(_falta("consideraciones"))
    else:
        with d.reg.como(origen="modelo"):
            d.prosa(cons.procedibilidad, citar=True)
            for bloque in cons.bloques:
                d.subtitulo(bloque.titulo)
                d.prosa(bloque.texto, citar=True)
    d.plantilla(formulas.TRANSICION)


def _secciones_i_a_v(d: _Docx, c: _Caso) -> None:
    gen = GEN[d.cfg.plantilla_gen]
    ap = c.apertura
    d.zona("I")
    d.titulo("ASUNTO")
    d.prosa(formulas.asunto(c.md), esc=114)
    d.titulo("ANTECEDENTES DEL CASO")
    if ap is None:
        d.prosa(_falta("apertura"))
    else:
        d.prosa(ap.antecedentes_hechos, modelo=True)
        for contestacion in ap.contestaciones:
            d.prosa(contestacion.texto, modelo=True)
    d.zona("III")
    d.titulo(gen["III"])
    d.prosa(ap.sentencia_impugnada if ap else _falta("sentencia impugnada"), modelo=ap is not None)
    d.titulo(gen["IV"])
    d.prosa(ap.impugnacion if ap else _falta("impugnación"), esc=104, modelo=ap is not None)
    _consideraciones(d, c)


def _caso_concreto(d: _Docx, c: _Caso) -> None:
    d.zona("VI")
    d.titulo("CASO CONCRETO")
    if d.cfg.plantilla_gen == "A":
        d.parrafo(formulas.COMPETENCIA_1)
    if c.caso is None:
        d.prosa(_falta("caso concreto"))
        return
    with d.reg.como(origen="modelo"):
        d.prosa(c.caso.problema_juridico)
        for parrafo in c.caso.parrafos:
            d.prosa(parrafo.texto)
        d.prosa(c.caso.conclusion)


def _otras_determinaciones(d: _Docx, decision: Decision) -> None:
    compulsa = decision.compulsa
    d.zona("VI")
    d.titulo("OTRAS DETERMINACIONES")
    if compulsa.hechos_ref.strip():
        d.prosa(compulsa.hechos_ref)
    d.plantilla(formulas.cierre_otras_determinaciones(compulsa))


@_bloque("firma")
def _firma_juez(d: _Docx) -> None:
    d.parrafo(_o(d.cfg.despacho.juez, "nombre del juez").upper(), alinear="c", negrita=True, antes=40)
    d.parrafo(d.cfg.despacho.cargo_juez, alinear="c", negrita=True)


@_bloque("firma")
def _centrado_b(d: _Docx, texto: str, mantener: bool = False) -> None:
    par = d.par_b(alinear="c", mantener=mantener)
    d.corridas(par, texto, negrita=True)


def _resolutiva(d: _Docx, c: _Caso) -> None:
    gen = d.cfg.plantilla_gen
    nombre = d.cfg.despacho.nombre_cuerpo
    numerales = formulas.numerales(c.decision, c.md)
    d.zona("VI")
    if gen == "A":
        d.titulo("PARTE RESOLUTIVA")
        d.parrafo(f"{formulas.MERITO_ANTES}{nombre}, {GEN[gen]['merito']}")
        with d.reg.como("encabezado"):
            d.parrafo("RESUELVE", alinear="c", negrita=True, antes=10, mantener=True)
        with d.reg.como("resuelve_numeral"):
            for i, numeral in enumerate(numerales, 1):
                par = d.parrafo()
                d.escribir(par, f"{formulas.ordinal(i)}: ", negrita=True)
                d.escribir(par, numeral.texto)
                for linea in numeral.literales:
                    d.parrafo(linea, sangria=1.0)
        with d.reg.como("firma"):
            d.parrafo(d.cfg.despacho.cierre_fallo, alinear="c", negrita=True, antes=14)
        _firma_juez(d)
        return

    d.cuerpo(f"{formulas.MERITO_ANTES}{nombre}{formulas.MERITO_DESPUES}", negritas=[nombre])
    d.titulo("RESUELVE")
    bloques: list[tuple[str, list[str]]] = []
    for i, numeral in enumerate(numerales, 1):
        ordinal = f"{formulas.ordinal(i)}: "
        bloques.append((ordinal + numeral.texto, [ordinal, *numeral.negritas]))
        bloques.extend((literal, []) for literal in numeral.literales)
    for i, (texto, negritas) in enumerate(bloques):
        if i:
            d.vacio(1.5)
        with d.reg.como("resuelve_numeral"):
            d.cuerpo(texto, esc=104, negritas=negritas, antes=None if i == 0 else 0)
    d.par_b(alinear="c", marca=11, mantener=True)
    _centrado_b(d, d.cfg.despacho.cierre_fallo, mantener=True)
    d.par_b(alinear="c", multiple=None, exacto=ALTO_FIRMA, mantener=True)
    _centrado_b(d, _o(d.cfg.despacho.juez, "nombre del juez").upper(), mantener=True)
    _centrado_b(d, d.cfg.despacho.cargo_juez)


def _tabla_citas(d: _Docx, citas: list[CitaVerificada]) -> None:
    if not citas:
        d.parrafo("No hay citas de jurisprudencia.", alinear="i")
        return
    conteo = {e: sum(1 for x in citas if x.estado == e) for e in ("ok", "alerta", "rechazada")}
    d.parrafo(
        f"{len(citas)} citas: {conteo['ok']} ok, {conteo['alerta']} con alerta, "
        f"{conteo['rechazada']} {'rechazada' if conteo['rechazada'] == 1 else 'rechazadas'}.",
        alinear="i",
    )
    filas = [
        [
            cv.sentencia_norm or cv.sentencia_original,
            cv.estado.upper(),
            f"{cv.cobertura * 100:.0f} %" if cv.cobertura is not None else "—",
            cv.mp_dataset or "—",
            cv.url or "—",
            "; ".join(cv.motivos) or "—",
        ]
        for cv in citas
    ]
    d.tabla(
        filas,
        [2.8, 1.9, 1.8, 3.0, 3.6, 3.0],
        cabecera=["Sentencia", "Estado", "Cobertura", "M.P. (dataset)", "URL", "Motivos"],
        tam=8,
    )


def _alertas(d: _Docx, alertas: dict[str, list[str]]) -> None:
    con_mensajes = {nodo: msgs for nodo, msgs in alertas.items() if msgs}
    if not con_mensajes:
        d.parrafo("Sin alertas.", alinear="i")
    for nodo, mensajes in con_mensajes.items():
        d.parrafo(nodo, alinear="i", negrita=True, mantener=True)
        for mensaje in mensajes:
            d.item(mensaje)


def render_previo(estado: dict, cfg: Config | dict, ruta: Path) -> Path:
    cfg = _como(Config, cfg)
    c = _leer(estado)
    d = _Docx(cfg, c.citas_por_id, "Borrador previo", fallo=True)
    with d.reg.como("encabezado"):
        _encabezado(d, c, fecha=None, con_decision=False)
        d.parrafo("BORRADOR PREVIO A LA DECISIÓN (SECCIONES I A V)", alinear="c", negrita=True)
    _secciones_i_a_v(d, c)
    d.titulo("INFORME DE CITAS", numerar=False)
    _tabla_citas(d, c.citas)
    d.titulo("ALERTAS POR NODO", numerar=False)
    _alertas(d, c.alertas)
    return d.guardar_con_vista(ruta, "borrador")


def render_fallo(estado: dict, cfg: Config | dict, ruta: Path, hoy: date | None = None) -> Path:
    cfg = _como(Config, cfg)
    c = _leer(estado)
    if c.decision is None:
        raise ValueError("No hay una decisión humana registrada: no se puede generar el fallo.")
    d = _Docx(cfg, c.citas_por_id, "Fallo de tutela de segunda instancia", fallo=True)
    with d.reg.como("encabezado"):
        _encabezado(d, c, fecha=c.decision.fecha_fallo or (hoy or date.today()).isoformat(), con_decision=True)
    _secciones_i_a_v(d, c)
    _caso_concreto(d, c)
    if c.decision.compulsa:
        _otras_determinaciones(d, c.decision)
    _resolutiva(d, c)
    return d.guardar_con_vista(ruta, "fallo")


def render_informe(estado: dict, cfg: Config | dict, ruta: Path) -> Path:
    cfg = _como(Config, cfg)
    c = _leer(estado)
    d = _Docx(cfg, c.citas_por_id, "Informe de verificación")
    d.parrafo(cfg.despacho.nombre, alinear="c", negrita=True)
    d.parrafo("INFORME DE VERIFICACIÓN", alinear="c", negrita=True)
    d.parrafo(f"Radicado: {_o(c.md.cui_2a or c.md.cui_1a, 'radicado')}", alinear="i")
    d.titulo("CITAS DE JURISPRUDENCIA")
    _tabla_citas(d, c.citas)
    d.titulo("CITAS NORMATIVAS (NO VERIFICADAS AUTOMÁTICAMENTE)")
    _citas_normativas(d, c)
    d.titulo("ALERTAS POR NODO")
    _alertas(d, c.alertas)
    d.titulo("ERRORES BLOQUEANTES VIGENTES")
    if c.errores:
        for error in c.errores:
            d.item(error)
    else:
        d.parrafo("No hay errores bloqueantes vigentes.", alinear="i")
    d.titulo("BITÁCORA DE LLAMADAS A LA IA")
    if not c.bitacora:
        d.parrafo("No se registraron llamadas a la IA.", alinear="i")
    else:
        d.tabla(
            [
                [
                    f"{b.nodo} (intento {b.intento})",
                    b.modelo_efectivo or b.modelo_pedido,
                    f"{b.tokens_entrada if b.tokens_entrada is not None else '—'} / "
                    f"{b.tokens_salida if b.tokens_salida is not None else '—'}",
                    f"entrada {b.sha256_entrada}\nsalida {b.sha256_salida}",
                    b.error or "—",
                ]
                for b in c.bitacora
            ],
            [2.8, 2.6, 2.0, 6.0, 2.7],
            cabecera=["Nodo", "Modelo efectivo", "Tokens (ent./sal.)", "sha256", "Error"],
            tam=7,
        )
    if c.fallos:
        d.titulo("LLAMADAS FALLIDAS A LA IA")
        _tabla_fallos(d, c)
    return d.guardar(ruta)


def _modelos_usados(c: Any, cfg: Config, proveedor: str | None = None) -> list[str]:
    usados = list(
        dict.fromkeys(
            m
            for b in c.bitacora
            if proveedor in (None, b.proveedor)
            for m in (b.modelo_pedido, b.modelo_efectivo)
            if m
        )
    )
    return usados or ["ninguno"]


def _secciones_prosa(c: Any) -> list[tuple[str, str]]:
    secciones: list[tuple[str, str]] = []
    if c.apertura:
        a = c.apertura
        secciones.append(("Antecedentes", "\n\n".join([a.antecedentes_hechos, *(x.texto for x in a.contestaciones)])))
        secciones.append(("Sentencia impugnada", a.sentencia_impugnada))
        secciones.append(("Impugnación", a.impugnacion))
    if c.consideraciones:
        k = c.consideraciones
        secciones.append(("Consideraciones", "\n\n".join([k.procedibilidad, *(b.texto for b in k.bloques)])))
    if c.caso:
        k = c.caso
        secciones.append(("Caso concreto", "\n\n".join([k.problema_juridico, *(p.texto for p in k.parrafos), k.conclusion])))
    return secciones


def _citas_normativas(d: "_Docx", c: Any) -> None:
    d.parrafo(
        "La aplicación solo verifica las sentencias de la Corte Constitucional. Las normas siguientes, citadas "
        "en el texto redactado por la IA, NO se verifican automáticamente: compruebe a mano que el artículo y la "
        "norma existan y digan lo que el texto afirma.",
        alinear="i",
    )
    filas: dict[tuple, list] = {}
    for seccion, texto in _secciones_prosa(c):
        for cita in normas.extraer_normas(texto):
            fila = filas.setdefault((cita.articulo, cita.norma.lower()), [cita.texto, [], cita.contexto])
            if seccion not in fila[1]:
                fila[1].append(seccion)
    if not filas:
        d.parrafo("No se detectaron citas normativas en el texto generado.", alinear="i")
        return
    d.tabla(
        [[texto, ", ".join(secciones), contexto] for texto, secciones, contexto in filas.values()],
        [4.6, 3.0, 8.5],
        cabecera=["Norma citada", "Sección", "Contexto"],
        tam=8,
    )


def _tabla_fallos(d: "_Docx", c: Any) -> None:
    d.tabla(
        [
            [f["nodo"], f.get("fecha", ""), f.get("modelo_pedido", ""), f"{f.get('tipo_error', '')}: {f.get('error', '')}"]
            for f in c.fallos
        ],
        [2.6, 3.0, 3.0, 7.5],
        cabecera=["Nodo", "Fecha", "Modelo", "Error"],
        tam=7,
    )


def _version() -> str:
    try:
        return importlib_metadata.version("tutela2")
    except importlib_metadata.PackageNotFoundError:
        return "desconocida"


PROVEEDORES = {"anthropic": "Anthropic PBC", "jev": "TypeSafe AI"}
USO_IA = (
    "Redacción de antecedentes, síntesis de la sentencia impugnada y de la impugnación, "
    "marco doctrinal de las consideraciones y desarrollo del caso concreto"
)


def _proveedores_usados(c: Any, cfg: Config) -> list[str]:
    return list(dict.fromkeys(b.proveedor for b in c.bitacora)) or [cfg.llm.proveedor]


def _uso_ia(c: Any) -> str:
    nodos = {b.nodo for b in c.bitacora if b.proveedor == "jev"}
    fines = []
    if "roles" in nodos:
        fines.append("como segunda opinión sobre el rol de cada documento del expediente")
    if "metadatos" in nodos:
        fines.append("para verificar el sentido de la decisión de primera instancia y el rol del impugnante")
    if not fines:
        return USO_IA
    return (
        f"{USO_IA}. Además se consultó a {PROVEEDORES['jev']} (Jev), un modelo de decisión que no genera texto, "
        f"{' y '.join(fines)}; para ello se le enviaron fragmentos acotados de los documentos del expediente"
    )


def _anexo_prompts(d: "_Docx", c: Any, cfg: Config) -> None:
    d.titulo("ANEXO: PROMPTS E INSTRUCCIONES UTILIZADAS")
    d.parrafo(
        "Texto íntegro de las instrucciones del sistema de cada llamada y de las secciones de instrucción del "
        "mensaje enviado. Los documentos del expediente, que viajan en el mensaje, no se reproducen aquí; su "
        "huella sha256 consta en la bitácora.",
        alinear="i",
    )
    vistos: set[str] = set()
    for b in c.bitacora:
        d.parrafo(f"{b.nodo} (intento {b.intento}), prompt {b.prompt_id}", alinear="i", negrita=True, mantener=True, antes=8)
        if b.proveedor == "jev":
            d.parrafo(
                "Modelo de decisión que no genera texto: las preguntas cerradas enviadas constan por su huella sha256 en la bitácora.",
                alinear="i",
                tam=9,
            )
            continue
        if b.prompt_id in vistos:
            d.parrafo("Instrucciones del sistema: las mismas ya transcritas para este prompt.", alinear="i", tam=9)
        else:
            vistos.add(b.prompt_id)
            texto, _ = prompts.prompt_para(b.nodo, cfg)
            if hashlib.sha256(texto.encode("utf-8")).hexdigest() != b.sha256_instrucciones:
                d.parrafo(
                    "Advertencia: el texto vigente del prompt no coincide con la huella registrada; "
                    "no puede reproducirse el texto usado en esta llamada.",
                    alinear="i",
                    tam=9,
                )
            else:
                d.parrafo("Instrucciones del sistema:", alinear="i", cursiva=True, tam=9, mantener=True)
                for linea in filter(str.strip, texto.splitlines()):
                    d.parrafo(linea, alinear="i", tam=8)
        d.parrafo("Instrucciones del mensaje (sin documentos):", alinear="i", cursiva=True, tam=9, mantener=True)
        for linea in filter(str.strip, (b.instrucciones or "no se registraron").splitlines()):
            d.parrafo(linea, alinear="i", tam=8)


def _mapa_secciones(gen: str, hay_compulsa: bool) -> list[list[str]]:
    t = GEN[gen]
    filas = [
        [
            "Encabezado (despacho, fecha y cuadro de partes)",
            "plantilla + IA",
            "Datos extraídos de los documentos por código; vinculadas, derechos y género de las etiquetas, "
            "cuando la ingesta no los extrae, los redacta la IA",
        ],
        [
            "ASUNTO",
            "plantilla + IA",
            "Fórmula fija con cláusulas redactadas por la IA (impugnantes y resultado del fallo de primera instancia)",
        ],
        ["ANTECEDENTES DEL CASO", "IA", "Redactado a partir de los documentos del expediente"],
        [t["III"], "IA", "Redactado a partir del fallo de primera instancia"],
        [t["IV"], "IA", "Redactado a partir del escrito de impugnación"],
        [f"{t['V']}: competencia y transición", "plantilla", "Bloques fijos"],
        [f"{t['V']}: procedibilidad y bloques temáticos", "IA", "Marco doctrinal sin aplicación al caso"],
        [f"{t['V']}: referencias de jurisprudencia", "plantilla", "Magistrado ponente y fecha tomados del dataset oficial por código"],
        ["CASO CONCRETO", "IA", "Desarrolla la decisión y el eje fijados por el humano"],
    ]
    if hay_compulsa:
        filas.append(["OTRAS DETERMINACIONES", "plantilla", "Datos de la decisión humana"])
    filas.append(
        [
            "RESUELVE",
            "humano + plantilla + IA",
            "Sentido, órdenes y numerales decididos por el humano; redacción de plantilla con datos redactados por la "
            "IA (identificación y tratamiento del accionante, resultado del fallo de primera instancia y, si el "
            "humano no los fija, derechos invocados)",
        ]
    )
    return filas


def render_declaracion_ia(estado: dict, cfg: Config | dict, ruta: Path, hoy: date | None = None) -> Path:
    cfg = _como(Config, cfg)
    c = _leer(estado)
    d = _Docx(cfg, c.citas_por_id, "Declaración de uso de inteligencia artificial")
    d.parrafo(cfg.despacho.nombre, alinear="c", negrita=True)
    d.parrafo("DECLARACIÓN DE USO DE INTELIGENCIA ARTIFICIAL GENERATIVA", alinear="c", negrita=True)
    d.parrafo(f"Radicado: {_o(c.md.cui_2a or c.md.cui_1a, 'radicado')}", alinear="i")
    fecha = (c.decision.fecha_fallo if c.decision else None) or (hoy or date.today()).isoformat()
    d.parrafo(f"{cfg.despacho.ciudad}, {fecha_larga(fecha)}", alinear="i")

    d.titulo("FUNDAMENTO")
    d.parrafo(
        "En cumplimiento del artículo 10 del Acuerdo PCSJA24-12243 del 16 de diciembre de 2024, "
        "expedido por el Consejo Superior de la Judicatura, se informa el uso de un sistema de "
        "inteligencia artificial generativa como apoyo en la elaboración del proyecto de esta providencia."
    )

    d.titulo("HERRAMIENTA, PROVEEDOR Y MODELO")
    proveedores = _proveedores_usados(c, cfg)
    nombres = [PROVEEDORES.get(p, p) for p in proveedores]
    modelos = (
        ", ".join(_modelos_usados(c, cfg))
        if len(proveedores) == 1
        else "; ".join(f"{n}: {', '.join(_modelos_usados(c, cfg, p))}" for p, n in zip(proveedores, nombres))
    )
    d.tabla(
        [
            ["Herramienta", f"tutela2, versión {_version()}"],
            ["Uso", _uso_ia(c)],
            ["Empresa proveedora", "; ".join(nombres)],
            ["Modelos usados", modelos],
        ],
        [4.5, 11.6],
        etiquetas=True,
        tam=10,
    )
    if c.bitacora:
        d.parrafo("Llamadas realizadas:", alinear="i", negrita=True, mantener=True)
        d.tabla(
            [
                [
                    f"{b.nodo} (intento {b.intento})",
                    f"{b.proveedor} / {b.modelo_efectivo or b.modelo_pedido}" + (f"\nFalló: {b.error}" if b.error else ""),
                    b.fecha,
                    b.prompt_id,
                    b.sha256_instrucciones,
                ]
                for b in c.bitacora
            ],
            [2.4, 3.6, 2.8, 3.0, 4.3],
            cabecera=["Nodo", "Proveedor / modelo", "Fecha", "Prompt", "sha256 de las instrucciones"],
            tam=7,
        )
    else:
        d.parrafo("No se registraron llamadas a la IA.", alinear="i")
    if c.fallos:
        d.parrafo("Llamadas fallidas (no produjeron salida):", alinear="i", negrita=True, mantener=True)
        _tabla_fallos(d, c)

    d.titulo("ORIGEN DE CADA SECCIÓN")
    d.tabla(
        _mapa_secciones(cfg.plantilla_gen, bool(c.decision and c.decision.compulsa)),
        [5.6, 2.0, 8.5],
        cabecera=["Sección", "Origen", "Observación"],
        tam=9,
    )

    d.titulo("DECISIÓN HUMANA")
    if c.decision is None:
        d.parrafo("Aún no se ha registrado una decisión humana.", alinear="i")
    else:
        d.tabla(
            [
                ["Decidido por", c.decision.decidido_por.strip() or "no consta"],
                ["Fecha", str(c.decision_raw.get("fecha") or "no consta")],
                ["Sentido", decision_encabezado(c.decision)],
                ["Eje de la decisión", c.decision.eje.strip() or "no consta"],
                ["Borrador previo (sha256)", c.decision.previo_sha256 or "no consta"],
            ],
            [4.5, 11.6],
            etiquetas=True,
            tam=10,
        )

    if c.bitacora:
        _anexo_prompts(d, c, cfg)

    d.titulo("CONSTANCIA DEL SERVIDOR JUDICIAL")
    d.parrafo(
        "Pendiente de confirmación por el servidor judicial responsable: que leyó, entendió y aceptó "
        "los términos y condiciones de uso de la herramienta y que verificó el contenido producido "
        "antes de adoptar la decisión."
    )
    d.parrafo("______________________________", alinear="i", antes=24)
    d.parrafo(_o(cfg.despacho.juez, "nombre del juez"), alinear="i")
    return d.guardar(ruta)


def render_requerimiento(ing: Ingesta | dict, cfg: Config | dict, ruta: Path, hoy: date | None = None) -> Path:
    cfg = _como(Config, cfg)
    ing = _como(Ingesta, ing)
    md = ing.metadatos
    hoy = hoy or date.today()
    cui = _o(md.cui_1a or md.cui_2a, "radicado")
    d = _Docx(cfg, titulo="Requerimiento de documentos")
    d.parrafo(f"{cfg.despacho.ciudad}, {fecha_larga(hoy.isoformat())}", alinear="i")
    d.parrafo(f"Señores: {_o(md.juzgado_a_quo, 'juzgado a quo')}", alinear="i")
    d.parrafo(f"Asunto: solicitud de documentos faltantes en la acción de tutela {cui}", alinear="i", negrita=True)
    d.parrafo("Cordial saludo.", alinear="i")
    d.parrafo(
        f"De manera atenta, me dirijo a ustedes con relación a la acción de tutela con radicado "
        f"No. {cui}, en la que figura como accionante {_o(md.accionante, 'accionante')}, la cual fue "
        "asignada por reparto a este Despacho."
    )
    if ing.faltantes:
        d.parrafo(
            "Al realizar la verificación de los documentos enviados, se advierte que no se encuentran "
            "adjuntos los siguientes:"
        )
        for rol in ing.faltantes:
            d.item(ROLES_ES.get(rol, rol).capitalize())
        d.parrafo(
            "Por esta razón, solicito amablemente el reenvío del expediente completo, asegurándose de "
            "incluir los documentos faltantes, para poder dar continuidad al trámite de segunda instancia.",
            antes=8,
        )
    else:
        d.parrafo("No se identificaron documentos faltantes en el expediente recibido.")
    d.parrafo("Agradezco de antemano su pronta colaboración.")
    d.parrafo("Cordialmente,", alinear="i", antes=12)
    d.parrafo(cfg.despacho.nombre_cuerpo, alinear="i", negrita=True)
    if cfg.despacho.correo:
        d.parrafo(cfg.despacho.correo, alinear="i")
    return d.guardar(ruta)

