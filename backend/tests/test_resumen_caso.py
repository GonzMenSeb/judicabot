from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_graph import DECISION, Verificador, ingesta_sintetica

from tutela2 import api, formato_global, ingest, llm, resumen_caso, server
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.esquemas import CasoResumen
from tutela2.llm import ErrorLLM, FakeClient

CAMPOS = set(CasoResumen.model_fields)


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


@pytest.fixture
def caso(tmp_path, monkeypatch) -> Path:
    carpeta = tmp_path / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    real = ingest.reaplicar
    monkeypatch.setattr(ingest, "reaplicar", lambda ing, roles: real(ing, roles).model_copy(update={"metadatos": ing.metadatos}))
    return carpeta


@pytest.fixture
def llamadas_estado(monkeypatch) -> dict[str, int]:
    cuenta = {"n": 0}
    real = api.estado

    def contado(caso_dir):
        cuenta["n"] += 1
        return real(caso_dir)

    monkeypatch.setattr(api, "estado", contado)
    return cuenta


def _cache(caso: Path) -> dict:
    return json.loads((caso / ".resumen.json").read_text(encoding="utf-8"))


def _dato(caso: Path, campo: str):
    return _cache(caso)["datos"][campo]


class FallaEn:
    def __init__(self, nodo: str):
        self.nodo = nodo
        self.base = FakeClient()

    def estructurado(self, nodo, *args, **kwargs):
        if nodo == self.nodo:
            raise ErrorLLM("El modelo rechazó la solicitud.")
        return self.base.estructurado(nodo, *args, **kwargs)


@pytest.mark.parametrize(
    "estado, etapa, siguiente",
    [
        ("sin_iniciar", 0, "Procesar los documentos"),
        ("incompleto", 0, "Completar los documentos"),
        ("revision", 0, "Revisar los documentos"),
        ("esperando_decision", 2, "Revisar el borrador y decidir"),
        ("terminado", 4, "Ver el fallo"),
    ],
)
def test_etapa_y_siguiente_paso_por_estado(estado, etapa, siguiente):
    campos = resumen_caso.campos_desde_estado({"estado": estado, "resumen": {"metadatos": {}}})
    assert (campos["estado"], campos["etapa"], campos["siguiente_paso"]) == (estado, etapa, siguiente)


@pytest.mark.parametrize(
    "resumen, etapa, siguiente",
    [
        ({"decision": None, "metadatos": {}}, 1, "Continuar la ejecución"),
        ({"decision": {"accion": "rehacer_apertura"}}, 1, "Continuar la ejecución"),
        ({"decision": {"accion": "rehacer_consideraciones"}}, 1, "Continuar la ejecución"),
        ({"decision": {"accion": "decidir"}}, 3, "Continuar la ejecución"),
        ({}, 0, "Revisar el error"),
    ],
)
def test_etapa_de_un_error_depende_de_la_ultima_decision(resumen, etapa, siguiente):
    campos = resumen_caso.campos_desde_estado({"estado": "error", "resumen": resumen})
    assert (campos["estado"], campos["etapa"], campos["siguiente_paso"]) == ("error", etapa, siguiente)


@pytest.mark.parametrize("respuesta", [None, "x", {}, {"estado": "inventado", "resumen": {}}])
def test_respuesta_ilegible_es_error_en_etapa_cero(respuesta):
    campos = resumen_caso.campos_desde_estado(respuesta)
    assert (campos["estado"], campos["etapa"], campos["n_alertas"]) == ("error", 0, 0)
    assert campos["radicado"] is None and campos["accionadas"] == []


def test_metadatos_y_alertas_desde_el_estado():
    base = {"cui_1a": "A1", "cui_2a": "B2", "accionante": "Ana", "accionadas": ["X", "Y"], "juzgado_a_quo": "Juzgado 1"}
    campos = resumen_caso.campos_desde_estado(
        {"estado": "revision", "resumen": {"metadatos": base, "alertas": ["a", "b"]}}
    )
    assert campos["radicado"] == "B2" and campos["accionante"] == "Ana" and campos["accionadas"] == ["X", "Y"]
    assert campos["juzgado_a_quo"] == "Juzgado 1" and campos["n_alertas"] == 2
    sin_2a = {**base, "cui_2a": None}
    campos = resumen_caso.campos_desde_estado(
        {"estado": "terminado", "resumen": {"metadatos": sin_2a, "alertas": {"ingesta": ["a"], "caso_concreto": ["b", "c"], "x": []}}}
    )
    assert campos["radicado"] == "A1" and campos["n_alertas"] == 3


