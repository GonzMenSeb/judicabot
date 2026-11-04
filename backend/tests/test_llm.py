from __future__ import annotations

import functools
import itertools
import json
import logging
import time
import types
from pathlib import Path

import anthropic
import pytest
from anthropic.lib._parse._transform import to_json_output_format

from tutela2 import citas, lint, llm
from tutela2.config import Config, LLMConfig
from tutela2.llm import AnthropicClient, ErrorLLM, FakeClient, cliente_para
from tutela2.models import AperturaLLM, CasoConcretoLLM, ConsideracionesLLM, Decision, MetadatosLLM
from tutela2.prompts import prompt_default

try:
    import httpx2 as httpx
except ImportError:
    import httpx

CASO = CasoConcretoLLM(problema_juridico="p", parrafos=[], conclusion="c")
BETA = "server-side-fallback-2026-07-01"


def respuesta(parsed=CASO, stop="end_turn", modelo="claude-efectivo", texto=None, iteraciones=None):
    uso = types.SimpleNamespace(input_tokens=11, output_tokens=7, iterations=iteraciones)
    if texto is None and parsed is not None:
        texto = parsed.model_dump_json()
    contenido = [types.SimpleNamespace(type="thinking", thinking="x")]
    if texto is not None:
        contenido.append(types.SimpleNamespace(type="text", text=texto))
    return types.SimpleNamespace(content=contenido, stop_reason=stop, model=modelo, usage=uso)


def error_400(mensaje: str) -> anthropic.BadRequestError:
    peticion = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(
        mensaje, response=httpx.Response(400, request=peticion), body={"error": {"message": mensaje}}
    )


class SDKEspia:
    instancias: list["SDKEspia"] = []
    guion: list = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.llamadas: list[dict] = []
        self.flujos: list[Flujo] = []
        self.messages = self
        self.beta = types.SimpleNamespace(messages=BetaEspia(self))
        self.opciones: dict = {}
        SDKEspia.instancias.append(self)

    def with_options(self, **opciones):
        self.opciones.update(opciones)
        return self

    def stream(self, **kwargs):
        self.llamadas.append(kwargs)
        return self.abrir()

    def abrir(self):
        siguiente = SDKEspia.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        flujo = siguiente if isinstance(siguiente, Flujo) else Flujo(siguiente)
        self.flujos.append(flujo)
        return flujo


class BetaEspia:
    def __init__(self, padre):
        self.padre = padre

    def stream(self, **kwargs):
        self.padre.llamadas.append({"beta": True, **kwargs})
        return self.padre.abrir()


class Flujo:
    def __init__(self, final, trozos=None):
        self.final = final
        self.trozos = trozos
        self.consumido = 0
        self.cerrado = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cerrado = True
        return False

    @property
    def text_stream(self):
        for trozo in self._trozos():
            self.consumido += len(trozo)
            yield trozo

    def _trozos(self):
        if self.trozos is not None:
            return self.trozos
        texto = "".join(b.text for b in self.final.content if b.type == "text")
        return [texto[i : i + 40] for i in range(0, len(texto), 40)]

    def get_final_message(self):
        return self.final


@pytest.fixture
def sdk(monkeypatch):
    SDKEspia.instancias, SDKEspia.guion = [], []
    monkeypatch.setattr(anthropic, "Anthropic", SDKEspia)
    return SDKEspia


def llamar(cfg: Config | None = None, nodo: str = "apertura"):
    cliente = AnthropicClient()
    return cliente.estructurado(nodo, "sistema", "usuario", CasoConcretoLLM, cfg or Config())


def test_el_cliente_se_crea_sin_argumentos_para_tomar_la_clave_del_entorno(sdk):
    sdk.guion = [respuesta()]
    llamar()
    assert len(sdk.instancias) == 1
    assert sdk.instancias[0].args == () and sdk.instancias[0].kwargs == {}


def test_cliente_para_elige_proveedor(sdk):
    assert isinstance(cliente_para(Config()), AnthropicClient)
    assert len(sdk.instancias) == 1
    falso = Config(llm=LLMConfig(proveedor="fake"))
    assert isinstance(cliente_para(falso), FakeClient)
    assert len(sdk.instancias) == 1


def test_parametros_enviados_a_messages_stream(sdk):
    sdk.guion = [respuesta()]
    cfg = Config(
        llm=LLMConfig(
            modelo="claude-opus-5-5",
            effort="high",
            max_tokens=12345,
            timeout_s=321.0,
            modelo_por_nodo={"caso_concreto": "claude-sonnet-5-5"},
            effort_por_nodo={"caso_concreto": "medium"},
        )
    )
    salida, meta = llamar(cfg, "caso_concreto")
    kwargs = sdk.instancias[0].llamadas[0]

    assert salida == CASO
    assert meta == {
        "modelo_efectivo": "claude-efectivo",
        "tokens_entrada": 11,
        "tokens_salida": 7,
        "stop_reason": "end_turn",
    }
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["max_tokens"] == 12345
    assert kwargs["system"] == "sistema"
    assert kwargs["messages"] == [{"role": "user", "content": "usuario"}]
    assert "output_format" not in kwargs
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"] == to_json_output_format(CasoConcretoLLM)
    assert sdk.instancias[0].opciones == {"max_retries": 1}
    assert kwargs["timeout"] == 321.0
    assert kwargs["betas"] == [BETA] and kwargs["fallbacks"] == "default" and kwargs["beta"] is True
    assert "extra_headers" not in kwargs and "extra_body" not in kwargs
    assert not {"temperature", "thinking", "top_p", "top_k"} & set(kwargs)


