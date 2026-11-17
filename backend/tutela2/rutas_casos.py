from __future__ import annotations

import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from tutela2 import papelera, resumen_caso, termino, vigencia
from tutela2.esquemas import CasoCreado, CasoEliminado, CasoResumen, CasoRestaurado, Termino, TerminoRespuesta

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


def _crear_carpetas(base: Path, partes: tuple[str, ...]) -> None:
    # Sin parents=True: si el caso se eliminó durante la subida, falla en vez de recrear su carpeta.
    for i in range(1, len(partes) + 1):
        base.joinpath(*partes[:i]).mkdir(exist_ok=True)


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
                _crear_carpetas(insumos.parent, ("insumos", *ruta[:-1]))
                with destino.open("wb") as out:
                    shutil.copyfileobj(f.file, out)
            except FileNotFoundError as exc:
                raise HTTPException(404, "Caso no encontrado.") from exc
            except (FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
                raise HTTPException(400, f"La ruta {'/'.join(ruta)} choca con otra: un nombre no puede ser archivo y carpeta a la vez.") from exc
        try:
            (caso_dir / resumen_caso.NOMBRE).write_text(nombre, encoding="utf-8")
            formato_global.copiar_a_caso(caso_dir)
            termino.crear(caso_dir)
        except FileNotFoundError as exc:
            if caso_dir.is_dir():
                raise
            raise HTTPException(404, "Caso no encontrado.") from exc
    except BaseException:
        shutil.rmtree(caso_dir, ignore_errors=True)
        raise
    try:
        resumen_caso.actualizar(caso_dir)
    except Exception:
        log.warning("No se pudo escribir el resumen inicial de %s", caso_id, exc_info=True)
    log.info("Caso %s creado con %d archivos", caso_id, len(pares))
    return {"id": caso_id, "n_insumos": len(pares)}


def _caso_dir(caso_id: str) -> Path:
    from tutela2 import server

    return server._dir_caso(caso_id)


def _respuesta_termino(caso_dir: Path) -> dict[str, Any]:
    return termino.describir(caso_dir, resumen_caso._leer_estado(caso_dir))


@router.get("/api/casos/{caso_id}/termino", response_model=TerminoRespuesta)
def leer_termino(caso_dir: Path = Depends(_caso_dir)) -> dict[str, Any]:
    return _respuesta_termino(caso_dir)


@router.put("/api/casos/{caso_id}/termino", response_model=TerminoRespuesta)
def fijar_termino(cuerpo: Termino, caso_dir: Path = Depends(_caso_dir)) -> dict[str, Any]:
    try:
        termino.guardar_termino(caso_dir, cuerpo)
    except OSError as exc:
        log.exception("No se pudo guardar el término de %s", caso_dir.name)
        raise HTTPException(500, f"No se pudo guardar el término: {exc}") from exc
    try:
        resumen_caso.actualizar(caso_dir)
    except Exception:
        log.warning("No se pudo actualizar el resumen de %s", caso_dir.name, exc_info=True)
    return _respuesta_termino(caso_dir)


def _purgar_papelera(raiz: Path) -> None:
    try:
        papelera.purgar(raiz)
    except Exception:
        log.warning("No se pudo purgar la papelera", exc_info=True)


@router.delete(
    "/api/casos/{caso_id}",
    response_model=CasoEliminado,
    responses={404: {"description": "Caso no encontrado."}, 409: {"description": "Hay una ejecución en curso para este caso."}},
)
def eliminar_caso(caso_id: str) -> dict[str, Any]:
    from tutela2 import server

    server._dir_caso(caso_id)
    raiz = server.casos_dir().resolve()
    with server._LOCK:
        if any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in server.JOBS.values()):
            raise HTTPException(409, "Hay una ejecución en curso para este caso. Espere a que termine para eliminarlo.")
        if not (raiz / caso_id).is_dir():
            raise HTTPException(404, "Caso no encontrado.")
        entrada = papelera.mover(raiz, caso_id)
    # Las consultas de vigencia que esperaba el caso ya no le sirven a nadie: no se envían.
    vigencia.COLA.retirar(raiz / caso_id)
    log.info("Caso %s enviado a la papelera como %s", caso_id, entrada)
    _purgar_papelera(raiz)
    return {"id": caso_id, "papelera": entrada}


@router.post(
    "/api/papelera/{entrada}/restaurar",
    response_model=CasoRestaurado,
    responses={404: {"description": "No se encontró el caso en la papelera."}, 409: {"description": "Ya hay otro caso con ese identificador."}},
)
def restaurar_caso(entrada: str) -> dict[str, Any]:
    from tutela2 import server

    raiz = server.casos_dir().resolve()
    with server._LOCK:
        encontrada = papelera.entrada_existente(raiz, entrada)
        if encontrada is None:
            raise HTTPException(404, "No se encontró el caso en la papelera.")
        caso_id, origen = encontrada
        destino = raiz / caso_id
        if destino.exists() or destino.is_symlink():
            raise HTTPException(409, "Ya hay otro caso con ese identificador.")
        origen.rename(destino)
    log.info("Caso %s restaurado desde la papelera (%s)", caso_id, entrada)
    return {"id": caso_id}
