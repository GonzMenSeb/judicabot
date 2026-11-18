from __future__ import annotations

import json
import sqlite3

import pytest
from test_graph import AUTO, DECISION, FALLO_DOCX, Verificador, ingesta_sintetica

from tutela2 import api, descarte, fallos, graph, ingest, llm
from tutela2 import citas as citas_real
from tutela2 import config as cfgmod
from tutela2.config import Config, JevConfig, LLMConfig
from tutela2.jev import FakeJev
from tutela2.llm import ErrorLLM
from tutela2.models import Ingesta


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


@pytest.fixture
def caso(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    real = ingest.reaplicar
    monkeypatch.setattr(ingest, "reaplicar", lambda ing, roles: real(ing, roles).model_copy(update={"metadatos": ing.metadatos}))
    return carpeta


def test_flujo_nuevo_revisar_iniciar_decidir(caso):
    r = api.nuevo(caso)
    assert r["ok"] and r["estado"] == "revision"
    resumen = r["resumen"]
    doc = next(d for d in resumen["documentos"] if d["doc_id"] == "1a-003")
    assert doc["rol"] == "contestacion" and doc["rol_origen"] == "contenido"
    assert set(doc) == {
        "doc_id", "ruta", "nombre", "rol", "rol_origen", "evidencia", "paginas", "paginas_sin_texto", "ruido", "ajeno",
        "revisar", "jev_rol", "jev_confianza", "jev_umbral",
    }
    assert doc["ajeno"] is False and doc["revisar"] is False and resumen["docs_revisar"] == []
    assert doc["jev_rol"] is None and doc["jev_confianza"] is None and doc["jev_umbral"] is None
    assert resumen["auto"]["accionante"] == "Marta Ejemplo" and resumen["auto"]["fecha"] == "2026-10-06"
    assert "esperados_faltantes" in resumen and "alertas" in resumen and resumen["metadatos"]["accionante"] == "Marta Ejemplo"

    r = api.revisar(caso, {"1a-003": "anexo"}, {"fecha": "2026-10-07", "accionada": "Otra Entidad"})
    assert r["ok"] and r["estado"] == "revision", r["error"]
    doc = next(d for d in r["resumen"]["documentos"] if d["doc_id"] == "1a-003")
    assert doc["rol"] == "anexo" and doc["rol_origen"] == "usuario"
    assert r["resumen"]["auto"]["fecha"] == "2026-10-07" and r["resumen"]["auto"]["accionada"] == "Otra Entidad"
    assert json.loads((caso / "auto.json").read_text(encoding="utf-8"))["fecha"] == "2026-10-07"
    assert Ingesta.model_validate_json((caso / "caso.json").read_text(encoding="utf-8")).documentos[2].rol == "anexo"
    assert r["salidas"] == [AUTO]

    r = api.iniciar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert FALLO_DOCX in r["salidas"] and "trabajo/previo.docx" in r["salidas"]

    r = api.revisar(caso, {"1a-003": "contestacion"}, None)
    assert not r["ok"] and r["error"]
    assert api.iniciar(caso)["ok"] is False


def test_documento_para_revisar_se_expone_y_no_bloquea_iniciar(caso, monkeypatch):
    ing = ingesta_sintetica().model_copy(update={"docs_revisar": ["1a-003"]})
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ing, raising=False)
    r = api.nuevo(caso)
    assert r["ok"] and r["estado"] == "revision", r["error"]
    marcas = {d["doc_id"]: (d["ajeno"], d["revisar"]) for d in r["resumen"]["documentos"]}
    assert marcas["1a-003"] == (False, True)
    assert {k for k, v in marcas.items() if v[1]} == {"1a-003"}
    assert r["resumen"]["docs_revisar"] == ["1a-003"] and r["resumen"]["docs_ajenos"] == []
    r = api.iniciar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]


def test_documento_para_revisar_que_es_ruido_no_pide_confirmacion(caso, monkeypatch):
    ing = ingesta_sintetica()
    ing.docs_revisar = ["1a-003", "1a-004"]
    next(d for d in ing.documentos if d.doc_id == "1a-003").ruido = True
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ing, raising=False)
    r = api.nuevo(caso)
    assert r["ok"], r["error"]
    docs = {d["doc_id"]: d for d in r["resumen"]["documentos"]}
    assert (docs["1a-003"]["ruido"], docs["1a-003"]["revisar"]) == (True, False)
    assert (docs["1a-004"]["ruido"], docs["1a-004"]["revisar"]) == (False, True)
    assert r["resumen"]["docs_revisar"] == ["1a-004"]


