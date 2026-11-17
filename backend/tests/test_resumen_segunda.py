from __future__ import annotations

from typing import Any, get_args

import pytest

from tutela2 import jev_metadatos, resumen_caso
from tutela2.api import _resumen
from tutela2.config import JevConfig
from tutela2.esquemas import CasoResumen, DatosSegunda
from tutela2.models import Decision, ResultadoDecision, SustitutivaDecision
from tutela2.resumen_segunda import clasificar_sentido, datos

CLAVES = {
    "decision_a_quo", "impugnante", "resultado", "sustitutiva", "derechos", "pruebas_nuevas", "n_citas_revisar",
    "jev_discrepa",
}
ESTADOS = ("sin_iniciar", "incompleto", "revision", "esperando_decision", "terminado", "error")
UMBRAL = JevConfig().umbral_confianza


def jev(sentido: str | None = "ampara", confianza: float = 0.95, **extra: Any) -> dict[str, Any]:
    preguntas = {"sentido_fallo": {"choice": sentido, "confidence": confianza}} if sentido else {}
    return {"modelo": "jev-test", "umbral": UMBRAL, "preguntas": preguntas, "coincide": {}, **extra}


def con_meta(**metadatos: Any) -> dict[str, Any]:
    return {"metadatos": metadatos}


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("negó el amparo solicitado por la accionante", "niega"),
        ("NEGAR la tutela", "niega"),
        ("Negó El Ampáro", "niega"),
        ("denegó la protección invocada", "niega"),
        ("niega las pretensiones", "niega"),
        ("declarar improcedente la acción de tutela", "improcedente"),
        ("declaró improcedente la acción de tutela por subsidiariedad", "improcedente"),
        ("DECLARÓ IMPROCEDENTE el amparo", "improcedente"),
        ("declaró la carencia actual de objeto por hecho superado", "carencia_actual_de_objeto"),
        ("declarar la CARENCIA ACTUAL DE OBJETO", "carencia_actual_de_objeto"),
        ("amparó los derechos fundamentales a la salud y al mínimo vital", "ampara"),
        ("concedió la protección solicitada", "ampara"),
        ("tuteló el derecho de petición", "ampara"),
        ("TUTELÓ los derechos de la accionante", "ampara"),
        ("amparó parcialmente y negó lo demás", "ampara"),
        ("negó el amparo y declaró improcedente la solicitud de reembolso", "niega"),
        ("  «Negó» el amparo", "niega"),
        # el verbo inicial manda sobre lo que aparezca después, en el orden carencia, improcedente, niega, ampara
        ("declaró la carencia actual de objeto y negó lo demás", "carencia_actual_de_objeto"),
        ("declaró improcedente la acción y negó el amparo", "improcedente"),
        # «declar… carencia» no tiene tope de palabras entre medias: gana a «declar… improcedente»
        ("declaró improcedente la acción de tutela por carencia actual de objeto", "carencia_actual_de_objeto"),
        ("declaró la acción de tutela, presentada por la accionante contra la entidad, improcedente por carencia actual de objeto", "carencia_actual_de_objeto"),
        ("el juzgado declaró improcedente la acción de tutela por carencia actual de objeto", "carencia_actual_de_objeto"),
        ("declaró la acción de tutela promovida por la señora Marta contra la entidad accionada improcedente", "improcedente"),
        # sin verbo al inicio se busca en todo el texto, en el mismo orden
        ("el juzgado negó la tutela de la accionante", "niega"),
        ("mediante providencia el despacho amparó el derecho a la salud", "ampara"),
        ("el juzgado declaró improcedente el amparo", "improcedente"),
        ("el juez declaró la carencia actual de objeto", "carencia_actual_de_objeto"),
        ("en lo demás negó el amparo y concedió un término", "niega"),
        # negaciones y verbos que rechazan: niegan aunque lleven raíces de ampara
        ("no tutelar los derechos", "niega"),
        ("NO TUTELAR", "niega"),
        ("no amparó los derechos", "niega"),
        ("no concedió el amparo", "niega"),
        ("no accedió al amparo", "niega"),
        ("se abstuvo de conceder el amparo", "niega"),
        ("desestimó el amparo", "niega"),
        ("rechazó el amparo", "niega"),
        ("el juzgado decidió no amparar los derechos", "niega"),
        ("el despacho no tuteló el derecho invocado", "niega"),
        # el sustantivo «amparo» no ampara; el verbo «amparó» (con tilde) sí
        ("AMPARÓ el derecho a la salud", "ampara"),
        ("el juzgado amparó los derechos", "ampara"),
        ("consideró improcedente el amparo", "improcedente"),
        # carencia e improcedencia sin «declar…» pegado a la palabra clave
        ("declaró la existencia de un hecho superado", "carencia_actual_de_objeto"),
        ("declaró la configuración de un daño consumado", "carencia_actual_de_objeto"),
        ("declaró una situación sobreviniente", "carencia_actual_de_objeto"),
        ("declaró improcedente la acción por hecho superado", "carencia_actual_de_objeto"),
        ("rechazó por improcedente la acción", "improcedente"),
        ("declaró la improcedencia de la acción", "improcedente"),
        ("improcedente la acción de tutela", "improcedente"),
        # nada que clasificar
        ("remitió el expediente a la Corte Constitucional", None),
        ("fijó fecha para audiencia de pruebas", None),
        ("negligencia del despacho en la notificación", None),
        ("rechazó el recurso por extemporáneo", None),
        ("", None),
        ("   ", None),
    ],
)
def test_clasificar_sentido_en_texto_libre(texto, esperado):
    assert clasificar_sentido(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "trasladó la acción de tutela al juez competente",
        "ordenó notificar a las partes sobre la acción de tutelas pendientes",
        "tramitó el negocio jurídico",
        "se pronunció sobre el amparo constitucional",
        "no procede la tutela de la accionante",
    ],
)
def test_el_sustantivo_tutela_y_las_raices_que_se_le_parecen_no_clasifican(texto):
    assert clasificar_sentido(texto) is None
    assert datos("revision", con_meta(decision_a_quo=texto))["decision_a_quo"] == "otro"


