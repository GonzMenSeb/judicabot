from __future__ import annotations

import json
from pathlib import Path

ARCHIVO = "fallos_ia.jsonl"


def registrar(caso_dir: Path, registro: dict) -> None:
    with (Path(caso_dir) / ARCHIVO).open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def leer(caso_dir: Path | str | None) -> list[dict]:
    if not caso_dir:
        return []
    ruta = Path(caso_dir) / ARCHIVO
    if not ruta.exists():
        return []
    registros = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            registros.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return registros
