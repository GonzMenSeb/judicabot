from __future__ import annotations

import os

import pytest

from tutela2 import config as cfgmod
from tutela2 import llm
from tutela2.config import Config, LLMConfig
from tutela2.llm import ErrorLLM, FakeClient

VARIABLE = "TUTELA2_MODELOS_PERMITIDOS"
SONNET, HAIKU, OPUS = cfgmod.MODELOS
ARGON, CARBON, HYDROGEN = cfgmod.MODELOS_GEMINI


def test_tutela2_proveedor_fake_fuerza_el_cliente_falso_sin_relatoria(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    cfg = cfgmod.cargar(tmp_path)
    assert cfg.llm.proveedor == "fake"
    assert cfg.verificar_relatoria is False
    assert cfg.apoderados.consulta == "fake"


def test_tutela2_proveedor_se_ignora_sin_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    monkeypatch.setenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, "extension")
    cfg = cfgmod.cargar(tmp_path, entorno=False)
    assert cfg.llm.proveedor == "anthropic"
    assert cfg.verificar_relatoria is True
    assert cfg.apoderados.consulta == "apagada"


@pytest.fixture
def sin_consulta_en_el_entorno(monkeypatch):
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)
    monkeypatch.delenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, raising=False)


def test_apoderados_por_defecto_y_config_json_sin_la_clave(tmp_path, sin_consulta_en_el_entorno):
    a = Config().apoderados
    assert (a.activo, a.consulta, a.max_chars) == (True, "apagada", 150_000)
    (tmp_path / "config.json").write_text(Config().model_dump_json(exclude={"apoderados"}), encoding="utf-8")
    assert cfgmod.cargar(tmp_path).apoderados == cfgmod.ApoderadosConfig()
    cfgmod.guardar(tmp_path, Config(apoderados=cfgmod.ApoderadosConfig(consulta="extension", max_chars=9000)))
    assert cfgmod.cargar(tmp_path).apoderados.model_dump() == {"activo": True, "consulta": "extension", "max_chars": 9000}


def test_la_consulta_automatica_de_la_vigencia_esta_apagada_por_defecto(tmp_path, sin_consulta_en_el_entorno):
    """Compuerta legal: hasta que la URNA y el área jurídica lo aprueben por escrito, ninguna cédula sale sola."""
    assert cfgmod.ApoderadosConfig().consulta == "apagada"
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "apagada"
    cfgmod.guardar(tmp_path, Config())
    assert '"consulta": "apagada"' in (tmp_path / "config.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("modo", ["extension", "directa", "apagada", " Extension "])
def test_la_variable_de_entorno_enciende_o_apaga_la_consulta_sobre_el_config_del_caso(tmp_path, sin_consulta_en_el_entorno, monkeypatch, modo):
    cfgmod.guardar(tmp_path, Config(apoderados=cfgmod.ApoderadosConfig(consulta="extension" if modo.strip() == "apagada" else "apagada")))
    monkeypatch.setenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, modo)
    assert cfgmod.cargar(tmp_path).apoderados.consulta == modo.strip().lower()
    assert cfgmod.cargar(tmp_path, entorno=False).apoderados.consulta != modo.strip().lower()


@pytest.mark.parametrize("modo", ["", "   "])
def test_la_variable_de_entorno_vacia_no_cambia_nada(tmp_path, sin_consulta_en_el_entorno, monkeypatch, modo):
    monkeypatch.setenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, modo)
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "apagada"
    cfgmod.guardar(tmp_path, Config(apoderados=cfgmod.ApoderadosConfig(consulta="extension")))
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "extension"


@pytest.mark.parametrize("modo", ["off", "apagado", "no", "0", "false", "fake", "encendida", "EXTENSION_X"])
def test_la_variable_de_entorno_invalida_o_fake_apaga_la_consulta(tmp_path, sin_consulta_en_el_entorno, monkeypatch, caplog, modo):
    """Compuerta legal: quien quiso apagar la consulta con un valor que no se entiende no la deja encendida."""
    monkeypatch.setattr(cfgmod, "_avisadas", set())
    cfgmod.guardar(tmp_path, Config(apoderados=cfgmod.ApoderadosConfig(consulta="extension")))
    monkeypatch.setenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, modo)
    with caplog.at_level("WARNING", logger="tutela2"):
        assert cfgmod.cargar(tmp_path).apoderados.consulta == "apagada"
        assert cfgmod.cargar(tmp_path).apoderados.consulta == "apagada"
    avisos = [r for r in caplog.records if cfgmod.VARIABLE_CONSULTA_VIGENCIA in r.getMessage()]
    assert len(avisos) == 1 and "extension, directa, apagada" in avisos[0].getMessage()
    assert cfgmod.cargar(tmp_path, entorno=False).apoderados.consulta == "extension"


