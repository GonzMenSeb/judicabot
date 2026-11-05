from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import get_args

from .clasificar import EVIDENCIA_SIN_ROL, EVIDENCIA_SIN_TEXTO, texto_cabecera
from .config import Config
from .jev import ErrorJev, JevClient, RespuestaJev, descripcion_error, llamada_fallida, llamada_ia
from .models import Doc, Rol

ROLES_JEV: tuple[Rol, ...] = tuple(r for r in get_args(Rol) if r not in ("producto_despacho", "otro")) + ("otro",)
ROLES_UNICOS: tuple[Rol, ...] = ("fallo_a_quo", "acta_reparto_2a")
EVIDENCIA_JEV = "El código no halló rasgos del documento; el rol lo propone Jev."

INSTRUCCIONES_ROL = (
    "¿Qué papel cumple este documento dentro de un expediente de acción de tutela? "
    "El estado trae 'Nombre del archivo:' y un fragmento inicial del documento. "
    "Elige el rol que mejor lo describe teniendo en cuenta ambos: cuando el contenido sea claro, "
    "prima sobre el nombre del archivo; cuando el fragmento sea parcial, ambiguo o tenga ruido de "
    "lectura, apóyate en 'Nombre del archivo:' para desambiguar o completar. Si ni por su contenido "
    "ni por el nombre del archivo encaja con claridad en un rol, elige 'otro'."
)

DESCRIPCIONES_ROL: dict[str, str] = {
    "acta_reparto_1a": "Acta individual de reparto de la tutela en primera instancia: formato de la Rama Judicial con radicación, clase de proceso y despacho al que se repartió.",
    "acta_reparto_2a": "Acta individual de reparto de la impugnación de una tutela, que asigna el expediente al juzgado que decidirá la segunda instancia.",
    "escrito_tutela": "Escrito con el que el accionante presenta la acción de tutela ante el juez: hechos, pretensiones y solicitud de amparo.",
    "auto_admisorio": "Auto del juzgado que admite la tutela, avoca su conocimiento y la pone en trámite.",
    "auto_vinculacion": "Auto del juzgado que ordena vincular al trámite de la tutela a otras entidades o personas.",
    "contestacion": "Respuesta o informe que la accionada o una vinculada presenta al juzgado frente a la tutela: contestación o descargos.",
    "fallo_a_quo": "Sentencia de primera instancia de la tutela, con antecedentes, consideraciones y una parte RESUELVE en la que el juez decide.",
    "impugnacion": "Escrito o correo con que una parte impugna o apela el fallo de primera instancia de la tutela.",
    "auto_concede_impugnacion": "Auto breve del juzgado de primera instancia que concede la impugnación y remite el expediente al superior.",
    "notificacion": "Constancia o correo del juzgado que notifica o comunica una providencia a las partes.",
    "correo": "Mensaje de correo electrónico que no es una notificación, una impugnación ni una contestación.",
    "memorial": "Escrito breve de una parte dirigido al juzgado durante el trámite, titulado o nombrado memorial, que no es la tutela, la contestación ni la impugnación.",
    "indice": "Índice del expediente digital o electrónico: lista de los documentos que lo componen.",
    "anexo": "Documento aportado como prueba o soporte, como una cédula, un poder, una historia clínica o un certificado, que no es un escrito del proceso.",
    "otro": "Ninguno de los anteriores, o no se puede determinar ni por su contenido ni por el nombre del archivo.",
}


@dataclass
class OpinionRol:
    doc_id: str
    rol: Rol
    confianza: float
    probabilidades: dict[str, float]
    llamada: dict


def pregunta_rol(invertir: bool = False) -> dict[str, dict]:
    roles = ROLES_JEV[::-1] if invertir else ROLES_JEV
    return {
        "rol": {
            "type": "choice",
            "instructions": INSTRUCCIONES_ROL,
            "criteria": {r: DESCRIPCIONES_ROL[r] for r in roles},
        }
    }


def estado_rol(doc: Doc, max_chars: int) -> str | None:
    cabecera = texto_cabecera(doc)[:max_chars]
    if not cabecera.strip():
        return None
    return f"Nombre del archivo: {doc.nombre}\n\n{cabecera}"


def _numero(valor: object) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _probabilidad(valor: object) -> bool:
    return _numero(valor) and 0 <= valor <= 1


