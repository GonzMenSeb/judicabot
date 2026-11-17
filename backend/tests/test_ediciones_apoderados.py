"""Edición in situ del borrador con abogados identificados: los nombres se vuelven a marcar al renderizar."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_ajustes_apoderados import ColaFalsa
from test_apoderados import EPS
from test_ediciones_api import BLOQUE, montar_caso, provocar_conflicto
from test_graph import DECISION, Verificador, ingesta_con_abogada
from tutela2 import api, estado_apoderados, ingest, llm, salidas, server, vigencia, vista
from tutela2 import citas as citas_real
from tutela2 import config as cfgmod
from tutela2 import rutas_ajustes_apoderados as rutas
from tutela2.config import ApoderadosConfig, Config, LLMConfig
from tutela2.models import Identificacion

CONTESTACION = "apertura.contestaciones.0.texto"
NOMBRE = "Andrea Paola Giraldo Montoya"
DECISION_EPS = {**DECISION, "ordenes": [{**DECISION["ordenes"][0], "destinatario": EPS}]}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None, galletas=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)
    monkeypatch.setattr(vigencia, "_abrir", _falla)
    monkeypatch.setattr(vigencia, "COLA", ColaFalsa(), raising=False)
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)
    monkeypatch.delenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, raising=False)
    server.JOBS.clear()
    yield
    server.JOBS.clear()


def _montar(tmp_path, monkeypatch, activo: bool) -> Path:
    carpeta = tmp_path / "casos" / "caso-abogada"
    (carpeta / "insumos").mkdir(parents=True)
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    base = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    cfgmod.guardar(carpeta, base.model_copy(update={"apoderados": ApoderadosConfig(activo=activo, consulta="fake")}))
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_con_abogada(), raising=False)
    assert api.nuevo(carpeta)["ok"]
    r = api.iniciar(carpeta)
    assert r["estado"] == "esperando_decision", r["error"]
    cfgmod.guardar(carpeta, base.model_copy(update={"apoderados": ApoderadosConfig(consulta="fake")}))
    return carpeta


def _valores(caso: Path) -> dict:
    with api._grafo(caso, cfgmod.cargar(caso)) as (g, hilo):
        return dict(g.get_state(hilo).values)


def _vista(caso: Path) -> dict:
    return json.loads((salidas.trabajo(caso) / vista.ARCHIVOS["borrador"]).read_text(encoding="utf-8"))


def _marcas(caso: Path) -> list[tuple[str, str, str | None, int | None]]:
    """``(texto, apoderado_id, pieza, párrafo)`` de cada nombre marcado en el borrador previo."""
    return [
        (s["texto"], s["apoderado_id"], (b.get("fuente") or {}).get("pieza"), (b.get("fuente") or {}).get("parrafo"))
        for p in _vista(caso)["paginas"]
        for b in p["bloques"]
        for s in b["segmentos"]
        if "apoderado_id" in s
    ]


def _citas(caso: Path) -> list[str]:
    return [s["cita_id"] for p in _vista(caso)["paginas"] for b in p["bloques"] for s in b["segmentos"] if "cita_id" in s]


def _editar(caso: Path, parrafo: int, texto: str) -> dict:
    original = api.ediciones(caso)["piezas"][CONTESTACION]["parrafos"][parrafo]
    return api.editar_pieza(caso, CONTESTACION, parrafo, original, texto)


def test_editar_un_parrafo_vuelve_a_marcar_a_los_abogados_que_siguen_en_el_texto(tmp_path, monkeypatch):
    caso = _montar(tmp_path, monkeypatch, activo=True)
    [ap] = Identificacion.model_validate(_valores(caso)["apoderados"]).apoderados
    sha, citas = _vista(caso)["sha256"], _citas(caso)
    assert _marcas(caso) == [(NOMBRE, ap.id, CONTESTACION, 0)]
    [original] = api.ediciones(caso)["piezas"][CONTESTACION]["parrafos"]
    assert NOMBRE in original and "⟦" not in original

    # El nombre sigue en el párrafo editado y aparece en uno nuevo: los dos quedan marcados con el mismo id.
    nuevo = original.replace("dio respuesta a la acción de tutela", "contestó la acción de tutela")
    r = _editar(caso, 0, f"{nuevo}\n\nLa doctora {NOMBRE} allegó el poder que le confirió la entidad.")
    assert r["piezas"][CONTESTACION]["editados"] == [0, 1]
    assert _marcas(caso) == [(NOMBRE, ap.id, CONTESTACION, 0), (NOMBRE, ap.id, CONTESTACION, 1)]
    assert _citas(caso) == citas

    # Sin el nombre no queda marca, y un nombre parecido de otra persona tampoco se marca con el id viejo.
    _editar(caso, 1, "La entidad allegó el poder.")
    assert _marcas(caso) == [(NOMBRE, ap.id, CONTESTACION, 0)]
    _editar(caso, 0, nuevo.replace(NOMBRE, "Andrea Paola Giraldo Restrepo"))
    assert _marcas(caso) == [] and _citas(caso) == citas

    # Restaurar devuelve la marca y el mismo .docx, byte a byte.
    api.restaurar_pieza(caso, CONTESTACION)
    assert _marcas(caso) == [(NOMBRE, ap.id, CONTESTACION, 0)]
    assert _vista(caso)["sha256"] == sha


def test_identificar_un_caso_editado_marca_el_texto_editado_y_la_decision_lo_consolida(tmp_path, monkeypatch):
    caso = _montar(tmp_path, monkeypatch, activo=False)
    [original] = api.ediciones(caso)["piezas"][CONTESTACION]["parrafos"]
    _editar(caso, 0, original.replace("dio respuesta a la acción de tutela", "contestó la acción de tutela"))
    assert _marcas(caso) == []

    falso = llm.FakeClient()
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: falso)
    r = rutas.identificar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert [n for n, _ in falso.llamadas] == ["apoderados"]

    # El borrador previo se regenera con la edición aplicada y el nombre marcado.
    [ap] = Identificacion.model_validate(_valores(caso)["apoderados"]).apoderados
    assert _marcas(caso) == [(NOMBRE, ap.id, CONTESTACION, 0)]
    bloques = [b for p in _vista(caso)["paginas"] for b in p["bloques"] if (b.get("fuente") or {}).get("pieza") == CONTESTACION]
    assert "contestó la acción de tutela" in "".join(s["texto"] for b in bloques for s in b["segmentos"])
    ediciones = api.ediciones(caso)
    assert ediciones["conflictos"] == [] and ediciones["piezas"][CONTESTACION]["editados"] == [0]

    # El cambio de la identificación y el de las ediciones entran al mismo punto de control sin chocar.
    r = api.decidir(caso, DECISION_EPS)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    valores = _valores(caso)
    assert "contestó la acción de tutela" in valores["apertura"]["contestaciones"][0]["texto"]
    assert valores["ediciones_humanas"] == ["antecedentes"]
    assert Identificacion.model_validate(valores["apoderados"]).apoderados == [ap]


def test_run_rechaza_primero_los_conflictos_de_edicion_y_luego_los_apoderados(tmp_path, monkeypatch):
    caso, _, _ = provocar_conflicto(lambda cliente=None: montar_caso(tmp_path, monkeypatch, cliente))
    pendiente = estado_apoderados.Bloqueo("ap1", "María Pérez Gómez", "accionada", "Sin respuesta del registro.")
    monkeypatch.setattr(estado_apoderados, "bloqueos", lambda d: [pendiente])
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    http = TestClient(server.app, base_url="http://127.0.0.1")

    # Con las dos compuertas cerradas, /run y api.decidir dan el mismo motivo: los conflictos van primero.
    conflictos = "Hay conflictos de edición sin resolver en el borrador"
    rechazo = http.post(f"/api/casos/{caso.name}/run", json={"cmd": "decidir", "decision": DECISION})
    assert rechazo.status_code == 409 and rechazo.json()["detail"].startswith(conflictos)
    assert api.decidir(caso, DECISION)["error"].startswith(conflictos)
    assert server.JOBS == {}

    # Resueltos los conflictos, queda la compuerta de apoderados.
    assert api.resolver_pieza(caso, BLOQUE, ["mio"])["conflictos"] == []
    rechazo = http.post(f"/api/casos/{caso.name}/run", json={"cmd": "decidir", "decision": DECISION})
    assert rechazo.status_code == 409
    assert rechazo.json()["detail"] == estado_apoderados.mensaje_bloqueo([pendiente])
    assert server.JOBS == {}
