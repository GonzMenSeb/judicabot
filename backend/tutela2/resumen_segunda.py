"""Datos propios de la segunda instancia que la lista de casos usa para filtrar (CasoResumen.segunda).

datos(estado, resumen) arma, a partir del estado de api.estado, un dict con la forma de esquemas.DatosSegunda.
Solo lee: tolera resumen == {} y cualquier clave ausente, None o de tipo inesperado (en ese caso el campo queda
None, o [] en derechos). Cada Literal se valida antes de emitirse para que un dato corrupto nunca haga fallar la
validación de CasoResumen y, con ella, toda la lista.

Fuentes (todas dentro de resumen):
  decision_a_quo   metadatos.decision_a_quo (o metadatos.resultado_a_quo si aquella está en blanco), texto libre
                   del a quo clasificado con clasificar_sentido; si no clasifica, la respuesta sentido_fallo de
                   jev_metadatos cuando su confianza alcanza el umbral que ese bloque trae; si hay texto que no
                   clasifica ni la respuesta de Jev es firme, "otro"; sin texto ni respuesta firme, None
  impugnante       "varios" si metadatos.impugnantes trae más de uno; si no, metadatos.impugnante_rol
  resultado,       decision.resultado y decision.sustitutiva, solo si decision.accion == "decidir"
  sustitutiva
  derechos         metadatos.derechos_invocados, sin espacios sobrantes ni repetidos (sin distinguir mayúsculas)
  pruebas_nuevas   bool(apertura.pruebas_nuevas_2a) si hay apertura; si no, None
  n_citas_revisar  citas con estado "alerta" o "rechazada", solo mientras el caso espera la decisión (0 si no hay)
  jev_discrepa     alguna comparación de jev_metadatos.coincide es False, solo mientras espera la decisión
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, get_args

from tutela2.clasificar import plano
from tutela2.config import JevConfig
from tutela2.jev_metadatos import ROLES_IMPUGNANTE, SENTIDOS, firme
from tutela2.models import ResultadoDecision, SustitutivaDecision

_RESULTADOS = frozenset(get_args(ResultadoDecision))
_SUSTITUTIVAS = frozenset(get_args(SustitutivaDecision))
_ROLES = frozenset(ROLES_IMPUGNANTE)
_ESTADOS_CITA_A_REVISAR = frozenset({"alerta", "rechazada"})

# Raíces con forma de verbo, sobre texto sin tildes y en minúscula. No se reutiliza lint._SUSTITUTIVA: allí "ampar"
# también está en "negó el amparo". "neg" a secas pegaría en "negligencia", "tutel" en el sustantivo "tutela" y "ampar"
# en el sustantivo "amparo"; como plano() quita la tilde de "amparó", _llano() la protege antes para distinguirlo.
# Las negaciones delante del verbo ("no concedió el amparo") y los verbos que rechazan ("desestimó el amparo") niegan.
_NO_ANTES = r"(?<![a-z0-9])"
_VERBO_AMPARAR = r"(?:ampar(?!os?\b)|tutel(?!as?\b)|conced|acced)"
_PATRONES_SENTIDO = tuple(
    (etiqueta, re.compile(_NO_ANTES + patron))
    for etiqueta, patron in (
        ("carencia_actual_de_objeto", r"declar\w*\b.*?\b(?:carencia|hecho superado|dano consumado|situacion sobreviniente)"),
        ("improcedente", r"(?:declar\w*\b.*?\bimprocedente|improcedencia|improcedente\b)"),
        (
            "niega",
            r"(?:neg(?:ar|ara|aria|aran|ando|aron|ada|adas|ado|ados|ase|ue|uen|o)\b|nieg|deneg"
            rf"|no\s+(?:\w+\s+){{0,2}}?{_VERBO_AMPARAR}"
            rf"|abstuv\w*\s+de\s+{_VERBO_AMPARAR}"
            r"|(?:desestim|rechaz)\w*\s+(?:\w+\s+){0,3}?(?:amparo|tutela|pretension|proteccion))"
        ),
        ("ampara", r"(?:ampar(?!os?\b)|tutel(?!as?\b)|conced)"),
    )
)


def _llano(texto: str) -> str:
    """Texto en minúscula, sin tildes y con espacios simples; "amparó" (verbo) queda distinto de "amparo" (sustantivo)."""
    texto = re.sub(r"(?i)ampar\u00f3", "amparado", unicodedata.normalize("NFC", texto))
    return " ".join(plano(texto).split())


def clasificar_sentido(texto: str) -> str | None:
    """Sentido de una decisión del a quo en texto libre, o None si ninguna raíz coincide.

    Primero se busca el verbo inicial; si el texto no empieza con ninguno, se busca en todo el texto. En ambos
    casos rige el mismo orden: carencia, improcedente, niega, ampara.
    """
    llano = _llano(texto)
    inicio = re.sub(r"^[^a-z0-9]+", "", llano)
    for etiqueta, patron in _PATRONES_SENTIDO:
        if patron.match(inicio):
            return etiqueta
    for etiqueta, patron in _PATRONES_SENTIDO:
        if patron.search(llano):
            return etiqueta
    return None


def _dict(valor: Any) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _sentido_de_jev(jev: dict[str, Any]) -> str | None:
    pregunta = _dict(_dict(jev.get("preguntas")).get("sentido_fallo"))
    etiqueta, confianza = pregunta.get("choice"), pregunta.get("confidence")
    if etiqueta not in SENTIDOS or not _numero(confianza):
        return None
    umbral = jev.get("umbral")
    umbral = float(umbral) if _numero(umbral) else JevConfig().umbral_confianza
    return etiqueta if firme((etiqueta, float(confianza)), umbral) else None


def _decision_a_quo(metadatos: dict[str, Any], jev: dict[str, Any]) -> str | None:
    texto = next(
        (t.strip() for t in (metadatos.get("decision_a_quo"), metadatos.get("resultado_a_quo")) if isinstance(t, str) and t.strip()),
        "",
    )
    sentido = clasificar_sentido(texto) if texto else None
    if sentido is None:
        sentido = _sentido_de_jev(jev)
    if sentido is None and texto:
        sentido = "otro"
    return sentido


def _impugnante(metadatos: dict[str, Any]) -> str | None:
    impugnantes = metadatos.get("impugnantes")
    if isinstance(impugnantes, list) and sum(1 for i in impugnantes if isinstance(i, str) and i.strip()) > 1:
        return "varios"
    rol = metadatos.get("impugnante_rol")
    return rol if isinstance(rol, str) and rol in _ROLES else None


def _derechos(metadatos: dict[str, Any]) -> list[str]:
    crudos = metadatos.get("derechos_invocados")
    vistos: set[str] = set()
    derechos: list[str] = []
    for derecho in crudos if isinstance(crudos, list) else []:
        limpio = " ".join(derecho.split()) if isinstance(derecho, str) else ""
        if limpio and limpio.casefold() not in vistos:
            vistos.add(limpio.casefold())
            derechos.append(limpio)
    return derechos


def _n_citas_a_revisar(citas: Any) -> int:
    return sum(1 for c in citas if isinstance(c, dict) and c.get("estado") in _ESTADOS_CITA_A_REVISAR) if isinstance(citas, list) else 0


def _jev_discrepa(jev: dict[str, Any]) -> bool:
    return any(v is False for v in _dict(jev.get("coincide")).values())


def datos(estado: str | None, resumen: dict[str, Any] | None) -> dict[str, Any]:
    resumen = _dict(resumen)
    metadatos, jev = _dict(resumen.get("metadatos")), _dict(resumen.get("jev_metadatos"))
    decision, apertura = _dict(resumen.get("decision")), resumen.get("apertura")
    decidida = decision.get("accion") == "decidir"
    resultado, sustitutiva = decision.get("resultado"), decision.get("sustitutiva")
    esperando = estado == "esperando_decision"
    return {
        "decision_a_quo": _decision_a_quo(metadatos, jev),
        "impugnante": _impugnante(metadatos),
        "resultado": resultado if decidida and isinstance(resultado, str) and resultado in _RESULTADOS else None,
        "sustitutiva": sustitutiva if decidida and isinstance(sustitutiva, str) and sustitutiva in _SUSTITUTIVAS else None,
        "derechos": _derechos(metadatos),
        "pruebas_nuevas": bool(apertura.get("pruebas_nuevas_2a")) if isinstance(apertura, dict) else None,
        "n_citas_revisar": _n_citas_a_revisar(resumen.get("citas")) if esperando else None,
        "jev_discrepa": _jev_discrepa(jev) if esperando else None,
    }