def test_el_proveedor_falso_manda_sobre_la_variable_de_la_consulta(tmp_path, sin_consulta_en_el_entorno, monkeypatch):
    monkeypatch.setenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, "extension")
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "fake"


def test_la_consulta_simulada_sin_el_proveedor_falso_queda_apagada(tmp_path, sin_consulta_en_el_entorno):
    """Un certificado ficticio nunca debe dejar en verde a un abogado de un caso real."""
    cfgmod.guardar(tmp_path, Config(apoderados=cfgmod.ApoderadosConfig(consulta="fake")))
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "apagada"
    assert cfgmod.cargar(tmp_path, entorno=False).apoderados.consulta == "fake"
    cfgmod.guardar(tmp_path, Config(llm=LLMConfig(proveedor="fake"), apoderados=cfgmod.ApoderadosConfig(consulta="fake")))
    assert cfgmod.cargar(tmp_path).apoderados.consulta == "fake"


def test_apoderados_es_un_nodo_del_modelo_con_su_prompt_y_sus_ajustes(monkeypatch):
    from tutela2 import prompts

    assert cfgmod.NODOS_LLM == ("apertura", "apoderados", "consideraciones", "caso_concreto")
    assert set(prompts.prompts_default()) == set(cfgmod.NODOS_LLM)
    texto, prompt_id = prompts.prompt_para("apoderados", Config())
    assert texto and prompt_id.startswith("apoderados@")
    cfg = Config(llm=LLMConfig(modelo=SONNET, modelo_por_nodo={"apoderados": HAIKU}, effort_por_nodo={"apoderados": "low"}))
    assert (cfg.modelo_para("apoderados"), cfg.effort_para("apoderados")) == (HAIKU, "low")
    assert cfg.modelo_para("consideraciones") == SONNET
    monkeypatch.setenv(VARIABLE, SONNET)
    with pytest.raises(ErrorLLM, match=rf"{HAIKU} \(nodo apoderados\)"):
        llm.cliente_para(cfg)


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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prueba")
    monkeypatch.setattr(llm, "AnthropicClient", lambda: "cliente")
    assert llm.cliente_para(Config(llm=LLMConfig(modelo=OPUS))) == "cliente"
    monkeypatch.setenv(VARIABLE, f"{SONNET},{OPUS}")
    cfg = Config(llm=LLMConfig(modelo_por_nodo={"apertura": SONNET, "caso_concreto": OPUS}))
    assert llm.cliente_para(cfg) == "cliente"


def test_modelos_permitidos_por_proveedor_comparten_la_variable(monkeypatch):
    assert cfgmod.modelos_permitidos("gemini") == cfgmod.MODELOS_GEMINI
    monkeypatch.setenv(VARIABLE, f"{HYDROGEN},{SONNET},{ARGON}")
    assert cfgmod.modelos_permitidos() == (SONNET,)
    assert cfgmod.modelos_permitidos("gemini") == (ARGON, HYDROGEN)
    assert cfgmod.modelo_permitido(ARGON) and cfgmod.modelo_permitido(SONNET) and not cfgmod.modelo_permitido(CARBON)
    assert not cfgmod.modelo_permitido(ARGON, "anthropic") and cfgmod.modelo_permitido(ARGON, "gemini")


def gemini(**extra) -> Config:
    return Config(llm=LLMConfig(proveedor="gemini", modelo=ARGON, **extra))


def test_con_gemini_los_ajustes_por_nodo_de_claude_se_ignoran():
    cfg = gemini(effort="medium", modelo_por_nodo={"apertura": OPUS, "caso_concreto": HYDROGEN}, effort_por_nodo={"apertura": "max", "caso_concreto": "xhigh"})
    assert [cfg.modelo_para(n) for n in cfgmod.NODOS_LLM] == [ARGON, ARGON, ARGON, HYDROGEN]
    assert [cfg.effort_para(n) for n in cfgmod.NODOS_LLM] == ["medium", "medium", "medium", "xhigh"]


def test_con_gemini_el_nivel_por_nodo_debe_admitirlo_el_modelo_del_nodo():
    cfg = gemini(effort_por_nodo={"apertura": "xhigh", "consideraciones": "low"})
    assert cfg.effort_para("apertura") == "high" and cfg.effort_para("consideraciones") == "low"


