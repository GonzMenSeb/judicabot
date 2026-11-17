"""Anonimiza el texto de un certificado de vigencia real para usarlo como fixture.

Entrada: la salida de ``pdftotext -layout`` del certificado (un .txt, ``-`` para la entrada
estándar o el propio .pdf, que se pasa por pdftotext). Salida: el mismo texto con el nombre,
la cédula, la tarjeta profesional, el número de certificado y el código de verificación
sustituidos por valores ficticios **de la misma longitud**, de modo que las columnas del
diseño no se muevan. También se reemplaza el nombre de quien firma, que figura en el pie.

    uv run python scripts/anonimizar_certificado.py real.txt -o tests/fixtures/vigencia/vigente.txt
    pdftotext -layout real.pdf - | uv run python scripts/anonimizar_certificado.py - > vigente.txt

Falla (código 1 o 2, sin escribir nada) si no encuentra al titular o si después de reemplazar
queda algún valor original. Imprime solo conteos, nunca los valores. Revise a mano el resultado:
las fechas y el texto de las observaciones no se tocan y pueden identificar a la persona.
Los PDF reales no se versionan: van en $TUTELA2_DATOS/vigencias/.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

RE_PERSONA = re.compile(
    r"(?P<antes>se[ñn]or(?:\(a\)|a)?\s+)(?P<nombre>[^,]{3,120}?)"
    r"(?P<medio>,\s+quien\s+se\s+identifica\s+con\s+[A-ZÁÉÍÓÚÑ ]{3,40}?\s+N\s?\.?\s*[°º]?\s*)"
    r"(?P<doc>[\d.]{3,20})",
    re.IGNORECASE,
)
RE_NUMERO = re.compile(r"(?P<antes>CERTIFICADO\s+N\s?\.?\s*[°º]?\s*:?\s*)(?P<valor>\d{1,12})(?!\d)")
RE_TARJETA = re.compile(r"(?<![\d/])(?P<valor>\d{3,7})(?P<despues>\s+\d{2}/\d{2}/\d{4})")
RE_SECCION_TPA = re.compile(r"VIGENCIA\s+TPA")
RE_CODIGO = re.compile(
    r"(?P<antes>C[óo]digo\s+de\s+verificaci[óo]n:?\s*)(?P<valor>(?:[0-9a-fA-F]\s*){64})(?![0-9a-fA-F])"
)
RE_FIRMANTE = re.compile(r"(?P<antes>Firmado\s+Por:\s*\n(?:[ \t]*\n)*)(?P<valor>[^\n]*\S[^\n]*)")
RE_HEX64 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")

PALABRAS = ("EJEMPLO", "PRUEBA", "FICTICIO", "MUESTRA")
HEXA = "0123456789abcdef"


def _letras(texto: str) -> str:
    """Palabras ficticias de la misma longitud en el lugar de cada palabra; lo demás queda igual."""
    n = 0

    def _palabra(m: re.Match[str]) -> str:
        nonlocal n
        original = m.group()
        base = PALABRAS[n % len(PALABRAS)]
        n += 1
        f = (base * (len(original) // len(base) + 1))[: len(original)]
        if original.isupper():
            return f
        if original[0].isupper():
            return f.capitalize()
        return f.lower()

    return re.sub(r"[^\W\d_]+", _palabra, texto)


def _cedula(texto: str) -> str:
    """1 + ceros + 1 con la longitud de los dígitos; los puntos separadores se conservan."""
    total = sum(c.isdigit() for c in texto)
    n = 0
    salida: list[str] = []
    for c in texto:
        if c.isdigit():
            n += 1
            salida.append("1" if n in (1, total) else "0")
        else:
            salida.append(c)
    return "".join(salida)


def _consecutivo(texto: str) -> str:
    """1234567890… con la longitud de los dígitos."""
    return "".join("1234567890"[i % 10] for i in range(len(texto)))


def _hexa(texto: str) -> str:
    """0123456789abcdef… sobre los caracteres hexadecimales; los espacios se conservan."""
    salida: list[str] = []
    n = 0
    for c in texto:
        if c.isspace():
            salida.append(c)
        else:
            salida.append(HEXA[n % len(HEXA)])
            n += 1
    return "".join(salida)


def _plegar(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _regex_nombre(nombre: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(t) for t in nombre.split()), re.IGNORECASE)


def _regex_cedula(digitos: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\d.])" + r"\.?".join(digitos) + r"(?!\d)")


def _regex_numero(digitos: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\d/]){re.escape(digitos)}(?![\d/])")


def anonimizar(texto: str) -> tuple[str, dict[str, int]]:
    """Devuelve (texto sin datos personales, cuántas veces se reemplazó cada dato).

    Lanza ``ValueError`` si no encuentra al titular o si algún valor original sobrevive."""
    persona = RE_PERSONA.search(texto)
    if not persona:
        raise ValueError("no se encontró el nombre y la cédula del titular: ¿es un certificado de vigencia?")
    nombre = " ".join(persona["nombre"].split())
    cedula = re.sub(r"\D", "", persona["doc"])
    if not cedula:
        raise ValueError("la cédula del titular no tiene dígitos")

    numero = (m["valor"] if (m := RE_NUMERO.search(texto)) else "")
    tarjeta = ""
    tpa = RE_SECCION_TPA.search(texto)
    if tpa and (m := RE_TARJETA.search(texto, tpa.end())):
        tarjeta = m["valor"]
    codigos = {re.sub(r"\s+", "", m["valor"]).lower() for m in RE_CODIGO.finditer(texto)}
    codigos |= {m.group().lower() for m in RE_HEX64.finditer(texto)}
    firmante = (m["valor"].strip() if (m := RE_FIRMANTE.search(texto)) else "")

    conteo = {"nombre": 0, "cedula": 0, "tarjeta": 0, "numero": 0, "codigo": 0, "firmante": 0}

    def _contar(c: dict[str, int], clave: str, valor: str) -> str:
        c[clave] += 1
        return valor

    def reemplazar(patron: re.Pattern[str], fn, clave: str, t: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            conteo[clave] += 1
            return fn(m.group())

        return patron.sub(_sub, t)

    t = texto
    t = reemplazar(_regex_nombre(nombre), _letras, "nombre", t)
    t = reemplazar(_regex_cedula(cedula), _cedula, "cedula", t)
    if tarjeta:
        t = reemplazar(_regex_numero(tarjeta), _consecutivo, "tarjeta", t)
    if numero:
        t = reemplazar(_regex_numero(numero), _consecutivo, "numero", t)
    t = RE_CODIGO.sub(lambda m: _contar(conteo, "codigo", m["antes"] + _hexa(m["valor"])), t)
    t = reemplazar(RE_HEX64, _hexa, "codigo", t)
    if firmante:
        t = reemplazar(_regex_nombre(firmante), _letras, "firmante", t)

    # Un valor que ya era ficticio (el reemplazo lo deja igual) no cuenta como superviviente.
    quedan = [
        clave
        for clave, valor, fn, patron in (
            ("nombre", nombre, _letras, _regex_nombre(nombre)),
            ("cedula", cedula, _cedula, _regex_cedula(cedula)),
            ("tarjeta", tarjeta, _consecutivo, _regex_numero(tarjeta) if tarjeta else None),
            ("numero", numero, _consecutivo, _regex_numero(numero) if numero else None),
            ("firmante", firmante, _letras, _regex_nombre(firmante) if firmante else None),
        )
        if patron is not None and fn(valor) != valor and patron.search(t)
    ]
    compacto = re.sub(r"\s+", "", t).lower()
    quedan += ["codigo" for c in codigos if _hexa(c) != c and c in compacto]
    if quedan:
        raise ValueError("después de reemplazar siguen apareciendo: " + ", ".join(sorted(set(quedan))))
    if conteo["nombre"] == 0 or conteo["cedula"] == 0:
        raise ValueError("no se reemplazó el nombre o la cédula del titular")
    return t, conteo


def _leer_entrada(ruta: str) -> str:
    if ruta == "-":
        return sys.stdin.read()
    p = Path(ruta)
    if p.suffix.lower() == ".pdf":
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], capture_output=True, check=True)
        return r.stdout.decode("utf-8", errors="replace")
    return p.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("entrada", help="texto de pdftotext -layout (.txt), '-' para la entrada estándar o un .pdf")
    p.add_argument("-o", "--salida", type=Path, help="archivo de salida (por defecto, la salida estándar)")
    args = p.parse_args(argv)
    try:
        texto, conteo = anonimizar(_leer_entrada(args.entrada))
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2 if isinstance(e, ValueError) else 1
    if args.salida:
        args.salida.write_text(texto, encoding="utf-8")
    else:
        sys.stdout.write(texto)
    print("reemplazos: " + ", ".join(f"{k}={v}" for k, v in conteo.items()), file=sys.stderr)
    print("revise a mano las fechas y las observaciones antes de versionar el resultado", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
