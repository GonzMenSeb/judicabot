from __future__ import annotations

import json
import os
import sys
import time
import types
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from tutela2 import config as cfgmod
from tutela2 import preferencias as pref
from tutela2 import server
from tutela2.config import Config, JevConfig, LLMConfig

VARIABLES = (
    "TUTELA2_MODELO",
    "TUTELA2_JEV_MODO",
    "TUTELA2_JEV_UMBRAL",
    "TUTELA2_EFFORT",
    "TUTELA2_MAX_TOKENS",
    "TUTELA2_MAX_RETRIES",
    "TUTELA2_PROVEEDOR_LLM",
    "TUTELA2_GEMINI_MODELO",
    "TUTELA2_GEMINI_RAZONAMIENTO",
    "TUTELA2_MODELOS_PERMITIDOS",
    "TUTELA2_PROVEEDOR",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "JEV_API_KEY",
)
PREFERENCIAS_ENTORNO = VARIABLES[:9]

COMPLETA = {
    "modelo": "claude-opus-5-5",
    "jev": {"modo": "sombra", "umbral": 0.75},
    "effort": "medium",
    "max_tokens": 32000,
    "max_retries": 2,
}


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for var in VARIABLES:
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.setattr(pref, "_APLICADAS", {})


@pytest.fixture
def casos(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    return tmp_path / "casos"


@pytest.fixture
def archivo(casos):
    return casos / ".preferencias.json"


@pytest.fixture
def cliente(casos) -> TestClient:
    server.JOBS.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def cfgs(monkeypatch) -> list[Config]:
    capturadas: list[Config] = []

    def nuevo(caso_dir):
        capturadas.append(cfgmod.cargar(caso_dir))
        return {"ok": True, "estado": "revision", "payload": None, "salidas": [], "resumen": {}, "error": None}

    fake = types.ModuleType("tutela2.api")
    fake.nuevo = nuevo
    fake.estado = lambda caso_dir: {"estado": "sin_iniciar"}
    monkeypatch.setitem(sys.modules, "tutela2.api", fake)
    return capturadas


CONFIG_CASO = Config(
    llm=LLMConfig(modelo="claude-haiku-5-5", effort="low", max_tokens=100, max_retries=4),
    jev=JevConfig(modo="relleno", umbral_confianza=0.5),
)


@pytest.fixture
def caso(casos):
    carpeta = casos / "c1"
    carpeta.mkdir(parents=True)
    cfgmod.guardar(carpeta, CONFIG_CASO)
    return carpeta


def _resumen_ia(cfg: Config) -> dict:
    return {
        "modelo": cfg.llm.modelo,
        "jev": {"modo": cfg.jev.modo, "umbral": cfg.jev.umbral_confianza},
        "effort": cfg.llm.effort,
        "max_tokens": cfg.llm.max_tokens,
        "max_retries": cfg.llm.max_retries,
    }


def test_get_sin_preferencias_devuelve_los_valores_por_defecto(cliente, archivo):
    r = cliente.get("/api/ia")
    assert r.status_code == 200
    assert r.json() == {
        "proveedor": "anthropic",
        "modelo": "claude-sonnet-5-5",
        "modelos": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
        "gemini": {"modelo": "gemini-4-argon", "razonamiento": "high"},
        "modelos_gemini": ["gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen"],
        "razonamientos_gemini": {
            "gemini-4-argon": ["low", "medium", "high"],
            "gemini-4-carbon": ["low", "medium", "high"],
            "gemini-4-hydrogen": ["low", "medium", "high", "xhigh"],
        },
        "api_key": False,
        "gemini_key": False,
        "jev_key": False,
        "jev": {"modo": "apagado", "umbral": 0.9},
        "effort": "high",
        "max_tokens": 64000,
        "max_retries": 1,
    }
    assert not archivo.exists()


def test_get_informa_las_claves_sin_exponerlas(cliente, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secreta-123")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-secreta-789")
    monkeypatch.setenv("JEV_API_KEY", "k-jev-secreta-456")
    r = cliente.get("/api/ia")
    assert r.json()["api_key"] is True and r.json()["gemini_key"] is True and r.json()["jev_key"] is True
    assert "secreta" not in r.text


def test_get_informa_cada_clave_por_separado(cliente, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
    ia = cliente.get("/api/ia").json()
    assert ia["gemini_key"] is True and ia["api_key"] is False
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert cliente.get("/api/ia").json()["gemini_key"] is False


def test_put_round_trip(cliente, archivo):
    r = cliente.put("/api/ia", json=COMPLETA)
    assert r.status_code == 200
    assert {k: r.json()[k] for k in COMPLETA} == COMPLETA
    assert cliente.get("/api/ia").json() == r.json()
    assert json.loads(archivo.read_text(encoding="utf-8")) == COMPLETA


def test_put_acepta_que_se_devuelva_lo_que_entrego_el_get(cliente):
    leido = cliente.get("/api/ia").json()
    leido["effort"] = "max"
    r = cliente.put("/api/ia", json=leido)
    assert r.status_code == 200 and r.json()["effort"] == "max"
    leido = r.json()
    leido.update(proveedor="gemini", gemini={"modelo": "gemini-4-hydrogen", "razonamiento": "xhigh"})
    r = cliente.put("/api/ia", json=leido)
    assert r.status_code == 200 and r.json()["proveedor"] == "gemini" and r.json()["gemini"]["razonamiento"] == "xhigh"


GEMINI = {"proveedor": "gemini", "gemini": {"modelo": "gemini-4-carbon", "razonamiento": "medium"}}


def test_put_de_gemini_round_trip_conserva_lo_de_anthropic(cliente, archivo):
    cliente.put("/api/ia", json=COMPLETA)
    r = cliente.put("/api/ia", json=GEMINI)
    assert r.status_code == 200
    assert r.json()["proveedor"] == "gemini" and r.json()["gemini"] == GEMINI["gemini"]
    assert r.json()["modelo"] == COMPLETA["modelo"] and r.json()["effort"] == COMPLETA["effort"]
    assert json.loads(archivo.read_text(encoding="utf-8")) == {**COMPLETA, **GEMINI}
    assert cliente.get("/api/ia").json() == r.json()


def test_put_parcial_de_gemini_valida_el_nivel_contra_el_modelo_guardado(cliente, archivo):
    cliente.put("/api/ia", json={"gemini": {"modelo": "gemini-4-hydrogen", "razonamiento": "low"}})
    r = cliente.put("/api/ia", json={"gemini": {"razonamiento": "xhigh"}})
    assert r.status_code == 200 and r.json()["gemini"] == {"modelo": "gemini-4-hydrogen", "razonamiento": "xhigh"}
    antes = archivo.read_text(encoding="utf-8")
    r = cliente.put("/api/ia", json={"gemini": {"modelo": "gemini-4-argon"}})
    assert r.status_code == 422
    assert r.json() == {
        "detail": {"errores": [{"campo": "gemini.razonamiento", "mensaje": "con gemini-4-argon debe ser uno de: low, medium o high."}]}
    }
    assert archivo.read_text(encoding="utf-8") == antes


def test_put_de_nivel_sin_modelo_se_valida_contra_el_modelo_por_defecto(cliente, archivo):
    r = cliente.put("/api/ia", json={"gemini": {"razonamiento": "xhigh"}})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"] == [
        {"campo": "gemini.razonamiento", "mensaje": "con gemini-4-argon debe ser uno de: low, medium o high."}
    ]
    assert not archivo.exists()


def test_put_parcial_conserva_lo_demas(cliente, archivo):
    cliente.put("/api/ia", json=COMPLETA)
    r = cliente.put("/api/ia", json={"jev": {"modo": "relleno"}, "max_retries": 0})
    assert r.status_code == 200
    esperado = {**COMPLETA, "jev": {"modo": "relleno", "umbral": 0.75}, "max_retries": 0}
    assert json.loads(archivo.read_text(encoding="utf-8")) == esperado


def test_put_vacio_no_cambia_nada_ni_crea_preferencias(cliente, archivo):
    r = cliente.put("/api/ia", json={})
    assert r.status_code == 200
    assert json.loads(archivo.read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize(
    "cuerpo, campo, mensaje",
    [
        ({"modelo": "gpt-5"}, "modelo", "debe ser uno de: claude-sonnet-5-5, claude-haiku-5-5 o claude-opus-5-5."),
        ({"jev": {"modo": "siempre"}}, "jev.modo", "debe ser uno de: apagado, sombra o relleno."),
        ({"jev": {"umbral": 1.5}}, "jev.umbral", "debe ser como máximo 1.0."),
        ({"jev": {"umbral": -0.1}}, "jev.umbral", "debe ser al menos 0.0."),
        ({"jev": {"umbral": "alto"}}, "jev.umbral", "debe ser un número."),
        ({"effort": "ultra"}, "effort", "debe ser uno de: low, medium, high, xhigh o max."),
        ({"max_tokens": 0}, "max_tokens", "debe ser al menos 1."),
        ({"max_tokens": 64001}, "max_tokens", "debe ser como máximo 64000."),
        ({"max_tokens": 2.5}, "max_tokens", "debe ser un número entero, sin decimales."),
        ({"max_tokens": True}, "max_tokens", "debe ser un número entero."),
        ({"max_retries": -1}, "max_retries", "debe ser al menos 0."),
        ({"max_retries": 6}, "max_retries", "debe ser como máximo 5."),
        ({"max_retries": "dos"}, "max_retries", "debe ser un número entero."),
        ({"temperatura": 1}, "temperatura", "no es un campo reconocido."),
        ({"jev": {"otro": 1}}, "jev.otro", "no es un campo reconocido."),
        ({"jev": "sombra"}, "jev", "debe ser un objeto."),
        ({"proveedor": "openai"}, "proveedor", "debe ser uno de: anthropic o gemini."),
        ({"proveedor": "fake"}, "proveedor", "debe ser uno de: anthropic o gemini."),
        ({"gemini": {"modelo": "gemini-3.8-flash"}}, "gemini.modelo", "debe ser uno de: gemini-4-argon, gemini-4-carbon o gemini-4-hydrogen."),
        ({"gemini": {"razonamiento": "max"}}, "gemini.razonamiento", "debe ser uno de: low, medium, high o xhigh."),
        (
            {"gemini": {"modelo": "gemini-4-carbon", "razonamiento": "xhigh"}},
            "gemini.razonamiento",
            "con gemini-4-carbon debe ser uno de: low, medium o high.",
        ),
        ({"gemini": "argon"}, "gemini", "debe ser un objeto."),
        ({"gemini": {"effort": "high"}}, "gemini.effort", "no es un campo reconocido."),
        ({"modelo": "gemini-4-argon"}, "modelo", "debe ser uno de: claude-sonnet-5-5, claude-haiku-5-5 o claude-opus-5-5."),
    ],
)
def test_put_invalido_devuelve_422_con_mensajes_legibles(cliente, archivo, cuerpo, campo, mensaje):
    r = cliente.put("/api/ia", json=cuerpo)
    assert r.status_code == 422
    assert r.json() == {"detail": {"errores": [{"campo": campo, "mensaje": mensaje}]}}
    assert not archivo.exists()


def test_put_invalido_reporta_todos_los_errores_y_no_guarda_nada(cliente, archivo):
    cliente.put("/api/ia", json={"effort": "low"})
    antes = archivo.read_text(encoding="utf-8")
    r = cliente.put("/api/ia", json={"effort": "high", "max_tokens": 0, "jev": {"modo": "x"}})
    assert r.status_code == 422
    assert {e["campo"] for e in r.json()["detail"]["errores"]} == {"max_tokens", "jev.modo"}
    assert "Input should" not in r.text
    assert archivo.read_text(encoding="utf-8") == antes


@pytest.mark.parametrize("contenido, mensaje", [("{no es json", "no es un JSON válido."), ("[]", "debe ser un objeto.")])
def test_put_con_cuerpo_que_no_es_un_objeto_json(cliente, contenido, mensaje):
    r = cliente.put("/api/ia", content=contenido, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"][0]["mensaje"] == mensaje


def test_archivo_antiguo_solo_con_modelo_sigue_siendo_compatible(cliente, archivo):
    archivo.parent.mkdir(parents=True)
    archivo.write_text(json.dumps({"modelo": "claude-haiku-5-5"}), encoding="utf-8")
    ia = cliente.get("/api/ia").json()
    assert ia["modelo"] == "claude-haiku-5-5"
    assert ia["effort"] == "high" and ia["jev"] == {"modo": "apagado", "umbral": 0.9}
    assert cliente.get("/api/estado-servidor").json()["modelo"] == "claude-haiku-5-5"
    assert server.modelo_actual() == "claude-haiku-5-5"
    cliente.put("/api/ia", json={"effort": "low"})
    assert json.loads(archivo.read_text(encoding="utf-8")) == {"modelo": "claude-haiku-5-5", "effort": "low"}


@pytest.mark.parametrize("contenido", ["no es json", "[]", '"texto"', "null", json.dumps({"modelo": "gpt-5"}), ""])
def test_archivo_corrupto_o_con_modelo_desconocido_usa_los_valores_por_defecto(cliente, archivo, contenido):
    archivo.parent.mkdir(parents=True)
    archivo.write_text(contenido, encoding="utf-8")
    assert cliente.get("/api/ia").status_code == 200
    assert server.modelo_actual() == "claude-sonnet-5-5"


def test_archivo_con_nivel_de_gemini_no_admitido_conserva_el_modelo(archivo):
    archivo.parent.mkdir(parents=True)
    bruto = {"proveedor": "gemini", "gemini": {"modelo": "gemini-4-carbon", "razonamiento": "xhigh"}}
    archivo.write_text(json.dumps(bruto), encoding="utf-8")
    leidas = pref.leer(archivo)
    assert leidas.proveedor == "gemini" and leidas.gemini.modelo == "gemini-4-carbon" and leidas.gemini.razonamiento is None
    archivo.write_text(json.dumps({"gemini": None, "proveedor": "otro", "modelo": "claude-haiku-5-5"}), encoding="utf-8")
    leidas = pref.leer(archivo)
    assert leidas.proveedor is None and leidas.modelo == "claude-haiku-5-5"


def test_archivo_con_claves_validas_e_invalidas_conserva_las_validas(archivo):
    archivo.parent.mkdir(parents=True)
    bruto = {"modelo": "claude-opus-5-5", "effort": "ultra", "max_tokens": "mucho", "jev": {"modo": "sombra", "umbral": 7}, "x": 1}
    archivo.write_text(json.dumps(bruto), encoding="utf-8")
    leidas = pref.leer(archivo)
    assert leidas.modelo == "claude-opus-5-5" and leidas.jev.modo == "sombra"
    assert leidas.effort is None and leidas.max_tokens is None and leidas.jev.umbral is None


def test_post_modelo_conserva_las_demas_preferencias(cliente, archivo):
    cliente.put("/api/ia", json=COMPLETA)
    assert cliente.post("/api/modelo", json={"modelo": "claude-haiku-5-5"}).json() == {"modelo": "claude-haiku-5-5"}
    assert json.loads(archivo.read_text(encoding="utf-8")) == {**COMPLETA, "modelo": "claude-haiku-5-5"}
    assert cliente.get("/api/ia").json()["modelo"] == "claude-haiku-5-5"


def test_post_modelo_solo_escribe_el_modelo(cliente, archivo):
    cliente.post("/api/modelo", json={"modelo": "claude-haiku-5-5"})
    assert json.loads(archivo.read_text(encoding="utf-8")) == {"modelo": "claude-haiku-5-5"}


def test_la_escritura_es_atomica_y_no_deja_temporales(cliente, archivo, monkeypatch):
    cliente.put("/api/ia", json=COMPLETA)
    assert [p.name for p in archivo.parent.iterdir()] == [".preferencias.json"]
    antes = archivo.read_text(encoding="utf-8")

    def falla(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(pref.os, "replace", falla)
    with pytest.raises(OSError):
        pref.actualizar(archivo, pref.Preferencias(effort="low"))
    assert archivo.read_text(encoding="utf-8") == antes
    assert [p.name for p in archivo.parent.iterdir()] == [".preferencias.json"]


def test_preferencias_guardadas_mandan_sobre_el_config_del_caso(cliente, caso, cfgs):
    cliente.put("/api/ia", json=COMPLETA)
    server._comando("nuevo", caso, None)
    assert _resumen_ia(cfgs[-1]) == COMPLETA
    assert _resumen_ia(cfgmod.cargar(caso, entorno=False)) == _resumen_ia(CONFIG_CASO)


def test_preferencias_se_aplican_al_ejecutar_por_el_endpoint(cliente, caso, cfgs):
    cliente.put("/api/ia", json=COMPLETA)
    job_id = cliente.post("/api/casos/c1/run", json={"cmd": "nuevo"}).json()["job_id"]
    limite = time.time() + 5
    while cliente.get(f"/api/jobs/{job_id}").json()["estado"] == "corriendo" and time.time() < limite:
        time.sleep(0.02)
    assert _resumen_ia(cfgs[-1]) == COMPLETA


def test_sin_preferencias_manda_el_config_del_caso(caso, cfgs):
    server._comando("nuevo", caso, None)
    assert _resumen_ia(cfgs[-1]) == _resumen_ia(CONFIG_CASO)
    assert not any(v in os.environ for v in PREFERENCIAS_ENTORNO)


def test_solo_las_preferencias_fijadas_mandan_sobre_el_caso(cliente, caso, cfgs):
    cliente.put("/api/ia", json={"effort": "xhigh", "jev": {"umbral": 0.6}})
    server._comando("nuevo", caso, None)
    esperado = _resumen_ia(CONFIG_CASO)
    esperado.update(effort="xhigh", jev={"modo": "relleno", "umbral": 0.6})
    assert _resumen_ia(cfgs[-1]) == esperado


def test_post_modelo_manda_sobre_el_config_del_caso_y_no_toca_lo_demas(cliente, caso, cfgs):
    cliente.post("/api/modelo", json={"modelo": "claude-opus-5-5"})
    server._comando("nuevo", caso, None)
    esperado = {**_resumen_ia(CONFIG_CASO), "modelo": "claude-opus-5-5"}
    assert _resumen_ia(cfgs[-1]) == esperado


def test_si_la_preferencia_desaparece_vuelve_a_mandar_el_caso(cliente, caso, archivo, cfgs):
    cliente.put("/api/ia", json=COMPLETA)
    server._comando("nuevo", caso, None)
    archivo.unlink()
    server._comando("nuevo", caso, None)
    assert _resumen_ia(cfgs[-1]) == _resumen_ia(CONFIG_CASO)
    assert not any(v in os.environ for v in PREFERENCIAS_ENTORNO)


def test_variable_de_entorno_externa_no_se_pisa_sin_preferencia(caso, cfgs, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELO", "claude-opus-5-5")
    server._comando("nuevo", caso, None)
    assert cfgs[-1].llm.modelo == "claude-opus-5-5"
    assert os.environ["TUTELA2_MODELO"] == "claude-opus-5-5"


def test_variables_de_entorno_invalidas_se_ignoran(caso, monkeypatch):
    monkeypatch.setenv("TUTELA2_EFFORT", "ultra")
    monkeypatch.setenv("TUTELA2_MAX_TOKENS", "12")
    monkeypatch.setenv("TUTELA2_JEV_UMBRAL", "alto")
    cfg = cfgmod.cargar(caso)
    assert cfg.llm.effort == "low" and cfg.llm.max_tokens == 12 and cfg.jev.umbral_confianza == 0.5


def _resumen_llm(cfg: Config) -> tuple:
    return cfg.llm.proveedor, cfg.llm.modelo, cfg.llm.effort


def test_proveedor_gemini_guardado_lleva_su_modelo_y_nivel_al_caso(cliente, caso, cfgs):
    cliente.put("/api/ia", json={**COMPLETA, **GEMINI})
    server._comando("nuevo", caso, None)
    assert _resumen_llm(cfgs[-1]) == ("gemini", "gemini-4-carbon", "medium")
    assert cfgs[-1].llm.max_tokens == COMPLETA["max_tokens"] and cfgs[-1].jev.modo == "sombra"
    assert _resumen_llm(cfgmod.cargar(caso, entorno=False)) == ("anthropic", "claude-haiku-5-5", "low")


def test_gemini_sin_modelo_ni_nivel_guardados_usa_los_valores_por_defecto(cliente, caso, cfgs):
    cliente.put("/api/ia", json={"proveedor": "gemini"})
    server._comando("nuevo", caso, None)
    assert _resumen_llm(cfgs[-1]) == ("gemini", "gemini-4-argon", "high")


def test_volver_a_anthropic_recupera_sus_preferencias(cliente, caso, cfgs):
    cliente.put("/api/ia", json={**COMPLETA, **GEMINI})
    cliente.put("/api/ia", json={"proveedor": "anthropic"})
    server._comando("nuevo", caso, None)
    assert _resumen_llm(cfgs[-1]) == ("anthropic", "claude-opus-5-5", "medium")


def test_tutela2_proveedor_fake_manda_sobre_el_proveedor_guardado(cliente, caso, cfgs, monkeypatch):
    cliente.put("/api/ia", json=GEMINI)
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    server._comando("nuevo", caso, None)
    assert cfgs[-1].llm.proveedor == "fake" and cfgs[-1].verificar_relatoria is False


def test_el_proveedor_guardado_no_pisa_el_fake_del_caso(cliente, casos, cfgs):
    carpeta = casos / "falso"
    carpeta.mkdir(parents=True)
    cfgmod.guardar(carpeta, Config(llm=LLMConfig(proveedor="fake")))
    cliente.put("/api/ia", json=GEMINI)
    server._comando("nuevo", carpeta, None)
    assert cfgs[-1].llm.proveedor == "fake"


def test_caso_con_proveedor_gemini_conserva_su_modelo_sin_preferencias(casos, cfgs):
    carpeta = casos / "g"
    carpeta.mkdir(parents=True)
    cfgmod.guardar(carpeta, Config(llm=LLMConfig(proveedor="gemini", modelo="gemini-4-hydrogen", effort="xhigh")))
    server._comando("nuevo", carpeta, None)
    assert _resumen_llm(cfgs[-1]) == ("gemini", "gemini-4-hydrogen", "xhigh")


def test_variables_de_entorno_de_gemini(caso, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR_LLM", "gemini")
    monkeypatch.setenv("TUTELA2_GEMINI_MODELO", "gemini-4-hydrogen")
    monkeypatch.setenv("TUTELA2_GEMINI_RAZONAMIENTO", "xhigh")
    assert _resumen_llm(cfgmod.cargar(caso)) == ("gemini", "gemini-4-hydrogen", "xhigh")
    monkeypatch.delenv("TUTELA2_GEMINI_MODELO")
    assert _resumen_llm(cfgmod.cargar(caso)) == ("gemini", "gemini-4-argon", "high")
    monkeypatch.setenv("TUTELA2_PROVEEDOR_LLM", "otro")
    assert _resumen_llm(cfgmod.cargar(caso)) == _resumen_llm(CONFIG_CASO)


def test_las_preferencias_de_gemini_se_aplican_al_entorno_y_se_retiran(cliente, caso, archivo, cfgs):
    cliente.put("/api/ia", json=GEMINI)
    server._comando("nuevo", caso, None)
    assert os.environ["TUTELA2_PROVEEDOR_LLM"] == "gemini" and os.environ["TUTELA2_GEMINI_MODELO"] == "gemini-4-carbon"
    archivo.unlink()
    server._comando("nuevo", caso, None)
    assert not any(v in os.environ for v in PREFERENCIAS_ENTORNO)
    assert _resumen_llm(cfgs[-1]) == _resumen_llm(CONFIG_CASO)


def test_estado_servidor_informa_el_proveedor_activo_y_su_modelo(cliente, monkeypatch):
    estado = cliente.get("/api/estado-servidor").json()
    assert estado["proveedor"] == "anthropic" and estado["modelo"] == "claude-sonnet-5-5" and estado["gemini_key"] is False
    assert estado["modelos_gemini"] == ["gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen"]
    cliente.put("/api/ia", json=GEMINI)
    estado = cliente.get("/api/estado-servidor").json()
    assert estado["proveedor"] == "gemini" and estado["modelo"] == "gemini-4-carbon"
    assert server.modelo_actual() == "gemini-4-carbon"
    cliente.put("/api/ia", json={"gemini": {"modelo": "gemini-4-argon", "razonamiento": "low"}})
    assert cliente.get("/api/estado-servidor").json()["modelo"] == "gemini-4-argon"


def test_cargar_sin_entorno_ignora_las_preferencias(cliente, caso):
    cliente.put("/api/ia", json=COMPLETA)
    assert _resumen_ia(cfgmod.cargar(caso, entorno=False)) == _resumen_ia(CONFIG_CASO)
    assert _resumen_ia(cfgmod.cargar(caso)) == COMPLETA


def test_modelos_permitidos_filtran_la_lista_que_ofrece_la_api(cliente, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-haiku-5-5,claude-sonnet-5-5")
    r = cliente.get("/api/ia")
    assert r.status_code == 200
    assert r.json()["modelos"] == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    assert r.json()["modelo"] == "claude-sonnet-5-5"


def test_put_con_modelo_fuera_de_la_lista_permitida_devuelve_422(cliente, archivo, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-sonnet-5-5,claude-haiku-5-5")
    r = cliente.put("/api/ia", json={"modelo": "claude-opus-5-5"})
    assert r.status_code == 422
    assert r.json() == {
        "detail": {"errores": [{"campo": "modelo", "mensaje": "debe ser uno de: claude-sonnet-5-5 o claude-haiku-5-5."}]}
    }
    assert not archivo.exists()
    assert cliente.put("/api/ia", json={"modelo": "claude-haiku-5-5"}).json()["modelo"] == "claude-haiku-5-5"


def test_modelos_permitidos_restringen_ambos_catalogos(cliente, archivo, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "gemini-4-hydrogen,claude-haiku-5-5")
    ia = cliente.get("/api/ia").json()
    assert ia["modelos"] == ["claude-haiku-5-5"] and ia["modelos_gemini"] == ["gemini-4-hydrogen"]
    assert cliente.get("/api/estado-servidor").json()["modelos_gemini"] == ["gemini-4-hydrogen"]
    r = cliente.put("/api/ia", json={"gemini": {"modelo": "gemini-4-argon"}})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"] == [{"campo": "gemini.modelo", "mensaje": "debe ser uno de: gemini-4-hydrogen."}]
    assert not archivo.exists()
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-haiku-5-5")
    assert cliente.get("/api/ia").json()["modelos_gemini"] == []
    r = cliente.put("/api/ia", json={"gemini": {"modelo": "gemini-4-hydrogen"}})
    assert r.json()["detail"]["errores"] == [
        {"campo": "gemini.modelo", "mensaje": "no hay modelos permitidos en este servidor (TUTELA2_MODELOS_PERMITIDOS)."}
    ]


def test_put_sin_modelos_validos_en_la_lista_lo_dice(cliente, monkeypatch):
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "gpt-5")
    r = cliente.put("/api/ia", json={"modelo": "claude-sonnet-5-5"})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"] == [
        {"campo": "modelo", "mensaje": "no hay modelos permitidos en este servidor (TUTELA2_MODELOS_PERMITIDOS)."}
    ]
    assert cliente.get("/api/ia").json()["modelos"] == []


def test_modelo_guardado_o_del_entorno_fuera_de_la_lista_permitida_se_ignora(cliente, archivo, caso, monkeypatch):
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps({"modelo": "claude-opus-5-5", "effort": "low"}), encoding="utf-8")
    monkeypatch.setenv("TUTELA2_MODELOS_PERMITIDOS", "claude-sonnet-5-5")
    guardadas = pref.leer(archivo)
    assert guardadas.modelo is None and guardadas.effort == "low"
    assert cliente.get("/api/ia").json()["modelo"] == "claude-sonnet-5-5"
    monkeypatch.setenv("TUTELA2_MODELO", "claude-opus-5-5")
    assert pref.desde_entorno().modelo is None
    assert cfgmod.cargar(caso).llm.modelo == CONFIG_CASO.llm.modelo


def test_los_valores_permitidos_son_coherentes_con_la_configuracion():
    assert get_args(pref.Effort) == get_args(LLMConfig.model_fields["effort"].annotation)
    assert get_args(pref.Modo) == get_args(JevConfig.model_fields["modo"].annotation)
    assert get_args(pref.Modelo) == cfgmod.MODELOS
    assert get_args(pref.ModeloGemini) == cfgmod.MODELOS_GEMINI == tuple(cfgmod.RAZONAMIENTOS_GEMINI)
    assert set(get_args(pref.RazonamientoGemini)) <= set(get_args(pref.Effort))
    assert all(set(n) <= set(get_args(pref.RazonamientoGemini)) for n in cfgmod.RAZONAMIENTOS_GEMINI.values())
    assert cfgmod.RAZONAMIENTO_GEMINI in cfgmod.RAZONAMIENTOS_GEMINI[cfgmod.MODELO_GEMINI]
    assert set(get_args(pref.Proveedor)) == set(cfgmod.CATALOGO) < set(get_args(LLMConfig.model_fields["proveedor"].annotation))
    assert 1 <= LLMConfig().max_tokens <= pref.MAX_TOKENS
    assert 0 <= LLMConfig().max_retries <= pref.MAX_REINTENTOS


def test_openapi_documenta_los_endpoints_de_ia(cliente):
    spec = cliente.get("/openapi.json").json()
    ruta = spec["paths"]["/api/ia"]
    assert set(ruta) == {"get", "put"}
    assert ruta["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/IAEstado")
    assert ruta["put"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/Preferencias")
    assert ruta["put"]["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/IAErrores")
