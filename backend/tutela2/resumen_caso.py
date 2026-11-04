"""Resumen cacheado por caso para GET /api/casos.

Fuente: una sola llamada a api.estado por reconstrucción. El resultado se guarda en
<caso>/.resumen.json junto con la firma (st_mtime_ns) de caso.json, hilo.sqlite, hilo.sqlite-wal,
decision.json, config.json, salidas/ e insumos/. Si la firma coincide se lee el JSON sin abrir el grafo.

estado: el de api.estado (sin_iniciar, incompleto, revision, esperando_decision, terminado, error),
o "corriendo" cuando el caso tiene un job activo (se aplica al listar con con_job; no se cachea).

etapa (0-4), a partir de estado:
  sin_iniciar, incompleto, revision -> 0 (documentos)
  esperando_decision                -> 2 (decisión; el borrador ya está listo)
  terminado                         -> 4 (fallo listo)
  error con valores del grafo       -> 3 si la última decisión registrada es accion "decidir"
                                       (falló la redacción final), si no 1 (falló apertura o consideraciones)
  error sin valores del grafo       -> 0 (caso ilegible o corrupto)
  corriendo (según cmd del job)     -> nuevo 0; iniciar 1; continuar la etapa cacheada;
                                       decidir 1 si decision.json trae accion rehacer_*, si no 3

siguiente_paso: texto fijo por estado (SIGUIENTE_PASO).

n_alertas: len(alertas) si es lista (ingesta) o la suma de los largos si es dict (grafo).
radicado: cui_2a o, si falta, cui_1a de los metadatos. nombre: contenido de <caso>/.nombre o, si no
existe, el id. actualizado: la mayor mtime de los archivos de la firma, en ISO 8601 UTC.
"""

from __future__ import annotations

import functools
import importlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("tutela2.resumen_caso")

ARCHIVO = ".resumen.json"
NOMBRE = ".nombre"
VERSION = 1
RASTREADOS = ("caso.json", "hilo.sqlite", "hilo.sqlite-wal", "decision.json", "config.json", "salidas", "insumos")

ESTADOS = ("sin_iniciar", "revision", "incompleto", "esperando_decision", "terminado", "error")
SIGUIENTE_PASO = {
    "sin_iniciar": "Procesar los documentos",
    "incompleto": "Completar los documentos",
    "revision": "Revisar los documentos",
    "esperando_decision": "Revisar el borrador y decidir",
    "terminado": "Ver el fallo",
    "error": "Revisar el error",
    "corriendo": "Ver el avance",
}
SIGUIENTE_PASO_REANUDAR = "Continuar la ejecución"
ETAPA_POR_ESTADO = {"sin_iniciar": 0, "incompleto": 0, "revision": 0, "esperando_decision": 2, "terminado": 4}
CLAVES = frozenset(
    {
        "nombre", "radicado", "accionante", "accionadas", "juzgado_a_quo", "estado", "etapa",
        "siguiente_paso", "n_alertas", "n_insumos", "actualizado",
    }
)


def firma(caso_dir: Path) -> list[int | None]:
    base = os.fspath(caso_dir)
    resultado: list[int | None] = []
    for nombre in RASTREADOS:
        try:
            resultado.append(os.stat(os.path.join(base, nombre)).st_mtime_ns)
        except OSError:
            resultado.append(None)
    return resultado


def _contar_insumos(caso_dir: Path) -> int:
    insumos = caso_dir / "insumos"
    return sum(1 for f in insumos.rglob("*") if f.is_file()) if insumos.is_dir() else 0


def _nombre(caso_dir: Path) -> str:
    try:
        texto = (caso_dir / NOMBRE).read_text(encoding="utf-8").strip()
    except OSError:
        texto = ""
    return texto or caso_dir.name


def _n_alertas(alertas: Any) -> int:
    if isinstance(alertas, dict):
        return sum(len(v) for v in alertas.values() if isinstance(v, (list, tuple)))
    if isinstance(alertas, (list, tuple)):
        return len(alertas)
    return 0


def _actualizado(sig: list[int | None], caso_dir: Path) -> str:
    validas = [n for n in sig if n is not None]
    try:
        ns = max(validas) if validas else caso_dir.stat().st_mtime_ns
    except OSError:
        ns = 0
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat(timespec="seconds")


