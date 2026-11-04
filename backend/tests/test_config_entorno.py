from __future__ import annotations

import pytest

from tutela2 import config as cfgmod
from tutela2 import llm
from tutela2.config import Config, LLMConfig
from tutela2.llm import ErrorLLM, FakeClient

VARIABLE = "TUTELA2_MODELOS_PERMITIDOS"
SONNET, HAIKU, OPUS = cfgmod.MODELOS


def test_tutela2_proveedor_fake_fuerza_el_cliente_falso_sin_relatoria(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    cfg = cfgmod.cargar(tmp_path)
    assert cfg.llm.proveedor == "fake"
    assert cfg.verificar_relatoria is False


def test_tutela2_proveedor_se_ignora_sin_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    cfg = cfgmod.cargar(tmp_path, entorno=False)
    assert cfg.llm.proveedor == "anthropic"
    assert cfg.verificar_relatoria is True


def test_tutela2_proveedor_ausente_o_invalido_no_cambia_nada(tmp_path, monkeypatch):
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)
    assert cfgmod.cargar(tmp_path).llm.proveedor == "anthropic"
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "otro")
    assert cfgmod.cargar(tmp_path).llm.proveedor == "anthropic"


@pytest.fixture(autouse=True)
def sin_restriccion(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)


@pytest.mark.parametrize("valor", [None, "", "   ", " , ,"])
def test_modelos_permitidos_apagada_ofrece_todos(monkeypatch, valor):
    if valor is not None:
        monkeypatch.setenv(VARIABLE, valor)
    assert cfgmod.modelos_permitidos() == cfgmod.MODELOS


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (SONNET, (SONNET,)),
        (f" {HAIKU} , {SONNET},", (SONNET, HAIKU)),
        (f"{OPUS},{SONNET},{SONNET}", (SONNET, OPUS)),
        (f"{SONNET},gpt-5", (SONNET,)),
        ("gpt-5", ()),
    ],
)
def test_modelos_permitidos_restringe_sin_ampliar_y_conserva_el_orden(monkeypatch, valor, esperado):
    monkeypatch.setenv(VARIABLE, valor)
    assert cfgmod.modelos_permitidos() == esperado


def test_cliente_para_rechaza_el_modelo_global_no_permitido(monkeypatch):
    monkeypatch.setenv(VARIABLE, f"{SONNET},{HAIKU}")
    with pytest.raises(ErrorLLM) as e:
        llm.cliente_para(Config(llm=LLMConfig(modelo=OPUS)))
    assert OPUS in str(e.value) and VARIABLE in str(e.value) and f"{SONNET}, {HAIKU}" in str(e.value)


def test_cliente_para_rechaza_el_modelo_de_un_nodo_no_permitido(monkeypatch):
    monkeypatch.setenv(VARIABLE, SONNET)
    cfg = Config(llm=LLMConfig(modelo_por_nodo={"caso_concreto": OPUS}))
    with pytest.raises(ErrorLLM, match=OPUS):
        llm.cliente_para(cfg)


def test_cliente_para_sin_modelos_validos_dice_ninguno(monkeypatch):
    monkeypatch.setenv(VARIABLE, "gpt-5")
    with pytest.raises(ErrorLLM, match="ninguno"):
        llm.cliente_para(Config())


def test_cliente_para_acepta_los_modelos_permitidos_y_no_restringe_sin_variable(monkeypatch):
    monkeypatch.setattr(llm, "AnthropicClient", lambda: "cliente")
    assert llm.cliente_para(Config(llm=LLMConfig(modelo=OPUS))) == "cliente"
    monkeypatch.setenv(VARIABLE, f"{SONNET},{OPUS}")
    cfg = Config(llm=LLMConfig(modelo_por_nodo={"apertura": SONNET, "caso_concreto": OPUS}))
    assert llm.cliente_para(cfg) == "cliente"


def test_cliente_falso_no_depende_de_la_lista_permitida(monkeypatch):
    monkeypatch.setenv(VARIABLE, HAIKU)
    assert isinstance(llm.cliente_para(Config(llm=LLMConfig(proveedor="fake"))), FakeClient)