def test_revisar_rechaza_documento_o_rol_invalido(caso):
    api.nuevo(caso)
    assert not api.revisar(caso, {"no-existe": "anexo"}, None)["ok"]
    assert not api.revisar(caso, {"1a-003": "inventado"}, None)["ok"]


def test_revisar_sin_ingesta(caso):
    r = api.revisar(caso, None, None)
    assert not r["ok"] and r["estado"] == "sin_iniciar"


def test_iniciar_incompleto_no_corre_el_grafo(caso, monkeypatch):
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(["impugnacion"]), raising=False)
    r = api.nuevo(caso)
    assert r["estado"] == "incompleto" and "trabajo/requerimiento.docx" in r["salidas"]
    r = api.iniciar(caso)
    assert not r["ok"] and r["estado"] == "incompleto"
    assert not (caso / "hilo.sqlite").exists()


def test_revisar_actualiza_el_requerimiento(caso, monkeypatch):
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(["impugnacion"]), raising=False)
    api.nuevo(caso)
    caso_json = caso / "caso.json"
    ing = Ingesta.model_validate_json(caso_json.read_text(encoding="utf-8"))
    ing.faltantes = []
    caso_json.write_text(ing.model_dump_json(), encoding="utf-8")
    r = api.revisar(caso, None, {"accionante": "Otra Persona"})
    assert r["estado"] == "revision" and "trabajo/requerimiento.docx" not in r["salidas"]


def test_decidir_antes_de_iniciar_no_bloquea_el_caso(caso):
    api.nuevo(caso)
    r = api.decidir(caso, DECISION)
    assert not r["ok"] and r["estado"] == "revision"
    assert not (caso / "hilo.sqlite").exists()
    assert api.iniciar(caso)["estado"] == "esperando_decision"


def test_hilo_vacio_no_impide_iniciar(caso):
    api.nuevo(caso)
    (caso / "hilo.sqlite").write_bytes(b"")
    assert api.revisar(caso, None, {"accionada": "X"})["ok"]
    (caso / "hilo.sqlite").write_bytes(b"")
    assert api.iniciar(caso)["estado"] == "esperando_decision"


def test_control_en_auto_se_limpia_y_conserva_el_002(caso):
    api.nuevo(caso)
    r = api.revisar(caso, None, {"accionante": "Ana\x0bPérez"})
    assert r["ok"] and r["salidas"] == [AUTO]
    assert "\x0b" not in (caso / "auto.json").read_text(encoding="utf-8")


