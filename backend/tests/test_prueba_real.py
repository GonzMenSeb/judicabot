from __future__ import annotations

import importlib.util
import json
import os
import shutil
import types
from pathlib import Path

import anthropic
import httpx
import pytest
from docx import Document
from pydantic import BaseModel

from tutela2 import config as cfgmod
from tutela2 import llm
from tutela2.config import Config, JevConfig, LLMConfig
from tutela2.llm import AnthropicClient, ErrorLLM

RUTA = Path(__file__).resolve().parents[1] / "scripts" / "prueba_real.py"
NORMAS = Path(__file__).resolve().parents[1] / "tutela2" / "assets" / "normas_citables.json"
SONNET = "claude-sonnet-5-5"

necesita_sintetico = pytest.mark.skipif(
    not (shutil.which("soffice") and shutil.which("pdftotext")), reason="requiere soffice y pdftotext"
)


@pytest.fixture(autouse=True)
def entorno_aislado():
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def pr():
    spec = importlib.util.spec_from_file_location("prueba_real", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(autouse=True)
def gasto_aislado(pr, tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("cache_tutela2")
    monkeypatch.setattr(pr, "CARPETA_DEFECTO", base / "prueba_real")
    monkeypatch.setattr(pr, "RUTA_GASTO", base / "prueba_real_gasto.json")
    return base


class Salida(BaseModel):
    y: int


def respuesta(
    modelo=SONNET, stop="end_turn", entrada=1000, salida=500, texto='{"y": 1}', cache_e=0, cache_l=0, iteraciones=None, bloques=None, razonamiento=None
):
    uso = types.SimpleNamespace(
        input_tokens=entrada,
        output_tokens=salida,
        iterations=iteraciones,
        cache_creation_input_tokens=cache_e,
        cache_read_input_tokens=cache_l,
    )
    if razonamiento is not None:
        uso.output_tokens_details = types.SimpleNamespace(thinking_tokens=razonamiento)
    contenido = bloques if bloques is not None else [types.SimpleNamespace(type="text", text=texto)]
    return types.SimpleNamespace(content=contenido, stop_reason=stop, model=modelo, usage=uso)


def bloque_razonamiento(texto):
    return types.SimpleNamespace(type="thinking", thinking=texto, signature="firma")


def bloque_texto(texto):
    return types.SimpleNamespace(type="text", text=texto)


class Flujo:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        if self.final is not None:
            yield from (b.text for b in self.final.content if b.type == "text")

    def get_final_message(self):
        return self.final


class SDKFalso:
    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas: list[dict] = []
        self.messages = self
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._beta))

    def with_options(self, **opciones):
        return self

    def stream(self, **kwargs):
        self.llamadas.append(kwargs)
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return Flujo(siguiente)

    def _beta(self, **kwargs):
        self.llamadas.append({"beta": True, **kwargs})
        raise AssertionError("no debe alcanzarse el endpoint beta")


def escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def leer_gasto(pr) -> dict:
    return json.loads(pr.RUTA_GASTO.read_text(encoding="utf-8"))


def cfg_sonnet(**llm) -> Config:
    return Config(llm=LLMConfig(fallbacks_default=False, **llm))


def armar(pr, tmp_path, sdk, suave=5.0, duro=15.0):
    presupuesto = pr.Presupuesto(tmp_path, suave, duro)
    guardia = pr.Guardia(presupuesto)
    return AnthropicClient(client=pr.ClienteSDKVigilado(guardia, sdk)), guardia, presupuesto


def llamar(cliente, cfg=None):
    return cliente.estructurado("apertura", "sistema", "usuario", Salida, cfg or cfg_sonnet())


@pytest.mark.parametrize(
    "modelo",
    ["claude-opus-5-5", "claude-opus-4-8", "claude-fable-5-1", "claude-haiku-5-5", "claude-sonnet-5", "CLAUDE-SONNET-5-5", "", "gpt-5"],
)
def test_lista_blanca_rechaza_todo_salvo_sonnet_5_5(pr, modelo):
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_modelo_pedido(modelo)


def test_lista_blanca_acepta_sonnet_5_5(pr):
    pr.verificar_modelo_pedido(SONNET)


@pytest.mark.parametrize("modelo", ["claude-opus-5-5", "claude-sonnet-5-5-opus", "claude-fable-5-1", "otro"])
def test_modelo_de_la_respuesta_fuera_de_la_lista_se_rechaza(pr, modelo):
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_modelo_respuesta(modelo)


def test_modelo_de_la_respuesta_admite_sufijo_de_fecha(pr):
    pr.verificar_modelo_respuesta(f"{SONNET}-20261001")


def test_config_valida_pasa(pr):
    pr.verificar_config(cfg_sonnet())


@pytest.mark.parametrize(
    "cfg",
    [
        Config(),
        cfg_sonnet(modelo="claude-opus-5-5"),
        cfg_sonnet(modelo_por_nodo={"consideraciones": "claude-opus-5-5"}),
        cfg_sonnet(modelo_por_nodo={"caso_concreto": "claude-fable-5-1"}),
        cfg_sonnet(proveedor="fake"),
        Config(llm=LLMConfig(fallbacks_default=False), jev=JevConfig(modo="relleno")),
        Config(llm=LLMConfig(fallbacks_default=False), verificar_relatoria=False),
    ],
    ids=["fallbacks", "opus", "opus-por-nodo", "fable-por-nodo", "fake", "jev", "sin-relatoria"],
)
def test_config_insegura_se_rechaza(pr, cfg):
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_config(cfg)


def test_entorno_fuerza_jev_apagado_y_modelo_y_quita_llaves_ajenas(pr, monkeypatch, tmp_path):
    for variable, valor in {
        "TUTELA2_JEV_MODO": "relleno",
        "TUTELA2_MODELO": "claude-opus-5-5",
        "TUTELA2_PROVEEDOR": "fake",
        "JEV_API_KEY": "x",
        "ANTHROPIC_AUTH_TOKEN": "y",
    }.items():
        monkeypatch.setenv(variable, valor)
    cfgmod.guardar(tmp_path, Config(jev=JevConfig(modo="relleno")))
    pr.fijar_entorno()
    cfg = cfgmod.cargar(tmp_path)
    assert cfg.jev.modo == "apagado"
    assert cfg.llm.modelo == SONNET
    assert cfg.llm.proveedor == "anthropic"
    assert "JEV_API_KEY" not in os.environ and "TUTELA2_PROVEEDOR" not in os.environ
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ


def test_modelo_opus_se_rechaza_antes_de_llamar_al_sdk(pr, tmp_path):
    sdk = SDKFalso([respuesta()])
    cliente, guardia, _ = armar(pr, tmp_path, sdk)
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente, cfg_sonnet(modelo="claude-opus-5-5"))
    assert sdk.llamadas == []
    assert guardia.aborto and guardia.tipo_aborto == "seguridad"


def test_los_fallbacks_del_servidor_no_alcanzan_el_endpoint_beta(pr, tmp_path):
    sdk = SDKFalso([respuesta()])
    cliente, guardia, _ = armar(pr, tmp_path, sdk)
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente, Config())
    assert sdk.llamadas == []
    assert guardia.aborto


def test_una_vez_abortado_se_bloquean_las_llamadas_siguientes(pr, tmp_path):
    sdk = SDKFalso([respuesta(), respuesta()])
    cliente, guardia, _ = armar(pr, tmp_path, sdk)
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente, cfg_sonnet(modelo="claude-opus-5-5"))
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente)
    assert sdk.llamadas == []