def test_nodo_sin_override_usa_modelo_y_effort_globales(sdk):
    sdk.guion = [respuesta()]
    llamar(Config(llm=LLMConfig(modelo="claude-haiku-5-5", effort="low")), "consideraciones")
    kwargs = sdk.instancias[0].llamadas[0]
    assert kwargs["model"] == "claude-haiku-5-5" and kwargs["output_config"]["effort"] == "low"


def test_sin_fallbacks_no_se_envian_cabecera_ni_cuerpo_extra(sdk):
    sdk.guion = [respuesta()]
    llamar(Config(llm=LLMConfig(fallbacks_default=False)))
    kwargs = sdk.instancias[0].llamadas[0]
    assert not {"extra_headers", "extra_body", "betas", "fallbacks", "beta"} & set(kwargs)


def test_error_400_de_fallbacks_reintenta_una_vez_sin_ellos(sdk, caplog):
    sdk.guion = [error_400("fallbacks: Extra inputs are not permitted"), respuesta()]
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        salida, _ = llamar()
    primera, segunda = sdk.instancias[0].llamadas
    assert salida == CASO
    assert primera["fallbacks"] == "default" and primera["betas"] == [BETA]
    assert not {"beta", "betas", "fallbacks"} & set(segunda)
    assert {k: v for k, v in primera.items() if k not in ("beta", "betas", "fallbacks")} == segunda
    assert any("fallbacks" in r.getMessage() for r in caplog.records)


def test_el_reintento_ocurre_una_sola_vez(sdk):
    sdk.guion = [error_400("fallbacks no soportado"), error_400("fallbacks no soportado")]
    with pytest.raises(ErrorLLM, match="BadRequestError"):
        llamar()
    assert len(sdk.instancias[0].llamadas) == 2


def test_otro_error_400_no_se_reintenta(sdk):
    sdk.guion = [error_400("prompt is too long")]
    with pytest.raises(ErrorLLM, match="prompt is too long"):
        llamar()
    assert len(sdk.instancias[0].llamadas) == 1


@pytest.mark.parametrize(
    "r, texto",
    [
        (respuesta(None, "refusal"), "rechazó"),
        (respuesta(None, "max_tokens"), "llm.max_tokens"),
        (respuesta(None, "end_turn"), "salida estructurada"),
        (respuesta(None, "max_tokens", texto='{"problema_juridico": "p", "parr'), "llm.max_tokens"),
        (respuesta(None, "refusal", texto='{"problema'), "rechazó"),
    ],
)
def test_respuestas_inutilizables_levantan_error_llm(sdk, r, texto):
    sdk.guion = [r]
    with pytest.raises(ErrorLLM, match=texto):
        llamar()


def test_fallos_de_red_o_de_servicio_son_error_llm(sdk):
    peticion = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk.guion = [anthropic.APIConnectionError(request=peticion)]
    with pytest.raises(ErrorLLM, match="APIConnectionError"):
        llamar()


def cuerpo_sse(texto: str, stop: str = "end_turn", modelo: str = "claude-efectivo") -> bytes:
    def ev(tipo: str, datos: dict) -> str:
        return f"event: {tipo}\ndata: {json.dumps({'type': tipo, **datos})}\n\n"

    mensaje = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": modelo, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 0},
    }
    partes = [
        ev("message_start", {"message": mensaje}),
        ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": texto}}),
        ev("content_block_stop", {"index": 0}),
        ev("message_delta", {"delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 2}}),
        ev("message_stop", {}),
    ]
    return "".join(partes).encode()


def sdk_real(manejador) -> anthropic.Anthropic:
    transporte = httpx.MockTransport(manejador)
    return anthropic.Anthropic(api_key="clave", http_client=httpx.Client(transport=transporte), max_retries=0)


def sse(texto: str, stop: str = "end_turn", modelo: str = "claude-efectivo") -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo_sse(texto, stop, modelo))


def sse_con_fallback(texto: str, origen: str, destino: str) -> httpx.Response:
    def ev(tipo: str, datos: dict) -> str:
        return f"event: {tipo}\ndata: {json.dumps({'type': tipo, **datos})}\n\n"

    iteraciones = [
        {"type": "message", "input_tokens": 1000, "output_tokens": 50,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        {"type": "fallback_message", "model": destino, "input_tokens": 1100, "output_tokens": 30,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    ]
    mensaje = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": origen, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 0},
    }
    fallback = {"type": "fallback", "from": {"model": origen}, "to": {"model": destino}, "trigger": {"type": "refusal"}}
    cuerpo = "".join(
        [
            ev("message_start", {"message": mensaje}),
            ev("content_block_start", {"index": 0, "content_block": fallback}),
            ev("content_block_stop", {"index": 0}),
            ev("content_block_start", {"index": 1, "content_block": {"type": "text", "text": ""}}),
            ev("content_block_delta", {"index": 1, "delta": {"type": "text_delta", "text": texto}}),
            ev("content_block_stop", {"index": 1}),
            ev(
                "message_delta",
                {"delta": {"stop_reason": "end_turn", "stop_sequence": None},
                 "usage": {"output_tokens": 80, "iterations": iteraciones}},
            ),
            ev("message_stop", {}),
        ]
    )
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo.encode())


def test_sdk_real_el_reintento_viaja_sin_fallbacks_ni_cabecera_beta():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if len(peticiones) == 1:
            return httpx.Response(
                400,
                json={"type": "error", "error": {"type": "invalid_request_error", "message": "fallbacks: no permitido"}},
            )
        return sse(CASO.model_dump_json())

    salida, meta = AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, Config())
    assert salida == CASO and len(peticiones) == 2 and meta["tokens_entrada"] == 3
    primero, segundo = (json.loads(p.content) for p in peticiones)
    assert primero["fallbacks"] == "default" and BETA in peticiones[0].headers["anthropic-beta"]
    assert "fallbacks" not in segundo and BETA not in peticiones[1].headers.get("anthropic-beta", "")
    assert meta["modelo_efectivo"] == "claude-efectivo"
    for cuerpo in (primero, segundo):
        assert cuerpo["stream"] is True and cuerpo["max_tokens"] == 64000
        assert cuerpo["output_config"]["effort"] == "high" and cuerpo["output_config"]["format"]["type"] == "json_schema"
        assert not {"temperature", "thinking"} & set(cuerpo)


