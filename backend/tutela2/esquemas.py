from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
