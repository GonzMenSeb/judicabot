from __future__ import annotations

import unicodedata
from datetime import date

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_UNIDADES = (
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
    "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
    "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve",
)
_DECENAS = ("", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa")
_CENTENAS = (
    "", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
    "seiscientos", "setecientos", "ochocientos", "novecientos",
)
_ORDINALES_UNIDAD = ("primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "séptimo", "octavo", "noveno")
_ORDINALES_DECENA = (
    "", "décimo", "vigésimo", "trigésimo", "cuadragésimo", "quincuagésimo",
    "sexagésimo", "septuagésimo", "octogésimo", "nonagésimo",
)


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))


def _apocopar(texto: str, genero: str) -> str:
    if genero not in ("m", "f"):
        return texto
    if texto.endswith("veintiuno"):
        return texto[:-9] + ("veintiún" if genero == "m" else "veintiuna")
    if texto.endswith("uno"):
        return texto[:-3] + ("un" if genero == "m" else "una")
    return texto


def _hasta_999(n: int, genero: str) -> str:
    if n == 100:
        return "cien"
    centenas, resto = divmod(n, 100)
    partes = []
    if centenas:
        palabra = _CENTENAS[centenas]
        partes.append(palabra[:-2] + "as" if genero == "f" and centenas > 1 else palabra)
    if resto:
        if resto < 30:
            partes.append(_UNIDADES[resto])
        else:
            decena, unidad = divmod(resto, 10)
            partes.append(_DECENAS[decena] + (f" y {_UNIDADES[unidad]}" if unidad else ""))
    return _apocopar(" ".join(partes), genero)


def numero_a_letras(n: int, genero: str = "") -> str:
    if not 0 <= n < 1_000_000:
        raise ValueError(f"Número fuera de rango: {n}")
    if n == 0:
        return "cero"
    miles, unidades = divmod(n, 1000)
    partes = []
    if miles == 1:
        partes.append("mil")
    elif miles:
        partes.append(_hasta_999(miles, "f" if genero == "f" else "m") + " mil")
    if unidades:
        partes.append(_hasta_999(unidades, genero))
    return " ".join(partes)


def _a_fecha(iso: str | None) -> date | None:
    try:
        return date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def fecha_larga(iso: str | None) -> str:
    f = _a_fecha(iso)
    if f is None:
        return "⟦FALTA: fecha⟧"
    return (
        f"{numero_a_letras(f.day)} ({f.day:02d}) de {MESES[f.month - 1]} "
        f"de {numero_a_letras(f.year)} ({f.year})"
    )


def fecha_corta(iso: str | None) -> str:
    f = _a_fecha(iso)
    if f is None:
        return "⟦FALTA: fecha⟧"
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"


def numero_titulo(n: int) -> str:
    return " ".join(p if p == "y" else p.capitalize() for p in numero_a_letras(n).split())


def _tabla_letras() -> dict[str, int]:
    tabla = {_sin_tildes(numero_a_letras(n)): n for n in range(1, 1000)}
    for decena in range(1, 10):
        for unidad in range(10):
            n = decena * 10 + unidad
            if unidad:
                texto = f"{_ORDINALES_DECENA[decena]} {_ORDINALES_UNIDAD[unidad - 1]}"
            else:
                texto = _ORDINALES_DECENA[decena]
            tabla[_sin_tildes(texto)] = n
    for i, palabra in enumerate(_ORDINALES_UNIDAD, start=1):
        tabla[_sin_tildes(palabra)] = i
    tabla["un"] = 1
    tabla["veintiun"] = 21
    return tabla


_TABLA = _tabla_letras()


def letras_a_numero(texto: str) -> int | None:
    return _TABLA.get(" ".join(_sin_tildes(texto).split()))
