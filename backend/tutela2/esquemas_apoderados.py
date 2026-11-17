"""Modelos de la API de apoderados y del visor del expediente (contrato con el frontend)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from tutela2.models import Rol, RolParte, TipoPoder

EstadoApoderado = Literal["verificado", "revisar", "no_verificado"]
Fase = Literal["en_cola", "consultando", "necesita_ayuda", "listo"]
EstadoVigencia = Literal[
    "vigente",
    "vigente_obs",
    "no_vigente",
    "no_inscrito",
    "otra_persona",
    "ilegible",
    "inaccesible",
    "sin_cedula",
    "sin_consultar",
]
EstadoPoder = Literal["hallado", "hallado_reserva", "manual", "sin_poder", "ajeno", "descartado"]
EstadoCadena = Literal["confirmada", "contradicha", "sin_certificado", "no_aplica"]
EstadoExtension = Literal["conectada", "desactualizada", "no_conectada"]
ModoConsulta = Literal["extension", "directa", "fake", "apagada"]


class Cotejo(BaseModel):
    """Una comprobación automática: ``ok`` es ``None`` cuando no se pudo cotejar."""

    ok: bool | None
    texto: str


class EvidenciaVista(BaseModel):
    doc_id: str
    documento: str
    rol: Rol | None
    pagina: int
    total_paginas: int | None
    cita: str
    ocr: bool
    inicio: int | None
    fin: int | None


class CadenaVista(BaseModel):
    estado: EstadoCadena
    otorgante: str
    cargo: str
    evidencia: EvidenciaVista | None


class VigenciaVista(BaseModel):
    estado: EstadoVigencia
    fase: Fase
    cedula: str | None
    tarjeta_registro: str | None
    consultado_en: str | None
    origen: Literal["extension", "directa", "manual", "fake"] | None
    certificado_url: str | None
    numero_certificado: str | None
    codigo_verificacion: str | None
    detalle: str
    grave: bool = Field(
        description="La vigencia por sí sola deja al abogado sin verificar (se muestra en rojo): tarjeta no vigente, "
        "o cédula no inscrita que consta en una página del expediente leída sin OCR. Una cédula no inscrita que pudo "
        "leerse o escribirse mal no es grave, aunque el abogado quede sin verificar por otra razón."
    )


class PoderVista(BaseModel):
    estado: EstadoPoder
    tipo: TipoPoder | None
    evidencia: EvidenciaVista | None
    otorgante: str
    parte: str
    cadena: CadenaVista | None
    mencion: EvidenciaVista | None
    documentos_revisados: int
    hay_hallado: bool = Field(
        description="El código halló en el expediente un poder del abogado (aunque se muestre otro o se haya "
        "descartado): «Deshacer el descarte» solo tiene adónde volver si es así."
    )


class ApoderadoVista(BaseModel):
    id: str
    nombre: str
    parte: str
    rol_parte: RolParte
    tipo_persona: Literal["natural", "juridica"]
    estado: EstadoApoderado
    fase: Fase
    motivos: list[str]
    cedula: str | None
    tarjeta: str | None
    vigencia: VigenciaVista
    poder: PoderVista
    cotejos: list[Cotejo]
    revisado: bool
    revision_vencida: bool
    bloquea: bool
    huella: str


class ParteSinApoderadoVista(BaseModel):
    nombre: str
    rol_parte: RolParte
    nota: str


class ConsultaEstado(BaseModel):
    activa: bool
    extension: EstadoExtension
    modo: ModoConsulta
    pausa_hasta: str | None


class ApoderadosRespuesta(BaseModel):
    identificacion: Literal["lista", "no_disponible", "fallida"]
    apoderados: list[ApoderadoVista]
    sin_apoderado: list[ParteSinApoderadoVista]
    alertas: list[str]
    consulta: ConsultaEstado
    bloquea_decision: bool
    editable: bool


class RevisionCuerpo(BaseModel):
    revisado: bool
    nota: str = Field("", max_length=2000)
    huella: str | None = Field(
        None,
        max_length=64,
        description="Huella del estado que vio quien revisa (ApoderadoVista.huella); obligatoria para marcar como revisado.",
    )

    @model_validator(mode="after")
    def _huella_al_marcar(self) -> RevisionCuerpo:
        if self.revisado and not self.huella:
            raise ValueError("Para marcar como revisado hace falta la huella del estado que se revisó.")
        return self


class ConsultarCuerpo(BaseModel):
    ids: list[Annotated[str, Field(max_length=64)]] | None = Field(
        None, max_length=200, description="Apoderados cuya vigencia se consulta; sin ids, todos los del caso."
    )
    forzar: bool = Field(
        False,
        description=(
            "Consultar de nuevo aunque ya haya un resultado, uno en caché o se hayan agotado los intentos del día; "
            "respeta la pausa tras quedar la Rama Judicial sin responder."
        ),
    )


class PaginaExpediente(BaseModel):
    doc_id: str
    documento: str
    rol: Rol
    pagina: int
    total: int
    texto: str
    ocr: bool
    es_pdf: bool
