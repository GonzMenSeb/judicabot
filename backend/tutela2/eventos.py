from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Callable

MAX_EVENTOS = 2000
MAX_TEXTO = 2000
MAX_DATOS = 8000
ETAPAS = ("ingesta", "apertura", "consideraciones", "verificacion", "caso_concreto", "documentos", "sistema")
TIPOS = ("lee", "razona", "escribe", "verifica", "sistema", "error")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Buffer:
    def __init__(self, maximo: int = MAX_EVENTOS) -> None:
        self.maximo = maximo
        self.inicio = time.monotonic()
        self._eventos: deque[dict[str, Any]] = deque()
        self._n = 0
        self._t_descarte: str | None = None
        self._fin: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._despertadores: set[Callable[[], None]] = set()

    def agregar(self, etapa: str, tipo: str, texto: str, datos: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock:
            if self._fin is not None:
                return None
            self._n += 1
            evento = {"n": self._n, "t": _ahora(), "etapa": etapa, "tipo": tipo, "texto": texto, "datos": datos}
            self._eventos.append(evento)
            if len(self._eventos) > self.maximo:
                self._t_descarte = self._eventos.popleft()["t"]
            despertadores = list(self._despertadores)
        _despertar(despertadores)
        return evento

    def cerrar(self, estado: str, error: str | None) -> None:
        with self._lock:
            if self._fin is not None:
                return
            self._fin = {"estado": estado, "error": error}
            despertadores = list(self._despertadores)
        _despertar(despertadores)

    def leer(self, desde: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        with self._lock:
            return self._desde(max(desde, 0)), self._fin

    def _desde(self, desde: int) -> list[dict[str, Any]]:
        if desde >= self._n or not self._eventos:
            return []
        primero = self._eventos[0]["n"]
        if desde >= primero - 1:
            return list(islice(self._eventos, desde - primero + 1, None))
        omitidos = primero - 1 - desde
        aviso = {
            "n": primero - 1,
            "t": self._t_descarte,
            "etapa": "sistema",
            "tipo": "sistema",
            "texto": f"Se omiten {omitidos} eventos anteriores: cada proceso conserva solo los últimos {self.maximo}.",
            "datos": {"omitidos": omitidos, "limite": self.maximo},
        }
        return [aviso, *self._eventos]

    async def esperar(self, desde: int, timeout: float) -> bool:
        loop = asyncio.get_running_loop()
        senal = asyncio.Event()

        def despertar() -> None:
            try:
                loop.call_soon_threadsafe(senal.set)
            except RuntimeError:
                pass

        with self._lock:
            if self._n > desde or self._fin is not None:
                return True
            self._despertadores.add(despertar)
        try:
            await asyncio.wait_for(senal.wait(), timeout)
            return True
        except TimeoutError:
            return False
        finally:
            with self._lock:
                self._despertadores.discard(despertar)

    def lectores(self) -> int:
        with self._lock:
            return len(self._despertadores)


def _despertar(despertadores: list[Callable[[], None]]) -> None:
    for despertar in despertadores:
        try:
            despertar()
        except Exception:
            pass


_ACTUAL: ContextVar[Buffer | None] = ContextVar("eventos_job", default=None)
_REGISTRO: dict[str, Buffer] = {}


def crear(job_id: str) -> Buffer:
    buffer = _REGISTRO[job_id] = Buffer()
    return buffer


def buffer(job_id: str) -> Buffer | None:
    return _REGISTRO.get(job_id)


def olvidar(job_id: str) -> None:
    _REGISTRO.pop(job_id, None)


def activar(buffer: Buffer) -> Token:
    return _ACTUAL.set(buffer)


def desactivar(token: Token) -> None:
    _ACTUAL.reset(token)


def _datos(datos: Any) -> dict[str, Any] | None:
    if datos is None:
        return None
    serializado = json.dumps(datos, ensure_ascii=False, default=str)
    if len(serializado) > MAX_DATOS:
        return {"truncado": True, "caracteres": len(serializado)}
    limpio = json.loads(serializado)
    return limpio if isinstance(limpio, dict) else {"valor": limpio}


def emitir(etapa: str, tipo: str, texto: str, datos: Any = None) -> None:
    buffer = _ACTUAL.get()
    if buffer is None:
        return
    try:
        buffer.agregar(
            etapa if etapa in ETAPAS else "sistema",
            tipo if tipo in TIPOS else "sistema",
            str(texto)[:MAX_TEXTO],
            _datos(datos),
        )
    except Exception:
        pass


def finalizar(buffer: Buffer, cmd: str, estado: str, error: str | None) -> None:
    try:
        segundos = round(time.monotonic() - buffer.inicio, 1)
        if estado == "error":
            buffer.agregar("sistema", "error", str(error or "La operación falló.")[:MAX_TEXTO], {"cmd": cmd, "segundos": segundos})
        else:
            buffer.agregar("sistema", "sistema", f"«{cmd}» terminó en {segundos} s.", {"cmd": cmd, "segundos": segundos})
    finally:
        buffer.cerrar(estado, error)