def test_llamada_normal_cuenta_tokens_y_costo(pr, tmp_path):
    sdk = SDKFalso([respuesta(entrada=1_000_000, salida=100_000)])
    cliente, guardia, presupuesto = armar(pr, tmp_path, sdk)
    salida, meta = llamar(cliente)
    assert salida.y == 1
    assert presupuesto.datos["tokens"]["entrada"] == 1_000_000
    assert presupuesto.datos["tokens"]["salida"] == 100_000
    assert presupuesto.acumulado == pytest.approx(2.0 + 1.0)
    assert presupuesto.datos["llamadas"] == 1
    assert guardia.aborto is None


def test_tokens_de_respuesta_truncada_se_cuentan_aunque_llm_py_la_descarte(pr, tmp_path):
    sdk = SDKFalso([respuesta(stop="max_tokens", entrada=2000, salida=64000)])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.acumulado == pytest.approx((2000 * 2 + 64000 * 10) / 1e6)
    assert presupuesto.datos["tokens"]["salida"] == 64000


def test_tokens_de_respuesta_que_no_cumple_el_esquema_se_cuentan(pr, tmp_path):
    sdk = SDKFalso([respuesta(texto="{}", entrada=3000, salida=700)])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.datos["tokens"] == {"entrada": 3000, "salida": 700, "cache_escritura": 0, "cache_lectura": 0}


def test_tokens_de_rechazo_se_cuentan(pr, tmp_path):
    sdk = SDKFalso([respuesta(stop="refusal", texto="", entrada=500, salida=10)])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.datos["tokens"]["entrada"] == 500


def test_cache_se_cobra_con_sus_tarifas_y_las_iteraciones_se_suman(pr, tmp_path):
    iteraciones = [
        types.SimpleNamespace(input_tokens=400, output_tokens=100),
        types.SimpleNamespace(input_tokens=600, output_tokens=200),
    ]
    sdk = SDKFalso([respuesta(entrada=1, salida=1, cache_e=1_000_000, cache_l=1_000_000, iteraciones=iteraciones)])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    llamar(cliente)
    assert presupuesto.datos["tokens"]["entrada"] == 1000
    assert presupuesto.datos["tokens"]["salida"] == 300
    esperado = (1000 * 2 + 300 * 10) / 1e6 + 4.0 + 0.20
    assert presupuesto.acumulado == pytest.approx(esperado)


def test_respuesta_de_un_modelo_opus_se_cobra_y_aborta(pr, tmp_path):
    sdk = SDKFalso([respuesta(modelo="claude-opus-5-5", entrada=1000, salida=1000), respuesta()])
    cliente, guardia, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente)
    assert presupuesto.acumulado == pytest.approx(pr.costo_usd(SONNET, 1000, 1000))
    assert guardia.tipo_aborto == "seguridad"
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente)
    assert len(sdk.llamadas) == 1


def test_aborto_duro_ocurre_antes_de_llamar_al_sdk(pr, tmp_path):
    sdk = SDKFalso([respuesta()])
    cliente, guardia, presupuesto = armar(pr, tmp_path, sdk, duro=15.0)
    presupuesto.gasto["acumulado_usd"] = 14.9
    presupuesto.guardar()
    with pytest.raises(pr.AbortoPresupuesto):
        llamar(cliente)
    assert sdk.llamadas == []
    assert guardia.tipo_aborto == "presupuesto"


def test_el_peor_caso_de_una_llamada_cuenta_para_el_aborto(pr, tmp_path):
    sdk = SDKFalso([respuesta()])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk, duro=1.0)
    presupuesto.gasto["acumulado_usd"] = 0.5
    presupuesto.guardar()
    with pytest.raises(pr.AbortoPresupuesto):
        llamar(cliente, cfg_sonnet(max_tokens=64000))
    assert sdk.llamadas == []


def test_el_contador_persiste_entre_instancias(pr, tmp_path):
    sdk = SDKFalso([respuesta(entrada=1_000_000, salida=0)])
    cliente, _, _ = armar(pr, tmp_path, sdk)
    llamar(cliente)
    otra = pr.Presupuesto(tmp_path, 5.0, 15.0)
    assert otra.acumulado == pytest.approx(2.0)
    assert otra.datos["llamadas"] == 1


def test_llamada_interrumpida_se_recupera_como_peor_caso(pr, tmp_path):
    presupuesto = pr.Presupuesto(tmp_path, 5.0, 15.0)
    presupuesto.reservar(0.7)
    reabierto = pr.Presupuesto(tmp_path, 5.0, 15.0)
    assert reabierto.acumulado == pytest.approx(0.7)
    assert reabierto.gasto["en_vuelo"] is None


def test_error_de_red_libera_la_reserva_sin_cobrar(pr, tmp_path):
    sdk = SDKFalso([anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))])
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.acumulado == 0
    assert presupuesto.gasto["en_vuelo"] is None


class FlujoRoto(Flujo):
    def get_final_message(self):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))


def test_error_durante_el_flujo_cobra_el_peor_caso_de_la_reserva(pr, tmp_path):
    sdk = SDKFalso([FlujoRoto(None)])
    sdk.stream = lambda **kw: sdk.llamadas.append(kw) or sdk.guion.pop(0)
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.acumulado > 0
    assert presupuesto.acumulado == pytest.approx(pr.peor_caso_usd(sdk.llamadas[0]), rel=1e-5)
    assert presupuesto.gasto["en_vuelo"] is None


class FlujoLazo(Flujo):
    @property
    def text_stream(self):
        yield '{"y": "'
        for _ in range(3000):
            yield "Fin.  "


def test_lazo_degenerado_cobra_el_peor_caso_del_intento_abortado_y_el_reintento_cabe_en_el_tope(pr, tmp_path):
    sdk = SDKFalso([FlujoLazo(None), Flujo(respuesta())])
    sdk.stream = lambda **kw: sdk.llamadas.append(kw) or sdk.guion.pop(0)
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    salida, _ = llamar(cliente)
    peor = pr.peor_caso_usd(sdk.llamadas[0])
    assert salida == Salida(y=1) and len(sdk.llamadas) == 2
    assert presupuesto.acumulado == pytest.approx(peor + (1000 * 2 + 500 * 10) / 1e6, rel=1e-5)
    assert presupuesto.gasto["en_vuelo"] is None


def test_dos_lazos_degenerados_cobran_el_peor_caso_de_cada_intento(pr, tmp_path):
    sdk = SDKFalso([FlujoLazo(None), FlujoLazo(None)])
    sdk.stream = lambda **kw: sdk.llamadas.append(kw) or sdk.guion.pop(0)
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM, match="dos intentos consecutivos"):
        llamar(cliente)
    assert len(sdk.llamadas) == 2
    assert presupuesto.acumulado == pytest.approx(2 * pr.peor_caso_usd(sdk.llamadas[0]), rel=1e-5)
    assert presupuesto.gasto["en_vuelo"] is None


class ManagerQueFallaAlAbrir:
    def __enter__(self):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    def __exit__(self, *a):
        return False


def test_error_al_abrir_el_flujo_cobra_el_peor_caso_de_la_reserva(pr, tmp_path):
    sdk = SDKFalso([ManagerQueFallaAlAbrir()])
    sdk.stream = lambda **kw: sdk.llamadas.append(kw) or sdk.guion.pop(0)
    cliente, _, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(ErrorLLM):
        llamar(cliente)
    assert presupuesto.acumulado == pytest.approx(pr.peor_caso_usd(sdk.llamadas[0]), rel=1e-5)
    assert presupuesto.gasto["en_vuelo"] is None
    assert pr.Presupuesto(tmp_path, 5.0, 15.0).acumulado == pytest.approx(presupuesto.acumulado)