def test_sdk_real_haiku_va_sin_fallbacks_y_ante_rechazo_repite_con_sonnet(caplog):
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if len(peticiones) == 1:
            return sse("", "refusal", "claude-haiku-5-5")
        return sse(CASO.model_dump_json(), modelo="claude-sonnet-5-5")

    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5"))
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        salida, meta = AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert salida == CASO and len(peticiones) == 2
    assert meta["modelo_efectivo"] == "claude-sonnet-5-5" and meta["tokens_entrada"] == 6 and meta["tokens_salida"] == 4
    primero, segundo = (json.loads(p.content) for p in peticiones)
    assert primero["model"] == "claude-haiku-5-5" and "fallbacks" not in primero
    assert BETA not in peticiones[0].headers.get("anthropic-beta", "")
    assert segundo["model"] == "claude-sonnet-5-5" and segundo["fallbacks"] == "default"
    assert "claude-sonnet-5-5" in caplog.text


def test_sdk_real_haiku_y_sonnet_rechazan_levanta_error_con_ambos_modelos():
    n = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return sse("", "refusal")

    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5"))
    with pytest.raises(ErrorLLM, match="claude-haiku-5-5 y claude-sonnet-5-5"):
        AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert n == 2


@pytest.mark.parametrize("modelo, destino", [("claude-sonnet-5-5", "claude-sonnet-5"), ("claude-opus-5-5", "claude-opus-5")])
def test_sdk_real_fallback_del_servidor_reetiqueta_modelo_y_suma_tokens(modelo, destino):
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return sse_con_fallback(CASO.model_dump_json(), modelo, destino)

    cfg = Config(llm=LLMConfig(modelo=modelo))
    salida, meta = AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert salida == CASO and len(peticiones) == 1
    assert meta["modelo_efectivo"] == destino
    assert meta["tokens_entrada"] == 2100 and meta["tokens_salida"] == 80
    assert json.loads(peticiones[0].content)["fallbacks"] == "default"


def test_sdk_real_haiku_no_repite_con_sonnet_si_este_no_esta_permitido(monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-haiku-5-5,claude-opus-5-5")
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return sse("", "refusal", "claude-haiku-5-5")

    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5"))
    with pytest.raises(ErrorLLM, match="El modelo rechazó la solicitud") as e:
        AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert "claude-sonnet-5-5" not in str(e.value)
    assert [json.loads(p.content)["model"] for p in peticiones] == ["claude-haiku-5-5"]


def test_sdk_real_haiku_sin_fallbacks_activados_no_repite_el_rechazo():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return sse("", "refusal")

    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5", fallbacks_default=False))
    with pytest.raises(ErrorLLM, match="refusal"):
        AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert len(peticiones) == 1


def test_sdk_real_la_llamada_larga_va_en_streaming_sin_la_guarda_de_diez_minutos():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return sse(CASO.model_dump_json())

    cfg = Config(llm=LLMConfig(fallbacks_default=False, max_tokens=128000, timeout_s=1200.0))
    AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert json.loads(peticiones[0].content)["stream"] is True


def test_sdk_real_los_reintentos_del_sdk_se_acotan_con_max_retries():
    n = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "caido"}})

    cfg = Config(llm=LLMConfig(fallbacks_default=False, max_retries=0))
    transporte = httpx.MockTransport(manejador)
    cliente = anthropic.Anthropic(api_key="k", http_client=httpx.Client(transport=transporte), max_retries=5)
    with pytest.raises(ErrorLLM):
        AnthropicClient(cliente).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert n == 1


def test_sdk_real_respuesta_truncada_con_texto_dice_max_tokens():
    cfg = Config(llm=LLMConfig(fallbacks_default=False))
    cliente = AnthropicClient(sdk_real(lambda p: sse('{"problema_juridico": "p", "parr', "max_tokens")))
    with pytest.raises(ErrorLLM, match="llm.max_tokens"):
        cliente.estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)


def test_sdk_real_enum_con_otra_capitalizacion_no_tumba_la_apertura():
    texto = AperturaLLM(
        metadatos=MetadatosLLM(), cronologia=[], antecedentes_hechos="a", contestaciones=[],
        sentencia_impugnada="s", impugnacion="i", reparos=[],
    ).model_dump_json().replace('"impugnante_rol":""', '"impugnante_rol":"Accionante"').replace(
        '"genero_accionadas":""', '"genero_accionadas":"F"'
    )
    assert "Accionante" in texto
    cfg = Config(llm=LLMConfig(fallbacks_default=False))
    salida, _ = AnthropicClient(sdk_real(lambda p: sse(texto))).estructurado("apertura", "s", "u", AperturaLLM, cfg)
    assert salida.metadatos.impugnante_rol == "accionante" and salida.metadatos.genero_accionadas == "f"


