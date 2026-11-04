from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tutela2 import acceso, eventos, server
from tutela2.rutas_eventos import flujo


def _sse(texto: str) -> list[tuple[str, dict]]:
    mensajes = []
    for bloque in texto.split("\n\n"):
        campos: dict[str, str] = {}
        for linea in bloque.splitlines():
            if linea.startswith(":"):
                continue
            clave, _, valor = linea.partition(": ")
            campos[clave] = valor
        if "data" in campos:
            mensajes.append((campos.get("event", "message"), {**json.loads(campos["data"]), "_id": campos.get("id")}))
    return mensajes


def _emitidos(buffer: eventos.Buffer, desde: int = 0) -> list[dict]:
    return buffer.leer(desde)[0]


@pytest.fixture
def activo():
    buffer = eventos.Buffer()
    token = eventos.activar(buffer)
    yield buffer
    eventos.desactivar(token)


def test_emitir_fuera_de_job_es_noop():
    antes = dict(eventos._REGISTRO)
    eventos.emitir("ingesta", "lee", "nada", {"x": object()})
    assert eventos._ACTUAL.get() is None
    assert eventos._REGISTRO == antes


def test_orden_y_n_monotonico(activo):
    for i in range(5):
        eventos.emitir("apertura", "lee", f"paso {i}", {"i": i})
    todos = _emitidos(activo)
    assert [e["n"] for e in todos] == [1, 2, 3, 4, 5]
    assert [e["texto"] for e in todos] == [f"paso {i}" for i in range(5)]
    assert [e["n"] for e in _emitidos(activo, 2)] == [3, 4, 5]
    assert _emitidos(activo, 5) == []
    assert _emitidos(activo, 99) == []
    assert all(e["t"].endswith("+00:00") for e in todos)


def test_emitir_nunca_lanza_y_sanea(activo):
    ciclico: dict = {}
    ciclico["yo"] = ciclico
    eventos.emitir("ingesta", "lee", "ciclo", ciclico)
    eventos.emitir("inventada", "otro", 123, [1, 2])
    eventos.emitir("ingesta", "lee", "x" * 10_000, {"ruta": Path("/a/b")})
    eventos.emitir("verificacion", "razona", "reservado", None)
    a, b, c = _emitidos(activo)
    assert (a["etapa"], a["tipo"], a["texto"], a["datos"]) == ("sistema", "sistema", "123", {"valor": [1, 2]})
    assert len(b["texto"]) == eventos.MAX_TEXTO and b["datos"] == {"ruta": "/a/b"}
    assert c["tipo"] == "razona" and c["datos"] is None


def test_datos_grandes_se_reemplazan(activo):
    eventos.emitir("ingesta", "lee", "grande", {"x": "y" * 20_000})
    assert _emitidos(activo)[0]["datos"] == {"truncado": True, "caracteres": 20_009}


def test_reaplicar_reemite_faltantes_con_los_roles_del_usuario(activo):
    from tutela2 import ingest
    from tutela2.models import Doc, Ingesta, Pagina

    docs = [
        Doc(doc_id=f"1a-00{i}", ruta=f"{i}.pdf", nombre=f"{i}.pdf", instancia="1a", rol=rol, sha256=str(i), paginas=[Pagina(n=1, texto="texto")])
        for i, rol in enumerate(("escrito_tutela", "fallo_a_quo", "otro"), 1)
    ]
    ingest.reaplicar(Ingesta(documentos=docs), {"1a-003": "impugnacion"})
    lista = _emitidos(activo)
    assert lista[0]["datos"] == {"roles": {"1a-003": "impugnacion"}}
    assert lista[-1]["tipo"] == "verifica" and lista[-1]["datos"]["faltantes"] == []


def test_desbordamiento_conserva_los_ultimos_y_avisa():
    buffer = eventos.Buffer(maximo=5)
    for i in range(1, 13):
        buffer.agregar("ingesta", "lee", f"e{i}")
    desde_cero = _emitidos(buffer)
    aviso, *resto = desde_cero
    assert [e["n"] for e in resto] == [8, 9, 10, 11, 12]
    assert (aviso["n"], aviso["tipo"], aviso["etapa"]) == (7, "sistema", "sistema")
    assert aviso["datos"] == {"omitidos": 7, "limite": 5}
    assert aviso["t"]
    assert _emitidos(buffer, 3)[0]["datos"]["omitidos"] == 4
    assert [e["n"] for e in _emitidos(buffer, 7)] == [8, 9, 10, 11, 12]
    assert [e["n"] for e in _emitidos(buffer, 10)] == [11, 12]
    assert len(buffer._eventos) == 5


