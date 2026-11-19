from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import sys
import threading
import time
import types
import zipfile
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tutela2 import config as cfgmod
from tutela2 import server, termino
from tutela2.config import Config, LLMConfig
from tutela2.rutas_ajustes_apoderados import CMD_IDENTIFICAR


def _envelope(estado: str, **extra) -> dict:
    return {"ok": True, "estado": estado, "payload": None, "salidas": [], "resumen": {}, "error": None, **extra}


@pytest.fixture
def api(monkeypatch) -> types.SimpleNamespace:
    llamadas: list[tuple] = []
    soltar = threading.Event()
    soltar.set()

    def nuevo(caso_dir):
        llamadas.append(("nuevo", Path(caso_dir)))
        logging.getLogger("tutela2.x").info("paso uno del borrador")
        soltar.wait(5)
        return _envelope("esperando_decision", payload={"reparos": []})

    def decidir(caso_dir, decision):
        llamadas.append(("decidir", Path(caso_dir), decision))
        return _envelope("terminado")

    def continuar(caso_dir, forzar=False):
        llamadas.append(("continuar", Path(caso_dir), forzar))
        raise RuntimeError("fallo simulado")

    def estado(caso_dir):
        return _envelope("sin_iniciar")

    def iniciar(caso_dir):
        llamadas.append(("iniciar", Path(caso_dir)))
        return _envelope("esperando_decision")

    def revisar(caso_dir, roles, auto):
        llamadas.append(("revisar", Path(caso_dir), roles, auto))
        return _envelope("revision")

    fake = types.ModuleType("tutela2.api")
    fake.config_default = lambda: Config().model_dump()
    fake.prompts_default = lambda: {"apertura": "texto apertura"}
    fake.nuevo, fake.decidir, fake.continuar, fake.estado = nuevo, decidir, continuar, estado
    fake.iniciar, fake.revisar = iniciar, revisar
    monkeypatch.setitem(sys.modules, "tutela2.api", fake)
    return types.SimpleNamespace(modulo=fake, llamadas=llamadas, soltar=soltar)


_VARIABLES_ENTORNO = ("TUTELA2_MODELO", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "JEV_API_KEY")


@pytest.fixture(autouse=True)
def _entorno_intacto():
    antes = {var: os.environ.get(var) for var in _VARIABLES_ENTORNO}
    yield
    assert {var: os.environ.get(var) for var in _VARIABLES_ENTORNO} == antes


@pytest.fixture
def cliente(tmp_path, monkeypatch, api) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    for var in _VARIABLES_ENTORNO:
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    server.JOBS.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


def _subir(cliente: TestClient, nombre: str, archivos: dict[str, bytes]):
    files = [("files", (ruta, contenido, "application/pdf")) for ruta, contenido in archivos.items()]
    return cliente.post("/api/casos", data={"nombre": nombre}, files=files)


