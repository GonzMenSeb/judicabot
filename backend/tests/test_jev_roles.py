from __future__ import annotations

import json
import threading
from typing import get_args

import pytest

from tutela2 import clasificar
from tutela2.config import Config, JevConfig
from tutela2.jev import ErrorJev, FakeJev
from tutela2.jev_roles import ROLES_JEV, OpinionRol, estado_rol, pregunta_rol, segunda_opinion
from tutela2.models import Doc, Pagina, Rol

CFG = Config(jev=JevConfig(modo="sombra"))
TEXTO = "Medellín, 9 de febrero de 2027. Señor JUEZ. Texto cualquiera con contenido suficiente para ser legible."


def choice(rol: str, confianza: float = 0.97, probabilidades: dict | None = None) -> dict:
    return {
        "rol": {
            "type": "choice",
            "choice": rol,
            "confidence": confianza,
            "probabilities": probabilidades if probabilidades is not None else {rol: confianza},
        }
    }


def doc_de(nombre: str = "001.pdf", paginas: list[Pagina] | None = None, doc_id: str = "1a-001") -> Doc:
    return Doc(
        doc_id=doc_id,
        ruta=nombre,
        nombre=nombre,
        instancia="1a",
        rol="otro",
        sha256=doc_id,
        paginas=paginas if paginas is not None else [Pagina(n=1, texto=TEXTO)],
    )


def doc_con_texto(doc_id: str = "1a-001", nombre: str = "001.pdf") -> Doc:
    return doc_de(nombre=nombre, doc_id=doc_id)


def _lanza(error: Exception):
    def f(estado, preguntas):
        raise error

    return f


def test_documento_sin_texto_no_genera_peticion():
    doc = doc_de(nombre="scan.pdf", paginas=[Pagina(n=1, texto="", sin_texto=True)])
    fake = FakeJev(choice("otro"))
    ops, alertas = segunda_opinion([doc], fake, CFG)
    assert fake.llamadas == [] and ops == [] and alertas == []


def test_documento_sin_paginas_o_en_blanco_no_genera_peticion():
    fake = FakeJev(choice("otro"))
    sin_paginas = doc_de(nombre="vacio.pdf", paginas=[])
    en_blanco = doc_de(nombre="blanco.pdf", paginas=[Pagina(n=1, texto="  \n\t ")], doc_id="1a-002")
    assert estado_rol(sin_paginas, 1500) is None and estado_rol(en_blanco, 1500) is None
    ops, alertas = segunda_opinion([sin_paginas, en_blanco], fake, CFG)
    assert fake.llamadas == [] and ops == [] and alertas == []


def test_estado_enviado_esta_acotado_y_lleva_el_nombre():
    doc = doc_de(nombre="004Escrito.pdf", paginas=[Pagina(n=1, texto="x" * 9000)])
    estado = estado_rol(doc, 1500)
    assert estado.startswith("Nombre del archivo: 004Escrito.pdf")
    assert estado.count("x") <= 1500


def test_estado_usa_el_texto_de_cabecera_del_documento():
    doc = doc_de(paginas=[Pagina(n=1, texto="primera " * 10), Pagina(n=2, texto="segunda " * 10), Pagina(n=3, texto="tercera " * 10)])
    estado = estado_rol(doc, 5000)
    assert estado == f"Nombre del archivo: 001.pdf\n\n{clasificar.texto_cabecera(doc)}"
    assert "primera" in estado and "segunda" in estado and "tercera" not in estado


def test_peticion_respeta_max_chars_cabecera_de_la_configuracion():
    doc = doc_de(nombre="a.pdf", paginas=[Pagina(n=1, texto="x" * 9000)])
    fake = FakeJev(choice("otro"))
    segunda_opinion([doc], fake, Config(jev=JevConfig(modo="sombra", max_chars_cabecera=100)))
    estado, _ = fake.llamadas[0]
    assert estado.count("x") == 100


def test_etiqueta_fuera_del_catalogo_se_ignora_con_alerta():
    fake = FakeJev({"rol": {"type": "choice", "choice": "inventado", "confidence": 0.99, "probabilidades": {}}})
    ops, alertas = segunda_opinion([doc_con_texto()], fake, CFG)
    assert ops == [] and len(alertas) == 1 and "inventado" in alertas[0]
    assert alertas[0].startswith("1a-001 001.pdf: ")


