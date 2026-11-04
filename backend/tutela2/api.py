from __future__ import annotations

import ast
import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, get_args

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from tutela2 import config as cfgmod
from tutela2 import expediente, fallos, graph, ingest, llm, prompts, render, resumen_caso, salidas
from tutela2.config import Config
from tutela2.models import DatosAuto, Ingesta, Rol

log = logging.getLogger("tutela2")


def config_default() -> dict:
    return Config().model_dump()


def prompts_default() -> dict[str, str]:
    return prompts.prompts_default()


def _respuesta(
    estado: str,
    caso_dir: Path,
    *,
    ok: bool = True,
    payload: dict | None = None,
    resumen: dict | None = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": ok,
        "estado": estado,
        "payload": payload,
        "salidas": salidas.listar(caso_dir),
        "resumen": resumen or {},
        "error": error,
    }


def _doc_resumen(ing: Ingesta, d: Any) -> dict:
    return {
        "doc_id": d.doc_id,
        "ruta": d.ruta,
        "nombre": d.nombre,
        "rol": d.rol,
        "rol_origen": d.rol_origen,
        "evidencia": d.evidencia,
        "paginas": len(d.paginas),
        "paginas_sin_texto": sum(1 for p in d.paginas if p.sin_texto),
        "ruido": d.ruido,
        "ajeno": d.doc_id in ing.docs_ajenos,
        "jev_rol": d.jev_rol,
        "jev_confianza": d.jev_confianza,
        "jev_umbral": d.jev_umbral,
    }


def _resumen_ingesta(caso_dir: Path, ing: Ingesta) -> dict:
    return {
        "n_documentos": len(ing.documentos),
        "documentos": [_doc_resumen(ing, d) for d in ing.documentos],
        "faltantes": ing.faltantes,
        "esperados_faltantes": ing.esperados_faltantes,
        "alertas": ing.alertas,
        "docs_ajenos": ing.docs_ajenos,
        "metadatos": ing.metadatos.model_dump(mode="json"),
        "auto": expediente.auto_efectivo(caso_dir, ing.metadatos).model_dump(mode="json"),
    }


def _resumen(valores: dict) -> dict:
    decisiones = valores.get("decisiones") or []
    return {
        "metadatos": valores.get("metadatos"),
        "jev_metadatos": valores.get("jev_metadatos"),
        "apertura": valores.get("apertura"),
        "consideraciones": valores.get("consideraciones"),
        "citas": valores.get("citas") or [],
        "caso_concreto": valores.get("caso"),
        "decision": decisiones[-1] if decisiones else None,
        "alertas": valores.get("alertas") or {},
        "errores": valores.get("errores") or [],
        "bitacora": valores.get("bitacora") or [],
        "salidas": valores.get("salidas") or {},
    }


def _borrar_hilo(caso_dir: Path) -> None:
    for sufijo in ("", "-wal", "-shm"):
        (caso_dir / f"hilo.sqlite{sufijo}").unlink(missing_ok=True)
    (caso_dir / "decision.json").unlink(missing_ok=True)
    (caso_dir / fallos.ARCHIVO).unlink(missing_ok=True)


@contextmanager
def _grafo(caso_dir: Path, cfg: Config, cliente: Any = None) -> Iterator[tuple[Any, dict]]:
    conexion = sqlite3.connect(caso_dir / "hilo.sqlite", check_same_thread=False)
    try:
        yield graph.construir(cfg, cliente, SqliteSaver(conexion)), {"configurable": {"thread_id": caso_dir.name}}
    finally:
        conexion.close()


def _mensaje_error(error: Any) -> str:
    if isinstance(error, BaseException):
        return str(error.args[0]) if error.args and isinstance(error.args[0], str) else str(error)
    texto = str(error)
    try:
        nodo = ast.parse(texto, mode="eval").body
        if isinstance(nodo, ast.Call) and nodo.args and not nodo.keywords:
            valor = ast.literal_eval(nodo.args[0])
            if isinstance(valor, str):
                return valor
    except (SyntaxError, ValueError):
        pass
    return texto


