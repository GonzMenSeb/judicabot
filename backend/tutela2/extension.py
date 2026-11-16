from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Literal, NamedTuple

from fastapi import WebSocket

from tutela2.citas import BASE_RELATORIA

log = logging.getLogger("tutela2.extension")

ESPERA_S = 120.0
ESPERA_HOLA_S = 10.0
CIERRE_SIN_RESPUESTA = 4408

CARPETA = Path(__file__).resolve().parents[2] / "extension"
RAIZ_ZIP = "judicabot-relatoria"
_FUERA_DEL_ZIP = {"pruebas", "package.json"}
_IGNORADOS = {"__pycache__", "node_modules"}


class Entrega(NamedTuple):
    estado: Literal["ok", "no_conectada", "sin_respuesta", "rechazo"]
    cuerpo: bytes | None = None
    detalle: str = ""


NO_CONECTADA = Entrega("no_conectada", None, "la extensión de judicabot no estaba conectada")
VENCIDA = Entrega("sin_respuesta", None, "la extensión no respondió a tiempo")
DESCONECTADA = Entrega("sin_respuesta", None, "la extensión se desconectó")


@dataclass(eq=False)
class _Conexion:
    socket: WebSocket
    bucle: asyncio.AbstractEventLoop
    envios: asyncio.Lock = field(default_factory=asyncio.Lock)
    pendientes: dict[str, concurrent.futures.Future[Entrega]] = field(default_factory=dict)

    async def pedir(self, id_: str, url: str) -> None:
        async with self.envios:
            await self.socket.send_json({"tipo": "pedido", "id": id_, "url": url})

    async def cerrar(self, codigo: int) -> None:
        async with self.envios:
            await self.socket.close(codigo)

    def recibir(self, datos: bytes) -> None:
        cabecera, _, cuerpo = datos.partition(b"\n")
        try:
            meta = json.loads(cabecera)
            id_, codigo, detalle = meta["id"], meta["codigo"], meta.get("detalle") or ""
            with _candado:
                futuro = self.pendientes.pop(id_, None)
        except (ValueError, KeyError, TypeError, RecursionError):
            log.warning("Se descartó una entrega ilegible de la extensión")
            return
        if futuro is None:
            log.info("Se descartó la entrega tardía %s de la extensión", id_)
        elif not futuro.done():
            futuro.set_result(_entrega(codigo, cuerpo, str(detalle)))


_conexiones: list[_Conexion] = []
_candado = threading.Lock()


def _entrega(codigo: object, cuerpo: bytes, detalle: str) -> Entrega:
    if codigo == 200:
        return Entrega("ok", cuerpo, "")
    if codigo is None:
        return Entrega("sin_respuesta", None, detalle or "la extensión no pudo descargar la página")
    return Entrega("rechazo", None, f"HTTP {codigo}")


def conectada() -> bool:
    with _candado:
        return bool(_conexiones)


async def atender(socket: WebSocket, version: str) -> None:
    conexion = _Conexion(socket, asyncio.get_running_loop())
    with _candado:
        _conexiones.append(conexion)
    log.info("Extensión de la relatoría conectada (versión %s)", version)
    try:
        while True:
            mensaje = await socket.receive()
            if mensaje["type"] == "websocket.disconnect":
                break
            if mensaje.get("bytes") is not None:
                conexion.recibir(mensaje["bytes"])
    finally:
        with _candado:
            if conexion in _conexiones:
                _conexiones.remove(conexion)
            pendientes = list(conexion.pendientes.values())
            conexion.pendientes.clear()
        for futuro in pendientes:
            if not futuro.done():
                futuro.set_result(DESCONECTADA)
        log.info("Extensión de la relatoría desconectada (versión %s)", version)


def pedir_pagina(url: str, espera_s: float = ESPERA_S) -> Entrega:
    if not url.startswith(BASE_RELATORIA + "/"):
        raise ValueError(f"La extensión solo descarga páginas de la relatoría: {url}")
    with _candado:
        intentos = len(_conexiones)
    entrega = NO_CONECTADA
    for _ in range(intentos):
        siguiente = _pedir_a_la_ultima(url, espera_s)
        if siguiente is None:
            break
        entrega = siguiente
        if entrega is not DESCONECTADA and entrega is not VENCIDA:
            break
    return entrega


def _pedir_a_la_ultima(url: str, espera_s: float) -> Entrega | None:
    id_ = uuid.uuid4().hex
    futuro: concurrent.futures.Future[Entrega] = concurrent.futures.Future()
    with _candado:
        if not _conexiones:
            return None
        conexion = _conexiones[-1]
        conexion.pendientes[id_] = futuro
    asyncio.run_coroutine_threadsafe(conexion.pedir(id_, url), conexion.bucle)
    try:
        return futuro.result(timeout=espera_s)
    except concurrent.futures.TimeoutError:
        with _candado:
            vencido = conexion.pendientes.pop(id_, None) is not None
            if vencido and conexion in _conexiones:
                _conexiones.remove(conexion)
    if not vencido:
        return futuro.result()
    log.warning("La extensión no respondió a tiempo el pedido de %s; se cierra su conexión", url)
    asyncio.run_coroutine_threadsafe(conexion.cerrar(CIERRE_SIN_RESPUESTA), conexion.bucle)
    return VENCIDA


def _empaquetable(relativa: Path) -> bool:
    if relativa.parts[0] in _FUERA_DEL_ZIP:
        return False
    return not any(parte.startswith(".") or parte in _IGNORADOS for parte in relativa.parts)


def paquete() -> tuple[str, bytes]:
    carpeta = CARPETA
    version = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))["version"]
    archivos = sorted(
        relativa
        for ruta in carpeta.rglob("*")
        if ruta.is_file() and _empaquetable(relativa := ruta.relative_to(carpeta))
    )
    destino = BytesIO()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zip_:
        for relativa in archivos:
            zip_.write(carpeta / relativa, f"{RAIZ_ZIP}/{relativa.as_posix()}")
    return f"{RAIZ_ZIP}-{version}.zip", destino.getvalue()
