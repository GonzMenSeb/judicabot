from __future__ import annotations

import os
import shutil

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from tutela2 import acceso, estaticos, server

SHELL = "<!doctype html><title>Nueva shell</title><div id=app></div>" + "<!-- relleno -->" * 40
JS = "console.log('hola');\n" * 200
HASH_JS = "/assets/app-abc123.js"
FORM = {"content-type": "application/x-www-form-urlencoded"}


@pytest.fixture
def estaticos_tmp(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "dist" / "assets").mkdir(parents=True)
    (static / "dist" / "index.html").write_text(SHELL, encoding="utf-8")
    (static / "dist" / "assets" / "app-abc123.js").write_text(JS, encoding="utf-8")
    (static / "dist" / "assets" / "fuente-abc123.woff2").write_bytes(os.urandom(3000))
    (static / "dist" / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'>" + " " * 600 + "</svg>")
    (tmp_path / "secreto.txt").write_text("secreto", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC", static)
    return static


@pytest.fixture
def cliente(estaticos_tmp, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    return TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)


@pytest.fixture
def cliente_sin_dist_factory(estaticos_tmp, cliente):
    def quitar() -> TestClient:
        shutil.rmtree(estaticos_tmp / "dist", ignore_errors=True)
        return cliente

    return quitar


@pytest.fixture
def cliente_sin_dist(cliente_sin_dist_factory) -> TestClient:
    return cliente_sin_dist_factory()


def test_comprime_con_gzip_si_el_cliente_lo_acepta(cliente):
    r = cliente.get(HASH_JS, headers={"accept-encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    assert r.text == JS


def test_no_comprime_sin_accept_encoding(cliente):
    r = cliente.get(HASH_JS, headers={"accept-encoding": "identity"})
    assert "content-encoding" not in r.headers
    assert int(r.headers["content-length"]) == len(JS.encode())


def test_no_comprime_respuestas_pequenas(cliente):
    r = cliente.get("/healthz", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers


def test_no_comprime_binarios_ya_comprimidos(cliente, tmp_path):
    r = cliente.get("/assets/fuente-abc123.woff2", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers

    docx = tmp_path / "casos" / "c1" / "salidas" / "fallo.docx"
    docx.parent.mkdir(parents=True)
    docx.write_bytes(os.urandom(4000))
    r = cliente.get("/api/casos/c1/salidas/fallo.docx", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers
    assert r.headers["content-type"] == server.DOCX


def test_assets_con_hash_son_inmutables(cliente):
    r = cliente.get(HASH_JS)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    r304 = cliente.get(HASH_JS, headers={"if-none-match": r.headers["etag"]})
    assert r304.status_code == 304
    assert r304.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_asset_inexistente_no_queda_en_cache(cliente):
    r = cliente.get("/assets/no-existe-abc123.js")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("ruta", ["/", "/segunda/caso-1/fallo", "/favicon.svg"])
def test_index_y_resto_de_estaticos_van_sin_cache(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_csp_solo_en_respuestas_html(cliente):
    csp = estaticos.CSP
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert cliente.get("/").headers["content-security-policy"] == csp
    assert cliente.get("/segunda/caso-1/fallo").headers["content-security-policy"] == csp
    assert "content-security-policy" not in cliente.get("/api/config-default").headers
    assert "content-security-policy" not in cliente.get(HASH_JS).headers
    assert "content-security-policy" not in cliente.get("/docs").headers


def test_la_raiz_sirve_la_shell_nueva_cuando_hay_dist(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "Nueva shell" in r.text
    assert cliente.head("/").status_code == 200


def test_fallback_spa_para_rutas_sin_archivo(cliente):
    assert "Nueva shell" in cliente.get("/segunda/caso-1/fallo").text
    assert "Nueva shell" in cliente.get("/formato").text


def test_sirve_los_archivos_de_la_raiz_de_dist(cliente):
    r = cliente.get("/favicon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


def test_el_fallback_no_traga_api_assets_ni_archivos_inexistentes(cliente):
    r = cliente.get("/api/no-existe")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert cliente.get("/assets/no-existe-abc123.js").status_code == 404
    assert cliente.get("/no-existe.js").status_code == 404


def test_el_fallback_no_sale_de_dist(cliente):
    r = cliente.get("/%2e%2e%2fsecreto.txt")
    assert r.status_code == 404 and "secreto" not in r.text
    r = cliente.get("/%2e%2e/secreto")
    assert "secreto" not in r.text


@pytest.fixture
def router_tardio():
    router = APIRouter()
    router.get("/api/ruta-tardia")(lambda: {"ok": True})
    router.post("/api/ruta-tardia")(lambda: {"ok": True})
    rutas = list(server.app.router.routes)
    server.app.include_router(router)
    yield
    server.app.router.routes[:] = rutas


def test_los_routers_agregados_despues_siguen_respondiendo(cliente, cliente_sin_dist_factory, router_tardio):
    assert cliente.get("/api/ruta-tardia").json() == {"ok": True}
    assert cliente.post("/api/ruta-tardia").json() == {"ok": True}
    assert cliente_sin_dist_factory().get("/api/ruta-tardia").json() == {"ok": True}


def test_post_a_una_ruta_desconocida_sigue_dando_404(cliente):
    assert cliente.post("/api/no-existe").status_code == 404
    assert cliente.post("/no-existe").status_code == 404


def test_la_api_sigue_respondiendo(cliente):
    assert cliente.get("/api/casos").status_code == 200
    assert cliente.get("/api/config-default").status_code == 200


def test_sin_dist_la_raiz_da_503_con_mensaje_claro(cliente_sin_dist):
    for r in (cliente_sin_dist.get("/"), cliente_sin_dist.head("/")):
        assert r.status_code == 503
        assert r.headers["cache-control"] == "no-cache"
    r = cliente_sin_dist.get("/")
    assert "text/plain" in r.headers["content-type"]
    assert r.text == "Falta compilar el frontend (pnpm build)."


def test_sin_dist_no_hay_assets_ni_fallback(cliente_sin_dist):
    assert cliente_sin_dist.get(HASH_JS).status_code == 404
    assert cliente_sin_dist.get("/segunda/caso-1/fallo").status_code == 404
    assert cliente_sin_dist.get("/api/casos").status_code == 200


def test_dist_no_se_expone_bajo_static(cliente):
    assert cliente.get("/static/dist/index.html").status_code == 404
    assert cliente.get("/static/app.js").status_code == 404


@pytest.fixture
def cliente_con_clave(estaticos_tmp, monkeypatch) -> TestClient:
    monkeypatch.setenv("JUDICABOT_PASSWORD", "clave-de-prueba")
    acceso._fallos.clear()
    return TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)


@pytest.mark.parametrize("ruta", ["/", "/segunda/caso-1/fallo", HASH_JS, "/favicon.svg"])
def test_con_clave_la_shell_y_los_assets_exigen_acceso(cliente_con_clave, ruta):
    r = cliente_con_clave.get(ruta)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_con_clave_la_pantalla_de_acceso_sigue_funcionando(cliente_con_clave):
    r = cliente_con_clave.get("/login")
    assert r.status_code == 200 and 'name="password"' in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-security-policy"] == estaticos.CSP

    mal = cliente_con_clave.post("/login", content="password=otra", headers=FORM)
    assert mal.status_code == 401 and 'name="password"' in mal.text

    ok = cliente_con_clave.post("/login", content="password=clave-de-prueba", headers=FORM)
    assert ok.status_code == 303 and ok.headers["location"] == "/"


def test_con_clave_tras_entrar_se_sirven_shell_y_assets(cliente_con_clave):
    cliente_con_clave.post("/login", content="password=clave-de-prueba", headers=FORM)
    assert "Nueva shell" in cliente_con_clave.get("/").text
    r = cliente_con_clave.get(HASH_JS)
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert cliente_con_clave.get("/healthz").status_code == 200


def test_con_clave_y_sin_dist_el_login_funciona_y_la_raiz_avisa(cliente_con_clave, estaticos_tmp):
    shutil.rmtree(estaticos_tmp / "dist")
    assert 'name="password"' in cliente_con_clave.get("/login").text
    ok = cliente_con_clave.post("/login", content="password=clave-de-prueba", headers=FORM)
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    r = cliente_con_clave.get("/")
    assert r.status_code == 503 and "pnpm build" in r.text
