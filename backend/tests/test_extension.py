from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
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
    monkeypatch.setattr(extension, "_avisos", [])
    return TestClient(server.app, base_url="http://127.0.0.1")


def _hola(ws, **campos) -> None:
    ws.send_json({"tipo": "hola", "version": "1.0.0", **campos})


def _entrega(id: str, codigo: int | None, cuerpo: bytes = b"", detalle: str = "", tipo: str | None = None) -> bytes:
    meta = {"id": id, "codigo": codigo, "detalle": detalle} | ({"tipo": tipo} if tipo is not None else {})
    return json.dumps(meta).encode() + b"\n" + cuerpo


def _cierre(cliente: TestClient, **campos) -> int:
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect(SOCKET) as ws:
            _hola(ws, **campos)
            ws.receive_json()
    return cierre.value.code


def _esperar(condicion, plazo_s: float = 5.0) -> None:
    limite = time.monotonic() + plazo_s
    while not condicion():
        assert time.monotonic() < limite, "la condición no se cumplió a tiempo"
        time.sleep(0.01)


@contextmanager
def _conectada(cliente: TestClient, version: str = "1.0.0"):
    antes = len(extension._conexiones)
    with cliente.websocket_connect(SOCKET) as ws:
        _hola(ws, contrasena=CLAVE, version=version)
        assert ws.receive_json()["tipo"] == "listo"
        _esperar(lambda: len(extension._conexiones) > antes)
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
        assert futuro.result(timeout=5) == Entrega("ok", cuerpo, "", 200)


def test_codigo_http_de_error_es_rechazo(cliente):
    with _conectada(cliente) as ws:
        assert _responder(ws, 403, b"<html>Forbidden</html>") == Entrega("rechazo", None, "HTTP 403", 403)


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
        assert primero.result(timeout=5) == Entrega("ok", b"primera", "", 200)
        segundo = hilos.submit(extension.pedir_pagina, URL)
        vigente = ws.receive_json()["id"]
        ws.send_bytes(_entrega(vencido, 200, b"tardia"))
        ws.send_bytes(b"no es una entrega")
        ws.send_bytes(b'["roto"]\n')
        ws.send_bytes(_entrega(vigente, 200, b"segunda"))
        assert segundo.result(timeout=5) == Entrega("ok", b"segunda", "", 200)
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
        assert uno.result(timeout=5) == Entrega("ok", b"uno", "", 200)
        assert dos.result(timeout=5) == Entrega("ok", b"dos", "", 200)


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
        assert _responder(ws, 200, b"pagina") == Entrega("ok", b"pagina", "", 200)


def test_desconexion_de_la_mas_reciente_reintenta_en_otra(cliente):
    with _conectada(cliente) as vieja, ThreadPoolExecutor() as hilos:
        with _conectada(cliente) as nueva:
            futuro = hilos.submit(extension.pedir_pagina, URL)
            assert nueva.receive_json()["url"] == URL
        pedido = vieja.receive_json()
        assert pedido["url"] == URL
        vieja.send_bytes(_entrega(pedido["id"], 200, b"pagina"))
        assert futuro.result(timeout=5) == Entrega("ok", b"pagina", "", 200)
        assert extension.conectada() is True


def test_paginas_de_varios_megabytes_pasan(cliente):
    cuerpo = os.urandom(5 * 1024 * 1024)
    with _conectada(cliente) as ws:
        assert _responder(ws, 200, cuerpo) == Entrega("ok", cuerpo, "", 200)


# --- Servicio de vigencia (extensión 1.1.0) -------------------------------------------------------------

