from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from tutela2 import config as cfgmod

log = logging.getLogger("tutela2.preferencias")

ARCHIVO = ".preferencias.json"
MAX_TOKENS = 64000
MAX_REINTENTOS = 5

Proveedor = Literal["anthropic", "gemini"]
Modelo = Literal[cfgmod.MODELOS]
ModeloGemini = Literal[cfgmod.MODELOS_GEMINI]
Modo = Literal["apagado", "sombra", "relleno"]
Effort = Literal[cfgmod.ESFUERZOS]
RazonamientoGemini = Literal[cfgmod.NIVELES_GEMINI]

COMPLETAS = {"completas": True}
_SOLO_LECTURA = ("modelos", "modelos_gemini", "razonamientos_gemini", "api_key", "gemini_key", "jev_key")
_VARIABLES = {
    ("proveedor",): "TUTELA2_PROVEEDOR_LLM",
    ("modelo",): "TUTELA2_MODELO",
    ("gemini", "modelo"): "TUTELA2_GEMINI_MODELO",
    ("gemini", "razonamiento"): "TUTELA2_GEMINI_RAZONAMIENTO",
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


def _exigir_permitido(valor: Any, proveedor: str) -> Any:
    permitidos = cfgmod.modelos_permitidos(proveedor)
    if isinstance(valor, str) and valor not in permitidos:
        raise PydanticCustomError("modelo_no_permitido", "modelo no permitido", {"permitidos": list(permitidos)})
    return valor


class JevPreferencias(_Estricto):
    modo: Modo | None = None
    umbral: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None


class GeminiPreferencias(_Estricto):
    modelo: ModeloGemini | None = None
    razonamiento: RazonamientoGemini | None = None

    @field_validator("modelo", mode="before")
    @classmethod
    def _modelo_permitido(cls, valor: Any) -> Any:
        return _exigir_permitido(valor, "gemini")

    @field_validator("razonamiento")
    @classmethod
    def _razonamiento_del_modelo(cls, valor: Any, info: ValidationInfo) -> Any:
        if valor is None or "modelo" not in info.data:
            return valor
        modelo = info.data["modelo"]
        if modelo is None:
            if not (info.context or {}).get("completas"):
                return valor
            modelo = cfgmod.MODELO_GEMINI
        admitidos = cfgmod.RAZONAMIENTOS_GEMINI[modelo]
        if valor not in admitidos:
            raise PydanticCustomError(
                "razonamiento_no_admitido", "nivel no admitido por el modelo", {"modelo": modelo, "admitidos": list(admitidos)}
            )
        return valor


class Preferencias(_Estricto):
    proveedor: Proveedor | None = None
    modelo: Modelo | None = None
    gemini: GeminiPreferencias = Field(default_factory=GeminiPreferencias)
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
        for anidado in ("gemini", "jev"):
            if datos.get(anidado) is None:
                datos.pop(anidado, None)
        return datos

    @field_validator("modelo", mode="before")
    @classmethod
    def _modelo_permitido(cls, valor: Any) -> Any:
        return _exigir_permitido(valor, "anthropic")

    @field_validator("max_tokens", "max_retries", mode="before")
    @classmethod
    def _sin_booleanos(cls, valor: Any) -> Any:
        if isinstance(valor, bool):
            raise PydanticCustomError("int_parsing", "debe ser un número entero")
        return valor


def _a_dict(prefs: Preferencias) -> dict[str, Any]:
    datos = prefs.model_dump(exclude_none=True)
    for anidado in ("gemini", "jev"):
        if not datos.get(anidado):
            datos.pop(anidado, None)
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
            return Preferencias.model_validate(bruto, context=COMPLETAS)
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
        prefs = Preferencias.model_validate(datos, context=COMPLETAS)
        _escribir(archivo, datos)
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


def proveedor_activo(prefs: Preferencias) -> str:
    return prefs.proveedor or "anthropic"


def modelo_activo(prefs: Preferencias) -> str:
    if prefs.proveedor == "gemini":
        return prefs.gemini.modelo or cfgmod.MODELO_GEMINI
    return prefs.modelo or cfgmod.LLMConfig().modelo


def superponer(cfg: cfgmod.Config, prefs: Preferencias) -> cfgmod.Config:
    if prefs.proveedor is not None and cfg.llm.proveedor != "fake":
        cfg.llm.proveedor = prefs.proveedor
    if cfg.llm.proveedor == "gemini":
        propio = cfg.llm.modelo in cfgmod.MODELOS_GEMINI
        cfg.llm.modelo = prefs.gemini.modelo or (cfg.llm.modelo if propio else cfgmod.MODELO_GEMINI)
        cfg.llm.effort = prefs.gemini.razonamiento or (cfg.llm.effort if propio else cfgmod.RAZONAMIENTO_GEMINI)
    else:
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
