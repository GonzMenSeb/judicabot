from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from tutela2 import salidas, vista

router = APIRouter()

RELATIVAS = {
    "borrador": f"trabajo/{vista.ARCHIVOS['borrador']}",
    "fallo": "/".join([*salidas.PRINCIPAL, vista.ARCHIVOS["fallo"]]),
}
NOMBRES = {"borrador": "El borrador", "fallo": "El fallo"}
MAX_CACHE = 64
_cache: dict[Path, tuple[tuple[int, int], bytes]] = {}
_candado = threading.Lock()


def _hay_docx(caso_dir: Path, tipo: str) -> bool:
    if tipo == "borrador":
        return (salidas.trabajo(caso_dir) / "previo.docx").is_file()
    carpeta = salidas.principal(caso_dir)
    return carpeta.is_dir() and any(carpeta.glob("*FalloSegunda*.docx"))


def _leer(ruta: Path) -> bytes:
    st = ruta.stat()
    clave = (st.st_mtime_ns, st.st_size)
    with _candado:
        guardado = _cache.get(ruta)
    if guardado is not None and guardado[0] == clave:
        return guardado[1]
    contenido = ruta.read_bytes()
    with _candado:
        _cache.pop(ruta, None)
        _cache[ruta] = (clave, contenido)
        while len(_cache) > MAX_CACHE:
            _cache.pop(next(iter(_cache)))
    return contenido


@router.get("/api/casos/{caso_id}/vista/{tipo}", response_model=vista.Vista)
def obtener_vista(caso_id: str, tipo: Literal["borrador", "fallo"]) -> Response:
    from tutela2.server import _dir_caso

    caso_dir = _dir_caso(caso_id)
    try:
        ruta = salidas.resolver(caso_dir, RELATIVAS[tipo])
        contenido = _leer(ruta)
    except FileNotFoundError as exc:
        if _hay_docx(caso_dir, tipo):
            raise HTTPException(
                404, f"{NOMBRES[tipo]} existe, pero no tiene vista previa: se generó antes de esta versión. Vuelva a generarlo."
            ) from exc
        raise HTTPException(404, f"{NOMBRES[tipo]} aún no existe.") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(404, "Vista no encontrada.") from exc
    return Response(contenido, media_type="application/json")