def test_producto_despacho_no_esta_en_el_catalogo_y_se_ignora():
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(choice("producto_despacho")), CFG)
    assert ops == [] and len(alertas) == 1 and "producto_despacho" in alertas[0]


@pytest.mark.parametrize(
    "respuesta",
    [
        {},
        {"rol": "fallo_a_quo"},
        {"rol": {"type": "choice", "choice": "fallo_a_quo"}},
        {"rol": {"type": "choice", "choice": "fallo_a_quo", "confidence": "alta"}},
        {"rol": {"type": "choice", "choice": "fallo_a_quo", "confidence": True}},
        {"rol": {"type": "choice", "choice": "fallo_a_quo", "confidence": 1.5}},
        {"rol": {"type": "choice", "choice": ["fallo_a_quo"], "confidence": 0.9}},
    ],
)
def test_respuesta_mal_formada_se_ignora_con_alerta_sin_excepcion(respuesta):
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(respuesta), CFG)
    assert ops == [] and len(alertas) == 1 and alertas[0].startswith("1a-001 001.pdf: ")


def test_respuesta_sin_probabilidades_se_acepta_con_dict_vacio():
    respuesta = {"rol": {"type": "choice", "choice": "fallo_a_quo", "confidence": 0.95}}
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(respuesta), CFG)
    assert alertas == [] and ops[0].probabilidades == {}


def test_error_de_jev_produce_una_alerta_y_no_excepcion():
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(_lanza(ErrorJev("429"))), CFG)
    assert ops == [] and len(alertas) == 1
    assert "Jev" in alertas[0] and "429" in alertas[0]


def test_varios_documentos_con_jev_caido_dejan_una_sola_alerta():
    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 6)]
    cfg = Config(jev=JevConfig(modo="sombra", concurrencia=1))
    fake = FakeJev(_lanza(ErrorJev("Jev respondió 401: clave inválida")))
    ops, alertas = segunda_opinion(docs, fake, cfg)
    assert ops == [] and len(alertas) == 1
    assert "401" in alertas[0] and "5 de 5" in alertas[0]
    assert len(fake.llamadas) == 1


def test_un_error_no_descarta_las_opiniones_ya_obtenidas():
    def responder(estado, preguntas):
        if "falla.pdf" in estado:
            raise ErrorJev("529")
        return choice("fallo_a_quo")

    docs = [doc_con_texto("1a-001", "ok.pdf"), doc_con_texto("1a-002", "falla.pdf")]
    cfg = Config(jev=JevConfig(modo="sombra", concurrencia=1))
    ops, alertas = segunda_opinion(docs, FakeJev(responder), cfg)
    assert [o.doc_id for o in ops] == ["1a-001"] and len(alertas) == 1 and "1 de 2" in alertas[0]


def test_opinion_exitosa_lleva_rol_confianza_probabilidades_y_llamada():
    probs = {"fallo_a_quo": 0.93, "otro": 0.07}
    fake = FakeJev(choice("fallo_a_quo", 0.93, probs))
    ops, alertas = segunda_opinion([doc_con_texto()], fake, CFG)
    assert alertas == []
    (op,) = ops
    assert (op.doc_id, op.rol, op.confianza, op.probabilidades) == ("1a-001", "fallo_a_quo", 0.93, probs)
    assert op.llamada["proveedor"] == "jev" and op.llamada["nodo"] == "roles"
    assert op.llamada["prompt_id"] == "jev-roles-v1" and op.llamada["modelo_pedido"] == CFG.jev.modelo
    assert TEXTO not in json.dumps(op.llamada)


def test_opinion_rol_se_construye_en_orden_posicional():
    op = OpinionRol("1a-001", "escrito_tutela", 0.97, {}, {})
    assert (op.doc_id, op.rol, op.confianza, op.probabilidades, op.llamada) == ("1a-001", "escrito_tutela", 0.97, {}, {})