def test_salida_limpia_sin_consumir_la_respuesta_libera_la_reserva(pr, tmp_path):
    sdk = SDKFalso([Flujo(None)])
    _, guardia, presupuesto = armar(pr, tmp_path, sdk)
    vigilado = pr.ClienteSDKVigilado(guardia, sdk)
    with vigilado.messages.stream(model=SONNET, max_tokens=100, system="s", messages=[{"role": "user", "content": "u"}]):
        assert presupuesto.gasto["en_vuelo"] is not None
    assert presupuesto.acumulado == 0
    assert presupuesto.gasto["en_vuelo"] is None


def test_parada_suave_se_marca_sin_abortar(pr, tmp_path):
    sdk = SDKFalso([respuesta(entrada=3_000_000, salida=0)])
    cliente, guardia, presupuesto = armar(pr, tmp_path, sdk, suave=5.0)
    assert not presupuesto.parada_suave_alcanzada()
    llamar(cliente)
    assert presupuesto.acumulado == pytest.approx(6.0)
    assert presupuesto.parada_suave_alcanzada()
    assert guardia.aborto is None


@pytest.mark.parametrize("suave,duro", [(5, 16), (5, 15.01), (6, 5), (0, 5), (-1, 5)])
def test_topes_invalidos_se_rechazan(pr, suave, duro):
    with pytest.raises(pr.ErrorSeguridad):
        pr.validar_topes(suave, duro)


def test_topes_por_defecto_son_los_del_plan(pr):
    assert pr.validar_topes(5, 15) == (5.0, 15.0)


def test_el_costo_usa_la_tabla_de_precios(pr):
    assert pr.costo_usd(SONNET, 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert pr.costo_usd(SONNET, 0, 0, cache_lectura=1_000_000) == pytest.approx(0.20)
    assert pr.costo_usd(SONNET, 0, 0, cache_escritura=1_000_000) == pytest.approx(4.0)


def test_carpeta_bajo_casos_o_referencia_se_rechaza(pr, tmp_path):
    for nombre in ("casos", "referencia"):
        with pytest.raises(pr.ErrorSeguridad):
            pr.verificar_ruta(tmp_path / nombre / "p1")


def test_carpeta_dentro_del_repositorio_se_rechaza(pr):
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_ruta(pr.RAIZ_REPO / "backend" / "caso_prueba")
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_ruta(pr.RAIZ_REPO / "casos" / "p1")


def test_carpeta_con_contenido_y_sin_marca_se_rechaza(pr, tmp_path):
    (tmp_path / "caso.json").write_text("{}", encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_carpeta_propia(tmp_path)


def test_carpeta_con_marca_de_otro_radicado_se_rechaza(pr, tmp_path):
    (tmp_path / pr.MARCA).write_text(json.dumps({"radicado": "05001400000000000000001"}), encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_carpeta_propia(tmp_path)


def test_carpeta_vacia_o_inexistente_se_acepta(pr, tmp_path):
    pr.verificar_carpeta_propia(tmp_path / "nueva")
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    pr.verificar_carpeta_propia(vacia)


@pytest.fixture(scope="module")
def sintetico(tmp_path_factory, pr):
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        pytest.skip("requiere soffice y pdftotext")
    carpeta = tmp_path_factory.mktemp("prueba_real_sintetico")
    cs = pr.caso_sintetico()
    cs.generar(carpeta)
    cs.preparar(carpeta, "fake")
    from tutela2 import api

    assert api.nuevo(carpeta)["estado"] == "revision"
    return carpeta


@necesita_sintetico
def test_el_caso_sintetico_ingerido_pasa_la_comprobacion_de_contenido(pr, sintetico):
    pr.verificar_contenido(sintetico)


def _mutar_ingesta(carpeta: Path, destino: Path, mutar) -> Path:
    from tutela2.models import Ingesta

    shutil.copytree(carpeta, destino)
    ruta = destino / "caso.json"
    ing = Ingesta.model_validate_json(ruta.read_text(encoding="utf-8"))
    mutar(ing)
    ruta.write_text(ing.model_dump_json(), encoding="utf-8")
    return destino


@necesita_sintetico
def test_radicado_distinto_se_rechaza_por_contenido(pr, sintetico, tmp_path):
    def mutar(ing):
        ing.metadatos.cui_1a = "05001400000000000000001"

    copia = _mutar_ingesta(sintetico, tmp_path / "otro", mutar)
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_contenido(copia)


@necesita_sintetico
def test_documentos_distintos_a_los_nueve_sinteticos_se_rechazan(pr, sintetico, tmp_path):
    def mutar(ing):
        ing.documentos[0].nombre = "expediente_real.pdf"

    copia = _mutar_ingesta(sintetico, tmp_path / "otros", mutar)
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_contenido(copia)


@necesita_sintetico
def test_documento_sin_el_nombre_ficticio_se_rechaza(pr, sintetico, tmp_path):
    def mutar(ing):
        for p in ing.documentos[4].paginas:
            p.texto = "texto de un expediente cualquiera"

    copia = _mutar_ingesta(sintetico, tmp_path / "ajeno", mutar)
    with pytest.raises(pr.ErrorSeguridad):
        pr.verificar_contenido(copia)


def cita(id="c1", estado="ok", texto=None, seccion="mayoria", **extra):
    texto = texto or (
        "La acción de tutela no puede utilizarse como mecanismo para sustituir los procesos ordinarios cuando "
        "el afectado dispone de otro medio de defensa judicial idóneo y eficaz para proteger su derecho"
    )
    return {"id": id, "sentencia_original": "T-001 de 2020", "texto_citado": texto, "estado": estado, "seccion": seccion, "motivos": [], **extra}


def consideraciones(texto="La Corte analizó el caso [[CITA:c1]]. Se concluye lo anterior."):
    return {"procedibilidad": "Procede la acción.", "bloques": [{"titulo": "t", "reparo_ids": [], "texto": texto}], "citas": []}


def estado_resumen(citas_, cons=None):
    return {"citas": citas_, "consideraciones": cons or consideraciones(), "alertas": {}, "errores": []}


def por_id(criterios):
    return {c["id"]: c for c in criterios}


def cfg_criterios():
    return Config(min_citas_ok=2, min_palabras_cita=25)


def test_criterios_consideraciones_todo_bien(pr):
    otra = cita("c2", texto="El juez constitucional debe verificar que la entidad accionada haya resuelto de fondo y no de forma evasiva la solicitud elevada por la accionante dentro del plazo previsto")
    res = pr.criterios_consideraciones(estado_resumen([cita("c1"), otra]), cfg_criterios())
    assert {c["estado"] for c in res} == {"pasa"}, res


def test_criterios_consideraciones_pocas_citas_ok(pr):
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2", estado="rechazada")]), cfg_criterios()))
    assert res["citas_ok"]["estado"] == "falla"
    assert "1" in res["citas_ok"]["detalle"]


def test_criterios_consideraciones_cita_corta_falla_longitud(pr):
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2", texto="inmutables, vinculantes y definitivas")]), cfg_criterios()))
    assert res["longitud"]["estado"] == "falla"
    assert "c2" in res["longitud"]["detalle"]


def test_criterios_consideraciones_texto_normativo_falla(pr):
    norma = next(n for n in json.loads(NORMAS.read_text(encoding="utf-8")) if n["articulo"] == "86")["texto"]
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2", texto=norma)]), cfg_criterios()))
    assert res["sin_normativas"]["estado"] == "falla"
    assert "c2" in res["sin_normativas"]["detalle"]


def test_criterios_consideraciones_solo_en_salvamento_falla_y_sin_dato_no_es_evaluable(pr):
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2", seccion="salvamento")]), cfg_criterios()))
    assert res["sin_salvamento"]["estado"] == "falla"
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2", seccion=None)]), cfg_criterios()))
    assert res["sin_salvamento"]["estado"] == "no_evaluable"


def test_criterios_consideraciones_formula_sin_marcador_falla(pr):
    cons = consideraciones("La jurisprudencia ha decantado que el amparo es subsidiario. Otra oración distinta [[CITA:c1]].")
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")], cons), cfg_criterios()))
    assert res["formula_sin_marcador"]["estado"] == "falla"
    cons = consideraciones("La jurisprudencia ha decantado que el amparo es subsidiario [[CITA:c1]].")
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")], cons), cfg_criterios()))
    assert res["formula_sin_marcador"]["estado"] == "pasa"


def test_criterios_consideraciones_informan_los_umbrales_usados(pr):
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")]), cfg_criterios()))
    assert "25" in res["longitud"]["detalle"]
    assert "2" in res["citas_ok"]["detalle"]


def hacer_fallo(carpeta: Path, parrafos: list[str]) -> None:
    ruta = carpeta / "salidas" / "02SegundaInstancia" / "C01Principal"
    ruta.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for p in parrafos:
        doc.add_paragraph(p)
    doc.save(ruta / "003FalloSegunda202600412.docx")


FRAGMENTO = (
    "La acción de tutela no puede utilizarse como mecanismo para sustituir los procesos ordinarios cuando "
    "el afectado dispone de otro medio de defensa judicial idóneo y eficaz para proteger su derecho"
)
CONCLUSION = "En consecuencia, se revocará la sentencia de primera instancia y se amparará el mínimo vital de la accionante."


def resumen_decision(plazo=48, unidad="horas_habiles"):
    return {
        "citas": [cita("c1", texto=FRAGMENTO)],
        "caso_concreto": {
            "problema_juridico": "¿Procede el amparo?",
            "parrafos": [{"reparo_ids": [], "texto": "El Despacho acoge el reparo [[CITA:c1]]."}],
            "conclusion": CONCLUSION,
        },
        "decision": {"ordenes": [{"plazo": {"n": plazo, "unidad": unidad}}]},
    }


FALLO_BIEN = [
    "V. CONSIDERACIONES",
    "Texto de las consideraciones.",
    "VI. CASO CONCRETO",
    "¿Procede el amparo?",
    f"En la sentencia T-001 de 2020, la Corte Constitucional (M.P. Fulano) sostuvo: «{FRAGMENTO}». El Despacho acoge el reparo.",
    CONCLUSION,
    "VII. RESUELVE",
    "PRIMERO: ORDENAR a la EPS que, en el término de cuarenta y ocho (48) horas hábiles, resuelva de fondo.",
]


def test_criterios_decision_todo_bien(pr, tmp_path):
    fallo = list(FALLO_BIEN)
    fallo[4] += " Se concede el término de cuarenta y ocho (48) horas hábiles."
    hacer_fallo(tmp_path, fallo)
    res = pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios())
    assert {c["estado"] for c in res} == {"pasa"}, res


def test_criterios_decision_marcador_sin_expandir_falla(pr, tmp_path):
    fallo = list(FALLO_BIEN)
    fallo[4] = "El Despacho acoge el reparo [[CITA:c1]]. Se concede el término de 48 horas."
    hacer_fallo(tmp_path, fallo)
    res = por_id(pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios()))
    assert res["sin_marcadores_crudos"]["estado"] == "falla"
    assert res["marcador_ok_expandido"]["estado"] == "falla"


def test_criterios_decision_fragmento_solo_en_consideraciones_no_cuenta(pr, tmp_path):
    fallo = list(FALLO_BIEN)
    fallo[1] = FRAGMENTO
    fallo[4] = "El Despacho acoge el reparo. Se concede el término de 48 horas."
    hacer_fallo(tmp_path, fallo)
    res = por_id(pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios()))
    assert res["marcador_ok_expandido"]["estado"] == "falla"


