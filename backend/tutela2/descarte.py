"""Trabajo que se perdería al volver a procesar un caso, y la copia que se guarda antes de descartarlo.

``nuevo`` (y ``iniciar`` sobre un caso que perdió su historial) borran el hilo, la decisión y las salidas. Este módulo
dice qué hay en disco que valga la pena conservar (``trabajo_previo``, ``trabajo_huerfano``), redacta el aviso que
recibe quien lo pide sin confirmar (``mensaje``, ``detalle``) y, cuando se confirma, copia el caso completo a la
papelera (``respaldar``) para que se pueda restaurar durante ``papelera.DIAS_PAPELERA`` días.

No depende del grafo: el servidor lo usa antes de crear el trabajo y las pruebas del servidor sustituyen ``tutela2.api``.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from tutela2 import papelera

log = logging.getLogger("tutela2.descarte")

CODIGO = "trabajo_previo"
AVANCE, BORRADOR, DECISION, FALLO = (
    "el avance de la redacción",
    "el borrador",
    "la decisión del juez",
    "el fallo con sus documentos",
)
Comando = Literal["nuevo", "iniciar", "revisar"]

_COPIA = f"antes se guarda una copia del caso en la papelera, donde se puede recuperar durante {papelera.DIAS_PAPELERA} días."


class ErrorRespaldo(Exception):
    """No se pudo guardar la copia del caso: no se descarta nada."""


def hilo_con_datos(caso_dir: Path) -> bool:
    """Si ``hilo.sqlite`` tiene algún paso guardado. Un hilo ilegible cuenta como con datos: no se descarta sin confirmar."""
    ruta = Path(caso_dir) / "hilo.sqlite"
    try:
        if not ruta.is_file() or ruta.stat().st_size == 0:
            return False
        # Path.as_uri() codifica ?, # y %, que f"file:{ruta}?mode=ro" interpretaría como parte de la URI.
        conexion = sqlite3.connect(ruta.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return True
    except OSError:
        return False
    try:
        return conexion.execute("SELECT 1 FROM checkpoints LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError as e:
        # Hilo creado sin pasos: tiene el esquema pero ninguna fila (o ni siquiera la tabla).
        return "no such table" not in str(e)
    except sqlite3.DatabaseError:
        return True
    finally:
        conexion.close()


def _hay_archivos(carpeta: Path) -> bool:
    return carpeta.is_dir() and any(p.is_file() for p in carpeta.rglob("*"))


def trabajo_previo(caso_dir: Path, *, con_hilo: bool = True) -> list[str]:
    """Lo que ``nuevo`` descartaría, en el orden del flujo y sin repetir."""
    caso_dir = Path(caso_dir)
    salidas = caso_dir / "salidas"
    trabajo: list[str] = []
    if (salidas / "trabajo" / "previo.docx").exists():
        trabajo.append(BORRADOR)
    elif con_hilo and hilo_con_datos(caso_dir):
        trabajo.append(AVANCE)
    if (caso_dir / "decision.json").exists():
        trabajo.append(DECISION)
    principal = salidas / "02SegundaInstancia" / "C01Principal"
    if (
        _hay_archivos(salidas / "por_radicar")
        or _hay_archivos(salidas / "borradores_correo")
        or (principal.is_dir() and any(principal.glob("*FalloSegunda*.docx")))
    ):
        trabajo.append(FALLO)
    return trabajo


def trabajo_huerfano(caso_dir: Path) -> list[str]:
    """Trabajo en disco sin un hilo que lo respalde (el historial se perdió); vacío si el hilo tiene datos."""
    if hilo_con_datos(caso_dir):
        return []
    return trabajo_previo(caso_dir, con_hilo=False)


def enumerar(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return f"{', '.join(partes[:-1])} y {partes[-1]}"


def mensaje(trabajo: list[str], cmd: Comando) -> str:
    cosas = enumerar(trabajo)
    if cmd == "nuevo":
        return f"Este caso ya tiene {cosas}. Volver a procesar los documentos los descarta; {_COPIA}"
    anterior = f"Este caso tiene {cosas} de una redacción anterior cuyo historial se perdió."
    if cmd == "iniciar":
        return f"{anterior} Iniciar la redacción los descarta; {_COPIA}"
    return (
        f"{anterior} Para cambiar los documentos o los datos del auto hay que volver a procesar los documentos, "
        "lo que los descarta."
    )


def detalle(trabajo: list[str], cmd: Comando) -> dict:
    return {"codigo": CODIGO, "mensaje": mensaje(trabajo, cmd), "trabajo": trabajo}


def respaldar(caso_dir: Path) -> str:
    """Copia el caso completo a ``<raíz>/.papelera/<id>@<sello>`` y devuelve el nombre de la entrada.

    Se copia a una carpeta oculta y solo al terminar se renombra: una copia a medias (disco lleno, proceso
    interrumpido) nunca queda con el nombre de una entrada restaurable. Si falla, no queda rastro y se lanza
    ``ErrorRespaldo``, de modo que quien descarta no borra nada. Restaurar es lo de siempre (``papelera``): la copia
    conserva el id del caso, así que hay que eliminar o mover antes el caso actual.
    """
    caso_dir = Path(caso_dir)
    raiz = caso_dir.parent
    destino = papelera.carpeta(raiz)
    entrada = papelera.nombre_entrada(caso_dir.name)
    provisional = destino / f".copiando-{uuid.uuid4().hex}"
    try:
        if not caso_dir.is_dir():
            raise FileNotFoundError(f"No existe la carpeta del caso: {caso_dir}")
        destino.mkdir(exist_ok=True)
        shutil.copytree(caso_dir, provisional, symlinks=True)
        provisional.rename(destino / entrada)
    except Exception as e:
        shutil.rmtree(provisional, ignore_errors=True)
        raise ErrorRespaldo(f"No se pudo guardar la copia del caso en la papelera, así que no se descartó nada: {e}") from e
    try:
        papelera.purgar(raiz)
    except Exception:
        log.warning("No se pudo purgar la papelera", exc_info=True)
    log.info("Caso %s copiado a la papelera como %s", caso_dir.name, entrada)
    return entrada
