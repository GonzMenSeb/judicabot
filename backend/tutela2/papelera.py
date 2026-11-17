"""Papelera de casos eliminados: CASOS_DIR/.papelera/<id>@<sello>.

<sello> es la hora UTC de la eliminación (AAAAMMDDTHHMMSSffffffZ). Las entradas viven DIAS_PAPELERA días y luego
se purgan; las que tienen un nombre que no se puede interpretar no se tocan. Restaurar a mano es mover la entrada a
CASOS_DIR/<id>.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("tutela2.papelera")

CARPETA = ".papelera"
DIAS_PAPELERA = 30
FORMATO_SELLO = "%Y%m%dT%H%M%S%fZ"
_SELLO = re.compile(r"\d{8}T\d{12}Z")
_PURGA = threading.Lock()


def carpeta(raiz: Path) -> Path:
    return Path(raiz) / CARPETA


def nombre_entrada(caso_id: str, ahora: datetime | None = None) -> str:
    return f"{caso_id}@{(ahora or datetime.now(timezone.utc)).strftime(FORMATO_SELLO)}"


def interpretar(entrada: str) -> tuple[str, datetime] | None:
    if "/" in entrada or "\\" in entrada or "\x00" in entrada or entrada.startswith("."):
        return None
    caso_id, arroba, sello = entrada.rpartition("@")
    if not arroba or not caso_id or not _SELLO.fullmatch(sello):
        return None
    try:
        return caso_id, datetime.strptime(sello, FORMATO_SELLO).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ids(raiz: Path) -> set[str]:
    """Ids ocupados por la papelera: los de toda entrada <id>@..., aunque su sello no se pueda interpretar."""
    try:
        with os.scandir(carpeta(raiz)) as entradas:
            return {caso_id for e in entradas if not e.name.startswith(".") and (caso_id := e.name.rpartition("@")[0])}
    except FileNotFoundError:
        return set()


def mover(raiz: Path, caso_id: str) -> str:
    destino = carpeta(raiz)
    destino.mkdir(exist_ok=True)
    entrada = nombre_entrada(caso_id)
    os.rename(Path(raiz) / caso_id, destino / entrada)
    return entrada


def entrada_existente(raiz: Path, entrada: str) -> tuple[str, Path] | None:
    datos = interpretar(entrada)
    if datos is None:
        return None
    ruta = carpeta(raiz) / entrada
    return (datos[0], ruta) if ruta.is_dir() and not ruta.is_symlink() else None


def purgar(raiz: Path, ahora: datetime | None = None) -> list[str]:
    limite = (ahora or datetime.now(timezone.utc)) - timedelta(days=DIAS_PAPELERA)
    borradas: list[str] = []
    with _PURGA:
        try:
            with os.scandir(carpeta(raiz)) as it:
                entradas = list(it)
        except FileNotFoundError:
            return borradas
        for e in entradas:
            datos = interpretar(e.name)
            if datos is None or datos[1] >= limite:
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    shutil.rmtree(e.path)
                else:
                    os.unlink(e.path)
            except OSError:
                log.warning("No se pudo purgar %s de la papelera", e.name, exc_info=True)
                continue
            borradas.append(e.name)
    if borradas:
        log.info("Papelera: se purgaron %d entradas", len(borradas))
    return borradas