def test_negar_el_amparo_no_se_confunde_con_ampararlo():
    assert datos("terminado", con_meta(decision_a_quo="negó el amparo"))["decision_a_quo"] == "niega"
    assert datos("terminado", con_meta(decision_a_quo="amparó"))["decision_a_quo"] == "ampara"


def test_la_decision_a_quo_usa_resultado_a_quo_solo_si_la_clausula_esta_en_blanco():
    assert datos("revision", con_meta(decision_a_quo="", resultado_a_quo="declaró improcedente la acción"))["decision_a_quo"] == "improcedente"
    assert datos("revision", con_meta(decision_a_quo=None, resultado_a_quo="amparó el derecho"))["decision_a_quo"] == "ampara"
    assert datos("revision", con_meta(decision_a_quo="  ", resultado_a_quo="negó el amparo"))["decision_a_quo"] == "niega"
    mezcla = con_meta(decision_a_quo="negó el amparo", resultado_a_quo="amparó el derecho")
    assert datos("revision", mezcla)["decision_a_quo"] == "niega"


def test_texto_que_no_clasifica_es_otro():
    assert datos("revision", con_meta(decision_a_quo="remitió el expediente"))["decision_a_quo"] == "otro"


# Flujo de decision_a_quo: texto, respuesta de Jev y valor final.
@pytest.mark.parametrize(
    "metadatos, jev_md, esperado",
    [
        # el texto que clasifica gana, aunque Jev sea firme y distinto
        ({"decision_a_quo": "negó el amparo"}, jev("ampara", 0.99), "niega"),
        # texto que no clasifica y Jev firme: gana Jev
        ({"decision_a_quo": "remitió el expediente"}, jev("improcedente", 0.95), "improcedente"),
        # texto que no clasifica y Jev débil: otro
        ({"decision_a_quo": "remitió el expediente"}, jev("improcedente", 0.5), "otro"),
        # sin texto y Jev firme: gana Jev
        ({}, jev("carencia_actual_de_objeto", 0.93), "carencia_actual_de_objeto"),
        ({"decision_a_quo": "  "}, jev("niega", 0.9), "niega"),
        # sin texto y Jev débil o ausente: None
        ({}, jev("ampara", 0.89), None),
        ({}, None, None),
        ({}, {}, None),
        ({"decision_a_quo": None}, jev(None), None),
        # Jev dice "otro" con firmeza: es una respuesta válida
        ({}, jev("otro", 0.97), "otro"),
    ],
)
def test_decision_a_quo_texto_jev_y_valor_final(metadatos, jev_md, esperado):
    resumen = {"metadatos": metadatos, "jev_metadatos": jev_md}
    assert datos("revision", resumen)["decision_a_quo"] == esperado