def test_flujo_real_deja_el_resumen_al_dia_en_cada_transicion(caso, llamadas_estado):
    assert api.nuevo(caso)["estado"] == "revision"
    assert (_dato(caso, "estado"), _dato(caso, "etapa")) == ("revision", 0)
    assert _dato(caso, "radicado") == "05001400900120260000101" and _dato(caso, "accionante") == "Marta Ejemplo"
    assert _dato(caso, "accionadas") == ["Entidad Prestadora Uno"] and _dato(caso, "juzgado_a_quo") == "Juzgado Primero Municipal"

    assert api.revisar(caso, {"1a-003": "anexo"}, None)["ok"]
    assert _dato(caso, "estado") == "revision"

    assert api.iniciar(caso)["estado"] == "esperando_decision"
    assert (_dato(caso, "estado"), _dato(caso, "etapa"), _dato(caso, "siguiente_paso")) == (
        "esperando_decision",
        2,
        "Revisar el borrador y decidir",
    )

    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    assert (_dato(caso, "estado"), _dato(caso, "etapa"), _dato(caso, "siguiente_paso")) == ("terminado", 4, "Ver el fallo")

    antes = llamadas_estado["n"]
    resumen = resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes
    assert resumen["estado"] == "terminado" and resumen["etapa"] == 4 and resumen["id"] == "caso-api"


def test_error_en_apertura_queda_en_etapa_uno_y_en_caso_concreto_en_tres(caso, monkeypatch):
    api.nuevo(caso)
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: FallaEn("apertura"))
    assert api.iniciar(caso)["estado"] == "error"
    assert (_dato(caso, "estado"), _dato(caso, "etapa"), _dato(caso, "siguiente_paso")) == ("error", 1, "Continuar la ejecución")

    monkeypatch.setattr(llm, "cliente_para", lambda cfg: FakeClient())
    assert api.continuar(caso, forzar=True)["estado"] == "esperando_decision"
    assert _dato(caso, "etapa") == 2

    monkeypatch.setattr(llm, "cliente_para", lambda cfg: FallaEn("caso_concreto"))
    assert api.decidir(caso, DECISION)["estado"] == "error"
    assert (_dato(caso, "estado"), _dato(caso, "etapa")) == ("error", 3)

    monkeypatch.setattr(llm, "cliente_para", lambda cfg: FakeClient())
    assert api.continuar(caso, forzar=True)["estado"] == "terminado"
    assert _dato(caso, "etapa") == 4


def test_se_reconstruye_perezosamente_si_falta_y_se_persiste(caso, llamadas_estado):
    api.nuevo(caso)
    (caso / ".resumen.json").unlink()
    antes = llamadas_estado["n"]
    resumen = resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes + 1
    assert resumen["estado"] == "revision" and set(resumen) == CAMPOS
    assert (caso / ".resumen.json").is_file()
    resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes + 1


@pytest.mark.parametrize("contenido", ["", "no es json", "[]", '{"v": 99, "firma": [], "datos": {}}', '{"v": 1, "firma": [], "datos": {"id": "x"}}'])
def test_cache_corrupto_o_de_otra_version_se_reconstruye(caso, contenido):
    api.nuevo(caso)
    (caso / ".resumen.json").write_text(contenido, encoding="utf-8")
    assert resumen_caso.leer(caso)["estado"] == "revision"
    assert _dato(caso, "estado") == "revision"


@pytest.mark.parametrize("archivo", ["caso.json", "decision.json", "config.json", "hilo.sqlite"])
def test_cambio_de_mtime_invalida_el_cache(caso, llamadas_estado, archivo):
    api.nuevo(caso)
    api.iniciar(caso)
    ruta = caso / archivo
    if not ruta.exists():
        ruta.write_bytes(b"")
    resumen_caso.actualizar(caso)
    antes = llamadas_estado["n"]
    resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes
    futuro = time.time() + 3600
    os.utime(ruta, (futuro, futuro))
    resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes + 1