def _esperar(cliente: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    limite = time.time() + timeout
    while time.time() < limite:
        job = cliente.get(f"/api/jobs/{job_id}").json()
        if job["estado"] != "corriendo":
            return job
        time.sleep(0.02)
    raise AssertionError("el job no terminó")


@pytest.fixture
def caso(cliente) -> str:
    return _subir(cliente, "Caso Uno", {"Raiz/01PrimeraInstancia/a.pdf": b"%PDF-a"}).json()["id"]


@pytest.mark.parametrize(
    "nombre, esperado",
    [
        ("Raiz/01PrimeraInstancia/a.pdf", ("Raiz", "01PrimeraInstancia", "a.pdf")),
        ("a.pdf", ("a.pdf",)),
        ("./x//y.pdf", ("x", "y.pdf")),
        ("Raiz\\sub\\a.pdf", ("Raiz", "sub", "a.pdf")),
    ],
)
def test_sanear_ruta_valida(nombre, esperado):
    assert server.sanear_ruta(nombre) == esperado


@pytest.mark.parametrize(
    "nombre",
    ["../a.pdf", "a/../../b.pdf", "/etc/passwd", "C:\\x\\a.pdf", "a/..", "..\\a.pdf", "", None, "a\x00.pdf", "/", "./"],
)
def test_sanear_ruta_rechaza(nombre):
    with pytest.raises(ValueError):
        server.sanear_ruta(nombre)


def test_quitar_carpeta_raiz():
    assert server.quitar_carpeta_raiz([("R", "a", "x"), ("R", "y")]) == [("a", "x"), ("y",)]
    assert server.quitar_carpeta_raiz([("R", "x"), ("S", "y")]) == [("R", "x"), ("S", "y")]
    assert server.quitar_carpeta_raiz([("x",), ("R", "y")]) == [("x",), ("R", "y")]


def test_subida_conserva_subcarpetas_y_quita_raiz(cliente, tmp_path):
    r = _subir(
        cliente,
        "Caso Ñandú 1",
        {
            "MiCarpeta/01PrimeraInstancia/Fallo ñ.pdf": b"%PDF-1",
            "MiCarpeta/02SegundaInstancia/ActaReparto.pdf": b"%PDF-2",
            "MiCarpeta/.DS_Store": b"basura",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"id": "caso-nandu-1", "n_insumos": 2}
    insumos = tmp_path / "casos" / "caso-nandu-1" / "insumos"
    assert (insumos / "01PrimeraInstancia" / "Fallo ñ.pdf").read_bytes() == b"%PDF-1"
    assert (insumos / "02SegundaInstancia" / "ActaReparto.pdf").read_bytes() == b"%PDF-2"
    assert not (insumos / ".DS_Store").exists()
    assert not (insumos / "MiCarpeta").exists()


def test_subida_sin_carpeta_raiz_deja_rutas(cliente, tmp_path):
    _subir(cliente, "plano", {"a.pdf": b"1", "b.pdf": b"2"})
    assert sorted(p.name for p in (tmp_path / "casos" / "plano" / "insumos").iterdir()) == ["a.pdf", "b.pdf"]


@pytest.mark.parametrize("malo", ["Raiz/../../../evil.pdf", "/tmp/evil.pdf", "Raiz/../evil.pdf", "..\\evil.pdf"])
def test_subida_rechaza_rutas_peligrosas(cliente, tmp_path, malo):
    r = _subir(cliente, "Caso", {"Raiz/ok.pdf": b"1", malo: b"2"})
    assert r.status_code == 400
    assert not (tmp_path / "casos").exists() or list((tmp_path / "casos").iterdir()) == []
    assert not (tmp_path / "evil.pdf").exists()


def test_subida_valida_nombre_y_archivos(cliente):
    assert _subir(cliente, "   ", {"a.pdf": b"1"}).status_code == 200
    assert _subir(cliente, "x", {".DS_Store": b"1"}).status_code == 400
    assert cliente.post("/api/casos", data={"nombre": "x"}).status_code == 422


def test_nombre_repetido_agrega_sufijo(cliente):
    assert _subir(cliente, "Mismo", {"a.pdf": b"1"}).json()["id"] == "mismo"
    assert _subir(cliente, "Mismo", {"a.pdf": b"1"}).json()["id"] == "mismo-2"


def test_listar_casos(cliente, caso):
    (fila,) = cliente.get("/api/casos").json()
    assert (fila["id"], fila["estado"], fila["n_insumos"], fila["nombre"]) == (caso, "sin_iniciar", 1, "Caso Uno")


def test_listar_casos_sin_carpeta(cliente):
    assert cliente.get("/api/casos").json() == []


def test_config_por_defecto_y_round_trip(cliente, caso):
    assert cliente.get(f"/api/casos/{caso}/config").json() == Config().model_dump()
    cfg = Config().model_dump()
    cfg["plantilla_gen"] = "A"
    cfg["llm"]["effort"] = "low"
    cfg["llm"]["modelo_por_nodo"] = {"apertura": "claude-haiku-5-5"}
    cfg["rango_palabras"]["antecedentes"] = [100, 200]
    cfg["prompts_override"] = {"apertura": "mi prompt"}
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 200
    assert r.json() == cfg
    assert cliente.get(f"/api/casos/{caso}/config").json() == cfg


def test_config_invalida_no_se_guarda(cliente, caso, tmp_path):
    cfg = Config().model_dump()
    cfg["llm"]["effort"] = "ultra"
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 422
    assert r.json()["detail"]["errores"][0]["campo"] == "llm.effort"
    assert not (tmp_path / "casos" / caso / "config.json").exists()


def test_config_caso_inexistente(cliente):
    assert cliente.get("/api/casos/nada/config").status_code == 404
    assert cliente.put("/api/casos/nada/config", json={}).status_code == 404


def test_defaults_vienen_de_api(cliente):
    assert cliente.get("/api/config-default").json() == Config().model_dump()
    assert cliente.get("/api/prompts-default").json() == {"apertura": "texto apertura"}


def test_job_nuevo_ciclo_de_vida(cliente, caso, api):
    api.soltar.clear()
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "corriendo"
    durante = cliente.get(f"/api/casos/{caso}/estado").json()
    assert durante["job_activo"] == job_id
    # La lectura del expediente no es el grafo: /estado conserva lo que dice ``api.estado``.
    assert durante["estado"] == "sin_iniciar"
    assert cliente.get("/api/casos").json()[0]["estado"] == "corriendo"

    segundo = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "continuar"})
    assert segundo.status_code == 409

    api.soltar.set()
    job = _esperar(cliente, job_id)
    assert job["estado"] == "terminado"
    assert job["error"] is None
    assert job["resultado"]["estado"] == "esperando_decision"
    assert any("paso uno del borrador" in linea for linea in job["log"])
    assert api.llamadas[0][0] == "nuevo"
    assert cliente.get(f"/api/casos/{caso}/estado").json()["job_activo"] is None


_A_MEDIAS = "El proceso quedó a medias en apertura. Use continuar para reanudarlo."


def _estado_a_medias(caso_dir):
    # Lo que ``api.estado`` lee de un checkpoint intermedio; ``tope_intentos`` simula la clave que añade #22.
    return {**_envelope("error"), "ok": False, "error": _A_MEDIAS, "tope_intentos": True}


@pytest.mark.parametrize("cmd", ["iniciar", "continuar", "decidir"])
def test_estado_durante_un_job_del_grafo_dice_corriendo(cliente, caso, api, cmd):
    def bloqueado(caso_dir, *args, **kwargs):
        api.soltar.wait(5)
        return _envelope("esperando_decision")

    api.modulo.estado = _estado_a_medias
    setattr(api.modulo, cmd, bloqueado)
    cuerpo = {"cmd": cmd}
    if cmd == "decidir":
        cuerpo["decision"] = {"accion": "rehacer_consideraciones", "instruccion": "x"}
    api.soltar.clear()
    try:
        job_id = cliente.post(f"/api/casos/{caso}/run", json=cuerpo).json()["job_id"]
        durante = cliente.get(f"/api/casos/{caso}/estado").json()
        assert durante["estado"] == "corriendo"
        assert durante["ok"] is True
        assert durante["error"] is None
        assert durante["payload"] is None
        assert durante["job_activo"] == job_id
        assert "tope_intentos" not in durante
    finally:
        api.soltar.set()
    _esperar(cliente, job_id)
    despues = cliente.get(f"/api/casos/{caso}/estado").json()
    assert despues["estado"] == "error"
    assert despues["error"] == _A_MEDIAS
    assert despues["tope_intentos"] is True
    assert despues["job_activo"] is None


