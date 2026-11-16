from __future__ import annotations

import json
import logging

import pytest
from google import genai
from google.genai import _api_client, types

from tutela2 import config as cfgmod
from tutela2 import llm
from tutela2.config import Config, LLMConfig
from tutela2.llm import ErrorLLM, FakeClient, GeminiClient, cliente_para, esquema_gemini
from tutela2.models import AperturaLLM, CasoConcretoLLM, ConsideracionesLLM

try:
    import httpx2 as httpx
except ImportError:
    import httpx

CASO = CasoConcretoLLM(problema_juridico="p", parrafos=[], conclusion="c")
MENSAJE_DOS_LAZOS = (
    "El modelo entró en un lazo de repetición en dos intentos consecutivos; use 'continuar' para reintentar."
)
PREFIJO_LAZO = '{"problema_juridico": "' + "El Despacho analiza el asunto con cuidado. " * 8


def gemini(modelo: str = "gemini-4-argon", effort: str = "high", **extra) -> Config:
    return Config(llm=LLMConfig(proveedor="gemini", modelo=modelo, effort=effort, **extra))


def trozo(texto: str | None = None, fin: str | None = None, uso: dict | None = None, modelo: str | None = "gemini-4-argon-001") -> dict:
    datos: dict = {}
    if texto is not None or fin is not None:
        candidato: dict = {"index": 0, "content": {"role": "model", "parts": [{"text": texto}] if texto is not None else []}}
        if fin:
            candidato["finishReason"] = fin
        datos["candidates"] = [candidato]
    if uso:
        datos["usageMetadata"] = uso
    if modelo:
        datos["modelVersion"] = modelo
    return datos


def evento(datos: dict) -> bytes:
    return f"data: {json.dumps(datos)}\r\n\r\n".encode()


def sse(*trozos: dict) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"".join(evento(t) for t in trozos))


def respuesta_ok(texto: str | None = None, fin: str = "STOP", modelo: str | None = "gemini-4-argon-001") -> httpx.Response:
    texto = CASO.model_dump_json() if texto is None else texto
    mitad = len(texto) // 2
    uso = {"promptTokenCount": 120, "candidatesTokenCount": 30, "thoughtsTokenCount": 45, "totalTokenCount": 195}
    return sse(trozo(texto[:mitad], modelo=modelo), trozo(texto[mitad:], fin, uso, modelo))


def sdk_real(manejador) -> genai.Client:
    opciones = types.HttpOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(manejador)))
    return genai.Client(api_key="clave-de-prueba", vertexai=False, http_options=opciones)


def llamar(manejador, cfg: Config | None = None, nodo: str = "caso_concreto", schema=CasoConcretoLLM):
    return GeminiClient(sdk_real(manejador)).estructurado(nodo, "sistema", "usuario", schema, cfg or gemini())


@pytest.fixture
def sin_esperas(monkeypatch):
    monkeypatch.setattr(_api_client, "_RETRY_INITIAL_DELAY", 0.0)
    monkeypatch.setattr(_api_client, "_RETRY_JITTER", 0.0)


def test_flujo_completo_devuelve_el_objeto_y_la_meta():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return respuesta_ok()

    salida, meta = llamar(manejador)
    assert salida == CASO
    assert meta == {"modelo_efectivo": "gemini-4-argon-001", "tokens_entrada": 120, "tokens_salida": 75, "stop_reason": "STOP"}
    assert len(peticiones) == 1


def test_parametros_enviados_a_generate_content():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return respuesta_ok()

    cfg = gemini("gemini-4-carbon", "medium", max_tokens=12345, timeout_s=321.0)
    llamar(manejador, cfg)
    peticion = peticiones[0]
    cuerpo = json.loads(peticion.content)
    generacion = cuerpo["generationConfig"]
    assert peticion.url.path.endswith("/models/gemini-4-carbon:streamGenerateContent")
    assert peticion.url.params["alt"] == "sse"
    assert peticion.headers["x-goog-api-key"] == "clave-de-prueba"
    assert cuerpo["contents"] == [{"role": "user", "parts": [{"text": "usuario"}]}]
    assert cuerpo["systemInstruction"]["parts"] == [{"text": "sistema"}]
    assert cuerpo["store"] is False
    assert generacion["responseMimeType"] == "application/json"
    assert generacion["responseJsonSchema"] == esquema_gemini(CasoConcretoLLM)
    assert generacion["maxOutputTokens"] == 12345
    pensamiento = {k.replace("_", "").lower(): v for k, v in generacion["thinkingConfig"].items()}
    assert pensamiento == {"thinkinglevel": "MEDIUM"}
    assert not {"temperature", "topP", "topK", "responseSchema"} & set(generacion)
    assert peticion.headers["x-server-timeout"] == "321"
    assert set(peticion.extensions["timeout"].values()) == {321.0}