def test_escritura_en_el_wal_invalida_el_cache(caso, llamadas_estado):
    api.nuevo(caso)
    api.iniciar(caso)
    con = sqlite3.connect(caso / "hilo.sqlite")
    try:
        con.execute("CREATE TABLE t (x)")
        con.commit()
        assert (caso / "hilo.sqlite-wal").exists()
        resumen_caso.actualizar(caso)
        antes = llamadas_estado["n"]
        resumen_caso.leer(caso)
        assert llamadas_estado["n"] == antes
        time.sleep(0.05)
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        resumen_caso.leer(caso)
        assert llamadas_estado["n"] == antes + 1
    finally:
        con.close()


def test_cambio_en_la_carpeta_salidas_invalida_el_cache(caso, llamadas_estado):
    api.nuevo(caso)
    antes = llamadas_estado["n"]
    os.utime(caso / "salidas", (time.time() + 3600, time.time() + 3600))
    resumen_caso.leer(caso)
    assert llamadas_estado["n"] == antes + 1


def test_actualizado_es_la_mayor_mtime_en_iso_utc(caso):
    api.nuevo(caso)
    instante = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()
    os.utime(caso / "caso.json", (instante, instante))
    for otro in ("config.json", "salidas", "insumos"):
        os.utime(caso / otro, (instante - 100, instante - 100))
    assert resumen_caso.leer(caso)["actualizado"] == "2030-01-02T03:04:05+00:00"


def test_tolerar_obsoleto_no_reconstruye_pero_si_falta_el_cache_si(caso, llamadas_estado):
    api.nuevo(caso)
    os.utime(caso / "caso.json", (time.time() + 3600, time.time() + 3600))
    antes = llamadas_estado["n"]
    assert resumen_caso.leer(caso, tolerar_obsoleto=True)["estado"] == "revision"
    assert llamadas_estado["n"] == antes
    (caso / ".resumen.json").unlink()
    resumen_caso.leer(caso, tolerar_obsoleto=True)
    assert llamadas_estado["n"] == antes + 1