def _clasificar(snap: Any) -> tuple[str, dict | None, str | None]:
    pendientes = [i for t in snap.tasks for i in t.interrupts]
    if pendientes:
        return "esperando_decision", pendientes[0].value, None
    if snap.next:
        fallas = "; ".join(_mensaje_error(t.error) for t in snap.tasks if t.error)
        detalle = f" ({fallas})" if fallas else ""
        return (
            "error",
            None,
            f"El proceso quedó a medias en {', '.join(snap.next)}{detalle}. Use continuar para reanudarlo.",
        )
    if snap.values:
        return "terminado", None, None
    return "sin_iniciar", None, None


def _leer_estado(g: Any, hilo: dict, cfg: Config, caso_dir: Path, regenerar_previo: bool = False) -> dict:
    snap = g.get_state(hilo)
    estado, payload, error = _clasificar(snap)
    valores = dict(snap.values)
    if estado == "esperando_decision" and regenerar_previo:
        render.render_previo(valores, cfg, salidas.trabajo(caso_dir) / "previo.docx")
    return _respuesta(estado, caso_dir, ok=estado != "error", payload=payload, resumen=_resumen(valores), error=error)


def _fallo(caso_dir: Path, e: Exception) -> dict:
    log.exception("Falló la operación sobre %s", caso_dir.name)
    return _respuesta("error", caso_dir, ok=False, error=str(e) or type(e).__name__)


def _cargar_ingesta(caso_dir: Path) -> Ingesta | None:
    caso_json = caso_dir / "caso.json"
    if not caso_json.exists():
        return None
    return Ingesta.model_validate_json(caso_json.read_text(encoding="utf-8"))


def _respuesta_revision(caso_dir: Path, ing: Ingesta) -> dict:
    estado = "revision" if ing.completo else "incompleto"
    return _respuesta(estado, caso_dir, resumen=_resumen_ingesta(caso_dir, ing))


def _generar_previos(caso_dir: Path, ing: Ingesta, cfg: Config, auto: DatosAuto | None = None) -> None:
    efectivo = expediente.auto_efectivo(caso_dir, ing.metadatos, auto)
    expediente.generar_previos(caso_dir, ing, cfg, efectivo)
    requerimiento = salidas.trabajo(caso_dir) / "requerimiento.docx"
    if ing.completo:
        requerimiento.unlink(missing_ok=True)
    else:
        render.render_requerimiento(ing, cfg, requerimiento)


@resumen_caso.tras_transicion
def nuevo(caso_dir: str | Path) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        cfg = cfgmod.cargar(caso_dir)
        roles_usuario: dict[str, str] = {}
        previa = _cargar_ingesta(caso_dir)
        if previa is not None:
            roles_usuario = {d.sha256: d.rol for d in previa.documentos if d.rol_origen == "usuario"}
        ing = ingest.ingerir(caso_dir, cfg)
        if roles_usuario:
            roles = {d.doc_id: roles_usuario[d.sha256] for d in ing.documentos if d.sha256 in roles_usuario}
            if roles:
                ing = ingest.reaplicar(ing, roles)
        if (caso_dir / "hilo.sqlite").exists():
            log.warning("%s: se descarta el hilo anterior y se reinicia el caso.", caso_dir.name)
        _borrar_hilo(caso_dir)
        shutil.rmtree(salidas.raiz(caso_dir), ignore_errors=True)
        (caso_dir / "caso.json").write_text(ing.model_dump_json(indent=2), encoding="utf-8")
        _generar_previos(caso_dir, ing, cfg)
        return _respuesta_revision(caso_dir, ing)
    except Exception as e:
        return _fallo(caso_dir, e)