def test_el_nodo_usa_su_modelo_y_nivel_del_catalogo_de_gemini():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return respuesta_ok()

    cfg = gemini(modelo_por_nodo={"caso_concreto": "gemini-4-hydrogen"}, effort_por_nodo={"caso_concreto": "xhigh"})
    llamar(manejador, cfg)
    cuerpo = json.loads(peticiones[0].content)
    assert peticiones[0].url.path.endswith("/models/gemini-4-hydrogen:streamGenerateContent")
    assert list(cuerpo["generationConfig"]["thinkingConfig"].values()) == ["XHIGH"]


def test_sin_version_del_modelo_usa_el_id_pedido():
    _, meta = llamar(lambda p: respuesta_ok(modelo=None), gemini("gemini-4-hydrogen"))
    assert meta["modelo_efectivo"] == "gemini-4-hydrogen"


def test_el_uso_es_el_ultimo_no_nulo_del_flujo():
    texto = CASO.model_dump_json()
    primero = {"promptTokenCount": 9, "candidatesTokenCount": 1, "totalTokenCount": 10}
    ultimo = {"promptTokenCount": 9, "candidatesTokenCount": 4, "thoughtsTokenCount": 6, "totalTokenCount": 19}
    cuerpo = sse(trozo(texto[:5], uso=primero), trozo(texto[5:], uso=ultimo), trozo(fin="STOP"))
    _, meta = llamar(lambda p: cuerpo)
    assert meta["tokens_entrada"] == 9 and meta["tokens_salida"] == 10


def test_respuesta_truncada_pide_subir_max_tokens():
    with pytest.raises(ErrorLLM, match=r"límite de tokens \(64000\); aumente llm.max_tokens"):
        llamar(lambda p: respuesta_ok('{"problema_juridico": "p", "parr', "MAX_TOKENS"))


@pytest.mark.parametrize("motivo", ["SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "OTHER"])
def test_otro_motivo_de_cierre_se_nombra(motivo):
    with pytest.raises(ErrorLLM, match=rf"finish_reason={motivo}\)"):
        llamar(lambda p: respuesta_ok(fin=motivo))


def test_flujo_sin_motivo_de_cierre_es_error():
    texto = CASO.model_dump_json()
    with pytest.raises(ErrorLLM, match="finish_reason=ausente"):
        llamar(lambda p: sse(trozo(texto)))


def test_solicitud_bloqueada_nombra_el_motivo():
    bloqueo = {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}, "usageMetadata": {"promptTokenCount": 7, "totalTokenCount": 7}}
    with pytest.raises(ErrorLLM, match=r"block_reason=PROHIBITED_CONTENT"):
        llamar(lambda p: sse(bloqueo))


def test_texto_vacio_o_fuera_de_esquema_reutiliza_los_mensajes():
    with pytest.raises(ErrorLLM, match="no devolvió una salida estructurada"):
        llamar(lambda p: respuesta_ok("   "))
    with pytest.raises(ErrorLLM, match="no cumple el esquema: parrafos"):
        llamar(lambda p: respuesta_ok('{"problema_juridico": "p", "parrafos": 3, "conclusion": "c"}'))


def test_error_de_la_api_es_error_del_proveedor_sin_reintentos():
    n = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(400, json={"error": {"code": 400, "message": "schema inválido", "status": "INVALID_ARGUMENT"}})

    with pytest.raises(ErrorLLM, match=r"Error del proveedor \(ClientError\).*INVALID_ARGUMENT"):
        llamar(manejador, gemini(max_retries=3))
    assert n == 1


@pytest.mark.parametrize("reintentos", [0, 2])
def test_los_reintentos_del_sdk_siguen_max_retries(sin_esperas, reintentos):
    n = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(503, json={"error": {"code": 503, "message": "sobrecargado", "status": "UNAVAILABLE"}})

    with pytest.raises(ErrorLLM, match=r"Error del proveedor \(ServerError\)"):
        llamar(manejador, gemini(max_retries=reintentos))
    assert n == reintentos + 1


def test_un_reintento_del_sdk_recupera_la_respuesta(sin_esperas):
    n = 0

    def manejador(peticion: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}) if n == 1 else respuesta_ok()

    salida, _ = llamar(manejador, gemini(max_retries=1))
    assert salida == CASO and n == 2