def test_escritura_atomica_si_falla_el_reemplazo_queda_el_cache_anterior(caso, monkeypatch):
    api.nuevo(caso)
    anterior = (caso / ".resumen.json").read_bytes()
    os.utime(caso / "caso.json", (time.time() + 3600, time.time() + 3600))

    def falla(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(resumen_caso.os, "replace", falla)
    resumen = resumen_caso.actualizar(caso)
    assert resumen["estado"] == "revision"
    assert (caso / ".resumen.json").read_bytes() == anterior
    assert [p.name for p in caso.iterdir() if p.name.endswith(".tmp")] == []


def test_escritura_atomica_si_falla_la_escritura_no_deja_temporales(caso, monkeypatch):
    api.nuevo(caso)
    original = Path.write_text

    def falla(self, *args, **kwargs):
        if self.name.endswith(".tmp"):
            self.touch()
            raise OSError("sin espacio")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", falla)
    with pytest.raises(OSError):
        resumen_caso._escribir(caso, {"v": 1})
    assert [p.name for p in caso.iterdir() if p.name.endswith(".tmp")] == []


def test_lectores_nunca_ven_un_resumen_a_medias(caso):
    api.nuevo(caso)
    detener = threading.Event()

    def escribir():
        while not detener.is_set():
            resumen_caso.actualizar(caso)

    hilos = [threading.Thread(target=escribir) for _ in range(3)]
    for h in hilos:
        h.start()
    try:
        for _ in range(300):
            assert resumen_caso._leer_cache(caso) is not None
    finally:
        detener.set()
        for h in hilos:
            h.join()
    assert [p.name for p in caso.iterdir() if p.name.endswith(".tmp")] == []


def test_caso_corrupto_es_error_en_etapa_cero(caso):
    api.nuevo(caso)
    (caso / "caso.json").write_text("{ no es json", encoding="utf-8")
    resumen = resumen_caso.leer(caso)
    assert (resumen["estado"], resumen["etapa"], resumen["siguiente_paso"]) == ("error", 0, "Revisar el error")
    assert resumen["radicado"] is None and resumen["accionadas"] == []


def test_hilo_corrupto_es_error_en_etapa_cero(caso):
    api.nuevo(caso)
    (caso / "hilo.sqlite").write_bytes(b"basura que no es sqlite" * 50)
    resumen = resumen_caso.leer(caso)
    assert resumen["estado"] == "error" and resumen["etapa"] == 0


def test_nombre_sale_de_dot_nombre_y_si_no_existe_del_id(caso):
    assert resumen_caso.actualizar(caso)["nombre"] == "caso-api"
    (caso / ".nombre").write_text("  Tutela 2026-00412 \n", encoding="utf-8")
    assert resumen_caso.actualizar(caso)["nombre"] == "Tutela 2026-00412"


def test_n_insumos_se_cuenta_en_la_reconstruccion(caso):
    sub = caso / "insumos" / "01PrimeraInstancia" / "C01Principal"
    sub.mkdir(parents=True)
    for i in range(3):
        (sub / f"{i}.pdf").write_bytes(b"%PDF")
    assert resumen_caso.actualizar(caso)["n_insumos"] == 3


def test_con_job_calcula_estado_etapa_y_job(caso):
    api.nuevo(caso)
    base = resumen_caso.leer(caso)
    for cmd, etapa in (("nuevo", 0), ("iniciar", 1), ("decidir", 3), ("continuar", base["etapa"])):
        r = resumen_caso.con_job(base, "j1", cmd, caso)
        assert (r["estado"], r["etapa"], r["job_activo"], r["siguiente_paso"]) == ("corriendo", etapa, "j1", "Ver el avance")
    assert base["estado"] == "revision" and base["job_activo"] is None
    assert "corriendo" not in (caso / ".resumen.json").read_text(encoding="utf-8")


def test_con_job_decidir_con_rehacer_vuelve_a_la_etapa_uno(caso):
    (caso / "decision.json").write_text(json.dumps({"accion": "rehacer_consideraciones"}), encoding="utf-8")
    base = resumen_caso.actualizar(caso)
    assert resumen_caso.con_job(base, "j", "decidir", caso)["etapa"] == 1
    (caso / "decision.json").write_text("roto", encoding="utf-8")
    assert resumen_caso.con_job(base, "j", "decidir", caso)["etapa"] == 3


def test_el_enganche_no_altera_la_respuesta_aunque_falle_el_resumen(caso, monkeypatch):
    def falla(caso_dir):
        raise RuntimeError("fallo del resumen")

    monkeypatch.setattr(resumen_caso, "actualizar", falla)
    r = api.nuevo(caso)
    assert r["ok"] and r["estado"] == "revision"


def test_el_enganche_corre_tambien_si_la_funcion_lanza(tmp_path, monkeypatch):
    vistos = []
    monkeypatch.setattr(resumen_caso, "actualizar", lambda d: vistos.append(d))

    @resumen_caso.tras_transicion
    def rota(caso_dir):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        rota(tmp_path)
    assert vistos == [tmp_path.resolve()]


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    server.JOBS.clear()
    yield TestClient(server.app, base_url="http://127.0.0.1")
    server.JOBS.clear()


def _subir(cliente: TestClient, archivos: dict[str, bytes], nombre: str | None = None):
    files = [("files", (ruta, contenido, "application/pdf")) for ruta, contenido in archivos.items()]
    return cliente.post("/api/casos", data={} if nombre is None else {"nombre": nombre}, files=files)


def test_post_sin_nombre_usa_la_carpeta_raiz_comun(cliente):
    r = _subir(cliente, {"Raiz Tutela/01PrimeraInstancia/a.pdf": b"%PDF-a", "Raiz Tutela/01PrimeraInstancia/b.pdf": b"%PDF-b"})
    assert r.status_code == 200 and r.json() == {"id": "raiz-tutela", "n_insumos": 2}
    [caso] = cliente.get("/api/casos").json()
    assert caso["id"] == "raiz-tutela" and caso["nombre"] == "Raiz Tutela" and caso["n_insumos"] == 2
    assert (server.casos_dir() / "raiz-tutela" / "insumos" / "01PrimeraInstancia" / "a.pdf").is_file()


def test_post_sin_nombre_y_sin_carpeta_comun_usa_caso(cliente):
    assert _subir(cliente, {"a.pdf": b"%PDF-a"}).json()["id"] == "caso"
    assert _subir(cliente, {"X/a.pdf": b"%PDF-a", "Y/b.pdf": b"%PDF-b"}).json()["id"] == "caso-2"
    assert {c["nombre"] for c in cliente.get("/api/casos").json()} == {"caso"}


def test_post_con_nombre_vacio_o_en_blanco_se_trata_como_ausente(cliente):
    assert _subir(cliente, {"Raiz/a.pdf": b"%PDF"}, nombre="   ").json()["id"] == "raiz"


def test_post_con_nombre_lo_conserva_y_el_id_es_el_slug(cliente):
    r = _subir(cliente, {"Raiz/a.pdf": b"%PDF"}, nombre="Tutela 2026-00412")
    assert r.json()["id"] == "tutela-2026-00412"
    [caso] = cliente.get("/api/casos").json()
    assert caso["nombre"] == "Tutela 2026-00412"
    assert (server.casos_dir() / "tutela-2026-00412" / ".resumen.json").is_file()


def test_post_sin_archivos_validos_es_400_y_rutas_peligrosas_se_rechazan(cliente):
    assert _subir(cliente, {".oculto/a.pdf": b"x"}).status_code == 400
    assert _subir(cliente, {"../a.pdf": b"x"}).status_code == 400
    assert cliente.get("/api/casos").json() == []


def _subir_lista(cliente: TestClient, rutas: list[str], nombre: str = "x"):
    files = [("files", (ruta, f"%PDF-{i}".encode(), "application/pdf")) for i, ruta in enumerate(rutas)]
    return cliente.post("/api/casos", data={"nombre": nombre}, files=files)


def _sin_casos(cliente: TestClient) -> bool:
    raiz = server.casos_dir()
    return not raiz.exists() or list(raiz.iterdir()) == []


def test_post_con_rutas_repetidas_tras_normalizar_es_400_y_no_crea_el_caso(cliente):
    rutas = ["Raiz/a.pdf", "Raiz/./a.pdf", "Raiz/b.pdf", "Raiz\\b.pdf", "Raiz/ñ.pdf", "Raiz/n\u0303.pdf", "Raiz/c.pdf"]
    r = _subir_lista(cliente, rutas)
    assert r.status_code == 400
    detalle = r.json()["detail"]
    assert "a.pdf, b.pdf, ñ.pdf" in detalle and "c.pdf" not in detalle
    assert _sin_casos(cliente)


def test_post_con_repetidas_tras_quitar_la_raiz_comun_es_400(cliente):
    assert _subir_lista(cliente, ["Raiz/a.pdf", "Raiz/a.pdf"]).status_code == 400
    assert _subir_lista(cliente, ["X/a.pdf", "Y/a.pdf"]).status_code == 200


@pytest.mark.parametrize(
    "rutas",
    [
        ["Raiz/a", "Raiz/a/b.pdf"],
        ["Raiz/a/b.pdf", "Raiz/a"],
        ["Raiz/a", "Raiz/a/b/c.pdf"],
        ["a", "a/b.pdf", "otro.pdf"],
    ],
)
def test_post_con_archivo_y_carpeta_del_mismo_nombre_es_400_y_limpia_el_directorio(cliente, rutas):
    r = _subir_lista(cliente, rutas)
    assert r.status_code == 400
    assert "archivo y carpeta" in r.json()["detail"]
    assert _sin_casos(cliente)


def test_post_copia_el_formato_global_al_caso_nuevo(cliente, monkeypatch):
    vistos = []
    monkeypatch.setattr(formato_global, "copiar_a_caso", lambda d: vistos.append(Path(d)))
    r = _subir(cliente, {"Raiz/a.pdf": b"%PDF"})
    assert vistos == [server.casos_dir() / r.json()["id"]]


def test_post_si_falla_la_copia_del_formato_no_deja_el_caso(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))

    def falla(d):
        raise RuntimeError("formato roto")

    monkeypatch.setattr(formato_global, "copiar_a_caso", falla)
    cliente = TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    assert _subir(cliente, {"Raiz/a.pdf": b"%PDF"}).status_code == 500
    assert list((tmp_path / "casos").iterdir()) == []