URL_VIGENCIA = "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx"
CEDULA = "52987613"
FORMULARIO = {
    "__VIEWSTATE": "/wEPDwUKLTE5NDQ5ODQ2NA9kFgJmD2QWAgIDD2Q=",
    "__VIEWSTATEGENERATOR": "EC7CB15A",
    "__EVENTVALIDATION": "/wEdAAYAbrxA3yjlCxnI9ccEY07lO0MZsW5iiFxn+s0P04VVra==",
    "ddlCalidad": "1",
    "ddlTipoDocumento": "1",
    "txtDocumento": CEDULA,
    "btnTpVigente": "Generar",
}


def _pedir_vigencia(metodo: str = "POST", **cambios):
    formulario = None if metodo == "GET" else FORMULARIO | cambios
    return lambda: extension.pedir("vigencia", URL_VIGENCIA, metodo, formulario)


def test_la_tabla_de_servicios_fija_direcciones_metodos_y_versiones():
    relatoria, vigencia = extension.SERVICIOS["relatoria"], extension.SERVICIOS["vigencia"]
    assert set(extension.SERVICIOS) == {"relatoria", "vigencia"}
    assert (relatoria.metodos, relatoria.version_minima) == ({"GET"}, (1, 0, 0, 0))
    assert (vigencia.metodos, vigencia.version_minima, vigencia.url) == ({"GET", "POST"}, (1, 1, 0, 0), URL_VIGENCIA)
    assert extension.URL_VIGENCIA == URL_VIGENCIA
    assert list(vigencia.campos) == list(FORMULARIO)
    assert extension.ESPERA_S > extension.ESPERA_VIGENCIA_S == 75.0 > 60.0


def test_vigencia_sin_extension_no_envia_nada(cliente):
    assert extension.estado_conexion() == "no_conectada"
    inicio = time.monotonic()
    for metodo in ("GET", "POST"):
        with pytest.raises(extension.ExtensionNoConectada):
            _pedir_vigencia(metodo)()
    assert time.monotonic() - inicio < 1


@pytest.mark.parametrize("version", ["1.0.0", "1.0", "1.0.9", "0.9.9", "", "abc", "1.1.0-beta", "1..1", "١.١.٠"])
def test_una_extension_anterior_a_1_1_0_nunca_recibe_pedidos_de_vigencia(cliente, version):
    with _conectada(cliente, version) as ws, ThreadPoolExecutor() as hilos:
        assert extension.estado_conexion() == "desactualizada"
        assert extension.estado_conexion("vigencia") == "desactualizada"
        inicio = time.monotonic()
        for metodo in ("GET", "POST"):
            with pytest.raises(extension.ExtensionDesactualizada, match="1.1.0"):
                _pedir_vigencia(metodo)()
        assert time.monotonic() - inicio < 1
        assert extension.conectada() is True
        if extension.estado_conexion("relatoria") == "conectada":
            _relatoria_llega_primero(ws, hilos)
        else:
            assert extension.pedir_pagina(URL) == extension.DESACTUALIZADA
            assert extension.DESACTUALIZADA.estado == "no_conectada"


@pytest.mark.parametrize("version", ["1.1.0", "1.1", "1.1.0.0", "1.2.3", "2.0.0"])
def test_desde_1_1_0_la_extension_consulta_la_vigencia(cliente, version):
    with _conectada(cliente, version):
        assert extension.estado_conexion() == "conectada"
        assert extension.estado_conexion("relatoria") == "conectada"