def test_estado_durante_identificar_apoderados_no_cambia(cliente, caso, api, monkeypatch):
    # Identificar apoderados de casos anteriores corre mientras el caso espera la decisión: no es el grafo.
    api.modulo.estado = lambda caso_dir: _envelope("esperando_decision", payload={"reparos": []})
    job = {"id": "x", "caso": caso, "cmd": CMD_IDENTIFICAR, "estado": "corriendo", "log": [], "resultado": None, "error": None}
    monkeypatch.setitem(server.JOBS, "x", job)
    estado = cliente.get(f"/api/casos/{caso}/estado").json()
    assert estado["estado"] == "esperando_decision"
    assert estado["ok"] is True
    assert estado["payload"] == {"reparos": []}
    assert estado["job_activo"] == "x"


def test_job_con_excepcion_queda_en_error(cliente, caso):
    job_id = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "continuar"}).json()["job_id"]
    job = _esperar(cliente, job_id)
    assert job["estado"] == "error"
    assert job["error"] == "fallo simulado"
    assert any("fallo simulado" in linea for linea in job["log"])


def test_job_con_ok_falso_queda_en_error(cliente, caso, api):
    api.modulo.nuevo = lambda caso_dir: {**_envelope("error"), "ok": False, "error": "Faltan insumos"}
    job_id = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"}).json()["job_id"]
    job = _esperar(cliente, job_id)
    assert job["estado"] == "error"
    assert job["error"] == "Faltan insumos"
    assert job["resultado"]["estado"] == "error"


def test_el_log_de_un_job_no_recibe_el_de_otro(cliente, caso, api):
    otro = _subir(cliente, "Otro", {"a.pdf": b"1"}).json()["id"]
    api.soltar.clear()
    j1 = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"}).json()["job_id"]
    logging.getLogger("tutela2.x").info("mensaje ajeno al job")
    api.soltar.set()
    cliente.post(f"/api/casos/{otro}/run", json={"cmd": "nuevo"})
    job = _esperar(cliente, j1)
    assert not any("mensaje ajeno al job" in linea for linea in job["log"])


def test_run_valida_comando_y_decision(cliente, caso):
    assert cliente.post(f"/api/casos/{caso}/run", json={"cmd": "borrar"}).status_code == 422
    assert cliente.post(f"/api/casos/{caso}/run", json={"cmd": "decidir"}).status_code == 422
    assert cliente.post("/api/casos/nada/run", json={"cmd": "nuevo"}).status_code == 404
    assert cliente.get("/api/jobs/inexistente").status_code == 404


def test_decidir_pasa_la_decision_intacta_a_api(cliente, caso, api):
    decision = {"accion": "decidir", "resultado": "REVOCAR", "sustitutiva": "NEGAR", "eje": "porque sí ñ"}
    job_id = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "decidir", "decision": decision}).json()["job_id"]
    job = _esperar(cliente, job_id)
    assert job["estado"] == "terminado"
    assert api.llamadas[0][2] == decision


DECISION_COMPLETA = {
    "accion": "decidir",
    "resultado": "REVOCAR",
    "sustitutiva": "AMPARAR",
    "eje": "Procede el amparo.",
    "ordenes": [{"destinatario": "la EPS X", "conducta": "cumpla", "plazo": {"n": 24, "unidad": "horas_habiles"}}],
}


def _con_plazo(n) -> dict:
    return {**DECISION_COMPLETA, "ordenes": [{"destinatario": "la EPS X", "conducta": "cumpla", "plazo": {"n": n, "unidad": "dias"}}]}


# (decisión, campos rechazados, mensaje exacto o None si solo se fija el campo)
DECISIONES_RECHAZADAS = [
    pytest.param({**DECISION_COMPLETA, "fecha_fallo": "20266-11-17"}, ["fecha_fallo"], None, id="fecha-de-seis-digitos"),
    # La vista previa recorta la fecha y la acepta; el grafo no: la compuerta tiene que rechazarla igual.
    pytest.param({**DECISION_COMPLETA, "fecha_fallo": " 2026-11-17"}, ["fecha_fallo"], None, id="fecha-con-espacio"),
    pytest.param({**DECISION_COMPLETA, "fecha_fallo": ""}, ["fecha_fallo"], None, id="fecha-vacia"),
    pytest.param(
        _con_plazo(10_000_000), ["ordenes.0.plazo.n"], "El plazo de la orden 1 no puede superar 999.999.", id="plazo-enorme"
    ),
    pytest.param(_con_plazo(-5), ["ordenes.0.plazo.n"], "El plazo de cada orden debe ser mayor que cero.", id="plazo-negativo"),
    pytest.param(_con_plazo(1.5), ["ordenes.0.plazo.n"], "El plazo de cada orden debe ser un número entero.", id="plazo-decimal"),
    pytest.param({"accion": "rehacer_apertura"}, ["instruccion"], None, id="rehacer-sin-instruccion"),
    pytest.param({**DECISION_COMPLETA, "eje": ""}, ["eje"], "Falta el eje: 2 a 5 líneas con el porqué de la decisión.", id="sin-eje"),
]