def test_get_devuelve_la_forma_del_contrato(cliente):
    _subir(cliente, {"Raiz/a.pdf": b"%PDF"})
    [caso] = cliente.get("/api/casos").json()
    assert set(caso) == CAMPOS
    assert caso["estado"] == "sin_iniciar" and caso["etapa"] == 0 and caso["job_activo"] is None
    assert caso["radicado"] is None and caso["accionadas"] == [] and caso["n_alertas"] == 0
    assert datetime.fromisoformat(caso["actualizado"]).utcoffset().total_seconds() == 0


def test_get_sin_carpeta_de_casos_es_lista_vacia_y_ignora_los_ocultos(cliente):
    assert cliente.get("/api/casos").json() == []
    (server.casos_dir() / ".oculto").mkdir(parents=True)
    (server.casos_dir() / "archivo.txt").write_text("x", encoding="utf-8")
    assert cliente.get("/api/casos").json() == []


def test_get_ordena_por_id_y_marca_corriendo_sin_cachearlo(cliente):
    for raiz in ("Beta", "Alfa"):
        _subir(cliente, {f"{raiz}/a.pdf": b"%PDF"})
    assert [c["id"] for c in cliente.get("/api/casos").json()] == ["alfa", "beta"]
    server.JOBS["j1"] = {"id": "j1", "caso": "beta", "cmd": "iniciar", "estado": "corriendo", "log": []}
    por_id = {c["id"]: c for c in cliente.get("/api/casos").json()}
    assert (por_id["beta"]["estado"], por_id["beta"]["etapa"], por_id["beta"]["job_activo"]) == ("corriendo", 1, "j1")
    assert por_id["alfa"]["estado"] == "sin_iniciar"
    server.JOBS["j1"]["estado"] = "terminado"
    por_id = {c["id"]: c for c in cliente.get("/api/casos").json()}
    assert por_id["beta"]["estado"] == "sin_iniciar" and por_id["beta"]["job_activo"] is None