def test_control_en_decision_no_rompe_el_ensamblado(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    d = {**DECISION, "eje": DECISION["eje"] + "\x0bfin"}
    r = api.decidir(caso, d)
    assert r["ok"] and r["estado"] == "terminado", r["error"]


def _parrafos_fallo(caso) -> list[str]:
    from docx import Document

    return [p.text for p in Document(str(caso / "salidas" / FALLO_DOCX)).paragraphs]


def test_la_decision_se_normaliza_antes_de_escribir_decision_json(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    d = {
        **DECISION,
        "eje": "▎ La entidad no acreditó\n▎ la autorización.",
        "ordenes": [{**DECISION["ordenes"][0], "conducta": "▎ autorice\n▎ el procedimiento ordenado"}],
        "numerales_libres": ["▎ CONFIRMAR   en lo demás.\n"],
        "por_reparo": [{"reparo_id": "R1", "disposicion": "ACOGE", "nota": "▎ la nota\n  del reparo"}],
        "decidido_por": "  Oficial\nMayor ",
    }
    original = json.loads(json.dumps(d))
    r = api.decidir(caso, d)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert d == original
    guardada = json.loads((caso / "decision.json").read_text(encoding="utf-8"))
    assert guardada["eje"] == "La entidad no acreditó la autorización."
    assert guardada["ordenes"][0]["conducta"] == "autorice el procedimiento ordenado"
    assert guardada["numerales_libres"] == ["CONFIRMAR en lo demás."]
    assert guardada["por_reparo"][0]["nota"] == "la nota del reparo"
    assert guardada["decidido_por"] == original["decidido_por"]
    assert set(guardada) == set(original)
    texto = "\n".join(_parrafos_fallo(caso))
    assert "▎" not in texto and "autorice el procedimiento ordenado." in texto


def test_improcedente_con_causal_y_advertir_sin_amparar_llega_al_fallo(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    d = {
        "accion": "decidir",
        "resultado": "REVOCAR",
        "sustitutiva": "IMPROCEDENTE",
        "causal": "COSA_JUZGADA",
        "eje": "Existe un trámite de tutela previo con identidad de partes, causa y objeto.",
        "ordenes": [
            {
                "verbo": "ADVERTIR",
                "destinatario": "la señora Marta Ejemplo",
                "conducta": "en caso de considerar incumplida la orden previa, deberá acudir ante el juzgado que la profirió",
            }
        ],
        "decidido_por": "Oficial Mayor",
    }
    r = api.decidir(caso, d)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    parrafos = _parrafos_fallo(caso)
    assert any(p.startswith("SEGUNDO: DECLARAR IMPROCEDENTE") and "cosa juzgada constitucional" in p for p in parrafos)
    assert (
        "TERCERO: ADVERTIR a la señora Marta Ejemplo que en caso de considerar incumplida la orden previa, "
        "deberá acudir ante el juzgado que la profirió."
    ) in parrafos
    from docx import Document

    celdas = [c.text for t in Document(str(caso / "salidas" / FALLO_DOCX)).tables for fila in t.rows for c in fila.cells]
    assert "REVOCA Y DECLARA IMPROCEDENTE POR COSA JUZGADA" in celdas


def test_oficio_sin_fecha_fallo_usa_hoy(caso):
    from datetime import date

    from docx import Document

    api.nuevo(caso)
    api.iniciar(caso)
    r = api.decidir(caso, {**DECISION, "fecha_fallo": None, "fecha_oficio": None})
    assert r["ok"], r["error"]
    texto = "\n".join(p.text for p in Document(str(caso / "salidas/por_radicar/OficioRemiteCorteConstitucional.docx")).paragraphs)
    assert "FALTA" not in texto and str(date.today().year) in texto


def test_nuevo_conserva_roles_y_auto(caso):
    api.nuevo(caso)
    api.revisar(caso, {"1a-003": "anexo"}, {"fecha": "2026-10-07"})
    r = api.nuevo(caso)
    assert r["ok"], r["error"]
    doc = next(d for d in r["resumen"]["documentos"] if d["doc_id"] == "1a-003")
    assert doc["rol"] == "anexo" and doc["rol_origen"] == "usuario"
    assert r["resumen"]["auto"]["fecha"] == "2026-10-07"
    assert json.loads((caso / "auto.json").read_text(encoding="utf-8"))["fecha"] == "2026-10-07"


def _terminado(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]


def _sin_hilo(caso):
    for sufijo in ("", "-wal", "-shm"):
        (caso / f"hilo.sqlite{sufijo}").unlink(missing_ok=True)


TRES = ["el borrador", "la decisión del juez", "el fallo con sus documentos"]


def test_nuevo_sobre_un_caso_terminado_se_niega_sin_descartar(caso):
    _terminado(caso)
    r = api.nuevo(caso)
    assert r["ok"] is False and r["estado"] == "terminado" and r["trabajo_previo"] == TRES
    assert "el borrador, la decisión del juez y el fallo con sus documentos" in r["error"]
    assert "--descartar" in r["error"] and "papelera" in r["error"]
    assert (caso / "hilo.sqlite").exists() and (caso / "decision.json").exists() and (caso / "salidas" / FALLO_DOCX).exists()
    assert not (caso.parent / ".papelera").exists()
    r = api.nuevo(caso, descartar=True)
    assert r["ok"] and r["estado"] == "revision"
    assert not (caso / "decision.json").exists() and not (caso / "hilo.sqlite").exists()
    assert r["salidas"] == [AUTO]


def test_nuevo_esperando_decision_conserva_el_borrador(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    r = api.nuevo(caso)
    assert r["ok"] is False and r["estado"] == "esperando_decision" and r["trabajo_previo"] == ["el borrador"]
    assert (caso / "salidas" / "trabajo" / "previo.docx").exists() and (caso / "hilo.sqlite").exists()


def test_nuevo_con_una_ingesta_fallida_no_descarta_el_trabajo(caso, monkeypatch):
    _terminado(caso)

    def falla(d, c):
        raise RuntimeError("no se pudo leer")

    monkeypatch.setattr(ingest, "ingerir", falla, raising=False)
    assert api.nuevo(caso, descartar=True)["ok"] is False
    assert (caso / "hilo.sqlite").exists() and (caso / "decision.json").exists()
    assert not (caso.parent / ".papelera").exists()


def test_sin_hilo_con_salidas_avisa_historial_perdido(caso):
    _terminado(caso)
    _sin_hilo(caso)
    r = api.estado(caso)
    assert r["estado"] == "revision" and r["historial_perdido"] is True and r["trabajo_previo"] == TRES


def test_hilo_vaciado_avisa_historial_perdido(caso):
    _terminado(caso)
    (caso / "hilo.sqlite").write_bytes(b"")
    r = api.estado(caso)
    assert r["estado"] == "revision" and r["historial_perdido"] is True and r["trabajo_previo"] == TRES


def test_un_caso_sano_no_avisa_historial_perdido(caso):
    assert "historial_perdido" not in api.estado(caso)
    api.nuevo(caso)
    assert "historial_perdido" not in api.estado(caso)
    api.iniciar(caso)
    assert "historial_perdido" not in api.estado(caso)
    api.decidir(caso, DECISION)
    assert "historial_perdido" not in api.estado(caso)


def test_iniciar_sin_historial_se_niega_y_con_descartar_rehace(caso):
    _terminado(caso)
    _sin_hilo(caso)
    r = api.iniciar(caso)
    assert r["ok"] is False and r["trabajo_previo"] == TRES and "cuyo historial se perdió" in r["error"]
    assert not (caso / "hilo.sqlite").exists() and (caso / "decision.json").exists()
    r = api.iniciar(caso, descartar=True)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert not (caso / "decision.json").exists() and not (caso / "salidas" / "por_radicar").exists()
    assert not (caso / "salidas" / FALLO_DOCX).exists()
    assert "historial_perdido" not in api.estado(caso)


def test_iniciar_con_hilo_vacio_no_pierde_la_decision_al_negarse(caso):
    _terminado(caso)
    (caso / "hilo.sqlite").write_bytes(b"")
    r = api.iniciar(caso)
    assert r["ok"] is False and "la decisión del juez" in r["error"]
    assert (caso / "decision.json").exists()


def test_revisar_sin_historial_se_niega(caso):
    _terminado(caso)
    _sin_hilo(caso)
    fallo = caso / "salidas" / FALLO_DOCX
    antes = fallo.read_bytes()
    vistas = sorted((caso / "salidas").rglob("*.vista.json"))
    assert any("Fallo" in v.name or "fallo" in v.name for v in vistas)
    auto = (caso / "auto.json").read_bytes() if (caso / "auto.json").exists() else None
    r = api.revisar(caso, None, {"accionada": "X"})
    assert r["ok"] is False and "cuyo historial se perdió" in r["error"]
    assert fallo.read_bytes() == antes and sorted((caso / "salidas").rglob("*.vista.json")) == vistas
    assert ((caso / "auto.json").read_bytes() if (caso / "auto.json").exists() else None) == auto


def test_iniciar_con_hilo_sano_no_se_confunde_con_historial_perdido(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    r = api.iniciar(caso)
    assert r["ok"] is False and "ya se inició" in r["error"] and "trabajo_previo" not in r


def test_hilo_danado_da_mensaje_en_espanol(caso):
    _terminado(caso)
    (caso / "hilo.sqlite").write_bytes(b"basura" * 100)
    r = api.estado(caso)
    assert r["estado"] == "error" and r["error"] == api.HILO_DANADO
    assert "file is not a database" not in r["error"]
    assert r["historial_perdido"] is True and r["trabajo_previo"] == TRES


def test_un_hilo_bloqueado_no_se_presenta_como_danado(caso):
    r = api._fallo(caso, sqlite3.OperationalError("database is locked"))
    assert r["error"] == "database is locked" and "historial_perdido" not in r


def test_nuevo_sobre_un_hilo_ilegible_se_niega_sin_descartar(caso):
    api.nuevo(caso)
    (caso / "hilo.sqlite").write_bytes(b"basura" * 100)
    r = api.nuevo(caso)
    assert r["ok"] is False and r["trabajo_previo"] == ["el avance de la redacción"]
    assert (caso / "hilo.sqlite").read_bytes() == b"basura" * 100
    assert api.nuevo(caso, descartar=True)["ok"]
    assert descarte.trabajo_previo(caso) == []


def test_error_sin_repr_de_excepcion(caso, monkeypatch):
    class Caido:
        def estructurado(self, *a, **k):
            raise ErrorLLM("No hay credenciales.")

    monkeypatch.setattr(llm, "cliente_para", lambda cfg: Caido())
    api.nuevo(caso)
    api.iniciar(caso)
    r = api.estado(caso)
    assert r["estado"] == "error" and "(No hay credenciales.)" in r["error"]
    assert "ErrorLLM" not in r["error"] and "'No hay" not in r["error"]


def test_modelo_fuera_de_la_lista_permitida_no_arranca_el_grafo(caso, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-sonnet-5-5")
    api.nuevo(caso)
    cfgmod.guardar(caso, Config(llm=LLMConfig(modelo="claude-opus-5-5")))
    r = api.iniciar(caso)
    assert r["ok"] is False and r["estado"] == "error"
    assert "claude-opus-5-5" in r["error"] and "TUTELA2_MODELOS_PERMITIDOS" in r["error"]
    assert not (caso / "hilo.sqlite").exists()


class _Contador:
    def __init__(self):
        self.llamadas = 0

    def estructurado(self, *a, **k):
        self.llamadas += 1
        raise ErrorLLM("El modelo rechazó la solicitud.")


def test_fallo_del_cliente_deja_rastro(caso, monkeypatch):
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: _Contador())
    api.nuevo(caso)
    api.iniciar(caso)
    registros = fallos.leer(caso)
    assert len(registros) == 1
    r = registros[0]
    assert r["nodo"] == "apertura" and r["tipo_error"] == "ErrorLLM" and "rechazó" in r["error"]
    assert len(r["sha256_entrada"]) == 64 and r["prompt_id"] and r["modelo_pedido"] and r["fecha"]
    assert (caso / "fallos_ia.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_continuar_respeta_el_tope_y_forzar_reintenta(caso, monkeypatch):
    cliente = _Contador()
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: cliente)
    api.nuevo(caso)
    api.iniciar(caso)
    api.continuar(caso)
    assert api.estado(caso)["tope_intentos"] is False
    api.continuar(caso)
    assert cliente.llamadas == 3
    e = api.estado(caso)
    assert e["estado"] == "error" and e["tope_intentos"] is True
    assert "Reintentar de todos modos" in e["error"] and "la apertura" in e["error"]
    r = api.continuar(caso)
    assert cliente.llamadas == 3
    assert r["ok"] is False and r["tope_intentos"] is True
    assert "rechazó la solicitud" in r["error"] and "Reintentar de todos modos" in r["error"]
    assert "falló 3 veces seguidas en la apertura" in r["error"] and "Inteligencia artificial" in r["error"]
    r = api.continuar(caso, forzar=True)
    assert cliente.llamadas == 4
    assert len(fallos.leer(caso)) == 4


class _SinCoste:
    def __init__(self):
        self.llamadas = 0

    def estructurado(self, *a, **k):
        self.llamadas += 1
        raise ErrorLLM("Error del proveedor (OverloadedError): saturado", sin_coste=True)


def test_fallos_sin_coste_no_cuentan_para_el_tope(caso, monkeypatch):
    cliente = _SinCoste()
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: cliente)
    api.nuevo(caso)
    respuestas = [api.iniciar(caso)] + [api.continuar(caso) for _ in range(4)]
    assert cliente.llamadas == 5
    assert not any(r.get("tope_intentos") for r in respuestas)
    assert api.estado(caso)["tope_intentos"] is False
    registros = fallos.leer(caso)
    assert len(registros) == 5 and all(r["sin_coste"] is True for r in registros)
    assert all(r["max_tokens"] == cfgmod.cargar(caso).llm.max_tokens for r in registros)


def test_registros_viejos_sin_coste_se_reconocen_por_el_texto(tmp_path):
    textos = [
        "No hay credenciales para el proveedor (ANTHROPIC_API_KEY): Could not resolve authentication method.",
        "Error del proveedor (OverloadedError): Error code: 529 - {'type': 'error'}",
        "Error del proveedor (RateLimitError): Error code: 429",
        "Error del proveedor (InternalServerError): Error code: 503",
        "Error del proveedor (BadRequestError): Error code: 400 - Your credit balance is too low to access the Anthropic API.",
        "Error del proveedor (ClientError): 400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.",
        "Error del proveedor (ServerError): 503 UNAVAILABLE.",
        "Error del proveedor (APIConnectionError): Connection error.",
        "Falta la clave de la API de Anthropic (ANTHROPIC_API_KEY): agréguela en Inteligencia artificial y vuelva a intentarlo.",
    ]
    for texto in textos:
        fallos.registrar(tmp_path, {"nodo": "apertura", "exitos": 0, "error": texto})
    assert api._fallos_consecutivos("apertura", [], tmp_path) == []
    fallos.registrar(tmp_path, {"nodo": "apertura", "exitos": 0, "error": "La respuesta del modelo no cumple el esquema: x"})
    assert [f["error"] for f in api._fallos_consecutivos("apertura", [], tmp_path)] == [
        "La respuesta del modelo no cumple el esquema: x"
    ]


def test_los_tiempos_agotados_y_los_cortes_cuentan_aunque_el_registro_sea_viejo(tmp_path):
    for texto in (
        "Error del proveedor (APITimeoutError): Request timed out.",
        "Error del proveedor (RemoteProtocolError): peer closed connection without sending complete message body",
        "El modelo rechazó la solicitud (stop_reason=refusal).",
        "La respuesta se cortó por el límite de tokens (8000); aumente llm.max_tokens.",
    ):
        fallos.registrar(tmp_path, {"nodo": "apertura", "exitos": 0, "error": texto})
    assert len(api._fallos_consecutivos("apertura", [], tmp_path)) == 4


def test_la_marca_sin_coste_del_registro_manda_sobre_el_texto(tmp_path):
    fallos.registrar(tmp_path, {"nodo": "apertura", "exitos": 0, "error": "algo raro", "sin_coste": True})
    fallos.registrar(
        tmp_path, {"nodo": "apertura", "exitos": 0, "error": "Error del proveedor (OverloadedError): x", "sin_coste": False}
    )
    assert [f["error"] for f in api._fallos_consecutivos("apertura", [], tmp_path)] == [
        "Error del proveedor (OverloadedError): x"
    ]


def test_cambiar_el_modelo_reinicia_el_tope(caso, monkeypatch):
    cliente = _Contador()
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: cliente)
    api.nuevo(caso)
    api.iniciar(caso)
    api.continuar(caso)
    api.continuar(caso)
    assert api.continuar(caso)["tope_intentos"] is True and cliente.llamadas == 3
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="fake", max_tokens=32000), verificar_relatoria=False))
    assert api.estado(caso)["tope_intentos"] is False
    api.continuar(caso)
    assert cliente.llamadas == 4
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="fake", modelo="otro-modelo", max_tokens=32000), verificar_relatoria=False))
    api.continuar(caso)
    assert cliente.llamadas == 5


