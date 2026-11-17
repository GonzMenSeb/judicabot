from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

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
    advertencias: list[FaltanteDecision]
    encabezado: str
    fecha_fallo: str
    fecha_por_defecto: bool


# --- edición in situ del borrador ---


class PiezaEdicion(BaseModel):
    parrafos: list[str]
    editados: list[int]
    modificada: bool
    avisos: list[str]


class TrozoOk(BaseModel):
    tipo: Literal["ok"]
    parrafos: list[str]


class TrozoConflicto(BaseModel):
    tipo: Literal["conflicto"]
    mio: list[str]
    nuevo: list[str]
    mio_permitido: bool


class ConflictoEdicion(BaseModel):
    pieza: str
    etiqueta: str
    huerfana: bool
    trozos: list[Annotated[TrozoOk | TrozoConflicto, Field(discriminator="tipo")]]


class EdicionesRespuesta(BaseModel):
    editable: bool
    motivo: str | None
    piezas: dict[str, PiezaEdicion]
    conflictos: list[ConflictoEdicion]


class EdicionCuerpo(BaseModel):
    parrafo: int = Field(ge=0)
    original: str
    texto: str


class ResolverCuerpo(BaseModel):
    elecciones: list[Literal["mio", "nuevo"]]
