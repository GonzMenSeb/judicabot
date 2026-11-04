from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import logging
import math
import os
import re
import sys
import tempfile
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from docx import Document

from tutela2 import api, salidas
from tutela2 import citas as citas_mod
from tutela2 import config as cfgmod
from tutela2 import lint, llm
from tutela2.config import NODOS_LLM, Config
from tutela2.letras import numero_a_letras
from tutela2.models import Ingesta

RAIZ_REPO = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent

MODELOS_PERMITIDOS = ("claude-sonnet-5-5",)
PROHIBIDOS = ("opus", "fable", "mythos")
PRECIOS = {
    "claude-sonnet-5-5": {"entrada": 2.0, "salida": 10.0, "cache_escritura": 4.0, "cache_lectura": 0.20},
}
PRECIOS_FUENTE = "https://platform.claude.com/docs/en/about-claude/pricing (consultada el 2026-11-04)"
NOTA_PRECIO_CACHE = (
    "La lectura de caché se cobra a US$0.20/MTok, el valor más alto entre las fuentes consultadas (otra daba 0.10), "
    "por prudencia en un guardia de presupuesto."
)
URL_API = "https://api.anthropic.com"
PATRON_CLAVE = re.compile(r"[A-Za-z0-9_\-]+")
LOGGERS_SDK = ("anthropic", "httpx", "httpx2", "httpcore")
TOPE_DURO_MAXIMO = 15.0
PARADA_SUAVE_DEFECTO = 5.0
MAX_REHACER = 3
EXIGIR_RELATORIA = True
CARPETA_DEFECTO = Path.home() / ".cache" / "tutela2" / "prueba_real"
RUTA_GASTO = CARPETA_DEFECTO.parent / "prueba_real_gasto.json"
INSTRUCCION_REHACER = (
    "Rehaz las consideraciones desde cero con el mismo análisis, apoyándote en jurisprudencia de la Corte Constitucional."
)

ARCHIVO_PRESUPUESTO = "presupuesto.json"
MARCA = ".caso_sintetico.json"
NOMBRES_SINTETICOS = frozenset(f"{n:03d}.pdf" for n in range(1, 10))

SALIDA_OK, SALIDA_FALLA, SALIDA_USO, SALIDA_PARADA_SUAVE, SALIDA_ABORTO_DURO = 0, 1, 2, 3, 4

CEROS = {"entrada": 0, "salida": 0, "cache_escritura": 0, "cache_lectura": 0}
PROHIBIDAS_EN_SDK = ("fallbacks", "betas", "extra_body", "extra_headers")
MUESTRA_CARACTERES = 1500
VENTANA_REPETICION = 80


class ErrorUso(Exception):
    pass


class ErrorSeguridad(ErrorUso):
    pass


class AbortoPresupuesto(Exception):
    pass