def _leer(doc: Doc, llamada: dict, resp: RespuestaJev) -> OpinionRol | str:
    prefijo = f"{doc.doc_id} {doc.nombre}"
    r = resp.respuestas.get("rol")
    if not isinstance(r, dict):
        return f"{prefijo}: Jev no respondió la pregunta de rol; se ignora."
    etiqueta = r.get("choice")
    if etiqueta not in ROLES_JEV:
        return f"{prefijo}: Jev propuso el rol {etiqueta!r}, que no está en el catálogo; se ignora."
    confianza = r.get("confidence")
    if not _numero(confianza) or not 0 <= confianza <= 1:
        return f"{prefijo}: Jev no dio una confianza válida para el rol {etiqueta!r}; se ignora."
    crudas = r.get("probabilities")
    probabilidades = {str(k): float(v) for k, v in crudas.items() if _probabilidad(v)} if isinstance(crudas, dict) else {}
    return OpinionRol(
        doc_id=doc.doc_id,
        rol=etiqueta,
        confianza=float(confianza),
        probabilidades=probabilidades,
        llamada=llamada,
    )


def segunda_opinion(
    docs: list[Doc],
    cliente: JevClient,
    cfg: Config,
    invertir: bool = False,
    llamadas: list[dict] | None = None,
) -> tuple[list[OpinionRol], list[str]]:
    preguntas = pregunta_rol(invertir)
    pendientes = [(d, e) for d in docs if (e := estado_rol(d, cfg.jev.max_chars_cabecera)) is not None]
    if not pendientes:
        return [], []
    detenido = threading.Event()

    def consultar(par: tuple[Doc, str]) -> tuple[OpinionRol | str | ErrorJev | None, dict | None]:
        doc, estado = par
        if detenido.is_set():
            return None, None
        try:
            resp = cliente.preguntar(estado, preguntas, cfg.jev.modelo)
        except Exception as e:
            detenido.set()
            error = e if isinstance(e, ErrorJev) else ErrorJev(descripcion_error(e))
            enviada = isinstance(e, ErrorJev) and e.enviada
            return error, llamada_fallida("roles", estado, preguntas, cfg.jev.modelo, e) if enviada else None
        llamada = llamada_ia("roles", estado, preguntas, resp, modelo_pedido=cfg.jev.modelo)
        return _leer(doc, llamada, resp), llamada

    with ThreadPoolExecutor(max_workers=max(1, cfg.jev.concurrencia)) as pool:
        resultados = list(pool.map(consultar, pendientes))

    opiniones: list[OpinionRol] = []
    alertas: list[str] = []
    errores: list[ErrorJev] = []
    sin_opinion = 0
    for r, llamada in resultados:
        if llamadas is not None and llamada is not None:
            llamadas.append(llamada)
        if isinstance(r, OpinionRol):
            opiniones.append(r)
        elif isinstance(r, str):
            alertas.append(r)
        else:
            sin_opinion += 1
            if r is not None:
                errores.append(r)
    if sin_opinion:
        detalle = f" ({errores[0]})" if errores else ""
        alertas.append(
            f"Jev no respondió{detalle}; {sin_opinion} de {len(pendientes)} documentos quedaron sin segunda opinión."
        )
    return opiniones, alertas


def rellenable(doc: Doc, opinion: OpinionRol, docs: list[Doc]) -> bool:
    return (
        doc.rol == "otro"
        and doc.evidencia in (EVIDENCIA_SIN_TEXTO, EVIDENCIA_SIN_ROL)
        and doc.rol_origen == "contenido"
        and opinion.rol != "otro"
        and not (opinion.rol in ROLES_UNICOS and any(d is not doc and d.rol == opinion.rol for d in docs))
    )


def aplicar(docs: list[Doc], opiniones: list[OpinionRol], cfg: Config) -> list[str]:
    if cfg.jev.modo == "apagado":
        return []
    por_id = {d.doc_id: d for d in docs}
    alertas: list[str] = []
    for op in opiniones:
        doc = por_id.get(op.doc_id)
        if doc is None:
            continue
        doc.jev_rol = op.rol
        doc.jev_confianza = op.confianza
        doc.jev_umbral = cfg.jev.umbral_confianza
        doc.jev_probabilidades = dict(op.probabilidades)
        if op.confianza < cfg.jev.umbral_confianza:
            continue
        if cfg.jev.modo == "relleno" and rellenable(doc, op, docs):
            doc.rol, doc.rol_origen = op.rol, "jev"
            doc.evidencia = EVIDENCIA_JEV
        elif op.rol != doc.rol:
            alertas.append(
                f"{doc.doc_id} {doc.nombre}: Jev sugiere el rol {op.rol} (confianza {op.confianza:.2f}) "
                f"y el documento quedó como {doc.rol}; revisar."
            )
    return alertas
