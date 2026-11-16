from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_citas import SHELL_ANGULAR, _pagina

from tutela2 import acceso, extension, server
from tutela2.extension import Entrega

CLAVE = "clave-de-prueba"
SOCKET = "ws://127.0.0.1/api/extension"
URL = "https://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm"
URL_OTRA = "https://www.corteconstitucional.gov.co/relatoria/2014/C-313-14.htm"
NO_CONECTADA = Entrega("no_conectada", None, "la extensión de judicabot no estaba conectada")


@pytest.fixture
def cliente(monkeypatch) -> TestClient:
    monkeypatch.setenv("JUDICABOT_PASSWORD", CLAVE)
    acceso._fallos.clear()
    extension._conexiones.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


def _hola(ws, **campos) -> None:
    ws.send_json({"tipo": "hola", "version": "1.0.0", **campos})


def _entrega(id: str, codigo: int | None, cuerpo: bytes = b"", detalle: str = "") -> bytes:
    return json.dumps({"id": id, "codigo": codigo, "detalle": detalle}).encode() + b"\n" + cuerpo


def _cierre(cliente: TestClient, **campos) -> int:
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect(SOCKET) as ws:
            _hola(ws, **campos)
            ws.receive_json()
    return cierre.value.code


@contextmanager
def _conectada(cliente: TestClient):
    with cliente.websocket_connect(SOCKET) as ws:
        _hola(ws, contrasena=CLAVE)
        assert ws.receive_json()["tipo"] == "listo"
        yield ws


def _responder(ws, codigo: int | None, cuerpo: bytes = b"", detalle: str = "") -> Entrega:
    with ThreadPoolExecutor() as hilos:
        futuro = hilos.submit(extension.pedir_pagina, URL)
        ws.send_bytes(_entrega(ws.receive_json()["id"], codigo, cuerpo, detalle))
        return futuro.result(timeout=5)


def test_hola_sin_credencial_cierra_con_4401(cliente):
    assert _cierre(cliente) == 4401


def test_contrasena_incorrecta_cierra_con_4401(cliente):
    assert _cierre(cliente, contrasena="otra") == 4401


@pytest.mark.parametrize("mensaje", ["no es json", '{"tipo": "latido"}', '["hola"]', None])
def test_primer_mensaje_ilegible_o_tardio_cierra_con_4401(cliente, monkeypatch, mensaje):
    monkeypatch.setattr(extension, "ESPERA_HOLA_S", 0.2)
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect(SOCKET) as ws:
            if mensaje is not None:
                ws.send_text(mensaje)
            ws.receive_json()
    assert cierre.value.code == 4401


def test_hola_anidado_en_exceso_cierra_con_4401(cliente):
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect(SOCKET) as ws:
            ws.send_text("[" * 200000)
            ws.receive_json()
    assert cierre.value.code == 4401


def test_origen_de_pagina_web_cierra_con_4401(cliente, monkeypatch):
    monkeypatch.delenv("JUDICABOT_PASSWORD")
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect(SOCKET, headers={"origin": "https://evil.example"}) as ws:
            _hola(ws)
            ws.receive_json()
    assert cierre.value.code == 4401


def test_origen_de_extension_se_acepta(cliente):
    with cliente.websocket_connect(SOCKET, headers={"origin": "chrome-extension://abc"}) as ws:
        _hola(ws, contrasena=CLAVE)
        assert ws.receive_json()["tipo"] == "listo"


def test_contrasena_correcta_entrega_la_ficha(cliente):
    ficha = acceso.ficha_extension(CLAVE)
    with cliente.websocket_connect(SOCKET) as ws:
        _hola(ws, contrasena=CLAVE)
        assert ws.receive_json() == {"tipo": "listo", "ficha": ficha}
    with cliente.websocket_connect(SOCKET) as ws:
        _hola(ws, ficha=ficha)
        assert ws.receive_json() == {"tipo": "listo", "ficha": ficha}


