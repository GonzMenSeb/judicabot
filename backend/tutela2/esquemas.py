from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from tutela2.models import ResultadoDecision, SustitutivaDecision

# --- casos (B1) ---


class DatosSegunda(BaseModel):
    """Datos propios de la segunda instancia para filtrar la lista de casos (ver resumen_segunda)."""

    # Los cinco valores de jev_metadatos.SENTIDOS, en su orden (lo verifica test_resumen_segunda).
    decision_a_quo: Literal["ampara", "niega", "improcedente", "carencia_actual_de_objeto", "otro"] | None
    impugnante: Literal["accionante", "accionada", "vinculada", "otro", "varios"] | None
    resultado: ResultadoDecision | None
    sustitutiva: SustitutivaDecision | None
    derechos: list[str]
    pruebas_nuevas: bool | None
    n_citas_revisar: int | None
    jev_discrepa: bool | None


_FECHA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
INICIO_MIN = date(2000, 1, 1)
INICIO_MAX = date(2100, 12, 31)


class Termino(BaseModel):
    """Término para fallar de un caso: el despacho recibió el expediente el día `inicio` y cuenta con `dias`.

    Los días se cuentan desde el día siguiente a `inicio`, en días hábiles (sin fines de semana ni festivos
    colombianos) o calendario (si vence en un día no hábil, pasa al siguiente hábil). Ver tutela2.termino.
    """

    inicio: str
    dias: Annotated[int, Field(ge=1, le=365, strict=True)]
    unidad: Literal["habiles", "calendario"]

    @field_validator("inicio")
    @classmethod
    def _inicio_valido(cls, v: str) -> str:
        if not _FECHA_ISO.fullmatch(v):
            raise ValueError("debe ser una fecha con formato AAAA-MM-DD")
        try:
            dia = date.fromisoformat(v)
        except ValueError:
            raise ValueError("no es una fecha real") from None
        if not INICIO_MIN <= dia <= INICIO_MAX:
            raise ValueError(f"debe estar entre {INICIO_MIN.isoformat()} y {INICIO_MAX.isoformat()}")
        return dia.isoformat()


class TerminoRespuesta(BaseModel):
    """GET/PUT /api/casos/{id}/termino: el término vigente y su vencimiento calculado hoy.

    termino es el guardado o, si no hay, el que se propone a partir de la fecha de reparto (por_defecto True).
    Sin fecha de reparto ni término guardado, termino, vence y dias_restantes son None. vence y dias_restantes
    también son None si el caso ya terminó. dias_restantes: ver tutela2.termino.plazo.
    """

    termino: Termino | None
    por_defecto: bool
    fecha_reparto: str | None
    vence: str | None
    dias_restantes: int | None


class CasoResumen(BaseModel):
    id: str
    nombre: str
    proceso: Literal["segunda"]
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
    segunda: DatosSegunda | None
    creado: str | None
    termino: Termino | None
    vence: str | None
    dias_restantes: int | None


class CasoCreado(BaseModel):
    id: str
    n_insumos: int


class CasoEliminado(BaseModel):
    """DELETE /api/casos/{id}: papelera es la entrada <id>@<sello> de CASOS_DIR/.papelera que sirve para restaurarlo."""

    id: str
    papelera: str


class CasoRestaurado(BaseModel):
    id: str


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