def test_error_de_esquema_detalla_los_campos(sdk):
    sdk.guion = [respuesta(None, texto='{"problema_juridico": "p", "parrafos": 3, "conclusion": "c"}')]
    with pytest.raises(ErrorLLM, match="parrafos"):
        llamar()


def test_tokens_de_la_bitacora_suman_las_iteraciones_del_fallback(sdk):
    it = [types.SimpleNamespace(input_tokens=100, output_tokens=5), types.SimpleNamespace(input_tokens=40, output_tokens=9)]
    sdk.guion = [respuesta(iteraciones=it)]
    _, meta = llamar()
    assert meta["tokens_entrada"] == 140 and meta["tokens_salida"] == 14


def test_sdk_real_sin_clave_da_error_claro(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(ErrorLLM, match="ANTHROPIC_API_KEY"):
        AnthropicClient().estructurado("apertura", "s", "u", CasoConcretoLLM, Config())


def test_esquemas_aceptados_por_salida_estructurada():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter

    for esquema in (AperturaLLM, ConsideracionesLLM, CasoConcretoLLM):
        transformado = transform_schema(TypeAdapter(esquema).json_schema())
        assert transformado["type"] == "object" and transformado["properties"]


def _complejidad(esquema: dict) -> tuple[int, int]:
    opcionales = uniones = 0

    def visita(o):
        nonlocal opcionales, uniones
        if isinstance(o, dict):
            if "properties" in o:
                req = set(o.get("required", []))
                opcionales += len([k for k in o["properties"] if k not in req])
            uniones += "anyOf" in o
            for v in o.values():
                visita(v)
        elif isinstance(o, list):
            for v in o:
                visita(v)

    visita(esquema)
    return opcionales, uniones


def test_esquema_de_apertura_lejos_de_los_limites_de_complejidad():
    formato = to_json_output_format(AperturaLLM)
    opcionales, uniones = _complejidad(formato["schema"])
    assert formato["type"] == "json_schema" and opcionales <= 8 and uniones <= 4
    props = formato["schema"]["$defs"]["MetadatosLLM"]["properties"]
    assert all(p.get("description") for p in props.values())


def test_fake_client_es_determinista_y_no_crea_el_sdk(sdk):
    cfg = Config(llm=LLMConfig(proveedor="fake"))
    user = llm.seccion("DECISION", json.dumps({"resultado": "REVOCAR", "sustitutiva": "AMPARAR"})) + llm.seccion(
        "REPAROS", "[]"
    )
    a, meta = FakeClient().estructurado("caso_concreto", "s", user, CasoConcretoLLM, cfg)
    b, _ = FakeClient().estructurado("caso_concreto", "s", user, CasoConcretoLLM, cfg)
    assert a == b and "revocar" in a.conclusion and "amparar" in a.conclusion
    assert meta["stop_reason"] == "end_turn" and meta["modelo_efectivo"] == "fake"
    assert sdk.instancias == []


def test_fake_client_rechaza_esquemas_desconocidos():
    with pytest.raises(ErrorLLM, match="MetadatosLLM"):
        FakeClient().estructurado("apertura", "s", "u", MetadatosLLM, Config())


CAMPOS_NUEVOS = (
    "impugnantes",
    "resultado_a_quo",
    "resultado_a_quo_se",
    "accionante_tratamiento",
    "accionante_identificacion",
    "juez_a_quo_nombres",
    "juez_a_quo_apellidos",
    "genero_accionadas",
    "genero_vinculadas",
)


def test_el_prompt_de_apertura_menciona_cada_campo_nuevo():
    texto = prompt_default("apertura")
    for campo in CAMPOS_NUEVOS:
        assert f"`{campo}`" in texto


def test_prompt_consideraciones_limita_la_procedibilidad():
    texto = prompt_default("consideraciones")
    for palabra in ("inmediatez", "subsidiariedad", "perjuicio irremediable", "legitimación"):
        assert palabra in texto


def test_prompt_caso_concreto_aplica_la_procedibilidad_antes_del_fondo():
    texto = prompt_default("caso_concreto")
    assert "legitimación en la causa, la inmediatez y la subsidiariedad" in texto


def test_fake_client_llena_los_campos_nuevos_de_apertura():
    cfg = Config(llm=LLMConfig(proveedor="fake"))
    user = llm.seccion("DOCUMENTOS", "") + llm.seccion("METADATOS", json.dumps({"impugnante": "Parte X"}))
    salida, _ = FakeClient().estructurado("apertura", "s", user, AperturaLLM, cfg)
    for campo in CAMPOS_NUEVOS:
        assert getattr(salida.metadatos, campo)
    assert salida.metadatos.impugnantes == ["Parte X"]
    assert salida.metadatos.resultado_a_quo == "resolvió la acción de tutela"
    assert salida.metadatos.resultado_a_quo_se == "resolvió la acción de tutela"


def test_esquema_de_apertura_dentro_de_los_limites_de_anthropic():
    fmt = to_json_output_format(AperturaLLM)
    assert "resultado_a_quo_se" in fmt["schema"]["$defs"]["MetadatosLLM"]["properties"]
    texto = json.dumps(fmt["schema"])
    assert texto.count('"anyOf"') <= 16


def test_los_prompts_explican_la_salida_anterior_en_los_reintentos():
    for nodo in ("apertura", "consideraciones", "caso_concreto"):
        assert "salida del intento anterior" in prompt_default(nodo)


def test_los_prompts_con_documentos_explican_el_aviso_de_documento_a_revisar():
    for nodo in ("apertura", "caso_concreto"):
        texto = prompt_default(nodo)
        assert '"[AVISO: ...]"' in texto and "otro radicado" in texto and "corrobor" in texto


def test_prompt_de_apertura_distingue_resultado_para_que_y_para_se_sin_ordenes():
    texto = prompt_default("apertura")
    assert "ir tras \"que\"" in texto and "ir tras \"se\"" in texto and "concordando en número" in texto
    assert "No incluyas las órdenes" in texto
    assert "incluidas las órdenes" not in texto


def test_prompt_consideraciones_no_deja_salida_sin_citas_ni_modela_la_formula_sin_marcador():
    texto = prompt_default("consideraciones")
    assert "o no cites" not in texto and "ha decantado" not in texto
    assert lint.jurisprudencia_sin_cita(texto, "prompt") == []


def test_prompt_consideraciones_pide_ratio_literal_y_excluye_normas_y_salvamentos():
    texto = prompt_default("consideraciones")
    assert "ratio decidendi" in texto and "una a tres frases completas" in texto
    assert "LIMITES" in texto
    for excluido in ("texto de la Constitución", "salvamento"):
        assert excluido in texto


MIN_PALABRAS_FAKE = 25


@pytest.mark.parametrize("id_", sorted(llm.CITAS_FAKE))
def test_citas_fake_cumplen_las_reglas_de_longitud_y_no_son_normativas(id_):
    _, texto = llm.CITAS_FAKE[id_]
    literal, *_ = citas._analizar_cita(citas._limpiar_cita(texto))
    assert len(literal) >= MIN_PALABRAS_FAKE
    normas = json.loads((Path(citas.__file__).parent / "assets" / "normas_citables.json").read_text(encoding="utf-8"))
    assert normas
    for norma in normas:
        assert (citas.cobertura(texto, norma["texto"], 6) or 0) < 0.5


def test_fake_consideraciones_no_atribuye_a_la_jurisprudencia_sin_marcador():
    cfg = Config(llm=LLMConfig(proveedor="fake"))
    user = llm.seccion("REPAROS", json.dumps([{"id": "R1", "sintesis": "s"}])) + llm.seccion("LIMITES", "Máximo: 3")
    salida, _ = FakeClient().estructurado("consideraciones", "s", user, ConsideracionesLLM, cfg)
    for b in salida.bloques:
        assert lint.jurisprudencia_sin_cita(b.texto, "bloque") == []
    assert lint.jurisprudencia_sin_cita(salida.procedibilidad, "procedibilidad") == []
    assert lint.marcadores_consideraciones(salida) == []


def _citas_json(**estados: str) -> str:
    return json.dumps([{"id": i, "estado": e} for i, e in estados.items()])


def _caso_fake(decision: dict, reparos: list[dict], citas: str | None = None) -> CasoConcretoLLM:
    user = llm.seccion("DECISION", json.dumps(decision)) + llm.seccion("REPAROS", json.dumps(reparos))
    if citas is not None:
        user += llm.seccion("CITAS", citas)
    salida, _ = FakeClient().estructurado("caso_concreto", "s", user, CasoConcretoLLM, Config(llm=LLMConfig(proveedor="fake")))
    return salida


REPARO = {"id": "R1", "sintesis": "El impugnante señala que no se valoró la prueba.", "disposicion": "ACOGE"}
DECISION_FAKE = {"resultado": "REVOCAR", "sustitutiva": "AMPARAR"}


def test_fake_caso_prefiere_las_citas_ok_a_las_que_estan_en_alerta():
    caso = _caso_fake(DECISION_FAKE, [REPARO], _citas_json(c1="alerta", c2="ok"))
    marcadores = [m for p in caso.parrafos for m in lint._MARCADOR.findall(p.texto)]
    assert marcadores == ["c2"]
    solo_alerta = _caso_fake(DECISION_FAKE, [REPARO], _citas_json(c1="alerta"))
    assert [m for p in solo_alerta.parrafos for m in lint._MARCADOR.findall(p.texto)] == ["c1"]


def test_fake_caso_sin_reparos_igual_deja_un_marcador():
    caso = _caso_fake(DECISION_FAKE, [], _citas_json(c1="ok"))
    assert [m for p in caso.parrafos for m in lint._MARCADOR.findall(p.texto)] == ["c1"]


def test_fake_caso_sin_citas_utilizables_no_inventa_marcadores():
    caso = _caso_fake(DECISION_FAKE, [REPARO], _citas_json(c1="rechazada"))
    assert not [m for p in caso.parrafos for m in lint._MARCADOR.findall(p.texto)]
    assert not [m for p in _caso_fake(DECISION_FAKE, [REPARO]).parrafos for m in lint._MARCADOR.findall(p.texto)]


@pytest.mark.parametrize("n_reparos", [0, 1, 3])
def test_fake_caso_la_conclusion_no_repite_el_ultimo_parrafo(n_reparos):
    temas = [
        "el juez de primera instancia no valoró los conceptos médicos aportados con la tutela y que demuestran la urgencia del procedimiento",
        "la acción se interpuso dentro de un plazo razonable porque la negativa de la entidad persiste y la afectación continúa cada día",
        "existen medios ordinarios que no resultan idóneos ni eficaces para proteger el mínimo vital de una persona en situación de vulnerabilidad",
    ]
    reparos = [{**REPARO, "id": f"R{i}", "sintesis": f"El impugnante señala que {temas[i - 1]}."} for i in range(1, n_reparos + 1)]
    ordenes = [{"verbo": "ORDENAR", "destinatario": "la entidad", "conducta": "pague", "plazo": {"n": 48, "unidad": "horas_habiles"}}]
    caso = _caso_fake({**DECISION_FAKE, "ordenes": ordenes}, reparos, _citas_json(c1="ok"))
    assert lint.duplicados_caso(caso, Config().jaccard_duplicados) == []


def test_fake_caso_menciona_el_plazo_de_cada_orden_con_plazo_propio():
    ordenes = [
        {"verbo": "ORDENAR", "destinatario": "la entidad uno", "conducta": "pague", "plazo": {"n": 3, "unidad": "dias"}},
        {"verbo": "ORDENAR", "destinatario": "la entidad dos", "conducta": "informe", "plazo": {"n": 48, "unidad": "horas_habiles"}},
        {"verbo": "PREVENIR", "destinatario": "la entidad tres", "conducta": "no reincida", "plazo": {"n": 9, "unidad": "dias"}},
        {"verbo": "ORDENAR", "destinatario": "la entidad cuatro", "conducta": "cumpla", "mismo_termino": True},
    ]
    decision = {**DECISION_FAKE, "ordenes": ordenes, "accion": "decidir"}
    caso = _caso_fake(decision, [REPARO], _citas_json(c1="ok"))
    assert lint.plazos_en_caso(caso, Decision.model_validate(decision)) == []
    sin_ordenes = _caso_fake(DECISION_FAKE, [REPARO], _citas_json(c1="ok"))
    assert not [p for p in sin_ordenes.parrafos if p.texto.startswith("Frente a las órdenes")]


def test_prompt_caso_concreto_exige_marcador_ok_y_prohibe_transcribir():
    texto = prompt_default("caso_concreto")
    assert "al menos un marcador de una cita con estado `ok`" in texto
    assert "Nunca transcribas" in texto and "se rechaza" in texto
    assert "el hecho relevante que consta en el expediente, la razón del Despacho" in texto
    assert "la regla jurisprudencial que la respalda, invocada solo con su marcador" in texto


def test_prompt_caso_concreto_motiva_las_ordenes_y_su_plazo_fuera_de_la_conclusion():
    texto = prompt_default("caso_concreto")
    assert "sección ORDENES" in texto
    assert "mencionando ese plazo tal como allí aparece" in texto
    assert "no en la conclusion" in texto.replace("conclusión", "conclusion")


def test_prompt_caso_concreto_pide_una_sola_conclusion():
    texto = prompt_default("caso_concreto")
    assert "La conclusión va solo en este campo" in texto
    assert "ningún párrafo la repite" in texto
    assert lint.jurisprudencia_sin_cita(texto, "prompt") == []


RELATORIA = Path(__file__).parent / "fixtures" / "relatoria"
PREFIJO_LAZO = (
    '{"problema_juridico":' + json.dumps(prompt_default("caso_concreto")[:500]) + ',"parrafos":[],"conclusion":"'
)
MENSAJE_DOS_LAZOS = (
    "El modelo entró en un lazo de repetición en dos intentos consecutivos; use 'continuar' para reintentar."
)


def lazo(veces: int = 5000, repeticion: str = "Fin.  ") -> Flujo:
    trozos = itertools.chain([PREFIJO_LAZO], itertools.repeat(repeticion, veces))
    return Flujo(respuesta(None, "max_tokens"), trozos=trozos)


def trozos_de(texto: str, n: int) -> list[str]:
    return [texto[i : i + n] for i in range(0, len(texto), n)]


def texto_sentencia(archivo: str) -> str:
    return citas._html_a_texto((RELATORIA / archivo).read_text(encoding="utf-8"))


def unidad_de(n: int) -> str:
    base = "Corresponde al Despacho determinar si la decision de primera instancia se ajusta a derecho. "
    return (base * 2)[:n]


@pytest.mark.parametrize(
    "texto",
    [
        "Fin.  " * 41,
        "Fin.  " * 500,
        PREFIJO_LAZO + "Fin.  " * 60,
        ("Fin.  " * 50)[:-2],
        unidad_de(80) * 12,
        unidad_de(40) * 12,
        unidad_de(7) * 40,
        "\\n" * 130,
        '"}],"x":[' + '{"a":"","b":""},' * 20,
        "[[CITA:c1]] " * 25,
        "." * 400,
        " " * 400,
        "\n" * 400,
        "texto normal " + "-" * 400,
    ],
)
def test_detecta_degeneracion_en_repeticiones_y_rachas(texto):
    assert llm.detectar_degeneracion(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "Fin.",
        "Fin.  " * 39,
        unidad_de(80) * 11,
        unidad_de(40) * 11,
        "." * 399,
        "=" * 399,
        " " * 300,
        "a" * 1000,
        "0" * 1000,
        "\n" + " " * 300 + "texto",
        "Fin.  " * 41 + texto_sentencia("T-1215-03.min.html")[:1500],
        "-" * 500 + "x",
        " ".join(f"[[CITA:c{i}]]" for i in range(1, 60)),
        "| Fecha | Valor |\n| --- | --- |\n" + "".join(f"| {i} | {i * 7} |\n" for i in range(200)),
        json.dumps([{"id": f"R{i}", "reparo_ids": ["R1"], "texto": "El Despacho considera."} for i in range(80)]),
        "\n".join("    " * (i % 6) + f"línea {i}" for i in range(300)),
    ],
)
def test_no_detecta_degeneracion_en_texto_legitimo(texto):
    assert llm.detectar_degeneracion(texto) is False