@pytest.mark.parametrize("decision, campos, mensaje", DECISIONES_RECHAZADAS)
def test_run_decidir_rechaza_la_decision_invalida_sin_crear_el_job(cliente, caso, api, decision, campos, mensaje):
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "decidir", "decision": decision})
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert [e["campo"] for e in detalle["errores"]] == campos
    assert all(e["mensaje"] for e in detalle["errores"])
    if mensaje:
        assert detalle["errores"][0]["mensaje"] == mensaje
    assert detalle["mensaje"].startswith("Su decisión no se aplicó: ")
    assert detalle["errores"][0]["mensaje"] in detalle["mensaje"]
    assert server.JOBS == {}
    assert api.llamadas == []


def test_run_decidir_rechaza_antes_de_mirar_si_hay_otra_ejecucion(cliente, caso, api):
    api.soltar.clear()
    try:
        assert cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"}).status_code == 200
        r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "decidir", "decision": {"accion": "rehacer_apertura"}})
        assert r.status_code == 422 and r.json()["detail"]["errores"][0]["campo"] == "instruccion"
    finally:
        api.soltar.set()
        for job in list(server.JOBS):
            _esperar(cliente, job)


def test_run_decidir_rehacer_valido_pasa_la_compuerta(cliente, caso, api):
    decision = {"accion": "rehacer_apertura", "instruccion": "Más breve."}
    job_id = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "decidir", "decision": decision}).json()["job_id"]
    assert _esperar(cliente, job_id)["estado"] == "terminado"
    assert api.llamadas[0][2] == decision


def test_estado_incluye_job_activo_y_falla_con_mensaje(cliente, caso, api, tmp_path):
    api.modulo.estado = lambda caso_dir: (_ for _ in ()).throw(RuntimeError("sqlite roto"))
    r = cliente.get(f"/api/casos/{caso}/estado")
    assert r.status_code == 500
    assert "sqlite roto" in r.json()["detail"]
    (tmp_path / "casos" / caso / ".resumen.json").unlink()
    assert cliente.get("/api/casos").json()[0]["estado"] == "error"


@pytest.fixture
def con_salidas(cliente, caso, tmp_path) -> Path:
    base = tmp_path / "casos" / caso
    (base / "salidas").mkdir()
    (base / "salidas" / "fallo.docx").write_bytes(b"PK-docx")
    (base / "config.json").write_text("SECRETO-CONFIG")
    (tmp_path / "fuera.txt").write_text("SECRETO-FUERA")
    (base / "salidas" / "enlace.docx").symlink_to(tmp_path / "fuera.txt")
    (base / "salidas" / "carpeta").mkdir()
    return base


def test_descarga_salida(cliente, caso, con_salidas):
    r = cliente.get(f"/api/casos/{caso}/salidas/fallo.docx")
    assert r.status_code == 200
    assert r.content == b"PK-docx"
    assert r.headers["content-type"] == server.DOCX
    assert "attachment" in r.headers["content-disposition"]
    assert cliente.get(f"/api/casos/{caso}/salidas/no_existe.docx").status_code == 404


@pytest.mark.parametrize("archivo", ["..", "../config.json", "a..docx", "enlace.docx", "carpeta", "sub/no.docx", "/etc/passwd", ""])
def test_guardia_de_salidas_directa(cliente, caso, con_salidas, archivo):
    with pytest.raises(HTTPException) as exc:
        server._ruta_salida(caso, archivo)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "../config.json",
        "..%2Fconfig.json",
        "%2e%2e%2fconfig.json",
        "..%2f..%2ffuera.txt",
        "enlace.docx",
        "%2Fetc%2Fpasswd",
    ],
)
def test_descarga_no_filtra_archivos_fuera_de_salidas(cliente, caso, con_salidas, url):
    r = cliente.get(f"/api/casos/{caso}/salidas/{url}")
    assert r.status_code in (404, 405)
    assert b"SECRETO" not in r.content


def test_descarga_anidada(cliente, caso, con_salidas):
    ruta = "02SegundaInstancia/C01Principal/003FalloSegunda202600530.docx"
    for rel, datos in [("trabajo/previo.docx", b"PK-previo"), (ruta, b"PK-fallo")]:
        destino = con_salidas / "salidas" / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    r = cliente.get(f"/api/casos/{caso}/salidas/trabajo/previo.docx")
    assert (r.status_code, r.content) == (200, b"PK-previo")
    assert r.headers["content-type"] == server.DOCX
    r = cliente.get(f"/api/casos/{caso}/salidas/{ruta}")
    assert (r.status_code, r.content) == (200, b"PK-fallo")
    assert cliente.get(f"/api/casos/{caso}/salidas/trabajo/otro.docx").status_code == 404
    assert cliente.get(f"/api/casos/{caso}/salidas/trabajo").status_code == 404


def test_descarga_anidada_rechaza_escapes(cliente, caso, con_salidas):
    (con_salidas / "salidas" / "trabajo").mkdir()
    for url in ["trabajo/..%2F..%2Fconfig.json", "trabajo/%2e%2e/%2e%2e/config.json", "%2Fetc%2Fpasswd", "trabajo/%2Fetc%2Fpasswd"]:
        r = cliente.get(f"/api/casos/{caso}/salidas/{url}")
        assert r.status_code == 404
        assert b"SECRETO" not in r.content