def test_buffer_por_defecto_acotado_a_2000():
    buffer = eventos.Buffer()
    for i in range(2500):
        buffer.agregar("ingesta", "lee", str(i))
    lista = _emitidos(buffer)
    assert len(buffer._eventos) == 2000
    assert lista[0]["datos"]["omitidos"] == 500
    assert [e["n"] for e in lista[1:]] == list(range(501, 2501))


def test_cerrar_es_definitivo():
    buffer = eventos.Buffer()
    buffer.agregar("sistema", "sistema", "a")
    buffer.cerrar("terminado", None)
    buffer.cerrar("error", "tarde")
    assert buffer.agregar("sistema", "sistema", "b") is None
    assert buffer.leer(0) == (_emitidos(buffer), {"estado": "terminado", "error": None})
    assert len(_emitidos(buffer)) == 1


async def _leer_flujo(buffer: eventos.Buffer, desde: int = 0, latido: float = 15.0) -> str:
    partes = []
    async for parte in flujo(buffer, desde, latido):
        partes.append(parte)
    return "".join(partes)


def test_multiples_lectores_reciben_todo_en_orden():
    buffer = eventos.Buffer()

    def productor():
        for i in range(60):
            buffer.agregar("apertura", "lee", f"e{i}", {"i": i})
            if i % 7 == 0:
                time.sleep(0.005)
        buffer.cerrar("terminado", None)

    async def principal():
        lectores = [asyncio.create_task(_leer_flujo(buffer, 0, 0.05)) for _ in range(4)]
        tardio = asyncio.create_task(_leer_flujo(buffer, 30, 0.05))
        await asyncio.sleep(0.02)
        hilo = threading.Thread(target=productor)
        hilo.start()
        resultados = await asyncio.wait_for(asyncio.gather(*lectores, tardio), 10)
        hilo.join()
        return resultados

    *completos, tardio = asyncio.run(principal())
    for texto in completos:
        mensajes = _sse(texto)
        assert [m[1]["n"] for m in mensajes[:-1]] == list(range(1, 61))
        assert all(m[0] == "evento" and m[1]["_id"] == str(m[1]["n"]) for m in mensajes[:-1])
        assert mensajes[-1][0] == "fin" and mensajes[-1][1]["estado"] == "terminado"
    assert [m[1]["n"] for m in _sse(tardio)[:-1]] == list(range(31, 61))
    assert buffer.lectores() == 0


def test_latido_y_fin_sin_eventos():
    buffer = eventos.Buffer()

    async def principal():
        tarea = asyncio.create_task(_leer_flujo(buffer, 0, 0.03))
        await asyncio.sleep(0.12)
        assert buffer.lectores() == 1
        buffer.cerrar("error", "se cayó")
        return await asyncio.wait_for(tarea, 2)

    texto = asyncio.run(principal())
    assert texto.count(": latido\n\n") >= 2
    assert _sse(texto) == [("fin", {"estado": "error", "error": "se cayó", "_id": None})]
    assert buffer.lectores() == 0


def test_lector_cancelado_libera_su_espera():
    buffer = eventos.Buffer()

    async def principal():
        tarea = asyncio.create_task(_leer_flujo(buffer, 0, 30))
        await asyncio.sleep(0.05)
        assert buffer.lectores() == 1
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(principal())
    assert buffer.lectores() == 0
    buffer.agregar("sistema", "sistema", "tras cancelar")


@pytest.fixture
def entorno():
    antes = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(antes)


