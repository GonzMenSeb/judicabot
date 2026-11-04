from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from tutela2.config import Config
from tutela2.models import LlamadaIA

MAX_CHARS_ERROR = 300
CLAVE_VALIDA = re.compile(r"[\x21-\x7e]+")


class ErrorJev(Exception):
    def __init__(self, mensaje: str = "", enviada: bool = False, reintentable: bool = True) -> None:
        super().__init__(mensaje)
        self.enviada = enviada
        self.reintentable = reintentable


@dataclass
class RespuestaJev:
    modelo: str
    respuestas: dict[str, dict]
    tokens_entrada: int
    tokens_salida: int


class JevClient(Protocol):
    def preguntar(self, estado: str | dict, preguntas: dict[str, dict], modelo: str) -> RespuestaJev: ...


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def clave_valida(clave: str) -> bool:
    return CLAVE_VALIDA.fullmatch(clave) is not None


def descripcion_error(error: Exception) -> str:
    return str(error) if isinstance(error, ErrorJev) else f"error inesperado ({type(error).__name__})"


def _tiempo_agotado(error: Exception) -> bool:
    return isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)


def _serializar(valor: Any) -> str:
    return valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entero(valor: Any) -> int:
    return valor if isinstance(valor, int) else 0


def _detalle_error(e: urllib.error.HTTPError) -> str:
    try:
        return e.read(MAX_CHARS_ERROR * 4).decode("utf-8", "replace")[:MAX_CHARS_ERROR]
    except (OSError, http.client.HTTPException):
        return ""
    finally:
        e.close()


def _interpretar(crudo: bytes) -> RespuestaJev:
    try:
        datos = json.loads(crudo.decode("utf-8"))
    except ValueError as e:
        raise ErrorJev("Jev devolvió una respuesta que no es JSON.") from e
    respuestas = datos.get("answers") if isinstance(datos, dict) else None
    if not isinstance(respuestas, dict) or not all(isinstance(v, dict) for v in respuestas.values()):
        raise ErrorJev("La respuesta de Jev no trae las respuestas esperadas (answers).")
    uso = datos.get("usage")
    uso = uso if isinstance(uso, dict) else {}
    return RespuestaJev(
        modelo=str(datos.get("model") or ""),
        respuestas=respuestas,
        tokens_entrada=_entero(uso.get("input_tokens")),
        tokens_salida=_entero(uso.get("output_tokens")),
    )