def test_con_gemini_el_nivel_global_debe_admitirlo_el_modelo_del_nodo():
    cfg = Config(llm=LLMConfig(proveedor="gemini", modelo=HYDROGEN, effort="xhigh", modelo_por_nodo={"apertura": ARGON}))
    assert cfg.effort_para("apertura") == "high" and cfg.effort_para("caso_concreto") == "xhigh"
    cfg.llm.effort_por_nodo = {"apertura": "medium"}
    assert cfg.effort_para("apertura") == "medium"


def test_con_anthropic_los_ajustes_por_nodo_de_gemini_se_ignoran():
    cfg = Config(llm=LLMConfig(modelo=SONNET, modelo_por_nodo={"apertura": ARGON, "caso_concreto": OPUS}, effort_por_nodo={"apertura": "max", "caso_concreto": "ultra"}))
    assert [cfg.modelo_para(n) for n in cfgmod.NODOS_LLM] == [SONNET, SONNET, SONNET, OPUS]
    assert [cfg.effort_para(n) for n in cfgmod.NODOS_LLM] == ["max", "high", "high", "high"]


def test_el_proveedor_falso_no_filtra_los_ajustes_por_nodo():
    cfg = Config(llm=LLMConfig(proveedor="fake", modelo_por_nodo={"apertura": "otro"}, effort_por_nodo={"apertura": "x"}))
    assert cfg.modelo_para("apertura") == "otro" and cfg.effort_para("apertura") == "x"


def test_cliente_para_gemini_usa_su_cliente_y_su_lista_permitida(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-prueba")
    monkeypatch.setattr(llm, "GeminiClient", lambda: "gemini")
    assert llm.cliente_para(gemini()) == "gemini"
    monkeypatch.setenv(VARIABLE, f"{SONNET},{CARBON}")
    with pytest.raises(ErrorLLM) as e:
        llm.cliente_para(gemini())
    assert ARGON in str(e.value) and f"permitidos: {CARBON}." in str(e.value)
    monkeypatch.setenv(VARIABLE, SONNET)
    with pytest.raises(ErrorLLM, match="ninguno"):
        llm.cliente_para(gemini())


def test_cliente_falso_no_depende_de_la_lista_permitida(monkeypatch):
    monkeypatch.setenv(VARIABLE, HAIKU)
    assert isinstance(llm.cliente_para(Config(llm=LLMConfig(proveedor="fake"))), FakeClient)


VARIABLE_CACHE = "TUTELA2_CACHE_DIR"


def test_cache_path_sin_variable_usa_cache_dir_y_lo_crea(tmp_path, monkeypatch):
    monkeypatch.delenv(VARIABLE_CACHE, raising=False)
    destino = tmp_path / "a" / "b"
    assert Config(cache_dir=str(destino)).cache_path() == destino
    assert destino.is_dir()


def test_cache_path_la_variable_manda_sobre_cache_dir(tmp_path, monkeypatch):
    elegido = tmp_path / "volumen" / ".cache"
    monkeypatch.setenv(VARIABLE_CACHE, str(elegido))
    cfg = Config(cache_dir=str(tmp_path / "del_config"))
    assert cfg.cache_path() == elegido
    assert elegido.is_dir() and not (tmp_path / "del_config").exists()
    assert os.access(elegido, os.W_OK | os.X_OK)


def test_cache_path_la_variable_manda_sobre_el_config_json_del_caso(tmp_path, monkeypatch):
    elegido = tmp_path / "volumen" / ".cache"
    monkeypatch.setenv(VARIABLE_CACHE, str(elegido))
    (tmp_path / "caso").mkdir()
    cfgmod.guardar(tmp_path / "caso", Config())
    assert cfgmod.cargar(tmp_path / "caso").cache_dir == "~/.cache/tutela2"
    assert cfgmod.cargar(tmp_path / "caso").cache_path() == elegido


def test_cache_path_expande_la_tilde_de_la_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(VARIABLE_CACHE, "~/mi-cache")
    assert Config().cache_path() == tmp_path / "mi-cache"


@pytest.mark.parametrize("valor", ["", "   "])
def test_cache_path_ignora_una_variable_vacia(tmp_path, monkeypatch, valor):
    monkeypatch.setenv(VARIABLE_CACHE, valor)
    destino = tmp_path / "del_config"
    assert Config(cache_dir=str(destino)).cache_path() == destino


def test_cache_path_es_idempotente_con_el_directorio_existente(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE_CACHE, str(tmp_path / ".cache"))
    cfg = Config()
    primero = cfg.cache_path()
    (primero / "ocr-psm1").mkdir()
    assert cfg.cache_path() == primero and (primero / "ocr-psm1").is_dir()