def test_fallo_de_red_es_error_del_proveedor():
    def manejador(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=peticion)

    with pytest.raises(ErrorLLM, match=r"Error del proveedor \(ConnectError\)"):
        llamar(manejador, gemini(max_retries=0))


def cuerpo_lazo(veces: int, leidos: list[int]):
    yield evento(trozo(PREFIJO_LAZO))
    for n in range(veces):
        leidos.append(n)
        yield evento(trozo("Fin.  "))
    yield evento(trozo(fin="MAX_TOKENS", uso={"promptTokenCount": 9, "candidatesTokenCount": 64000, "totalTokenCount": 64009}))


def test_el_lazo_se_corta_sin_leer_el_cuerpo_completo_y_la_llamada_se_repite(caplog):
    leidos: list[int] = []
    peticiones: list[httpx.Request] = []
    veces = 20000

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if len(peticiones) == 1:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo_lazo(veces, leidos))
        return respuesta_ok()

    with caplog.at_level(logging.WARNING, logger="tutela2"):
        salida, meta = llamar(manejador)
    assert salida == CASO and len(peticiones) == 2
    assert 0 < len(leidos) < veces // 10
    assert meta["tokens_entrada"] == 120 and meta["tokens_salida"] == 75
    assert json.loads(peticiones[0].content) == json.loads(peticiones[1].content)
    assert "repetición" in caplog.text and "Fin." not in caplog.text


def test_dos_lazos_levantan_error_llm_con_dos_peticiones():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo_lazo(3000, []))

    with pytest.raises(ErrorLLM) as e:
        llamar(manejador)
    assert type(e.value) is ErrorLLM and str(e.value) == MENSAJE_DOS_LAZOS and len(peticiones) == 2


def test_lazo_y_error_del_proveedor_en_el_reintento_se_reportan_como_error_llm():
    peticiones: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if len(peticiones) == 1:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo_lazo(3000, []))
        return httpx.Response(500, json={"error": {"code": 500, "status": "INTERNAL"}})

    with pytest.raises(ErrorLLM, match=r"Error del proveedor \(ServerError\)"):
        llamar(manejador, gemini(max_retries=0))


def test_nivel_no_admitido_por_el_modelo_falla_antes_de_llamar():
    def manejador(peticion: httpx.Request) -> httpx.Response:
        raise AssertionError("no debía llamar")

    with pytest.raises(ErrorLLM, match=r"xhigh no es válido para gemini-4-argon \(admite: low, medium, high\)"):
        llamar(manejador, gemini("gemini-4-argon", "xhigh"))
    with pytest.raises(ErrorLLM, match="max no es válido"):
        llamar(manejador, gemini("gemini-4-hydrogen", "max"))


@pytest.fixture
def fabrica(monkeypatch):
    creados: list[dict] = []
    peticiones: list[httpx.Request] = []
    original = genai.Client

    def manejador(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return respuesta_ok()

    def crear(**kwargs):
        creados.append(kwargs)
        opciones = types.HttpOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(manejador)))
        return original(**kwargs, http_options=opciones)

    monkeypatch.setattr(genai, "Client", crear)
    return creados, peticiones


def test_sin_clave_de_gemini_el_error_lo_dice_y_no_se_crea_el_sdk(monkeypatch, fabrica):
    creados, peticiones = fabrica
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-google")
    with pytest.raises(ErrorLLM, match="GEMINI_API_KEY"):
        GeminiClient().estructurado("caso_concreto", "s", "u", CasoConcretoLLM, gemini())
    assert creados == [] and peticiones == []


@pytest.mark.parametrize("clave", ["AIzaSECRETO\r\nX", "AIzaSECRETO\tX", "AIza SECRETO", "AIzaSECRETOñ"])
def test_una_clave_con_caracteres_no_validos_no_llega_al_sdk_ni_a_los_mensajes(monkeypatch, fabrica, clave):
    creados, peticiones = fabrica
    monkeypatch.setenv("GEMINI_API_KEY", clave)
    with pytest.raises(ErrorLLM, match="GEMINI_API_KEY") as e:
        GeminiClient().estructurado("caso_concreto", "s", "u", CasoConcretoLLM, gemini())
    assert "SECRETO" not in str(e.value)
    assert creados == [] and peticiones == []