def test_criterios_decision_conclusion_repetida_falla(pr, tmp_path):
    fallo = list(FALLO_BIEN)
    fallo[4] += " Se concede el término de 48 horas. " + CONCLUSION
    hacer_fallo(tmp_path, fallo)
    res = por_id(pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios()))
    assert res["una_sola_conclusion"]["estado"] == "falla"


def test_criterios_decision_plazo_ausente_falla(pr, tmp_path):
    hacer_fallo(tmp_path, FALLO_BIEN)
    res = por_id(pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios()))
    assert res["plazo_reflejado"]["estado"] == "falla"


def test_criterios_decision_sin_fallo_falla(pr, tmp_path):
    res = pr.criterios_decision(tmp_path, resumen_decision(), cfg_criterios())
    assert [c["estado"] for c in res] == ["falla"]


def hacer_informe(carpeta: Path, parrafos: list[str]) -> None:
    ruta = carpeta / "salidas" / "trabajo"
    ruta.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for p in parrafos:
        doc.add_paragraph(p)
    doc.save(ruta / "informe_verificacion.docx")


def test_criterios_informe_detecta_el_verde_falso(pr, tmp_path):
    hacer_informe(tmp_path, ["No hay errores bloqueantes vigentes.", "Sin pendientes registrados."])
    resumen = {"alertas": {"consideraciones": ["BLOQUEA: faltan citas"]}, "errores": [], "decision": {"generar_formato": True}}
    res = por_id(pr.criterios_informe(tmp_path, resumen))
    assert res["errores_bloqueantes_veraz"]["estado"] == "falla"
    assert res["pendientes_listados"]["estado"] == "falla"


def test_criterios_informe_veraz_pasa(pr, tmp_path):
    hacer_informe(
        tmp_path,
        ["Errores bloqueantes vigentes", "BLOQUEA: faltan citas", "V. PENDIENTES Y VALORES POR DEFECTO", "Formato de calidad sin puntajes."],
    )
    resumen = {"alertas": {"consideraciones": ["BLOQUEA: faltan citas"]}, "errores": [], "decision": {"generar_formato": True}}
    res = pr.criterios_informe(tmp_path, resumen)
    assert {c["estado"] for c in res} == {"pasa"}, res


def test_criterios_informe_falta_sin_reportar_falla(pr, tmp_path):
    hacer_fallo(tmp_path, ["VI. CASO CONCRETO", "⟦FALTA: nombre del juez⟧"])
    hacer_informe(tmp_path, ["No hay errores bloqueantes vigentes.", "V. PENDIENTES Y VALORES POR DEFECTO", "Otro pendiente."])
    resumen = {"alertas": {}, "errores": [], "decision": {"generar_formato": True}}
    res = por_id(pr.criterios_informe(tmp_path, resumen))
    assert res["falta_reportado"]["estado"] == "falla"
    assert "nombre del juez" in res["falta_reportado"]["detalle"]


def test_reporte_markdown_incluye_motivos_costo_y_criterios(pr):
    reporte = {
        "comando": "rehacer",
        "veredicto": "falla",
        "costo": {"invocacion_usd": 0.1234, "acumulado_usd": 0.5, "parada_suave_usd": 5.0, "aborto_duro_usd": 15.0, "tokens": {"entrada": 10, "salida": 5, "cache_escritura": 0, "cache_lectura": 0}, "llamadas": 2},
        "criterios": {"consideraciones": [{"id": "citas_ok", "descripcion": "d", "estado": "falla", "detalle": "1 de 2"}]},
        "intentos_citas": [[{"id": "c1", "sentencia_original": "T-1 de 2020", "estado": "rechazada", "motivos": ["mínimo 25 palabras de ratio"], "n_palabras": 4, "seccion": "mayoria"}]],
        "pasos": [],
    }
    texto = pr.reporte_markdown(reporte)
    assert "mínimo 25 palabras de ratio" in texto
    assert "0.1234" in texto
    assert "citas_ok" in texto and "falla" in texto


