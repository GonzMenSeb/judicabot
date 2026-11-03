from __future__ import annotations

from typing import Any

from tutela2 import lint
from tutela2.clasificar import texto_cabecera
from tutela2.config import Config
from tutela2.jev import ErrorJev, JevClient, RespuestaJev, descripcion_error, llamada_fallida, llamada_ia
from tutela2.models import AperturaLLM, Doc, Ingesta

NODO = "metadatos"
SENTIDOS: tuple[str, ...] = ("ampara", "niega", "improcedente", "carencia_actual_de_objeto", "otro")
ROLES_IMPUGNANTE: tuple[str, ...] = ("accionante", "accionada", "vinculada", "otro")

_DESCRIPCION_SENTIDOS = {
    "ampara": "Concede el amparo: la acción de tutela prospera y se protegen derechos fundamentales de la parte accionante.",
    "niega": "Niega el amparo: examina el fondo y concluye que no se vulneró ningún derecho fundamental.",
    "improcedente": "Declara improcedente la acción de tutela, sin decidir de fondo la vulneración alegada.",
    "carencia_actual_de_objeto": "Declara la carencia actual de objeto (hecho superado, daño consumado o situación sobreviniente).",
    "otro": "Ninguna de las anteriores, o no se puede determinar.",
}
_DESCRIPCION_ROLES = {
    "accionante": "Quien presentó la acción de tutela.",
    "accionada": "Entidad o persona contra quien se dirige la acción de tutela.",
    "vinculada": "Entidad o persona que el juez vinculó al trámite sin ser la accionada.",
    "otro": "Ninguna de las anteriores, o no se puede determinar.",
}


def _pregunta(instrucciones: str, opciones: tuple[str, ...], descripciones: dict[str, str]) -> dict:
    return {
        "type": "choice",
        "instructions": instrucciones,
        "criteria": {o: descripciones[o] for o in opciones},
    }


PREGUNTAS = {
    "sentido_fallo": _pregunta(
        "Lee solo el campo fallo_resolutivo, el tramo final de una sentencia de tutela de primera instancia. "
        "¿Qué decide la sentencia sobre la acción de tutela?",
        SENTIDOS,
        _DESCRIPCION_SENTIDOS,
    ),
    "sentido_clausula": _pregunta(
        "Lee solo el campo clausula, que resume en pasado la decisión de una sentencia de tutela de primera "
        "instancia. ¿Qué decisión describe?",
        SENTIDOS,
        _DESCRIPCION_SENTIDOS,
    ),
    "rol_impugnante": _pregunta(
        "Lee el campo escrito_impugnacion y los nombres de accionante, accionadas y vinculadas. ¿En qué calidad "
        "dentro del trámite de tutela actúa quien presenta la impugnación?",
        ROLES_IMPUGNANTE,
        _DESCRIPCION_ROLES,
    ),
}
_OPCIONES = {"sentido_fallo": SENTIDOS, "sentido_clausula": SENTIDOS, "rol_impugnante": ROLES_IMPUGNANTE}
_FUENTE = {
    "sentido_fallo": "fallo_resolutivo",
    "sentido_clausula": "clausula",
    "rol_impugnante": "escrito_impugnacion",
}


def _visibles(ing: Ingesta, rol: str) -> list[Doc]:
    return [d for d in ing.documentos if d.rol == rol and not d.ruido and d.doc_id not in ing.docs_ajenos]


def _cola_del_fallo(ing: Ingesta, limite: int) -> str:
    for d in _visibles(ing, "fallo_a_quo"):
        texto = "\n".join(p.texto for p in d.paginas if p.texto and not p.ruido).strip()
        if texto:
            return texto[max(len(texto) - limite, 0) :]
    return ""


def _cabecera_de_la_impugnacion(ing: Ingesta, limite: int) -> str:
    for d in _visibles(ing, "impugnacion"):
        texto = texto_cabecera(d).strip()[: max(limite, 0)]
        if texto:
            return texto
    return ""