def test_mensajes_exactos_de_vigencia_y_relatoria(cliente):
    pdf = b"%PDF-1.7\n" + os.urandom(2048)
    with _conectada(cliente, "1.1.0") as ws, ThreadPoolExecutor() as hilos:
        futuro = hilos.submit(_pedir_vigencia("GET"))
        pedido = ws.receive_json()
        assert pedido == {
            "tipo": "pedir", "id": pedido["id"], "servicio": "vigencia",
            "url": URL_VIGENCIA, "metodo": "GET", "formulario": None,
        }
        assert re.fullmatch(r"[0-9a-f]{32}", pedido["id"])
        ws.send_bytes(_entrega(pedido["id"], 200, b"<html>formulario</html>", tipo="text/html; charset=utf-8"))
        assert futuro.result(timeout=5) == Entrega("ok", b"<html>formulario</html>", "", 200, "text/html; charset=utf-8")

        desordenado = dict(reversed(FORMULARIO.items()))
        futuro = hilos.submit(extension.pedir, "vigencia", URL_VIGENCIA, "POST", desordenado)
        pedido = ws.receive_json()
        assert pedido == {
            "tipo": "pedir", "id": pedido["id"], "servicio": "vigencia",
            "url": URL_VIGENCIA, "metodo": "POST", "formulario": FORMULARIO,
        }
        assert list(pedido["formulario"]) == list(FORMULARIO)
        ws.send_bytes(_entrega(pedido["id"], 200, pdf, tipo="application/pdf"))
        assert futuro.result(timeout=5) == Entrega("ok", pdf, "", 200, "application/pdf")

        futuro = hilos.submit(extension.pedir_pagina, URL)
        pedido = ws.receive_json()
        assert pedido == {"tipo": "pedido", "id": pedido["id"], "url": URL}
        ws.send_bytes(_entrega(pedido["id"], 200, b"pagina"))
        assert futuro.result(timeout=5) == Entrega("ok", b"pagina", "", 200)


@pytest.mark.parametrize(
    ("codigo", "detalle", "tipo", "esperada"),
    [
        (500, "", "text/html", Entrega("rechazo", None, "HTTP 500", 500, "text/html")),
        (429, "", None, Entrega("rechazo", None, "HTTP 429", 429)),
        (403, "", "text/html", Entrega("rechazo", None, "HTTP 403", 403, "text/html")),
        (None, "signal timed out", None, Entrega("sin_respuesta", None, "signal timed out")),
        (None, "", None, Entrega("sin_respuesta", None, "la extensión no pudo descargar la página")),
    ],
)
def test_la_entrega_de_vigencia_trae_codigo_y_tipo(cliente, codigo, detalle, tipo, esperada):
    with _conectada(cliente, "1.1.0") as ws, ThreadPoolExecutor() as hilos:
        futuro = hilos.submit(_pedir_vigencia())
        id_ = ws.receive_json()["id"]
        ws.send_bytes(_entrega(id_, codigo, b"<html>Error</html>", detalle, tipo))
        assert futuro.result(timeout=5) == esperada


def test_tipo_ilegible_o_enorme_se_recorta_o_se_ignora(cliente):
    with _conectada(cliente, "1.1.0") as ws, ThreadPoolExecutor() as hilos:
        futuro = hilos.submit(_pedir_vigencia())
        ws.send_bytes(_entrega(ws.receive_json()["id"], 200, b"%PDF-", tipo="x" * 5000))
        assert futuro.result(timeout=5).tipo == "x" * extension.MAX_TIPO
        futuro = hilos.submit(_pedir_vigencia())
        id_ = ws.receive_json()["id"]
        ws.send_bytes(json.dumps({"id": id_, "codigo": 200, "detalle": "", "tipo": ["application/pdf"]}).encode() + b"\n%PDF-")
        assert futuro.result(timeout=5) == Entrega("ok", b"%PDF-", "", 200, None)


def test_vigencia_va_a_la_extension_mas_reciente_que_la_hace(cliente):
    with _conectada(cliente, "1.1.0") as nueva_version, ThreadPoolExecutor() as hilos:
        with _conectada(cliente, "1.0.0") as vieja_version:
            futuro = hilos.submit(_pedir_vigencia())
            pedido = nueva_version.receive_json()
            assert pedido["servicio"] == "vigencia"
            nueva_version.send_bytes(_entrega(pedido["id"], 200, b"%PDF-", tipo="application/pdf"))
            assert futuro.result(timeout=5).estado == "ok"

            futuro = hilos.submit(extension.pedir_pagina, URL)
            pedido = vieja_version.receive_json()
            assert pedido == {"tipo": "pedido", "id": pedido["id"], "url": URL}
            vieja_version.send_bytes(_entrega(pedido["id"], 200, b"pagina"))
            assert futuro.result(timeout=5).estado == "ok"