def test_segunda_opinion_envia_la_pregunta_de_rol_y_su_version_invertida():
    fake = FakeJev(choice("otro"))
    segunda_opinion([doc_con_texto()], fake, CFG)
    segunda_opinion([doc_con_texto()], fake, CFG, invertir=True)
    assert fake.llamadas[0][1] == pregunta_rol()
    assert fake.llamadas[1][1] == pregunta_rol(invertir=True)


def test_segunda_opinion_no_depende_del_modo_de_la_configuracion():
    fake = FakeJev(choice("fallo_a_quo"))
    ops, _ = segunda_opinion([doc_con_texto()], fake, Config())
    assert len(ops) == 1


def test_las_opiniones_conservan_el_orden_de_los_documentos():
    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 9)]
    sin_texto = doc_de(nombre="scan.pdf", paginas=[Pagina(n=1, texto="", sin_texto=True)], doc_id="1a-099")
    docs.insert(3, sin_texto)
    ops, alertas = segunda_opinion(docs, FakeJev(choice("memorial")), Config(jev=JevConfig(modo="sombra", concurrencia=4)))
    assert [o.doc_id for o in ops] == [d.doc_id for d in docs if d is not sin_texto] and alertas == []


def test_la_concurrencia_configurada_permite_peticiones_simultaneas():
    barrera = threading.Barrier(3, timeout=5)

    def responder(estado, preguntas):
        barrera.wait()
        return choice("memorial")

    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 4)]
    ops, alertas = segunda_opinion(docs, FakeJev(responder), Config(jev=JevConfig(modo="sombra", concurrencia=3)))
    assert len(ops) == 3 and alertas == []


def test_concurrencia_cero_no_rompe():
    ops, _ = segunda_opinion([doc_con_texto()], FakeJev(choice("memorial")), Config(jev=JevConfig(modo="sombra", concurrencia=0)))
    assert len(ops) == 1


def test_roles_jev_excluye_producto_despacho_y_cubre_el_resto():
    assert "producto_despacho" not in ROLES_JEV
    assert set(ROLES_JEV) == set(get_args(Rol)) - {"producto_despacho"}
    assert ROLES_JEV[-1] == "otro"
    assert len(set(ROLES_JEV)) == len(ROLES_JEV)


def test_pregunta_rol_es_una_sola_pregunta_choice_con_descripcion_por_rol():
    pregunta = pregunta_rol()
    assert list(pregunta) == ["rol"]
    p = pregunta["rol"]
    assert p["type"] == "choice" and p["instructions"].strip()
    assert tuple(p["criteria"]) == ROLES_JEV
    assert all(isinstance(d, str) and d.strip() for d in p["criteria"].values())


def test_pregunta_rol_instruye_usar_el_nombre_del_archivo_como_apoyo_del_contenido():
    p = pregunta_rol()["rol"]
    instrucciones = p["instructions"]
    assert "Nombre del archivo:" in instrucciones
    assert "contenido" in instrucciones and "prima" in instrucciones
    assert "nombre del archivo" in p["criteria"]["otro"]
    assert "nombrado memorial" in p["criteria"]["memorial"]
    ops, _ = segunda_opinion([doc_con_texto("1a-001", "012MemorialImpulso.pdf")], FakeJev(choice("memorial")), CFG)
    assert "Nombre del archivo:" in ops[0].llamada["instrucciones"]


def test_invertir_reordena_las_opciones():
    directo = list(pregunta_rol()["rol"]["criteria"])
    inverso = pregunta_rol(invertir=True)["rol"]["criteria"]
    assert list(inverso) == directo[::-1]
    assert inverso == dict(reversed(list(pregunta_rol()["rol"]["criteria"].items())))


def test_clasificar_expone_las_constantes_de_evidencia_que_usa():
    assert clasificar.EVIDENCIA_SIN_TEXTO == "Sin texto legible."
    assert clasificar.EVIDENCIA_SIN_ROL == "Sin rasgos de ningún rol."
    sin_texto = doc_de(nombre="scan.pdf", paginas=[Pagina(n=1, texto="", sin_texto=True)])
    assert clasificar.clasificar(sin_texto) == ("otro", clasificar.EVIDENCIA_SIN_TEXTO)
    sin_rasgos = doc_de(paginas=[Pagina(n=1, texto="Lorem ipsum dolor sit amet consectetur adipiscing elit.")])
    assert clasificar.clasificar(sin_rasgos) == ("otro", clasificar.EVIDENCIA_SIN_ROL)