@pytest.mark.parametrize(
    "confianza, esperado",
    [(0.0, None), (UMBRAL - 0.001, None), (UMBRAL, "niega"), (UMBRAL + 0.001, "niega"), (1, "niega"), (1.0, "niega")],
)
def test_el_respaldo_de_jev_exige_la_confianza_del_umbral(confianza, esperado):
    assert datos("revision", {"jev_metadatos": jev("niega", confianza)})["decision_a_quo"] == esperado


def test_el_umbral_es_el_que_trae_el_bloque_de_jev_y_si_falta_el_de_la_configuracion():
    assert datos("revision", {"jev_metadatos": jev("niega", 0.7, umbral=0.6)})["decision_a_quo"] == "niega"
    assert datos("revision", {"jev_metadatos": jev("niega", 0.7, umbral=0.8)})["decision_a_quo"] is None
    sin_umbral = {k: v for k, v in jev("niega", 0.95).items() if k != "umbral"}
    assert datos("revision", {"jev_metadatos": sin_umbral})["decision_a_quo"] == "niega"
    sin_umbral["preguntas"]["sentido_fallo"]["confidence"] = UMBRAL - 0.01
    assert datos("revision", {"jev_metadatos": sin_umbral})["decision_a_quo"] is None


@pytest.mark.parametrize(
    "pregunta",
    [
        {"choice": "inventado", "confidence": 0.99},
        {"choice": "niega", "confidence": "0.99"},
        {"choice": "niega", "confidence": True},
        {"choice": "niega"},
        {"confidence": 0.99},
        {"choice": ["niega"], "confidence": 0.99},
        None,
        "niega",
    ],
)
def test_una_respuesta_de_jev_invalida_se_ignora(pregunta):
    resumen = {"jev_metadatos": {"umbral": UMBRAL, "preguntas": {"sentido_fallo": pregunta}}}
    assert datos("revision", resumen)["decision_a_quo"] is None


def test_solo_cuenta_la_pregunta_sentido_fallo_de_jev():
    resumen = {"jev_metadatos": {"umbral": UMBRAL, "preguntas": {"sentido_clausula": {"choice": "niega", "confidence": 0.99}}}}
    assert datos("revision", resumen)["decision_a_quo"] is None


@pytest.mark.parametrize(
    "metadatos, esperado",
    [
        ({"impugnantes": ["la señora A", "el señor B"], "impugnante_rol": "accionante"}, "varios"),
        ({"impugnantes": ["uno", "dos", "tres"]}, "varios"),
        ({"impugnantes": ["la señora A"], "impugnante_rol": "accionada"}, "accionada"),
        ({"impugnantes": [], "impugnante_rol": "vinculada"}, "vinculada"),
        ({"impugnante_rol": "otro"}, "otro"),
        ({"impugnante_rol": "accionante"}, "accionante"),
        ({"impugnantes": ["la señora A", "  ", ""], "impugnante_rol": "accionante"}, "accionante"),
        ({"impugnantes": ["la señora A", 7], "impugnante_rol": "accionada"}, "accionada"),
        ({"impugnante_rol": "inventado"}, None),
        ({"impugnante_rol": ""}, None),
        ({"impugnante_rol": None}, None),
        ({"impugnantes": "la señora A y el señor B"}, None),
        ({}, None),
    ],
)
def test_impugnante_es_varios_o_el_rol(metadatos, esperado):
    assert datos("revision", con_meta(**metadatos))["impugnante"] == esperado


@pytest.mark.parametrize("estado", ESTADOS)
@pytest.mark.parametrize("accion", ["decidir", "rehacer_apertura", "rehacer_consideraciones", None])
def test_resultado_y_sustitutiva_solo_si_la_accion_es_decidir(estado, accion):
    decision = {"resultado": "REVOCAR", "sustitutiva": "AMPARAR"} | ({"accion": accion} if accion else {})
    salida = datos(estado, {"decision": decision})
    esperado = ("REVOCAR", "AMPARAR") if accion == "decidir" else (None, None)
    assert (salida["resultado"], salida["sustitutiva"]) == esperado