def test_get_con_job_activo_usa_el_cache_aunque_este_viejo(cliente, llamadas_estado):
    _subir(cliente, {"Raiz/a.pdf": b"%PDF"})
    caso_dir = server.casos_dir() / "raiz"
    cliente.get("/api/casos")
    os.utime(caso_dir / "insumos", (time.time() + 3600, time.time() + 3600))
    server.JOBS["j1"] = {"id": "j1", "caso": "raiz", "cmd": "nuevo", "estado": "corriendo", "log": []}
    antes = llamadas_estado["n"]
    assert cliente.get("/api/casos").json()[0]["estado"] == "corriendo"
    assert llamadas_estado["n"] == antes
    (caso_dir / ".resumen.json").unlink()
    cliente.get("/api/casos")
    assert llamadas_estado["n"] == antes + 1


def test_un_caso_corrupto_no_rompe_la_lista(cliente, monkeypatch):
    for raiz in ("Uno", "Dos", "Tres"):
        _subir(cliente, {f"{raiz}/a.pdf": b"%PDF"})
    dos = server.casos_dir() / "dos"
    (dos / "caso.json").write_text("{ roto", encoding="utf-8")
    por_id = {c["id"]: c for c in cliente.get("/api/casos").json()}
    assert por_id["dos"]["estado"] == "error" and por_id["dos"]["etapa"] == 0
    assert por_id["uno"]["estado"] == "sin_iniciar" and por_id["tres"]["estado"] == "sin_iniciar"

    real = resumen_caso.leer

    def leer(caso_dir, tolerar_obsoleto=False):
        if caso_dir.name == "tres":
            raise RuntimeError("explotó")
        return real(caso_dir, tolerar_obsoleto)

    monkeypatch.setattr(resumen_caso, "leer", leer)
    respuesta = cliente.get("/api/casos")
    assert respuesta.status_code == 200
    por_id = {c["id"]: c for c in respuesta.json()}
    assert por_id["tres"]["estado"] == "error" and por_id["uno"]["estado"] == "sin_iniciar"


def _esperar(cliente: TestClient, job_id: str) -> dict:
    limite = time.time() + 20
    while time.time() < limite:
        job = cliente.get(f"/api/jobs/{job_id}").json()
        if job["estado"] != "corriendo":
            return job
        time.sleep(0.02)
    raise AssertionError("el job no terminó")