def test_arbol_de_salidas(cliente, caso, con_salidas):
    for rel in ["trabajo/previo.docx", "02SegundaInstancia/C01Principal/001A.docx"]:
        destino = con_salidas / "salidas" / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"x")
    archivos = cliente.get(f"/api/casos/{caso}/salidas").json()["archivos"]
    assert "trabajo/previo.docx" in archivos
    assert "02SegundaInstancia/C01Principal/001A.docx" in archivos
    assert archivos == sorted(archivos)
    assert not any(a.startswith(("/", "..")) or "SECRETO" in a for a in archivos)
    assert cliente.get("/api/casos/nada/salidas").status_code == 404


def test_arbol_de_salidas_oculta_las_vistas_y_sus_temporales(cliente, caso, con_salidas):
    for rel in ["trabajo/previo.docx", "trabajo/previo.vista.json", "trabajo/.previo.vista.json.tmp"]:
        destino = con_salidas / "salidas" / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"x")
    archivos = cliente.get(f"/api/casos/{caso}/salidas").json()["archivos"]
    assert "trabajo/previo.docx" in archivos
    assert not any(".vista.json" in a for a in archivos)
    with zipfile.ZipFile(io.BytesIO(cliente.get(f"/api/casos/{caso}/zip").content)) as z:
        assert not any(".vista.json" in n for n in z.namelist())


def test_zip_con_rutas_relativas(cliente, caso, con_salidas):
    destino = con_salidas / "salidas" / "trabajo" / "previo.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(b"PK-previo")
    r = cliente.get(f"/api/casos/{caso}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="{caso}.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert z.testzip() is None
        nombres = z.namelist()
        assert "trabajo/previo.docx" in nombres
        assert z.read("trabajo/previo.docx") == b"PK-previo"
    assert not any(n.startswith(("/", "..")) for n in nombres)
    assert all(b"SECRETO" not in z for z in [r.content])
    assert cliente.get("/api/casos/nada/zip").status_code == 404


def test_run_iniciar(cliente, caso, api):
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "iniciar"})
    assert r.status_code == 200
    job = _esperar(cliente, r.json()["job_id"])
    assert job["estado"] == "terminado"
    assert job["resultado"]["estado"] == "esperando_decision"
    assert api.llamadas[0][0] == "iniciar"


def _dir(caso: str) -> Path:
    return server.casos_dir() / caso


def _hilo_con_fila(ruta: Path) -> None:
    con = sqlite3.connect(ruta)
    with con:
        con.execute("CREATE TABLE checkpoints (thread_id TEXT)")
        con.execute("INSERT INTO checkpoints VALUES ('x')")
    con.close()


def _previo(caso: str) -> None:
    previo = _dir(caso) / "salidas" / "trabajo" / "previo.docx"
    previo.parent.mkdir(parents=True, exist_ok=True)
    previo.write_bytes(b"PK-previo")


def test_run_nuevo_con_trabajo_previo_responde_409(cliente, caso, api):
    (_dir(caso) / "decision.json").write_text("{}", encoding="utf-8")
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["codigo"] == "trabajo_previo" and detalle["trabajo"] == ["la decisión del juez"]
    assert "Este caso ya tiene la decisión del juez." in detalle["mensaje"] and "papelera" in detalle["mensaje"]
    assert api.llamadas == [] and not server.JOBS


def test_run_nuevo_con_descartar_llama_a_api_con_descartar(cliente, caso, api):
    (_dir(caso) / "decision.json").write_text("{}", encoding="utf-8")
    vistos: list[bool] = []

    def nuevo(caso_dir, descartar=False):
        vistos.append(descartar)
        return _envelope("revision")

    api.modulo.nuevo = nuevo
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo", "descartar": True})
    assert r.status_code == 200
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert vistos == [True]


def test_run_nuevo_sin_trabajo_previo_no_pasa_descartar(cliente, caso, api):
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    assert r.status_code == 200
    # El módulo falso define ``nuevo(caso_dir)``: pasarle ``descartar`` lo haría fallar con TypeError.
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert api.llamadas[0][0] == "nuevo"


def test_run_iniciar_con_hilo_sano_no_responde_409_por_descarte(cliente, caso, api):
    _hilo_con_fila(_dir(caso) / "hilo.sqlite")
    _previo(caso)
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "iniciar"})
    assert r.status_code == 200
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert api.llamadas[0][0] == "iniciar"


def test_run_iniciar_sin_hilo_con_salidas_responde_409(cliente, caso, api):
    _previo(caso)
    (_dir(caso) / "decision.json").write_text("{}", encoding="utf-8")
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "iniciar"})
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["codigo"] == "trabajo_previo" and detalle["trabajo"] == ["el borrador", "la decisión del juez"]
    assert "cuyo historial se perdió" in detalle["mensaje"]
    assert api.llamadas == []
    vistos: list[bool] = []

    def iniciar(caso_dir, descartar=False):
        vistos.append(descartar)
        return _envelope("esperando_decision")

    api.modulo.iniciar = iniciar
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "iniciar", "descartar": True})
    assert r.status_code == 200
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert vistos == [True]


def test_run_iniciar_con_hilo_basura_y_sin_salidas_crea_job(cliente, caso, api):
    (_dir(caso) / "hilo.sqlite").write_bytes(b"basura" * 100)
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "iniciar"})
    assert r.status_code == 200
    _esperar(cliente, r.json()["job_id"])
    assert api.llamadas[0][0] == "iniciar"


