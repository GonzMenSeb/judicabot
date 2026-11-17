"""Correcciones a mano de los apoderados e identificación de los casos anteriores a ella.

``PUT …/apoderados/{ap}/ajustes`` guarda en ``registro.ajustes`` lo que corrige quien revisa, bajo el
candado del registro del caso, sin lanzar trabajos ni volver a correr el grafo:

- ``poder_manual`` ("Señalar el poder a mano…"): la página donde está el poder que el código no
  halló. Se vuelve a comprobar con el texto de la página: el nombre del abogado debe constar en ella
  y la cita se toma de allí (``apoderados.evidencia_poder_manual``); si no, 422.
- ``poder_descartado`` ("No es correcto…"): el poder que se muestra no lo faculta. Si era uno
  señalado a mano, se quita.
- ``cedula``: la cédula del abogado cuando el expediente no la trae (de 5 a 10 dígitos, con puntos o
  espacios; se guarda con 0-9 aunque se escriba con dígitos de ancho completo). Se pone en la cola de consultas de vigencia, salvo que la consulta automática
  esté apagada; entonces queda la subida del certificado a mano. La que reemplaza (quizá mal escrita,
  de otra persona) sale de la cola y su consulta se borra si ya nadie la usa.

Un campo que no viene no se toca y uno que viene en ``null`` quita esa corrección. Cada corrección
cambia la huella del apoderado, así que una revisión anterior vence. Ningún registro de log ni
mensaje de error lleva la cédula.

``POST …/apoderados/identificar`` identifica a los apoderados de un caso que llegó a la decisión sin
identificación (anterior al nodo ``apoderados``, o con una identificación que falló). Corre en un
trabajo del caso, como ``/run``, para que nada más toque el grafo mientras tanto: llama a
``graph.nodo_apoderados`` con el estado actual y escribe su salida en el estado con
``Command(update=…)``, sin pasar por ningún otro nodo. Así la decisión pendiente se vuelve a
presentar al instante con las alertas nuevas; ``update_state(as_node=…)`` la perdería, porque
encamina el grafo al nodo que sigue al indicado. Después se vuelve a generar el borrador previo, que
ya marca los nombres de los abogados; el nodo pone en cola sus cédulas. Una identificación que falla
queda solo en el registro, para poder reintentarla. Responde 202 al empezar y 200 si no hay nada que
hacer.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from tutela2 import (
    apoderados,
    estado_apoderados,
    registro_apoderados,
    resumen_caso,
    rutas_apoderados,
    rutas_expediente,
    vigencia,
)
from tutela2 import config as cfgmod
from tutela2.esquemas_apoderados import ApoderadosRespuesta, ApoderadoVista
from tutela2.models import Apoderado, EvidenciaDoc, Identificacion
from tutela2.registro_apoderados import Ajuste, ConsultaVigencia, Registro

log = logging.getLogger("tutela2.rutas_ajustes_apoderados")

router = APIRouter()

CORRECCIONES = frozenset({"poder_manual", "poder_descartado", "cedula"})
CMD_IDENTIFICAR = "identificar"
MAX_TRABAJOS = 50

NADA_QUE_AJUSTAR = "Indique qué corregir: el poder señalado a mano, si el poder hallado no es correcto o la cédula del abogado."
SIN_PAGINA = "La página indicada no existe en el expediente."
DOC_AJENO = "Ese documento es de otro radicado: no puede acreditar el poder."
SIN_NOMBRE = "El nombre del abogado no aparece en esa página."
CEDULA_INVALIDA = "La cédula debe tener entre 5 y 10 dígitos."
CEDULA_DEL_EXPEDIENTE = "La cédula del abogado consta en el expediente; no se puede cambiar a mano."
SIN_PODER = "No hay un poder hallado que se pueda descartar."
NO_ESPERANDO = "El caso no está esperando la decisión: no se pueden identificar los apoderados ahora."
EN_CURSO = "Ya hay una ejecución en curso para este caso."
DESACTIVADA = "La identificación de apoderados está desactivada en la configuración del caso."
FALLIDA = "No se pudieron identificar los apoderados; inténtelo de nuevo."

_CEDULA = re.compile(r"[\d.\s]{1,32}")


class PoderManualCuerpo(BaseModel):
    doc_id: str = Field(pattern=rutas_expediente.PATRON_DOC_ID, description="doc_id de la ingesta, p. ej. 1a-014.")
    pagina: int = Field(ge=1, le=100_000)


class AjusteCuerpo(BaseModel):
    """Correcciones a mano de un apoderado: un campo que no viene no cambia; uno en ``null`` quita esa corrección."""

    poder_manual: PoderManualCuerpo | None = Field(
        None, description="Página donde está el poder; se comprueba que nombre al abogado y de ella se toma la cita."
    )
    poder_descartado: bool | None = Field(None, description="El poder que se muestra no es correcto («No es correcto…»).")
    cedula: str | None = Field(
        None, description="Cédula del abogado si el expediente no la trae: de 5 a 10 dígitos (admite puntos y espacios)."
    )
    nota: str = Field("", max_length=2000, description="Razón de la corrección; queda en el informe de verificación.")


class _NoEncontrado(LookupError):
    pass


class _SinPoder(Exception):
    pass


def _cedula_pedida(texto: str | None, ap: Apoderado) -> str | None:
    """La cédula del ajuste en dígitos, o ``None`` para no guardar ninguna.

    Solo completa la que falta en el expediente: la verificada manda (la subida del certificado la
    exige), así que otra distinta es un conflicto y la misma no hace falta guardarla."""
    texto = (texto or "").strip()
    if not texto:
        return None
    digitos = rutas_apoderados._digitos(texto)
    minimo, maximo = apoderados.DIGITOS_CEDULA
    if not _CEDULA.fullmatch(texto) or not minimo <= len(digitos) <= maximo:
        raise HTTPException(422, CEDULA_INVALIDA)
    del_expediente = rutas_apoderados._digitos(ap.cedula)
    if del_expediente:
        if digitos != del_expediente:
            raise HTTPException(409, CEDULA_DEL_EXPEDIENTE)
        return None
    return digitos


def _evidencia_manual(caso_dir: Path, ap: Apoderado, pedido: PoderManualCuerpo) -> EvidenciaDoc:
    ing = rutas_expediente.ingesta(caso_dir)
    doc = next((d for d in ing.documentos if d.doc_id == pedido.doc_id), None) if ing is not None else None
    pagina = next((p for p in doc.paginas if p.n == pedido.pagina), None) if doc is not None else None
    if ing is None or doc is None or pagina is None:
        raise HTTPException(422, SIN_PAGINA)
    if doc.doc_id in ing.docs_ajenos:
        raise HTTPException(422, DOC_AJENO)
    evidencia = apoderados.evidencia_poder_manual(doc, pagina, ap.nombre)
    if evidencia is None:
        raise HTTPException(422, SIN_NOMBRE)
    return evidencia


def _consulta_automatica(caso_dir: Path) -> bool:
    try:
        return cfgmod.cargar(caso_dir).apoderados.consulta != "apagada"
    except Exception:
        log.warning("No se pudo leer la configuración de %s", caso_dir.name, exc_info=True)
        return False


def _encolar(caso_dir: Path, cedulas: list[str]) -> None:
    """Pone las cédulas en la cola de consultas de vigencia, salvo que la consulta automática esté apagada.

    Si la cola falla, la corrección sigue guardada: el abogado queda en «Necesita su ayuda» y el
    certificado se puede subir a mano. El registro de log no lleva la cédula."""
    cedulas = [c for c in dict.fromkeys(cedulas) if c]
    if not cedulas or not _consulta_automatica(caso_dir):
        return
    try:
        vigencia.COLA.encolar(caso_dir, cedulas)
    except Exception as e:
        log.warning("%s: no se pudo poner en cola la consulta de vigencia (%s)", caso_dir.name, type(e).__name__)


def _correcciones(ajuste: Ajuste) -> tuple[Any, ...]:
    return ajuste.cedula, ajuste.poder_manual, ajuste.poder_descartado


def _vista_de(caso_id: str, caso_dir: Path, ap_id: str) -> ApoderadoVista:
    """El apoderado al día, leído de nuevo: la cola pudo aplicar ya una consulta guardada en caché."""
    reg = rutas_apoderados._registro(caso_dir)
    ev = next((e for e in rutas_apoderados._evaluar_todos(reg, caso_dir) if e.apoderado.id == ap_id), None)
    if ev is None:
        raise HTTPException(404, rutas_apoderados.NO_ENCONTRADO)
    return rutas_apoderados._vista(ev, reg, rutas_apoderados._documentos(caso_dir), caso_id)


@router.put(
    "/api/casos/{caso_id}/apoderados/{ap_id}/ajustes",
    response_model=ApoderadoVista,
    responses={
        404: {"description": "Caso o apoderado no encontrado."},
        409: {
            "description": "El caso no está esperando la decisión, la cédula ya consta en el expediente "
            "o no hay un poder que descartar."
        },
        422: {
            "description": "No hay nada que ajustar, la cédula no es válida, o la página no existe, es de otro "
            "radicado o no nombra al abogado."
        },
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def ajustar_apoderado(caso_id: str, ap_id: str, cuerpo: AjusteCuerpo) -> ApoderadoVista:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, _ = rutas_apoderados._estado_del_caso(caso_dir)
    if not rutas_apoderados._editable(caso_id, estado):
        raise HTTPException(409, rutas_apoderados.NO_EDITABLE)
    pedidos = cuerpo.model_fields_set & CORRECCIONES
    if not pedidos:
        raise HTTPException(422, NADA_QUE_AJUSTAR)
    ap = rutas_apoderados._apoderado(rutas_apoderados._registro(caso_dir), ap_id)
    if ap is None:
        raise HTTPException(404, rutas_apoderados.NO_ENCONTRADO)
    cedula = _cedula_pedida(cuerpo.cedula, ap) if "cedula" in pedidos else None
    manual = _evidencia_manual(caso_dir, ap, cuerpo.poder_manual) if cuerpo.poder_manual is not None else None
    nota = cuerpo.nota.strip()
    sin_uso: list[ConsultaVigencia] = []
    retiradas: list[str] = []
    cambiados: list[str] = []

    def ajustar(reg: Registro) -> None:
        actual = rutas_apoderados._apoderado(reg, ap_id)
        if actual is None or actual.nombre != ap.nombre:
            raise _NoEncontrado(ap_id)
        anterior = reg.ajustes.get(ap_id) or Ajuste()
        nuevo = anterior.model_copy()
        if "poder_manual" in pedidos:
            nuevo.poder_manual = manual
        if "poder_descartado" in pedidos:
            descartar = bool(cuerpo.poder_descartado)
            if descartar and not (actual.poderes or actual.ajenos or anterior.poder_manual or manual):
                raise _SinPoder(ap_id)
            nuevo.poder_descartado = descartar
            # «No es correcto…» sobre un poder señalado a mano lo quita: es el que se mostraba.
            if descartar and "poder_manual" not in pedidos:
                nuevo.poder_manual = None
        if "cedula" in pedidos:
            nuevo.cedula = cedula
        pares = zip(("cedula", "poder_manual", "poder_descartado"), _correcciones(anterior), _correcciones(nuevo))
        cambiados.extend(campo for campo, antes, despues in pares if antes != despues)
        if cambiados:
            nuevo.en = registro_apoderados.ahora()
        if nota:
            nuevo.nota = nota
        if _correcciones(nuevo) == _correcciones(Ajuste()):
            reg.ajustes.pop(ap_id, None)
        else:
            reg.ajustes[ap_id] = nuevo
        # La consulta de una cédula que ya nadie usa (una mal escrita o reemplazada) se quita con su
        # PDF: no se guardan datos de quien no es parte del caso.
        # Tampoco se consulta: sale de la cola aunque ya estuviera esperando.
        previa = rutas_apoderados._digitos(anterior.cedula)
        if previa and previa not in rutas_apoderados._cedulas_en_uso(reg):
            retiradas.append(previa)
            if previa in reg.consultas:
                sin_uso.append(reg.consultas.pop(previa))

    try:
        reg = registro_apoderados.actualizar(caso_dir, ajustar)
    except _NoEncontrado:
        raise HTTPException(404, rutas_apoderados.NO_ENCONTRADO) from None
    except _SinPoder:
        raise HTTPException(409, SIN_PODER) from None
    except registro_apoderados.RegistroInvalido as e:
        raise HTTPException(500, str(e)) from None
    if reg is None:
        raise HTTPException(404, rutas_apoderados.NO_ENCONTRADO)
    registro_apoderados.borrar_certificados_sin_uso(caso_dir, [c.certificado for c in sin_uso if c.certificado])
    rutas_apoderados.retirar_de_la_cola(caso_dir, retiradas)
    if "cedula" in cambiados and cedula:
        _encolar(caso_dir, [cedula])
    log.info("Ajuste del apoderado %s de %s: %s", ap_id, caso_id, ", ".join(cambiados) or "sin cambios")
    return _vista_de(caso_id, caso_dir, ap_id)


# --- identificación de los casos anteriores a ella ---


def _registrar_trabajo(caso_id: str) -> dict[str, Any]:
    """Registra la identificación como trabajo del caso; 409 si ya corre otro (como ``server.ejecutar``)."""
    from tutela2 import eventos, server

    job = {
        "id": uuid.uuid4().hex,
        "caso": caso_id,
        "cmd": CMD_IDENTIFICAR,
        "estado": "corriendo",
        "log": deque(maxlen=200),
        "resultado": None,
        "error": None,
    }
    with server._LOCK:
        if any(j["caso"] == caso_id and j["estado"] == "corriendo" for j in server.JOBS.values()):
            raise HTTPException(409, EN_CURSO)
        server.JOBS[job["id"]] = job
        eventos.crear(job["id"])
        for viejo in [i for i, j in server.JOBS.items() if j["estado"] != "corriendo"][:-MAX_TRABAJOS]:
            del server.JOBS[viejo]
            eventos.olvidar(viejo)
    return job


def _identificacion(valor: Any) -> Identificacion | None:
    """La identificación guardada en el estado del grafo; ``None`` si no hay o no es válida."""
    if not valor:
        return None
    try:
        return Identificacion.model_validate(valor)
    except ValidationError:
        return None


def _por_identificar(ident: Identificacion | None) -> bool:
    """Falta identificar: el caso es anterior al nodo ``apoderados`` o su identificación falló."""
    return ident is None or estado_apoderados.fallida(ident)


@resumen_caso.tras_transicion
def identificar(caso_dir: Path) -> dict:
    """Identifica a los apoderados de un caso que espera la decisión y no los tiene identificados.

    Corre dentro de un trabajo del caso. La salida de ``graph.nodo_apoderados`` entra al estado con
    ``Command(update=…)``: el grafo sigue en la decisión, que se vuelve a presentar con las alertas
    nuevas, y ningún otro nodo corre. Luego se regenera el borrador previo (con los nombres de los
    abogados marcados); el nodo ya copió la identificación al registro y puso en cola las cédulas.

    Una identificación que falla no se escribe en el estado, solo en el registro (la pestaña la muestra
    como fallida): el cambio queda pendiente sobre el mismo punto de control de la decisión, que no
    admite dos valores de la misma clave, y así se puede reintentar hasta que salga bien."""
    from langgraph.types import Command

    from tutela2 import graph, llm, preferencias, server

    api = server._api()
    preferencias.aplicar_entorno(preferencias.leer(server._preferencias()))
    caso_dir = Path(caso_dir)
    cfg = cfgmod.cargar(caso_dir)
    # El grafo se arma sin cliente del modelo: ningún nodo que lo use puede correr durante el cambio.
    with api._grafo(caso_dir, cfg) as (g, hilo):
        snap = g.get_state(hilo)
        estado, _, _ = api._clasificar(snap)
        if estado != "esperando_decision":
            return api._respuesta(estado, caso_dir, ok=False, error=NO_ESPERANDO)
        valores = dict(snap.values)
        anterior = _identificacion(valores.get("apoderados"))
        if not _por_identificar(anterior):
            registro_apoderados.espejar(caso_dir, anterior)
            return api._leer_estado(g, hilo, cfg, caso_dir)
        if not cfg.apoderados.activo:
            return api._respuesta(estado, caso_dir, ok=False, error=DESACTIVADA)
        salida = graph.nodo_apoderados(valores, cfg, llm.cliente_para(cfg))
        ident = _identificacion(salida.get("apoderados"))
        if ident is None:
            # Ni el expediente ni las partes cambiaron desde la identificación anterior: no hay qué rehacer.
            return api._leer_estado(g, hilo, cfg, caso_dir)
        # El nodo copió la identificación al registro de la carpeta que guarda el estado; esta es la de hoy.
        registro_apoderados.espejar(caso_dir, ident)
        if estado_apoderados.fallida(ident):
            return api._respuesta(estado, caso_dir, ok=False, error=" ".join(ident.alertas) or FALLIDA)
        cambios = {k: v for k, v in salida.items() if k in ("apoderados", "alertas", "intentos", "bitacora")}
        g.invoke(Command(update=cambios), hilo, durability="sync")
        respuesta = api._leer_estado(g, hilo, cfg, caso_dir, regenerar_previo=True)
    if Path(valores["caso_dir"]).resolve() != caso_dir.resolve():
        _encolar(caso_dir, [a.cedula for a in ident.apoderados if a.cedula])
    log.info(
        "%s: apoderados identificados en un caso que no los tenía (%d apoderados)", caso_dir.name, len(ident.apoderados)
    )
    return respuesta


@router.post(
    "/api/casos/{caso_id}/apoderados/identificar",
    response_model=ApoderadosRespuesta,
    responses={
        200: {"description": "El caso ya tiene a sus apoderados identificados; no se hizo nada."},
        202: {
            "model": ApoderadosRespuesta,
            "description": "La identificación empezó en un trabajo del caso (cabecera Location: /api/jobs/{id}); "
            "la respuesta es el estado actual, que se vuelve a leer con GET …/apoderados.",
        },
        404: {"description": "Caso no encontrado."},
        409: {
            "description": "El caso no está esperando la decisión, ya hay una ejecución en curso o la identificación "
            "está desactivada."
        },
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def identificar_apoderados(caso_id: str, respuesta: Response) -> ApoderadosRespuesta:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, valores = rutas_apoderados._estado_del_caso(caso_dir)
    if estado != "esperando_decision":
        raise HTTPException(409, NO_ESPERANDO)
    if server._job_activo(caso_id) is not None:
        raise HTTPException(409, EN_CURSO)
    # Lo que cuenta es el estado del grafo, del que sale el borrador previo; el espejo se escribe desde él.
    if not _por_identificar(_identificacion(valores.get("apoderados"))):
        return rutas_apoderados.leer_apoderados(caso_id)
    if not cfgmod.cargar(caso_dir).apoderados.activo:
        raise HTTPException(409, DESACTIVADA)
    job = _registrar_trabajo(caso_id)
    threading.Thread(target=server._ejecutar, args=(job, lambda: identificar(caso_dir)), daemon=True).start()
    respuesta.status_code = 202
    respuesta.headers["Location"] = f"/api/jobs/{job['id']}"
    return rutas_apoderados.leer_apoderados(caso_id)