def test_ficha_vieja_tras_cambiar_la_contrasena_cierra_con_4401(cliente, monkeypatch):
    vieja = acceso.ficha_extension(CLAVE)
    monkeypatch.setenv("JUDICABOT_PASSWORD", "nueva-clave")
    assert _cierre(cliente, ficha=vieja) == 4401


def test_demasiados_intentos_cierra_con_4429(cliente):
    for _ in range(acceso.MAX_FALLOS):
        assert _cierre(cliente, contrasena="mala") == 4401
    assert _cierre(cliente, contrasena=CLAVE) == 4429


def test_sin_contrasena_configurada_acepta(cliente, monkeypatch):
    monkeypatch.delenv("JUDICABOT_PASSWORD")
    with cliente.websocket_connect(SOCKET) as ws:
        _hola(ws)
        assert ws.receive_json() == {"tipo": "listo", "ficha": ""}


def test_pedir_pagina_sin_extension_no_espera(cliente):
    inicio = time.monotonic()
    assert extension.pedir_pagina(URL) == NO_CONECTADA
    assert time.monotonic() - inicio < 1


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x.htm",
        "https://www.corteconstitucional.gov.co/otra/x.htm",
        "http://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm",
    ],
)
def test_pedir_pagina_rechaza_urls_fuera_de_la_relatoria(cliente, url):
    with pytest.raises(ValueError):
        extension.pedir_pagina(url)


def test_pedir_pagina_devuelve_los_bytes_que_entrega_la_extension(cliente):
    cuerpo = b"<script src='encabezado.js'></script>" + bytes(range(256)) * 100
    with _conectada(cliente) as ws, ThreadPoolExecutor() as hilos:
        ws.send_json({"tipo": "latido"})
        futuro = hilos.submit(extension.pedir_pagina, URL)
        pedido = ws.receive_json()
        assert pedido == {"tipo": "pedido", "id": pedido["id"], "url": URL}
        assert re.fullmatch(r"[0-9a-f]{32}", pedido["id"])
        ws.send_bytes(_entrega(pedido["id"], 200, cuerpo))
        assert futuro.result(timeout=5) == Entrega("ok", cuerpo, "")


def test_codigo_http_de_error_es_rechazo(cliente):
    with _conectada(cliente) as ws:
        assert _responder(ws, 403, b"<html>Forbidden</html>") == Entrega("rechazo", None, "HTTP 403")


def test_error_de_la_extension_es_sin_respuesta(cliente):
    with _conectada(cliente) as ws:
        assert _responder(ws, None, detalle="Failed to fetch") == Entrega("sin_respuesta", None, "Failed to fetch")


def test_sin_respuesta_a_tiempo_suelta_la_conexion(cliente):
    with _conectada(cliente) as ws:
        inicio = time.monotonic()
        assert extension.pedir_pagina(URL, espera_s=0.2) == Entrega(
            "sin_respuesta", None, "la extensión no respondió a tiempo"
        )
        assert time.monotonic() - inicio < 1
        assert extension.conectada() is False
        assert ws.receive_json()["tipo"] == "pedido"
        with pytest.raises(WebSocketDisconnect) as cierre:
            ws.receive_json()
        assert cierre.value.code == 4408
        assert extension.pedir_pagina(URL) == NO_CONECTADA


def test_entrega_tardia_se_ignora(cliente):
    with _conectada(cliente) as ws, ThreadPoolExecutor() as hilos:
        primero = hilos.submit(extension.pedir_pagina, URL)
        vencido = ws.receive_json()["id"]
        ws.send_bytes(_entrega(vencido, 200, b"primera"))
        assert primero.result(timeout=5) == Entrega("ok", b"primera", "")
        segundo = hilos.submit(extension.pedir_pagina, URL)
        vigente = ws.receive_json()["id"]
        ws.send_bytes(_entrega(vencido, 200, b"tardia"))
        ws.send_bytes(b"no es una entrega")
        ws.send_bytes(b'["roto"]\n')
        ws.send_bytes(_entrega(vigente, 200, b"segunda"))
        assert segundo.result(timeout=5) == Entrega("ok", b"segunda", "")
        assert extension.conectada() is True