@pytest.fixture
def api_fake(monkeypatch):
    fake = types.ModuleType("tutela2.api")
    fake.soltar = threading.Event()
    fake.soltar.set()

    def nuevo(caso_dir):
        for i in range(5):
            eventos.emitir("ingesta", "lee", f"{Path(caso_dir).name} {i}", {"caso": Path(caso_dir).name, "i": i})
            if i == 1:
                fake.soltar.wait(5)
        return {"ok": True, "estado": "revision", "error": None}

    fake.nuevo = nuevo
    fake.continuar = lambda caso_dir, forzar=False: (_ for _ in ()).throw(RuntimeError("fallo simulado"))
    fake.iniciar = lambda caso_dir: {"ok": False, "estado": "incompleto", "error": "Faltan documentos obligatorios: impugnacion."}
    monkeypatch.setitem(sys.modules, "tutela2.api", fake)
    return fake


@pytest.fixture
def cliente(tmp_path, monkeypatch, entorno, api_fake) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    for nombre in ("uno", "dos"):
        (tmp_path / "casos" / nombre / "insumos").mkdir(parents=True)
    server.JOBS.clear()
    eventos._REGISTRO.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


def _correr(cliente: TestClient, caso: str, cmd: str = "nuevo") -> str:
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": cmd})
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def _flujo_http(cliente: TestClient, job_id: str, **kwargs) -> tuple[object, list[tuple[str, dict]]]:
    r = cliente.get(f"/api/jobs/{job_id}/eventos", **kwargs)
    assert r.status_code == 200, r.text
    return r, _sse(r.text)


def test_sse_completo_con_inicio_eventos_y_fin(cliente):
    job_id = _correr(cliente, "uno")
    r, mensajes = _flujo_http(cliente, job_id)
    assert r.headers["content-type"].startswith("text/event-stream")
    eventos_ = [m[1] for m in mensajes if m[0] == "evento"]
    assert [e["n"] for e in eventos_] == list(range(1, len(eventos_) + 1))
    assert eventos_[0]["etapa"] == "sistema" and "nuevo" in eventos_[0]["texto"]
    assert [e["texto"] for e in eventos_ if e["etapa"] == "ingesta"] == [f"uno {i}" for i in range(5)]
    assert eventos_[-1]["tipo"] == "sistema" and eventos_[-1]["datos"]["cmd"] == "nuevo"
    assert mensajes[-1] == ("fin", {"estado": "terminado", "error": None, "_id": None})
    assert cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "terminado"


def test_reconexion_por_desde_y_last_event_id(cliente):
    job_id = _correr(cliente, "uno")
    _, todos = _flujo_http(cliente, job_id)
    total = len(todos) - 1
    _, tras3 = _flujo_http(cliente, job_id, params={"desde": 3})
    assert [m[1]["n"] for m in tras3[:-1]] == list(range(4, total + 1))
    _, tras5 = _flujo_http(cliente, job_id, params={"desde": 0}, headers={"Last-Event-ID": "5"})
    assert [m[1]["n"] for m in tras5[:-1]] == list(range(6, total + 1))
    _, basura = _flujo_http(cliente, job_id, params={"desde": 2}, headers={"Last-Event-ID": "x"})
    assert basura[0][1]["n"] == 3
    _, final = _flujo_http(cliente, job_id, params={"desde": total})
    assert final == [("fin", {"estado": "terminado", "error": None, "_id": None})]
    assert cliente.get(f"/api/jobs/{job_id}/eventos", params={"desde": -1}).status_code == 422


def test_formato_json_por_polling(cliente, api_fake):
    api_fake.soltar.clear()
    job_id = _correr(cliente, "uno")
    limite = time.time() + 5
    while True:
        parcial = cliente.get(f"/api/jobs/{job_id}/eventos", params={"formato": "json"}).json()
        if len(parcial["eventos"]) >= 3 or time.time() > limite:
            break
        time.sleep(0.01)
    assert parcial["estado"] == "corriendo" and parcial["error"] is None
    assert [e["n"] for e in parcial["eventos"]] == [1, 2, 3]
    api_fake.soltar.set()
    limite = time.time() + 5
    while cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "corriendo" and time.time() < limite:
        time.sleep(0.01)
    resto = cliente.get(f"/api/jobs/{job_id}/eventos", params={"formato": "json", "desde": 3}).json()
    assert resto["estado"] == "terminado"
    assert resto["eventos"][0]["n"] == 4
    assert set(resto["eventos"][0]) == {"n", "t", "etapa", "tipo", "texto", "datos"}