def test_la_clave_sale_de_gemini_api_key_aunque_exista_google_api_key(monkeypatch, fabrica):
    creados, peticiones = fabrica
    monkeypatch.setenv("GEMINI_API_KEY", " clave-de-gemini ")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-de-google")
    salida, _ = GeminiClient().estructurado("caso_concreto", "s", "u", CasoConcretoLLM, gemini())
    assert salida == CASO
    assert creados == [{"api_key": "clave-de-gemini", "vertexai": False}]
    assert peticiones[0].headers["x-goog-api-key"] == "clave-de-gemini"


def test_cliente_para_elige_gemini_sin_crear_el_sdk(monkeypatch, fabrica):
    creados, _ = fabrica
    monkeypatch.delenv(cfgmod.VARIABLE_MODELOS_PERMITIDOS, raising=False)
    assert isinstance(cliente_para(gemini()), GeminiClient)
    assert creados == []


CLAVES_ADMITIDAS = llm._CLAVES_GEMINI


def _claves(esquema, ruta="raíz"):
    if isinstance(esquema, dict):
        for clave, valor in esquema.items():
            if clave == "properties":
                for nombre, sub in valor.items():
                    yield from _claves(sub, f"{ruta}.{nombre}")
                continue
            yield clave, ruta
            yield from _claves(valor, f"{ruta}/{clave}")
    elif isinstance(esquema, list):
        for i, sub in enumerate(esquema):
            yield from _claves(sub, f"{ruta}[{i}]")


def _cumple(valor, esquema) -> bool:
    if "anyOf" in esquema:
        return any(_cumple(valor, o) for o in esquema["anyOf"])
    tipos = esquema["type"] if isinstance(esquema["type"], list) else [esquema["type"]]
    python = {"string": str, "array": list, "object": dict, "boolean": bool, "integer": int, "number": (int, float)}
    if valor is None:
        return "null" in tipos
    if not any(t != "null" and isinstance(valor, python[t]) for t in tipos):
        return False
    if "enum" in esquema and valor not in esquema["enum"]:
        return False
    if isinstance(valor, list):
        return all(_cumple(v, esquema["items"]) for v in valor)
    if isinstance(valor, dict):
        props = esquema["properties"]
        return set(esquema.get("required", [])) <= set(valor) and set(valor) <= set(props) and all(_cumple(v, props[k]) for k, v in valor.items())
    return True


ESQUEMAS = (AperturaLLM, ConsideracionesLLM, CasoConcretoLLM)


@pytest.mark.parametrize("schema", ESQUEMAS, ids=lambda s: s.__name__)
def test_esquema_convertido_sin_referencias_ni_claves_no_admitidas(schema):
    convertido = esquema_gemini(schema)
    texto = json.dumps(convertido)
    assert "$ref" not in texto and "$defs" not in texto
    assert {clave for clave, _ in _claves(convertido)} <= CLAVES_ADMITIDAS
    assert convertido["type"] == "object" and set(convertido["properties"]) == set(schema.model_fields)


@pytest.mark.parametrize("schema", ESQUEMAS, ids=lambda s: s.__name__)
def test_esquema_convertido_conserva_campos_obligatorios_y_enum(schema):
    original = schema.model_json_schema()
    defs = original.get("$defs", {})
    convertido = esquema_gemini(schema)

    def comparar(o: dict, c: dict):
        if "$ref" in o:
            o = defs[o["$ref"].split("/")[-1]]
        assert o.get("required", []) == c.get("required", [])
        if "enum" in o:
            assert c["enum"] == o["enum"]
        for nombre, sub in o.get("properties", {}).items():
            comparar(sub, c["properties"][nombre])
        if isinstance(o.get("items"), dict):
            comparar(o["items"], c["items"])

    comparar(original, convertido)


def test_opcionales_y_restricciones_quedan_en_forma_admitida():
    convertido = esquema_gemini(AperturaLLM)
    fecha = convertido["properties"]["cronologia"]["items"]["properties"]["fecha"]
    assert fecha["type"] == ["string", "null"] and "anyOf" not in fecha and "default" not in fecha
    assert fecha["description"] == "Fecha ISO AAAA-MM-DD si consta"
    rol = convertido["properties"]["metadatos"]["properties"]["impugnante_rol"]
    assert rol["type"] == "string" and "" in rol["enum"] and "default" not in rol
    banco = esquema_gemini(ConsideracionesLLM)["properties"]["bloques"]["items"]["properties"]["banco_id"]
    assert banco["type"] == ["string", "null"]