@resumen_caso.tras_transicion
def revisar(caso_dir: str | Path, roles: dict[str, str] | None = None, auto: dict | None = None) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        if _hilo_vigente(caso_dir):
            actual = estado(caso_dir)
            return _respuesta(
                actual["estado"], caso_dir, ok=False, error="El caso ya se inició; la revisión de documentos ya no es posible."
            )
        ing = _cargar_ingesta(caso_dir)
        if ing is None:
            return _respuesta("sin_iniciar", caso_dir, ok=False, error="El caso no tiene ingesta; use nuevo.")
        cfg = cfgmod.cargar(caso_dir)
        if roles:
            validos = set(get_args(Rol))
            ids = {d.doc_id for d in ing.documentos}
            malos = sorted(f"{k}={v}" for k, v in roles.items() if k not in ids or v not in validos)
            if malos:
                return _respuesta(
                    "revision" if ing.completo else "incompleto",
                    caso_dir,
                    ok=False,
                    error=f"Documento o rol inválido: {', '.join(malos)}.",
                )
            ing = ingest.reaplicar(ing, roles)
            (caso_dir / "caso.json").write_text(ing.model_dump_json(indent=2), encoding="utf-8")
        nuevo_auto = None
        if auto is not None:
            previo = caso_dir / "auto.json"
            guardado = DatosAuto.model_validate_json(previo.read_text(encoding="utf-8")) if previo.exists() else DatosAuto()
            cambios = {k: v for k, v in auto.items() if k in DatosAuto.model_fields}
            nuevo_auto = DatosAuto.model_validate({**guardado.model_dump(), **cambios})
            _generar_previos(caso_dir, ing, cfg, nuevo_auto)
            previo.write_text(nuevo_auto.model_dump_json(indent=2), encoding="utf-8")
        else:
            _generar_previos(caso_dir, ing, cfg)
        return _respuesta_revision(caso_dir, ing)
    except Exception as e:
        return _fallo(caso_dir, e)


@resumen_caso.tras_transicion
def iniciar(caso_dir: str | Path) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        if _hilo_vigente(caso_dir):
            actual = estado(caso_dir)
            return _respuesta(actual["estado"], caso_dir, ok=False, error="El caso ya se inició; use continuar.")
        ing = _cargar_ingesta(caso_dir)
        if ing is None:
            return _respuesta("sin_iniciar", caso_dir, ok=False, error="El caso no tiene ingesta; use nuevo.")
        if not ing.completo:
            return _respuesta(
                "incompleto",
                caso_dir,
                ok=False,
                resumen=_resumen_ingesta(caso_dir, ing),
                error=f"Faltan documentos obligatorios: {', '.join(ing.faltantes)}.",
            )
        cfg = cfgmod.cargar(caso_dir)
        with _grafo(caso_dir, cfg, llm.cliente_para(cfg)) as (g, hilo):
            g.invoke(graph.estado_inicial(caso_dir, cfg, ing), hilo, durability="sync")
            return _leer_estado(g, hilo, cfg, caso_dir, regenerar_previo=True)
    except Exception as e:
        return _fallo(caso_dir, e)


def _hilo_vigente(caso_dir: Path) -> bool:
    if not (caso_dir / "hilo.sqlite").exists():
        return False
    cfg = cfgmod.cargar(caso_dir)
    with _grafo(caso_dir, cfg) as (g, hilo):
        vacio = _clasificar(g.get_state(hilo))[0] == "sin_iniciar"
    if vacio:
        _borrar_hilo(caso_dir)
    return not vacio


def estado(caso_dir: str | Path) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        if (caso_dir / "hilo.sqlite").exists():
            cfg = cfgmod.cargar(caso_dir)
            with _grafo(caso_dir, cfg) as (g, hilo):
                respuesta = _leer_estado(g, hilo, cfg, caso_dir)
            if respuesta["estado"] != "sin_iniciar":
                return respuesta
        ing = _cargar_ingesta(caso_dir)
        if ing is None:
            return _respuesta("sin_iniciar", caso_dir)
        return _respuesta_revision(caso_dir, ing)
    except Exception as e:
        return _fallo(caso_dir, e)


