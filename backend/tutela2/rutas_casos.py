from __future__ import annotations

import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from tutela2 import resumen_caso
from tutela2.esquemas import CasoCreado, CasoResumen

log = logging.getLogger("tutela2.rutas_casos")

router = APIRouter()


def _jobs_activos() -> dict[str, tuple[str, str]]:
    from tutela2 import server

    with server._LOCK:
        return {j["caso"]: (j["id"], j["cmd"]) for j in server.JOBS.values() if j["estado"] == "corriendo"}


@router.get("/api/casos", response_model=list[CasoResumen])
def listar_casos() -> list[dict[str, Any]]:
    from tutela2 import server

    raiz = server.casos_dir()
    if not raiz.is_dir():
        return []
    activos = _jobs_activos()
    return [_resumen_de(raiz / nombre, activos.get(nombre)) for nombre in resumen_caso.nombres_de_casos(raiz)]


def _resumen_de(caso_dir: Path, job: tuple[str, str] | None) -> dict[str, Any]:
    try:
        resumen = resumen_caso.leer(caso_dir, tolerar_obsoleto=job is not None)
        try:
            CasoResumen.model_validate(resumen)
        except ValidationError:
            log.warning("Resumen inválido en %s; se reconstruye", caso_dir.name)
            resumen = resumen_caso.actualizar(caso_dir)
    except Exception:
        log.exception("No se pudo leer el resumen de %s", caso_dir.name)
        resumen = resumen_caso.resumen_de_error(caso_dir)
    return resumen_caso.con_job(resumen, *job, caso_dir) if job else resumen


@router.get("/api/casos/{caso_id}/resumen", response_model=CasoResumen)
def resumen_del_caso(caso_id: str) -> dict[str, Any]:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    return _resumen_de(caso_dir, _jobs_activos().get(caso_id))


@router.post("/api/casos", response_model=CasoCreado)
def crear_caso(nombre: str | None = Form(None), files: list[UploadFile] = File(...)) -> dict[str, Any]:
    from tutela2 import formato_global, server

    try:
        rutas = [server.sanear_ruta(f.filename) for f in files]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    pares = [(f, r) for f, r in zip(files, rutas) if not any(p.startswith(".") for p in r)]
    if not pares:
        raise HTTPException(400, "No se recibió ningún archivo.")
    originales = [r for _, r in pares]
    rutas_finales = server.quitar_carpeta_raiz(originales)
    repetidas = sorted("/".join(r) for r, n in Counter(rutas_finales).items() if n > 1)
    if repetidas:
        raise HTTPException(400, f"Hay archivos con la misma ruta: {', '.join(repetidas)}.")
    raiz_comun = originales[0][0] if len(rutas_finales[0]) != len(originales[0]) else None
    nombre = (nombre or "").strip() or raiz_comun or "caso"

    caso_id, caso_dir = server._crear_dir_caso(nombre)
    insumos = (caso_dir / "insumos").resolve()
    try:
        for (f, _), ruta in zip(pares, rutas_finales):
            destino = insumos.joinpath(*ruta)
            if not destino.resolve().is_relative_to(insumos):
                raise HTTPException(400, f"Ruta no permitida: {'/'.join(ruta)}")
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                with destino.open("wb") as out:
                    shutil.copyfileobj(f.file, out)
            except (FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
                raise HTTPException(400, f"La ruta {'/'.join(ruta)} choca con otra: un nombre no puede ser archivo y carpeta a la vez.") from exc
        (caso_dir / resumen_caso.NOMBRE).write_text(nombre, encoding="utf-8")
        formato_global.copiar_a_caso(caso_dir)
    except BaseException:
        shutil.rmtree(caso_dir, ignore_errors=True)
        raise
    try:
        resumen_caso.actualizar(caso_dir)
    except Exception:
        log.warning("No se pudo escribir el resumen inicial de %s", caso_id, exc_info=True)
    log.info("Caso %s creado con %d archivos", caso_id, len(pares))
    return {"id": caso_id, "n_insumos": len(pares)}