def test_run_continuar_no_mira_el_trabajo_previo(cliente, caso, api):
    (_dir(caso) / "decision.json").write_text("{}", encoding="utf-8")
    _previo(caso)
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "continuar"})
    assert r.status_code == 200
    _esperar(cliente, r.json()["job_id"])
    assert api.llamadas[0][0] == "continuar"


def test_estado_con_job_activo_no_avisa_historial_perdido(cliente, caso, api):
    api.modulo.estado = lambda caso_dir: _envelope("revision", historial_perdido=True, trabajo_previo=["el borrador"])
    assert cliente.get(f"/api/casos/{caso}/estado").json()["historial_perdido"] is True
    api.soltar.clear()
    cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    durante = cliente.get(f"/api/casos/{caso}/estado").json()
    assert "historial_perdido" not in durante and "trabajo_previo" not in durante
    api.soltar.set()


def test_revision_llama_a_api_revisar(cliente, caso, api):
    cuerpo = {"roles": {"d1": "fallo_1a"}, "auto": {"accionante": "X"}}
    r = cliente.put(f"/api/casos/{caso}/revision", json=cuerpo)
    assert r.status_code == 200
    assert r.json()["estado"] == "revision"
    assert api.llamadas[0][0] == "revisar"
    assert api.llamadas[0][2:] == (cuerpo["roles"], cuerpo["auto"])
    cliente.put(f"/api/casos/{caso}/revision", json={})
    assert api.llamadas[1][2:] == (None, None)


def test_revision_con_job_corriendo_es_409(cliente, caso, api):
    api.soltar.clear()
    cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    r = cliente.put(f"/api/casos/{caso}/revision", json={"roles": {}})
    assert r.status_code == 409
    assert not any(c[0] == "revisar" for c in api.llamadas)
    api.soltar.set()


def test_revision_caso_inexistente_y_error_de_api(cliente, caso, api):
    assert cliente.put("/api/casos/nada/revision", json={}).status_code == 404
    api.modulo.revisar = lambda caso_dir, roles, auto: (_ for _ in ()).throw(RuntimeError("hilo existente"))
    r = cliente.put(f"/api/casos/{caso}/revision", json={})
    assert r.status_code == 500
    assert "hilo existente" in r.json()["detail"]


def test_caso_con_ruta_peligrosa_es_404(cliente, caso, con_salidas):
    for malo in ["..", "%2e%2e", "..%2f", ".hidden"]:
        r = cliente.get(f"/api/casos/{malo}/salidas/fallo.docx")
        assert r.status_code == 404
    with pytest.raises(HTTPException):
        server._dir_caso("..")
    with pytest.raises(HTTPException):
        server._dir_caso("a/b")


