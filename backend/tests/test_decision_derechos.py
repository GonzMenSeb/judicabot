from __future__ import annotations

import json

import pytest
from langgraph.types import Command

import test_graph
from test_graph import DECISION, arrancar
from tutela2.config import Config, LLMConfig

verificador = test_graph.verificador


@pytest.fixture
def cfg() -> Config:
    return Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)


DERECHOS = [
    {"derecho": "salud", "disposicion": "AMPARA"},
    {"derecho": "vida", "disposicion": "AMPARA"},
]


def seccion_decision(cliente) -> dict:
    user = [u for n, u in cliente.llamadas if n == "caso_concreto"][0]
    return json.loads(user.split("=== DECISION ===\n")[1].split("\n=== ")[0])


def correr(cfg, tmp_path, **cambios) -> dict:
    g, h, cliente = arrancar(cfg, tmp_path)
    g.invoke(Command(resume={**DECISION, "derechos": DERECHOS, **cambios}), h, durability="sync")
    return seccion_decision(cliente)


@pytest.mark.parametrize("sustitutiva", ["AMPARAR", "NEGAR"])
def test_derechos_viajan_si_amparar_o_negar(cfg, tmp_path, sustitutiva):
    extra = {} if sustitutiva == "AMPARAR" else {"ordenes": []}
    dec = correr(cfg, tmp_path, sustitutiva=sustitutiva, **extra)
    assert [d["derecho"] for d in dec["derechos"]] == ["salud", "vida"]


def test_derechos_no_viajan_si_confirmar(cfg, tmp_path):
    dec = correr(cfg, tmp_path, resultado="CONFIRMAR", sustitutiva=None, ordenes=[])
    assert "derechos" not in dec
    assert dec["resultado"] == "CONFIRMAR"


@pytest.mark.parametrize("sustitutiva", ["IMPROCEDENTE", "CARENCIA_HECHO_SUPERADO"])
def test_derechos_no_viajan_en_otras_sustitutivas(cfg, tmp_path, sustitutiva):
    dec = correr(cfg, tmp_path, sustitutiva=sustitutiva, ordenes=[])
    assert "derechos" not in dec
