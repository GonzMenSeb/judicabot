from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from docx import Document
from langgraph.checkpoint.memory import InMemorySaver

from test_graph import Verificador, hilo, ingesta_sintetica
from tutela2 import citas as citas_real
from tutela2 import graph, lint
from tutela2.config import Config, JevConfig, LLMConfig
from tutela2.jev import ErrorJev, FakeJev, HttpJev, RespuestaJev, llamada_ia
from tutela2.jev_metadatos import ROLES_IMPUGNANTE, SENTIDOS, verificar_apertura
from tutela2.llm import FakeClient
from tutela2.models import AperturaLLM, Doc, Ingesta, Metadatos, MetadatosLLM, Pagina, Rol

CFG_SOMBRA = Config(jev=JevConfig(modo="sombra"))
RESUELVE = "RESUELVE: PRIMERO: AMPARAR los derechos fundamentales de la accionante. SEGUNDO: ORDENAR a la entidad accionada autorizar el procedimiento."
ENCABEZADO_IMPUGNACION = "Señor Juez. Referencia: acción de tutela. Impugnación presentada por la entidad accionada contra el fallo de primera instancia."


def respuestas(**preguntas: tuple[str, float]) -> dict[str, dict]:
    return {
        id_: {"type": "choice", "choice": etiqueta, "confidence": confianza, "probabilities": {etiqueta: confianza}}
        for id_, (etiqueta, confianza) in preguntas.items()
    }


RESP_OK = respuestas(
    sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionada", 0.95)
)


def doc_de(i: int, rol: Rol, nombre: str, paginas: list[str], **extra) -> Doc:
    return Doc(
        doc_id=f"1a-{i:03d}",
        ruta=f"1a/{nombre}",
        nombre=nombre,
        instancia="1a",
        rol=rol,
        sha256=hashlib.sha256(nombre.encode()).hexdigest(),
        paginas=[Pagina(n=n, texto=t) for n, t in enumerate(paginas, 1)],
        **extra,
    )


def ingesta(fallo: str | None = RESUELVE, impugnacion: str | None = ENCABEZADO_IMPUGNACION, **md) -> Ingesta:
    docs = []
    if fallo is not None:
        docs.append(doc_de(1, "fallo_a_quo", "006Fallo.pdf", [fallo]))
    if impugnacion is not None:
        docs.append(doc_de(2, "impugnacion", "008Impugnacion.pdf", [impugnacion]))
    return Ingesta(documentos=docs, metadatos=Metadatos(**md))


def apertura(rol: str = "accionada", clausula: str = "amparó los derechos fundamentales de la accionante", **md) -> AperturaLLM:
    return AperturaLLM(
        metadatos=MetadatosLLM(decision_a_quo=clausula, impugnante_rol=rol, **md),
        cronologia=[],
        antecedentes_hechos="a",
        contestaciones=[],
        sentencia_impugnada="s",
        impugnacion="i",
        reparos=[],
    )


def lanza(error: Exception):
    def f(estado, preguntas):
        raise error

    return f


def estado_con_apertura(cfg: Config) -> dict:
    entrada = graph.estado_inicial(None, cfg, ingesta_sintetica())
    entrada["caso_dir"] = "caso"
    return {**entrada, **graph.nodo_apertura(entrada, cfg, FakeClient())}


def test_alerta_si_la_clausula_no_coincide_con_el_fallo():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    alertas, _, _ = verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)
    assert any(a.startswith(lint.ALERTA) and "decision_a_quo" in a for a in alertas)


def test_sin_alertas_si_todo_coincide():
    fake = FakeJev(RESP_OK)
    assert verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)[0] == []


def test_alerta_si_el_rol_del_impugnante_difiere():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionante", 0.95)))
    alertas, _, _ = verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)
    assert len(alertas) == 1 and alertas[0].startswith(lint.ALERTA) and "impugnante_rol" in alertas[0]


def test_baja_confianza_no_genera_alerta_y_queda_sin_comparar():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.4), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)
    assert alertas == [] and jev_md["coincide"]["sentido"] is None


