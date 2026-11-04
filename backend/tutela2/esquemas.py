from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# --- casos (B1) ---


class CasoResumen(BaseModel):
    id: str
    nombre: str
    radicado: str | None
    accionante: str | None
    accionadas: list[str]
    juzgado_a_quo: str | None
    estado: Literal["sin_iniciar", "revision", "incompleto", "esperando_decision", "terminado", "error", "corriendo"]
    etapa: Literal[0, 1, 2, 3, 4]
    siguiente_paso: str
    n_insumos: int
    n_alertas: int
    job_activo: str | None
    actualizado: str


class CasoCreado(BaseModel):
    id: str
    n_insumos: int


# --- vista del RESUELVE (B5) ---


class NumeralVista(BaseModel):
    clave: str
    texto: str
    negritas: list[str]


class FaltanteDecision(BaseModel):
    campo: str
    mensaje: str


class DecisionVistaRespuesta(BaseModel):
    numerales: list[NumeralVista]
    faltantes: list[FaltanteDecision]
    errores: list[str]