def test_sse_en_vivo_mientras_corre(cliente, api_fake):
    api_fake.soltar.clear()
    job_id = _correr(cliente, "uno")
    recibidos: list[str] = []
    with cliente.stream("GET", f"/api/jobs/{job_id}/eventos") as r:
        for linea in r.iter_lines():
            recibidos.append(linea)
            if linea.startswith("data: ") and json.loads(linea[6:]).get("n") == 3:
                assert cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "corriendo"
                assert not api_fake.soltar.is_set()
                api_fake.soltar.set()
    assert api_fake.soltar.is_set()
    assert "event: fin" in recibidos
    assert eventos.buffer(job_id).lectores() == 0


def test_job_con_excepcion_emite_error_y_fin(cliente):
    job_id = _correr(cliente, "uno", "continuar")
    _, mensajes = _flujo_http(cliente, job_id)
    errores = [m[1] for m in mensajes if m[0] == "evento" and m[1]["tipo"] == "error"]
    assert errores and errores[-1]["texto"] == "fallo simulado"
    assert mensajes[-1] == ("fin", {"estado": "error", "error": "fallo simulado", "_id": None})
    assert cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "error"


def test_job_con_ok_falso_emite_error_y_fin(cliente):
    job_id = _correr(cliente, "uno", "iniciar")
    _, mensajes = _flujo_http(cliente, job_id)
    error = "Faltan documentos obligatorios: impugnacion."
    assert [m[1]["texto"] for m in mensajes if m[0] == "evento" and m[1]["tipo"] == "error"] == [error]
    assert mensajes[-1] == ("fin", {"estado": "error", "error": error, "_id": None})


def test_dos_jobs_concurrentes_no_mezclan_eventos(cliente, api_fake):
    api_fake.soltar.clear()
    uno = _correr(cliente, "uno")
    dos = _correr(cliente, "dos")
    time.sleep(0.05)
    api_fake.soltar.set()
    for job_id, caso in ((uno, "uno"), (dos, "dos")):
        _, mensajes = _flujo_http(cliente, job_id)
        ingesta = [m[1] for m in mensajes if m[0] == "evento" and m[1]["etapa"] == "ingesta"]
        assert [e["datos"] for e in ingesta] == [{"caso": caso, "i": i} for i in range(5)]
        assert [m[1]["n"] for m in mensajes[:-1]] == list(range(1, len(mensajes)))