def test_api_key_solo_en_memoria(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cliente.get("/api/estado-servidor").json()["api_key"] is False
    r = cliente.post("/api/api-key", json={"key": "  sk-ant-prueba-123  "})
    assert r.status_code == 200
    assert "sk-ant" not in r.text
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-prueba-123"
    assert cliente.get("/api/estado-servidor").json()["api_key"] is True
    assert "sk-ant" not in cliente.get("/api/estado-servidor").text
    _subir(cliente, "x", {"a.pdf": b"1"})
    assert not any(b"sk-ant-prueba" in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    monkeypatch.delenv("ANTHROPIC_API_KEY")


def test_estado_servidor_trae_los_festivos_del_anio_anterior_actual_y_siguiente(cliente, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: date(2026, 11, 17))
    festivos = cliente.get("/api/estado-servidor").json()["festivos"]
    assert festivos == sorted(festivos) and len(festivos) == len(set(festivos)) == 17 + 19 + 19
    assert {f[:4] for f in festivos} == {"2025", "2026", "2027"}
    assert {"2025-12-25", "2026-11-16", "2026-12-08", "2027-01-11"} <= set(festivos)
    assert "2026-11-17" not in festivos and all(date.fromisoformat(f) for f in festivos)


def test_los_festivos_del_servidor_siguen_el_anio_de_colombia(cliente, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: date(2027, 1, 1))
    assert {f[:4] for f in cliente.get("/api/estado-servidor").json()["festivos"]} == {"2026", "2027", "2028"}


def test_clave_de_gemini_solo_en_memoria(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    estado = cliente.get("/api/estado-servidor").json()
    assert estado["gemini_key"] is False and estado["api_key"] is False
    r = cliente.post("/api/gemini-key", json={"key": "  AIza-prueba-456  "})
    assert r.status_code == 200 and r.json() == {"gemini_key": True}
    assert "AIza" not in r.text
    assert os.environ["GEMINI_API_KEY"] == "AIza-prueba-456"
    estado = cliente.get("/api/estado-servidor")
    assert estado.json()["gemini_key"] is True and estado.json()["api_key"] is False and "AIza" not in estado.text
    assert "AIza" not in cliente.get("/api/ia").text
    _subir(cliente, "x", {"a.pdf": b"1"})
    assert not any(b"AIza-prueba" in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    monkeypatch.delenv("GEMINI_API_KEY")


def test_clave_de_gemini_vacia_se_rechaza(cliente, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = cliente.post("/api/gemini-key", json={"key": " \n "})
    assert r.status_code == 422 and r.json()["detail"] == "La clave de Gemini no puede estar vacía."
    assert "GEMINI_API_KEY" not in os.environ


@pytest.mark.parametrize("clave", ["AIzaSECRETO\r\nX", "AIzaSECRETO\nx", "AIza SECRETO", "clave​SECRETO", "AIzañandú"])
def test_clave_de_gemini_con_caracteres_no_validos_se_rechaza_sin_repetirla(cliente, monkeypatch, clave):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = cliente.post("/api/gemini-key", json={"key": clave})
    assert r.status_code == 422 and "GEMINI_API_KEY" not in os.environ
    assert "SECRETO" not in r.text and "ñandú" not in r.text


def test_api_key_vacia_se_rechaza(cliente, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cliente.post("/api/api-key", json={"key": "   "}).status_code == 422
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_modelo_global_se_elige_persiste_y_aplica(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("TUTELA2_MODELO", raising=False)
    estado = cliente.get("/api/estado-servidor").json()
    assert estado["modelo"] == "claude-sonnet-5-5"
    assert estado["modelos"] == ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]
    assert cliente.post("/api/modelo", json={"modelo": "claude-fable-5-1"}).status_code == 422
    assert cliente.post("/api/modelo", json={"modelo": "claude-haiku-5-5"}).json() == {"modelo": "claude-haiku-5-5"}
    assert cliente.get("/api/estado-servidor").json()["modelo"] == "claude-haiku-5-5"
    assert json.loads((tmp_path / "casos" / ".preferencias.json").read_text()) == {"modelo": "claude-haiku-5-5"}
    monkeypatch.delenv("TUTELA2_MODELO")
    caso_dir = tmp_path / "casos" / "c1"
    caso_dir.mkdir()
    cfgmod.guardar(caso_dir, Config(llm=LLMConfig(modelo="claude-opus-5-5")))
    server._comando("nuevo", caso_dir, None)
    assert cfgmod.cargar(caso_dir).llm.modelo == "claude-haiku-5-5"
    assert [c["id"] for c in cliente.get("/api/casos").json()] == ["c1"]


def test_modelos_permitidos_restringen_la_lista_y_la_eleccion(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("TUTELA2_MODELO", raising=False)
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-sonnet-5-5, claude-haiku-5-5")
    assert cliente.get("/api/estado-servidor").json()["modelos"] == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    r = cliente.post("/api/modelo", json={"modelo": "claude-opus-5-5"})
    assert r.status_code == 422
    assert "claude-opus-5-5" in r.json()["detail"] and "claude-sonnet-5-5, claude-haiku-5-5" in r.json()["detail"]
    assert not (tmp_path / "casos" / ".preferencias.json").exists()
    assert cliente.post("/api/modelo", json={"modelo": "claude-haiku-5-5"}).json() == {"modelo": "claude-haiku-5-5"}
    monkeypatch.delenv("TUTELA2_MODELO")


def test_sirve_la_interfaz_compilada(cliente, tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "dist").mkdir(parents=True)
    (static / "dist" / "index.html").write_text("<!doctype html><title>Judicabot</title>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC", static)
    r = cliente.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Judicabot" in r.text


def test_rechaza_hosts_externos(cliente):
    assert cliente.get("/api/estado-servidor", headers={"host": "evil.example.com"}).status_code == 400


def test_revision_ok_falso_no_es_200(cliente, caso, api):
    api.modulo.revisar = lambda caso_dir, roles, auto: {**_envelope("error"), "ok": False, "error": "El caso ya se inició."}
    r = cliente.put(f"/api/casos/{caso}/revision", json={})
    assert r.status_code == 409
    assert r.json()["detail"] == "El caso ya se inició."
    api.modulo.revisar = lambda caso_dir, roles, auto: {**_envelope("revision"), "ok": False, "error": "Rol inválido."}
    assert cliente.put(f"/api/casos/{caso}/revision", json={}).status_code == 422


def test_estado_con_hilo_incluye_ingesta(cliente, caso, api, tmp_path):
    base = tmp_path / "casos" / caso
    assert "ingesta" not in cliente.get(f"/api/casos/{caso}/estado").json()
    (base / "hilo.sqlite").write_bytes(b"")
    (base / "caso.json").write_text("{}")
    api.modulo._cargar_ingesta = lambda caso_dir: "ing"
    api.modulo._resumen_ingesta = lambda caso_dir, ing: {"documentos": [{"doc_id": "1a-001"}], "ing": ing}
    r = cliente.get(f"/api/casos/{caso}/estado").json()
    assert r["ingesta"]["documentos"][0]["doc_id"] == "1a-001"


def test_log_del_job_no_incluye_traza(cliente, caso, api):
    def nuevo(caso_dir):
        try:
            raise ValueError("interno")
        except ValueError:
            logging.getLogger("tutela2.x").exception("Falló algo")
        return _envelope("revision")

    api.modulo.nuevo = nuevo
    job = _esperar(cliente, cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"}).json()["job_id"])
    texto = "\n".join(job["log"])
    assert "Falló algo" in texto
    assert "Traceback" not in texto


def test_config_invalida_mensajes_en_espanol(cliente, caso):
    cfg = Config().model_dump()
    cfg["max_intentos"] = 2.5
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 422
    mensajes = [e["mensaje"] for e in r.json()["detail"]["errores"]]
    assert mensajes and not any("Input should" in m for m in mensajes)


@pytest.mark.parametrize("cuerpo, esperado", [({"cmd": "continuar"}, False), ({"cmd": "continuar", "forzar": True}, True)])
def test_run_pasa_forzar_a_continuar(cliente, caso, api, cuerpo, esperado):
    job_id = cliente.post(f"/api/casos/{caso}/run", json=cuerpo).json()["job_id"]
    _esperar(cliente, job_id)
    assert api.llamadas[-1][0] == "continuar" and api.llamadas[-1][2] is esperado


def test_config_no_hornea_el_modelo_del_entorno(cliente, caso, tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELO", "claude-opus-5-5")
    assert cliente.get(f"/api/casos/{caso}/config").json()["llm"]["modelo"] == "claude-sonnet-5-5"
    cfg = cliente.get(f"/api/casos/{caso}/config").json()
    assert cliente.put(f"/api/casos/{caso}/config", json=cfg).status_code == 200
    guardado = json.loads((tmp_path / "casos" / caso / "config.json").read_text(encoding="utf-8"))
    assert guardado["llm"]["modelo"] == "claude-sonnet-5-5"
    assert cfgmod.cargar(tmp_path / "casos" / caso).llm.modelo == "claude-opus-5-5"
    assert cfgmod.cargar(tmp_path / "casos" / caso, entorno=False).llm.modelo == "claude-sonnet-5-5"


def test_jev_key_se_guarda_solo_en_el_entorno(cliente, tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is False
    r = cliente.post("/api/jev-key", json={"key": "  k-jev-prueba-123  "})
    assert r.status_code == 200 and r.json() == {"jev_key": True}
    assert "k-jev-prueba" not in r.text
    assert os.environ["JEV_API_KEY"] == "k-jev-prueba-123"
    estado = cliente.get("/api/estado-servidor")
    assert estado.json()["jev_key"] is True and "k-jev-prueba" not in estado.text
    _subir(cliente, "x", {"a.pdf": b"1"})
    assert not any(b"k-jev-prueba" in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    monkeypatch.delenv("JEV_API_KEY")


def test_jev_key_vacia_se_rechaza(cliente, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente.post("/api/jev-key", json={"key": "   "}).status_code == 422
    assert "JEV_API_KEY" not in os.environ


@pytest.mark.parametrize("clave", ["clave\u2013con-raya", "con espacio", "SECRETO\nx", "clave\u200bx", "ñandú"])
def test_jev_key_con_caracteres_no_validos_se_rechaza_sin_repetirla(cliente, monkeypatch, clave):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    r = cliente.post("/api/jev-key", json={"key": clave})
    assert r.status_code == 422 and "JEV_API_KEY" not in os.environ
    assert "SECRETO" not in r.text and "raya" not in r.text and "ñandú" not in r.text


def test_estado_servidor_informa_si_hay_clave_de_jev(cliente, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is False
    monkeypatch.setenv("JEV_API_KEY", "x")
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is True
    monkeypatch.setenv("JEV_API_KEY", "   ")
    assert cliente.get("/api/estado-servidor").json()["jev_key"] is False


def test_config_de_un_caso_acepta_y_devuelve_los_ajustes_de_jev(cliente, caso):
    cfg = cliente.get(f"/api/casos/{caso}/config").json()
    assert cfg["jev"]["modo"] == "apagado" and cfg["jev"]["umbral_confianza"] == 0.9
    cfg["jev"].update(modo="sombra", umbral_confianza=0.95, timeout_s=30.0, max_chars_cabecera=1200, max_chars_sentido=2000, concurrencia=3)
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 200 and r.json()["jev"]["modo"] == "sombra"
    devuelto = cliente.get(f"/api/casos/{caso}/config").json()["jev"]
    assert devuelto == {**cfg["jev"], "modo": "sombra"}
    assert devuelto["umbral_confianza"] == 0.95 and devuelto["concurrencia"] == 3


def test_config_con_modo_de_jev_invalido_no_se_guarda(cliente, caso):
    cfg = cliente.get(f"/api/casos/{caso}/config").json()
    cfg["jev"]["modo"] = "total"
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 422
    assert r.json()["detail"]["errores"][0] == {"campo": "jev.modo", "mensaje": "no es una de las opciones permitidas."}
    assert cliente.get(f"/api/casos/{caso}/config").json()["jev"]["modo"] == "apagado"


@pytest.mark.parametrize(
    "umbral, mensaje",
    [(90, "como máximo 1"), (-0.1, "al menos 0")],
)
def test_config_con_umbral_de_jev_fuera_de_0_a_1_no_se_guarda(cliente, caso, umbral, mensaje):
    cfg = cliente.get(f"/api/casos/{caso}/config").json()
    cfg["jev"]["umbral_confianza"] = umbral
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 422
    [error] = r.json()["detail"]["errores"]
    assert error["campo"] == "jev.umbral_confianza" and mensaje in error["mensaje"]
    assert cliente.get(f"/api/casos/{caso}/config").json()["jev"]["umbral_confianza"] == 0.9


@pytest.mark.parametrize("timeout", [0, -1])
def test_config_con_tiempo_maximo_de_jev_no_positivo_no_se_guarda(cliente, caso, timeout):
    cfg = cliente.get(f"/api/casos/{caso}/config").json()
    cfg["jev"]["timeout_s"] = timeout
    r = cliente.put(f"/api/casos/{caso}/config", json=cfg)
    assert r.status_code == 422
    [error] = r.json()["detail"]["errores"]
    assert error["campo"] == "jev.timeout_s" and "mayor que 0" in error["mensaje"]