def test_sin_clave_en_el_entorno_se_sale_antes_de_tocar_nada(pr, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: pytest.fail("no debe crearse el cliente"))
    codigo = pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso")])
    assert codigo == pr.SALIDA_USO
    assert not (tmp_path / "caso").exists()
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_carpeta_no_permitida_sale_sin_crear_cliente(pr, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: pytest.fail("no debe crearse el cliente"))
    codigo = pr.main(["hasta-decision", "--carpeta", str(pr.RAIZ_REPO / "casos" / "p1")])
    assert codigo == pr.SALIDA_USO
    assert "sk-prueba" not in capsys.readouterr().err


def test_tope_duro_mayor_a_15_sale_con_error_de_uso(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    codigo = pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso"), "--aborto-duro", "16"])
    assert codigo == pr.SALIDA_USO


class SDKViaFake:
    def __init__(self, cfg):
        self.cfg = cfg
        self.messages = self
        self.llamadas: list[dict] = []

    def with_options(self, **opciones):
        return self

    def stream(self, **kwargs):
        from tutela2.llm import FakeClient
        from tutela2.models import AperturaLLM, CasoConcretoLLM, ConsideracionesLLM

        self.llamadas.append(kwargs)
        titulo = kwargs["output_config"]["format"]["schema"]["title"]
        esquema = {"AperturaLLM": AperturaLLM, "ConsideracionesLLM": ConsideracionesLLM, "CasoConcretoLLM": CasoConcretoLLM}[titulo]
        salida, _ = FakeClient().estructurado(titulo, kwargs["system"], kwargs["messages"][0]["content"], esquema, self.cfg)
        return Flujo(respuesta(texto=salida.model_dump_json(), entrada=12_000, salida=3_000))


@necesita_sintetico
def test_flujo_completo_con_sdk_simulado_cuenta_y_reporta(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"

    def fabrica():
        return sdk

    assert pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=fabrica) in (pr.SALIDA_OK, pr.SALIDA_FALLA)
    datos = json.loads((carpeta / "presupuesto.json").read_text(encoding="utf-8"))
    assert datos["llamadas"] == 2
    assert datos["acumulado_usd"] == pytest.approx(2 * (12_000 * 2 + 3_000 * 10) / 1e6)
    assert (carpeta / "reporte_hasta-decision.json").is_file()
    assert (carpeta / "reporte_hasta-decision.md").is_file()
    assert (carpeta / pr.MARCA).is_file()

    assert pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=fabrica) == pr.SALIDA_USO
    assert len(sdk.llamadas) == 2

    assert pr.main(["rehacer", "--carpeta", str(carpeta)], fabrica_sdk=fabrica) in (pr.SALIDA_OK, pr.SALIDA_FALLA)
    datos = json.loads((carpeta / "presupuesto.json").read_text(encoding="utf-8"))
    assert datos["rehacer"] == 1 and datos["llamadas"] == 3

    assert pr.main(["decidir", "--carpeta", str(carpeta)], fabrica_sdk=fabrica) in (pr.SALIDA_OK, pr.SALIDA_FALLA)
    datos = json.loads((carpeta / "presupuesto.json").read_text(encoding="utf-8"))
    assert datos["llamadas"] == 4
    assert (carpeta / "salidas" / "trabajo" / "informe_verificacion.docx").is_file()