def caso_sintetico():
    ruta = SCRIPTS / "caso_sintetico.py"
    spec = importlib.util.spec_from_file_location("caso_sintetico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def verificar_modelo_pedido(modelo: Any) -> None:
    bajo = str(modelo).strip().lower()
    if any(p in bajo for p in PROHIBIDOS):
        raise ErrorSeguridad(f"Modelo prohibido en esta prueba: {modelo!r}.")
    if modelo not in MODELOS_PERMITIDOS:
        raise ErrorSeguridad(f"Modelo fuera de la lista blanca {MODELOS_PERMITIDOS}: {modelo!r}.")


def verificar_modelo_respuesta(modelo: Any) -> None:
    bajo = str(modelo).strip().lower()
    if any(p in bajo for p in PROHIBIDOS):
        raise ErrorSeguridad(f"La respuesta vino de un modelo prohibido: {modelo!r}.")
    if not any(re.fullmatch(rf"{re.escape(p)}(-\d{{8}})?", str(modelo)) for p in MODELOS_PERMITIDOS):
        raise ErrorSeguridad(f"La respuesta vino de un modelo fuera de la lista blanca: {modelo!r}.")


def verificar_config(cfg: Config) -> None:
    errores = []
    if cfg.llm.proveedor != "anthropic":
        errores.append(f"llm.proveedor es {cfg.llm.proveedor!r}, debe ser 'anthropic'")
    if EXIGIR_RELATORIA and not cfg.verificar_relatoria:
        errores.append("verificar_relatoria está desactivado")
    if cfg.llm.fallbacks_default:
        errores.append("llm.fallbacks_default está activo (los fallbacks del servidor pueden cambiar de modelo)")
    if cfg.jev.modo != "apagado":
        errores.append(f"jev.modo es {cfg.jev.modo!r}, debe ser 'apagado'")
    for modelo in {cfg.llm.modelo, *cfg.llm.modelo_por_nodo.values(), *(cfg.modelo_para(n) for n in NODOS_LLM)}:
        try:
            verificar_modelo_pedido(modelo)
        except ErrorSeguridad as e:
            errores.append(str(e))
    if errores:
        raise ErrorSeguridad("Configuración rechazada: " + "; ".join(errores))


def fijar_entorno() -> None:
    os.environ["TUTELA2_MODELO"] = MODELOS_PERMITIDOS[0]
    os.environ["TUTELA2_JEV_MODO"] = "apagado"
    for variable in ("TUTELA2_PROVEEDOR", "JEV_API_KEY"):
        os.environ.pop(variable, None)
    for variable in [v for v in os.environ if v.startswith("ANTHROPIC_") and v != "ANTHROPIC_API_KEY"]:
        os.environ.pop(variable)
    for nombre in LOGGERS_SDK:
        logging.getLogger(nombre).setLevel(logging.WARNING)


def clave_api() -> str:
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not clave.strip():
        raise ErrorUso(
            "Falta la variable de entorno ANTHROPIC_API_KEY. Cárguela con: "
            "uv run --env-file ../.local.env python scripts/prueba_real.py ..."
        )
    if not PATRON_CLAVE.fullmatch(clave):
        raise ErrorSeguridad(
            "ANTHROPIC_API_KEY tiene caracteres no permitidos (solo letras, dígitos, '_' y '-'); no se imprime su valor."
        )
    return clave


def redactar(texto: str) -> str:
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if clave:
        texto = texto.replace(clave, "***")
    return re.sub(r"(?i)\b(bearer|x-api-key)\b[\s:=]+\S+", r"\1 ***", texto)


@contextmanager
def bloqueo_gasto():
    ruta = RUTA_GASTO.with_name(RUTA_GASTO.name + ".lock")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a") as archivo:
        try:
            fcntl.flock(archivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ErrorSeguridad("Hay otra instancia de prueba_real en curso; no se lanza más de una a la vez.") from e
        yield


def validar_topes(suave: float, duro: float) -> tuple[float, float]:
    suave, duro = float(suave), float(duro)
    if not 0 < suave <= duro <= TOPE_DURO_MAXIMO:
        raise ErrorSeguridad(
            f"Topes inválidos: se exige 0 < parada suave ({suave}) <= aborto duro ({duro}) <= {TOPE_DURO_MAXIMO}."
        )
    return suave, duro


def costo_usd(modelo: str, entrada: int, salida: int, cache_escritura: int = 0, cache_lectura: int = 0) -> float:
    p = PRECIOS[modelo]
    return (
        entrada * p["entrada"] + salida * p["salida"] + cache_escritura * p["cache_escritura"] + cache_lectura * p["cache_lectura"]
    ) / 1e6


def peor_caso_usd(kw: dict) -> float:
    chars = (
        len(str(kw.get("system", "")))
        + sum(len(str(m.get("content", ""))) for m in kw.get("messages", []))
        + len(json.dumps(kw.get("output_config", {}), default=str))
    )
    return costo_usd(kw["model"], math.ceil(chars / 2), int(kw.get("max_tokens") or 64000))


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _numero_valido(valor: Any, origen: Path, campo: str) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError) as e:
        raise ErrorSeguridad(f"{campo} de {origen} no es un número; no se continúa.") from e
    if not math.isfinite(numero) or numero < 0:
        raise ErrorSeguridad(f"{campo} de {origen} no es finito o es negativo ({numero}); no se continúa.")
    return numero


def _leer_registro(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ErrorSeguridad(f"El archivo de presupuesto {ruta} es ilegible; no se continúa: {e}") from e
    if not isinstance(datos, dict):
        raise ErrorSeguridad(f"El archivo de presupuesto {ruta} no tiene el formato esperado; no se continúa.")
    return datos


def _pendiente_usd(registro: dict, ruta: Path) -> float:
    pendiente = registro.get("en_vuelo")
    if not pendiente:
        return 0.0
    if not isinstance(pendiente, dict):
        raise ErrorSeguridad(f"en_vuelo de {ruta} no tiene el formato esperado; no se continúa.")
    return _numero_valido(pendiente.get("estimado_usd", 0), ruta, "en_vuelo.estimado_usd")


def _entero_valido(valor: Any, ruta: Path, campo: str) -> int:
    return int(_numero_valido(valor, ruta, campo))


class Presupuesto:
    def __init__(self, carpeta: Path, parada_suave: float, aborto_duro: float, ruta_gasto: Path | None = None) -> None:
        self.ruta = Path(carpeta) / ARCHIVO_PRESUPUESTO
        self.ruta_gasto = Path(ruta_gasto or RUTA_GASTO)
        self.parada_suave = parada_suave
        self.aborto_duro = aborto_duro
        self.gasto = self._cargar_gasto()
        self.datos = self._cargar_carpeta()

    def _previos_usd(self) -> float:
        rutas = {
            self.ruta,
            *CARPETA_DEFECTO.rglob(ARCHIVO_PRESUPUESTO),
            *CARPETA_DEFECTO.parent.glob(f"*/{ARCHIVO_PRESUPUESTO}"),
        }
        previos = []
        for ruta in sorted(r for r in rutas if r.is_file()):
            registro = _leer_registro(ruta)
            previos.append(_numero_valido(registro.get("acumulado_usd", 0), ruta, "acumulado_usd") + _pendiente_usd(registro, ruta))
        return max([0.0, *previos])

    def _cargar_gasto(self) -> dict:
        gasto: dict[str, Any] = {"version": 1, "acumulado_usd": 0.0, "en_vuelo": None, "recuperadas": 0}
        if self.ruta_gasto.is_file():
            leido = _leer_registro(self.ruta_gasto)
            gasto["acumulado_usd"] = _numero_valido(leido.get("acumulado_usd", 0), self.ruta_gasto, "acumulado_usd")
            gasto["recuperadas"] = _entero_valido(leido.get("recuperadas", 0), self.ruta_gasto, "recuperadas")
            pendiente = _pendiente_usd(leido, self.ruta_gasto)
            if not pendiente:
                return gasto
            gasto["acumulado_usd"] = round(gasto["acumulado_usd"] + pendiente, 8)
            gasto["recuperadas"] += 1
        else:
            gasto["acumulado_usd"] = self._previos_usd()
        self._escribir(self.ruta_gasto, gasto)
        return gasto

    def _cargar_carpeta(self) -> dict:
        datos: dict[str, Any] = {
            "version": 1,
            "acumulado_usd": 0.0,
            "llamadas": 0,
            "tokens": dict(CEROS),
            "rehacer": 0,
            "historial": [],
        }
        if not self.ruta.is_file():
            return datos
        leido = _leer_registro(self.ruta)
        tokens = leido.get("tokens") or {}
        if not isinstance(tokens, dict):
            raise ErrorSeguridad(f"tokens de {self.ruta} no tiene el formato esperado; no se continúa.")
        datos["acumulado_usd"] = round(
            _numero_valido(leido.get("acumulado_usd", 0), self.ruta, "acumulado_usd") + _pendiente_usd(leido, self.ruta), 8
        )
        datos["llamadas"] = _entero_valido(leido.get("llamadas", 0), self.ruta, "llamadas")
        datos["tokens"] = {k: _entero_valido(tokens.get(k, 0), self.ruta, f"tokens.{k}") for k in CEROS}
        datos["rehacer"] = _entero_valido(leido.get("rehacer", 0), self.ruta, "rehacer")
        datos["historial"] = leido["historial"] if isinstance(leido.get("historial"), list) else []
        return datos

    @property
    def acumulado(self) -> float:
        return self.gasto["acumulado_usd"]

    @staticmethod
    def _escribir(ruta: Path, datos: dict) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(ruta.name + ".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ruta)

    def guardar(self) -> None:
        self._escribir(self.ruta_gasto, self.gasto)
        self._escribir(self.ruta, self.datos)

    def parada_suave_alcanzada(self) -> bool:
        return self.acumulado >= self.parada_suave

    def reservar(self, estimado_usd: float) -> None:
        if self.acumulado + estimado_usd > self.aborto_duro:
            raise AbortoPresupuesto(
                f"Aborto duro: acumulado US${self.acumulado:.4f} + peor caso de la llamada US${estimado_usd:.4f} "
                f"superaría el tope de US${self.aborto_duro:.2f}."
            )
        self.gasto["en_vuelo"] = {"estimado_usd": round(estimado_usd, 6), "desde": _ahora()}
        self.guardar()

    def liberar(self) -> None:
        if self.gasto.get("en_vuelo") is not None:
            self.gasto["en_vuelo"] = None
            self.guardar()

    def _sumar(self, usd: float) -> None:
        for registro in (self.gasto, self.datos):
            registro["acumulado_usd"] = round(registro["acumulado_usd"] + usd, 8)

    def liquidar(self, modelo: str, entrada: int, salida: int, cache_escritura: int, cache_lectura: int, stop_reason: Any) -> float:
        costo = costo_usd(modelo, entrada, salida, cache_escritura, cache_lectura)
        self._sumar(costo)
        self.datos["llamadas"] += 1
        for clave, valor in zip(CEROS, (entrada, salida, cache_escritura, cache_lectura)):
            self.datos["tokens"][clave] += valor
        self.gasto["en_vuelo"] = None
        self.datos["historial"].append(
            {
                "fecha": _ahora(),
                "modelo": modelo,
                "entrada": entrada,
                "salida": salida,
                "cache_escritura": cache_escritura,
                "cache_lectura": cache_lectura,
                "stop_reason": stop_reason,
                "costo_usd": round(costo, 8),
            }
        )
        self.guardar()
        return costo

    def cobrar_reserva(self) -> None:
        pendiente = self.gasto.get("en_vuelo")
        if pendiente:
            self._sumar(float(pendiente["estimado_usd"]))
            self.gasto["en_vuelo"] = None
            self.guardar()


def repeticion_maxima(texto: str, ventana: int = VENTANA_REPETICION) -> tuple[int, str]:
    if len(texto) < ventana:
        return 0, ""
    conteo = Counter(texto[i : i + ventana] for i in range(len(texto) - ventana + 1))
    subcadena, veces = conteo.most_common(1)[0]
    return veces, subcadena


def describir_bloque(bloque: Any) -> dict:
    tipo = str(getattr(bloque, "type", type(bloque).__name__))
    texto = next((v for v in (getattr(bloque, a, None) for a in ("thinking", "text")) if isinstance(v, str)), None)
    if texto is None:
        datos = getattr(bloque, "data", None)
        caracteres = len(datos) if isinstance(datos, str) else len(repr(bloque))
        return {"tipo": tipo, "caracteres": caracteres, "inicio": "", "fin": "", "repeticion_80": 0, "subcadena_repetida": ""}
    veces, subcadena = repeticion_maxima(texto)
    return {
        "tipo": tipo,
        "caracteres": len(texto),
        "inicio": texto[:MUESTRA_CARACTERES],
        "fin": texto[max(MUESTRA_CARACTERES, len(texto) - MUESTRA_CARACTERES) :],
        "repeticion_80": veces,
        "subcadena_repetida": subcadena,
    }


def describir_respuesta(resp: Any) -> dict:
    usage = getattr(resp, "usage", None)
    try:
        entrada, salida = llm._tokens(resp)
    except (AttributeError, TypeError):
        entrada = salida = None
    return {
        "stop_reason": getattr(resp, "stop_reason", None),
        "modelo": getattr(resp, "model", None),
        "usage": {
            "input_tokens": entrada,
            "output_tokens": salida,
            "thinking_tokens": getattr(getattr(usage, "output_tokens_details", None), "thinking_tokens", None),
        },
        "bloques": [describir_bloque(b) for b in getattr(resp, "content", None) or []],
    }


def _titulo_esquema(kw: dict) -> str | None:
    config = kw.get("output_config")
    formato = config.get("format") if isinstance(config, dict) else None
    esquema = formato.get("schema") if isinstance(formato, dict) else None
    return esquema.get("title") if isinstance(esquema, dict) else None


def linea_truncada(captura: dict) -> str:
    if "error_captura" in captura:
        return f"Respuesta truncada ({captura.get('esquema')}): falló la captura de diagnóstico: {captura['error_captura']}"
    uso = captura["usage"]
    razonamiento = "n/d" if uso["thinking_tokens"] is None else uso["thinking_tokens"]
    bloques = ", ".join(f"{b['tipo']} {b['caracteres']} caracteres" for b in captura["bloques"]) or "sin bloques"
    return (
        f"Respuesta truncada ({captura.get('esquema')}, stop_reason={captura['stop_reason']}): "
        f"salida {uso['output_tokens']} tokens, razonamiento {razonamiento} tokens; bloques: {bloques}."
    )


class Guardia:
    def __init__(self, presupuesto: Presupuesto) -> None:
        self.presupuesto = presupuesto
        self.aborto: str | None = None
        self.tipo_aborto: str | None = None
        self.truncadas: list[dict] = []
        self.pendiente: Any = None
        self.esquema: str | None = None

    def abortar(self, motivo: Exception, tipo: str) -> None:
        if self.aborto is None:
            self.aborto, self.tipo_aborto = str(motivo), tipo

    def antes(self, kw: dict) -> None:
        self.pendiente = None
        self.esquema = _titulo_esquema(kw)
        if self.aborto:
            if self.tipo_aborto == "presupuesto":
                raise AbortoPresupuesto(f"Bloqueado tras un aborto previo: {self.aborto}")
            raise ErrorSeguridad(f"Bloqueado tras un aborto previo: {self.aborto}")
        try:
            verificar_modelo_pedido(kw.get("model"))
            extra = [k for k in PROHIBIDAS_EN_SDK if k in kw]
            if extra:
                raise ErrorSeguridad(f"Parámetros no permitidos en la llamada: {extra}.")
            self.presupuesto.reservar(peor_caso_usd(kw))
        except AbortoPresupuesto as e:
            self.abortar(e, "presupuesto")
            raise
        except ErrorSeguridad as e:
            self.abortar(e, "seguridad")
            raise

    def registrar(self, resp: Any, modelo_pedido: str) -> None:
        try:
            entrada, salida = llm._tokens(resp)
            usage = resp.usage
            cache_e = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            cache_l = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        except (AttributeError, TypeError):
            self.presupuesto.cobrar_reserva()
            error = ErrorSeguridad("La respuesta no trae uso de tokens; se cobró el peor caso de la reserva.")
            self.abortar(error, "seguridad")
            raise error
        self.presupuesto.liquidar(modelo_pedido, entrada, salida, cache_e, cache_l, getattr(resp, "stop_reason", None))
        try:
            verificar_modelo_respuesta(getattr(resp, "model", None))
        except ErrorSeguridad as e:
            self.abortar(e, "seguridad")
            raise
        self.pendiente = resp
        if getattr(resp, "stop_reason", None) == "max_tokens":
            self.capturar("stop_reason=max_tokens")

    def capturar(self, motivo: str) -> None:
        resp, self.pendiente = self.pendiente, None
        if resp is None:
            return
        try:
            captura = {"esquema": self.esquema, "motivo": motivo, **describir_respuesta(resp)}
        except Exception as e:
            captura = {"esquema": self.esquema, "motivo": motivo, "error_captura": f"{type(e).__name__}: {e}"}
        self.truncadas.append(captura)


class ClienteDiagnostico:
    def __init__(self, cliente: Any, guardia: Guardia) -> None:
        self._cliente, self._guardia = cliente, guardia

    def estructurado(self, *args: Any, **kwargs: Any) -> Any:
        self._guardia.pendiente = None
        try:
            return self._cliente.estructurado(*args, **kwargs)
        except llm.ErrorLLM as e:
            self._guardia.capturar(str(e))
            raise

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._cliente, nombre)


class _Flujo:
    def __init__(self, flujo: Any, guardia: Guardia, modelo: str) -> None:
        self._flujo, self._guardia, self._modelo = flujo, guardia, modelo

    def get_final_message(self) -> Any:
        resp = self._flujo.get_final_message()
        self._guardia.registrar(resp, self._modelo)
        return resp

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._flujo, nombre)


class _Manager:
    def __init__(self, manager: Any, guardia: Guardia, modelo: str) -> None:
        self._manager, self._guardia, self._modelo = manager, guardia, modelo

    def __enter__(self) -> _Flujo:
        try:
            return _Flujo(self._manager.__enter__(), self._guardia, self._modelo)
        except BaseException:
            self._guardia.presupuesto.cobrar_reserva()
            raise

    def __exit__(self, tipo: Any, valor: Any, traza: Any) -> Any:
        try:
            return self._manager.__exit__(tipo, valor, traza)
        finally:
            if tipo is None:
                self._guardia.presupuesto.liberar()
            else:
                self._guardia.presupuesto.cobrar_reserva()


class _Mensajes:
    def __init__(self, guardia: Guardia, real: Any) -> None:
        self._guardia, self._real = guardia, real

    def stream(self, **kw: Any) -> _Manager:
        self._guardia.antes(kw)
        try:
            manager = self._real.stream(**kw)
        except BaseException:
            self._guardia.presupuesto.liberar()
            raise
        return _Manager(manager, self._guardia, kw["model"])

    def __getattr__(self, nombre: str) -> Any:
        error = ErrorSeguridad(f"messages.{nombre} no está permitido en esta prueba; solo messages.stream.")
        self._guardia.abortar(error, "seguridad")
        raise error


class ClienteSDKVigilado:
    def __init__(self, guardia: Guardia, real: Any) -> None:
        self._guardia, self._real = guardia, real
        self.messages = _Mensajes(guardia, real.messages)

    def with_options(self, **opciones: Any) -> ClienteSDKVigilado:
        return ClienteSDKVigilado(self._guardia, self._real.with_options(**opciones))

    def __getattr__(self, nombre: str) -> Any:
        error = ErrorSeguridad(f"El cliente del SDK no permite usar '{nombre}' (fallbacks y betas están prohibidos).")
        self._guardia.abortar(error, "seguridad")
        raise error


@contextmanager
def entorno_vigilado(guardia: Guardia, fabrica_sdk: Callable[[], Any] | None = None, intentos_citas: list | None = None):
    import anthropic

    original_sdk, original_cliente, original_verificar = anthropic.Anthropic, llm.cliente_para, citas_mod.verificar_citas

    def fabrica(*args: Any, **kwargs: Any) -> ClienteSDKVigilado:
        real = fabrica_sdk() if fabrica_sdk else original_sdk(api_key=clave_api(), base_url=URL_API)
        return ClienteSDKVigilado(guardia, real)

    def cliente_para(cfg: Config):
        try:
            verificar_config(cfg)
        except ErrorSeguridad as e:
            guardia.abortar(e, "seguridad")
            raise
        return ClienteDiagnostico(original_cliente(cfg), guardia)

    def verificar(propuestas, cfg, dataset):
        resultado = original_verificar(propuestas, cfg, dataset)
        if intentos_citas is not None:
            intentos_citas.append([_ficha_cita(cv.model_dump(mode="json")) for cv in resultado])
        return resultado

    anthropic.Anthropic, llm.cliente_para, citas_mod.verificar_citas = fabrica, cliente_para, verificar
    try:
        yield
    finally:
        anthropic.Anthropic, llm.cliente_para, citas_mod.verificar_citas = original_sdk, original_cliente, original_verificar


def verificar_ruta(carpeta: Path) -> Path:
    ruta = Path(carpeta).expanduser().resolve()
    if ruta == RAIZ_REPO or ruta.is_relative_to(RAIZ_REPO):
        raise ErrorSeguridad(f"La carpeta {ruta} está dentro del repositorio; el caso sintético debe vivir fuera de él.")
    if {"casos", "referencia"} & set(ruta.parts):
        raise ErrorSeguridad(f"La carpeta {ruta} está bajo una ruta 'casos' o 'referencia'.")
    return ruta


def _contenido_propio(carpeta: Path) -> list[Path]:
    return [p for p in carpeta.iterdir() if p.name != ARCHIVO_PRESUPUESTO and not p.name.startswith("reporte_")]


def verificar_carpeta_propia(carpeta: Path) -> None:
    carpeta = verificar_ruta(carpeta)
    if not carpeta.exists() or not _contenido_propio(carpeta):
        return
    marca = carpeta / MARCA
    try:
        radicado = json.loads(marca.read_text(encoding="utf-8")).get("radicado")
    except (OSError, ValueError, AttributeError):
        radicado = None
    if radicado != caso_sintetico().RADICADO:
        raise ErrorSeguridad(f"La carpeta {carpeta} tiene contenido y no es un caso sintético generado por este script.")


def verificar_contenido(carpeta: Path) -> None:
    cs = caso_sintetico()
    ruta = Path(carpeta) / "caso.json"
    if not ruta.is_file():
        raise ErrorSeguridad(f"No existe {ruta}; no se puede comprobar que el caso sea el sintético.")
    ing = Ingesta.model_validate_json(ruta.read_text(encoding="utf-8"))
    if ing.metadatos.cui_1a != cs.RADICADO:
        raise ErrorSeguridad(f"El radicado del caso ({ing.metadatos.cui_1a}) no es el ficticio {cs.RADICADO}.")
    nombres = {d.nombre for d in ing.documentos}
    if nombres != NOMBRES_SINTETICOS:
        raise ErrorSeguridad(f"Los documentos del caso no son los nueve sintéticos: {sorted(nombres)}.")
    for d in ing.documentos:
        texto = " ".join(" ".join(p.texto for p in d.paginas).split()).lower()
        if cs.ACCIONANTE.lower() not in texto:
            raise ErrorSeguridad(f"El documento {d.nombre} no contiene el nombre ficticio de la accionante.")


def ajustar_config(carpeta: Path) -> None:
    cfg = cfgmod.cargar(carpeta, entorno=False)
    cfg.llm.proveedor = "anthropic"
    cfg.llm.modelo = MODELOS_PERMITIDOS[0]
    cfg.llm.modelo_por_nodo = {}
    cfg.llm.fallbacks_default = False
    cfg.jev.modo = "apagado"
    cfg.verificar_relatoria = EXIGIR_RELATORIA
    cfgmod.guardar(carpeta, cfg)


def palabras_cita(texto: str) -> list[str]:
    return citas_mod._analizar_cita(citas_mod._limpiar_cita(texto))[0]


def _ficha_cita(cv: dict) -> dict:
    return {
        "id": cv.get("id"),
        "sentencia_original": cv.get("sentencia_original"),
        "estado": cv.get("estado"),
        "n_palabras": len(palabras_cita(cv.get("texto_citado") or "")),
        "seccion": cv.get("seccion"),
        "cobertura": cv.get("cobertura"),
        "motivos": list(cv.get("motivos") or []),
        "texto": cv.get("texto_citado"),
    }


@lru_cache(maxsize=1)
def _normas() -> tuple[dict, ...]:
    ruta = Path(citas_mod.__file__).parent / "assets" / "normas_citables.json"
    return tuple(json.loads(ruta.read_text(encoding="utf-8"))) if ruta.is_file() else ()


def _criterio(id: str, descripcion: str, cumple: bool | None, detalle: str) -> dict:
    estado = "no_evaluable" if cumple is None else ("pasa" if cumple else "falla")
    return {"id": id, "descripcion": descripcion, "estado": estado, "detalle": detalle}


def _cobertura_normativa(palabras: list[str], cfg: Config) -> tuple[float, str]:
    mejor, norma = 0.0, ""
    n = min(cfg.ngram, len(palabras))
    for entrada in _normas():
        for incisos in (False, True):
            c = citas_mod._cobertura_modo(palabras, entrada["texto"], n, incisos)
            if c > mejor:
                mejor, norma = c, f"{entrada['norma']} art. {entrada['articulo']}"
    return mejor, norma


_MARCADOR = re.compile(r"\[\[CITA:([^\]]+)\]\]")


def criterios_consideraciones(resumen: dict, cfg: Config) -> list[dict]:
    todas = resumen.get("citas") or []
    ok = [c for c in todas if c.get("estado") == "ok"]
    conteo = {e: sum(1 for c in todas if c.get("estado") == e) for e in ("ok", "alerta", "rechazada")}
    criterios = [
        _criterio(
            "citas_ok",
            f"Al menos {cfg.min_citas_ok} citas verificadas (ok)",
            len(ok) >= cfg.min_citas_ok,
            f"{conteo['ok']} ok, {conteo['alerta']} alerta, {conteo['rechazada']} rechazadas (mínimo exigido {cfg.min_citas_ok}).",
        )
    ]

    palabras = {c["id"]: palabras_cita(c.get("texto_citado") or "") for c in ok}
    cortas = [f"{i} ({len(p)})" for i, p in palabras.items() if len(p) < cfg.min_palabras_cita]
    criterios.append(
        _criterio(
            "longitud",
            f"Cada cita ok tiene al menos {cfg.min_palabras_cita} palabras",
            (not cortas) if ok else None,
            f"Mínimo exigido {cfg.min_palabras_cita}. Palabras por cita: "
            + (", ".join(f"{i}={len(p)}" for i, p in palabras.items()) or "sin citas ok")
            + (f". Cortas: {', '.join(cortas)}." if cortas else "."),
        )
    )

    if _normas():
        normativas = []
        medidas = []
        for i, p in palabras.items():
            if not p:
                continue
            cobertura, norma = _cobertura_normativa(p, cfg)
            medidas.append(f"{i}={cobertura:.2f}")
            if cobertura >= cfg.cobertura_ok:
                normativas.append(f"{i} ({norma}, cobertura {cobertura:.2f})")
        criterios.append(
            _criterio(
                "sin_normativas",
                "Ninguna cita ok es texto normativo del corpus (CP, D. 2591, Ley 1751)",
                (not normativas) if ok else None,
                f"Umbral de cobertura {cfg.cobertura_ok}. Medidas: {', '.join(medidas) or 'sin citas ok'}."
                + (f" Normativas: {', '.join(normativas)}." if normativas else ""),
            )
        )
    else:
        criterios.append(_criterio("sin_normativas", "Ninguna cita ok es texto normativo", None, "No existe normas_citables.json."))

    secciones = {c["id"]: c.get("seccion") for c in ok}
    en_salvamento = [i for i, s in secciones.items() if s == "salvamento"]
    sin_dato = [i for i, s in secciones.items() if s not in ("mayoria", "salvamento")]
    if en_salvamento:
        cumple_seccion: bool | None = False
    elif not ok or sin_dato:
        cumple_seccion = None
    else:
        cumple_seccion = True
    criterios.append(
        _criterio(
            "sin_salvamento",
            "Ninguna cita ok proviene solo del salvamento de voto",
            cumple_seccion,
            f"Secciones: {', '.join(f'{i}={s}' for i, s in secciones.items()) or 'sin citas ok'}."
            + (" Sin dato de sección: no evaluable." if sin_dato and not en_salvamento else ""),
        )
    )

    cons = resumen.get("consideraciones") or {}
    textos = {
        "procedibilidad": cons.get("procedibilidad") or "",
        **{f"bloque {i}": b.get("texto") or "" for i, b in enumerate(cons.get("bloques") or [], 1)},
    }
    infractoras = [m for campo, t in textos.items() for m in lint.jurisprudencia_sin_cita(t, f"consideraciones, {campo}")]
    criterios.append(
        _criterio(
            "formula_sin_marcador",
            "Ninguna oración 'la jurisprudencia ha...' sin marcador [[CITA:id]]",
            not infractoras,
            f"{len(infractoras)} oraciones sin marcador (criterio de lint.jurisprudencia_sin_cita, tope por texto)."
            + (f" Ejemplos: {[m[:200] for m in infractoras[:3]]}" if infractoras else ""),
        )
    )
    return criterios


def texto_docx(ruta: Path, tablas: bool = True) -> list[str]:
    doc = Document(str(ruta))
    partes = [" ".join(p.text.split()) for p in doc.paragraphs]
    if tablas:
        partes += [" ".join(c.text.split()) for t in doc.tables for f in t.rows for c in f.cells]
    return [p for p in partes if p]


def _normalizado(texto: str) -> str:
    return citas_mod.normalizar_texto(texto, False)


def _tramo_caso_concreto(parrafos: list[str]) -> tuple[int | None, int]:
    titulo = re.compile(r"(?:[IVXL]+\.?\s*)?CASO CONCRETO")
    cierre = re.compile(r"(?:[IVXL]+\.?\s*)?(?:RESUELVE|OTRAS DETERMINACIONES|PARTE RESOLUTIVA)")
    inicio = next((i for i, p in enumerate(parrafos) if titulo.fullmatch(p.strip())), None)
    if inicio is None:
        return None, len(parrafos)
    fin = next((i for i in range(inicio + 1, len(parrafos)) if cierre.fullmatch(parrafos[i].strip())), len(parrafos))
    return inicio, fin


def _fallo_docx(carpeta: Path) -> Path | None:
    return next(iter(sorted(salidas.principal(carpeta).glob("003FalloSegunda*.docx"))), None)


def _palabras_clave(texto: str) -> set[str]:
    return {w for w in _normalizado(texto).split() if len(w) >= 4}


def criterios_decision(carpeta: Path, resumen: dict, cfg: Config) -> list[dict]:
    ruta = _fallo_docx(Path(carpeta))
    if ruta is None:
        return [_criterio("fallo_generado", "El fallo .docx se generó", False, "No existe 003FalloSegunda*.docx en salidas/.")]
    parrafos = texto_docx(ruta, tablas=False)
    todo = " ".join(parrafos)
    inicio, fin = _tramo_caso_concreto(parrafos)
    tramo = " ".join(parrafos[inicio + 1 : fin]) if inicio is not None else ""
    caso = resumen.get("caso_concreto") or {}
    texto_modelo = " ".join([caso.get("problema_juridico") or "", *(p.get("texto") or "" for p in caso.get("parrafos") or []), caso.get("conclusion") or ""])
    ok = {c["id"]: c for c in resumen.get("citas") or [] if c.get("estado") == "ok"}

    criterios = [
        _criterio("sin_marcadores_crudos", "El .docx no deja marcadores [[CITA:id]] sin expandir", "[[CITA:" not in todo, "Marcadores crudos en el .docx." if "[[CITA:" in todo else "Ninguno.")
    ]

    usados = [i for i in dict.fromkeys(_MARCADOR.findall(texto_modelo)) if i in ok]
    expandidos, medidas = [], []
    if inicio is not None:
        for i in usados:
            p = palabras_cita(ok[i].get("texto_citado") or "")
            if not p:
                continue
            cobertura = citas_mod._cobertura_modo(p, tramo, min(cfg.ngram, len(p)), False)
            medidas.append(f"{i}={cobertura:.2f}")
            if cobertura >= cfg.cobertura_alerta:
                expandidos.append(i)
    detalle = (
        f"Marcadores de citas ok en el caso concreto: {usados or 'ninguno'}. Cobertura del fragmento en la sección "
        f"(umbral {cfg.cobertura_alerta}): {', '.join(medidas) or 'n/a'}."
        + ("" if inicio is not None else " No se encontró el título CASO CONCRETO en el .docx.")
    )
    criterios.append(_criterio("marcador_ok_expandido", "Al menos un marcador de cita ok queda expandido en el caso concreto del .docx", bool(expandidos), detalle))

    segmentos = [x for x in _MARCADOR.split(caso.get("conclusion") or "") if len(x.split()) >= 5]
    todo_norm = _normalizado(todo)
    conteos = [todo_norm.count(_normalizado(x)) for x in segmentos]
    veces = max(conteos, default=0)
    claves = _palabras_clave(_MARCADOR.sub(" ", caso.get("conclusion") or ""))
    contenciones = []
    for p in caso.get("parrafos") or []:
        otras = _palabras_clave(p.get("texto") or "")
        if len(otras) >= 8 and claves:
            contenciones.append(len(claves & otras) / min(len(claves), len(otras)))
    maxima = max(contenciones, default=0.0)
    criterios.append(
        _criterio(
            "una_sola_conclusion",
            "La conclusión aparece una sola vez y no se repite en los párrafos",
            (all(c == 1 for c in conteos) and maxima < 0.85) if conteos else None,
            f"La conclusión aparece {veces} vez/veces en el .docx; contención máxima con los párrafos {maxima:.2f} (umbral 0.85).",
        )
    )

    ordenes = (resumen.get("decision") or {}).get("ordenes") or []
    tramo_norm = _normalizado(tramo)
    faltan = []
    for o in ordenes:
        plazo = o.get("plazo") or {}
        n, raiz = int(plazo.get("n", 0)), "hora" if "hora" in str(plazo.get("unidad")) else "dia"
        letras = re.escape(_normalizado(numero_a_letras(n)))
        if not re.search(rf"(?:\b{n}\b|\b{letras}\b)(?:\s+\w+){{0,3}}?\s+{raiz}\w*", tramo_norm):
            faltan.append(f"{n} {plazo.get('unidad')}")
    criterios.append(
        _criterio(
            "plazo_reflejado",
            "El caso concreto refleja el plazo de cada orden",
            not faltan if inicio is not None else False,
            ("Sin órdenes con plazo." if not ordenes else f"Órdenes: {len(ordenes)}.")
            + (f" Plazos ausentes en el caso concreto: {faltan}." if faltan else "")
            + ("" if inicio is not None else " No se encontró el título CASO CONCRETO."),
        )
    )
    return criterios


def criterios_informe(carpeta: Path, resumen: dict) -> list[dict]:
    ruta = salidas.trabajo(Path(carpeta)) / "informe_verificacion.docx"
    if not ruta.is_file():
        return [_criterio("informe_generado", "El informe .docx se generó", False, "No existe trabajo/informe_verificacion.docx.")]
    informe = " ".join(texto_docx(ruta))
    bajo = informe.lower()
    alertas = resumen.get("alertas") or {}
    mensajes = [m for v in alertas.values() for m in (v if isinstance(v, list) else [v])]
    vigentes = [m for m in mensajes if str(m).startswith("BLOQUEA:")] + [str(e) for e in resumen.get("errores") or []]
    criterios = []

    no_reportados = [m for m in vigentes if " ".join(m.split()) not in informe]
    dice_limpio = "no hay errores bloqueantes" in bajo
    criterios.append(
        _criterio(
            "errores_bloqueantes_veraz",
            "El informe no dice 'No hay errores bloqueantes' si los hay y los lista",
            not vigentes or (not dice_limpio and not no_reportados),
            f"{len(vigentes)} errores bloqueantes vigentes; el informe dice que no hay: {dice_limpio}; sin listar: {len(no_reportados)}.",
        )
    )
    criterios.append(
        _criterio(
            "sin_alertas_falso",
            "El informe no dice 'Sin alertas' si hay alertas",
            not ("sin alertas" in bajo and mensajes),
            f"{len(mensajes)} mensajes de alerta en el estado; el informe dice 'sin alertas': {'sin alertas' in bajo}.",
        )
    )

    faltas: dict[str, str] = {}
    for docx in sorted(salidas.raiz(Path(carpeta)).rglob("*.docx")):
        if docx.relative_to(salidas.raiz(Path(carpeta))).parts[0] == "trabajo":
            continue
        for marcador in re.findall(r"⟦FALTA[^⟧]*⟧", " ".join(texto_docx(docx))):
            faltas.setdefault(marcador, docx.name)
    decision = resumen.get("decision") or {}
    hay_pendientes = bool(faltas or decision.get("generar_formato") or decision.get("fecha_fallo") is None)
    criterios.append(
        _criterio(
            "pendientes_listados",
            "El informe tiene la sección de pendientes y no dice 'Sin pendientes' si los hay",
            "pendientes y valores por defecto" in bajo and not (hay_pendientes and "sin pendientes registrados" in bajo),
            f"Sección presente: {'pendientes y valores por defecto' in bajo}; hay pendientes conocidos: {hay_pendientes}.",
        )
    )

    sin_reportar = []
    for marcador, archivo in faltas.items():
        interior = marcador[len("⟦FALTA") : -1].strip(" :")
        if (interior and interior.lower() not in bajo) or (not interior and archivo not in informe):
            sin_reportar.append(f"{marcador} ({archivo})")
    criterios.append(
        _criterio(
            "falta_reportado",
            "Todo ⟦FALTA⟧ de los .docx finales figura en el informe",
            not sin_reportar,
            f"{len(faltas)} marcadores ⟦FALTA⟧ en los documentos finales; sin reportar: {sin_reportar or 'ninguno'}.",
        )
    )
    return criterios


def _veredicto(criterios: dict[str, list[dict]], contados: tuple[str, ...]) -> str:
    estados = [c["estado"] for g in contados for c in criterios.get(g, [])]
    if not estados or any(e == "falla" for e in estados):
        return "falla"
    return "pasa" if all(e == "pasa" for e in estados) else "incompleto"


class Sesion:
    def __init__(self, carpeta: Path, comando: str, suave: float, duro: float, fabrica_sdk: Callable[[], Any] | None) -> None:
        self.carpeta, self.comando, self.fabrica_sdk = carpeta, comando, fabrica_sdk
        self.presupuesto = Presupuesto(carpeta, suave, duro)
        self.guardia = Guardia(self.presupuesto)
        self.intentos_citas: list[list[dict]] = []
        self.pasos: list[dict] = []
        self.criterios: dict[str, list[dict]] = {}
        self.parada: str | None = None
        self.error: str | None = None
        self.estado_final: str | None = None
        self.resumen: dict = {}
        self.inicio = {
            "usd": self.presupuesto.acumulado,
            "tokens": dict(self.presupuesto.datos["tokens"]),
            "llamadas": self.presupuesto.datos["llamadas"],
        }

    def detenido(self) -> bool:
        if self.parada is None and self.presupuesto.parada_suave_alcanzada():
            self.parada = "suave"
        return self.parada is not None

    def paso(self, nombre: str, funcion: Callable[..., dict], *args: Any) -> dict | None:
        if self.detenido():
            return None
        antes = self.presupuesto.acumulado
        resultado = funcion(*args)
        self.pasos.append(
            {
                "paso": nombre,
                "estado": resultado.get("estado"),
                "ok": resultado.get("ok"),
                "error": resultado.get("error"),
                "costo_usd": round(self.presupuesto.acumulado - antes, 6),
            }
        )
        self.estado_final = resultado.get("estado")
        self.resumen = resultado.get("resumen") or self.resumen
        if not resultado.get("ok"):
            self.error = resultado.get("error")
        if self.guardia.aborto:
            self.parada = "duro" if self.guardia.tipo_aborto == "presupuesto" else "seguridad"
        return resultado

    def cfg(self) -> Config:
        return cfgmod.cargar(self.carpeta)

    def evaluar_consideraciones(self) -> None:
        self.criterios["consideraciones"] = criterios_consideraciones(self.resumen, self.cfg())

    def evaluar_decision(self) -> None:
        self.criterios["decision"] = criterios_decision(self.carpeta, self.resumen, self.cfg())
        self.criterios["informe"] = criterios_informe(self.carpeta, self.resumen)

    def reporte(self, contados: tuple[str, ...]) -> dict:
        datos = self.presupuesto.datos
        bitacora = self.resumen.get("bitacora") or []
        reporte = {
            "comando": self.comando,
            "fecha": _ahora(),
            "carpeta": str(self.carpeta),
            "modelo": MODELOS_PERMITIDOS[0],
            "precios": {"usd_por_mtok": PRECIOS[MODELOS_PERMITIDOS[0]], "fuente": PRECIOS_FUENTE},
            "estado_final": self.estado_final,
            "error": self.error,
            "parada": self.parada,
            "aborto": self.guardia.aborto,
            "veredicto": _veredicto(self.criterios, contados),
            "grupos_que_cuentan": list(contados),
            "costo": {
                "invocacion_usd": round(self.presupuesto.acumulado - self.inicio["usd"], 6),
                "acumulado_usd": round(self.presupuesto.acumulado, 6),
                "acumulado_carpeta_usd": round(datos["acumulado_usd"], 6),
                "parada_suave_usd": self.presupuesto.parada_suave,
                "aborto_duro_usd": self.presupuesto.aborto_duro,
                "llamadas": datos["llamadas"] - self.inicio["llamadas"],
                "llamadas_acumuladas": datos["llamadas"],
                "tokens": {k: datos["tokens"][k] - self.inicio["tokens"][k] for k in CEROS},
                "tokens_acumulados": datos["tokens"],
                "tokens_en_bitacora_de_llm_py": {
                    "entrada": sum(b.get("tokens_entrada") or 0 for b in bitacora),
                    "salida": sum(b.get("tokens_salida") or 0 for b in bitacora),
                },
                "rehacer_realizados": datos["rehacer"],
            },
            "pasos": self.pasos,
            "criterios": self.criterios,
            "citas": [_ficha_cita(c) for c in self.resumen.get("citas") or []],
            "intentos_citas": self.intentos_citas,
            "alertas": self.resumen.get("alertas") or {},
        }
        if self.guardia.truncadas:
            reporte["respuesta_truncada"] = self.guardia.truncadas
        return reporte

    def codigo(self, veredicto: str) -> int:
        if self.parada in ("seguridad", "rechazado"):
            return SALIDA_USO
        if self.parada == "duro":
            return SALIDA_ABORTO_DURO
        if self.parada == "suave":
            return SALIDA_PARADA_SUAVE
        return SALIDA_OK if veredicto == "pasa" else SALIDA_FALLA


def reporte_markdown(r: dict) -> str:
    c = r["costo"]
    t = c["tokens"]
    lineas = [
        f"# Prueba real: {r['comando']}",
        "",
        f"- Veredicto: **{r['veredicto']}**" + (f" (parada {r['parada']})" if r.get("parada") else ""),
        f"- Estado final del caso: {r.get('estado_final')}" + (f" | error: {r['error']}" if r.get("error") else ""),
        f"- Costo de esta invocación: US${c['invocacion_usd']:.4f} (acumulado US${c['acumulado_usd']:.4f}; parada suave US${c['parada_suave_usd']:.2f}; aborto duro US${c['aborto_duro_usd']:.2f})",
        f"- Llamadas: {c['llamadas']} | tokens entrada {t['entrada']}, salida {t['salida']}, cache escritura {t['cache_escritura']}, cache lectura {t['cache_lectura']}",
        "",
        "## Criterios",
        "",
        "| Grupo | Criterio | Estado | Detalle |",
        "|---|---|---|---|",
    ]
    for grupo, criterios in r.get("criterios", {}).items():
        for k in criterios:
            lineas.append(f"| {grupo} | {k['id']} | {k['estado']} | {k['detalle']} |")
    lineas += ["", "## Citas por intento (motivos de rechazo)", ""]
    for n, intento in enumerate(r.get("intentos_citas", []), 1):
        lineas.append(f"### Verificación {n}")
        for cita in intento:
            lineas.append(
                f"- {cita['id']} ({cita['sentencia_original']}): {cita['estado']}, {cita['n_palabras']} palabras, sección {cita['seccion']}"
            )
            lineas += [f"  - {m}" for m in cita["motivos"]]
    lineas += ["", "## Pasos", ""]
    lineas += [f"- {p['paso']}: {p['estado']} (US${p['costo_usd']:.4f})" + (f" | {p['error']}" if p.get("error") else "") for p in r.get("pasos", [])]
    for captura in r.get("respuesta_truncada", []):
        lineas += ["", f"## Respuesta truncada ({captura.get('esquema')})", "", linea_truncada(captura), "", f"Motivo: {captura.get('motivo')}"]
        for n, b in enumerate(captura.get("bloques", []), 1):
            lineas += [
                "",
                f"### Bloque {n}: {b['tipo']} ({b['caracteres']} caracteres; repetición máxima de {VENTANA_REPETICION} caracteres: {b['repeticion_80']} veces)",
            ]
            for etiqueta, muestra in (("Primeros", b["inicio"]), ("Últimos", b["fin"])):
                if muestra:
                    lineas += ["", f"{etiqueta} {len(muestra)} caracteres:", "", "````", muestra, "````"]
    return "\n".join(lineas) + "\n"


def _escribir_reporte(sesion: Sesion, contados: tuple[str, ...], salida: Path | None) -> dict:
    reporte = sesion.reporte(contados)
    base = salida or (sesion.carpeta / f"reporte_{sesion.comando}.json")
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(reporte_markdown(reporte), encoding="utf-8")
    return reporte


def _imprimir_resumen(reporte: dict) -> None:
    c = reporte["costo"]
    print(f"Veredicto: {reporte['veredicto']}" + (f" (parada {reporte['parada']})" if reporte.get("parada") else ""))
    print(f"Estado del caso: {reporte.get('estado_final')}")
    if reporte.get("error"):
        print(f"Error: {reporte['error']}")
    print(f"Costo de esta invocación: US${c['invocacion_usd']:.4f}; acumulado US${c['acumulado_usd']:.4f} de US${c['aborto_duro_usd']:.2f}")
    print(f"Llamadas: {c['llamadas']}; tokens: {c['tokens']}")
    for grupo, criterios in reporte["criterios"].items():
        for k in criterios:
            print(f"  [{k['estado']:^12}] {grupo}/{k['id']}: {k['detalle']}")
    for captura in reporte.get("respuesta_truncada", []):
        print(linea_truncada(captura))


def _preparar_caso(sesion: Sesion, reiniciar: bool) -> None:
    cs = caso_sintetico()
    carpeta = sesion.carpeta
    if (carpeta / "hilo.sqlite").exists() and not reiniciar:
        actual = api.estado(carpeta)["estado"]
        if actual not in ("sin_iniciar", "revision", "incompleto"):
            raise ErrorUso(
                f"El caso ya tiene un hilo con llamadas pagadas (estado {actual}); use --reiniciar para descartarlo y volver a pagar."
            )
    if not (carpeta / "01PrimeraInstancia").is_dir():
        cs.generar(carpeta)
    (carpeta / MARCA).write_text(json.dumps({"radicado": cs.RADICADO, "fecha": _ahora()}), encoding="utf-8")
    cs.preparar(carpeta, "anthropic")
    ajustar_config(carpeta)
    verificar_config(cfgmod.cargar(carpeta))
    nuevo = api.nuevo(carpeta)
    if nuevo["estado"] != "revision":
        raise ErrorUso(f"La ingesta del caso sintético no quedó en revisión: {nuevo['estado']} {nuevo['error']}")
    verificar_contenido(carpeta)
    sesion.presupuesto.datos["rehacer"] = 0
    sesion.presupuesto.guardar()


def _exigir_caso_existente(carpeta: Path) -> None:
    if not carpeta.exists() or not (carpeta / MARCA).is_file():
        raise ErrorUso(f"No hay un caso sintético en {carpeta}; corra primero 'hasta-decision'.")
    verificar_contenido(carpeta)
    verificar_config(cfgmod.cargar(carpeta))


def _exigir_estado(carpeta: Path, esperado: str) -> None:
    actual = api.estado(carpeta)["estado"]
    if actual != esperado:
        raise ErrorUso(f"El caso está en estado {actual!r}; este comando exige {esperado!r}.")


def _paso_hasta_decision(sesion: Sesion, reiniciar: bool) -> None:
    if sesion.detenido():
        return
    _preparar_caso(sesion, reiniciar)
    resultado = sesion.paso("iniciar", api.iniciar, sesion.carpeta)
    if resultado and resultado["estado"] == "esperando_decision":
        sesion.evaluar_consideraciones()


def _paso_rehacer(sesion: Sesion, veces: int, instruccion: str) -> None:
    _exigir_estado(sesion.carpeta, "esperando_decision")
    datos = sesion.presupuesto.datos
    for _ in range(veces):
        if sesion.detenido():
            break
        if datos["rehacer"] >= MAX_REHACER:
            sesion.error = f"Se alcanzó el máximo de {MAX_REHACER} rehacer por caso."
            break
        datos["rehacer"] += 1
        sesion.presupuesto.guardar()
        resultado = sesion.paso(
            "rehacer_consideraciones", api.decidir, sesion.carpeta, {"accion": "rehacer_consideraciones", "instruccion": instruccion}
        )
        if resultado is None or resultado["estado"] != "esperando_decision":
            break
        sesion.evaluar_consideraciones()
        if all(c["estado"] == "pasa" for c in sesion.criterios["consideraciones"]):
            break


def _paso_decidir(sesion: Sesion, decision: dict) -> None:
    if sesion.detenido():
        return
    _exigir_estado(sesion.carpeta, "esperando_decision")
    resultado = sesion.paso("decidir", api.decidir, sesion.carpeta, decision)
    if resultado and resultado["estado"] == "terminado":
        sesion.evaluar_decision()


def _paso_continuar(sesion: Sesion) -> None:
    resultado = sesion.paso("continuar", api.continuar, sesion.carpeta)
    if resultado and resultado["estado"] == "esperando_decision":
        sesion.evaluar_consideraciones()
    elif resultado and resultado["estado"] == "terminado":
        sesion.evaluar_decision()


CONTADOS = {
    "hasta-decision": ("consideraciones",),
    "rehacer": ("consideraciones",),
    "decidir": ("decision",),
    "extremo-a-extremo": ("consideraciones", "decision", "informe"),
    "continuar": ("consideraciones", "decision"),
}


def _pagado(args: argparse.Namespace, fabrica_sdk: Callable[[], Any] | None) -> int:
    suave, duro = validar_topes(args.parada_suave, args.aborto_duro)
    clave_api()
    with bloqueo_gasto():
        carpeta = verificar_ruta(args.carpeta)
        verificar_carpeta_propia(carpeta)
        fijar_entorno()
        comando = args.comando
        if comando not in ("hasta-decision", "extremo-a-extremo"):
            _exigir_caso_existente(carpeta)
        decision = None
        if comando in ("decidir", "extremo-a-extremo"):
            decision = (
                json.loads(args.decision.read_text(encoding="utf-8")) if args.decision else caso_sintetico().DECISION_POR_DEFECTO
            )
        carpeta.mkdir(parents=True, exist_ok=True)
        sesion = Sesion(carpeta, comando, suave, duro, fabrica_sdk)
        try:
            with entorno_vigilado(sesion.guardia, fabrica_sdk, sesion.intentos_citas):
                if comando == "hasta-decision":
                    _paso_hasta_decision(sesion, args.reiniciar)
                elif comando == "rehacer":
                    _paso_rehacer(sesion, args.veces, args.instruccion)
                elif comando == "decidir":
                    _paso_decidir(sesion, decision)
                elif comando == "extremo-a-extremo":
                    _paso_hasta_decision(sesion, args.reiniciar)
                    if sesion.estado_final == "esperando_decision" and not sesion.parada:
                        _paso_decidir(sesion, decision)
                else:
                    _paso_continuar(sesion)
        except ErrorUso as e:
            sesion.error = str(e)
            sesion.parada = sesion.parada or "rechazado"
        reporte = _escribir_reporte(sesion, CONTADOS[comando], args.salida)
    _imprimir_resumen(reporte)
    print(f"Reporte: {args.salida or sesion.carpeta / f'reporte_{comando}.json'}")
    return sesion.codigo(reporte["veredicto"])


class _Espia(llm.FakeClient):
    def __init__(self, registro: list[dict]) -> None:
        super().__init__()
        self.registro = registro

    def estructurado(self, nodo, system, user, schema, cfg):
        self.registro.append({"nodo": nodo, "system": system, "user": user, "max_tokens": cfg.llm.max_tokens})
        return super().estructurado(nodo, system, user, schema, cfg)


def _entrada(args: argparse.Namespace) -> int:
    fijar_entorno()
    cs = caso_sintetico()
    registro: list[dict] = []
    original = llm.cliente_para
    with tempfile.TemporaryDirectory(prefix="prueba_real_entrada_") as tmp:
        tmp = Path(tmp)
        cs.generar(tmp)
        cs.preparar(tmp, "fake")
        llm.cliente_para = lambda cfg: _Espia(registro)
        try:
            resultados = [api.nuevo(tmp), api.iniciar(tmp), api.decidir(tmp, cs.DECISION_POR_DEFECTO)]
        finally:
            llm.cliente_para = original
    fallido = next((r for r in resultados if not r.get("ok")), None)
    if fallido:
        print(f"La corrida simulada falló: {fallido.get('error')}", file=sys.stderr)
        return SALIDA_FALLA
    print("Entrada por nodo (sin llamar a la API; el modelo no interviene):")
    p = PRECIOS[MODELOS_PERMITIDOS[0]]
    for nodo in NODOS_LLM:
        llamadas = [r for r in registro if r["nodo"] == nodo]
        if not llamadas:
            continue
        primera = llamadas[0]
        chars = len(primera["system"]) + len(primera["user"])
        cota = costo_usd(MODELOS_PERMITIDOS[0], math.ceil(chars / 2), primera["max_tokens"])
        exactitud = "exacto" if nodo == "apertura" else "aproximado (depende de la salida del paso anterior, aquí simulada)"
        print(
            f"- {nodo}: system={len(primera['system'])} chars, user={len(primera['user'])} chars, "
            f"~{chars // 4} tokens estimados (chars/4), cota de la guardia {math.ceil(chars / 2)} tokens (chars/2), "
            f"peor caso por llamada US${cota:.4f} (entrada a US${p['entrada']}/MTok + max_tokens {primera['max_tokens']} a US${p['salida']}/MTok); "
            f"{len(llamadas)} llamada(s) simuladas; {exactitud}"
        )
        if args.texto:
            print(f"\n----- {nodo}: SYSTEM -----\n{primera['system']}\n----- {nodo}: USER -----\n{primera['user']}\n")
    return SALIDA_OK


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Prueba real controlada con el caso sintético (único permitido) y claude-sonnet-5-5 (único modelo permitido). "
            f"El gasto acumulado es global (se guarda en {RUTA_GASTO}, sin importar --carpeta) y los topes cuentan sobre él. "
            "No lance más de una instancia a la vez: el script lo bloquea y rechaza la segunda. " + NOTA_PRECIO_CACHE
        )
    )
    p.add_argument("comando", choices=("entrada", "hasta-decision", "rehacer", "decidir", "extremo-a-extremo", "continuar"))
    p.add_argument("--carpeta", type=Path, default=CARPETA_DEFECTO, help=f"Carpeta del caso sintético (por defecto {CARPETA_DEFECTO})")
    p.add_argument("--parada-suave", type=float, default=PARADA_SUAVE_DEFECTO, help="US$ acumulados a partir de los cuales no se inicia otro paso")
    p.add_argument("--aborto-duro", type=float, default=TOPE_DURO_MAXIMO, help=f"US$ acumulados que no se pueden superar (máximo {TOPE_DURO_MAXIMO})")
    p.add_argument("--salida", type=Path, help="Archivo JSON del reporte (el .md se escribe al lado); por defecto en la carpeta del caso")
    p.add_argument("--reiniciar", action="store_true", help="Descarta el hilo pagado del caso y empieza de nuevo (hasta-decision y extremo-a-extremo)")
    p.add_argument("--veces", type=int, default=1, help="Cantidad de rehacer en esta invocación (tope total por caso: 3)")
    p.add_argument("--instruccion", default=INSTRUCCION_REHACER, help="Instrucción enviada al modelo en rehacer")
    p.add_argument("--decision", type=Path, help="JSON de la decisión (por defecto la del caso sintético)")
    p.add_argument("--texto", action="store_true", help="Con entrada: imprime system y user completos")
    return p


def main(argv: list[str] | None = None, *, fabrica_sdk: Callable[[], Any] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _entrada(args) if args.comando == "entrada" else _pagado(args, fabrica_sdk)
    except ErrorUso as e:
        print(f"RECHAZADO: {redactar(str(e))}", file=sys.stderr)
        return SALIDA_USO
    except Exception:
        print(redactar(traceback.format_exc()), file=sys.stderr)
        return SALIDA_FALLA


if __name__ == "__main__":
    sys.exit(main())
