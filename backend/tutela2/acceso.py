from __future__ import annotations

import hashlib
import hmac
import os
import time
from html import escape
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "judicabot_acceso"
EXENTAS = {"/healthz"}
MAX_FALLOS = 5
VENTANA_S = 300
VIGENCIA_S = 30 * 24 * 3600

_fallos: dict[str, list[float]] = {}


def password() -> str:
    return os.environ.get("JUDICABOT_PASSWORD", "")


def _token(pw: str) -> str:
    return hmac.new(pw.encode(), b"judicabot-acceso", hashlib.sha256).hexdigest()


def _cliente(request: Request) -> str:
    reenviado = request.headers.get("x-forwarded-for")
    if reenviado:
        return reenviado.split(",")[-1].strip()
    return request.client.host if request.client else "desconocido"


def _bloqueado(cliente: str) -> bool:
    ahora = time.monotonic()
    recientes = [t for t in _fallos.get(cliente, []) if ahora - t < VENTANA_S]
    _fallos[cliente] = recientes
    return len(recientes) >= MAX_FALLOS


def _formulario(error: str = "", estado: int = 200) -> HTMLResponse:
    aviso = f'<p class="e">{escape(error)}</p>' if error else ""
    cuerpo = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>judicabot</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f4f2;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#fff;padding:2rem;border-radius:8px;box-shadow:0 1px 6px #0002;width:min(20rem,90vw)}}
h1{{font-size:1.2rem;margin:0 0 1rem}}
input,button{{width:100%;box-sizing:border-box;padding:.6rem;font-size:1rem;margin-top:.6rem}}
button{{cursor:pointer}}
.e{{color:#b00020;margin:.6rem 0 0}}
</style></head><body>
<form method="post" action="/login">
<h1>judicabot</h1>
<input type="password" name="password" placeholder="Contraseña" autofocus required>
{aviso}
<button type="submit">Entrar</button>
</form></body></html>"""
    return HTMLResponse(cuerpo, status_code=estado)


def _con_cookie(respuesta: Response, request: Request, pw: str) -> Response:
    seguro = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    respuesta.set_cookie(
        COOKIE, _token(pw), max_age=VIGENCIA_S, httponly=True, samesite="lax", secure=seguro
    )
    return respuesta


async def _login(request: Request, pw: str) -> Response:
    if request.method == "GET":
        return _formulario()
    cliente = _cliente(request)
    if _bloqueado(cliente):
        return _formulario("Demasiados intentos. Espere unos minutos.", 429)
    enviado = parse_qs((await request.body()).decode()).get("password", [""])[0]
    if hmac.compare_digest(enviado.encode(), pw.encode()):
        _fallos.pop(cliente, None)
        return _con_cookie(RedirectResponse("/", status_code=303), request, pw)
    _fallos.setdefault(cliente, []).append(time.monotonic())
    return _formulario("Contraseña incorrecta.", 401)


async def compuerta(request: Request, call_next) -> Response:
    pw = password()
    if not pw or request.url.path in EXENTAS:
        return await call_next(request)
    if request.url.path == "/login":
        return await _login(request, pw)
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), _token(pw)):
        return await call_next(request)
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "No autenticado"}, status_code=401)
    return RedirectResponse("/login", status_code=303)