def _anthropic_sin_clave(caso, monkeypatch):
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="anthropic"), verificar_relatoria=False))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_iniciar_sin_clave_falla_antes_de_abrir_el_hilo(caso, monkeypatch):
    api.nuevo(caso)
    _anthropic_sin_clave(caso, monkeypatch)
    r = api.iniciar(caso)
    assert r["ok"] is False
    assert "Falta la clave de la API de Anthropic" in r["error"] and "Could not resolve" not in r["error"]
    assert not (caso / "hilo.sqlite").exists()
    assert fallos.leer(caso) == []


def test_decidir_sin_clave_no_consume_la_decision(caso, monkeypatch):
    api.nuevo(caso)
    assert api.iniciar(caso)["estado"] == "esperando_decision"
    antes = api.estado(caso)
    _anthropic_sin_clave(caso, monkeypatch)
    r = api.decidir(caso, {"accion": "rehacer_consideraciones", "instruccion": "x"})
    assert r["ok"] is False and "Falta la clave de la API de Anthropic" in r["error"]
    assert api.estado(caso)["estado"] == "esperando_decision" == antes["estado"]
    assert not (caso / "decision.json").exists()
    assert fallos.leer(caso) == []


def test_continuar_sin_clave_no_registra_fallos_ni_cuenta_para_el_tope(caso, monkeypatch):
    real = llm.cliente_para
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: _Contador())
    api.nuevo(caso)
    api.iniciar(caso)
    assert len(fallos.leer(caso)) == 1
    monkeypatch.setattr(llm, "cliente_para", real)
    _anthropic_sin_clave(caso, monkeypatch)
    for _ in range(4):
        r = api.continuar(caso)
        assert r["ok"] is False and "Falta la clave de la API de Anthropic" in r["error"]
        assert not r.get("tope_intentos")
    assert len(fallos.leer(caso)) == 1
    assert api.estado(caso)["tope_intentos"] is False
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False))
    r = api.continuar(caso)
    assert r["ok"] is True and r["estado"] == "esperando_decision", r["error"]