def _relatoria_llega_primero(ws, hilos: ThreadPoolExecutor) -> None:
    """El siguiente mensaje que recibe esa extensión es un pedido nuevo de la relatoría: antes no se le envió nada."""
    futuro = hilos.submit(extension.pedir_pagina, URL)
    pedido = ws.receive_json()
    assert pedido == {"tipo": "pedido", "id": pedido["id"], "url": URL}
    ws.send_bytes(_entrega(pedido["id"], 200, b"pagina"))
    assert futuro.result(timeout=5) == Entrega("ok", b"pagina", "", 200)


def test_vigencia_sin_respuesta_a_tiempo_lanza_y_no_repite_en_otra(cliente):
    with _conectada(cliente, "1.1.0") as otra, ThreadPoolExecutor() as hilos:
        with _conectada(cliente, "1.1.0") as ws:
            inicio = time.monotonic()
            with pytest.raises(TimeoutError):
                extension.pedir("vigencia", URL_VIGENCIA, "POST", FORMULARIO, espera_s=0.2)
            assert time.monotonic() - inicio < 1
            assert ws.receive_json()["metodo"] == "POST"
            with pytest.raises(WebSocketDisconnect) as cierre:
                ws.receive_json()
            assert cierre.value.code == 4408
        assert extension.estado_conexion() == "conectada"
        assert len(extension._conexiones) == 1 and not extension._conexiones[0].pendientes
        _relatoria_llega_primero(otra, hilos)


def test_vigencia_con_la_extension_caida_no_se_repite_en_otra(cliente):
    with _conectada(cliente, "1.1.0") as otra, ThreadPoolExecutor() as hilos:
        with _conectada(cliente, "1.1.0") as ws:
            futuro = hilos.submit(_pedir_vigencia())
            ws.receive_json()
        assert futuro.result(timeout=5) == extension.DESCONECTADA
        assert len(extension._conexiones) == 1 and not extension._conexiones[0].pendientes
        _relatoria_llega_primero(otra, hilos)


def test_el_formulario_exacto_pasa_la_lista_del_servidor(cliente):
    with pytest.raises(extension.ExtensionNoConectada):
        extension.pedir("vigencia", URL_VIGENCIA, "POST", dict(FORMULARIO))
    for documento in ("12345", "1234567890"):
        with pytest.raises(extension.ExtensionNoConectada):
            _pedir_vigencia(txtDocumento=documento)()


