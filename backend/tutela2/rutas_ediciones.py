from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from tutela2 import ediciones
from tutela2.esquemas import EdicionCuerpo, EdicionesRespuesta, ResolverCuerpo

log = logging.getLogger("tutela2.rutas_ediciones")

router = APIRouter()

MOTIVO_JOB = "Hay una redacción en curso para este caso."

_RESPUESTAS: dict[int | str, dict[str, Any]] = {
    404: {"description": "Caso o pieza no encontrados."},
    409: {
        "description": "Hay una ejecución en curso, el caso no espera la decisión, la pieza tiene un conflicto o el párrafo cambió."
    },
    422: {"description": "La edición no es válida: el detalle es el motivo en español."},
}


def _caso_dir(caso_id: str, pieza: str | None = None) -> Path:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    if pieza is not None and not ediciones.es_pieza(pieza):
        raise HTTPException(404, f"No existe la pieza {pieza}.")
    return caso_dir


def _job_corriendo(caso_id: str) -> bool:
    from tutela2 import server

    return any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in server.JOBS.values())


def _correr(caso_id: str, fn: Callable[[Any], dict[str, Any]], fallo: str) -> dict[str, Any]:
    from tutela2 import server

    with server._LOCK:
        if _job_corriendo(caso_id):
            raise HTTPException(409, MOTIVO_JOB)
        try:
            return dict(fn(server._api()))
        except ediciones.ErrorEdicion as exc:
            raise HTTPException(exc.estado, exc.mensaje) from exc
        except Exception as exc:
            log.exception("%s de %s", fallo, caso_id)
            raise HTTPException(500, f"{fallo}: {exc}") from exc


@router.get("/api/casos/{caso_id}/ediciones", response_model=EdicionesRespuesta, responses={404: _RESPUESTAS[404]})
def leer_ediciones(caso_id: str) -> dict[str, Any]:
    from tutela2 import server

    caso_dir = _caso_dir(caso_id)
    with server._LOCK:
        if _job_corriendo(caso_id):
            return ediciones.respuesta({}, {}, editable=False, motivo=MOTIVO_JOB)
        try:
            return dict(server._api().ediciones(caso_dir))
        except Exception as exc:
            log.exception("No se pudieron leer las ediciones de %s", caso_id)
            raise HTTPException(500, f"No se pudieron leer las ediciones: {exc}") from exc


@router.put("/api/casos/{caso_id}/ediciones/{pieza}", response_model=EdicionesRespuesta, responses=_RESPUESTAS)
def editar_pieza(caso_id: str, pieza: str, cuerpo: EdicionCuerpo) -> dict[str, Any]:
    caso_dir = _caso_dir(caso_id, pieza)
    return _correr(
        caso_id,
        lambda api: api.editar_pieza(caso_dir, pieza, cuerpo.parrafo, cuerpo.original, cuerpo.texto),
        "No se pudo guardar la edición",
    )


@router.delete("/api/casos/{caso_id}/ediciones/{pieza}", response_model=EdicionesRespuesta, responses=_RESPUESTAS)
def restaurar_pieza(caso_id: str, pieza: str) -> dict[str, Any]:
    caso_dir = _caso_dir(caso_id, pieza)
    return _correr(caso_id, lambda api: api.restaurar_pieza(caso_dir, pieza), "No se pudo restaurar la pieza")


@router.post("/api/casos/{caso_id}/ediciones/{pieza}/resolver", response_model=EdicionesRespuesta, responses=_RESPUESTAS)
def resolver_pieza(caso_id: str, pieza: str, cuerpo: ResolverCuerpo) -> dict[str, Any]:
    caso_dir = _caso_dir(caso_id, pieza)
    return _correr(
        caso_id,
        lambda api: api.resolver_pieza(caso_dir, pieza, list(cuerpo.elecciones)),
        "No se pudo resolver el conflicto",
    )