def test_baja_confianza_del_rol_no_genera_alerta():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionante", 0.5)))
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)
    assert alertas == [] and jev_md["coincide"]["rol_impugnante"] is None


def test_el_umbral_viene_de_la_configuracion():
    cfg = Config(jev=JevConfig(modo="sombra", umbral_confianza=0.99))
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura("accionante"), FakeJev(RESP_OK), cfg)
    assert alertas == [] and jev_md["coincide"] == {"sentido": None, "rol_impugnante": None}


def test_una_sola_peticion_con_tres_preguntas_cerradas():
    fake = FakeJev(RESP_OK)
    verificar_apertura(ingesta(), apertura(), fake, CFG_SOMBRA)
    assert len(fake.llamadas) == 1
    estado, preguntas = fake.llamadas[0]
    assert isinstance(estado, dict)
    assert list(preguntas) == ["sentido_fallo", "sentido_clausula", "rol_impugnante"]
    assert all(p["type"] == "choice" for p in preguntas.values())
    assert tuple(preguntas["sentido_fallo"]["criteria"]) == SENTIDOS
    assert tuple(preguntas["sentido_clausula"]["criteria"]) == SENTIDOS
    assert tuple(preguntas["rol_impugnante"]["criteria"]) == ROLES_IMPUGNANTE
    assert all(p["instructions"] and all(p["criteria"].values()) for p in preguntas.values())


def test_el_estado_enviado_lleva_las_fuentes_y_las_partes():
    fake = FakeJev(RESP_OK)
    ing = ingesta(
        accionante="Marta Ejemplo", accionadas=["Entidad Uno"], vinculadas=["Secretaría de Salud"], impugnante="Entidad Uno"
    )
    verificar_apertura(ing, apertura(), fake, CFG_SOMBRA)
    estado = fake.llamadas[0][0]
    assert estado["fallo_resolutivo"] == RESUELVE
    assert estado["clausula"] == "amparó los derechos fundamentales de la accionante"
    assert estado["escrito_impugnacion"] == ENCABEZADO_IMPUGNACION
    assert (estado["accionante"], estado["accionadas"], estado["vinculadas"]) == (
        "Marta Ejemplo",
        ["Entidad Uno"],
        ["Secretaría de Salud"],
    )
    assert estado["impugnante"] == "Entidad Uno"


def test_las_partes_salen_de_apertura_si_la_ingesta_no_las_trae():
    fake = FakeJev(RESP_OK)
    verificar_apertura(ingesta(), apertura(accionante="Marta Ejemplo", impugnante="Entidad Uno"), fake, CFG_SOMBRA)
    estado = fake.llamadas[0][0]
    assert estado["accionante"] == "Marta Ejemplo" and estado["impugnante"] == "Entidad Uno"
    assert "accionadas" not in estado and "vinculadas" not in estado


def test_la_peticion_lleva_solo_la_cola_del_fallo():
    fallo = "CABEZA_DEL_FALLO " + "texto intermedio " * 1200 + RESUELVE
    assert len(fallo) > 20000
    fake = FakeJev(RESP_OK)
    verificar_apertura(ingesta(fallo=fallo), apertura(), fake, CFG_SOMBRA)
    enviado = fake.llamadas[0][0]["fallo_resolutivo"]
    assert len(enviado) <= CFG_SOMBRA.jev.max_chars_sentido
    assert enviado.endswith(RESUELVE) and "CABEZA_DEL_FALLO" not in enviado


def test_la_peticion_acota_la_cabecera_de_la_impugnacion():
    largo = "INICIO " + "argumento " * 2000
    fake = FakeJev(RESP_OK)
    verificar_apertura(ingesta(impugnacion=largo), apertura(), fake, CFG_SOMBRA)
    enviado = fake.llamadas[0][0]["escrito_impugnacion"]
    assert len(enviado) <= CFG_SOMBRA.jev.max_chars_cabecera and enviado.startswith("INICIO")