def test_jobs_reales_dejan_la_lista_al_dia(cliente, monkeypatch):
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    monkeypatch.setenv("TUTELA2_MODELO", "")
    caso_id = _subir(cliente, {"Raiz/a.pdf": b"%PDF"}).json()["id"]
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (server.casos_dir() / caso_id / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")

    def correr(cmd, **extra):
        job = _esperar(cliente, cliente.post(f"/api/casos/{caso_id}/run", json={"cmd": cmd, **extra}).json()["job_id"])
        assert job["estado"] == "terminado", job["error"]
        [caso] = cliente.get("/api/casos").json()
        return caso

    caso = correr("nuevo")
    assert (caso["estado"], caso["etapa"], caso["radicado"], caso["job_activo"]) == ("revision", 0, "05001400900120260000101", None)
    caso = correr("iniciar")
    assert (caso["estado"], caso["etapa"], caso["siguiente_paso"]) == ("esperando_decision", 2, "Revisar el borrador y decidir")
    caso = correr("decidir", decision=DECISION)
    assert (caso["estado"], caso["etapa"], caso["siguiente_paso"]) == ("terminado", 4, "Ver el fallo")
    assert caso["nombre"] == "Raiz" and caso["n_insumos"] == 1


def test_un_cache_con_valores_invalidos_se_reconstruye_sin_romper_la_lista(cliente):
    for raiz in ("Uno", "Dos"):
        _subir(cliente, {f"{raiz}/a.pdf": b"%PDF"})
    ruta = server.casos_dir() / "dos" / ".resumen.json"
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    documento["datos"].update(etapa=9, estado=["x"])
    ruta.write_text(json.dumps(documento), encoding="utf-8")
    respuesta = cliente.get("/api/casos")
    assert respuesta.status_code == 200
    por_id = {c["id"]: c for c in respuesta.json()}
    assert (por_id["dos"]["estado"], por_id["dos"]["etapa"]) == ("sin_iniciar", 0)
    assert json.loads(ruta.read_text(encoding="utf-8"))["datos"]["etapa"] == 0


def test_openapi_declara_el_modelo_de_respuesta(cliente):
    esquema = server.app.openapi()
    get = esquema["paths"]["/api/casos"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    post = esquema["paths"]["/api/casos"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert get["items"]["$ref"].endswith("/CasoResumen") and post["$ref"].endswith("/CasoCreado")
    assert "nombre" not in esquema["components"]["schemas"]["Body_crear_caso_api_casos_post"].get("required", [])


def test_lista_de_200_casos_con_cache_caliente_es_rapida_y_no_abre_el_grafo(cliente, llamadas_estado):
    raiz = server.casos_dir()
    ingesta = ingesta_sintetica().model_dump_json()
    for i in range(200):
        d = raiz / f"caso-{i:03d}"
        (d / "insumos" / "01PrimeraInstancia").mkdir(parents=True)
        for j in range(5):
            (d / "insumos" / "01PrimeraInstancia" / f"{j}.pdf").write_bytes(b"%PDF")
        if i % 2:
            (d / "caso.json").write_text(ingesta, encoding="utf-8")

    frio = cliente.get("/api/casos")
    assert frio.status_code == 200 and len(frio.json()) == 200
    assert llamadas_estado["n"] == 200

    mejor = float("inf")
    for _ in range(5):
        t0 = time.perf_counter()
        caliente = cliente.get("/api/casos")
        mejor = min(mejor, time.perf_counter() - t0)
    assert llamadas_estado["n"] == 200
    assert caliente.json() == frio.json()
    assert {c["estado"] for c in caliente.json()} == {"sin_iniciar", "revision"}
    assert mejor < 0.05, f"{mejor * 1000:.1f} ms"


def test_get_resumen_de_un_caso_coincide_con_la_fila_de_la_lista(cliente):
    _subir(cliente, {"Raiz/a.pdf": b"%PDF", "Raiz/b.pdf": b"%PDF"})
    [fila] = cliente.get("/api/casos").json()
    r = cliente.get("/api/casos/raiz/resumen")
    assert r.status_code == 200 and r.json() == fila
    assert set(r.json()) == CAMPOS and r.json()["n_insumos"] == 2 and r.json()["estado"] == "sin_iniciar"


def test_get_resumen_con_job_activo_marca_corriendo_igual_que_la_lista(cliente):
    _subir(cliente, {"Raiz/a.pdf": b"%PDF"})
    server.JOBS["j1"] = {"id": "j1", "caso": "raiz", "cmd": "iniciar", "estado": "corriendo", "log": []}
    r = cliente.get("/api/casos/raiz/resumen").json()
    assert (r["estado"], r["etapa"], r["job_activo"], r["siguiente_paso"]) == ("corriendo", 1, "j1", "Ver el avance")
    assert r == cliente.get("/api/casos").json()[0]
    server.JOBS["j1"]["estado"] = "terminado"
    assert cliente.get("/api/casos/raiz/resumen").json()["job_activo"] is None


def test_get_resumen_de_caso_inexistente_u_oculto_es_404(cliente):
    (server.casos_dir() / ".oculto").mkdir(parents=True)
    (server.casos_dir() / "archivo.txt").write_text("x", encoding="utf-8")
    for caso_id in ("nada", ".oculto", "archivo.txt"):
        r = cliente.get(f"/api/casos/{caso_id}/resumen")
        assert r.status_code == 404 and r.json() == {"detail": "Caso no encontrado."}


def test_get_resumen_de_un_caso_corrupto_devuelve_estado_error(cliente):
    _subir(cliente, {"Raiz/a.pdf": b"%PDF"})
    (server.casos_dir() / "raiz" / "caso.json").write_text("{ roto", encoding="utf-8")
    r = cliente.get("/api/casos/raiz/resumen")
    assert r.status_code == 200 and r.json()["estado"] == "error" and r.json()["etapa"] == 0


def test_openapi_declara_el_resumen_de_un_caso(cliente):
    operacion = cliente.get("/openapi.json").json()["paths"]["/api/casos/{caso_id}/resumen"]["get"]
    assert operacion["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/CasoResumen"}


def _casos_para_calentar(tmp_path: Path) -> Path:
    casos = tmp_path / "casos"
    for nombre in ("uno", "dos", "roto", "tres", ".oculto"):
        (casos / nombre / "insumos").mkdir(parents=True)
        (casos / nombre / "insumos" / "a.pdf").write_bytes(b"%PDF")
    (casos / "roto" / "caso.json").write_text("{ roto", encoding="utf-8")
    (casos / "archivo.txt").write_text("x", encoding="utf-8")
    return casos


def test_el_arranque_calienta_la_cache_aunque_un_caso_falle(tmp_path, monkeypatch, caplog):
    casos = _casos_para_calentar(tmp_path)
    monkeypatch.setenv("CASOS_DIR", str(casos))
    real = resumen_caso.leer

    def leer(caso_dir, tolerar_obsoleto=False):
        if caso_dir.name == "dos":
            raise RuntimeError("explotó")
        return real(caso_dir, tolerar_obsoleto)

    monkeypatch.setattr(resumen_caso, "leer", leer)
    with caplog.at_level("WARNING", logger="tutela2.resumen_caso"):
        with TestClient(server.app, base_url="http://127.0.0.1") as cliente:
            hilo = server.app.state.calentamiento
            hilo.join(30)
            assert not hilo.is_alive() and hilo.daemon
            assert cliente.get("/healthz").json() == {"status": "ok"}
    for nombre in ("uno", "roto", "tres"):
        assert (casos / nombre / ".resumen.json").is_file(), nombre
    assert json.loads((casos / "roto" / ".resumen.json").read_text(encoding="utf-8"))["datos"]["estado"] == "error"
    assert not (casos / "dos" / ".resumen.json").exists()
    assert not (casos / ".oculto" / ".resumen.json").exists()
    assert any("dos" in r.getMessage() for r in caplog.records)


def test_el_arranque_con_cache_vigente_no_reconstruye(tmp_path, monkeypatch, llamadas_estado):
    casos = _casos_para_calentar(tmp_path)
    monkeypatch.setenv("CASOS_DIR", str(casos))
    with TestClient(server.app, base_url="http://127.0.0.1"):
        server.app.state.calentamiento.join(30)
    despues_del_primero = llamadas_estado["n"]
    assert despues_del_primero >= 4
    with TestClient(server.app, base_url="http://127.0.0.1"):
        server.app.state.calentamiento.join(30)
    assert llamadas_estado["n"] == despues_del_primero


def test_el_arranque_no_falla_ni_crea_la_carpeta_si_casos_dir_no_existe(tmp_path, monkeypatch):
    casos = tmp_path / "no_existe"
    monkeypatch.setenv("CASOS_DIR", str(casos))
    with TestClient(server.app, base_url="http://127.0.0.1") as cliente:
        server.app.state.calentamiento.join(30)
        assert not server.app.state.calentamiento.is_alive()
        assert cliente.get("/healthz").status_code == 200
        assert cliente.get("/api/casos").json() == []
    assert not casos.exists()


def test_el_arranque_no_espera_al_calentamiento_y_tolera_que_este_falle(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    suelta = threading.Event()

    def lento(raiz):
        suelta.wait(30)
        raise OSError("sin permisos")

    monkeypatch.setattr(resumen_caso, "calentar", lento)
    with caplog.at_level("WARNING", logger="tutela2.server"):
        with TestClient(server.app, base_url="http://127.0.0.1") as cliente:
            hilo = server.app.state.calentamiento
            assert hilo.is_alive()
            assert cliente.get("/healthz").status_code == 200
            suelta.set()
            hilo.join(30)
            assert not hilo.is_alive()
    assert any("caché de resúmenes" in r.getMessage() for r in caplog.records)
