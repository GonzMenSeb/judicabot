"""API de los apoderados del caso: estado de cada abogado, su revisión y el certificado de vigencia.

``GET`` solo lee: el estado se calcula en cada petición con ``estado_apoderados.evaluar`` sobre
el registro del caso. Si falta el espejo de la identificación (casos que la tienen solo en el
grafo), se lee una vez del estado del grafo, bajo el candado del registro, y se guarda. Las
escrituras toman el candado del registro, nunca ``server._LOCK``, y no lanzan trabajos ni vuelven
a correr el grafo. Una revisión solo se guarda si el estado que vio quien revisa (su ``huella``)
sigue siendo el actual. Un registro dañado responde 500 y no se reescribe.

El certificado de vigencia se puede subir a mano (``PUT …/certificado``): debe ser un PDF que se
lea entero y de la cédula verificada del abogado; si el expediente no trae su cédula, debe estar a
su nombre y se toma la del certificado. Lo demás es de otra persona (422) y no se guarda. El
certificado de una cédula no inscrita como abogado(a) no trae nombre: solo se acepta para un abogado
que ya tiene cédula (la del expediente o la escrita a mano) y si es la misma; sin cédula, 422 y nada se
guarda. Se guarda
con ``origen="manual"`` en ``apoderados/certificados/`` con un nombre hecho del id del apoderado y
del hash del contenido, nunca con la cédula, que tampoco va a ningún registro de log. La consulta
automática de esa cédula que esperaba en la cola sale de ella: ya no hace falta.

``POST …/consultar`` pone las cédulas en la cola de consultas automáticas (``vigencia.COLA``), que
corre aparte y escribe los resultados en el registro: el GET muestra la fase de cada abogado
(en cola, consultando) mientras tanto. Con la consulta apagada (lo predeterminado) responde 409 y
nada sale; el borrador ofrece entonces subir el certificado a mano."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from tutela2 import config as cfgmod
from tutela2 import estado_apoderados, registro_apoderados, vigencia
from tutela2.esquemas_apoderados import (
    ApoderadosRespuesta,
    ApoderadoVista,
    CadenaVista,
    ConsultaEstado,
    ConsultarCuerpo,
    EstadoExtension,
    EvidenciaVista,
    ParteSinApoderadoVista,
    PoderVista,
    RevisionCuerpo,
    VigenciaVista,
)
from tutela2.estado_apoderados import Evaluacion
from tutela2.models import Apoderado, Doc, EvidenciaDoc
from tutela2.registro_apoderados import Ajuste, ConsultaVigencia, Registro, Revision
from tutela2.vigencia import CertificadoVigencia

log = logging.getLogger("tutela2.rutas_apoderados")

router = APIRouter()

NO_EDITABLE = "El caso no está esperando la decisión: la revisión de los apoderados no se puede cambiar ahora."
NO_ENCONTRADO = "Apoderado no encontrado."
CAMBIO = "El estado del apoderado cambió; revíselo de nuevo."

MAX_BYTES_CERTIFICADO = 2 * 1024 * 1024
MUY_GRANDE = "El certificado excede el tamaño máximo permitido (2 MiB)."
NO_ES_PDF = "El archivo no es un PDF."
ILEGIBLE = "No se pudo leer el certificado."
OTRA_PERSONA = "El certificado es de otra persona."
SIN_NOMBRE = "El certificado no trae nombre: escriba primero la cédula del abogado."
SIN_CERTIFICADO = "Certificado no encontrado."
DETALLE_MANUAL = "Certificado subido por el despacho."
CONSULTA_APAGADA = (
    "La consulta automática de la vigencia está apagada en esta instalación: descargue el certificado en la "
    "página de la Rama Judicial y súbalo aquí."
)
_CABECERAS_PDF = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


def _estado_del_caso(caso_dir: Path) -> tuple[str, dict[str, Any]]:
    """Estado del caso (como ``api.estado``) y los valores del grafo; sin hilo, ``sin_iniciar``.

    No crea ``hilo.sqlite`` cuando no existe."""
    if not (caso_dir / "hilo.sqlite").exists():
        return "sin_iniciar", {}
    from tutela2 import server

    api = server._api()
    try:
        cfg = cfgmod.cargar(caso_dir)
        with api._grafo(caso_dir, cfg) as (g, hilo):
            snap = g.get_state(hilo)
            return api._clasificar(snap)[0], dict(snap.values)
    except Exception:
        log.exception("No se pudo leer el estado del grafo de %s", caso_dir.name)
        return "error", {}


def _registro(caso_dir: Path) -> Registro:
    """El registro del caso, con el espejo escrito desde el grafo si faltaba.

    El grafo se vuelve a leer dentro del candado: si ``nuevo`` borró el hilo y el registro entre la
    lectura del estado y esta, lo leído antes es del caso anterior y no debe volver a escribirse."""
    try:
        return registro_apoderados.espejar_si_falta(caso_dir, lambda: _estado_del_caso(caso_dir)[1].get("apoderados"))
    except registro_apoderados.RegistroInvalido as e:
        raise HTTPException(500, str(e)) from None


def _editable(caso_id: str, estado: str) -> bool:
    from tutela2 import server

    return estado == "esperando_decision" and server._job_activo(caso_id) is None


def _estado_extension() -> EstadoExtension:
    """Si hay una extensión conectada que consulte la vigencia (1.1.0 o más nueva), una más vieja o ninguna."""
    from tutela2 import extension

    try:
        return extension.estado_conexion()
    except Exception:
        log.warning("No se pudo saber si la extensión está conectada", exc_info=True)
        return "no_conectada"


def _evaluar_todos(reg: Registro, caso_dir: Path | None = None) -> list[Evaluacion]:
    """Evalúa a todos los apoderados con la fase de la cola de consultas automáticas (de ``caso_dir``,
    si se da). La cola dice la verdad: una cédula sin consultar que no está en ella (la consulta está
    apagada, la extensión no está o se reinició el servidor) necesita ayuda."""

    def fase(cedula: str) -> estado_apoderados.FaseCola | None:
        return vigencia.COLA.fase(cedula, caso_dir)

    return estado_apoderados.evaluar_todos(reg, fase_cola=fase)


def _evidencia(e: EvidenciaDoc | None, docs: dict[str, Doc]) -> EvidenciaVista | None:
    if e is None:
        return None
    doc = docs.get(e.doc_id)
    return EvidenciaVista(
        doc_id=e.doc_id,
        documento=doc.nombre if doc is not None else e.doc_id,
        rol=doc.rol if doc is not None else None,
        pagina=e.pagina,
        total_paginas=len(doc.paginas) if doc is not None else None,
        cita=e.cita,
        ocr=e.ocr,
        inicio=e.inicio,
        fin=e.fin,
    )


def _vista(ev: Evaluacion, reg: Registro, docs: dict[str, Doc], caso_id: str) -> ApoderadoVista:
    ap, consulta, mostrado = ev.apoderado, ev.consulta, ev.poder_mostrado
    datos = consulta.datos if consulta is not None else None
    certificado_url = (
        f"/api/casos/{quote(caso_id)}/apoderados/{quote(ap.id)}/certificado"
        if consulta is not None and consulta.certificado
        else None
    )
    cadena = None
    if mostrado is not None:
        c = mostrado.cadena
        cadena = CadenaVista(estado=c.estado, otorgante=c.otorgante, cargo=c.cargo, evidencia=_evidencia(c.evidencia, docs))
    documentos = reg.identificacion.documentos_revisados if reg.identificacion is not None else 0
    return ApoderadoVista(
        id=ap.id,
        nombre=ap.nombre,
        parte=ap.parte,
        rol_parte=ap.rol_parte,
        tipo_persona=ap.tipo_persona,
        estado=ev.estado,
        fase=ev.fase,
        motivos=ev.motivos,
        cedula=ev.cedula,
        tarjeta=ap.tarjeta,
        vigencia=VigenciaVista(
            estado=ev.vigencia,
            fase=ev.fase,
            cedula=ev.cedula,
            tarjeta_registro=datos.tpa_numero if datos is not None else None,
            consultado_en=consulta.consultado_en if consulta is not None else None,
            origen=consulta.origen if consulta is not None else None,
            certificado_url=certificado_url,
            numero_certificado=datos.numero if datos is not None else None,
            codigo_verificacion=datos.codigo_verificacion if datos is not None else None,
            detalle=consulta.detalle if consulta is not None else "",
            grave=ev.vigencia_grave,
        ),
        poder=PoderVista(
            estado=ev.poder,
            tipo=mostrado.tipo if mostrado is not None else None,
            evidencia=_evidencia(mostrado.evidencia, docs) if mostrado is not None else None,
            otorgante=mostrado.otorgante if mostrado is not None else "",
            parte=mostrado.parte if mostrado is not None else "",
            cadena=cadena,
            mencion=_evidencia(ap.menciones[0] if ap.menciones else None, docs),
            documentos_revisados=documentos,
            hay_hallado=bool(ap.poderes or ap.ajenos),
        ),
        cotejos=ev.cotejos,
        revisado=ev.revisado,
        revision_vencida=ev.revision_vencida,
        bloquea=ev.bloquea,
        huella=ev.huella,
    )


def _documentos(caso_dir: Path) -> dict[str, Doc]:
    from tutela2 import rutas_expediente

    try:
        ing = rutas_expediente.ingesta(caso_dir)
    except Exception:
        log.exception("No se pudo leer la ingesta de %s", caso_dir.name)
        return {}
    return {d.doc_id: d for d in ing.documentos} if ing is not None else {}


def _consulta(caso_dir: Path, evaluaciones: list[Evaluacion]) -> ConsultaEstado:
    """``activa`` si la cola atiende o atenderá a algún abogado del caso (lo que ve el borrador);
    ``pausa_hasta`` si la cola espera tras quedar la Rama Judicial sin responder."""
    modo = vigencia.modo_consulta(caso_dir)
    pausa = vigencia.COLA.pausa_hasta() if modo in vigencia.MODOS_REGISTRO else None
    return ConsultaEstado(
        activa=any(ev.fase in ("en_cola", "consultando") for ev in evaluaciones),
        extension=_estado_extension(),
        modo=modo,
        pausa_hasta=pausa.isoformat(timespec="seconds") if pausa is not None else None,
    )


@router.get(
    "/api/casos/{caso_id}/apoderados",
    response_model=ApoderadosRespuesta,
    responses={
        404: {"description": "Caso no encontrado."},
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def leer_apoderados(caso_id: str) -> ApoderadosRespuesta:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, _ = _estado_del_caso(caso_dir)
    return _respuesta(caso_id, caso_dir, estado, _registro(caso_dir))


def _respuesta(caso_id: str, caso_dir: Path, estado: str, reg: Registro) -> ApoderadosRespuesta:
    ident = reg.identificacion
    evaluaciones = _evaluar_todos(reg, caso_dir) if ident is not None else []
    docs = _documentos(caso_dir) if evaluaciones else {}
    if ident is None:
        identificacion = "no_disponible"
    elif estado_apoderados.fallida(ident):
        identificacion = "fallida"
    else:
        identificacion = "lista"
    return ApoderadosRespuesta(
        identificacion=identificacion,
        apoderados=[_vista(ev, reg, docs, caso_id) for ev in evaluaciones],
        sin_apoderado=[
            ParteSinApoderadoVista(nombre=p.nombre, rol_parte=p.rol_parte, nota=p.nota)
            for p in (ident.sin_apoderado if ident is not None else [])
        ],
        alertas=list(ident.alertas) if ident is not None else [],
        consulta=_consulta(caso_dir, evaluaciones),
        bloquea_decision=any(ev.bloquea for ev in evaluaciones),
        editable=_editable(caso_id, estado),
    )


class _NoEncontrado(LookupError):
    pass


class _Cambio(Exception):
    pass


class _OtraPersona(Exception):
    pass


class _SinNombre(Exception):
    """Un certificado sin nombre (cédula no inscrita) para un abogado sin cédula con que atarlo."""


def _apoderado(reg: Registro, ap_id: str) -> Apoderado | None:
    ident = reg.identificacion
    return next((a for a in ident.apoderados if a.id == ap_id), None) if ident is not None else None


@router.put(
    "/api/casos/{caso_id}/apoderados/{ap_id}/revision",
    response_model=ApoderadoVista,
    responses={
        404: {"description": "Caso o apoderado no encontrado."},
        409: {"description": "El caso no está esperando la decisión, o el estado del apoderado cambió desde que se vio."},
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def revisar_apoderado(caso_id: str, ap_id: str, cuerpo: RevisionCuerpo) -> ApoderadoVista:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, _ = _estado_del_caso(caso_dir)
    if not _editable(caso_id, estado):
        raise HTTPException(409, NO_EDITABLE)
    _registro(caso_dir)

    def marcar(reg: Registro) -> None:
        ap = _apoderado(reg, ap_id)
        if ap is None:
            raise _NoEncontrado(ap_id)
        huella = estado_apoderados.evaluar(ap, reg).huella
        # Marcar revisado vale para el estado que se vio; desmarcar nunca abre la compuerta.
        if cuerpo.revisado and cuerpo.huella != huella:
            raise _Cambio(ap_id)
        reg.revisiones[ap_id] = Revision(
            revisado=cuerpo.revisado, en=registro_apoderados.ahora(), huella=huella, nota=cuerpo.nota.strip()
        )

    try:
        reg = registro_apoderados.actualizar(caso_dir, marcar)
    except _NoEncontrado:
        raise HTTPException(404, NO_ENCONTRADO) from None
    except _Cambio:
        raise HTTPException(409, CAMBIO) from None
    except registro_apoderados.RegistroInvalido as e:
        raise HTTPException(500, str(e)) from None
    ev = next((e for e in _evaluar_todos(reg, caso_dir) if e.apoderado.id == ap_id), None) if reg is not None else None
    if ev is None:
        raise HTTPException(404, NO_ENCONTRADO)
    log.info("Apoderado %s de %s marcado como %s", ap_id, caso_id, "revisado" if cuerpo.revisado else "no revisado")
    return _vista(ev, reg, _documentos(caso_dir), caso_id)


# --- consulta automática de la vigencia ---


@router.post(
    "/api/casos/{caso_id}/apoderados/consultar",
    response_model=ApoderadosRespuesta,
    status_code=202,
    responses={
        404: {"description": "Caso o apoderado no encontrado."},
        409: {"description": "El caso no está esperando la decisión, o la consulta automática está apagada."},
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def consultar_apoderados(caso_id: str, cuerpo: ConsultarCuerpo) -> ApoderadosRespuesta:
    """Pone en la cola de consultas automáticas la cédula de los apoderados pedidos (todos, sin ``ids``).

    Sin ``forzar`` se saltan los que ya tienen un resultado y los que agotaron sus intentos del día;
    ``forzar`` (el botón «Reintentar consulta automática») consulta de nuevo, pero respeta la pausa
    tras quedar la Rama Judicial sin responder. Responde enseguida con el estado de los apoderados:
    la consulta sigue aparte y el borrador la sigue con el GET."""
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, _ = _estado_del_caso(caso_dir)
    if not _editable(caso_id, estado):
        raise HTTPException(409, NO_EDITABLE)
    if vigencia.modo_consulta(caso_dir) not in vigencia.MODOS_AUTOMATICOS:
        raise HTTPException(409, CONSULTA_APAGADA)
    reg = _registro(caso_dir)
    apoderados = reg.identificacion.apoderados if reg.identificacion is not None else []
    if cuerpo.ids is not None:
        por_id = {ap.id: ap for ap in apoderados}
        if any(i not in por_id for i in cuerpo.ids):
            raise HTTPException(404, NO_ENCONTRADO)
        apoderados = [por_id[i] for i in dict.fromkeys(cuerpo.ids)]
    cedulas = [c for c in (vigencia.cedula_de(ap, reg) for ap in apoderados) if c]
    n = vigencia.COLA.encolar(caso_dir, cedulas, forzar=cuerpo.forzar) if cedulas else 0
    log.info("Consulta de vigencia pedida en %s: %d de %d apoderados en cola", caso_id, n, len(apoderados))
    return _respuesta(caso_id, caso_dir, estado, _registro(caso_dir))


# --- certificado de vigencia subido a mano ---


def _digitos(texto: str | None) -> str:
    return vigencia.solo_digitos(texto)


def retirar_de_la_cola(caso_dir: Path, cedulas: list[str]) -> None:
    """Saca de la cola de consultas automáticas las cédulas que el caso ya no necesita consultar (tienen un
    certificado subido o ya nadie las usa), para que el borrador no las siga viendo en cola.

    La cola lo vuelve a comprobar antes de enviar cada pedido, así que un fallo aquí no deja salir nada."""
    cedulas = [c for c in dict.fromkeys(cedulas) if c]
    if not cedulas:
        return
    try:
        vigencia.COLA.retirar(caso_dir, cedulas)
    except Exception as e:
        log.warning("%s: no se pudo sacar de la cola una consulta de vigencia (%s)", caso_dir.name, type(e).__name__)


def _cedulas_en_uso(reg: Registro) -> set[str]:
    """Las cédulas con que ``evaluar`` busca la consulta de cada apoderado (la del ajuste manda)."""
    if reg.identificacion is None:
        return set()
    usadas = set()
    for ap in reg.identificacion.apoderados:
        ajuste = reg.ajustes.get(ap.id)
        usadas.add(_digitos(ajuste.cedula if ajuste is not None and ajuste.cedula else ap.cedula))
    return usadas - {""}


def _preparar_subida(caso_id: str, ap_id: str) -> Path:
    """Comprueba, antes de leer el PDF, que el caso admite cambios y que el apoderado existe."""
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    estado, _ = _estado_del_caso(caso_dir)
    if not _editable(caso_id, estado):
        raise HTTPException(409, NO_EDITABLE)
    if _apoderado(_registro(caso_dir), ap_id) is None:
        raise HTTPException(404, NO_ENCONTRADO)
    return caso_dir


def _registrar_certificado(
    caso_id: str, caso_dir: Path, ap_id: str, pdf: bytes, cert: CertificadoVigencia
) -> ApoderadoVista:
    """Guarda el PDF y su consulta ``manual`` bajo el candado del caso y devuelve el apoderado al día.

    La cédula verificada del expediente manda: el certificado debe ser de ella (si no, 422) y deja
    de usarse una cédula tomada antes de otro certificado. Sin cédula verificada solo el nombre ata
    el certificado al abogado: si no es el suyo, 422; si lo es, la cédula del certificado queda como
    ajuste. El certificado de una cédula no inscrita no trae nombre: sin cédula del expediente ni escrita a
    mano no hay con qué atarlo (422 ``SIN_NOMBRE``); con ella, debe ser la misma. La consulta es de la cédula y la comparten los apoderados que la usan, así que su estado
    no depende del nombre de quien la sube (``estado_apoderados`` coteja el de cada uno); reemplaza a
    la anterior de esa cédula, que es un certificado de la misma persona. La consulta reemplazada y
    su PDF se borran si ya nadie los usa."""
    from tutela2 import server

    # Leer el PDF toma un momento: si entretanto empezó una ejecución, la subida ya no vale.
    if server._job_activo(caso_id) is not None:
        raise HTTPException(409, NO_EDITABLE)
    sha256 = hashlib.sha256(pdf).hexdigest()
    nombre = vigencia.nombre_certificado(ap_id, sha256)
    nueva = f"{registro_apoderados.CERTIFICADOS}/{nombre}"
    reemplazadas: list[ConsultaVigencia] = []
    retiradas: list[str] = []

    def guardar(reg: Registro) -> None:
        ap = _apoderado(reg, ap_id)
        if ap is None:
            raise _NoEncontrado(ap_id)
        verificada = _digitos(ap.cedula)
        if verificada and cert.documento != verificada:
            raise _OtraPersona(ap_id)
        if not cert.inscrito and not verificada:
            # Sin nombre, solo la cédula ata el certificado al abogado: la escrita a mano, si la hay.
            ajuste_previo = reg.ajustes.get(ap_id)
            escrita = _digitos(ajuste_previo.cedula if ajuste_previo is not None else None)
            if not escrita:
                raise _SinNombre(ap_id)
            if cert.documento != escrita:
                raise _OtraPersona(ap_id)
        # Sin cédula verificada, un certificado a otro nombre no se guarda: no es del abogado y no se
        # conservan datos de quien no es parte del caso (ni se pisa la consulta de otro apoderado).
        if cert.inscrito and not verificada and not vigencia.a_nombre_de(cert, ap.nombre):
            raise _OtraPersona(ap_id)
        cedula = cert.documento
        estado = vigencia.clasificar(cert, cedula)
        registro_apoderados.guardar_certificado(caso_dir, nombre, pdf)

        if (anterior := reg.consultas.get(cedula)) is not None:
            reemplazadas.append(anterior)
        reg.consultas[cedula] = ConsultaVigencia(
            estado=estado,
            origen="manual",
            consultado_en=registro_apoderados.ahora(),
            certificado=nueva,
            sha256=sha256,
            datos=cert,
            detalle=DETALLE_MANUAL,
        )
        ajuste = reg.ajustes.get(ap_id) or Ajuste()
        previa = _digitos(ajuste.cedula)
        ajuste = ajuste.model_copy(update={"cedula": None if verificada else cedula})
        if ajuste == Ajuste():
            reg.ajustes.pop(ap_id, None)
        else:
            reg.ajustes[ap_id] = ajuste
        # La cédula del certificado ya tiene resultado: una consulta automática que esperaba no hace falta.
        retiradas.append(cedula)
        # La consulta manual de una cédula que ya nadie usa (un certificado anterior de otra
        # persona) se quita con su PDF: no se guardan datos de quien no es parte del caso.
        if previa and previa != cedula and previa not in _cedulas_en_uso(reg):
            retiradas.append(previa)
            vieja = reg.consultas.get(previa)
            if vieja is not None and vieja.origen == "manual":
                reemplazadas.append(reg.consultas.pop(previa))

    try:
        reg = registro_apoderados.actualizar(caso_dir, guardar)
    except _NoEncontrado:
        raise HTTPException(404, NO_ENCONTRADO) from None
    except _OtraPersona:
        raise HTTPException(422, OTRA_PERSONA) from None
    except _SinNombre:
        raise HTTPException(422, SIN_NOMBRE) from None
    except registro_apoderados.RegistroInvalido as e:
        raise HTTPException(500, str(e)) from None
    except Exception:
        registro_apoderados.borrar_certificados_sin_uso(caso_dir, [nueva])
        raise
    if reg is None:
        raise HTTPException(404, NO_ENCONTRADO)
    registro_apoderados.borrar_certificados_sin_uso(caso_dir, [c.certificado for c in reemplazadas if c.certificado])
    retirar_de_la_cola(caso_dir, retiradas)
    ev = next((e for e in _evaluar_todos(reg, caso_dir) if e.apoderado.id == ap_id), None)
    if ev is None:
        raise HTTPException(404, NO_ENCONTRADO)
    log.info("Certificado de vigencia subido para el apoderado %s de %s: %s", ap_id, caso_id, ev.vigencia)
    return _vista(ev, reg, _documentos(caso_dir), caso_id)


@router.put(
    "/api/casos/{caso_id}/apoderados/{ap_id}/certificado",
    response_model=ApoderadoVista,
    responses={
        404: {"description": "Caso o apoderado no encontrado."},
        409: {"description": "El caso no está esperando la decisión."},
        413: {"description": "El archivo pasa de 2 MiB."},
        422: {
            "description": "No es un PDF, no se pudo leer el certificado, es de otra persona o no trae nombre "
            "(cédula no inscrita) y el abogado no tiene cédula."
        },
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
async def subir_certificado(caso_id: str, ap_id: str, archivo: UploadFile = File(...)) -> ApoderadoVista:
    caso_dir = await run_in_threadpool(_preparar_subida, caso_id, ap_id)
    pdf = await archivo.read(MAX_BYTES_CERTIFICADO + 1)
    if len(pdf) > MAX_BYTES_CERTIFICADO:
        raise HTTPException(413, MUY_GRANDE)
    if not pdf.startswith(b"%PDF-"):
        raise HTTPException(422, NO_ES_PDF)
    cert = await run_in_threadpool(vigencia.leer_certificado, pdf)
    if cert is None or not cert.documento:
        log.info("Certificado de vigencia ilegible para el apoderado %s de %s", ap_id, caso_id)
        raise HTTPException(422, ILEGIBLE)
    return await run_in_threadpool(_registrar_certificado, caso_id, caso_dir, ap_id, pdf, cert)


@router.get(
    "/api/casos/{caso_id}/apoderados/{ap_id}/certificado",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"description": "Caso, apoderado o certificado no encontrado."},
        500: {"description": "El registro de apoderados del caso está dañado."},
    },
)
def descargar_certificado(caso_id: str, ap_id: str) -> FileResponse:
    from tutela2 import server

    caso_dir = server._dir_caso(caso_id)
    try:
        reg = registro_apoderados.leer(caso_dir)
    except registro_apoderados.RegistroInvalido as e:
        raise HTTPException(500, str(e)) from None
    ap = _apoderado(reg, ap_id)
    if ap is None:
        raise HTTPException(404, NO_ENCONTRADO)
    consulta = estado_apoderados.evaluar(ap, reg).consulta
    ruta = None
    if consulta is not None and consulta.certificado:
        ruta = registro_apoderados.ruta_certificado(caso_dir, consulta.certificado)
    if ruta is None:
        raise HTTPException(404, SIN_CERTIFICADO)
    return FileResponse(
        ruta,
        media_type="application/pdf",
        filename=f"certificado-vigencia-{vigencia.id_en_archivo(ap.id)}.pdf",
        content_disposition_type="inline",
        headers=_CABECERAS_PDF,
    )