def test_los_limites_cero_no_envian_texto_del_documento():
    cfg = Config(jev=JevConfig(modo="sombra", max_chars_sentido=0, max_chars_cabecera=0))
    fake = FakeJev(RESP_OK)
    verificar_apertura(ingesta(), apertura(), fake, cfg)
    estado, preguntas = fake.llamadas[0]
    assert "fallo_resolutivo" not in estado and "escrito_impugnacion" not in estado
    assert list(preguntas) == ["sentido_clausula"]


def test_documentos_ruidosos_o_ajenos_no_se_envian():
    ing = ingesta(fallo=None, impugnacion=None)
    ing.documentos = [
        doc_de(1, "fallo_a_quo", "ruido.pdf", ["RUIDO"], ruido=True),
        doc_de(2, "fallo_a_quo", "ajeno.pdf", ["AJENO"]),
        doc_de(3, "fallo_a_quo", "bueno.pdf", ["BUENO"]),
    ]
    ing.docs_ajenos = ["1a-002"]
    fake = FakeJev(RESP_OK)
    verificar_apertura(ing, apertura(), fake, CFG_SOMBRA)
    assert fake.llamadas[0][0]["fallo_resolutivo"] == "BUENO"


def test_paginas_con_ruido_no_se_envian():
    ing = ingesta(fallo=None)
    ing.documentos.append(doc_de(5, "fallo_a_quo", "fallo.pdf", ["PAGINA_UTIL", "PAGINA_RUIDO"]))
    ing.documentos[-1].paginas[1].ruido = True
    fake = FakeJev(RESP_OK)
    verificar_apertura(ing, apertura(), fake, CFG_SOMBRA)
    assert fake.llamadas[0][0]["fallo_resolutivo"] == "PAGINA_UTIL"


def test_sin_texto_de_fallo_no_se_pregunta_por_el_fallo():
    fake = FakeJev(RESP_OK)
    alertas, _, jev_md = verificar_apertura(ingesta(fallo=None), apertura("accionante"), fake, CFG_SOMBRA)
    estado, preguntas = fake.llamadas[0]
    assert "fallo_resolutivo" not in estado and list(preguntas) == ["sentido_clausula", "rol_impugnante"]
    assert len(alertas) == 1 and "impugnante_rol" in alertas[0]
    assert set(jev_md["preguntas"]) == {"sentido_clausula", "rol_impugnante"}
    assert jev_md["coincide"]["sentido"] is None


def test_sin_nada_que_verificar_no_hace_peticion():
    fake = FakeJev(RESP_OK)
    resultado = verificar_apertura(ingesta(None, None), apertura(clausula=""), fake, CFG_SOMBRA)
    assert fake.llamadas == [] and resultado == ([], [], None)


def test_modo_apagado_no_hace_peticiones():
    fake = FakeJev(RESP_OK)
    assert verificar_apertura(ingesta(), apertura(), fake, Config()) == ([], [], None)
    assert fake.llamadas == []


def test_sin_cliente_no_hace_nada():
    assert verificar_apertura(ingesta(), apertura(), None, CFG_SOMBRA) == ([], [], None)


def test_modo_relleno_tambien_solo_alerta():
    cfg = Config(jev=JevConfig(modo="relleno"))
    fake = FakeJev(respuestas(sentido_fallo=("niega", 0.97), sentido_clausula=("ampara", 0.96), rol_impugnante=("accionada", 0.95)))
    alertas, _, _ = verificar_apertura(ingesta(), apertura(), fake, cfg)
    assert alertas and not any(a.startswith(lint.BLOQUEA) for a in alertas)


def test_error_de_jev_produce_una_sola_alerta_y_ningun_dato():
    fake = FakeJev(lanza(ErrorJev("Jev respondió 529")))
    alertas, bitacora, jev_md = verificar_apertura(ingesta(), apertura(), fake, CFG_SOMBRA)
    assert len(alertas) == 1 and alertas[0].startswith(lint.ALERTA) and "Jev" in alertas[0] and "529" in alertas[0]
    assert bitacora == [] and jev_md is None