@pytest.mark.parametrize(
    "malas",
    [{"otro": float("nan")}, {"otro": float("inf")}, {"otro": float("-inf")}, {"otro": 10**400}, {"otro": -0.1}, {"otro": 1.5}],
)
def test_probabilidades_no_finitas_o_fuera_de_rango_se_descartan(malas):
    respuesta = choice("fallo_a_quo", 0.9, {"fallo_a_quo": 0.9, **malas})
    ops, alertas = segunda_opinion([doc_con_texto()], FakeJev(respuesta), CFG)
    assert alertas == [] and ops[0].probabilidades == {"fallo_a_quo": 0.9}
    json.dumps(ops[0].probabilidades, allow_nan=False)


def test_probabilidades_con_tipo_distinto_de_numero_se_descartan():
    respuesta = choice("fallo_a_quo", 0.9, {"fallo_a_quo": 0.9, "otro": "alta", "memorial": True, "anexo": None})
    ops, _ = segunda_opinion([doc_con_texto()], FakeJev(respuesta), CFG)
    assert ops[0].probabilidades == {"fallo_a_quo": 0.9}


@pytest.mark.parametrize("error", [RuntimeError("Bearer SECRETO"), ValueError("Invalid header value b'Bearer SECRETO'"), OverflowError("x")])
def test_excepcion_inesperada_del_cliente_produce_una_alerta_sin_su_mensaje(error):
    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 4)]
    ops, alertas = segunda_opinion(docs, FakeJev(_lanza(error)), Config(jev=JevConfig(modo="sombra", concurrencia=1)))
    assert ops == [] and len(alertas) == 1
    assert type(error).__name__ in alertas[0] and "SECRETO" not in alertas[0] and "3 de 3" in alertas[0]


def test_llamadas_incluye_las_respuestas_descartadas():
    fake = FakeJev({"rol": {"type": "choice", "choice": "inventado", "confidence": 0.99}})
    llamadas: list[dict] = []
    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 4)]
    ops, alertas = segunda_opinion(docs, fake, CFG, llamadas=llamadas)
    assert ops == [] and len(alertas) == 3 and len(fake.llamadas) == 3
    assert len(llamadas) == 3 and all(c["proveedor"] == "jev" and c["nodo"] == "roles" and c["error"] is None for c in llamadas)
    assert all(TEXTO not in json.dumps(c) for c in llamadas)


def test_llamadas_incluye_las_exitosas_en_el_orden_de_los_documentos():
    llamadas: list[dict] = []
    docs = [doc_con_texto(f"1a-{i:03d}", f"{i:03d}.pdf") for i in range(1, 6)]
    ops, _ = segunda_opinion(docs, FakeJev(choice("memorial")), Config(jev=JevConfig(modo="sombra", concurrencia=3)), llamadas=llamadas)
    assert llamadas == [o.llamada for o in ops] and len(llamadas) == 5


def test_llamadas_registra_como_fallida_la_peticion_que_fallo_tras_el_envio():
    llamadas: list[dict] = []
    fake = FakeJev(_lanza(ErrorJev("Jev respondió 500: boom", enviada=True)))
    ops, alertas = segunda_opinion([doc_con_texto()], fake, CFG, llamadas=llamadas)
    assert ops == [] and len(alertas) == 1
    assert len(llamadas) == 1 and llamadas[0]["error"] == "Jev respondió 500: boom" and llamadas[0]["proveedor"] == "jev"
    assert TEXTO not in json.dumps(llamadas)


def test_llamadas_no_registra_lo_que_fallo_antes_de_enviar():
    llamadas: list[dict] = []
    segunda_opinion([doc_con_texto()], FakeJev(_lanza(ErrorJev("sin red"))), CFG, llamadas=llamadas)
    assert llamadas == []


def test_llamadas_es_opcional():
    ops, _ = segunda_opinion([doc_con_texto()], FakeJev(choice("memorial")), CFG)
    assert len(ops) == 1