def test_los_fallos_por_clave_ausente_ya_registrados_no_cuentan(tmp_path):
    for _ in range(3):
        fallos.registrar(
            tmp_path,
            {"nodo": "apertura", "exitos": 0, "error": "No hay credenciales para el proveedor (ANTHROPIC_API_KEY): x"},
        )
    fallos.registrar(tmp_path, {"nodo": "apertura", "exitos": 0, "error": "El modelo rechazó la solicitud."})
    assert [f["error"] for f in api._fallos_consecutivos("apertura", [], tmp_path)] == ["El modelo rechazó la solicitud."]
    fallos.registrar(
        tmp_path,
        {"nodo": "caso_concreto", "exitos": 0, "error": "Falta la clave de la API de Gemini (GEMINI_API_KEY): agréguela en Inteligencia artificial y vuelva a intentarlo."},
    )
    assert api._fallos_consecutivos("caso_concreto", [], tmp_path) == []


def test_nuevo_borra_los_fallos(caso, monkeypatch):
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: _Contador())
    api.nuevo(caso)
    api.iniciar(caso)
    assert (caso / "fallos_ia.jsonl").exists()
    api.nuevo(caso, descartar=True)
    assert not (caso / "fallos_ia.jsonl").exists()


def test_fallos_consecutivos_no_depende_del_reloj(tmp_path):
    fecha = "2026-11-03T08:48:50+00:00"
    bitacora = [{"nodo": "apertura", "fecha": fecha}]
    fallos.registrar(tmp_path, {"nodo": "apertura", "fecha": fecha, "exitos": 0})
    fallos.registrar(tmp_path, {"nodo": "apertura", "fecha": fecha, "exitos": 1})
    assert len(api._fallos_consecutivos("apertura", bitacora, tmp_path)) == 1