def test_jev_metadatos_incluye_confianzas_y_coincidencias():
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    _, _, jev_md = verificar_apertura(ingesta(), apertura("accionada"), fake, CFG_SOMBRA)
    assert jev_md == {
        "modelo": "jev-fake",
        "umbral": 0.9,
        "preguntas": {
            "sentido_fallo": {"choice": "ampara", "confidence": 0.97},
            "sentido_clausula": {"choice": "niega", "confidence": 0.96},
            "rol_impugnante": {"choice": "accionada", "confidence": 0.95},
        },
        "coincide": {"sentido": False, "rol_impugnante": True},
    }
    json.dumps(jev_md)


def test_rol_sin_valor_en_ningun_lado_queda_sin_comparar():
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura(rol=""), FakeJev(RESP_OK), CFG_SOMBRA)
    assert alertas == [] and jev_md["coincide"]["rol_impugnante"] is None
    assert jev_md["preguntas"]["rol_impugnante"]["choice"] == "accionada"


def test_rol_se_compara_con_la_ingesta_si_apertura_no_lo_trae():
    ing = ingesta(impugnante_rol="accionante")
    alertas, _, jev_md = verificar_apertura(ing, apertura(rol=""), FakeJev(RESP_OK), CFG_SOMBRA)
    assert len(alertas) == 1 and "impugnante_rol" in alertas[0] and jev_md["coincide"]["rol_impugnante"] is False


def test_el_rol_de_apertura_prevalece_sobre_el_de_la_ingesta():
    ing = ingesta(impugnante_rol="accionante")
    alertas, _, jev_md = verificar_apertura(ing, apertura(rol="accionada"), FakeJev(RESP_OK), CFG_SOMBRA)
    assert alertas == [] and jev_md["coincide"]["rol_impugnante"] is True


def test_etiqueta_fuera_del_catalogo_se_ignora_con_alerta():
    resp = respuestas(sentido_clausula=("ampara", 0.96), rol_impugnante=("accionada", 0.95))
    resp["sentido_fallo"] = {"type": "choice", "choice": "inventado", "confidence": 0.99, "probabilities": {}}
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(resp), CFG_SOMBRA)
    assert len(alertas) == 1 and "sentido_fallo" in alertas[0] and "inventado" in alertas[0]
    assert "sentido_fallo" not in jev_md["preguntas"] and jev_md["coincide"]["sentido"] is None


@pytest.mark.parametrize("confianza", ["alta", None, True, 1.5, -0.1, float("nan")])
def test_confianza_invalida_se_ignora_con_alerta(confianza):
    resp = respuestas(sentido_clausula=("ampara", 0.96), rol_impugnante=("accionada", 0.95))
    resp["sentido_fallo"] = {"type": "choice", "choice": "niega", "confidence": confianza}
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(resp), CFG_SOMBRA)
    assert len(alertas) == 1 and "sentido_fallo" in alertas[0]
    assert "sentido_fallo" not in jev_md["preguntas"]


def test_pregunta_sin_respuesta_se_ignora_con_alerta():
    resp = respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("ampara", 0.96))
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(resp), CFG_SOMBRA)
    assert len(alertas) == 1 and "rol_impugnante" in alertas[0]
    assert set(jev_md["preguntas"]) == {"sentido_fallo", "sentido_clausula"}


def test_todas_las_respuestas_invalidas_dejan_alertas_y_bitacora_pero_ningun_dato():
    alertas, bitacora, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev({}), CFG_SOMBRA)
    assert len(alertas) == 3 and len(bitacora) == 1 and jev_md is None


def test_la_bitacora_registra_la_llamada_sin_el_texto_ni_la_clave():
    fake = FakeJev(RESP_OK)
    _, bitacora, _ = verificar_apertura(ingesta(), apertura(), fake, CFG_SOMBRA)
    assert len(bitacora) == 1
    llamada = bitacora[0]
    assert llamada["proveedor"] == "jev" and llamada["nodo"] == "metadatos" and llamada["prompt_id"] == "jev-metadatos-v1"
    assert llamada["modelo_pedido"] == "jev-latest" and llamada["modelo_efectivo"] == "jev-fake"
    estado, preguntas = fake.llamadas[0]
    esperada = llamada_ia(
        "metadatos", estado, preguntas, RespuestaJev("jev-fake", RESP_OK, llamada["tokens_entrada"], llamada["tokens_salida"]), "jev-latest"
    )
    assert {k: v for k, v in llamada.items() if k != "fecha"} == {k: v for k, v in esperada.items() if k != "fecha"}
    volcado = json.dumps(llamada)
    assert "AMPARAR" not in volcado and "amparó" not in volcado and "Impugnación presentada" not in volcado


