from __future__ import annotations

import asyncio
import hmac
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tutela2 import acceso, extension

router = APIRouter()

CIERRE_RECHAZADA = 4401
CIERRE_BLOQUEADA = 4429


def _rechazo(socket: WebSocket, hola: object, pw: str) -> int | None:
    if not isinstance(hola, dict) or hola.get("tipo") != "hola":
        return CIERRE_RECHAZADA
    if not pw:
        return None
    ficha, contrasena = hola.get("ficha"), hola.get("contrasena")
    if isinstance(ficha, str) and hmac.compare_digest(ficha.encode(), acceso.ficha_extension(pw).encode()):
        return None
    if not isinstance(contrasena, str):
        return CIERRE_RECHAZADA
    resultado = acceso.verificar_contrasena(acceso._cliente(socket), contrasena, pw)
    return {"ok": None, "mal": CIERRE_RECHAZADA, "bloqueado": CIERRE_BLOQUEADA}[resultado]


@router.websocket("/api/extension")
async def socket_extension(socket: WebSocket) -> None:
    await socket.accept()
    try:
        hola = json.loads(await asyncio.wait_for(socket.receive_text(), extension.ESPERA_HOLA_S))
    except WebSocketDisconnect:
        return
    except (TimeoutError, ValueError, KeyError):
        hola = None
    pw = acceso.password()
    codigo = _rechazo(socket, hola, pw)
    if codigo is not None:
        await socket.close(codigo)
        return
    await socket.send_json({"tipo": "listo", "ficha": acceso.ficha_extension(pw) if pw else ""})
    await extension.atender(socket, str(hola.get("version", "")))