def test_el_conversor_inlinea_referencias_con_hermanos_y_quita_longitudes():
    from typing import Literal

    from pydantic import BaseModel, Field

    class Hijo(BaseModel):
        nombre: str = Field(min_length=3, max_length=9, pattern="^a")

    class Raiz(BaseModel):
        hijo: Hijo = Field(description="El hijo")
        opcional: Hijo | None = None
        lista: list[Hijo] = Field(min_length=1, max_length=4)
        tipo: Literal["x"] = "x"

    convertido = esquema_gemini(Raiz)
    hijo = convertido["properties"]["hijo"]
    assert hijo["description"] == "El hijo" and hijo["type"] == "object"
    assert hijo["properties"]["nombre"] == {"title": "Nombre", "type": "string"}
    opcional = convertido["properties"]["opcional"]
    assert opcional["type"] == ["object", "null"] and opcional["properties"]["nombre"]["type"] == "string"
    assert convertido["properties"]["lista"]["minItems"] == 1 and convertido["properties"]["lista"]["maxItems"] == 4
    assert convertido["properties"]["tipo"]["enum"] == ["x"]


def test_el_conversor_rechaza_esquemas_recursivos():
    from pydantic import BaseModel

    class Nodo(BaseModel):
        hijos: list["Nodo"] = []

    with pytest.raises(ValueError, match="recursivo"):
        esquema_gemini(Nodo)


def test_las_salidas_del_cliente_falso_cumplen_los_esquemas_convertidos():
    cfg = Config(llm=LLMConfig(proveedor="fake"))
    docs = llm.seccion("DOCUMENTOS", "### DOC d1 | escrito_tutela | 01 tutela.pdf\n" + "Texto del escrito de tutela con palabras suficientes " * 20)
    reparos = llm.seccion("REPAROS", json.dumps([{"id": "R1", "sintesis": "El fallo omitió valorar la prueba."}]))
    salidas = [
        FakeClient().estructurado("apertura", "s", docs, AperturaLLM, cfg)[0],
        FakeClient().estructurado("consideraciones", "s", reparos + llm.seccion("LIMITES", "Máximo: 3"), ConsideracionesLLM, cfg)[0],
        FakeClient().estructurado("caso_concreto", "s", reparos, CasoConcretoLLM, cfg)[0],
    ]
    for salida in salidas:
        assert _cumple(json.loads(salida.model_dump_json()), esquema_gemini(type(salida))), type(salida).__name__


@pytest.mark.parametrize("proveedor, sufijo", [("gemini", ""), ("anthropic", ""), ("fake", " (proveedor fake)")])
def test_el_evento_de_llamada_nombra_el_modelo_y_marca_solo_el_proveedor_falso(tmp_path, proveedor, sufijo):
    from tutela2 import eventos, graph

    class Cliente:
        def estructurado(self, nodo, system, user, schema, cfg):
            return CASO, {"modelo_efectivo": "m", "tokens_entrada": 1, "tokens_salida": 2, "stop_reason": "STOP"}

    modelo = {"gemini": "gemini-4-argon", "anthropic": "claude-sonnet-5-5", "fake": "claude-sonnet-5-5"}[proveedor]
    cfg = Config(llm=LLMConfig(proveedor=proveedor, modelo=modelo))
    buffer = eventos.Buffer()
    token = eventos.activar(buffer)
    try:
        _, llamada, _ = graph._llamar(Cliente(), cfg, {"caso_dir": str(tmp_path)}, "caso_concreto", "usuario", CasoConcretoLLM)
    finally:
        eventos.desactivar(token)
    lee = next(e for e in buffer.leer(0)[0] if e["tipo"] == "lee")
    assert lee["texto"].startswith(f"Llamada al modelo {modelo}{sufijo}, intento 1")
    assert lee["datos"]["proveedor"] == proveedor and llamada["proveedor"] == proveedor


def test_una_clave_con_salto_de_linea_no_queda_en_los_eventos_ni_en_los_fallos(tmp_path, monkeypatch, fabrica):
    from tutela2 import eventos, fallos, graph

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSECRETO\r\nX")
    buffer = eventos.Buffer()
    token = eventos.activar(buffer)
    try:
        with pytest.raises(ErrorLLM):
            graph._llamar(GeminiClient(), gemini(), {"caso_dir": str(tmp_path)}, "caso_concreto", "usuario", CasoConcretoLLM)
    finally:
        eventos.desactivar(token)
    assert "SECRETO" not in json.dumps(buffer.leer(0)[0], ensure_ascii=False)
    assert "SECRETO" not in (tmp_path / fallos.ARCHIVO).read_text(encoding="utf-8")
