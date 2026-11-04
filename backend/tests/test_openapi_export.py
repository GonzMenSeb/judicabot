from __future__ import annotations

import json

from tutela2 import openapi_export


def test_la_exportacion_es_estable_y_valida():
    primera = openapi_export.generar()
    assert primera == openapi_export.generar()
    esquema = json.loads(primera)
    assert esquema["openapi"].startswith("3.") and "/api/casos" in esquema["paths"]
    assert "/" not in esquema["paths"] and "/{ruta}" not in esquema["paths"]
    assert primera.endswith("}\n")


def test_escribe_en_el_destino(tmp_path, monkeypatch):
    destino = tmp_path / "frontend" / "openapi.json"
    monkeypatch.setattr(openapi_export, "DESTINO", destino)
    openapi_export.main()
    assert destino.read_text(encoding="utf-8") == openapi_export.generar()


def test_openapi_json_versionado_esta_al_dia():
    actual = openapi_export.DESTINO.read_text(encoding="utf-8")
    assert actual == openapi_export.generar(), "frontend/openapi.json desactualizado: ejecute `pnpm gen:tipos` en frontend/"