@necesita_sintetico
def test_parada_suave_termina_limpio_sin_llamar_a_la_api(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"
    carpeta.mkdir()
    escribir_json(pr.RUTA_GASTO, {"acumulado_usd": 6.0})
    codigo = pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    assert codigo == pr.SALIDA_PARADA_SUAVE
    assert sdk.llamadas == []
    reporte = json.loads((carpeta / "reporte_hasta-decision.json").read_text(encoding="utf-8"))
    assert reporte["parada"] == "suave"


@necesita_sintetico
def test_aborto_duro_se_reporta_y_no_vuelve_a_llamar(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"
    carpeta.mkdir()
    escribir_json(pr.RUTA_GASTO, {"acumulado_usd": 14.9})
    codigo = pr.main(["hasta-decision", "--carpeta", str(carpeta), "--parada-suave", "15"], fabrica_sdk=lambda: sdk)
    assert codigo == pr.SALIDA_ABORTO_DURO
    assert sdk.llamadas == []


@necesita_sintetico
def test_entrada_imprime_tamanos_por_nodo_sin_llamar_a_la_api(pr, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: pytest.fail("entrada no debe crear el cliente"))
    assert pr.main(["entrada"]) == pr.SALIDA_OK
    salida = capsys.readouterr().out
    for nodo in ("apertura", "consideraciones", "caso_concreto"):
        assert nodo in salida
    assert "system=" in salida and "user=" in salida


@necesita_sintetico
def test_rehacer_respeta_el_tope_de_tres_por_caso(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"
    pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    datos = json.loads((carpeta / "presupuesto.json").read_text(encoding="utf-8"))
    datos["rehacer"] = pr.MAX_REHACER
    (carpeta / "presupuesto.json").write_text(json.dumps(datos), encoding="utf-8")
    llamadas = len(sdk.llamadas)
    assert pr.main(["rehacer", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk) == pr.SALIDA_FALLA
    assert len(sdk.llamadas) == llamadas
    reporte = json.loads((carpeta / "reporte_rehacer.json").read_text(encoding="utf-8"))
    assert "máximo" in reporte["error"]


@necesita_sintetico
def test_extremo_a_extremo_corre_los_tres_pasos_y_evalua_los_tres_grupos(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"
    assert pr.main(["extremo-a-extremo", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk) == pr.SALIDA_FALLA
    reporte = json.loads((carpeta / "reporte_extremo-a-extremo.json").read_text(encoding="utf-8"))
    assert reporte["estado_final"] == "terminado"
    assert set(reporte["criterios"]) == {"consideraciones", "decision", "informe"}
    assert [p["paso"] for p in reporte["pasos"]] == ["iniciar", "decidir"]
    assert reporte["costo"]["llamadas"] == len(sdk.llamadas) == 3


def test_respuesta_sin_uso_de_tokens_cobra_el_peor_caso_y_aborta(pr, tmp_path):
    sin_uso = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text='{"y": 1}')], stop_reason="end_turn", model=SONNET, usage=None)
    sdk = SDKFalso([sin_uso, respuesta()])
    cliente, guardia, presupuesto = armar(pr, tmp_path, sdk)
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente)
    assert presupuesto.acumulado > 0 and presupuesto.gasto["en_vuelo"] is None
    with pytest.raises(pr.ErrorSeguridad):
        llamar(cliente)
    assert len(sdk.llamadas) == 1


def test_criterios_decision_conclusion_con_marcador_expandido_cuenta_una_vez(pr, tmp_path):
    resumen = resumen_decision()
    resumen["caso_concreto"]["conclusion"] = "En consecuencia, se revocará la sentencia de primera instancia [[CITA:c1]] y se amparará el mínimo vital."
    fallo = list(FALLO_BIEN)
    fallo[4] += " Se concede el término de 48 horas."
    fallo[5] = "En consecuencia, se revocará la sentencia de primera instancia, tal como lo dijo la Corte, y se amparará el mínimo vital."
    hacer_fallo(tmp_path, fallo)
    res = por_id(pr.criterios_decision(tmp_path, resumen, cfg_criterios()))
    assert res["una_sola_conclusion"]["estado"] == "pasa", res["una_sola_conclusion"]


@necesita_sintetico
def test_la_guardia_esta_instalada_tambien_durante_la_ingesta(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    vistos = []

    def nuevo_espia(carpeta):
        vistos.append(type(anthropic.Anthropic()))
        return {"estado": "error", "error": "espia", "ok": False}

    monkeypatch.setattr(pr.api, "nuevo", nuevo_espia)
    pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso")], fabrica_sdk=lambda: SDKFalso([]))
    assert vistos == [pr.ClienteSDKVigilado]


SECRETO = "FRASE_SECRETA_DEL_MODELO"


def razonamiento_largo(n=4000):
    return SECRETO + " " + " ".join(f"idea{i}" for i in range(n))


def sesion_en(pr, tmp_path):
    return pr.Sesion(tmp_path, "hasta-decision", 5.0, 15.0, None)


def llamar_con_diagnostico(pr, sesion, sdk):
    cfg = cfg_sonnet()
    with pr.entorno_vigilado(sesion.guardia, lambda: sdk):
        return llm.cliente_para(cfg).estructurado("apertura", "sistema", "usuario", Salida, cfg)


def test_repeticion_maxima_cuenta_la_subcadena_de_80_caracteres_mas_frecuente(pr):
    frase = "El amparo es subsidiario y procede cuando no existe otro medio de defensa judicial idoneo. "
    veces, subcadena = pr.repeticion_maxima(frase * 500)
    assert veces >= 490
    assert len(subcadena) == 80 and subcadena in frase * 2
    assert pr.repeticion_maxima(razonamiento_largo())[0] == 1
    assert pr.repeticion_maxima("corto") == (0, "")


def test_respuesta_truncada_con_razonamiento_largo_se_captura(pr, tmp_path):
    texto = razonamiento_largo()
    resp = respuesta(
        stop="max_tokens", entrada=2000, salida=64000, razonamiento=63000, bloques=[bloque_razonamiento(texto), bloque_texto('{"y": ')]
    )
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM):
        llamar_con_diagnostico(pr, sesion, SDKFalso([resp]))
    assert sesion.presupuesto.acumulado == pytest.approx((2000 * 2 + 64000 * 10) / 1e6)
    assert len(sesion.guardia.truncadas) == 1
    captura = sesion.guardia.truncadas[0]
    assert captura["stop_reason"] == "max_tokens"
    assert captura["esquema"] == "Salida"
    assert captura["usage"]["output_tokens"] == 64000
    assert captura["usage"]["thinking_tokens"] == 63000
    razon, salida = captura["bloques"]
    assert (razon["tipo"], salida["tipo"]) == ("thinking", "text")
    assert razon["caracteres"] == len(texto) and salida["caracteres"] == len('{"y": ')
    assert razon["inicio"] == texto[:1500] and razon["fin"] == texto[-1500:]
    assert len(razon["inicio"]) == len(razon["fin"]) == 1500
    assert razon["repeticion_80"] == 1
    assert salida["inicio"] == '{"y": ' and salida["fin"] == ""


def test_respuesta_truncada_con_texto_repetitivo_marca_la_repeticion(pr, tmp_path):
    lazo = '{"texto": "La Corte ha sostenido que el amparo es subsidiario y procede solo si no existe otro medio idoneo."},'
    texto = '{"parrafos": [' + lazo * 2000
    resp = respuesta(stop="max_tokens", salida=64000, bloques=[bloque_texto(texto)])
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM):
        llamar_con_diagnostico(pr, sesion, SDKFalso([resp]))
    (bloque,) = sesion.guardia.truncadas[0]["bloques"]
    assert bloque["tipo"] == "text" and bloque["caracteres"] == len(texto)
    assert bloque["repeticion_80"] >= 1900
    assert len(bloque["subcadena_repetida"]) == 80
    assert sesion.guardia.truncadas[0]["usage"]["thinking_tokens"] is None


def test_bloques_de_otro_tipo_se_describen_sin_texto(pr):
    resp = respuesta(
        stop="max_tokens",
        bloques=[types.SimpleNamespace(type="redacted_thinking", data="x" * 300), types.SimpleNamespace(type="tool_use", id="t1")],
    )
    redactado, otro = pr.describir_respuesta(resp)["bloques"]
    assert redactado["tipo"] == "redacted_thinking" and redactado["caracteres"] == 300
    assert redactado["inicio"] == redactado["fin"] == ""
    assert otro["tipo"] == "tool_use" and otro["inicio"] == ""


def test_respuesta_normal_no_genera_la_clave(pr, tmp_path):
    sesion = sesion_en(pr, tmp_path)
    salida, _ = llamar_con_diagnostico(pr, sesion, SDKFalso([respuesta(razonamiento=100)]))
    assert salida.y == 1
    assert sesion.guardia.truncadas == []
    assert "respuesta_truncada" not in sesion.reporte(("consideraciones",))
    assert sesion.presupuesto.datos["tokens"]["salida"] == 500


@pytest.mark.parametrize("texto", ['{"y": ', '{"y": "no es un entero"}', ""], ids=["json-cortado", "esquema", "vacio"])
def test_error_de_parseo_captura_la_respuesta_con_el_motivo(pr, tmp_path, texto):
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM) as error:
        llamar_con_diagnostico(pr, sesion, SDKFalso([respuesta(texto=texto, salida=700)]))
    (captura,) = sesion.guardia.truncadas
    assert captura["stop_reason"] == "end_turn"
    assert captura["motivo"] == str(error.value)
    assert captura["bloques"][0]["caracteres"] == len(texto)
    assert sesion.presupuesto.datos["tokens"]["salida"] == 700


def test_un_error_sin_respuesta_no_captura_la_respuesta_anterior(pr, tmp_path):
    sesion = sesion_en(pr, tmp_path)
    red = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    llamar_con_diagnostico(pr, sesion, SDKFalso([respuesta()]))
    with pytest.raises(ErrorLLM):
        llamar_con_diagnostico(pr, sesion, SDKFalso([red]))
    assert sesion.guardia.truncadas == []


def test_una_respuesta_truncada_no_se_captura_dos_veces(pr, tmp_path):
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM):
        llamar_con_diagnostico(pr, sesion, SDKFalso([respuesta(stop="max_tokens", salida=64000)]))
    assert len(sesion.guardia.truncadas) == 1


def test_una_falla_de_la_captura_no_rompe_el_conteo_ni_el_flujo(pr, monkeypatch, tmp_path):
    def roto(resp):
        raise RuntimeError("captura rota")

    monkeypatch.setattr(pr, "describir_respuesta", roto)
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM) as error:
        llamar_con_diagnostico(pr, sesion, SDKFalso([respuesta(stop="max_tokens", entrada=2000, salida=64000)]))
    assert "límite de tokens" in str(error.value)
    assert sesion.presupuesto.acumulado == pytest.approx((2000 * 2 + 64000 * 10) / 1e6)
    assert sesion.guardia.aborto is None
    assert "captura rota" in sesion.guardia.truncadas[0]["error_captura"]


def test_la_captura_no_cambia_el_peor_caso_ni_las_reglas_de_seguridad(pr, tmp_path):
    sesion = sesion_en(pr, tmp_path)
    sdk = SDKFalso([respuesta()])
    with pytest.raises(pr.ErrorSeguridad):
        with pr.entorno_vigilado(sesion.guardia, lambda: sdk):
            llm.cliente_para(cfg_sonnet(modelo="claude-opus-5-5"))
    assert sdk.llamadas == [] and sesion.guardia.truncadas == []


def truncada_con_sesion(pr, tmp_path):
    resp = respuesta(
        stop="max_tokens",
        entrada=2000,
        salida=64000,
        razonamiento=63000,
        bloques=[bloque_razonamiento(razonamiento_largo()), bloque_texto('{"y": ')],
    )
    sesion = sesion_en(pr, tmp_path)
    with pytest.raises(ErrorLLM):
        llamar_con_diagnostico(pr, sesion, SDKFalso([resp]))
    return sesion


