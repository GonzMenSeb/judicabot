from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from tutela2 import config as cfgmod
from tutela2.config import Config, Despacho

log = logging.getLogger("tutela2.formato_global")

ARCHIVO = ".formato.json"


class CampoFormato(BaseModel):
    clave: str
    etiqueta: str
    ayuda: str
    tipo: Literal["texto", "texto_largo", "lista"]
    grupo: str
    documentos: list[str]


class DocumentoFormato(BaseModel):
    id: str
    nombre: str


DOCUMENTOS: tuple[DocumentoFormato, ...] = (
    DocumentoFormato(id="fallo", nombre="Fallo de segunda instancia"),
    DocumentoFormato(id="auto", nombre="Auto que asume conocimiento"),
    DocumentoFormato(id="oficio", nombre="Oficio a la Corte Constitucional"),
    DocumentoFormato(id="correos", nombre="Borradores de correo"),
    DocumentoFormato(id="formato", nombre="Formato de calidad"),
    DocumentoFormato(id="informe", nombre="Informe de verificación"),
    DocumentoFormato(id="declaracion_ia", nombre="Declaración de uso de inteligencia artificial"),
    DocumentoFormato(id="requerimiento", nombre="Requerimiento de documentos faltantes"),
)


def _campo(clave: str, etiqueta: str, ayuda: str, tipo: str, grupo: str, *documentos: str) -> CampoFormato:
    return CampoFormato(clave=clave, etiqueta=etiqueta, ayuda=ayuda, tipo=tipo, grupo=grupo, documentos=list(documentos))


