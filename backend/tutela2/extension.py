"""Puente con la extensión de judicabot instalada en un navegador en Colombia.

La extensión hace, desde ese navegador, consultas públicas que los servidores de la Corte Constitucional
y de la Rama Judicial no responden a este servidor. Solo hay dos servicios (`SERVICIOS`): las páginas de la
relatoría y el certificado de vigencia de la tarjeta profesional. Todo lo que se le manda se valida aquí
antes de enviarlo (la extensión lo vuelve a validar con su propia lista), y a una extensión anterior a la
versión que exige un servicio no se le manda nada de ese servicio.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import threading
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Literal, NamedTuple
from urllib.parse import urlencode

from fastapi import WebSocket

from tutela2.citas import BASE_RELATORIA

log = logging.getLogger("tutela2.extension")

ESPERA_S = 120.0
ESPERA_VIGENCIA_S = 75.0
ESPERA_HOLA_S = 10.0
CIERRE_SIN_RESPUESTA = 4408

URL_VIGENCIA = "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx"
MAX_TIPO = 200

CARPETA = Path(__file__).resolve().parents[2] / "extension"
RAIZ_ZIP = "judicabot-relatoria"
_FUERA_DEL_ZIP = {"pruebas", "package.json"}
_IGNORADOS = {"__pycache__", "node_modules"}

Version = tuple[int, int, int, int]
EstadoConexion = Literal["conectada", "desactualizada", "no_conectada"]


class Entrega(NamedTuple):
    estado: Literal["ok", "no_conectada", "sin_respuesta", "rechazo"]
    cuerpo: bytes | None = None
    detalle: str = ""
    codigo: int | None = None
    tipo: str | None = None


NO_CONECTADA = Entrega("no_conectada", None, "la extensión de judicabot no estaba conectada")
DESACTUALIZADA = Entrega("no_conectada", None, "la extensión de judicabot conectada está desactualizada")
VENCIDA = Entrega("sin_respuesta", None, "la extensión no respondió a tiempo")
DESCONECTADA = Entrega("sin_respuesta", None, "la extensión se desconectó")


class ExtensionNoConectada(RuntimeError):
    """No había ninguna extensión conectada: no se envió nada."""


class ExtensionDesactualizada(RuntimeError):
    """Las extensiones conectadas son anteriores a la versión que exige el servicio: no se envió nada."""


def _version(texto: str) -> Version:
    """«1.1.0» → (1, 1, 0, 0). Lo que no sea una versión de extensión (1 a 4 números) vale (0, 0, 0, 0)."""
    partes = texto.strip().split(".")
    if not 1 <= len(partes) <= 4 or not all(p.isascii() and p.isdigit() and len(p) <= 6 for p in partes):
        return (0, 0, 0, 0)
    numeros = [int(p) for p in partes] + [0] * (4 - len(partes))
    return (numeros[0], numeros[1], numeros[2], numeros[3])


def _texto_version(version: Version) -> str:
    return ".".join(map(str, version[:3] if version[3] == 0 else version)) if any(version) else "desconocida"


@dataclass(frozen=True, eq=False)
class Servicio:
    """Una consulta pública que la extensión puede hacer: a qué direcciones, con qué métodos y desde qué versión."""

    nombre: str
    metodos: frozenset[str]
    version_minima: Version
    prefijo: str | None = None
    url: str | None = None
    campos: Mapping[str, re.Pattern[str]] = field(default_factory=lambda: MappingProxyType({}))
    max_cuerpo: int = 0
    reintentar: bool = False

    def admite(self, url: str) -> bool:
        if self.url is not None:
            return url == self.url
        return self.prefijo is not None and url.startswith(self.prefijo)


CAMPOS_VIGENCIA: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        "__VIEWSTATE": re.compile(r"[A-Za-z0-9+/=]{1,100000}"),
        "__VIEWSTATEGENERATOR": re.compile(r"[0-9A-F]{8}"),
        "__EVENTVALIDATION": re.compile(r"[A-Za-z0-9+/=]{1,20000}"),
        "ddlCalidad": re.compile(r"1"),
        "ddlTipoDocumento": re.compile(r"1"),
        "txtDocumento": re.compile(r"[0-9]{5,10}"),
        "btnTpVigente": re.compile(r"Generar"),
    }
)
"""El único formulario que sale hacia la Rama Judicial: los tres campos ocultos de la página, abogado
(`ddlCalidad=1`), cédula de ciudadanía (`ddlTipoDocumento=1`) y el número de cédula, nada más."""

SERVICIOS: Mapping[str, Servicio] = MappingProxyType(
    {
        "relatoria": Servicio(
            "relatoria", frozenset({"GET"}), _version("1.0.0"), prefijo=BASE_RELATORIA + "/", reintentar=True
        ),
        "vigencia": Servicio(
            "vigencia",
            frozenset({"GET", "POST"}),
            _version("1.1.0"),
            url=URL_VIGENCIA,
            campos=CAMPOS_VIGENCIA,
            max_cuerpo=256_000,
        ),
    }
)


def _validar(nombre: str, url: str, metodo: str, formulario: Mapping[str, str] | None) -> Servicio:
    """La lista de lo permitido, del lado del servidor. Los mensajes de error nunca repiten valores del
    formulario: el número de cédula no debe quedar en ningún registro."""
    servicio = SERVICIOS.get(nombre)
    if servicio is None:
        raise ValueError(f"La extensión no tiene el servicio «{nombre}».")
    if not isinstance(url, str) or not servicio.admite(url):
        if nombre == "relatoria":
            raise ValueError(f"La extensión solo descarga páginas de la relatoría: {url}")
        raise ValueError(f"La extensión solo consulta la vigencia en {URL_VIGENCIA}.")
    if metodo not in servicio.metodos:
        raise ValueError(f"El servicio «{nombre}» de la extensión no admite ese método.")
    if metodo == "GET":
        if formulario is not None:
            raise ValueError("Un pedido GET a la extensión no lleva formulario.")
        return servicio
    if not isinstance(formulario, dict) or set(formulario) != set(servicio.campos):
        raise ValueError(
            f"El formulario de «{nombre}» debe traer exactamente los campos {', '.join(servicio.campos)}."
        )
    for campo, patron in servicio.campos.items():
        valor = formulario[campo]
        if not isinstance(valor, str) or patron.fullmatch(valor) is None:
            raise ValueError(f"El campo {campo} del formulario de «{nombre}» no es válido.")
    if len(urlencode(formulario)) > servicio.max_cuerpo:
        raise ValueError(f"El formulario de «{nombre}» supera {servicio.max_cuerpo} bytes.")
    return servicio


def _mensaje(servicio: Servicio, url: str, metodo: str, formulario: Mapping[str, str] | None) -> dict:
    """Sin el id. La relatoría conserva el mensaje de la versión 1.0.0, `{tipo, id, url}`."""
    if servicio.nombre == "relatoria":
        return {"tipo": "pedido", "url": url}
    ordenado = None if formulario is None else {campo: formulario[campo] for campo in servicio.campos}
    return {"tipo": "pedir", "servicio": servicio.nombre, "url": url, "metodo": metodo, "formulario": ordenado}


@dataclass(eq=False)
class _Conexion:
    socket: WebSocket
    bucle: asyncio.AbstractEventLoop
    version: Version = (0, 0, 0, 0)
    envios: asyncio.Lock = field(default_factory=asyncio.Lock)
    pendientes: dict[str, concurrent.futures.Future[Entrega]] = field(default_factory=dict)

    def sirve(self, servicio: Servicio) -> bool:
        return self.version >= servicio.version_minima

    async def enviar(self, mensaje: dict) -> None:
        async with self.envios:
            await self.socket.send_json(mensaje)

    async def cerrar(self, codigo: int) -> None:
        async with self.envios:
            await self.socket.close(codigo)

    def recibir(self, datos: bytes) -> None:
        cabecera, _, cuerpo = datos.partition(b"\n")
        try:
            meta = json.loads(cabecera)
            id_, codigo, detalle = meta["id"], meta["codigo"], meta.get("detalle") or ""
            tipo = meta.get("tipo")
            with _candado:
                futuro = self.pendientes.pop(id_, None)
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            log.warning("Se descartó una entrega ilegible de la extensión")
            return
        if futuro is None:
            log.info("Se descartó la entrega tardía %s de la extensión", id_)
        elif not futuro.done():
            futuro.set_result(_entrega(codigo, cuerpo, str(detalle), tipo))


_conexiones: list[_Conexion] = []
_avisos: list[Callable[[], None]] = []
_candado = threading.Lock()


def _entrega(codigo: object, cuerpo: bytes, detalle: str, tipo: object = None) -> Entrega:
    numero = codigo if isinstance(codigo, int) and not isinstance(codigo, bool) else None
    contenido = tipo.strip()[:MAX_TIPO] if isinstance(tipo, str) else None
    if codigo == 200:
        return Entrega("ok", cuerpo, "", 200, contenido)
    if codigo is None:
        return Entrega("sin_respuesta", None, detalle or "la extensión no pudo descargar la página")
    return Entrega("rechazo", None, f"HTTP {codigo}", numero, contenido)


def conectada() -> bool:
    """Hay alguna extensión conectada, de cualquier versión."""
    with _candado:
        return bool(_conexiones)


def estado_conexion(servicio: str = "vigencia") -> EstadoConexion:
    """`conectada` si alguna extensión conectada hace ese servicio; `desactualizada` si las conectadas son
    anteriores a la versión que exige; `no_conectada` si no hay ninguna."""
    minima = SERVICIOS[servicio]
    with _candado:
        if any(c.sirve(minima) for c in _conexiones):
            return "conectada"
        return "desactualizada" if _conexiones else "no_conectada"


def al_conectar(fn: Callable[[], None]) -> Callable[[], None]:
    """Registra `fn` para que corra en un hilo aparte, fuera del bucle de eventos, cada vez que se conecta una
    extensión que consulta la vigencia (1.1.0 o más). Registrar dos veces la misma función no la duplica."""
    with _candado:
        if fn not in _avisos:
            _avisos.append(fn)
    return fn


def _avisar(funciones: list[Callable[[], None]]) -> None:
    for fn in funciones:
        try:
            fn()
        except Exception:
            log.exception("Falló un aviso de conexión de la extensión")


async def atender(socket: WebSocket, version: str) -> None:
    conexion = _Conexion(socket, asyncio.get_running_loop(), _version(version))
    with _candado:
        _conexiones.append(conexion)
        avisos = list(_avisos) if conexion.sirve(SERVICIOS["vigencia"]) else []
    etiqueta = _texto_version(conexion.version)
    log.info("Extensión de judicabot conectada (versión %s)", etiqueta)
    if avisos:
        threading.Thread(target=_avisar, args=(avisos,), name="extension-al-conectar", daemon=True).start()
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
        log.info("Extensión de judicabot desconectada (versión %s)", etiqueta)


def _sin_conexion(servicio: Servicio) -> RuntimeError:
    with _candado:
        hay = bool(_conexiones)
    if hay:
        return ExtensionDesactualizada(
            f"La extensión de judicabot conectada está desactualizada: el servicio «{servicio.nombre}» exige la "
            f"versión {_texto_version(servicio.version_minima)} o más."
        )
    return ExtensionNoConectada("La extensión de judicabot no estaba conectada.")


def pedir(
    servicio: str,
    url: str,
    metodo: str = "GET",
    formulario: dict[str, str] | None = None,
    espera_s: float = ESPERA_VIGENCIA_S,
) -> Entrega:
    """Pide a la extensión una consulta de `servicio` y espera su entrega. Se llama desde un hilo, nunca desde
    el bucle de eventos.

    Valida la dirección, el método y el formulario contra `SERVICIOS` antes de enviar (ValueError si no
    cumplen) y elige la extensión conectada más reciente que hace ese servicio. Sin ninguna conectada
    lanza ExtensionNoConectada; si las conectadas son anteriores a la versión mínima, ExtensionDesactualizada.
    En ambos casos no se envía nada. Si la extensión no entrega a tiempo se cierra su conexión (4408) y se
    lanza TimeoutError. La relatoría repite el pedido en otra extensión si la elegida se cae; la vigencia
    nunca lo repite, para no consultar dos veces seguidas a la Rama Judicial.
    """
    destino = _validar(servicio, url, metodo, formulario)
    mensaje = _mensaje(destino, url, metodo, formulario)
    with _candado:
        aptas = sum(c.sirve(destino) for c in _conexiones)
    if not aptas:
        raise _sin_conexion(destino)
    entrega: Entrega | None = None
    for _ in range(aptas if destino.reintentar else 1):
        siguiente = _pedir_a_la_ultima(destino, mensaje, espera_s)
        if siguiente is None:
            break
        entrega = siguiente
        if entrega is not DESCONECTADA and entrega is not VENCIDA:
            break
    if entrega is None:
        raise _sin_conexion(destino)
    if entrega is VENCIDA:
        raise TimeoutError(VENCIDA.detalle)
    return entrega


def pedir_pagina(url: str, espera_s: float = ESPERA_S) -> Entrega:
    """La consulta de la relatoría de siempre: nunca lanza por falta de extensión ni por tiempo agotado."""
    try:
        return pedir("relatoria", url, espera_s=espera_s)
    except ExtensionNoConectada:
        return NO_CONECTADA
    except ExtensionDesactualizada:
        return DESACTUALIZADA
    except TimeoutError:
        return VENCIDA


def _pedir_a_la_ultima(servicio: Servicio, mensaje: dict, espera_s: float) -> Entrega | None:
    id_ = uuid.uuid4().hex
    futuro: concurrent.futures.Future[Entrega] = concurrent.futures.Future()
    with _candado:
        conexion = next((c for c in reversed(_conexiones) if c.sirve(servicio)), None)
        if conexion is None:
            return None
        conexion.pendientes[id_] = futuro
    asyncio.run_coroutine_threadsafe(conexion.enviar({**mensaje, "id": id_}), conexion.bucle)
    try:
        return futuro.result(timeout=espera_s)
    except concurrent.futures.TimeoutError:
        with _candado:
            vencido = conexion.pendientes.pop(id_, None) is not None
            if vencido and conexion in _conexiones:
                _conexiones.remove(conexion)
    if not vencido:
        return futuro.result()
    log.warning(
        "La extensión no respondió a tiempo el pedido de %s (%s); se cierra su conexión",
        mensaje["url"],
        servicio.nombre,
    )
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