def test_fecha_reparto_se_persiste_y_propone_fecha_habil(caso):
    api.nuevo(caso)
    r = api.revisar(caso, {}, {"fecha_reparto": "2026-10-09"})
    assert r["ok"], r["error"]
    assert r["resumen"]["auto"]["fecha_reparto"] == "2026-10-09"
    assert r["resumen"]["auto"]["fecha"] == "2026-10-13"
    assert json.loads((caso / "auto.json").read_text(encoding="utf-8"))["fecha_reparto"] == "2026-10-09"
    r = api.revisar(caso, {}, {"fecha": "2026-10-14"})
    assert r["resumen"]["auto"]["fecha"] == "2026-10-14" and r["resumen"]["auto"]["fecha_reparto"] == "2026-10-09"


def _ingesta_con_opinion_de_jev() -> Ingesta:
    ing = ingesta_sintetica()
    ing.documentos[2].jev_rol, ing.documentos[2].jev_confianza, ing.documentos[2].jev_umbral = "escrito_tutela", 0.93, 0.9
    ing.documentos[3].rol_origen = "jev"
    ing.documentos[3].jev_rol, ing.documentos[3].jev_confianza, ing.documentos[3].jev_umbral = ing.documentos[3].rol, 0.97, 0.85
    return ing


def test_resumen_expone_jev_rol_y_confianza(caso, monkeypatch):
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: _ingesta_con_opinion_de_jev(), raising=False)
    r = api.nuevo(caso)
    docs = {d["doc_id"]: d for d in r["resumen"]["documentos"]}
    assert (docs["1a-003"]["jev_rol"], docs["1a-003"]["jev_confianza"]) == ("escrito_tutela", 0.93)
    assert (docs["1a-004"]["jev_rol"], docs["1a-004"]["jev_confianza"], docs["1a-004"]["rol_origen"]) == ("fallo_a_quo", 0.97, "jev")
    assert (docs["1a-003"]["jev_umbral"], docs["1a-004"]["jev_umbral"]) == (0.9, 0.85)
    assert all(
        docs[i]["jev_rol"] is None and docs[i]["jev_confianza"] is None and docs[i]["jev_umbral"] is None
        for i in ("1a-001", "1a-002", "1a-005")
    )

    r = api.revisar(caso, {"1a-003": "anexo"}, None)
    doc = next(d for d in r["resumen"]["documentos"] if d["doc_id"] == "1a-003")
    assert (doc["rol"], doc["rol_origen"]) == ("anexo", "usuario")
    assert (doc["jev_rol"], doc["jev_confianza"], doc["jev_umbral"]) == ("escrito_tutela", 0.93, 0.9)
    assert api.estado(caso)["resumen"]["documentos"][2]["jev_rol"] == "escrito_tutela"