CATALOGO: tuple[CampoFormato, ...] = (
    _campo(
        "nombre",
        "Nombre del despacho (encabezado del fallo)",
        "Título que encabeza el fallo, el informe de verificación y la declaración de uso de IA, con la ciudad si así "
        "se firma. En el fallo con la plantilla B sale siempre en mayúsculas.",
        "texto_largo", "Despacho", "fallo", "informe", "declaracion_ia",
    ),
    _campo(
        "nombre_corto",
        "Nombre del despacho sin la ciudad",
        "Título del auto que asume conocimiento y del oficio a la Corte Constitucional. Escríbalo sin la ciudad: "
        "esta se toma del campo «Ciudad» y se imprime en la línea de la fecha.",
        "texto_largo", "Despacho", "auto", "oficio",
    ),
    _campo(
        "nombre_cuerpo",
        "Nombre del despacho dentro del texto",
        "Aparece en la frase «En mérito de lo expuesto, el …» de la parte resolutiva del fallo, en la firma del "
        "requerimiento de documentos y como autor de los archivos de Word del fallo, el borrador y los documentos "
        "internos (informe, declaración de uso de IA y requerimiento).",
        "texto_largo", "Despacho", "fallo", "requerimiento",
    ),
    _campo(
        "ciudad",
        "Ciudad",
        "Va antes de la fecha en el fallo, en el auto, en el oficio, en la declaración de uso de IA y en el "
        "requerimiento (por ejemplo, «Medellín, tres (03) de noviembre de dos mil veintiséis (2026)»). En el formato "
        "de calidad las casillas «Distrito» y «Municipio» dicen siempre «MEDELLÍN», y al nombre del juzgado de "
        "primera instancia se le quita siempre el sufijo « DE MEDELLÍN»: ese texto del documento es fijo y no cambia "
        "con este campo.",
        "texto", "Despacho", "fallo", "auto", "oficio", "declaracion_ia", "requerimiento",
    ),
    _campo(
        "juez",
        "Nombre del juez",
        "Firma del fallo, del auto y de la declaración de uso de IA. También se usa como evaluador en el formato de "
        "calidad y en el correo de remisión de compulsa de copias.",
        "texto", "Firmas", "fallo", "auto", "correos", "formato", "declaracion_ia",
    ),
    _campo(
        "cargo_juez",
        "Cargo del juez",
        "Se imprime debajo del nombre del juez en el fallo y en el auto.",
        "texto", "Firmas", "fallo", "auto",
    ),
    _campo(
        "escribiente",
        "Nombre del escribiente",
        "Firma la constancia del auto y cierra los borradores de correo.",
        "texto", "Firmas", "auto", "correos",
    ),
    _campo(
        "cargo_escribiente",
        "Cargo del escribiente",
        "Se imprime debajo del nombre del escribiente en el auto y en los borradores de correo.",
        "texto", "Firmas", "auto", "correos",
    ),
    _campo(
        "firmante_oficio",
        "Nombre de quien firma el oficio",
        "Firma del oficio con el que se remite el expediente a la Corte Constitucional.",
        "texto", "Firmas", "oficio",
    ),
    _campo(
        "cargo_firmante_oficio",
        "Cargo de quien firma el oficio",
        "Se imprime debajo del nombre de quien firma el oficio.",
        "texto", "Firmas", "oficio",
    ),
    _campo(
        "cargo_evaluador",
        "Cargo del evaluador",
        "Cargo que se escribe junto al nombre del juez en el formato de calidad.",
        "texto", "Firmas", "formato",
    ),
    _campo(
        "correo",
        "Correo electrónico del despacho",
        "Va en la firma de los borradores de correo y bajo el nombre del despacho en el requerimiento de documentos. "
        "En el borrador de la remisión de compulsa de copias, la dirección de destino (la oficina de reparto, "
        "ofjudmed@cendoj.ramajudicial.gov.co) es texto fijo del documento y no cambia con este campo.",
        "texto", "Contacto", "correos", "requerimiento",
    ),
    _campo(
        "telefono_correo",
        "Teléfono en la firma de los correos",
        "Va al final de la firma de los borradores de correo.",
        "texto", "Contacto", "correos",
    ),
    _campo(
        "firma_correo",
        "Líneas del juzgado en la firma de los correos",
        "Una línea por renglón. Van entre el cargo del escribiente y el correo del despacho.",
        "lista", "Contacto", "correos",
    ),
    _campo(
        "cierre_fallo",
        "Fórmula de cierre del fallo",
        "Línea centrada que va antes de la firma del juez (por ejemplo, «NOTIFÍQUESE Y CÚMPLASE»).",
        "texto", "Cierres y pies de página", "fallo",
    ),
    _campo(
        "cierre_auto",
        "Fórmula de cierre del auto",
        "Línea centrada que va antes de la firma del juez en el auto.",
        "texto", "Cierres y pies de página", "auto",
    ),
    _campo(
        "pie",
        "Pie de página del fallo (plantilla A)",
        "Una sola línea al pie de cada página del fallo con la plantilla A; la plantilla B usa las líneas de «Pie de "
        "página del fallo (plantilla B)». También es el pie de los documentos internos (informe de verificación, "
        "declaración de uso de IA y requerimiento).",
        "texto_largo", "Cierres y pies de página", "fallo", "informe", "declaracion_ia", "requerimiento",
    ),
    _campo(
        "pie_fallo",
        "Pie de página del fallo (plantilla B)",
        "Una línea por renglón. Solo se usa con la plantilla B.",
        "lista", "Cierres y pies de página", "fallo",
    ),
    _campo(
        "pie_auto",
        "Pie de página del auto",
        "Una línea por renglón al pie del auto que asume conocimiento.",
        "lista", "Cierres y pies de página", "auto",
    ),
)


def archivo_formato() -> Path:
    from tutela2.server import casos_dir

    return casos_dir() / ARCHIVO


def leer_formato() -> tuple[Despacho, str] | None:
    ruta = archivo_formato()
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        despacho = Despacho.model_validate(datos["valores"])
        plantilla = datos["plantilla_gen"]
        if plantilla not in ("A", "B"):
            raise ValueError(f"plantilla_gen inválida: {plantilla!r}")
    except (OSError, ValueError, KeyError, TypeError, ValidationError):
        log.warning("%s no es válido; se ignora.", ruta, exc_info=True)
        return None
    return despacho, plantilla


def vigente() -> tuple[Despacho, str]:
    return leer_formato() or (Despacho(), Config().plantilla_gen)


def guardar_formato(despacho: Despacho, plantilla_gen: str) -> None:
    ruta = archivo_formato()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(
        {"valores": despacho.model_dump(), "plantilla_gen": plantilla_gen}, ensure_ascii=False, indent=2
    )
    fd, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=".formato-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def copiar_a_caso(caso_dir: Path) -> None:
    formato = leer_formato()
    if formato is None:
        return
    despacho, plantilla = formato
    cfg = cfgmod.cargar(caso_dir, entorno=False)
    cfg.despacho = despacho
    cfg.plantilla_gen = plantilla
    cfgmod.guardar(caso_dir, cfg)