@resumen_caso.tras_transicion
def decidir(caso_dir: str | Path, decision: dict) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        if not (caso_dir / "hilo.sqlite").exists():
            actual = estado(caso_dir)
            return _respuesta(
                actual["estado"], caso_dir, ok=False, error="No hay una decisión pendiente: el caso no se ha iniciado."
            )
        cfg = cfgmod.cargar(caso_dir)
        with _grafo(caso_dir, cfg, llm.cliente_para(cfg)) as (g, hilo):
            antes = g.get_state(hilo)
            actual, _, _ = _clasificar(antes)
            if actual != "esperando_decision":
                mensaje = f"No hay una decisión pendiente (estado: {actual})."
                if actual == "error":
                    mensaje += ' Si ya envió la decisión, quedó guardada: use "Continuar ejecución" en la pestaña Ejecutar.'
                return _respuesta(actual, caso_dir, ok=False, error=mensaje)
            (caso_dir / "decision.json").write_text(
                json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            previo = salidas.trabajo(caso_dir) / "previo.docx"
            if not decision.get("previo_sha256") and previo.exists():
                decision = {**decision, "previo_sha256": hashlib.sha256(previo.read_bytes()).hexdigest()}
            n_antes = len(antes.values.get("decisiones") or [])
            g.invoke(Command(resume=decision), hilo, durability="sync")
            despues = g.get_state(hilo).values.get("decisiones") or []
            rehecho = len(despues) > n_antes and despues[-1]["accion"].startswith("rehacer")
            return _leer_estado(g, hilo, cfg, caso_dir, regenerar_previo=rehecho)
    except Exception as e:
        return _fallo(caso_dir, e)


def _fallos_consecutivos(nodo: str, bitacora: list[dict], caso_dir: Path) -> list[dict]:
    exitos = [b for b in bitacora if b.get("nodo") == nodo]
    ultima = max((b.get("fecha") or "" for b in exitos), default="")
    return [
        f
        for f in fallos.leer(caso_dir)
        if f.get("nodo") == nodo
        and (f["exitos"] == len(exitos) if "exitos" in f else (f.get("fecha") or "") > ultima)
    ]


@resumen_caso.tras_transicion
def continuar(caso_dir: str | Path, forzar: bool = False) -> dict:
    caso_dir = Path(caso_dir).resolve()
    try:
        if not (caso_dir / "hilo.sqlite").exists():
            return _respuesta("sin_iniciar", caso_dir, ok=False, error="El caso no tiene un hilo; use nuevo.")
        cfg = cfgmod.cargar(caso_dir)
        with _grafo(caso_dir, cfg, llm.cliente_para(cfg)) as (g, hilo):
            snap = g.get_state(hilo)
            actual, _, _ = _clasificar(snap)
            if actual == "error" and not forzar and snap.next:
                nodo = snap.next[0]
                seguidos = _fallos_consecutivos(nodo, snap.values.get("bitacora") or [], caso_dir)
                if len(seguidos) >= cfg.max_intentos:
                    respuesta = _respuesta(
                        "error",
                        caso_dir,
                        ok=False,
                        resumen=_resumen(dict(snap.values)),
                        error=(
                            f"La llamada a la IA del paso {nodo} falló {len(seguidos)} veces seguidas "
                            f"(último error: {seguidos[-1].get('error', 'desconocido')}). No se reintenta "
                            "automáticamente para no reenviar y cobrar el expediente otra vez. Revise la "
                            "configuración o la clave de API antes de forzar un nuevo intento."
                        ),
                    )
                    respuesta["tope_intentos"] = True
                    return respuesta
            if actual == "error":
                g.invoke(None, hilo, durability="sync")
            return _leer_estado(g, hilo, cfg, caso_dir, regenerar_previo=actual == "error")
    except Exception as e:
        return _fallo(caso_dir, e)
