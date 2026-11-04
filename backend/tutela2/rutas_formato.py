from __future__ import annotations

from typing import Annotated, Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tutela2 import formato_global
from tutela2.config import Despacho
from tutela2.formato_global import CampoFormato, DocumentoFormato
from tutela2.models import limpiar_control

MAX_TEXTO = 500
MAX_LINEAS = 20
MAX_LINEA = 200

Texto = Annotated[str, Field(max_length=MAX_TEXTO)]
Lineas = Annotated[list[Annotated[str, Field(max_length=MAX_LINEA)]], Field(max_length=MAX_LINEAS)]


class DespachoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: Texto
    nombre_corto: Texto
    nombre_cuerpo: Texto
    ciudad: Texto
    juez: Texto
    cargo_juez: Texto
    escribiente: Texto
    cargo_escribiente: Texto
    firmante_oficio: Texto
    cargo_firmante_oficio: Texto
    cargo_evaluador: Texto
    pie: Texto
    correo: Texto
    telefono_correo: Texto
    cierre_fallo: Texto
    cierre_auto: Texto
    pie_fallo: Lineas
    pie_auto: Lineas
    firma_correo: Lineas

    @field_validator("*", mode="before")
    @classmethod
    def _sin_control(cls, v: Any) -> Any:
        return limpiar_control(v)


class FormatoCuerpo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valores: DespachoEntrada
    plantilla_gen: Literal["A", "B"]


class FormatoRespuesta(BaseModel):
    campos: list[CampoFormato]
    valores: Despacho
    plantilla_gen: Literal["A", "B"]
    documentos: list[DocumentoFormato]


class FormatoErrorCampo(BaseModel):
    campo: str
    mensaje: str


class FormatoErroresDetalle(BaseModel):
    errores: list[FormatoErrorCampo]


class FormatoErrores(BaseModel):
    detail: FormatoErroresDetalle


def _errores(errores: Any) -> list[dict[str, str]]:
    from tutela2.server import _mensaje_config

    salida = []
    for e in errores:
        if e["type"] == "json_invalid":
            salida.append({"campo": "", "mensaje": "no es un JSON válido."})
            continue
        loc = [str(p) for p in e["loc"]]
        if loc and loc[0] == "body":
            loc = loc[1:]
        if len(loc) > 1 and loc[0] == "valores":
            loc = loc[1:]
        salida.append({"campo": ".".join(loc), "mensaje": _mensaje_config(e)})
    return salida


class _RutaFormato(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def manejador(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                return JSONResponse({"detail": {"errores": _errores(exc.errors())}}, status_code=422)

        return manejador


router = APIRouter(route_class=_RutaFormato, tags=["formato"])


def _respuesta() -> FormatoRespuesta:
    despacho, plantilla = formato_global.vigente()
    return FormatoRespuesta(
        campos=list(formato_global.CATALOGO),
        valores=despacho,
        plantilla_gen=plantilla,
        documentos=list(formato_global.DOCUMENTOS),
    )


@router.get("/api/formato", response_model=FormatoRespuesta)
def obtener_formato() -> FormatoRespuesta:
    return _respuesta()


@router.put("/api/formato", response_model=FormatoRespuesta, responses={422: {"model": FormatoErrores}})
def guardar_formato(body: FormatoCuerpo) -> FormatoRespuesta:
    formato_global.guardar_formato(Despacho.model_validate(body.valores.model_dump()), body.plantilla_gen)
    return _respuesta()
