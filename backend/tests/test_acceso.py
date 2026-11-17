from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tutela2 import acceso, server


@pytest.fixture
def cliente(monkeypatch) -> TestClient:
    monkeypatch.setenv("JUDICABOT_PASSWORD", "clave-de-prueba")
    acceso._fallos.clear()
    return TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)


def test_sin_cookie_redirige_al_login(cliente):
    r = cliente.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_api_sin_cookie_da_401(cliente):
    assert cliente.get("/api/config-default").status_code == 401


def test_healthz_no_exige_contrasena(cliente):
    assert cliente.get("/healthz").status_code == 200


def test_healthz_informa_la_revision_solo_si_la_imagen_la_trae(cliente, monkeypatch):
    monkeypatch.delenv("JUDICABOT_REVISION", raising=False)
    assert cliente.get("/healthz").json() == {"status": "ok"}
    monkeypatch.setenv("JUDICABOT_REVISION", "abc1234")
    assert cliente.get("/healthz").json() == {"status": "ok", "revision": "abc1234"}


def test_login_correcto_da_acceso(cliente):
    r = cliente.post("/login", content="password=clave-de-prueba", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 303 and acceso.COOKIE in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]
    assert cliente.get("/api/config-default").status_code == 200


def test_login_incorrecto_no_da_cookie(cliente):
    r = cliente.post("/login", content="password=otra", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_bloqueo_tras_demasiados_fallos(cliente):
    cabeceras = {"content-type": "application/x-www-form-urlencoded"}
    for _ in range(acceso.MAX_FALLOS):
        cliente.post("/login", content="password=x", headers=cabeceras)
    r = cliente.post("/login", content="password=clave-de-prueba", headers=cabeceras)
    assert r.status_code == 429


def test_cambiar_la_contrasena_invalida_las_cookies(cliente, monkeypatch):
    cliente.post("/login", content="password=clave-de-prueba", headers={"content-type": "application/x-www-form-urlencoded"})
    monkeypatch.setenv("JUDICABOT_PASSWORD", "nueva")
    assert cliente.get("/api/config-default").status_code == 401


def test_sin_contrasena_configurada_no_hay_compuerta(monkeypatch):
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    c = TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)
    assert c.get("/api/config-default").status_code == 200


def test_eliminar_y_restaurar_sin_cookie_dan_401(cliente, tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path))
    (tmp_path / "caso").mkdir()
    (tmp_path / ".papelera" / "otro@20261117T150000000000Z").mkdir(parents=True)
    assert cliente.delete("/api/casos/caso").status_code == 401
    assert cliente.post("/api/papelera/otro@20261117T150000000000Z/restaurar").status_code == 401
    assert (tmp_path / "caso").is_dir() and not (tmp_path / "otro").exists()
    cliente.post("/login", content="password=clave-de-prueba", headers={"content-type": "application/x-www-form-urlencoded"})
    assert cliente.delete("/api/casos/caso").status_code == 200
    assert cliente.post("/api/papelera/otro@20261117T150000000000Z/restaurar").status_code == 200
    assert not (tmp_path / "caso").exists() and (tmp_path / "otro").is_dir()
