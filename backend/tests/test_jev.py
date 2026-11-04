from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from tutela2 import config as config_mod
from tutela2 import jev as jev_mod
from tutela2.config import Config, JevConfig
from tutela2.jev import (
    ErrorJev,
    FakeJev,
    HttpJev,
    RespuestaJev,
    clave_valida,
    cliente_jev,
    descripcion_error,
    llamada_fallida,
    llamada_ia,
    transcribir_preguntas,
)
from tutela2.models import LlamadaIA

PREGUNTA_EJEMPLO = {
    "rol": {
        "type": "choice",
        "instructions": "¿Qué rol cumple el documento?",
        "criteria": {"fallo_a_quo": "Sentencia de primera instancia.", "otro": "Ninguno de los anteriores."},
    }
}

RESPUESTA_DOCUMENTADA = {
    "model": "jev-1.14.0",
    "answers": {
        "rol": {
            "type": "choice",
            "choice": "fallo_a_quo",
            "confidence": 0.93,
            "probabilities": {"fallo_a_quo": 0.93, "otro": 0.07},
        }
    },
    "usage": {"input_tokens": 434, "output_tokens": 12},
}

RESP = RespuestaJev(
    modelo="jev-1.14.0",
    respuestas=RESPUESTA_DOCUMENTADA["answers"],
    tokens_entrada=434,
    tokens_salida=12,
)