@pytest.mark.parametrize(
    "formulario",
    [
        pytest.param(FORMULARIO | {"cedula": CEDULA}, id="campo-extra"),
        pytest.param(FORMULARIO | {"txtNombre": "PEREZ"}, id="otro-campo-extra"),
        pytest.param({k: v for k, v in FORMULARIO.items() if k != "btnTpVigente"}, id="falta-un-campo"),
        pytest.param({k: v for k, v in FORMULARIO.items() if not k.startswith("__")}, id="sin-campos-ocultos"),
        pytest.param(FORMULARIO | {"ddlTipoDocumento": "2"}, id="cedula-de-extranjeria"),
        pytest.param(FORMULARIO | {"ddlTipoDocumento": "4"}, id="ppt"),
        pytest.param(FORMULARIO | {"ddlTipoDocumento": " 1"}, id="tipo-con-espacio"),
        pytest.param(FORMULARIO | {"ddlCalidad": "4"}, id="licencia-temporal"),
        pytest.param(FORMULARIO | {"btnTpVigente": "Otro"}, id="otro-boton"),
        pytest.param(FORMULARIO | {"txtDocumento": CEDULA + "x"}, id="cedula-con-letra"),
        pytest.param(FORMULARIO | {"txtDocumento": "52.987.613"}, id="cedula-con-puntos"),
        pytest.param(FORMULARIO | {"txtDocumento": "1234"}, id="cedula-corta"),
        pytest.param(FORMULARIO | {"txtDocumento": "12345678901"}, id="cedula-larga"),
        pytest.param(FORMULARIO | {"txtDocumento": CEDULA + "\n"}, id="cedula-con-salto"),
        pytest.param(FORMULARIO | {"txtDocumento": "５２９８７６１３"}, id="digitos-de-ancho-completo"),
        pytest.param(FORMULARIO | {"txtDocumento": "٥٢٩٨٧٦١٣"}, id="digitos-arabigos"),
        pytest.param(FORMULARIO | {"txtDocumento": 52987613}, id="cedula-numerica"),
        pytest.param(FORMULARIO | {"txtDocumento": ""}, id="cedula-vacia"),
        pytest.param(FORMULARIO | {"__VIEWSTATEGENERATOR": "ec7cb15a"}, id="generador-en-minusculas"),
        pytest.param(FORMULARIO | {"__VIEWSTATE": "abc&txtNombre=PEREZ"}, id="estado-con-otro-campo"),
        pytest.param(FORMULARIO | {"__VIEWSTATE": "datos del expediente"}, id="estado-con-espacios"),
        pytest.param(FORMULARIO | {"__VIEWSTATE": "A" * 100001}, id="estado-enorme"),
        pytest.param(FORMULARIO | {"__EVENTVALIDATION": "A" * 20001}, id="validacion-enorme"),
        pytest.param(None, id="sin-formulario"),
        pytest.param(list(FORMULARIO.items()), id="lista"),
    ],
)
def test_la_lista_del_servidor_rechaza_cualquier_otro_formulario(cliente, formulario):
    with pytest.raises(ValueError) as error:
        extension.pedir("vigencia", URL_VIGENCIA, "POST", formulario)
    assert CEDULA not in str(error.value)
    assert "PEREZ" not in str(error.value) and "expediente" not in str(error.value)


def test_un_formulario_que_cabe_en_cada_campo_pero_excede_el_cuerpo_se_rechaza(cliente):
    largo = FORMULARIO | {"__VIEWSTATE": "A" * 100000, "__EVENTVALIDATION": "A" * 20000}
    with pytest.raises(extension.ExtensionNoConectada):
        extension.pedir("vigencia", URL_VIGENCIA, "POST", largo)
    codificado_enorme = FORMULARIO | {"__VIEWSTATE": "+" * 90000}
    with pytest.raises(ValueError, match="supera 256000 bytes"):
        extension.pedir("vigencia", URL_VIGENCIA, "POST", codificado_enorme)


@pytest.mark.parametrize(
    ("servicio", "url", "metodo", "formulario"),
    [
        ("vigencia", URL_VIGENCIA + "?txtDocumento=" + CEDULA, "GET", None),
        ("vigencia", URL_VIGENCIA + "#x", "GET", None),
        ("vigencia", "http://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx", "POST", FORMULARIO),
        ("vigencia", "https://vigenciaspublicas.ramajudicial.gov.co/certificados.aspx", "POST", FORMULARIO),
        ("vigencia", "https://vigenciaspublicas.ramajudicial.gov.co/Otra.aspx", "POST", FORMULARIO),
        ("vigencia", "https://vigenciaspublicas.ramajudicial.gov.co:8443/Certificados.aspx", "POST", FORMULARIO),
        ("vigencia", "https://evil.example/Certificados.aspx", "POST", FORMULARIO),
        ("vigencia", URL, "GET", None),
        ("vigencia", URL_VIGENCIA, "PUT", FORMULARIO),
        ("vigencia", URL_VIGENCIA, "post", FORMULARIO),
        ("vigencia", URL_VIGENCIA, "DELETE", None),
        ("vigencia", URL_VIGENCIA, "GET", FORMULARIO),
        ("relatoria", URL, "POST", FORMULARIO),
        ("relatoria", URL, "GET", FORMULARIO),
        ("relatoria", URL_VIGENCIA, "GET", None),
        ("otro", URL_VIGENCIA, "GET", None),
    ],
)
def test_la_lista_del_servidor_rechaza_otras_direcciones_y_metodos(cliente, servicio, url, metodo, formulario):
    with _conectada(cliente, "1.1.0") as ws, ThreadPoolExecutor() as hilos:
        with pytest.raises(ValueError) as error:
            extension.pedir(servicio, url, metodo, formulario)
        assert CEDULA not in str(error.value)
        _relatoria_llega_primero(ws, hilos)