def test_el_reporte_json_incluye_la_clave_respuesta_truncada(pr, tmp_path):
    sesion = truncada_con_sesion(pr, tmp_path)
    reporte = sesion.reporte(("consideraciones",))
    assert reporte["respuesta_truncada"] == sesion.guardia.truncadas
    json.dumps(reporte, ensure_ascii=False)


def test_el_markdown_incluye_el_diagnostico_y_la_salida_estandar_solo_tamanos(pr, tmp_path, capsys):
    sesion = truncada_con_sesion(pr, tmp_path)
    reporte = sesion.reporte(("consideraciones",))
    markdown = pr.reporte_markdown(reporte)
    assert "Respuesta truncada" in markdown and SECRETO in markdown and "thinking" in markdown
    pr._imprimir_resumen(reporte)
    salida = capsys.readouterr().out
    lineas = [l for l in salida.splitlines() if "truncada" in l.lower()]
    assert len(lineas) == 1
    assert "thinking" in lineas[0] and "text" in lineas[0] and "64000" in lineas[0] and "63000" in lineas[0]
    assert SECRETO not in salida


class SDKTruncaCasoConcreto(SDKViaFake):
    truncar = True

    def stream(self, **kwargs):
        titulo = kwargs["output_config"]["format"]["schema"]["title"]
        if titulo == "CasoConcretoLLM" and self.truncar:
            self.llamadas.append(kwargs)
            return Flujo(
                respuesta(
                    stop="max_tokens",
                    entrada=12_000,
                    salida=64_000,
                    razonamiento=60_000,
                    bloques=[bloque_razonamiento(razonamiento_largo()), bloque_texto('{"problema_juridico": "')],
                )
            )
        return super().stream(**kwargs)