def test_nodo_suma_la_alerta_la_bitacora_y_jev_metadatos():
    estado = estado_con_apertura(CFG_SOMBRA)
    fake = FakeJev(respuestas(sentido_fallo=("ampara", 0.97), sentido_clausula=("niega", 0.96), rol_impugnante=("accionada", 0.95)))
    r = graph.nodo_validar_apertura(estado, CFG_SOMBRA, jev=fake)
    assert any(a.startswith(lint.ALERTA) and "decision_a_quo" in a for a in r["alertas"]["apertura"])
    assert len(r["bitacora"]) == 1 and r["bitacora"][0]["proveedor"] == "jev"
    assert r["jev_metadatos"]["coincide"]["sentido"] is False
    assert not any(e.startswith(lint.BLOQUEA) for e in r["errores"])


def test_nodo_sin_jev_devuelve_bitacora_vacia_y_jev_metadatos_nulo():
    r = graph.nodo_validar_apertura(estado_con_apertura(CFG_SOMBRA), CFG_SOMBRA)
    assert r["bitacora"] == [] and r["jev_metadatos"] is None


def test_jev_caido_deja_una_alerta_y_el_nodo_termina():
    estado = estado_con_apertura(CFG_SOMBRA)
    base = graph.nodo_validar_apertura(estado, CFG_SOMBRA)
    r = graph.nodo_validar_apertura(estado, CFG_SOMBRA, jev=FakeJev(lanza(ErrorJev("Jev respondió 529"))))
    assert r["errores"] == base["errores"]
    nuevas = [a for a in r["alertas"]["apertura"] if a not in base["alertas"]["apertura"]]
    assert len(nuevas) == 1 and nuevas[0].startswith(lint.ALERTA) and "Jev" in nuevas[0]
    assert r["bitacora"] == [] and r["jev_metadatos"] is None


def test_nodo_en_modo_apagado_no_hace_peticiones():
    fake = FakeJev(RESP_OK)
    r = graph.nodo_validar_apertura(estado_con_apertura(Config()), Config(), jev=fake)
    assert fake.llamadas == [] and r["bitacora"] == [] and r["jev_metadatos"] is None


def test_estado_inicial_arranca_sin_jev_metadatos():
    assert graph.estado_inicial(None, Config(), ingesta_sintetica())["jev_metadatos"] is None


@pytest.fixture
def citas_falsas(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


def correr_hasta_la_decision(cfg: Config, tmp_path, jev):
    g = graph.construir(cfg, FakeClient(), InMemorySaver(), jev=jev)
    g.invoke(graph.estado_inicial(tmp_path / "caso-1", cfg, ingesta_sintetica()), hilo(), durability="sync")
    return g.get_state(hilo()).values


def test_construir_con_jev_verifica_la_apertura_sin_reintentar(tmp_path, citas_falsas):
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False, jev=JevConfig(modo="sombra"))
    fake = FakeJev(respuestas(sentido_fallo=("niega", 0.97), sentido_clausula=("niega", 0.96), rol_impugnante=("accionante", 0.95)))
    valores = correr_hasta_la_decision(cfg, tmp_path, fake)
    assert len(fake.llamadas) == 1
    assert valores["intentos"]["apertura"] == 1
    assert valores["jev_metadatos"]["coincide"]["sentido"] is True
    assert [b["nodo"] for b in valores["bitacora"] if b["proveedor"] == "jev"] == ["metadatos"]


def test_construir_sin_jev_deja_el_estado_limpio(tmp_path, citas_falsas):
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    valores = correr_hasta_la_decision(cfg, tmp_path, None)
    assert valores["jev_metadatos"] is None
    assert not [b for b in valores["bitacora"] if b["proveedor"] == "jev"]