def test_la_deteccion_es_independiente_de_la_fase_y_de_donde_empieza_la_repeticion():
    base = "Fin.  " * 80
    assert all(llm.detectar_degeneracion(PREFIJO_LAZO + base[i:]) for i in range(6))
    assert all(llm.detectar_degeneracion(PREFIJO_LAZO + base[:-i or None]) for i in range(6))


def test_el_costo_de_la_deteccion_depende_de_la_cola_y_no_del_texto():
    enorme = "x" * 20_000_000 + texto_sentencia("C-774-01.min.html")[:3000]
    inicio = time.perf_counter()
    for _ in range(200):
        assert llm.detectar_degeneracion(enorme) is False
    assert time.perf_counter() - inicio < 1.0
    assert llm.detectar_degeneracion("Fin.  " * 1000 + texto_sentencia("C-774-01.min.html")[:3000]) is False


def _user_apertura(textos: list[str]) -> str:
    roles = ["escrito_tutela", "fallo_a_quo", "impugnacion", "contestacion", "auto_admisorio"]
    docs = "\n".join(f"### DOC d{i} | {rol} | {rol}.pdf\n{texto}" for i, (rol, texto) in enumerate(zip(roles, textos)))
    return llm.seccion("DOCUMENTOS", docs) + llm.seccion("METADATOS", "{}")


