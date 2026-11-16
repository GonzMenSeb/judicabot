from __future__ import annotations

import asyncio
import hmac
import json

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect

from tutela2 import acceso, citas, extension
from tutela2.config import Config

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
    if socket.headers.get("origin", "").startswith(("http://", "https://")):
        await socket.close(CIERRE_RECHAZADA)
        return
    try:
        hola = json.loads(await asyncio.wait_for(socket.receive_text(), extension.ESPERA_HOLA_S))
    except WebSocketDisconnect:
        return
    except (TimeoutError, ValueError, KeyError, RecursionError):
        hola = None
    pw = acceso.password()
    codigo = _rechazo(socket, hola, pw)
    if codigo is not None:
        await socket.close(codigo)
        return
    await socket.send_json({"tipo": "listo", "ficha": acceso.ficha_extension(pw) if pw else ""})
    await extension.atender(socket, str(hola.get("version", "")))


@router.get("/api/relatoria", include_in_schema=False)
def consulta_relatoria(sentencia: str) -> dict:
    partes = citas.normalizar_sentencia(sentencia)
    if partes is None:
        raise HTTPException(422, f"No se pudo interpretar la sentencia «{sentencia}».")
    url = citas.url_relatoria(*partes)
    relatoria = citas.consultar_relatoria(url, Config())
    return {
        "sentencia": citas.clave_dataset(*partes),
        "url": url,
        "estado": relatoria.estado,
        "detalle": relatoria.detalle,
        "extension": relatoria.extension,
        "caracteres": len(relatoria.texto) if relatoria.texto is not None else None,
        "extension_conectada": extension.conectada(),
    }


@router.get("/api/extension/zip")
def descargar_extension() -> Response:
    try:
        nombre, contenido = extension.paquete()
    except FileNotFoundError:
        raise HTTPException(404, "La extensión no está disponible en este servidor.") from None
    return Response(
        contenido,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