@pytest.mark.parametrize(
    "decision",
    [
        {"accion": "decidir", "resultado": "ANULAR", "sustitutiva": "inventada"},
        {"accion": "decidir", "resultado": ["REVOCAR"], "sustitutiva": 3},
        {"accion": "decidir", "resultado": None, "sustitutiva": None},
        {"accion": "decidir"},
    ],
)
def test_resultado_y_sustitutiva_fuera_del_catalogo_quedan_en_none(decision):
    salida = datos("terminado", {"decision": decision})
    assert (salida["resultado"], salida["sustitutiva"]) == (None, None)
    DatosSegunda.model_validate(salida)


def test_confirmar_trae_resultado_sin_sustitutiva():
    salida = datos("terminado", {"decision": {"accion": "decidir", "resultado": "CONFIRMAR"}})
    assert (salida["resultado"], salida["sustitutiva"]) == ("CONFIRMAR", None)


def test_los_literales_de_la_decision_son_los_del_modelo():
    assert set(get_args(ResultadoDecision)) == {"CONFIRMAR", "REVOCAR", "MODIFICAR"}
    assert set(get_args(SustitutivaDecision)) >= {"AMPARAR", "NEGAR", "IMPROCEDENTE"}
    assert Decision.model_fields["resultado"].annotation == ResultadoDecision | None
    assert Decision.model_fields["sustitutiva"].annotation == SustitutivaDecision | None
    assert DatosSegunda.model_fields["resultado"].annotation == ResultadoDecision | None
    assert DatosSegunda.model_fields["sustitutiva"].annotation == SustitutivaDecision | None


def _literal(modelo, campo: str) -> tuple[str, ...]:
    (literal,) = (a for a in get_args(modelo.model_fields[campo].annotation) if a is not type(None))
    return get_args(literal)


def test_los_literales_de_decision_a_quo_e_impugnante_coinciden_con_jev_metadatos():
    assert _literal(DatosSegunda, "decision_a_quo") == jev_metadatos.SENTIDOS
    assert _literal(DatosSegunda, "impugnante") == (*jev_metadatos.ROLES_IMPUGNANTE, "varios")


@pytest.mark.parametrize(
    "apertura, esperado",
    [
        ({"pruebas_nuevas_2a": ["historia clínica de 2026"]}, True),
        ({"pruebas_nuevas_2a": []}, False),
        ({"pruebas_nuevas_2a": None}, False),
        ({}, False),
        (None, None),
        ("no es un dict", None),
    ],
)
@pytest.mark.parametrize("estado", ESTADOS)
def test_pruebas_nuevas_depende_de_que_exista_la_apertura(estado, apertura, esperado):
    resumen = {} if apertura is None else {"apertura": apertura}
    assert datos(estado, resumen)["pruebas_nuevas"] is esperado


CITAS = [
    {"id": "c1", "estado": "ok"},
    {"id": "c2", "estado": "alerta"},
    {"id": "c3", "estado": "rechazada"},
    {"id": "c4", "estado": "rechazada"},
    {"id": "c5"},
    "basura",
]
DISCREPA = {"coincide": {"sentido": True, "rol_impugnante": False}}


@pytest.mark.parametrize("estado", ESTADOS)
def test_citas_por_revisar_y_discrepancia_solo_se_informan_esperando_la_decision(estado):
    salida = datos(estado, {"citas": CITAS, "jev_metadatos": jev(**DISCREPA)})
    if estado == "esperando_decision":
        assert (salida["n_citas_revisar"], salida["jev_discrepa"]) == (3, True)
    else:
        assert (salida["n_citas_revisar"], salida["jev_discrepa"]) == (None, None)


@pytest.mark.parametrize("estado", ["sin_iniciar", "esperando_decision", "terminado"])
def test_estados_con_datos_de_decision_siguen_informando_el_resto(estado):
    resumen = {
        "metadatos": {"decision_a_quo": "amparó", "impugnante_rol": "accionada", "derechos_invocados": ["salud"]},
        "apertura": {"pruebas_nuevas_2a": ["x"]},
        "decision": {"accion": "decidir", "resultado": "REVOCAR", "sustitutiva": "NEGAR"},
    }
    salida = datos(estado, resumen)
    assert (salida["decision_a_quo"], salida["impugnante"], salida["derechos"], salida["pruebas_nuevas"]) == (
        "ampara",
        "accionada",
        ["salud"],
        True,
    )
    assert (salida["resultado"], salida["sustitutiva"]) == ("REVOCAR", "NEGAR")


