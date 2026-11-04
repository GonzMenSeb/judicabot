from __future__ import annotations

import json
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tutela2 import eventos

router = APIRouter()

LATIDO_S = 15.0


class Evento(BaseModel):
    n: int
    t: str
    etapa: Literal["ingesta", "apertura", "consideraciones", "verificacion", "caso_concreto", "documentos", "sistema"]
    tipo: Literal["lee", "razona", "escribe", "verifica", "sistema", "error"]
    texto: str
    datos: dict[str, Any] | None


class EventosJob(BaseModel):
    eventos: list[Evento]
    estado: Literal["corriendo", "terminado", "error"]
    error: str | None


def _cursor(desde: int, ultimo: str | None) -> int:
    try:
        return max(int(ultimo), 0) if ultimo is not None else desde
    except ValueError:
        return desde


def _mensaje(evento: dict[str, Any]) -> str:
    return f"id: {evento['n']}\nevent: evento\ndata: {json.dumps(evento, ensure_ascii=False)}\n\n"


async def flujo(buffer: eventos.Buffer, cursor: int, latido: float = LATIDO_S) -> AsyncIterator[str]:
    while True:
        lista, fin = buffer.leer(cursor)
        if lista:
            cursor = lista[-1]["n"]
            yield "".join(map(_mensaje, lista))
        elif fin is not None:
            yield f"event: fin\ndata: {json.dumps(fin, ensure_ascii=False)}\n\n"
            return
        elif not await buffer.esperar(cursor, latido):
            yield ": latido\n\n"


@router.get(
    "/api/jobs/{job_id}/eventos",
    response_model=EventosJob,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def eventos_job(
    job_id: str,
    desde: int = Query(0, ge=0),
    formato: Literal["sse", "json"] = "sse",
    last_event_id: str | None = Header(None),
) -> Any:
    buffer = eventos.buffer(job_id)
    if buffer is None:
        raise HTTPException(404, "Job no encontrado.")
    cursor = _cursor(desde, last_event_id)
    if formato == "json":
        lista, fin = buffer.leer(cursor)
        return {"eventos": lista, "estado": fin["estado"] if fin else "corriendo", "error": fin["error"] if fin else None}
    return StreamingResponse(
        flujo(buffer, cursor, LATIDO_S),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
