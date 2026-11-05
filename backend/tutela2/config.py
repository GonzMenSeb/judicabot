from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tutela2.models import limpiar_control

NODOS_LLM = ("apertura", "consideraciones", "caso_concreto")
MODELOS = ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5")
RESPALDO_CLIENTE = {"claude-haiku-5-5": "claude-sonnet-5-5"}
VARIABLE_MODELOS_PERMITIDOS = "TUTELA2_MODELOS_PERMITIDOS"
VARIABLE_CACHE = "TUTELA2_CACHE_DIR"


def _modelos_pedidos() -> set[str]:
    return {m.strip() for m in os.environ.get(VARIABLE_MODELOS_PERMITIDOS, "").split(",") if m.strip()}


def modelos_permitidos() -> tuple[str, ...]:
    """TUTELA2_MODELOS_PERMITIDOS (ids separados por comas) restringe los modelos de MODELOS; apagada, rigen todos."""
    pedidos = _modelos_pedidos()
    return tuple(m for m in MODELOS if m in pedidos) if pedidos else MODELOS


def modelo_permitido(modelo: str) -> bool:
    return not _modelos_pedidos() or modelo in modelos_permitidos()


class LLMConfig(BaseModel):
    proveedor: Literal["anthropic", "fake"] = "anthropic"
    modelo: str = "claude-sonnet-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = 64000
    timeout_s: float = 1200.0
    max_retries: int = 1
    fallbacks_default: bool = True
    modelo_por_nodo: dict[str, str] = {}
    effort_por_nodo: dict[str, str] = {}


class JevConfig(BaseModel):
    modo: Literal["apagado", "sombra", "relleno"] = "apagado"
    modelo: str = "jev-latest"
    umbral_confianza: float = Field(0.9, ge=0, le=1)
    timeout_s: float = Field(60.0, gt=0, allow_inf_nan=False)
    max_chars_cabecera: int = 1500
    max_chars_sentido: int = 2500
    concurrencia: int = 6


class Despacho(BaseModel):
    nombre: str = "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO DE MEDELLÍN"
    nombre_corto: str = "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO"
    nombre_cuerpo: str = "Juzgado Tercero Penal del Circuito con Función de Conocimiento de Medellín"
    ciudad: str = "Medellín"
    juez: str = "SANTIAGO ALEJANDRO CADAVID DUQUE"
    cargo_juez: str = "JUEZ"
    escribiente: str = "John Mendoza"
    cargo_escribiente: str = "Escribiente"
    firmante_oficio: str = "JOHN MANUEL MENDOZA"
    cargo_firmante_oficio: str = "Escribiente"
    cargo_evaluador: str = "Juez 3° Penal del Circuito de Conocimiento"
    pie: str = "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín"
    correo: str = "pcto03med@cendoj.ramajudicial.gov.co"
    telefono_correo: str = "Tel: 6042328525 Ext. 2903"
    cierre_fallo: str = "NOTIFÍQUESE Y CÚMPLASE"
    cierre_auto: str = "NOTIFÍQUESE Y CÚMPLASE"
    pie_fallo: list[str] = [
        "Juzgado Tercero Penal del Circuito con Funciones de Conocimiento Medellín",
        "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19",
        "Correo electrónico: pcto03med@cendoj.ramajudicial.gov.co",
    ]
    pie_auto: list[str] = [
        "Juzgado Tercero Penal del Circuito con Función de Conocimiento, Edificio José Félix de Restrepo Carrera 52 # 42 – 73, Medellín, Antioquia",
        "Correo Electrónico pcto03med@cendoj.ramajudicial.gov.co, Teléfono 2328525 Ext. 92903",
    ]
    firma_correo: list[str] = [
        "Juzgado 3 Penal del Circuito con Funciones",
        "de Conocimiento de Medellín",
    ]

    @field_validator("*", mode="before")
    @classmethod
    def _sin_control(cls, v: Any) -> Any:
        return limpiar_control(v)

    @model_validator(mode="before")
    @classmethod
    def _nombre_corto_heredado(cls, datos: Any) -> Any:
        if isinstance(datos, dict) and "nombre_corto" not in datos and isinstance(datos.get("nombre"), str):
            return {**datos, "nombre_corto": limpiar_control(datos["nombre"]).replace(" DE MEDELLÍN", "")}
        return datos


class Config(BaseModel):
    plantilla_gen: Literal["A", "B"] = "B"
    despacho: Despacho = Despacho()
    llm: LLMConfig = LLMConfig()
    jev: JevConfig = JevConfig()
    max_intentos: int = 3
    ocr: bool = True
    verificar_relatoria: bool = True
    cobertura_ok: float = 0.8
    cobertura_alerta: float = 0.5
    min_citas_ok: int = 2
    min_palabras_cita: int = 25
    ngram: int = 6
    exigir_mp: bool = True
    max_bloques_tematicos: int = 3
    permitir_listas_caso: bool = False
    jaccard_duplicados: float = 0.5
    rango_palabras: dict[str, list[int]] = {
        "antecedentes": [510, 1140],
        "sentencia_impugnada": [165, 560],
        "impugnacion": [155, 830],
        "consideraciones": [600, 2050],
        "caso_concreto": [930, 3280],
    }
    max_chars_documento: int = 120000
    max_chars_documentos_caso: int = 300000
    dataset_csv_url: str = "https://www.datos.gov.co/resource/v2k4-2t8s.csv?$limit=50000"
    cache_dir: str = "~/.cache/tutela2"
    prompts_override: dict[str, str] = {}

    def modelo_para(self, nodo: str) -> str:
        return self.llm.modelo_por_nodo.get(nodo) or self.llm.modelo

    def effort_para(self, nodo: str) -> str:
        return self.llm.effort_por_nodo.get(nodo) or self.llm.effort

    def cache_path(self) -> Path:
        """TUTELA2_CACHE_DIR, si está definida y no vacía, manda sobre cache_dir (los config.json de caso ya guardan el valor por defecto)."""
        p = Path(os.environ.get(VARIABLE_CACHE, "").strip() or self.cache_dir).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p


def cargar(caso_dir: str | Path, entorno: bool = True) -> Config:
    f = Path(caso_dir) / "config.json"
    cfg = Config.model_validate(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else Config()
    if entorno:
        from tutela2 import preferencias

        preferencias.superponer(cfg, preferencias.desde_entorno())
        if os.environ.get("TUTELA2_PROVEEDOR", "").strip() == "fake":
            cfg.llm.proveedor = "fake"
            cfg.verificar_relatoria = False
    return cfg


def guardar(caso_dir: str | Path, cfg: Config) -> None:
    (Path(caso_dir) / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
