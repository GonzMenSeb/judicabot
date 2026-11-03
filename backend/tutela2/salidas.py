from __future__ import annotations

import io
import zipfile
from pathlib import Path, PurePosixPath

PRINCIPAL = ("02SegundaInstancia", "C01Principal")


def raiz(caso_dir: Path) -> Path:
    return Path(caso_dir) / "salidas"


def principal(caso_dir: Path) -> Path:
    return raiz(caso_dir).joinpath(*PRINCIPAL)


def por_radicar(caso_dir: Path) -> Path:
    return raiz(caso_dir) / "por_radicar"


def borradores(caso_dir: Path) -> Path:
    return raiz(caso_dir) / "borradores_correo"


def trabajo(caso_dir: Path) -> Path:
    return raiz(caso_dir) / "trabajo"


def listar(caso_dir: Path) -> list[str]:
    base = raiz(caso_dir)
    if not base.is_dir():
        return []
    return sorted(f.relative_to(base).as_posix() for f in base.rglob("*") if f.is_file())


def resolver(caso_dir: Path, rel: str) -> Path:
    if not rel or "\0" in rel or "\\" in rel:
        raise ValueError("Ruta inválida.")
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("La ruta sale de salidas/.")
    base = raiz(caso_dir).resolve()
    ruta = (base / rel).resolve()
    if base not in ruta.parents:
        raise ValueError("La ruta sale de salidas/.")
    if not ruta.is_file():
        raise FileNotFoundError(rel)
    return ruta


def zip_bytes(caso_dir: Path) -> bytes:
    base = raiz(caso_dir)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in listar(caso_dir):
            z.write(base / rel, rel)
    return buffer.getvalue()