def test_pedidos_concurrentes_se_responden_por_id(cliente):
    with _conectada(cliente) as ws, ThreadPoolExecutor() as hilos:
        uno = hilos.submit(extension.pedir_pagina, URL)
        pedido_uno = ws.receive_json()
        dos = hilos.submit(extension.pedir_pagina, URL_OTRA)
        pedido_dos = ws.receive_json()
        assert (pedido_uno["url"], pedido_dos["url"]) == (URL, URL_OTRA)
        ws.send_bytes(_entrega(pedido_dos["id"], 200, b"dos"))
        ws.send_bytes(_entrega(pedido_uno["id"], 200, b"uno"))
        assert uno.result(timeout=5) == Entrega("ok", b"uno", "")
        assert dos.result(timeout=5) == Entrega("ok", b"dos", "")


def test_desconexion_con_pedido_pendiente_es_sin_respuesta(cliente):
    with ThreadPoolExecutor() as hilos:
        with _conectada(cliente) as ws:
            futuro = hilos.submit(extension.pedir_pagina, URL)
            ws.receive_json()
        assert futuro.result(timeout=5) == Entrega("sin_respuesta", None, "la extensión se desconectó")
    assert extension.conectada() is False


def test_entrega_anidada_en_exceso_se_descarta(cliente):
    with _conectada(cliente) as ws:
        ws.send_bytes(b"[" * 200000 + b"\n")
        assert _responder(ws, 200, b"pagina") == Entrega("ok", b"pagina", "")


def test_desconexion_de_la_mas_reciente_reintenta_en_otra(cliente):
    with _conectada(cliente) as vieja, ThreadPoolExecutor() as hilos:
        with _conectada(cliente) as nueva:
            futuro = hilos.submit(extension.pedir_pagina, URL)
            assert nueva.receive_json()["url"] == URL
        pedido = vieja.receive_json()
        assert pedido["url"] == URL
        vieja.send_bytes(_entrega(pedido["id"], 200, b"pagina"))
        assert futuro.result(timeout=5) == Entrega("ok", b"pagina", "")
        assert extension.conectada() is True


def test_paginas_de_varios_megabytes_pasan(cliente):
    cuerpo = os.urandom(5 * 1024 * 1024)
    with _conectada(cliente) as ws:
        assert _responder(ws, 200, cuerpo) == Entrega("ok", cuerpo, "")


