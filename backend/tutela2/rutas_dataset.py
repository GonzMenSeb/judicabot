from __future__ import annotations

import csv
import logging

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from tutela2 import citas
from tutela2.config import Config

log = logging.getLogger("tutela2.rutas_dataset")

router = APIRouter()

MAX_BYTES_DATASET = 32 * 1024 * 1024


class EstadoDataset(BaseModel):
    vigente: bool
    url: str


@router.get("/api/dataset", response_model=EstadoDataset)
def estado_dataset() -> EstadoDataset:
    cfg = Config()
    return EstadoDataset(vigente=citas.dataset_vigente(cfg), url=cfg.dataset_csv_url)


@router.put("/api/dataset", status_code=204, response_class=Response)
async def subir_dataset(archivo: UploadFile = File(...)) -> Response:
    datos = await archivo.read(MAX_BYTES_DATASET + 1)
    if len(datos) > MAX_BYTES_DATASET:
        raise HTTPException(413, "El dataset excede el tamaño máximo permitido.")
    try:
        await run_in_threadpool(citas.guardar_dataset, datos, citas.ruta_dataset(Config()))
    except (ValueError, csv.Error) as e:
        raise HTTPException(422, f"El archivo no es el dataset de sentencias de la Corte: {e}") from e
    log.info("Dataset de sentencias recibido desde el navegador (%d bytes)", len(datos))
    return Response(status_code=204)