def test_cabeceras_sse_sin_gzip(cliente):
    job_id = _correr(cliente, "uno")
    r, _ = _flujo_http(cliente, job_id, headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


def test_sse_detras_de_la_compuerta_de_acceso(cliente, monkeypatch):
    job_id = _correr(cliente, "uno")
    monkeypatch.setenv("JUDICABOT_PASSWORD", "clave-de-prueba")
    assert cliente.get(f"/api/jobs/{job_id}/eventos").status_code == 401
    cliente.cookies.set(acceso.COOKIE, acceso._token("clave-de-prueba"))
    _, mensajes = _flujo_http(cliente, job_id)
    assert mensajes[-1][0] == "fin"


def test_job_inexistente_404(cliente):
    assert cliente.get("/api/jobs/nada/eventos").status_code == 404
    assert cliente.get("/api/jobs/nada/eventos", params={"formato": "json"}).status_code == 404


def test_log_del_job_recortado_a_200(cliente, api_fake):
    def nuevo(caso_dir):
        for i in range(300):
            logging.getLogger("tutela2.x").info("linea %d", i)
        return {"ok": True, "estado": "revision", "error": None}

    api_fake.nuevo = nuevo
    job_id = _correr(cliente, "uno")
    _flujo_http(cliente, job_id)
    log = cliente.get(f"/api/jobs/{job_id}").json()["log"]
    assert len(log) == 200
    assert log[-1].endswith("Fin de nuevo: terminado")
    assert any(linea.endswith("linea 299") for linea in log)


def test_purga_conserva_los_ultimos_50_terminados(cliente):
    viejos = []
    for i in range(55):
        job_id = f"viejo{i:02d}"
        server.JOBS[job_id] = {"id": job_id, "caso": "otro", "cmd": "nuevo", "estado": "terminado", "log": [], "resultado": None, "error": None}
        eventos.crear(job_id)
        viejos.append(job_id)
    nuevo = _correr(cliente, "uno")
    _flujo_http(cliente, nuevo)
    terminados = [i for i, j in server.JOBS.items() if j["estado"] != "corriendo"]
    assert len(terminados) <= 51
    assert nuevo in server.JOBS
    assert all(j not in server.JOBS and eventos.buffer(j) is None for j in viejos[:5])
    assert all(j in server.JOBS and eventos.buffer(j) is not None for j in viejos[5:])


def _modulo_sintetico():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "caso_sintetico.py"
    spec = importlib.util.spec_from_file_location("caso_sintetico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def fuente_sintetica(tmp_path_factory):
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        pytest.skip("requiere soffice y pdftotext")
    modulo = _modulo_sintetico()
    carpeta = tmp_path_factory.mktemp("fuente")
    modulo.generar(carpeta)
    return modulo, carpeta


def test_caso_sintetico_eventos_reales_y_latencia(fuente_sintetica, tmp_path, monkeypatch, entorno):
    modulo, fuente = fuente_sintetica
    monkeypatch.setitem(sys.modules, "tutela2.api", importlib.import_module("tutela2.api"))
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    caso_dir = tmp_path / "casos" / "sintetico"
    shutil.copytree(fuente / "01PrimeraInstancia", caso_dir / "01PrimeraInstancia")
    modulo.preparar(caso_dir, "fake")
    server.JOBS.clear()
    cliente = TestClient(server.app, base_url="http://127.0.0.1")

    def correr(cmd: str, **extra) -> list[dict]:
        t0 = time.monotonic()
        job_id = cliente.post("/api/casos/sintetico/run", json={"cmd": cmd, **extra}).json()["job_id"]
        while not cliente.get(f"/api/jobs/{job_id}/eventos", params={"formato": "json"}).json()["eventos"]:
            time.sleep(0.005)
        assert time.monotonic() - t0 < 0.5
        r = cliente.get(f"/api/jobs/{job_id}/eventos")
        mensajes = _sse(r.text)
        assert mensajes[-1][0] == "fin" and mensajes[-1][1]["estado"] == "terminado", mensajes[-1]
        lista = [m[1] for m in mensajes if m[0] == "evento"]
        assert [e["n"] for e in lista] == list(range(1, len(lista) + 1))
        assert not [e for e in lista if e["tipo"] == "error"]
        return lista

    nuevo = correr("nuevo")
    ingesta = [e for e in nuevo if e["etapa"] == "ingesta"]
    assert ingesta[0]["datos"]["archivos"] == 9 and ingesta[0]["datos"]["por_tipo"] == {"PDF": 9}
    leidos = [e["datos"] for e in ingesta if e["datos"] and "paginas" in e["datos"]]
    assert len(leidos) == 9 and all(d["paginas"] >= 1 for d in leidos)
    roles = {Path(e["datos"]["archivo"]).name: e["datos"]["rol"] for e in ingesta if e["datos"] and "rol" in e["datos"]}
    assert roles["005.pdf"] == "fallo_a_quo" and roles["006.pdf"] == "impugnacion" and len(roles) == 9
    assert ingesta[-1]["tipo"] == "verifica" and ingesta[-1]["datos"]["faltantes"] == []

    iniciar = correr("iniciar")
    etapas = {e["etapa"] for e in iniciar}
    assert {"apertura", "consideraciones", "verificacion"} <= etapas
    respuestas = [e for e in iniciar if e["tipo"] == "escribe" and e["datos"].get("tokens_salida")]
    assert {e["datos"]["nodo"] for e in respuestas} == {"apertura", "consideraciones"}
    citas = [e["datos"] for e in iniciar if e["etapa"] == "verificacion" and e["datos"] and "cobertura" in e["datos"]]
    resumen = next(e["datos"] for e in iniciar if e["texto"].startswith("Informe de citas"))
    assert len(citas) == sum(resumen.values()) > 0

    decidir = correr("decidir", decision=modulo.DECISION_POR_DEFECTO)
    assert any(e["etapa"] == "caso_concreto" and e["tipo"] == "escribe" for e in decidir)
    generados = {e["datos"]["archivo"] for e in decidir if e["etapa"] == "documentos" and e["datos"].get("archivo")}
    assert "por_radicar/OficioRemiteCorteConstitucional.docx" in generados
    assert any(a.startswith("02SegundaInstancia/") and "FalloSegunda" in a for a in generados)