def test_construir_con_jev_caido_no_cambia_el_flujo(tmp_path, citas_falsas):
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False, jev=JevConfig(modo="sombra"))
    base = correr_hasta_la_decision(cfg, tmp_path / "a", None)
    caido = correr_hasta_la_decision(cfg, tmp_path / "b", FakeJev(lanza(ErrorJev("Jev respondió 401"))))
    assert caido["intentos"] == base["intentos"] and caido["errores"] == base["errores"]
    assert caido["jev_metadatos"] is None
    assert len([a for a in caido["alertas"]["apertura"] if "Jev" in a]) == 1


def test_declaracion_ia_con_llamadas_de_jev_no_busca_un_prompt(tmp_path):
    _, bitacora, _ = verificar_apertura(ingesta(), apertura(), FakeJev(RESP_OK), CFG_SOMBRA)
    estado = {"ingesta": Ingesta(documentos=[]).model_dump(mode="json"), "bitacora": bitacora}
    from tutela2 import render

    ruta = render.render_declaracion_ia(estado, Config(), tmp_path / "declaracion.docx", hoy=date(2026, 11, 3))
    plano = "\n".join(p.text for p in Document(str(ruta)).paragraphs)
    assert "metadatos (intento 1), prompt jev-metadatos-v1" in plano


def test_la_confianza_igual_al_umbral_se_compara():
    resp = respuestas(sentido_fallo=("ampara", 0.9), sentido_clausula=("niega", 0.9), rol_impugnante=("accionada", 0.9))
    alertas, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(resp), CFG_SOMBRA)
    assert len(alertas) == 1 and jev_md["coincide"]["sentido"] is False


@pytest.mark.parametrize("error", [RuntimeError("Bearer SECRETO"), ValueError("Invalid header value b'Bearer SECRETO'"), OverflowError("x")])
def test_excepcion_inesperada_de_jev_deja_una_alerta_sin_su_mensaje_y_no_rompe(error):
    alertas, bitacora, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(lanza(error)), CFG_SOMBRA)
    assert len(alertas) == 1 and alertas[0].startswith(lint.ALERTA)
    assert type(error).__name__ in alertas[0] and "SECRETO" not in alertas[0]
    assert bitacora == [] and jev_md is None


def test_peticion_fallida_tras_el_envio_queda_en_la_bitacora_con_su_error():
    fake = FakeJev(lanza(ErrorJev("Jev respondió 500: boom", enviada=True)))
    alertas, bitacora, jev_md = verificar_apertura(ingesta(), apertura(), fake, CFG_SOMBRA)
    assert len(alertas) == 1 and jev_md is None and len(bitacora) == 1
    assert bitacora[0]["proveedor"] == "jev" and bitacora[0]["nodo"] == "metadatos"
    assert bitacora[0]["error"] == "Jev respondió 500: boom" and bitacora[0]["modelo_efectivo"] is None
    assert "AMPARAR" not in json.dumps(bitacora)


def test_jev_metadatos_guarda_el_umbral_con_el_que_se_comparo():
    cfg = Config(jev=JevConfig(modo="sombra", umbral_confianza=0.93))
    _, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(RESP_OK), cfg)
    assert jev_md["umbral"] == 0.93
    _, _, jev_md = verificar_apertura(ingesta(), apertura(), FakeJev(RESP_OK), CFG_SOMBRA)
    assert jev_md["umbral"] == 0.9


@pytest.mark.parametrize("clave", ["SECRETO-JEV\nx", "clave\u2013con-raya"])
def test_nodo_con_clave_no_valida_deja_una_alerta_y_termina_sin_filtrar_la_clave(clave):
    estado = estado_con_apertura(CFG_SOMBRA)
    base = graph.nodo_validar_apertura(estado, CFG_SOMBRA)
    r = graph.nodo_validar_apertura(estado, CFG_SOMBRA, jev=HttpJev(clave, 5))
    assert r["errores"] == base["errores"]
    nuevas = [a for a in r["alertas"]["apertura"] if a not in base["alertas"]["apertura"]]
    assert len(nuevas) == 1 and "Jev" in nuevas[0]
    assert "SECRETO" not in json.dumps(r, default=str) and "raya" not in json.dumps(r, default=str)