def test_al_conectar_avisa_solo_por_extensiones_que_consultan_la_vigencia(cliente):
    avisos: list[tuple[str, bool]] = []
    llego = threading.Event()

    def falla() -> None:
        raise RuntimeError("el aviso falló")

    def aviso() -> None:
        try:
            asyncio.get_running_loop()
            en_bucle = True
        except RuntimeError:
            en_bucle = False
        avisos.append((threading.current_thread().name, en_bucle))
        llego.set()

    assert extension.al_conectar(falla) is falla
    extension.al_conectar(aviso)
    extension.al_conectar(aviso)
    with _conectada(cliente, "1.0.0"):
        assert not llego.wait(0.3)
    with _conectada(cliente, "1.1.0"):
        assert llego.wait(5)
        time.sleep(0.1)
        assert avisos == [("extension-al-conectar", False)]
        assert extension.estado_conexion() == "conectada"
    llego.clear()
    with _conectada(cliente, "1.2.0"):
        assert llego.wait(5)
    assert len(avisos) == 2


def test_ningun_registro_ni_error_contiene_la_cedula(cliente, caplog):
    caplog.set_level(logging.DEBUG)
    errores: list[str] = []
    for invalido in (FORMULARIO | {"txtDocumento": CEDULA + "0000"}, FORMULARIO | {"cedula": CEDULA}):
        with pytest.raises(ValueError) as error:
            extension.pedir("vigencia", URL_VIGENCIA, "POST", invalido)
        errores.append(str(error.value))
    with pytest.raises(extension.ExtensionNoConectada) as error:
        extension.pedir("vigencia", URL_VIGENCIA, "POST", FORMULARIO)
    errores.append(str(error.value))
    with _conectada(cliente, "1.0.0"):
        with pytest.raises(extension.ExtensionDesactualizada) as error:
            extension.pedir("vigencia", URL_VIGENCIA, "POST", FORMULARIO)
        errores.append(str(error.value))
    with _conectada(cliente, "1.1.0") as ws, ThreadPoolExecutor() as hilos:
        futuro = hilos.submit(_pedir_vigencia())
        pedido = ws.receive_json()
        assert pedido["formulario"]["txtDocumento"] == CEDULA
        ws.send_bytes(b"no es una entrega")
        ws.send_bytes(_entrega(pedido["id"], 500, b"<html>" + CEDULA.encode() + b"</html>", tipo="text/html"))
        ws.send_bytes(_entrega(pedido["id"], 200, b"tardia"))
        assert futuro.result(timeout=5).codigo == 500
        with pytest.raises(TimeoutError) as error:
            extension.pedir("vigencia", URL_VIGENCIA, "POST", FORMULARIO, espera_s=0.2)
        errores.append(str(error.value))
        assert ws.receive_json()["formulario"] == FORMULARIO
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert any("tardía" in r.getMessage() for r in caplog.records)
    assert any("no respondió a tiempo" in r.getMessage() for r in caplog.records)
    assert CEDULA not in caplog.text
    assert not any(CEDULA in e for e in errores)


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