@functools.cache
def corpus_legitimo() -> dict[str, str]:
    cfg = Config(llm=LLMConfig(proveedor="fake"))
    sentencias = {f.name: texto_sentencia(f.name) for f in sorted(RELATORIA.glob("*.html"))}
    corpus: dict[str, str] = {}
    for nombre, texto in sentencias.items():
        corpus[f"relatoria/{nombre}"] = texto
        corpus[f"relatoria-json/{nombre}"] = json.dumps(texto)
    for nodo in ("apertura", "consideraciones", "caso_concreto"):
        texto = prompt_default(nodo)
        corpus[f"prompt/{nodo}"] = texto
        corpus[f"prompt-json/{nodo}"] = json.dumps(texto)
    textos = list(sentencias.values())
    apertura, _ = FakeClient().estructurado("apertura", "s", _user_apertura(textos), AperturaLLM, cfg)
    reparos = [{**REPARO, "id": f"R{i}", "sintesis": ln} for i, ln in enumerate(textos[0].splitlines()[:12], start=1)]
    user_cons = llm.seccion("REPAROS", json.dumps(reparos)) + llm.seccion("LIMITES", "Máximo: 3")
    cons, _ = FakeClient().estructurado("consideraciones", "s", user_cons, ConsideracionesLLM, cfg)
    ordenes = [{"verbo": "ORDENAR", "destinatario": "la entidad", "conducta": "pague", "plazo": {"n": 48, "unidad": "horas_habiles"}}]
    caso = _caso_fake({**DECISION_FAKE, "ordenes": ordenes}, reparos, _citas_json(c1="ok", c2="ok"))
    for nombre, salida in (("apertura", apertura), ("consideraciones", cons), ("caso", caso)):
        corpus[f"fake/{nombre}"] = salida.model_dump_json()
        corpus[f"fake-indent/{nombre}"] = json.dumps(salida.model_dump(mode="json"), indent=4, ensure_ascii=False)
    return corpus


