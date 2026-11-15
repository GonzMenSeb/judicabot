from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from tutela2 import acceso, rutas_dataset, server
from tutela2.config import Config

CSV = (
    '"proceso","expediente_tipo","expediente_numero","magistrado_a","sala","sentencia_tipo","sentencia",'
    '"fecha_sentencia","sv_spv","av_apv"\n'
    '"Tutela","T","1","José Fernando Reyes Cuartas","Salas de Revisión","T","T-200/22","2022-06-06T00:00:00.000","s.d.","s.d."\n'
).encode("utf-8")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTELA2_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache" / "cc_sentencias.csv"


@pytest.fixture
def cliente(cache) -> TestClient:
    return TestClient(server.app, base_url="http://127.0.0.1")


def _subir(cliente: TestClient, contenido: bytes):
    return cliente.put("/api/dataset", files={"archivo": ("cc_sentencias.csv", contenido, "text/csv")})


def test_estado_sin_copia_local_pide_al_navegador_la_descarga(cliente):
    r = cliente.get("/api/dataset")
    assert r.status_code == 200
    assert r.json() == {"vigente": False, "url": Config().dataset_csv_url}
    assert r.json()["url"].startswith("https://www.datos.gov.co/")


def test_subir_el_dataset_lo_deja_vigente_y_sin_descarga_del_servidor(cliente, cache):
    r = _subir(cliente, CSV)
    assert r.status_code == 204 and r.content == b""
    assert cache.read_bytes() == CSV
    assert cliente.get("/api/dataset").json()["vigente"] is True


def test_subir_el_dataset_renueva_una_copia_vieja(cliente, cache):
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"viejo")
    viejo = time.time() - 40 * 24 * 3600
    os.utime(cache, (viejo, viejo))
    assert cliente.get("/api/dataset").json()["vigente"] is False
    assert _subir(cliente, CSV).status_code == 204
    assert cliente.get("/api/dataset").json()["vigente"] is True


@pytest.mark.parametrize(
    "basura", [b"", b"<html>Servicio no disponible</html>", b"\xff\xfe\x00", CSV.replace(b'"sentencia"', b'"otra"')]
)
def test_un_archivo_que_no_es_el_dataset_se_rechaza_y_no_pisa_la_copia(cliente, cache, basura):
    cache.parent.mkdir(parents=True)
    cache.write_bytes(CSV)
    r = _subir(cliente, basura)
    assert r.status_code == 422 and "no es el dataset" in r.json()["detail"]
    assert cache.read_bytes() == CSV


def test_un_archivo_demasiado_grande_se_rechaza(cliente, cache, monkeypatch):
    monkeypatch.setattr(rutas_dataset, "MAX_BYTES_DATASET", len(CSV) - 1)
    r = _subir(cliente, CSV)
    assert r.status_code == 413
    assert not cache.exists()


def test_sin_archivo_da_422(cliente):
    assert cliente.put("/api/dataset").status_code == 422


def test_la_contrasena_tambien_protege_el_dataset(cache, monkeypatch):
    monkeypatch.setenv("JUDICABOT_PASSWORD", "clave-de-prueba")
    acceso._fallos.clear()
    c = TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)
    assert c.get("/api/dataset").status_code == 401
    assert _subir(c, CSV).status_code == 401
    assert not cache.exists()
