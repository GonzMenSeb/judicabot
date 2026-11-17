"""Lectura del expediente para el visor de evidencia: el texto de una página y el archivo original.

El texto sale de la ingesta (``caso.json``), páginas de ruido incluidas: los certificados de
existencia quedan marcados como ruido pero son evidencia de la cadena de un poder."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ParametroRuta
from fastapi.responses import FileResponse

from tutela2.esquemas_apoderados import PaginaExpediente
from tutela2.models import Doc, Ingesta

log = logging.getLogger("tutela2.rutas_expediente")

router = APIRouter()

PATRON_DOC_ID = r"^[12][a-z]-\d{3,4}$"
MAX_CACHE = 4
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SIN_ADIVINAR = {"X-Content-Type-Options": "nosniff"}

_cache: dict[Path, tuple[tuple[int, int], Ingesta]] = {}
_candado = threading.Lock()

DocId = Annotated[str, ParametroRuta(pattern=PATRON_DOC_ID, description="doc_id de la ingesta, p. ej. 1a-014")]


def ingesta(caso_dir: Path) -> Ingesta | None:
    """La ingesta del caso, en caché mientras ``caso.json`` no cambie."""
    caso_json = Path(caso_dir) / "caso.json"
    try:
        st = caso_json.stat()
    except FileNotFoundError:
        return None
    clave = (st.st_mtime_ns, st.st_size)
    with _candado:
        guardado = _cache.get(caso_json)
    if guardado is not None and guardado[0] == clave:
        return guardado[1]
    from tutela2 import server

    leida = server._api()._cargar_ingesta(Path(caso_dir))
    if leida is None:
        return None
    with _candado:
        _cache.pop(caso_json, None)
        _cache[caso_json] = (clave, leida)
        while len(_cache) > MAX_CACHE:
            _cache.pop(next(iter(_cache)))
    return leida


def _documento(caso_id: str, doc_id: str) -> tuple[Path, Doc]:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    try:
        ing = ingesta(caso_dir)
    except Exception:
        log.exception("No se pudo leer la ingesta de %s", caso_id)
        raise HTTPException(404, "Documento no encontrado.") from None
    doc = next((d for d in ing.documentos if d.doc_id == doc_id), None) if ing is not None else None
    if doc is None:
        raise HTTPException(404, "Documento no encontrado.")
    return caso_dir, doc


@router.get(
    "/api/casos/{caso_id}/expediente/{doc_id}/paginas/{n}",
    response_model=PaginaExpediente,
    responses={404: {"description": "Caso, documento o página inexistente."}},
)
def pagina_expediente(caso_id: str, doc_id: DocId, n: Annotated[int, ParametroRuta(ge=1)]) -> PaginaExpediente:
    _, doc = _documento(caso_id, doc_id)
    pagina = next((p for p in doc.paginas if p.n == n), None)
    if pagina is None:
        raise HTTPException(404, f"El documento {doc_id} no tiene página {n}.")
    return PaginaExpediente(
        doc_id=doc.doc_id,
        documento=doc.nombre,
        rol=doc.rol,
        pagina=pagina.n,
        total=len(doc.paginas),
        texto=pagina.texto,
        ocr=pagina.ocr,
        es_pdf=doc.ruta.lower().endswith(".pdf"),
    )


@router.get(
    "/api/casos/{caso_id}/expediente/{doc_id}/archivo",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}, "text/plain": {}, "application/octet-stream": {}}},
        404: {"description": "Caso o documento inexistente, o archivo fuera de insumos/."},
    },
)
def archivo_expediente(caso_id: str, doc_id: DocId) -> FileResponse:
    caso_dir, doc = _documento(caso_id, doc_id)
    insumos = (caso_dir / "insumos").resolve()
    try:
        ruta = (insumos / doc.ruta).resolve()
        valida = ruta.is_relative_to(insumos) and ruta.is_file()
    except (OSError, ValueError, RuntimeError):
        valida = False
    if not valida:
        raise HTTPException(404, "Archivo no encontrado.")
    sufijo = ruta.suffix.lower()
    if sufijo == ".pdf":
        return FileResponse(
            ruta, media_type="application/pdf", filename=ruta.name, content_disposition_type="inline", headers=_SIN_ADIVINAR
        )
    if sufijo == ".txt":
        return FileResponse(
            ruta,
            media_type="text/plain; charset=utf-8",
            filename=ruta.name,
            content_disposition_type="inline",
            headers=_SIN_ADIVINAR,
        )
    return FileResponse(
        ruta, media_type=DOCX if sufijo == ".docx" else "application/octet-stream", filename=ruta.name, headers=_SIN_ADIVINAR
    )