def test_esperando_la_decision_sin_citas_ni_jev_informa_cero_y_falso():
    for resumen in ({}, {"citas": [], "jev_metadatos": None}, {"citas": None}):
        salida = datos("esperando_decision", resumen)
        assert (salida["n_citas_revisar"], salida["jev_discrepa"]) == (0, False)


@pytest.mark.parametrize(
    "coincide, esperado",
    [
        ({"sentido": True, "rol_impugnante": True}, False),
        ({"sentido": False, "rol_impugnante": True}, True),
        ({"sentido": True, "rol_impugnante": False}, True),
        ({"sentido": False, "rol_impugnante": False}, True),
        ({"sentido": None, "rol_impugnante": None}, False),
        ({"sentido": None, "rol_impugnante": True}, False),
        ({"sentido": 0, "rol_impugnante": ""}, False),
        ({}, False),
        (None, False),
    ],
)
def test_jev_discrepa_solo_si_una_comparacion_es_false(coincide, esperado):
    salida = datos("esperando_decision", {"jev_metadatos": jev(coincide=coincide)})
    assert salida["jev_discrepa"] is esperado


@pytest.mark.parametrize(
    "crudos, esperado",
    [
        (["salud", "debido proceso", "mínimo vital"], ["salud", "debido proceso", "mínimo vital"]),
        (["  salud ", "Salud", "SALUD", "vida"], ["salud", "vida"]),
        (["Debido Proceso", "debido  proceso", "debido proceso"], ["Debido Proceso"]),
        (["petición", "", "  ", None, 3, "Petición"], ["petición"]),
        (["vida", "salud", "vida"], ["vida", "salud"]),
        ([], []),
        (None, []),
        ("salud", []),
    ],
)
def test_derechos_sin_espacios_ni_repetidos_y_en_el_orden_original(crudos, esperado):
    assert datos("revision", con_meta(derechos_invocados=crudos))["derechos"] == esperado


def test_derechos_no_viene_de_las_disposiciones_de_la_decision():
    resumen = {"decision": {"accion": "decidir", "derechos": [{"derecho": "salud", "disposicion": "AMPARA"}]}}
    assert datos("terminado", resumen)["derechos"] == []


VACIOS = {
    "decision_a_quo": None, "impugnante": None, "resultado": None, "sustitutiva": None, "derechos": [],
    "pruebas_nuevas": None, "n_citas_revisar": None, "jev_discrepa": None,
}


@pytest.mark.parametrize("estado", [e for e in ESTADOS if e != "esperando_decision"])
def test_resumen_vacio_da_todo_en_none(estado):
    assert datos(estado, {}) == VACIOS


def test_resumen_vacio_esperando_la_decision():
    assert datos("esperando_decision", {}) == {**VACIOS, "n_citas_revisar": 0, "jev_discrepa": False}


@pytest.mark.parametrize("estado", [*ESTADOS, "corriendo", "inventado", None])
@pytest.mark.parametrize(
    "resumen",
    [
        {},
        None,
        "no es un dict",
        [],
        # la forma que deja api._resumen cuando los valores del grafo aún no existen
        _resumen({}),
        {"metadatos": None, "jev_metadatos": None, "apertura": None, "decision": None, "citas": None, "alertas": None},
        {"metadatos": [], "jev_metadatos": "x", "apertura": 3, "decision": [], "citas": {}},
        {"metadatos": {"decision_a_quo": 5, "resultado_a_quo": [], "impugnantes": None, "derechos_invocados": {}}},
        {"jev_metadatos": {"preguntas": None, "coincide": []}},
        {"jev_metadatos": {"preguntas": {"sentido_fallo": {"choice": "niega", "confidence": float("nan")}}, "umbral": "x"}},
    ],
)
def test_tolera_cualquier_forma_y_siempre_devuelve_los_ocho_campos_validos(estado, resumen):
    salida = datos(estado, resumen)
    assert set(salida) == CLAVES
    DatosSegunda.model_validate(salida)