def _jev_que_responde(sentido: str, rol: str, confianza: float = 0.97) -> FakeJev:
    def responder(estado, preguntas):
        return {
            id_: {"type": "choice", "choice": rol if id_ == "rol_impugnante" else sentido, "confidence": confianza, "probabilities": {}}
            for id_ in preguntas
        }

    return FakeJev(responder)


def test_resumen_expone_jev_metadatos(caso, monkeypatch):
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False, jev=JevConfig(modo="sombra")))
    jev = _jev_que_responde("niega", "accionante")
    monkeypatch.setattr(graph, "cliente_jev", lambda cfg: jev)
    api.nuevo(caso)
    r = api.iniciar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert jev.llamadas
    md = r["resumen"]["jev_metadatos"]
    assert set(md) == {"modelo", "umbral", "preguntas", "coincide"} and md["modelo"] == "jev-fake" and md["umbral"] == 0.9
    assert md["preguntas"]["rol_impugnante"] == {"choice": "accionante", "confidence": 0.97}
    assert md["preguntas"]["sentido_fallo"] == {"choice": "niega", "confidence": 0.97}
    assert set(md["coincide"]) == {"sentido", "rol_impugnante"}
    assert api.estado(caso)["resumen"]["jev_metadatos"] == md
    assert any(b.get("proveedor") == "jev" for b in r["resumen"]["bitacora"])


@pytest.mark.parametrize("clave", ["SECRETO-JEV\nx", "SECRETO-JEV\u2013x"])
def test_clave_de_jev_no_valida_no_detiene_la_redaccion_ni_se_filtra(caso, monkeypatch, clave):
    cfgmod.guardar(caso, Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False, jev=JevConfig(modo="sombra")))
    monkeypatch.setenv("JEV_API_KEY", clave)
    r = api.nuevo(caso)
    assert r["ok"], r["error"]
    r = api.iniciar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert any("Jev" in a for a in r["resumen"]["alertas"]["apertura"])
    assert r["resumen"]["jev_metadatos"] is None
    assert "SECRETO" not in json.dumps(r, default=str)
    assert not any(b"SECRETO-JEV" in p.read_bytes() for p in caso.rglob("*") if p.is_file())


def test_resumen_sin_jev_no_trae_metadatos_de_jev(caso):
    api.nuevo(caso)
    r = api.iniciar(caso)
    assert r["ok"], r["error"]
    assert r["resumen"]["jev_metadatos"] is None