class HttpJev:
    def __init__(
        self,
        clave: str,
        timeout_s: float,
        reintentos: int = 1,
        pausa_s: float = 1.0,
        base_url: str = "https://api.typesafe.ai",
    ) -> None:
        self.clave = clave
        self.timeout_s = timeout_s
        self.reintentos = reintentos
        self.pausa_s = pausa_s
        self.base_url = base_url.rstrip("/")
        self._opener = urllib.request.build_opener(_SinRedireccion)

    def preguntar(self, estado: str | dict, preguntas: dict[str, dict], modelo: str) -> RespuestaJev:
        cuerpo = json.dumps({"state": estado, "model": modelo, "questions": preguntas}, ensure_ascii=False)
        datos = cuerpo.encode("utf-8")
        for intento in range(self.reintentos + 1):
            try:
                return self._enviar(datos)
            except ErrorJev as e:
                if not e.reintentable or intento == self.reintentos:
                    raise
                time.sleep(self.pausa_s * 2**intento)
        raise AssertionError("inalcanzable")

    def _enviar(self, datos: bytes) -> RespuestaJev:
        if not clave_valida(self.clave):
            raise ErrorJev(
                "La clave de Jev tiene caracteres no válidos (solo ASCII visible, sin espacios).", reintentable=False
            )
        if self.timeout_s <= 0:
            raise ErrorJev("El tiempo máximo de Jev debe ser mayor que 0.", reintentable=False)
        req = urllib.request.Request(
            f"{self.base_url}/v1/systemone",
            data=datos,
            method="POST",
            headers={"Authorization": f"Bearer {self.clave}", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                crudo = resp.read()
        except urllib.error.HTTPError as e:
            raise ErrorJev(f"Jev respondió {e.code}: {_detalle_error(e)}", enviada=True) from e
        except (OSError, http.client.HTTPException) as e:
            if _tiempo_agotado(e):
                raise ErrorJev(f"Jev no respondió en {self.timeout_s:g} s.", enviada=True) from e
            raise ErrorJev(f"Error de conexión con Jev: {e}") from e
        except ValueError:
            raise ErrorJev(
                "No se pudo armar la petición a Jev; revise el tiempo máximo configurado.", reintentable=False
            ) from None
        return _interpretar(crudo)


class FakeJev:
    def __init__(self, respuestas: dict[str, dict] | Callable[[str | dict, dict], dict]) -> None:
        self._respuestas = respuestas
        self.llamadas: list[tuple[str | dict, dict]] = []

    def preguntar(self, estado: str | dict, preguntas: dict[str, dict], modelo: str) -> RespuestaJev:
        self.llamadas.append((estado, preguntas))
        crudas = self._respuestas(estado, preguntas) if callable(self._respuestas) else self._respuestas
        respuestas = copy.deepcopy(crudas)
        return RespuestaJev(
            modelo="jev-fake",
            respuestas=respuestas,
            tokens_entrada=(len(_serializar(estado)) + len(_serializar(preguntas))) // 4,
            tokens_salida=len(_serializar(respuestas)) // 4,
        )


def cliente_jev(cfg: Config) -> JevClient | None:
    clave = os.environ.get("JEV_API_KEY", "").strip()
    if cfg.jev.modo == "apagado" or not clave:
        return None
    return HttpJev(clave, cfg.jev.timeout_s)


def transcribir_preguntas(preguntas: dict[str, dict]) -> str:
    bloques = []
    for nombre, pregunta in preguntas.items():
        lineas = [f"=== {nombre} ==="]
        if isinstance(pregunta, dict):
            if pregunta.get("instructions"):
                lineas.append(str(pregunta["instructions"]))
            criterios = pregunta.get("criteria")
            if isinstance(criterios, dict) and criterios:
                lineas.append("Opciones:")
                lineas += [f"- {opcion}: {descripcion}" for opcion, descripcion in criterios.items()]
        bloques.append("\n".join(lineas))
    return "\n\n".join(bloques)


def _llamada(
    nodo: str,
    estado: str | dict,
    preguntas: dict[str, dict],
    modelo_pedido: str,
    salida: str,
    **campos: Any,
) -> dict:
    return LlamadaIA(
        nodo=nodo,
        intento=1,
        proveedor="jev",
        modelo_pedido=modelo_pedido,
        prompt_id=f"jev-{nodo}-v1",
        sha256_instrucciones=_sha(_serializar(preguntas)),
        instrucciones=transcribir_preguntas(preguntas),
        sha256_entrada=_sha(_serializar(estado)),
        sha256_salida=_sha(salida),
        fecha=_ahora(),
        **campos,
    ).model_dump(mode="json")


def llamada_ia(
    nodo: str,
    estado: str | dict,
    preguntas: dict[str, dict],
    resp: RespuestaJev,
    modelo_pedido: str | None = None,
) -> dict:
    return _llamada(
        nodo,
        estado,
        preguntas,
        modelo_pedido or resp.modelo,
        _serializar(resp.respuestas),
        modelo_efectivo=resp.modelo or None,
        tokens_entrada=resp.tokens_entrada,
        tokens_salida=resp.tokens_salida,
    )


def llamada_fallida(
    nodo: str, estado: str | dict, preguntas: dict[str, dict], modelo: str, error: Exception
) -> dict:
    return _llamada(nodo, estado, preguntas, modelo, "", error=descripcion_error(error)[:MAX_CHARS_ERROR])
