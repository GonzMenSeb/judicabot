from __future__ import annotations

import json

import pytest
from test_graph import AUTO, DECISION, FALLO_DOCX, Verificador, ingesta_sintetica

from tutela2 import api, fallos, ingest, llm
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
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
    assert set(doc) == {"doc_id", "ruta", "nombre", "rol", "rol_origen", "evidencia", "paginas", "paginas_sin_texto", "ruido", "ajeno"}
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
    api.continuar(caso)
    assert cliente.llamadas == 3
    r = api.continuar(caso)
    assert cliente.llamadas == 3
    assert r["ok"] is False and r["tope_intentos"] is True
    assert "rechazó la solicitud" in r["error"] and "configuración" in r["error"]
    r = api.continuar(caso, forzar=True)
    assert cliente.llamadas == 4
    assert len(fallos.leer(caso)) == 4


def test_nuevo_borra_los_fallos(caso, monkeypatch):
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: _Contador())
    api.nuevo(caso)
    api.iniciar(caso)
    assert (caso / "fallos_ia.jsonl").exists()
    api.nuevo(caso)
    assert not (caso / "fallos_ia.jsonl").exists()


def test_fallos_consecutivos_no_depende_del_reloj(tmp_path):
    fecha = "2026-11-03T08:48:50+00:00"
    bitacora = [{"nodo": "apertura", "fecha": fecha}]
    fallos.registrar(tmp_path, {"nodo": "apertura", "fecha": fecha, "exitos": 0})
    fallos.registrar(tmp_path, {"nodo": "apertura", "fecha": fecha, "exitos": 1})
    assert len(api._fallos_consecutivos("apertura", bitacora, tmp_path)) == 1