def campos_desde_estado(respuesta: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(respuesta, dict):
        respuesta = {"estado": "error", "resumen": {}}
    estado = respuesta.get("estado")
    if estado not in ESTADOS:
        estado = "error"
    resumen = respuesta.get("resumen") or {}
    meta = resumen.get("metadatos") or {}
    if estado == "error":
        if resumen:
            decision = resumen.get("decision") or {}
            etapa = 3 if decision.get("accion") == "decidir" else 1
            siguiente = SIGUIENTE_PASO_REANUDAR
        else:
            etapa, siguiente = 0, SIGUIENTE_PASO["error"]
    else:
        etapa, siguiente = ETAPA_POR_ESTADO[estado], SIGUIENTE_PASO[estado]
    return {
        "radicado": meta.get("cui_2a") or meta.get("cui_1a") or None,
        "accionante": meta.get("accionante") or None,
        "accionadas": [a for a in (meta.get("accionadas") or []) if isinstance(a, str)],
        "juzgado_a_quo": meta.get("juzgado_a_quo") or None,
        "estado": estado,
        "etapa": etapa,
        "siguiente_paso": siguiente,
        "n_alertas": _n_alertas(resumen.get("alertas")),
    }


def _leer_estado(caso_dir: Path) -> dict[str, Any] | None:
    try:
        return importlib.import_module("tutela2.api").estado(caso_dir)
    except Exception:
        log.warning("No se pudo leer el estado de %s", caso_dir.name, exc_info=True)
        return None


def construir(caso_dir: Path) -> tuple[list[int | None], dict[str, Any]]:
    sig = firma(caso_dir)
    datos = {
        "nombre": _nombre(caso_dir),
        **campos_desde_estado(_leer_estado(caso_dir)),
        "n_insumos": _contar_insumos(caso_dir),
        "actualizado": _actualizado(sig, caso_dir),
    }
    return sig, datos


def _leer_cache(caso_dir: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((caso_dir / ARCHIVO).read_text(encoding="utf-8"))
        valido = doc["v"] == VERSION and isinstance(doc["firma"], list) and set(doc["datos"]) == CLAVES
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return doc if valido else None


def _escribir(caso_dir: Path, documento: dict[str, Any]) -> None:
    tmp = caso_dir / f".resumen.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(json.dumps(documento, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, caso_dir / ARCHIVO)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _completo(caso_dir: Path, datos: dict[str, Any]) -> dict[str, Any]:
    return {"id": caso_dir.name, **datos, "job_activo": None}


def actualizar(caso_dir: Path) -> dict[str, Any]:
    caso_dir = Path(caso_dir)
    sig, datos = construir(caso_dir)
    try:
        _escribir(caso_dir, {"v": VERSION, "firma": sig, "datos": datos})
    except OSError:
        log.warning("No se pudo guardar %s de %s", ARCHIVO, caso_dir.name, exc_info=True)
    return _completo(caso_dir, datos)


def leer(caso_dir: Path, tolerar_obsoleto: bool = False) -> dict[str, Any]:
    caso_dir = Path(caso_dir)
    cache = _leer_cache(caso_dir)
    if cache is not None and (tolerar_obsoleto or cache["firma"] == firma(caso_dir)):
        return _completo(caso_dir, cache["datos"])
    return actualizar(caso_dir)


def _etapa_corriendo(cmd: str, etapa_cache: int, caso_dir: Path) -> int:
    if cmd == "nuevo":
        return 0
    if cmd == "iniciar":
        return 1
    if cmd == "decidir":
        try:
            accion = json.loads((caso_dir / "decision.json").read_text(encoding="utf-8")).get("accion")
        except (OSError, ValueError, AttributeError):
            accion = None
        return 1 if isinstance(accion, str) and accion.startswith("rehacer") else 3
    return etapa_cache


def con_job(resumen: dict[str, Any], job_id: str, cmd: str, caso_dir: Path) -> dict[str, Any]:
    return {
        **resumen,
        "estado": "corriendo",
        "etapa": _etapa_corriendo(cmd, resumen["etapa"], Path(caso_dir)),
        "siguiente_paso": SIGUIENTE_PASO["corriendo"],
        "job_activo": job_id,
    }


def resumen_de_error(caso_dir: Path) -> dict[str, Any]:
    caso_dir = Path(caso_dir)
    return _completo(
        caso_dir,
        {
            "nombre": caso_dir.name,
            **campos_desde_estado(None),
            "n_insumos": 0,
            "actualizado": _actualizado([], caso_dir),
        },
    )


def nombres_de_casos(raiz: Path) -> list[str]:
    with os.scandir(raiz) as entradas:
        return sorted(e.name for e in entradas if not e.name.startswith(".") and e.is_dir())


def calentar(raiz: Path) -> None:
    raiz = Path(raiz)
    if not raiz.is_dir():
        return
    for nombre in nombres_de_casos(raiz):
        try:
            leer(raiz / nombre)
        except Exception:
            log.warning("No se pudo calentar el resumen de %s", nombre, exc_info=True)


def tras_transicion(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def envoltura(caso_dir: str | Path, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(caso_dir, *args, **kwargs)
        finally:
            destino = Path(caso_dir).resolve()
            if destino.is_dir():
                try:
                    actualizar(destino)
                except Exception:
                    log.warning("No se pudo actualizar el resumen de %s", destino.name, exc_info=True)

    return envoltura