class ServidorLocal:
    def __init__(self) -> None:
        self.peticiones: list[dict] = []
        self.guion: list[tuple[int, object, dict]] = [(200, RESPUESTA_DOCUMENTADA, {})]
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                largo = int(self.headers.get("Content-Length", 0))
                cuerpo = self.rfile.read(largo)
                servidor.peticiones.append(
                    {
                        "metodo": self.command,
                        "ruta": self.path,
                        "headers": dict(self.headers.items()),
                        "json": json.loads(cuerpo.decode("utf-8")),
                    }
                )
                indice = min(len(servidor.peticiones), len(servidor.guion)) - 1
                estado, cuerpo_resp, cabeceras = servidor.guion[indice]
                crudo = cuerpo_resp if isinstance(cuerpo_resp, str) else json.dumps(cuerpo_resp)
                datos = crudo.encode("utf-8")
                self.send_response(estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                for k, v in cabeceras.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(datos)

            def log_message(self, *args) -> None:
                pass

        class Servidor(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, *args) -> None:
                pass

        self._httpd = Servidor(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._hilo = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self._hilo.start()

    @property
    def recibida(self) -> dict:
        return self.peticiones[-1]

    def responder(self, *guion: tuple[int, object] | tuple[int, object, dict]) -> None:
        self.guion = [(g[0], g[1], g[2] if len(g) > 2 else {}) for g in guion]

    def cerrar(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._hilo.join(timeout=5)


@pytest.fixture
def servidor_local(monkeypatch):
    for nombre in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(nombre, "127.0.0.1,localhost")
    servidor = ServidorLocal()
    yield servidor
    servidor.cerrar()


@pytest.fixture
def sin_esperas(monkeypatch):
    esperas: list[float] = []
    monkeypatch.setattr(jev_mod.time, "sleep", esperas.append)
    return esperas


def _http(servidor: ServidorLocal, **kw) -> HttpJev:
    return HttpJev("k-secreta-xyz", kw.pop("timeout_s", 5), pausa_s=kw.pop("pausa_s", 0), base_url=servidor.url, **kw)


def test_cliente_jev_apagado_o_sin_clave_devuelve_none(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cliente_jev(Config()) is None
    assert cliente_jev(Config(jev=JevConfig(modo="sombra"))) is None
    monkeypatch.setenv("JEV_API_KEY", "x")
    assert cliente_jev(Config()) is None
    assert isinstance(cliente_jev(Config(jev=JevConfig(modo="sombra"))), HttpJev)
    assert isinstance(cliente_jev(Config(jev=JevConfig(modo="relleno"))), HttpJev)


def test_cliente_jev_trata_una_clave_en_blanco_como_ausente(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "  \n")
    assert cliente_jev(Config(jev=JevConfig(modo="sombra"))) is None


def test_cliente_jev_usa_el_timeout_de_la_configuracion(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "x")
    cliente = cliente_jev(Config(jev=JevConfig(modo="sombra", timeout_s=7.5)))
    assert cliente.timeout_s == 7.5


def test_http_jev_arma_la_peticion_y_lee_la_respuesta(servidor_local):
    r = _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    recibida = servidor_local.recibida
    assert recibida["metodo"] == "POST" and recibida["ruta"] == "/v1/systemone"
    assert recibida["headers"]["Authorization"] == "Bearer k-secreta-xyz"
    assert recibida["headers"]["Content-Type"].startswith("application/json")
    assert recibida["json"] == {"state": "hola", "model": "jev-latest", "questions": PREGUNTA_EJEMPLO}
    assert r.modelo == "jev-1.14.0" and r.tokens_entrada == 434 and r.tokens_salida == 12
    assert r.respuestas["rol"]["choice"] == "fallo_a_quo"
    assert r.respuestas["rol"]["confidence"] == 0.93
    assert len(servidor_local.peticiones) == 1


def test_http_jev_envia_el_estado_objeto_con_tildes_intactas(servidor_local):
    estado = {"clausula": "Ampárese el derecho de petición", "accionadas": ["Ñandú S.A."]}
    _http(servidor_local).preguntar(estado, PREGUNTA_EJEMPLO, "jev-latest")
    assert servidor_local.recibida["json"]["state"] == estado


def test_http_jev_conserva_el_orden_de_las_opciones(servidor_local):
    inversa = {
        "rol": {**PREGUNTA_EJEMPLO["rol"], "criteria": dict(reversed(PREGUNTA_EJEMPLO["rol"]["criteria"].items()))}
    }
    _http(servidor_local).preguntar("hola", inversa, "jev-latest")
    assert list(servidor_local.recibida["json"]["questions"]["rol"]["criteria"]) == ["otro", "fallo_a_quo"]


def test_http_jev_acepta_una_respuesta_sin_uso(servidor_local):
    servidor_local.responder((200, {"model": "jev-1.14.0", "answers": RESPUESTA_DOCUMENTADA["answers"]}))
    r = _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert (r.tokens_entrada, r.tokens_salida) == (0, 0)


@pytest.mark.parametrize("estado", [400, 401, 422, 429, 500, 529])
def test_http_jev_reintenta_una_sola_vez_cualquier_error_http(servidor_local, sin_esperas, estado):
    servidor_local.responder((estado, {"error": "motivo"}))
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 2 and len(sin_esperas) == 1
    assert str(estado) in str(e.value) and "k-secreta-xyz" not in str(e.value)


def test_http_jev_por_defecto_hace_un_solo_reintento(monkeypatch):
    assert HttpJev("k", 5).reintentos == 1
    monkeypatch.setenv("JEV_API_KEY", "x")
    assert cliente_jev(Config(jev=JevConfig(modo="sombra"))).reintentos == 1


def test_http_jev_se_recupera_con_el_unico_reintento(servidor_local, sin_esperas):
    servidor_local.responder((500, {"error": "transitorio"}), (200, RESPUESTA_DOCUMENTADA))
    r = _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 2 and r.modelo == "jev-1.14.0"


def test_http_jev_reintenta_una_respuesta_que_no_es_json(servidor_local, sin_esperas):
    servidor_local.responder((200, "esto no es json"), (200, RESPUESTA_DOCUMENTADA))
    r = _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 2 and r.modelo == "jev-1.14.0"


def test_http_jev_trunca_el_cuerpo_del_error(servidor_local):
    servidor_local.responder((422, "x" * 5000))
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(str(e.value)) < 600


@pytest.mark.parametrize("estado", [429, 529])
def test_http_jev_reintenta_429_y_529_y_luego_falla(servidor_local, sin_esperas, estado):
    servidor_local.responder((estado, {"error": "saturado"}))
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local, reintentos=3).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 4 and len(sin_esperas) == 3
    assert str(estado) in str(e.value)


def test_http_jev_se_recupera_si_un_reintento_tiene_exito(servidor_local, sin_esperas):
    servidor_local.responder((429, {}), (529, {}), (200, RESPUESTA_DOCUMENTADA))
    r = _http(servidor_local, reintentos=3).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 3 and r.modelo == "jev-1.14.0"


def test_http_jev_espera_con_backoff_exponencial(servidor_local, sin_esperas):
    servidor_local.responder((429, {}))
    with pytest.raises(ErrorJev):
        _http(servidor_local, reintentos=3, pausa_s=0.5).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert sin_esperas == [0.5, 1.0, 2.0]


def test_http_jev_con_cero_reintentos_hace_una_sola_peticion(servidor_local, sin_esperas):
    servidor_local.responder((429, {}))
    with pytest.raises(ErrorJev):
        _http(servidor_local, reintentos=0).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 1 and sin_esperas == []


def test_http_jev_reintenta_errores_de_conexion_y_luego_falla(sin_esperas, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    cliente = HttpJev("k", 1, reintentos=2, pausa_s=0, base_url=f"http://127.0.0.1:{puerto}")
    with pytest.raises(ErrorJev) as e:
        cliente.preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(sin_esperas) == 2 and "conexi" in str(e.value).lower()


def test_http_jev_reintenta_una_vez_si_se_agota_el_tiempo_de_espera(sin_esperas, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(8)
        cliente = HttpJev("k", 0.1, pausa_s=1.0, base_url=f"http://127.0.0.1:{s.getsockname()[1]}")
        inicio = time.monotonic()
        with pytest.raises(ErrorJev) as e:
            cliente.preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
        assert time.monotonic() - inicio < 1.0
    assert sin_esperas == [1.0] and e.value.enviada is True


def test_http_jev_el_tiempo_agotado_durante_la_lectura_se_reintenta_una_vez(servidor_local, sin_esperas, monkeypatch):
    def lee_con_demora(self, *args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(jev_mod.http.client.HTTPResponse, "read", lee_con_demora)
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 2 and len(sin_esperas) == 1 and e.value.enviada is True


@pytest.mark.parametrize("clave", ["SECRETO-JEV\nx", "clave\u2013con-raya", "clave\u200bcon-cero", "con espacio"])
def test_http_jev_con_clave_no_valida_falla_sin_filtrar_la_clave(servidor_local, clave):
    cliente = HttpJev(clave, 5, pausa_s=0, base_url=servidor_local.url)
    with pytest.raises(ErrorJev) as e:
        cliente.preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    volcado = "".join(traceback.format_exception(e.value))
    assert servidor_local.peticiones == [] and e.value.enviada is False and e.value.reintentable is False
    assert clave not in volcado and "SECRETO" not in volcado and "raya" not in volcado


@pytest.mark.parametrize("timeout", [-1, 0])
def test_http_jev_con_tiempo_maximo_no_valido_falla_con_error_de_jev(servidor_local, timeout):
    cliente = HttpJev("k-secreta-xyz", timeout, pausa_s=0, base_url=servidor_local.url)
    with pytest.raises(ErrorJev) as e:
        cliente.preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert "k-secreta-xyz" not in "".join(traceback.format_exception(e.value))
    assert e.value.enviada is False and e.value.reintentable is False


def test_clave_valida_solo_acepta_ascii_visible_sin_espacios():
    assert clave_valida("sk-AbC_123.xyz~")
    for mala in ("", "a b", "a\nb", "a\tb", "ñ", "a\u2013b", "a\u200bb", "a\x7fb"):
        assert not clave_valida(mala)


@pytest.mark.parametrize("estado", [400, 401, 422, 500, 429, 529])
def test_error_http_de_jev_queda_marcado_como_enviado(servidor_local, sin_esperas, estado):
    servidor_local.responder((estado, {"error": "x"}))
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert e.value.enviada is True


def test_error_de_conexion_no_se_marca_como_enviado(sin_esperas, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    with pytest.raises(ErrorJev) as e:
        HttpJev("k", 1, reintentos=1, pausa_s=0, base_url=f"http://127.0.0.1:{puerto}").preguntar(
            "hola", PREGUNTA_EJEMPLO, "jev-latest"
        )
    assert e.value.enviada is False


def test_error_jev_por_defecto_no_esta_enviado_y_es_reintentable():
    assert ErrorJev("x").enviada is False and ErrorJev("x").reintentable is True
    assert str(ErrorJev("x", enviada=True)) == "x"


def test_llamada_fallida_registra_el_error_sin_texto_ni_clave():
    d = llamada_fallida("roles", "texto secreto", PREGUNTA_EJEMPLO, "jev-latest", ErrorJev("Jev respondió 500: boom", enviada=True))
    LlamadaIA.model_validate(d)
    assert d["proveedor"] == "jev" and d["nodo"] == "roles" and d["prompt_id"] == "jev-roles-v1"
    assert d["error"] == "Jev respondió 500: boom" and d["modelo_pedido"] == "jev-latest" and d["modelo_efectivo"] is None
    assert d["sha256_entrada"] == hashlib.sha256("texto secreto".encode("utf-8")).hexdigest()
    assert "texto secreto" not in json.dumps(d)
    assert "¿Qué rol cumple el documento?" in d["instrucciones"] and "- otro: Ninguno de los anteriores." in d["instrucciones"]


def test_error_inesperado_se_describe_sin_el_mensaje_original():
    assert descripcion_error(ErrorJev("Jev respondió 500")) == "Jev respondió 500"
    d = descripcion_error(ValueError("Invalid header value b'Bearer SECRETO'"))
    assert "ValueError" in d and "SECRETO" not in d


@pytest.mark.parametrize(
    "cuerpo",
    [
        "esto no es json",
        "[]",
        json.dumps({"model": "jev-1.14.0"}),
        json.dumps({"answers": []}),
        json.dumps({"answers": {"rol": "fallo_a_quo"}}),
    ],
)
def test_http_jev_rechaza_una_respuesta_mal_formada(servidor_local, cuerpo):
    servidor_local.responder((200, cuerpo))
    with pytest.raises(ErrorJev):
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")


def test_http_jev_no_sigue_redirecciones_con_la_clave(servidor_local):
    servidor_local.responder((302, {}, {"Location": "/otra"}))
    with pytest.raises(ErrorJev) as e:
        _http(servidor_local).preguntar("hola", PREGUNTA_EJEMPLO, "jev-latest")
    assert len(servidor_local.peticiones) == 2 and "302" in str(e.value)
    assert {p["ruta"] for p in servidor_local.peticiones} == {"/v1/systemone"}


def test_fake_jev_con_dict_responde_lo_mismo_y_registra_las_llamadas():
    fake = FakeJev(RESPUESTA_DOCUMENTADA["answers"])
    r1 = fake.preguntar("uno", PREGUNTA_EJEMPLO, "jev-latest")
    r2 = fake.preguntar({"dos": 2}, PREGUNTA_EJEMPLO, "jev-latest")
    assert isinstance(r1, RespuestaJev) and r1.respuestas == r2.respuestas == RESPUESTA_DOCUMENTADA["answers"]
    assert fake.llamadas == [("uno", PREGUNTA_EJEMPLO), ({"dos": 2}, PREGUNTA_EJEMPLO)]


def test_fake_jev_no_comparte_las_respuestas_entre_llamadas():
    fake = FakeJev({"rol": {"type": "choice", "choice": "otro", "confidence": 0.9, "probabilities": {}}})
    fake.preguntar("a", PREGUNTA_EJEMPLO, "jev-latest").respuestas["rol"]["choice"] = "alterado"
    assert fake.preguntar("b", PREGUNTA_EJEMPLO, "jev-latest").respuestas["rol"]["choice"] == "otro"


def test_fake_jev_con_callable_recibe_estado_y_preguntas():
    vistos = []

    def responder(estado, preguntas):
        vistos.append((estado, preguntas))
        return {"rol": {"type": "choice", "choice": "otro", "confidence": 0.5, "probabilities": {}}}

    r = FakeJev(responder).preguntar("texto", PREGUNTA_EJEMPLO, "jev-latest")
    assert vistos == [("texto", PREGUNTA_EJEMPLO)] and r.respuestas["rol"]["choice"] == "otro"


def test_fake_jev_propaga_el_error_del_callable_y_registra_la_llamada():
    def lanza(estado, preguntas):
        raise ErrorJev("429")

    fake = FakeJev(lanza)
    with pytest.raises(ErrorJev):
        fake.preguntar("texto", PREGUNTA_EJEMPLO, "jev-latest")
    assert fake.llamadas == [("texto", PREGUNTA_EJEMPLO)]


def test_llamada_ia_no_contiene_la_clave_ni_el_texto(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k-secreta-xyz")
    d = llamada_ia("roles", "texto secreto", PREGUNTA_EJEMPLO, RESP)
    volcado = json.dumps(d, ensure_ascii=False)
    assert d["proveedor"] == "jev" and "texto secreto" not in volcado and "k-secreta-xyz" not in volcado
    assert d["instrucciones"] and "texto secreto" not in d["instrucciones"]


def test_llamada_ia_es_un_registro_valido_con_los_hashes_de_lo_enviado():
    d = llamada_ia("roles", "texto secreto", PREGUNTA_EJEMPLO, RESP)
    LlamadaIA.model_validate(d)
    assert d["nodo"] == "roles" and d["prompt_id"] == "jev-roles-v1" and d["intento"] == 1
    assert d["modelo_efectivo"] == "jev-1.14.0"
    assert (d["tokens_entrada"], d["tokens_salida"]) == (434, 12)
    assert d["sha256_entrada"] == hashlib.sha256("texto secreto".encode("utf-8")).hexdigest()
    assert (
        d["sha256_instrucciones"]
        == hashlib.sha256(json.dumps(PREGUNTA_EJEMPLO, ensure_ascii=False).encode("utf-8")).hexdigest()
    )
    assert (
        d["sha256_salida"]
        == hashlib.sha256(json.dumps(RESP.respuestas, ensure_ascii=False).encode("utf-8")).hexdigest()
    )
    assert d["error"] is None
    assert d["instrucciones"] == (
        "=== rol ===\n¿Qué rol cumple el documento?\nOpciones:\n"
        "- fallo_a_quo: Sentencia de primera instancia.\n- otro: Ninguno de los anteriores."
    )


def test_llamada_ia_hashea_el_estado_objeto_y_distingue_el_orden_de_las_opciones():
    directa = llamada_ia("metadatos", {"a": "ñ"}, PREGUNTA_EJEMPLO, RESP)
    assert (
        directa["sha256_entrada"]
        == hashlib.sha256(json.dumps({"a": "ñ"}, ensure_ascii=False).encode("utf-8")).hexdigest()
    )
    invertida = {
        "rol": {**PREGUNTA_EJEMPLO["rol"], "criteria": dict(reversed(PREGUNTA_EJEMPLO["rol"]["criteria"].items()))}
    }
    assert (
        llamada_ia("metadatos", {"a": "ñ"}, invertida, RESP)["sha256_instrucciones"] != directa["sha256_instrucciones"]
    )
    assert llamada_ia("metadatos", {"a": "ñ"}, invertida, RESP)["instrucciones"] != directa["instrucciones"]


def test_transcripcion_de_las_preguntas_incluye_cada_pregunta_con_sus_opciones_y_nunca_el_estado():
    preguntas = {
        "sentido": {"type": "choice", "instructions": "¿Qué decide el fallo?", "criteria": {"ampara": "Concede.", "niega": "Deniega."}},
        "rol": {"type": "choice", "instructions": "¿Quién impugna?", "criteria": {"accionante": "Quien tutela."}},
    }
    texto = transcribir_preguntas(preguntas)
    assert texto.split("\n\n") == [
        "=== sentido ===\n¿Qué decide el fallo?\nOpciones:\n- ampara: Concede.\n- niega: Deniega.",
        "=== rol ===\n¿Quién impugna?\nOpciones:\n- accionante: Quien tutela.",
    ]
    d = llamada_ia("roles", "texto secreto del expediente", preguntas, RESP)
    assert d["instrucciones"] == texto and "texto secreto" not in d["instrucciones"]


@pytest.mark.parametrize("pregunta", [{}, {"type": "choice"}, {"criteria": {}}, {"instructions": "Solo instrucción"}])
def test_transcripcion_tolera_preguntas_sin_instrucciones_o_sin_criterios(pregunta):
    texto = transcribir_preguntas({"p": pregunta})
    assert texto.startswith("=== p ===") and "Opciones:" not in texto
    assert transcribir_preguntas({}) == ""


def test_llamada_ia_acepta_el_modelo_pedido():
    assert llamada_ia("roles", "t", PREGUNTA_EJEMPLO, RESP)["modelo_pedido"] == "jev-1.14.0"
    assert llamada_ia("roles", "t", PREGUNTA_EJEMPLO, RESP, modelo_pedido="jev-latest")["modelo_pedido"] == "jev-latest"


def test_jev_config_arranca_apagado_con_los_valores_iniciales():
    cfg = Config()
    assert cfg.jev == JevConfig()
    assert cfg.jev.modo == "apagado" and cfg.jev.modelo == "jev-latest"
    assert cfg.jev.umbral_confianza == 0.9 and cfg.jev.timeout_s == 60.0
    assert (cfg.jev.max_chars_cabecera, cfg.jev.max_chars_sentido, cfg.jev.concurrencia) == (1500, 2500, 6)


def test_jev_config_rechaza_un_modo_desconocido():
    with pytest.raises(ValidationError):
        JevConfig(modo="siempre")


def test_jev_config_sobrevive_al_guardado_y_una_config_antigua_carga_apagada(tmp_path):
    antigua = Config().model_dump()
    antigua.pop("jev")
    (tmp_path / "config.json").write_text(json.dumps(antigua), encoding="utf-8")
    assert config_mod.cargar(tmp_path).jev.modo == "apagado"
    config_mod.guardar(tmp_path, Config(jev=JevConfig(modo="sombra", umbral_confianza=0.8)))
    cargada = config_mod.cargar(tmp_path)
    assert cargada.jev.modo == "sombra" and cargada.jev.umbral_confianza == 0.8


@pytest.mark.parametrize("umbral", [90, 1.01, -0.1, float("nan")])
def test_jev_config_rechaza_un_umbral_fuera_de_0_a_1(umbral):
    with pytest.raises(ValidationError):
        JevConfig(umbral_confianza=umbral)
    with pytest.raises(ValidationError):
        Config.model_validate({"jev": {"umbral_confianza": umbral}})


@pytest.mark.parametrize("umbral", [0, 0.5, 1])
def test_jev_config_acepta_los_extremos_del_umbral(umbral):
    assert JevConfig(umbral_confianza=umbral).umbral_confianza == umbral


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_jev_config_rechaza_un_tiempo_maximo_no_positivo_o_infinito(timeout):
    with pytest.raises(ValidationError):
        JevConfig(timeout_s=timeout)