def _estado(ing: Ingesta, ap: AperturaLLM, cfg: Config) -> dict[str, Any]:
    estado: dict[str, Any] = {}
    if fallo := _cola_del_fallo(ing, cfg.jev.max_chars_sentido):
        estado["fallo_resolutivo"] = fallo
    if ap.metadatos.decision_a_quo:
        estado["clausula"] = ap.metadatos.decision_a_quo
    if escrito := _cabecera_de_la_impugnacion(ing, cfg.jev.max_chars_cabecera):
        estado["escrito_impugnacion"] = escrito
        for campo in ("impugnante", "accionante", "accionadas", "vinculadas"):
            if valor := getattr(ing.metadatos, campo) or getattr(ap.metadatos, campo):
                estado[campo] = valor
    return estado


def _confianza_valida(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and 0 <= valor <= 1


def _leer_respuestas(resp: RespuestaJev, preguntas: dict) -> tuple[dict[str, tuple[str, float]], list[str]]:
    leidas: dict[str, tuple[str, float]] = {}
    alertas: list[str] = []
    for id_ in preguntas:
        bruta = resp.respuestas.get(id_)
        bruta = bruta if isinstance(bruta, dict) else {}
        etiqueta, confianza = bruta.get("choice"), bruta.get("confidence")
        if isinstance(etiqueta, str) and etiqueta in _OPCIONES[id_] and _confianza_valida(confianza):
            leidas[id_] = (etiqueta, float(confianza))
        else:
            alertas.append(
                f"{lint.ALERTA}Jev devolvió para {id_} una respuesta fuera del catálogo o sin confianza válida "
                f"({etiqueta!r}); se ignora."
            )
    return leidas, alertas


def _firme(lectura: tuple[str, float] | None, umbral: float) -> bool:
    return lectura is not None and lectura[1] >= umbral


def verificar_apertura(
    ing: Ingesta, ap: AperturaLLM, cliente: JevClient | None, cfg: Config
) -> tuple[list[str], list[dict], dict | None]:
    if cliente is None or cfg.jev.modo == "apagado":
        return [], [], None
    estado = _estado(ing, ap, cfg)
    preguntas = {id_: p for id_, p in PREGUNTAS.items() if _FUENTE[id_] in estado}
    if not preguntas:
        return [], [], None
    try:
        resp = cliente.preguntar(estado, preguntas, cfg.jev.modelo)
    except Exception as e:
        fallida = [llamada_fallida(NODO, estado, preguntas, cfg.jev.modelo, e)] if isinstance(e, ErrorJev) and e.enviada else []
        return [f"{lint.ALERTA}Jev no pudo verificar los metadatos de la apertura ({descripcion_error(e)})."], fallida, None
    bitacora = [llamada_ia(NODO, estado, preguntas, resp, cfg.jev.modelo)]
    leidas, alertas = _leer_respuestas(resp, preguntas)
    umbral = cfg.jev.umbral_confianza

    coincide_sentido = None
    fallo, clausula = leidas.get("sentido_fallo"), leidas.get("sentido_clausula")
    if _firme(fallo, umbral) and _firme(clausula, umbral):
        coincide_sentido = fallo[0] == clausula[0]
        if not coincide_sentido:
            alertas.append(
                f"{lint.ALERTA}Jev lee el sentido del fallo como {fallo[0]!r} ({fallo[1]:.0%}) y la cláusula "
                f"decision_a_quo ({estado['clausula']!r}) como {clausula[0]!r} ({clausula[1]:.0%}); verifique decision_a_quo."
            )

    coincide_rol = None
    rol = leidas.get("rol_impugnante")
    esperado = ap.metadatos.impugnante_rol or ing.metadatos.impugnante_rol
    if esperado and _firme(rol, umbral):
        coincide_rol = rol[0] == esperado
        if not coincide_rol:
            alertas.append(
                f"{lint.ALERTA}Jev lee al impugnante como {rol[0]!r} ({rol[1]:.0%}) y los metadatos registran "
                f"impugnante_rol {esperado!r}; verifique impugnante_rol."
            )

    jev_metadatos = (
        {
            "modelo": resp.modelo,
            "umbral": umbral,
            "preguntas": {id_: {"choice": e, "confidence": c} for id_, (e, c) in leidas.items()},
            "coincide": {"sentido": coincide_sentido, "rol_impugnante": coincide_rol},
        }
        if leidas
        else None
    )
    return alertas, bitacora, jev_metadatos