@necesita_sintetico
def test_truncada_en_decidir_se_reporta_y_continuar_no_repaga_el_expediente(pr, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKTruncaCasoConcreto(Config())
    carpeta = tmp_path / "caso"
    titulos = lambda: [k["output_config"]["format"]["schema"]["title"] for k in sdk.llamadas]

    pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    assert "respuesta_truncada" not in json.loads((carpeta / "reporte_hasta-decision.json").read_text(encoding="utf-8"))

    capsys.readouterr()
    pr.main(["decidir", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    reporte = json.loads((carpeta / "reporte_decidir.json").read_text(encoding="utf-8"))
    (captura,) = reporte["respuesta_truncada"]
    assert captura["esquema"] == "CasoConcretoLLM" and captura["usage"]["thinking_tokens"] == 60_000
    assert SECRETO in (carpeta / "reporte_decidir.md").read_text(encoding="utf-8")
    salida = capsys.readouterr().out
    assert SECRETO not in salida and "truncada" in salida.lower()
    assert titulos() == ["AperturaLLM", "ConsideracionesLLM", "CasoConcretoLLM"]

    sdk.truncar = False
    pr.main(["continuar", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    assert titulos() == ["AperturaLLM", "ConsideracionesLLM", "CasoConcretoLLM", "CasoConcretoLLM"]
    reporte = json.loads((carpeta / "reporte_continuar.json").read_text(encoding="utf-8"))
    assert reporte["estado_final"] == "terminado"
    assert "respuesta_truncada" not in reporte


def sembrar(ruta: Path, acumulado, en_vuelo=None) -> None:
    escribir_json(ruta, {"version": 1, "acumulado_usd": acumulado, "en_vuelo": en_vuelo})


def test_el_gasto_es_global_y_comun_a_todas_las_carpetas(pr, tmp_path):
    cliente, _, _ = armar(pr, tmp_path / "a", SDKFalso([respuesta(entrada=1_000_000, salida=0)]))
    llamar(cliente)
    assert pr.RUTA_GASTO.is_file()
    assert pr.Presupuesto(tmp_path / "b", 5.0, 15.0).acumulado == pytest.approx(2.0)


def test_borrar_el_presupuesto_de_la_carpeta_no_reinicia_el_gasto(pr, tmp_path):
    cliente, _, _ = armar(pr, tmp_path, SDKFalso([respuesta(entrada=1_000_000, salida=0)]))
    llamar(cliente)
    (tmp_path / pr.ARCHIVO_PRESUPUESTO).unlink()
    assert pr.Presupuesto(tmp_path, 5.0, 15.0).acumulado == pytest.approx(2.0)


def test_el_tope_duro_cuenta_el_gasto_hecho_en_otras_carpetas(pr, tmp_path):
    escribir_json(pr.RUTA_GASTO, {"acumulado_usd": 14.9})
    sdk = SDKFalso([respuesta()])
    cliente, guardia, _ = armar(pr, tmp_path / "nueva", sdk)
    with pytest.raises(pr.AbortoPresupuesto):
        llamar(cliente)
    assert sdk.llamadas == [] and guardia.tipo_aborto == "presupuesto"


def test_el_gasto_global_nuevo_toma_el_maximo_de_los_presupuestos_previos(pr, tmp_path):
    sembrar(pr.CARPETA_DEFECTO / pr.ARCHIVO_PRESUPUESTO, 1.5)
    sembrar(pr.CARPETA_DEFECTO.parent / "hermana" / pr.ARCHIVO_PRESUPUESTO, 3.0, {"estimado_usd": 0.5, "desde": "x"})
    sembrar(tmp_path / pr.ARCHIVO_PRESUPUESTO, 2.0)
    assert pr.Presupuesto(tmp_path, 5.0, 15.0).acumulado == pytest.approx(3.5)
    assert leer_gasto(pr)["acumulado_usd"] == pytest.approx(3.5)
    sembrar(pr.CARPETA_DEFECTO / pr.ARCHIVO_PRESUPUESTO, 9.0)
    assert pr.Presupuesto(tmp_path, 5.0, 15.0).acumulado == pytest.approx(3.5)


def test_sin_presupuestos_previos_el_gasto_global_empieza_en_cero(pr, tmp_path):
    assert pr.Presupuesto(tmp_path, 5.0, 15.0).acumulado == 0


def test_gasto_global_ilegible_se_rechaza_y_no_se_vuelve_a_migrar(pr, tmp_path):
    sembrar(tmp_path / pr.ARCHIVO_PRESUPUESTO, 4.0)
    pr.RUTA_GASTO.parent.mkdir(parents=True, exist_ok=True)
    pr.RUTA_GASTO.write_text("{no es json", encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.Presupuesto(tmp_path, 5.0, 15.0)
    assert pr.RUTA_GASTO.read_text(encoding="utf-8") == "{no es json"


VALORES_INVALIDOS = ["NaN", "Infinity", "-Infinity", "-1", '"abc"', "null"]


@pytest.mark.parametrize("valor", VALORES_INVALIDOS)
def test_acumulado_invalido_en_el_gasto_global_se_rechaza(pr, tmp_path, valor):
    pr.RUTA_GASTO.parent.mkdir(parents=True, exist_ok=True)
    pr.RUTA_GASTO.write_text(f'{{"acumulado_usd": {valor}}}', encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.Presupuesto(tmp_path, 5.0, 15.0)


@pytest.mark.parametrize("valor", VALORES_INVALIDOS)
def test_acumulado_invalido_en_la_carpeta_se_rechaza(pr, tmp_path, valor):
    escribir_json(pr.RUTA_GASTO, {"acumulado_usd": 0.0})
    (tmp_path / pr.ARCHIVO_PRESUPUESTO).write_text(f'{{"acumulado_usd": {valor}}}', encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.Presupuesto(tmp_path, 5.0, 15.0)


@pytest.mark.parametrize("valor", VALORES_INVALIDOS)
def test_acumulado_invalido_en_un_presupuesto_previo_impide_migrar(pr, tmp_path, valor):
    destino = pr.CARPETA_DEFECTO / pr.ARCHIVO_PRESUPUESTO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(f'{{"acumulado_usd": {valor}}}', encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.Presupuesto(tmp_path, 5.0, 15.0)
    assert not pr.RUTA_GASTO.exists()


@pytest.mark.parametrize("estimado", ["-5", "NaN", "Infinity"])
def test_estimado_en_vuelo_invalido_se_rechaza(pr, tmp_path, estimado):
    pr.RUTA_GASTO.parent.mkdir(parents=True, exist_ok=True)
    pr.RUTA_GASTO.write_text(f'{{"acumulado_usd": 1.0, "en_vuelo": {{"estimado_usd": {estimado}}}}}', encoding="utf-8")
    with pytest.raises(pr.ErrorSeguridad):
        pr.Presupuesto(tmp_path, 5.0, 15.0)


@necesita_sintetico
def test_el_acumulado_global_sobrevive_a_reiniciar_y_a_una_carpeta_nueva(pr, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(pr, "EXIGIR_RELATORIA", False)
    sdk = SDKViaFake(Config())
    carpeta = tmp_path / "caso"
    pr.main(["hasta-decision", "--carpeta", str(carpeta)], fabrica_sdk=lambda: sdk)
    primero = leer_gasto(pr)["acumulado_usd"]
    assert primero > 0
    pr.main(["hasta-decision", "--carpeta", str(carpeta), "--reiniciar"], fabrica_sdk=lambda: sdk)
    assert leer_gasto(pr)["acumulado_usd"] == pytest.approx(2 * primero)
    pr.main(["hasta-decision", "--carpeta", str(tmp_path / "otra")], fabrica_sdk=lambda: sdk)
    assert leer_gasto(pr)["acumulado_usd"] == pytest.approx(3 * primero)


def test_una_segunda_instancia_se_rechaza_sin_tocar_nada(pr, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: pytest.fail("no debe crearse el cliente"))
    with pr.bloqueo_gasto():
        codigo = pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso")])
    assert codigo == pr.SALIDA_USO
    assert not (tmp_path / "caso").exists()
    assert "instancia" in capsys.readouterr().err
    with pr.bloqueo_gasto():
        pass


def test_la_ayuda_advierte_una_sola_instancia_y_la_tarifa_de_cache(pr):
    ayuda = " ".join(pr._parser().format_help().split())
    assert "más de una instancia a la vez" in ayuda
    assert "0.20" in ayuda and "caché" in ayuda


@pytest.mark.parametrize(
    "texto",
    [
        "La jurisprudencia constitucional, de manera reiterada, ha sostenido que el amparo es subsidiario.",
        "La jurisprudencia, de forma pacífica, ha decantado que el amparo es subsidiario.",
        "La jurisprudencia ha decantado que el amparo es subsidiario.",
    ],
)
def test_formula_sin_marcador_usa_el_criterio_del_lint_de_la_app(pr, texto):
    cons = consideraciones(f"{texto} Otra oración distinta [[CITA:c1]].")
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")], cons), cfg_criterios()))
    assert res["formula_sin_marcador"]["estado"] == "falla"
    cons = consideraciones(f"{texto[:-1]} [[CITA:c1]].")
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")], cons), cfg_criterios()))
    assert res["formula_sin_marcador"]["estado"] == "pasa"


def test_formula_sin_marcador_tambien_revisa_la_procedibilidad(pr):
    cons = consideraciones()
    cons["procedibilidad"] = "La jurisprudencia, de manera reiterada, ha sostenido que procede la acción."
    res = por_id(pr.criterios_consideraciones(estado_resumen([cita("c1"), cita("c2")], cons), cfg_criterios()))
    assert res["formula_sin_marcador"]["estado"] == "falla"


CLAVES_NO_PERMITIDAS = [
    "sk-ant-SECRETO\nX-Evil: 1",
    "sk-ant-ñSECRETO",
    "sk SECRETO",
    "sk-SECRETO/x",
    "sk-SECRETO\n",
    "sk-SECRETO\r",
]


@pytest.mark.parametrize("clave", CLAVES_NO_PERMITIDAS, ids=range(len(CLAVES_NO_PERMITIDAS)))
def test_clave_con_caracteres_no_permitidos_se_rechaza_sin_imprimirla(pr, monkeypatch, tmp_path, capsys, clave):
    monkeypatch.setenv("ANTHROPIC_API_KEY", clave)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: pytest.fail("no debe crearse el cliente"))
    codigo = pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso")])
    assert codigo == pr.SALIDA_USO
    salida = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in salida.err
    assert "SECRETO" not in salida.out + salida.err
    assert not (tmp_path / "caso").exists()


def test_la_fabrica_del_cliente_tampoco_acepta_una_clave_invalida(pr, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-SECRETO\nx")
    guardia = pr.Guardia(pr.Presupuesto(pr.CARPETA_DEFECTO, 5.0, 15.0))
    with pr.entorno_vigilado(guardia, None):
        with pytest.raises(pr.ErrorSeguridad) as error:
            anthropic.Anthropic()
    assert "SECRETO" not in str(error.value)


def test_un_error_inesperado_se_informa_sin_la_clave(pr, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-SECRETO-123")

    def explota(*a, **k):
        raise RuntimeError("Authorization: Bearer sk-SECRETO-123 rechazada")

    monkeypatch.setattr(pr, "Sesion", explota)
    codigo = pr.main(["hasta-decision", "--carpeta", str(tmp_path / "caso")])
    assert codigo == pr.SALIDA_FALLA
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "SECRETO" not in err and "Bearer sk-" not in err


def test_los_logs_del_sdk_no_pueden_quedar_en_debug(pr, monkeypatch):
    import logging

    nombres = ("anthropic", "httpx", "httpx2", "httpcore")
    previos = {n: logging.getLogger(n).level for n in nombres}
    monkeypatch.setenv("ANTHROPIC_LOG", "debug")
    try:
        for n in nombres:
            logging.getLogger(n).setLevel(logging.DEBUG)
        pr.fijar_entorno()
        assert "ANTHROPIC_LOG" not in os.environ
        assert all(logging.getLogger(n).getEffectiveLevel() >= logging.WARNING for n in nombres)
    finally:
        for n, nivel in previos.items():
            logging.getLogger(n).setLevel(nivel)


def test_fijar_entorno_quita_toda_variable_anthropic_salvo_la_llave(pr, monkeypatch):
    for variable in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_CONFIG_DIR",
        "ANTHROPIC_IDENTITY_TOKEN",
        "ANTHROPIC_WORKSPACE_ID",
        "ANTHROPIC_VARIABLE_FUTURA",
    ):
        monkeypatch.setenv(variable, "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    pr.fijar_entorno()
    assert [k for k in os.environ if k.startswith("ANTHROPIC_")] == ["ANTHROPIC_API_KEY"]


def test_el_cliente_real_apunta_a_la_url_oficial_aunque_el_entorno_diga_otra(pr, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://intruso.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "otro-token")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "anthropic-beta: intruso")
    pr.fijar_entorno()
    guardia = pr.Guardia(pr.Presupuesto(pr.CARPETA_DEFECTO, 5.0, 15.0))
    with pr.entorno_vigilado(guardia, None):
        real = anthropic.Anthropic()._real
    assert str(real.base_url).rstrip("/") == "https://api.anthropic.com"
    assert real.api_key == "sk-prueba" and real.auth_token is None
    assert "intruso" not in repr(real.default_headers)


def test_la_fabrica_ignora_anthropic_base_url_aunque_no_se_llame_fijar_entorno(pr, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://intruso.example")
    guardia = pr.Guardia(pr.Presupuesto(pr.CARPETA_DEFECTO, 5.0, 15.0))
    with pr.entorno_vigilado(guardia, None):
        real = anthropic.Anthropic()._real
    assert str(real.base_url).rstrip("/") == "https://api.anthropic.com"