@pytest.fixture
def relatoria_bloqueada(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("TUTELA2_CACHE_DIR", str(tmp_path / "cache"))

    def bloqueada(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", bloqueada)
    return tmp_path / "cache" / "relatoria"


def _iniciar_sesion(cliente: TestClient) -> None:
    r = cliente.post(
        "/login",
        content=f"password={CLAVE}",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_consulta_relatoria_exige_sesion(cliente, relatoria_bloqueada):
    assert cliente.get("/api/relatoria", params={"sentencia": "T-200/22"}).status_code == 401


def test_consulta_relatoria_sentencia_invalida(cliente, relatoria_bloqueada):
    _iniciar_sesion(cliente)
    assert cliente.get("/api/relatoria", params={"sentencia": "xyz"}).status_code == 422


def test_consulta_relatoria_por_la_extension_queda_en_cache(cliente, relatoria_bloqueada):
    _iniciar_sesion(cliente)
    with _conectada(cliente) as ws, ThreadPoolExecutor() as hilos:
        consulta = hilos.submit(cliente.get, "/api/relatoria", params={"sentencia": "T-200/22"})
        pedido = ws.receive_json()
        assert pedido["url"] == URL
        ws.send_bytes(_entrega(pedido["id"], 200, _pagina("T-200/22")))
        r = consulta.result(timeout=10)
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["estado"] == "ok" and cuerpo["extension_conectada"] is True
        assert cuerpo["sentencia"] == "T-200/22" and cuerpo["url"] == URL
        assert cuerpo["detalle"] == "" and cuerpo["extension"] is None and cuerpo["caracteres"] > 0
        assert (relatoria_bloqueada / "T-200-22.htm").read_bytes() == _pagina("T-200/22")

        consulta = hilos.submit(cliente.get, "/api/relatoria", params={"sentencia": "SU-319/26"})
        pedido = ws.receive_json()
        assert pedido["url"].endswith("/relatoria/2026/SU319-26.htm")
        ws.send_bytes(_entrega(pedido["id"], 200, SHELL_ANGULAR))
        cuerpo = consulta.result(timeout=10).json()
        assert cuerpo["estado"] == "no_publicada" and cuerpo["caracteres"] is None
        assert not (relatoria_bloqueada / "SU319-26.htm").exists()


def test_consulta_relatoria_sin_extension_es_inaccesible(cliente, relatoria_bloqueada):
    _iniciar_sesion(cliente)
    r = cliente.get("/api/relatoria", params={"sentencia": "T-200/22"})
    assert r.status_code == 200
    assert r.json() == {
        "sentencia": "T-200/22",
        "url": URL,
        "estado": "inaccesible",
        "detalle": "HTTP 403",
        "extension": "no_conectada",
        "caracteres": None,
        "extension_conectada": False,
    }
    assert not relatoria_bloqueada.exists()


RAIZ_EXTENSION = Path(__file__).resolve().parents[2] / "extension"


def _zip_extension(cliente: TestClient) -> zipfile.ZipFile:
    _iniciar_sesion(cliente)
    r = cliente.get("/api/extension/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    version = json.loads((RAIZ_EXTENSION / "manifest.json").read_text())["version"]
    assert r.headers["content-disposition"] == f'attachment; filename="judicabot-relatoria-{version}.zip"'
    return zipfile.ZipFile(BytesIO(r.content))


def _empaquetables() -> set[str]:
    return {
        ruta.relative_to(RAIZ_EXTENSION).as_posix()
        for ruta in RAIZ_EXTENSION.rglob("*")
        if ruta.is_file()
        and not any(p.startswith(".") or p in ("__pycache__", "node_modules") for p in ruta.relative_to(RAIZ_EXTENSION).parts)
        and ruta.relative_to(RAIZ_EXTENSION).parts[0] not in ("pruebas", "package.json")
    }


def test_zip_de_la_extension_trae_sus_archivos(cliente):
    zip_ = _zip_extension(cliente)
    nombres = zip_.namelist()
    assert all(nombre.startswith("judicabot-relatoria/") for nombre in nombres)
    relativos = {nombre.removeprefix("judicabot-relatoria/") for nombre in nombres}
    assert relativos == _empaquetables()
    assert {
        "manifest.json", "trabajador.js", "puente.js", "ventana.html", "ventana.js", "LEEME.md",
        "iconos/16.png", "iconos/32.png", "iconos/48.png", "iconos/128.png",
    } <= relativos
    assert "package.json" not in relativos
    assert not any(relativo.startswith("pruebas/") for relativo in relativos)
    for relativo in relativos:
        assert zip_.read(f"judicabot-relatoria/{relativo}") == (RAIZ_EXTENSION / relativo).read_bytes()


def test_zip_de_la_extension_trae_lo_que_pide_el_manifiesto(cliente):
    zip_ = _zip_extension(cliente)
    manifiesto = json.loads(zip_.read("judicabot-relatoria/manifest.json"))
    referidos = {
        manifiesto["background"]["service_worker"],
        manifiesto["action"]["default_popup"],
        *manifiesto["icons"].values(),
        *manifiesto["action"]["default_icon"].values(),
    }
    assert {f"judicabot-relatoria/{ruta}" for ruta in referidos} <= set(zip_.namelist())


def test_zip_de_la_extension_exige_sesion(cliente):
    assert cliente.get("/api/extension/zip").status_code == 401


def test_zip_de_la_extension_ausente_da_404(cliente, monkeypatch, tmp_path):
    monkeypatch.setattr(extension, "CARPETA", tmp_path / "no-existe")
    _iniciar_sesion(cliente)
    r = cliente.get("/api/extension/zip")
    assert r.status_code == 404
    assert r.json()["detail"] == "La extensión no está disponible en este servidor."