@pytest.mark.parametrize("paso", [1, 7])
@pytest.mark.parametrize("nombre", sorted(corpus_legitimo()))
def test_el_corpus_legitimo_llega_completo_sin_disparar_el_corte(nombre, paso):
    texto = corpus_legitimo()[nombre]
    flujo = Flujo(respuesta(None, texto=texto), trozos=trozos_de(texto, paso))
    final = llm._consumir(flujo)
    assert final.stop_reason == "end_turn" and flujo.consumido == len(texto)


def test_el_corpus_cubre_los_tres_esquemas_del_fake_y_las_cinco_sentencias():
    nombres = corpus_legitimo()
    assert {"fake/apertura", "fake/consideraciones", "fake/caso"} <= set(nombres)
    assert len([n for n in nombres if n.startswith("relatoria/")]) == 5
    assert all(len(nombres[n]) > 2000 for n in nombres if n.startswith(("relatoria/", "prompt/")))
    assert "[[CITA:c1]]" in nombres["fake/caso"]


def test_el_consumo_del_flujo_levanta_lazo_degenerado_sin_texto_del_modelo():
    flujo = lazo()
    with pytest.raises(llm.ErrorLLMDegenerado) as e:
        llm._consumir(flujo)
    assert isinstance(e.value, ErrorLLM)
    assert "Fin." not in str(e.value) and PREFIJO_LAZO[30:60] not in str(e.value)
    assert 0 < flujo.consumido - len(PREFIJO_LAZO) < 2000


def test_un_stream_largo_y_normal_no_se_corta_y_se_consume_completo(sdk):
    parrafos = [
        llm.ParrafoLLM(reparo_ids=["R1"], texto=f"{ln} [[CITA:c1]] [[CITA:c2]] [[CITA:c3]]")
        for ln in texto_sentencia("C-313-14.min.html").splitlines()[:60]
    ]
    caso = CasoConcretoLLM(problema_juridico="p", parrafos=parrafos, conclusion="c")
    sdk.guion = [respuesta(caso)]
    salida, _ = llamar()
    assert salida == caso
    flujo = sdk.instancias[0].flujos[0]
    assert len(sdk.instancias[0].llamadas) == 1 and flujo.consumido == len(caso.model_dump_json()) > 5000


