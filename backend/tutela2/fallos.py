from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Familia:
    """Causa de un fallo de la llamada a la IA.

    ``sin_coste``: el fallo ocurrió antes de que el proveedor recibiera o cobrara el expediente, así que no cuenta
    para el tope de reintentos. ``patron`` reconoce el texto de ``error`` de las líneas de ``fallos_ia.jsonl``
    escritas antes de que ``graph._llamar`` guardara la marca ``sin_coste``.
    """

    clave: str
    sin_coste: bool
    patron: re.Pattern[str]


def _p(texto: str) -> re.Pattern[str]:
    return re.compile(texto, re.IGNORECASE)


# Única tabla de familias del error del proveedor; ``llm._sin_coste`` la consulta por ``clave`` y
# ``sin_coste(registro)`` por el texto. El orden importa: gana la primera que casa.
FAMILIAS: tuple[Familia, ...] = (
    Familia("clave_ausente", True, re.compile(r"^(No hay credenciales para el proveedor|Falta la clave de la API)")),
    Familia("saldo", True, _p(r"credit balance is too low")),
    Familia("clave_gemini", True, _p(r"API key not valid")),
    Familia(
        "credenciales",
        True,
        re.compile(
            r"^Error del proveedor \((AuthenticationError|PermissionDeniedError)\)"
            r"|^Error del proveedor \(ClientError\): 40[13] "
        ),
    ),
    Familia(
        "limite",
        True,
        re.compile(r"^Error del proveedor \(RateLimitError\)|^Error del proveedor \(ClientError\): 429 "),
    ),
    Familia(
        "servicio",
        True,
        re.compile(
            r"^Error del proveedor \((OverloadedError|InternalServerError|ServiceUnavailableError|DeadlineExceededError|ServerError)\)"
        ),
    ),
    Familia("conexion", True, re.compile(r"^Error del proveedor \((APIConnectionError|ConnectError)\)")),
    Familia(
        "tiempo_agotado",
        False,
        re.compile(r"^Error del proveedor \((APITimeoutError|\w*Timeout\w*)\)", re.IGNORECASE),
    ),
    Familia(
        "corte",
        False,
        re.compile(r"^Error del proveedor \((RemoteProtocolError|ReadError|WriteError|CloseError|\w*ProtocolError)\)"),
    ),
    Familia(
        "rechazo",
        False,
        _p(r"stop_reason=refusal|finish_reason=(SAFETY|RECITATION|BLOCKLIST|PROHIBITED_CONTENT|SPII)|block_reason=|rechaz\w+ la solicitud|bloqueó la solicitud"),
    ),
    Familia("tokens", False, _p(r"límite de tokens|stop_reason=max_tokens|finish_reason=MAX_TOKENS")),
)

_POR_CLAVE = {f.clave: f for f in FAMILIAS}


def familia(clave: str) -> Familia:
    return _POR_CLAVE[clave]


def familia_de_texto(error: object) -> Familia | None:
    texto = str(error or "")
    return next((f for f in FAMILIAS if f.patron.search(texto)), None)


def sin_coste(registro: dict) -> bool:
    """Si el fallo no cuenta para el tope: la marca del registro y, en las líneas viejas, su texto."""
    if "sin_coste" in registro:
        return bool(registro["sin_coste"])
    encontrada = familia_de_texto(registro.get("error"))
    return encontrada is not None and encontrada.sin_coste
