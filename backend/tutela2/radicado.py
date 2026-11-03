from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from tutela2.letras import numero_titulo

_FUNCIONES = {"4009": "conocimiento", "4088": "control_garantias"}
_NOMBRE_FUNCION = {"conocimiento": "Conocimiento", "control_garantias": "Control de Garantías"}


def digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def corto(cui: str) -> str:
    return digitos(cui)[12:21]


def espaciado(cui: str) -> str:
    d = digitos(cui)
    return f"{d[:12]} {d[12:16]} {d[16:21]} {d[21:23]}"


def con_guion(cui: str) -> str:
    d = digitos(cui)
    return f"{d[:21]}-{d[21:23]}"


def cui_1a(cui: str) -> str:
    return digitos(cui)[:21] + "00"


def cui_2a(cui: str) -> str:
    return digitos(cui)[:21] + "01"


@dataclass(frozen=True)
class Juzgado:
    numero: int
    funcion: Literal["conocimiento", "control_garantias"]
    letras: str
    plural: bool = False


def juzgado_de_radicado(cui: str) -> Juzgado | None:
    d = digitos(cui)
    funcion = _FUNCIONES.get(d[5:9])
    if funcion is None or len(d) < 12:
        return None
    numero = int(d[9:12])
    if numero == 0:
        return None
    return Juzgado(numero=numero, funcion=funcion, letras=numero_titulo(numero))


def nombre_juzgado(j: Juzgado, forma: Literal["cuerpo", "cuerpo_numero", "digitos", "encabezado"]) -> str:
    funcion = ("Funciones" if j.plural else "Función") + f" de {_NOMBRE_FUNCION[j.funcion]}"
    if forma == "cuerpo":
        numero = j.letras
    elif forma == "cuerpo_numero":
        numero = f"{j.letras} ({j.numero})"
    else:
        numero = str(j.numero)
    texto = f"Juzgado {numero} Penal Municipal con {funcion} de Medellín"
    return texto.upper() if forma == "encabezado" else texto
