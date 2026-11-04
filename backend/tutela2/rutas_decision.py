from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from tutela2 import decision_vista
from tutela2.esquemas import DecisionVistaRespuesta
from tutela2.models import Metadatos

log = logging.getLogger("tutela2.rutas_decision")

MAX_CUERPO = 256 * 1024

router = APIRouter()


def _caso_dir(caso_id: str) -> Path:
    from tutela2 import server

    return server._dir_caso(caso_id)


def _constante_invalida(constante: str) -> None:
    raise ValueError(constante)


async def _cuerpo_decision(request: Request, _caso: Path = Depends(_caso_dir)) -> dict[str, Any]:
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > MAX_CUERPO:
        raise HTTPException(413, f"La decisión supera el tamaño permitido ({MAX_CUERPO // 1024} KB).")
    recibido = bytearray()
    async for trozo in request.stream():
        recibido += trozo
        if len(recibido) > MAX_CUERPO:
            raise HTTPException(413, f"La decisión supera el tamaño permitido ({MAX_CUERPO // 1024} KB).")
    try:
        valor = json.loads(bytes(recibido), parse_constant=_constante_invalida)
    except (ValueError, RecursionError):
        raise HTTPException(422, "El cuerpo debe ser un JSON válido.") from None
    if not isinstance(valor, dict):
        raise HTTPException(422, "La decisión debe ser un objeto JSON.")
    return valor


_CUERPO_OPENAPI = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "title": "DecisionParcial",
                "description": "Decisión parcial con los campos de la decisión; todos opcionales.",
                "additionalProperties": True,
            }
        }
    },
}


@router.post(
    "/api/casos/{caso_id}/decision/vista",
    response_model=DecisionVistaRespuesta,
    openapi_extra={"requestBody": _CUERPO_OPENAPI},
    responses={
        404: {"description": "Caso no encontrado."},
        413: {"description": "La decisión supera el tamaño permitido."},
        422: {"description": "El cuerpo no es un objeto JSON válido."},
    },
)
def vista_decision(
    caso_id: str,
    cuerpo: dict[str, Any] = Depends(_cuerpo_decision),
    caso_dir: Path = Depends(_caso_dir),
) -> dict[str, Any]:
    try:
        md = decision_vista.metadatos_del_caso(caso_dir)
    except Exception:
        log.exception("No se pudieron leer los metadatos de %s", caso_id)
        md = Metadatos()
    try:
        return decision_vista.decision_vista(cuerpo, md)
    except Exception:
        log.exception("Falló la vista del RESUELVE de %s", caso_id)
        return {"numerales": [], "faltantes": [], "errores": [decision_vista.ERROR_INTERNO]}
