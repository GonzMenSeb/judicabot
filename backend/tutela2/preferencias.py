from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from tutela2 import config as cfgmod

log = logging.getLogger("tutela2.preferencias")

ARCHIVO = ".preferencias.json"
MAX_TOKENS = 64000
MAX_REINTENTOS = 5

Modelo = Literal[cfgmod.MODELOS]
Modo = Literal["apagado", "sombra", "relleno"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

_SOLO_LECTURA = ("modelos", "api_key", "jev_key")
_VARIABLES = {
    ("modelo",): "TUTELA2_MODELO",
    ("jev", "modo"): "TUTELA2_JEV_MODO",
    ("jev", "umbral"): "TUTELA2_JEV_UMBRAL",
    ("effort",): "TUTELA2_EFFORT",
    ("max_tokens",): "TUTELA2_MAX_TOKENS",
    ("max_retries",): "TUTELA2_MAX_RETRIES",
}

_LOCK = threading.RLock()
_APLICADAS: dict[str, str] = {}


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JevPreferencias(_Estricto):
    modo: Modo | None = None
    umbral: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None


class Preferencias(_Estricto):
    modelo: Modelo | None = None
    jev: JevPreferencias = Field(default_factory=JevPreferencias)
    effort: Effort | None = None
    max_tokens: Annotated[int, Field(ge=1, le=MAX_TOKENS)] | None = None
    max_retries: Annotated[int, Field(ge=0, le=MAX_REINTENTOS)] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalizar(cls, datos: Any) -> Any:
        if not isinstance(datos, dict):
            return datos
        datos = {k: v for k, v in datos.items() if k not in _SOLO_LECTURA}
        if datos.get("jev") is None:
            datos.pop("jev", None)
        return datos

    @field_validator("max_tokens", "max_retries", mode="before")
    @classmethod
    def _sin_booleanos(cls, valor: Any) -> Any:
        if isinstance(valor, bool):
            raise PydanticCustomError("int_parsing", "debe ser un número entero")
        return valor


def _a_dict(prefs: Preferencias) -> dict[str, Any]:
    datos = prefs.model_dump(exclude_none=True)
    if not datos.get("jev"):
        datos.pop("jev", None)
    return datos


def _quitar(datos: dict[str, Any], ruta: tuple[Any, ...]) -> None:
    for parte in ruta[:-1]:
        datos = datos.get(parte) if isinstance(datos, dict) else None
        if not isinstance(datos, dict):
            return
    if ruta and isinstance(datos, dict):
        datos.pop(ruta[-1], None)


def _depurar(bruto: Any, origen: str) -> Preferencias:
    if not isinstance(bruto, dict):
        return Preferencias()
    bruto = copy.deepcopy(bruto)
    for _ in range(16):
        try:
            return Preferencias.model_validate(bruto)
        except ValidationError as exc:
            for e in exc.errors():
                log.warning("Se ignora la preferencia %s de %s: %s", ".".join(map(str, e["loc"])), origen, e["type"])
                _quitar(bruto, e["loc"])
    return Preferencias()


def leer(archivo: Path) -> Preferencias:
    try:
        bruto = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Preferencias()
    return _depurar(bruto, archivo.name)


def _fusionar(base: dict[str, Any], cambios: dict[str, Any]) -> dict[str, Any]:
    for clave, valor in cambios.items():
        if isinstance(valor, dict) and isinstance(base.get(clave), dict):
            _fusionar(base[clave], valor)
        else:
            base[clave] = valor
    return base


def _escribir(archivo: Path, datos: dict[str, Any]) -> None:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=archivo.parent, prefix=f"{archivo.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        os.replace(tmp, archivo)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def actualizar(archivo: Path, cambios: Preferencias) -> Preferencias:
    with _LOCK:
        datos = _fusionar(_a_dict(leer(archivo)), _a_dict(cambios))
        _escribir(archivo, datos)
        prefs = Preferencias.model_validate(datos)
        aplicar_entorno(prefs)
        return prefs


def aplicar_entorno(prefs: Preferencias) -> None:
    datos = _a_dict(prefs)
    fijar: dict[str, str] = {}
    for ruta, variable in _VARIABLES.items():
        valor: Any = datos
        for parte in ruta:
            valor = valor.get(parte) if isinstance(valor, dict) else None
        if valor is not None:
            fijar[variable] = str(valor)
    with _LOCK:
        for variable, valor in _APLICADAS.items():
            if variable not in fijar and os.environ.get(variable) == valor:
                del os.environ[variable]
        os.environ.update(fijar)
        _APLICADAS.clear()
        _APLICADAS.update(fijar)


def desde_entorno() -> Preferencias:
    bruto: dict[str, Any] = {}
    for ruta, variable in _VARIABLES.items():
        valor = os.environ.get(variable, "").strip()
        if valor:
            destino = bruto
            for parte in ruta[:-1]:
                destino = destino.setdefault(parte, {})
            destino[ruta[-1]] = valor
    return _depurar(bruto, "el entorno")


def superponer(cfg: cfgmod.Config, prefs: Preferencias) -> cfgmod.Config:
    if prefs.modelo is not None:
        cfg.llm.modelo = prefs.modelo
    if prefs.effort is not None:
        cfg.llm.effort = prefs.effort
    if prefs.max_tokens is not None:
        cfg.llm.max_tokens = prefs.max_tokens
    if prefs.max_retries is not None:
        cfg.llm.max_retries = prefs.max_retries
    if prefs.jev.modo is not None:
        cfg.jev.modo = prefs.jev.modo
    if prefs.jev.umbral is not None:
        cfg.jev.umbral_confianza = prefs.jev.umbral
    return cfg
