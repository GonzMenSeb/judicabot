from __future__ import annotations

from tutela2 import config as cfgmod


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
