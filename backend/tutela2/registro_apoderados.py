"""Registro por caso de los apoderados: espejo de la identificación, consultas de vigencia,
revisiones y ajustes.

Vive en ``<caso>/apoderados/registro.json``: fuera de ``insumos/`` (la ingesta lo leería) y de
``salidas/`` (se lista, se comprime y se borra). ``api.nuevo`` borra la carpeta entera con
``borrar``. Toda escritura pasa por un candado por caso y es atómica (``vista.guardar``); nada de
lo que se guarda aquí vuelve a correr el grafo ni toca el previo.

Las claves de ``consultas`` son números de cédula: este archivo es dato del caso, igual que la
identificación del grafo, pero ninguna cédula va a un registro de log ni a una ruta. Los PDF de
los certificados van en ``apoderados/certificados/`` con nombres que nunca llevan la cédula
(``guardar_certificado``), y se borran cuando ninguna consulta los usa.

Un registro que existe pero no se puede leer o no es válido (por ejemplo, escrito por una versión
más nueva antes de volver a una anterior, o editado a mano) falla cerrado: ``leer`` lanza
``RegistroInvalido``, nadie lo reescribe (se perderían consultas, revisiones y ajustes) y la
compuerta de la decisión queda bloqueada hasta que alguien lo repare o ``nuevo`` lo borre.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, ValidationError

from tutela2 import vista
from tutela2.models import EvidenciaDoc, Identificacion
from tutela2.vigencia import CertificadoVigencia

log = logging.getLogger("tutela2")

CARPETA = "apoderados"
ARCHIVO = "registro.json"
CERTIFICADOS = "certificados"
VERSION = 1

EstadoConsulta = Literal["vigente", "vigente_obs", "no_vigente", "no_inscrito", "otra_persona", "ilegible", "inaccesible"]
OrigenConsulta = Literal["extension", "directa", "manual", "fake"]


class ConsultaVigencia(BaseModel):
    """Resultado de consultar el certificado de vigencia de una cédula."""

    estado: EstadoConsulta
    origen: OrigenConsulta
    consultado_en: str
    certificado: str | None = None
    """Ruta del PDF relativa a ``<caso>/apoderados/``; ``None`` si no hay PDF guardado."""
    sha256: str | None = None
    datos: CertificadoVigencia | None = None
    detalle: str = ""
    intentos_auto: int = 0
    proximo_intento: str | None = None


class Revision(BaseModel):
    """Marca de revisión humana de un apoderado, atada a la huella del estado que se revisó."""

    revisado: bool
    en: str
    huella: str
    nota: str = ""


class Ajuste(BaseModel):
    """Correcciones a mano sobre la identificación de un apoderado.

    ``cedula`` la pone quien revisa o la subida de un certificado, solo si el expediente no la trae;
    ``nota`` y ``en`` son la razón que dio quien corrigió y cuándo lo hizo por última vez (no entran
    en la huella: lo que la cambia es la corrección misma)."""

    cedula: str | None = None
    poder_manual: EvidenciaDoc | None = None
    poder_descartado: bool = False
    nota: str = ""
    en: str | None = None


class Registro(BaseModel):
    version: int = VERSION
    identificacion: Identificacion | None = None
    consultas: dict[str, ConsultaVigencia] = {}
    revisiones: dict[str, Revision] = {}
    ajustes: dict[str, Ajuste] = {}


class RegistroInvalido(Exception):
    """El registro del caso existe pero no se puede leer o no es válido; no se reescribe ni se ignora."""

    def __init__(self) -> None:
        super().__init__(
            f"El registro de apoderados del caso ({CARPETA}/{ARCHIVO}) está dañado y no se puede leer. No se reescribe, "
            "para no perder consultas ni revisiones, y la decisión queda bloqueada hasta que se repare."
        )


_candados: dict[Path, threading.Lock] = {}
_candado_mapa = threading.Lock()


def _candado(caso_dir: Path) -> threading.Lock:
    clave = Path(caso_dir).resolve()
    with _candado_mapa:
        return _candados.setdefault(clave, threading.Lock())


def carpeta(caso_dir: Path) -> Path:
    return Path(caso_dir) / CARPETA


def ruta(caso_dir: Path) -> Path:
    return carpeta(caso_dir) / ARCHIVO


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def leer(caso_dir: Path) -> Registro:
    """El registro del caso; uno vacío si no existe.

    Lanza ``RegistroInvalido`` si existe pero no se puede leer o no es válido. El detalle del error
    de validación no se registra ni se encadena: repetiría valores del archivo, cédulas incluidas."""
    try:
        texto = ruta(caso_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return Registro()
    except (OSError, UnicodeDecodeError) as e:
        log.warning("%s: no se pudo leer el registro de apoderados (%s)", Path(caso_dir).name, type(e).__name__)
        raise RegistroInvalido() from None
    try:
        return Registro.model_validate_json(texto)
    except ValidationError:
        log.warning(
            "%s: el registro de apoderados no es válido; no se reescribe y la decisión queda bloqueada", Path(caso_dir).name
        )
        raise RegistroInvalido() from None


def _guardar(caso_dir: Path, reg: Registro, crear: bool) -> bool:
    """Escribe el registro; requiere tener el candado del caso. ``False`` si la carpeta ya no está."""
    dir_apoderados = carpeta(caso_dir)
    if not dir_apoderados.is_dir():
        if not crear:
            return False
        dir_apoderados.mkdir(exist_ok=True)
    try:
        vista.guardar(reg.model_dump(mode="json"), ruta(caso_dir))
    except FileNotFoundError:
        if crear:
            raise
        return False
    return True


def actualizar(caso_dir: Path, fn: Callable[[Registro], Registro | None], *, crear: bool = False) -> Registro | None:
    """Lee, modifica con ``fn`` y guarda el registro bajo el candado del caso.

    ``fn`` recibe el registro actual y lo modifica en su sitio o devuelve uno nuevo; no debe
    llamar a ``actualizar`` (el candado no es reentrante). Si no hay cambios no se escribe nada.
    Sin ``crear``, no hace nada (y devuelve ``None``) cuando la carpeta ``apoderados/`` no existe:
    así una consulta que termina después de ``nuevo`` no resucita el registro de un caso reiniciado.
    Si el registro guardado no es válido lanza ``RegistroInvalido`` sin tocarlo.
    """
    caso_dir = Path(caso_dir)
    with _candado(caso_dir):
        if not crear and not carpeta(caso_dir).is_dir():
            return None
        actual = leer(caso_dir)
        original = actual.model_copy(deep=True)
        nuevo = fn(actual)
        if nuevo is None:
            nuevo = actual
        if nuevo == original and ruta(caso_dir).is_file():
            return nuevo
        return nuevo if _guardar(caso_dir, nuevo, crear) else None


def espejar(caso_dir: Path, identificacion: Identificacion) -> Registro | None:
    """Guarda la identificación del grafo como espejo; crea la carpeta si hace falta.

    Conserva consultas, revisiones y ajustes: las revisiones vencen solas si cambia la huella."""

    def poner(reg: Registro) -> None:
        reg.identificacion = identificacion

    return actualizar(caso_dir, poner, crear=True)


def espejar_si_falta(caso_dir: Path, leer_estado: Callable[[], Any]) -> Registro:
    """El registro, con el espejo de la identificación escrito desde el estado del grafo si faltaba.

    ``leer_estado`` devuelve ``state["apoderados"]`` (o ``None``) y solo se llama si falta el
    espejo; se llama bajo el candado del caso, de modo que ``borrar`` no se cruza con la escritura.
    Debe leer el grafo ella misma, no devolver valores leídos antes: si ``nuevo`` borró el hilo
    entretanto, lo que se leyó antes es del caso anterior.
    Si el estado no trae identificación (casos anteriores) o no es válido, no se escribe nada; si el
    registro guardado no es válido, lanza ``RegistroInvalido`` sin tocarlo."""
    caso_dir = Path(caso_dir)
    reg = leer(caso_dir)
    if reg.identificacion is not None:
        return reg
    with _candado(caso_dir):
        reg = leer(caso_dir)
        if reg.identificacion is not None:
            return reg
        crudo = leer_estado()
        if not crudo:
            return reg
        try:
            identificacion = Identificacion.model_validate(crudo)
        except ValidationError:
            log.warning("%s: la identificación de apoderados del grafo no es válida", caso_dir.name)
            return reg
        reg.identificacion = identificacion
        _guardar(caso_dir, reg, crear=True)
        return reg


def guardar_certificado(caso_dir: Path, nombre: str, pdf: bytes) -> str:
    """Escribe de forma atómica ``apoderados/certificados/<nombre>`` y devuelve su ruta relativa a
    ``apoderados/`` (la de ``ConsultaVigencia.certificado``).

    Se llama dentro de ``actualizar``, con el candado del caso, para no cruzarse con ``borrar``: si
    la carpeta ``apoderados/`` ya no está, falla en vez de volver a crearla. ``nombre`` es un nombre
    de archivo simple y nunca lleva una cédula."""
    if not nombre or Path(nombre).name != nombre or nombre.startswith("."):
        raise ValueError("Nombre de certificado no válido.")
    destino_dir = carpeta(caso_dir) / CERTIFICADOS
    destino_dir.mkdir(exist_ok=True)
    if destino_dir.is_symlink() or not destino_dir.is_dir():
        raise OSError("La carpeta de certificados del caso no es válida.")
    fd, temporal = tempfile.mkstemp(dir=destino_dir, prefix=".certificado-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, destino_dir / nombre)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise
    return f"{CERTIFICADOS}/{nombre}"


def ruta_certificado(caso_dir: Path, relativa: str) -> Path | None:
    """El PDF guardado en ``relativa`` (relativa a ``apoderados/``), o ``None`` si no es un archivo
    o queda fuera de ``apoderados/certificados/`` (``..``, rutas absolutas, el propio registro o
    enlaces simbólicos que salen de la carpeta)."""
    raiz = Path(caso_dir).resolve() / CARPETA
    try:
        ruta = (raiz / relativa).resolve()
        valida = ruta.is_relative_to(raiz / CERTIFICADOS) and ruta.is_file()
    except (OSError, ValueError, RuntimeError):
        return None
    return ruta if valida else None


def borrar_certificados_sin_uso(caso_dir: Path, rutas: Iterable[str]) -> None:
    """Borra, bajo el candado del caso, los PDF de ``rutas`` que ya ninguna consulta usa.

    Solo toca archivos que están directamente en ``apoderados/certificados/``; si el registro no se
    puede leer no borra nada."""
    caso_dir = Path(caso_dir)
    with _candado(caso_dir):
        try:
            usados = {c.certificado for c in leer(caso_dir).consultas.values() if c.certificado}
        except RegistroInvalido:
            return
        for relativa in set(rutas) - usados:
            ruta = ruta_certificado(caso_dir, relativa)
            if ruta is None or ruta.parent != caso_dir.resolve() / CARPETA / CERTIFICADOS:
                continue
            try:
                ruta.unlink()
            except OSError as e:
                log.warning("%s: no se pudo borrar un certificado sin uso (%s)", caso_dir.name, type(e).__name__)


def borrar(caso_dir: Path) -> None:
    """Borra la carpeta ``apoderados/`` del caso (registro y certificados)."""
    with _candado(caso_dir):
        shutil.rmtree(carpeta(caso_dir), ignore_errors=True)
