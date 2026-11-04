from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from tutela2 import config as cfgmod
from tutela2 import preferencias as pref


class IAJev(BaseModel):
    modo: pref.Modo
    umbral: float


class IAEstado(BaseModel):
    modelo: pref.Modelo
    modelos: list[str]
    api_key: bool
    jev_key: bool
    jev: IAJev
    effort: pref.Effort
    max_tokens: int
    max_retries: int


class IAErrorCampo(BaseModel):
    campo: str
    mensaje: str


class IAErroresDetalle(BaseModel):
    errores: list[IAErrorCampo]


class IAErrores(BaseModel):
    detail: IAErroresDetalle


def _mensaje(e: dict[str, Any]) -> str:
    from tutela2.server import _mensaje_config

    tipo = e["type"]
    if tipo == "modelo_no_permitido":
        permitidos = e["ctx"]["permitidos"]
        if not permitidos:
            return f"no hay modelos permitidos en este servidor ({cfgmod.VARIABLE_MODELOS_PERMITIDOS})."
        *cabeza, cola = permitidos
        opciones = f"{', '.join(cabeza)} o {cola}" if cabeza else cola
        return f"debe ser uno de: {opciones}."
    if tipo == "literal_error":
        opciones = str((e.get("ctx") or {}).get("expected", "")).replace("'", "").replace(" or ", " o ")
        return f"debe ser uno de: {opciones}."
    if tipo == "finite_number":
        return "debe ser un número finito."
    if tipo == "json_invalid":
        return "no es un JSON válido."
    if tipo in ("model_attributes_type", "model_type"):
        return "debe ser un objeto."
    return _mensaje_config(e)


def _errores(errores: Any) -> list[dict[str, str]]:
    salida = []
    for e in errores:
        loc = [str(p) for p in e["loc"]]
        if loc and loc[0] == "body":
            loc = [] if e["type"] == "json_invalid" else loc[1:]
        salida.append({"campo": ".".join(loc), "mensaje": _mensaje(e)})
    return salida


class _RutaIA(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def manejador(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                return JSONResponse({"detail": {"errores": _errores(exc.errors())}}, status_code=422)

        return manejador


router = APIRouter(route_class=_RutaIA, tags=["ia"])


def _o(valor: Any, defecto: Any) -> Any:
    return defecto if valor is None else valor


def _estado() -> IAEstado:
    from tutela2 import server

    guardadas = pref.leer(server._preferencias())
    llm, jev = cfgmod.LLMConfig(), cfgmod.JevConfig()
    claves = server.estado_servidor()
    return IAEstado(
        modelo=_o(guardadas.modelo, llm.modelo),
        modelos=list(cfgmod.modelos_permitidos()),
        api_key=claves["api_key"],
        jev_key=claves["jev_key"],
        jev=IAJev(modo=_o(guardadas.jev.modo, jev.modo), umbral=_o(guardadas.jev.umbral, jev.umbral_confianza)),
        effort=_o(guardadas.effort, llm.effort),
        max_tokens=_o(guardadas.max_tokens, llm.max_tokens),
        max_retries=_o(guardadas.max_retries, llm.max_retries),
    )


@router.get("/api/ia", response_model=IAEstado)
def obtener_ia() -> IAEstado:
    return _estado()


@router.put("/api/ia", response_model=IAEstado, responses={422: {"model": IAErrores}})
def guardar_ia(body: pref.Preferencias) -> IAEstado:
    from tutela2 import server

    pref.actualizar(server._preferencias(), body)
    return _estado()
