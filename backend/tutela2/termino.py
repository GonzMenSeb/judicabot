"""Término para fallar de cada caso: datos propios del caso, término efectivo y plazo calculado al día.

<caso>/.datos_caso.json guarda, con escritura atómica:
  proceso  tipo de proceso; hoy siempre "segunda".
  creado   instante en que se creó el caso (ISO 8601 con desfase), o null si el caso es anterior a este archivo.
  termino  {inicio, dias, unidad} confirmado por el usuario en Documentos, o null mientras no lo haya fijado.
Si el archivo falta o está corrupto se leen los valores por defecto (proceso "segunda", creado y termino null).

Término (esquemas.Termino): inicio es el día en que el despacho recibió el expediente ("Recibido el"), dias va de
1 a 365 y unidad es "habiles" o "calendario". Los días se cuentan desde el día siguiente a inicio:
  habiles     vence el dias-ésimo día hábil posterior a inicio (festivos.es_habil: sin sábados, domingos ni
              festivos colombianos).
  calendario  vence en inicio + dias; si ese día no es hábil, pasa al siguiente día hábil.

Sin término guardado, efectivo propone inicio = fecha de reparto (el override fecha_reparto de auto.json, si es una
fecha válida entre 2000 y 2100, o si no la del acta de reparto de segunda en los metadatos), 20 días hábiles. Sin fecha de reparto
no hay término.

plazo(termino, estado, hoy) calcula vence y dias_restantes respecto de hoy; depende de la fecha, así que nunca se
guarda en el caché del resumen (resumen_caso._completo lo agrega en vivo). hoy() usa la hora de Colombia: el
contenedor corre en UTC y por la tarde ya sería el día siguiente.

Nada de aquí lanza por datos corruptos: una lista de casos entera no debe caerse por el archivo de un caso.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tutela2 import festivos
from tutela2.esquemas import INICIO_MAX, INICIO_MIN, Termino
from tutela2.letras import _a_fecha

log = logging.getLogger("tutela2.termino")

ARCHIVO = ".datos_caso.json"
AUTO = "auto.json"
PROCESO = "segunda"
PROCESOS = (PROCESO,)
DIAS_POR_DEFECTO = 20
UNIDAD_POR_DEFECTO = "habiles"
UNIDADES = ("habiles", "calendario")
ZONA = timezone(timedelta(hours=-5))


def ahora() -> datetime:
    return datetime.now(ZONA)


def hoy() -> date:
    return ahora().date()


def _a_termino(valor: Any) -> dict[str, Any] | None:
    try:
        return Termino.model_validate(valor).model_dump()
    except ValidationError:
        return None


def _a_creado(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    try:
        datetime.fromisoformat(valor)
    except ValueError:
        return None
    return valor


def leer(caso_dir: Path) -> dict[str, Any]:
    """Los datos propios del caso; si el archivo falta o está corrupto, los valores por defecto."""
    try:
        bruto = json.loads((Path(caso_dir) / ARCHIVO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bruto = None
    if not isinstance(bruto, dict):
        bruto = {}
    proceso = bruto.get("proceso")
    return {
        "proceso": proceso if proceso in PROCESOS else PROCESO,
        "creado": _a_creado(bruto.get("creado")),
        "termino": _a_termino(bruto.get("termino")),
    }


def guardar(caso_dir: Path, datos: dict[str, Any]) -> None:
    """Escribe .datos_caso.json de forma atómica (archivo temporal y os.replace)."""
    caso_dir = Path(caso_dir)
    documento = {"proceso": datos["proceso"], "creado": datos["creado"], "termino": datos["termino"]}
    tmp = caso_dir / f"{ARCHIVO}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_text(json.dumps(documento, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, caso_dir / ARCHIVO)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def crear(caso_dir: Path) -> None:
    """Datos de un caso nuevo: proceso, instante de creación y término todavía sin fijar."""
    guardar(caso_dir, {"proceso": PROCESO, "creado": ahora().isoformat(timespec="seconds"), "termino": None})


def guardar_termino(caso_dir: Path, termino: Termino) -> None:
    """Fija el término del caso conservando proceso y creado."""
    guardar(caso_dir, {**leer(caso_dir), "termino": termino.model_dump()})


def _fecha_de_inicio(valor: Any) -> date | None:
    """Una fecha que un Termino aceptaría como inicio (INICIO_MIN..INICIO_MAX), o None."""
    dia = _a_fecha(valor)
    return dia if dia is not None and INICIO_MIN <= dia <= INICIO_MAX else None


def _override_reparto(caso_dir: Path) -> date | None:
    try:
        bruto = json.loads((Path(caso_dir) / AUTO).read_text(encoding="utf-8"))
        return _fecha_de_inicio(bruto.get("fecha_reparto"))
    except (OSError, ValueError, AttributeError):
        return None


def _reparto_del_acta(respuesta: Any) -> date | None:
    try:
        return _fecha_de_inicio(respuesta["resumen"]["metadatos"]["fechas"]["reparto_2a"])
    except (TypeError, KeyError, AttributeError):
        return None


def fecha_reparto(caso_dir: Path, respuesta: Any) -> date | None:
    """La fecha de reparto: el override de auto.json si es una fecha válida; si no, la del acta de reparto de segunda.

    respuesta es lo que devuelve api.estado (o None si no se pudo leer).
    """
    return _override_reparto(caso_dir) or _reparto_del_acta(respuesta)


def efectivo(caso_dir: Path, respuesta: Any) -> tuple[dict[str, Any] | None, bool]:
    """(término, por_defecto): el guardado, o el propuesto desde la fecha de reparto, o (None, False) si no hay fecha."""
    guardado = leer(caso_dir)["termino"]
    if guardado is not None:
        return guardado, False
    reparto = fecha_reparto(caso_dir, respuesta)
    if reparto is None:
        return None, False
    propuesto = _a_termino({"inicio": reparto.isoformat(), "dias": DIAS_POR_DEFECTO, "unidad": UNIDAD_POR_DEFECTO})
    return propuesto, propuesto is not None


def _vence(inicio: date, dias: int, unidad: str) -> date:
    if unidad == "habiles":
        return festivos.sumar_habiles(inicio, dias)
    vence = inicio + timedelta(days=dias)
    return vence if festivos.es_habil(vence) else festivos.siguiente_habil(vence)


@lru_cache(maxsize=4096)
def _calcular(inicio: str, dias: int, unidad: str, dia: date) -> tuple[str, int]:
    if unidad not in UNIDADES or isinstance(dias, bool) or not isinstance(dias, int) or not 1 <= dias <= 365:
        raise ValueError(f"término inválido: {dias!r} {unidad!r}")
    vence = _vence(date.fromisoformat(inicio), dias, unidad)
    en_habiles = unidad == "habiles"
    if dia < vence:
        restantes = festivos.habiles_entre(dia, vence) if en_habiles else (vence - dia).days
    elif dia > vence:
        # Un vencimiento seguido de fin de semana o festivo no tiene días hábiles de atraso: sigue siendo negativo.
        atraso = max(1, festivos.habiles_entre(vence, dia)) if en_habiles else (dia - vence).days
        restantes = -atraso
    else:
        restantes = 0
    return vence.isoformat(), restantes


def plazo(termino: dict[str, Any] | None, estado: str | None, hoy: date) -> dict[str, Any] | None:
    """{vence, dias_restantes} del término respecto de hoy, o None si el caso terminó o no hay término.

    dias_restantes cuenta en la unidad del término: días hábiles posteriores a hoy hasta vence inclusive (habiles) o
    días corridos (calendario). Es 0 el día del vencimiento, positivo antes y negativo (días de atraso) después.
    """
    if estado == "terminado" or not termino:
        return None
    try:
        vence, restantes = _calcular(termino["inicio"], termino["dias"], termino["unidad"], hoy)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return {"vence": vence, "dias_restantes": restantes}


def describir(caso_dir: Path, respuesta: Any) -> dict[str, Any]:
    """Cuerpo de GET/PUT /api/casos/{id}/termino (esquemas.TerminoRespuesta). respuesta es lo de api.estado o None."""
    termino, por_defecto = efectivo(caso_dir, respuesta)
    estado = respuesta.get("estado") if isinstance(respuesta, dict) else None
    reparto = fecha_reparto(caso_dir, respuesta)
    calculado = plazo(termino, estado, hoy()) or {"vence": None, "dias_restantes": None}
    return {
        "termino": termino,
        "por_defecto": por_defecto,
        "fecha_reparto": reparto.isoformat() if reparto else None,
        **calculado,
    }
