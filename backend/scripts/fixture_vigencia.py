"""Construye el PDF sintético del certificado de vigencia (tests/fixtures/vigencia/sintetico.pdf).

Parte del texto ficticio de vigente.txt (salida de ``pdftotext -layout``, sin datos reales) y
lo dibuja con Helvetica usando solo pypdf: un flujo de contenido escrito a mano, una celda de
texto por cada tramo separado por dos o más espacios y su posición según la columna. El
resultado se cifra con AES-256 y clave de usuario vacía, igual que el certificado real de la
Rama Judicial, para que las pruebas recorran el mismo camino de descifrado.

    uv run python scripts/fixture_vigencia.py                  # regenera sintetico.pdf
    uv run python scripts/fixture_vigencia.py -e otro.txt -s otro.pdf
    uv run python scripts/fixture_vigencia.py --estado no_vigente --nombre "NOMBRE FICTICIO" \\
        --cedula 1000000005 --tarjeta 123460 -s otro.pdf
    uv run python scripts/fixture_vigencia.py --e2e            # rehace e2e_vigente.pdf y e2e_no_vigente.pdf
    uv run python scripts/fixture_vigencia.py --estado no_inscrito --cedula 1000000006 \\
        -s tests/fixtures/vigencia/no_inscrito.pdf               # cédula no inscrita como abogado(a)

``--estado`` elige la plantilla de texto (vigente.txt, no_vigente.txt, observaciones.txt o
no_inscrito.txt) y ``--nombre``, ``--cedula`` y ``--tarjeta`` cambian el titular de la plantilla; las
columnas de la fila de la tarjeta se conservan. El certificado ``no_inscrito`` no trae nombre ni
tarjeta: solo admite ``--cedula``. ``--e2e`` hace los dos certificados de la abogada ficticia de
scripts/caso_sintetico.py que suben las pruebas de punta a punta. Use solo datos ficticios.

Los bytes cambian en cada ejecución (identificador y sales aleatorios del cifrado); las
pruebas solo comparan el texto extraído, nunca los bytes.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

CARPETA = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "vigencia"
ENTRADA_DEFECTO = CARPETA / "vigente.txt"
SALIDA_DEFECTO = CARPETA / "sintetico.pdf"
CASO_SINTETICO = Path(__file__).resolve().parent / "caso_sintetico.py"

PLANTILLAS = {
    "vigente": CARPETA / "vigente.txt",
    "no_vigente": CARPETA / "no_vigente.txt",
    "observaciones": CARPETA / "observaciones.txt",
    "no_inscrito": CARPETA / "no_inscrito.txt",
}
SOLO_CEDULA = {"no_inscrito"}
"""Plantillas sin nombre ni tarjeta del titular: solo se les cambia la cédula."""
SALIDAS_E2E = {"vigente": CARPETA / "e2e_vigente.pdf", "no_vigente": CARPETA / "e2e_no_vigente.pdf"}

RE_NOMBRE = re.compile(r"(se[ñn]or\(a\) )([^,\n]+)(, quien se identifica)")
RE_CEDULA = re.compile(r"(CIUDADAN[ÍI]A N\.°\s*)([\d.]+)(?!\d)", re.IGNORECASE)
RE_TARJETA = re.compile(r"(ABOGADO\(A\) CON TPA +)(\d+)( +)")
NOMBRE_VALIDO = re.compile(r"[A-ZÁÉÍÓÚÜÑ]+(?: [A-ZÁÉÍÓÚÜÑ]+)+")

ANCHO_PAGINA = 612
ALTO_PAGINA = 792
MARGEN_X = 36
MARGEN_SUPERIOR = 56
MARGEN_INFERIOR = 48
CUERPO = 8
INTERLINEA = 11
ANCHO_COLUMNA = 4.6
LINEAS_POR_PAGINA = (ALTO_PAGINA - MARGEN_SUPERIOR - MARGEN_INFERIOR) // INTERLINEA

CLAVE_PROPIETARIO = "propietario-sintetico"
TRAMO = re.compile(r"\S+(?: \S+)*")


def _literal(texto: str) -> bytes:
    """Cadena literal PDF en WinAnsi (cp1252), con paréntesis y barras escapados."""
    crudo = texto.encode("cp1252", errors="replace")
    crudo = crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + crudo + b")"


def _contenido(lineas: list[str]) -> bytes:
    """Flujo de contenido de una página: cada tramo de cada línea en su columna."""
    partes: list[bytes] = []
    y = ALTO_PAGINA - MARGEN_SUPERIOR
    for linea in lineas:
        for tramo in TRAMO.finditer(linea.expandtabs(8)):
            x = MARGEN_X + tramo.start() * ANCHO_COLUMNA
            partes.append(
                b"BT /F1 %d Tf 1 0 0 1 %.2f %.2f Tm %s Tj ET"
                % (CUERPO, x, y, _literal(tramo.group()))
            )
        y -= INTERLINEA
    return b"\n".join(partes)


def _paginas(texto: str) -> list[list[str]]:
    """Reparte las líneas en páginas; un salto de página del texto (\\f) cierra la actual."""
    paginas: list[list[str]] = []
    for bloque in texto.split("\f"):
        lineas = bloque.splitlines()
        for i in range(0, max(len(lineas), 1), LINEAS_POR_PAGINA):
            paginas.append(lineas[i : i + LINEAS_POR_PAGINA])
    return paginas


def construir(texto: str) -> PdfWriter:
    """PDF de una o más páginas con el texto dado, ya cifrado con AES-256 y clave vacía."""
    w = PdfWriter()
    fuente = w._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    recursos = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): fuente})}
    )
    for lineas in _paginas(texto):
        pagina = w.add_blank_page(ANCHO_PAGINA, ALTO_PAGINA)
        flujo = DecodedStreamObject()
        flujo.set_data(_contenido(lineas))
        pagina[NameObject("/Resources")] = recursos
        pagina[NameObject("/Contents")] = w._add_object(flujo)
        pagina[NameObject("/MediaBox")] = ArrayObject(
            [NumberObject(0), NumberObject(0), NumberObject(ANCHO_PAGINA), NumberObject(ALTO_PAGINA)]
        )
    w.add_metadata(
        {
            "/Title": "Certificado de vigencia sintético (fixture de pruebas)",
            "/Producer": "judicabot scripts/fixture_vigencia.py",
        }
    )
    w.encrypt(user_password="", owner_password=CLAVE_PROPIETARIO, algorithm="AES-256")
    return w


def _reemplazar_uno(patron: re.Pattern[str], texto: str, nuevo, que: str) -> str:
    resultado, veces = patron.subn(nuevo, texto)
    if veces != 1:
        raise ValueError(f"La plantilla debe tener exactamente un {que}; tiene {veces}.")
    return resultado


def personalizar(
    texto: str, *, nombre: str | None = None, cedula: str | None = None, tarjeta: str | None = None
) -> str:
    """El texto de la plantilla con otro titular (nombre, cédula y tarjeta profesional).

    Cada dato debe figurar una sola vez en la plantilla. La tarjeta conserva la columna de las
    celdas que la siguen en su fila, con al menos dos espacios, que son los que separan los tramos."""
    if nombre is not None:
        texto = _reemplazar_uno(RE_NOMBRE, texto, lambda m: m[1] + nombre + m[3], "nombre del titular")
    if cedula is not None:
        texto = _reemplazar_uno(RE_CEDULA, texto, lambda m: m[1] + cedula, "número de cédula")
    if tarjeta is not None:

        def fila(m: re.Match[str]) -> str:
            return m[1] + tarjeta + " " * max(2, len(m[2]) + len(m[3]) - len(tarjeta))

        texto = _reemplazar_uno(RE_TARJETA, texto, fila, "fila de tarjeta profesional")
    return texto


def _titular(p: argparse.ArgumentParser, nombre: str | None, cedula: str | None, tarjeta: str | None) -> dict[str, str]:
    """Valida y normaliza el titular: nombre en mayúsculas, cédula y tarjeta solo con dígitos."""
    datos: dict[str, str] = {}
    if nombre is not None:
        datos["nombre"] = " ".join(nombre.split()).upper()
        if not NOMBRE_VALIDO.fullmatch(datos["nombre"]):
            p.error("--nombre debe tener al menos dos palabras y solo letras")
    if cedula is not None:
        datos["cedula"] = cedula.replace(".", "").strip()
        if not re.fullmatch(r"\d{5,10}", datos["cedula"]):
            p.error("--cedula debe tener de 5 a 10 dígitos")
    if tarjeta is not None:
        datos["tarjeta"] = tarjeta.replace(".", "").strip()
        if not re.fullmatch(r"\d{3,7}", datos["tarjeta"]):
            p.error("--tarjeta debe tener de 3 a 7 dígitos")
    return datos


def abogada_e2e() -> dict[str, str]:
    """Nombre, cédula y tarjeta (sin puntos) de la abogada ficticia de scripts/caso_sintetico.py."""
    spec = importlib.util.spec_from_file_location("caso_sintetico", CASO_SINTETICO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return {"nombre": modulo.ABOGADA, "cedula": modulo.CEDULA_ABOGADA_PLANA, "tarjeta": modulo.TARJETA_ABOGADA_PLANA}


def _escribir(texto: str, salida: Path) -> None:
    with salida.open("wb") as f:
        construir(texto).write(f)
    print(f"{salida} ({salida.stat().st_size} bytes)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    origen = p.add_mutually_exclusive_group()
    origen.add_argument("-e", "--entrada", type=Path, help=f"Texto de partida (por defecto {ENTRADA_DEFECTO.name})")
    origen.add_argument("--estado", choices=sorted(PLANTILLAS), help="Plantilla de texto según el estado de la tarjeta")
    origen.add_argument(
        "--e2e",
        action="store_true",
        help=f"Rehace {' y '.join(s.name for s in SALIDAS_E2E.values())} con la abogada de {CASO_SINTETICO.name}",
    )
    p.add_argument("-s", "--salida", type=Path, help=f"PDF de salida (por defecto {SALIDA_DEFECTO.name})")
    p.add_argument("--nombre", help="Nombre ficticio del titular")
    p.add_argument("--cedula", help="Cédula ficticia del titular (se quitan los puntos)")
    p.add_argument("--tarjeta", help="Tarjeta profesional ficticia del titular (se quitan los puntos)")
    args = p.parse_args(argv)
    titular = _titular(p, args.nombre, args.cedula, args.tarjeta)

    if args.e2e:
        if args.salida or titular:
            p.error("--e2e toma el titular de caso_sintetico.py y escribe sus propias salidas")
        abogada = _titular(p, **abogada_e2e())
        for estado, salida in SALIDAS_E2E.items():
            _escribir(personalizar(PLANTILLAS[estado].read_text(encoding="utf-8"), **abogada), salida)
        return 0

    if args.estado in SOLO_CEDULA and set(titular) - {"cedula"}:
        p.error(f"el certificado {args.estado} no trae nombre ni tarjeta: solo admite --cedula")
    if (titular or args.estado) and args.salida is None:
        p.error(f"indique la salida con -s: {SALIDA_DEFECTO.name} se hace solo desde {ENTRADA_DEFECTO.name}")
    entrada = args.entrada or PLANTILLAS.get(args.estado or "", ENTRADA_DEFECTO)
    try:
        texto = personalizar(entrada.read_text(encoding="utf-8"), **titular)
    except ValueError as e:
        p.error(str(e))
    _escribir(texto, args.salida or SALIDA_DEFECTO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
