from __future__ import annotations

import json
import logging
import types

import anthropic
import pytest
from anthropic.lib._parse._transform import to_json_output_format

from tutela2 import llm
from tutela2.config import Config, LLMConfig
from tutela2.llm import AnthropicClient, ErrorLLM, FakeClient, cliente_para
from tutela2.models import AperturaLLM, CasoConcretoLLM, ConsideracionesLLM, MetadatosLLM
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
        self.messages = self
        self.beta = types.SimpleNamespace(messages=BetaEspia(self))
        self.opciones: dict = {}
        SDKEspia.instancias.append(self)

    def with_options(self, **opciones):
        self.opciones.update(opciones)
        return self

    def stream(self, **kwargs):
        self.llamadas.append(kwargs)
        siguiente = SDKEspia.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return Flujo(siguiente)


class BetaEspia:
    def __init__(self, padre):
        self.padre = padre

    def stream(self, **kwargs):
        self.padre.llamadas.append({"beta": True, **kwargs})
        siguiente = SDKEspia.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return Flujo(siguiente)


class Flujo:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

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


def test_prompt_de_apertura_distingue_resultado_para_que_y_para_se_sin_ordenes():
    texto = prompt_default("apertura")
    assert "ir tras \"que\"" in texto and "ir tras \"se\"" in texto and "concordando en número" in texto
    assert "No incluyas las órdenes" in texto
    assert "incluidas las órdenes" not in texto