def test_lazo_en_la_ruta_beta_por_defecto_se_corta_pronto_y_se_repite_la_misma_llamada(sdk, caplog):
    sdk.guion = [lazo(), respuesta()]
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        salida, meta = llamar(Config(), "caso_concreto")
    espia = sdk.instancias[0]
    primero, segundo = espia.flujos
    assert salida == CASO
    assert len(espia.llamadas) == 2 and all(l["beta"] is True and l["fallbacks"] == "default" for l in espia.llamadas)
    assert {k: v for k, v in espia.llamadas[0].items()} == {k: v for k, v in espia.llamadas[1].items()}
    assert primero.cerrado and 0 < primero.consumido - len(PREFIJO_LAZO) < 2000
    assert segundo.cerrado and segundo.consumido == len(CASO.model_dump_json())
    assert meta["tokens_entrada"] == 11 and meta["tokens_salida"] == 7
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 1 and "repetición" in avisos[0].getMessage()
    assert "Fin." not in caplog.text and PREFIJO_LAZO[30:60] not in caplog.text


def test_lazo_sin_fallbacks_tambien_se_repite_una_vez(sdk):
    sdk.guion = [lazo(), respuesta()]
    salida, _ = llamar(Config(llm=LLMConfig(fallbacks_default=False)))
    assert salida == CASO
    assert [bool(l.get("beta")) for l in sdk.instancias[0].llamadas] == [False, False]


def test_dos_lazos_consecutivos_levantan_error_llm_y_no_hay_tercer_intento(sdk, caplog):
    sdk.guion = [lazo(), lazo(), respuesta()]
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        with pytest.raises(ErrorLLM) as e:
            llamar()
    assert type(e.value) is ErrorLLM and str(e.value) == MENSAJE_DOS_LAZOS
    espia = sdk.instancias[0]
    assert len(espia.llamadas) == 2 and all(f.cerrado for f in espia.flujos)
    assert all(0 < f.consumido - len(PREFIJO_LAZO) < 2000 for f in espia.flujos)
    assert len(sdk.guion) == 1
    assert "Fin." not in caplog.text and PREFIJO_LAZO[30:60] not in caplog.text


def test_el_reintento_por_lazo_convive_con_el_rechazo_de_fallbacks_de_la_api(sdk):
    sdk.guion = [error_400("fallbacks: Extra inputs are not permitted"), lazo(), respuesta()]
    salida, meta = llamar()
    llamadas = sdk.instancias[0].llamadas
    assert salida == CASO and meta["tokens_entrada"] == 11
    assert [bool(l.get("beta")) for l in llamadas] == [True, False, False]
    assert not {"betas", "fallbacks"} & set(llamadas[1]) and llamadas[1] == llamadas[2]


def test_una_llamada_abortada_no_devuelve_uso_y_no_suma_tokens_ni_borra_los_previos(sdk):
    sdk.guion = [
        respuesta(None, "refusal", modelo="claude-haiku-5-5"),
        lazo(),
        respuesta(modelo="claude-sonnet-5-5"),
    ]
    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5"))
    salida, meta = llamar(cfg)
    assert salida == CASO and len(sdk.instancias[0].llamadas) == 3
    assert meta["modelo_efectivo"] == "claude-sonnet-5-5"
    assert meta["tokens_entrada"] == 11 + 11 and meta["tokens_salida"] == 7 + 7


def test_lazo_y_error_del_proveedor_en_el_reintento_se_reportan_como_error_llm(sdk):
    peticion = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk.guion = [lazo(), anthropic.APIConnectionError(request=peticion)]
    with pytest.raises(ErrorLLM, match="APIConnectionError"):
        llamar()


def evento_sse(tipo: str, datos: dict) -> bytes:
    return f"event: {tipo}\ndata: {json.dumps({'type': tipo, **datos})}\n\n".encode()


def eventos_lazo(veces: int, modelo: str = "claude-efectivo"):
    mensaje = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": modelo, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 9, "output_tokens": 0},
    }
    yield evento_sse("message_start", {"message": mensaje})
    yield evento_sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
    yield evento_sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": PREFIJO_LAZO}})
    for _ in range(veces):
        yield evento_sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Fin.  "}})
    yield evento_sse("content_block_stop", {"index": 0})
    yield evento_sse(
        "message_delta", {"delta": {"stop_reason": "max_tokens", "stop_sequence": None}, "usage": {"output_tokens": 64000}}
    )
    yield evento_sse("message_stop", {})


@pytest.mark.parametrize("fallbacks", [True, False])
def test_sdk_real_el_lazo_se_corta_sin_leer_el_cuerpo_completo_y_la_llamada_se_repite(fallbacks):
    leidos: list[int] = []
    peticiones: list[httpx.Request] = []
    veces = 20000

    def cuerpo_lazo():
        for n, trozo in enumerate(eventos_lazo(veces)):
            leidos.append(n)
            yield trozo

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if len(peticiones) == 1:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo_lazo())
        return sse(CASO.model_dump_json())

    cfg = Config(llm=LLMConfig(fallbacks_default=fallbacks))
    salida, meta = AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert salida == CASO and len(peticiones) == 2
    assert 0 < len(leidos) < veces // 10
    assert meta["tokens_entrada"] == 3 and meta["tokens_salida"] == 2 and meta["stop_reason"] == "end_turn"
    primero, segundo = (json.loads(p.content) for p in peticiones)
    assert primero == segundo and primero["stream"] is True
    assert ("fallbacks" in primero) is fallbacks


def test_sdk_real_dos_lazos_levantan_error_llm_con_dos_peticiones():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=eventos_lazo(3000))

    with pytest.raises(ErrorLLM) as e:
        AnthropicClient(sdk_real(manejador)).estructurado("apertura", "s", "u", CasoConcretoLLM, Config())
    assert type(e.value) is ErrorLLM and str(e.value) == MENSAJE_DOS_LAZOS and len(peticiones) == 2