def test_la_forma_de_datos_es_la_del_esquema():
    assert set(DatosSegunda.model_fields) == CLAVES
    assert set(datos("terminado", {})) == set(DatosSegunda.model_fields)


def test_un_resumen_completo_valida_como_caso_resumen():
    resumen = {
        "metadatos": {
            "decision_a_quo": "amparó los derechos a la salud",
            "impugnantes": ["la señora A"],
            "impugnante_rol": "accionada",
            "derechos_invocados": ["salud", "Salud", "vida"],
        },
        "apertura": {"pruebas_nuevas_2a": []},
        "citas": CITAS,
        "jev_metadatos": jev(**DISCREPA),
    }
    segunda = datos("esperando_decision", resumen)
    assert segunda == {
        "decision_a_quo": "ampara", "impugnante": "accionada", "resultado": None, "sustitutiva": None,
        "derechos": ["salud", "vida"], "pruebas_nuevas": False, "n_citas_revisar": 3, "jev_discrepa": True,
    }
    fila = {
        "id": "caso", "nombre": "Caso", "radicado": None, "accionante": None, "accionadas": [], "juzgado_a_quo": None,
        "estado": "esperando_decision", "etapa": 2, "siguiente_paso": "x", "n_insumos": 0, "n_alertas": 0,
        "job_activo": None, "actualizado": "2026-11-01T00:00:00+00:00", "proceso": "segunda", "segunda": segunda,
    }
    assert CasoResumen.model_validate(fila).segunda == DatosSegunda(**segunda)


def test_campos_desde_estado_incluye_proceso_y_los_datos_de_segunda():
    respuesta = {
        "estado": "esperando_decision",
        "resumen": {"metadatos": {"decision_a_quo": "negó el amparo", "impugnante_rol": "accionante"}, "citas": CITAS},
    }
    campos = resumen_caso.campos_desde_estado(respuesta)
    assert campos["proceso"] == "segunda"
    assert campos["segunda"] == datos("esperando_decision", respuesta["resumen"])
    assert campos["segunda"]["decision_a_quo"] == "niega" and campos["segunda"]["n_citas_revisar"] == 3


@pytest.mark.parametrize("respuesta", [None, "x", {}, {"estado": "inventado", "resumen": {}}, {"estado": "error", "resumen": {}}])
def test_una_respuesta_ilegible_deja_segunda_en_none(respuesta):
    campos = resumen_caso.campos_desde_estado(respuesta)
    assert campos["proceso"] == "segunda" and campos["segunda"] is None


def test_un_error_con_datos_del_grafo_conserva_los_datos_de_segunda():
    resumen = {"metadatos": {"derechos_invocados": ["salud"]}, "decision": {"accion": "decidir", "resultado": "REVOCAR"}}
    campos = resumen_caso.campos_desde_estado({"estado": "error", "resumen": resumen})
    assert campos["segunda"]["derechos"] == ["salud"] and campos["segunda"]["resultado"] == "REVOCAR"
    assert campos["segunda"]["n_citas_revisar"] is None


def test_un_estado_sin_resumen_que_no_es_error_trae_la_forma_completa_vacia():
    campos = resumen_caso.campos_desde_estado({"estado": "sin_iniciar", "resumen": {}})
    assert campos["segunda"] == VACIOS


def test_con_job_borra_lo_que_solo_vale_esperando_la_decision(tmp_path):
    cacheado = {
        "etapa": 2,
        "segunda": datos("esperando_decision", {"citas": CITAS, "metadatos": {"derechos_invocados": ["salud"]}}),
    }
    assert cacheado["segunda"]["n_citas_revisar"] == 3
    corriendo = resumen_caso.con_job(cacheado, "job1", "decidir", tmp_path)
    assert corriendo["estado"] == "corriendo"
    assert corriendo["segunda"] == {**cacheado["segunda"], "n_citas_revisar": None, "jev_discrepa": None}
    assert cacheado["segunda"]["n_citas_revisar"] == 3
    sin_datos = resumen_caso.con_job({"etapa": 0, "segunda": None}, "job1", "nuevo", tmp_path)
    assert sin_datos["segunda"] is None
