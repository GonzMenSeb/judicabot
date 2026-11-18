from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from .clasificar import (
    clasificar,
    extraer_cuis,
    menciona_radicado,
    resolver_caso,
    texto_cabecera,
)
from .clasificar import plano as _plano
from . import eventos
from .config import Config
from .jev import JevClient, cliente_jev
from .jev_roles import aplicar, segunda_opinion
from .letras import letras_a_entero, letras_a_numero
from .models import Doc, Fechas, Ingesta, Metadatos, Pagina, Rol
from .radicado import Juzgado, juzgado_de_radicado, nombre_juzgado

log = logging.getLogger("tutela2")

MIN_CHARS_PAGINA = 30
OCR_DPI = 300
EXTENSIONES = {".pdf", ".docx", ".txt"}
ROLES_OBLIGATORIOS = ("escrito_tutela", "fallo_a_quo", "impugnacion")
ROLES_ESPERADOS = ("auto_admisorio", "auto_concede_impugnacion", "acta_reparto_2a")
AVISO_REVISAR = "[AVISO: el encabezado de este documento pertenece a otro radicado; verifique antes de afirmar hechos]"


def _limpiar(texto: str) -> str:
    return texto.replace("​", "").replace("﻿", "").replace("\xa0", " ").strip()


def es_segunda(carpeta: str) -> bool:
    c = _plano(carpeta)
    return (
        re.match(r"02(?!\d)", c) is not None
        or "segunda" in c
        or re.match(r"\s*2\s*(?:a|da|nda)?[\s._-]*instancia", c) is not None
        or re.search(r"\bcircuito\b", c) is not None
    )


def _es_primera(carpeta: str) -> bool:
    c = _plano(carpeta)
    return re.match(r"01(?!\d)\W*(?:primera|1a|instancia)", c) is not None or "primera" in c


_PDFIUM = threading.RLock()


def _max_hilos() -> int:
    return min(8, os.cpu_count() or 4)


def _sha256(ruta: Path) -> str:
    with ruta.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _partir(texto: str) -> list[str]:
    partes = texto.split("\f")
    if texto.endswith("\f"):
        partes.pop()
    return partes


def _textos_pdfium(ruta: Path) -> list[str]:
    import pypdfium2

    with _PDFIUM:
        pdf = pypdfium2.PdfDocument(str(ruta))
        try:
            return [p.get_textpage().get_text_range() for p in pdf]
        finally:
            pdf.close()


def _textos_pypdf(ruta: Path) -> list[str]:
    try:
        lector = PdfReader(str(ruta))
        if lector.is_encrypted:
            lector.decrypt("")
        return [p.extract_text() or "" for p in lector.pages]
    except Exception as e:
        try:
            return _textos_pdfium(ruta)
        except Exception:
            raise e


def _textos_pdf(ruta: Path) -> list[str]:
    if shutil.which("pdftotext"):
        try:
            r = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(ruta), "-"],
                capture_output=True,
                timeout=180,
            )
            if r.returncode == 0:
                return _partir(r.stdout.decode("utf-8", errors="replace"))
            log.warning("pdftotext falló en %s, se usa pypdf", ruta.name)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning(
                "pdftotext no disponible para %s (%s), se usa pypdf", ruta.name, e
            )
    return _textos_pypdf(ruta)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _texto_parrafo(p) -> str:
    partes: list[str] = []

    def rec(e) -> None:
        for c in e:
            if c.tag == _W + "t":
                partes.append(c.text or "")
            elif c.tag == _W + "tab":
                partes.append(" ")
            elif c.tag == _W + "br":
                partes.append("\n")
            elif c.tag not in (_W + "txbxContent", _MC_FALLBACK):
                rec(c)

    rec(p)
    return "".join(partes)


def _cuadros_de_texto(p):
    for tb in p.iter(_W + "txbxContent"):
        for a in tb.iterancestors():
            if a is p:
                yield tb
                break
            if a.tag in (_W + "txbxContent", _MC_FALLBACK):
                break


def _lineas_docx(el) -> list[str]:
    lineas: list[str] = []
    for hijo in el.iterchildren():
        if hijo.tag == _W + "p":
            lineas.append(_texto_parrafo(hijo))
            for tb in _cuadros_de_texto(hijo):
                lineas += _lineas_docx(tb)
        elif hijo.tag == _W + "tbl":
            for fila in hijo.iterchildren(_W + "tr"):
                celdas = [
                    " ".join(x.strip() for x in _lineas_docx(c) if x.strip())
                    for c in fila.iterchildren(_W + "tc")
                ]
                lineas.append(" | ".join(celdas))
        elif hijo.tag != _MC_FALLBACK and hijo.tag != _W + "sectPr":
            lineas += _lineas_docx(hijo)
    return lineas


def _textos_docx(ruta: Path) -> list[str]:
    doc = Document(str(ruta))
    lineas: list[str] = []
    vistos: set[str] = set()
    for sec in doc.sections:
        for hf in (sec.header, sec.footer):
            if hf.is_linked_to_previous:
                continue
            bloque = "\n".join(_lineas_docx(hf._element))
            if bloque.strip() and bloque not in vistos:
                vistos.add(bloque)
                lineas.append(bloque)
    lineas += _lineas_docx(doc.element.body)
    return ["\n".join(lineas)]


def _textos(ruta: Path) -> list[str]:
    ext = ruta.suffix.lower()
    if ext == ".pdf":
        return _textos_pdf(ruta)
    if ext == ".docx":
        return _textos_docx(ruta)
    return _partir(ruta.read_text(encoding="utf-8", errors="replace"))


def _ocr_disponible() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


_PALABRA = re.compile(r"[^\W\d_]+")
MIN_TOKENS_LEGIBLE = 20
MIN_PROPORCION_LEGIBLE = 0.4


def _legible(texto: str) -> bool:
    tokens = texto.split()
    if len(tokens) < MIN_TOKENS_LEGIBLE:
        return True
    buenos = sum(
        1
        for t in tokens
        if _PALABRA.fullmatch(t.strip(".,;:()\"'")) and re.search(r"[aeiouáéíóú]", t.lower())
    )
    return buenos / len(tokens) >= MIN_PROPORCION_LEGIBLE


class _PdfOcr:
    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        self._pdf = None

    def __getitem__(self, i: int):
        with _PDFIUM:
            if self._pdf is None:
                import pypdfium2

                self._pdf = pypdfium2.PdfDocument(str(self._ruta))
            return self._pdf[i]

    def close(self) -> None:
        with _PDFIUM:
            pdf, self._pdf = self._pdf, None
            if pdf is not None:
                pdf.close()


def _renderizar(pdf, n: int):
    with _PDFIUM:
        pagina = pdf[n - 1]
        try:
            return pagina.render(scale=OCR_DPI / 72).to_pil()
        finally:
            pagina.close()


def _de_cache(f: Path) -> str | None:
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        return None


def _ocr_pagina(pdf, n: int, sha: str, dir_cache: Path) -> str:
    import pytesseract

    f = dir_cache / sha / f"{n}.txt"
    en_cache = _de_cache(f)
    if en_cache is not None:
        return en_cache
    imagen = _renderizar(pdf, n)
    texto = _limpiar(
        pytesseract.image_to_string(imagen, lang="spa", config="--psm 1")
    )
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(texto, encoding="utf-8")
        tmp.replace(f)
    except OSError as e:
        log.warning("No se pudo escribir la caché de OCR %s: %s", f, e)
    return texto


def _leer_documento(ruta: Path, doc_id: str) -> tuple[list[Pagina], list[str]]:
    alertas: list[str] = []
    try:
        textos = _textos(ruta)
    except Exception as e:
        log.warning("No se pudo leer %s: %s", ruta, e)
        return [], [f"{doc_id} {ruta.name}: no se pudo leer el archivo ({e})."]
    paginas = []
    for i, t in enumerate(textos, 1):
        t = _limpiar(t)
        paginas.append(Pagina(n=i, texto=t, sin_texto=len(t) < MIN_CHARS_PAGINA))
    if ruta.suffix.lower() == ".docx" and sum(len(p.texto) for p in paginas) < MIN_CHARS_PAGINA:
        alertas.append(
            f"{doc_id} {ruta.name}: el Word no tiene texto extraíble; conviértalo a PDF."
        )
    return paginas, alertas


def _necesita_ocr(ruta: Path, paginas: list[Pagina]) -> bool:
    return ruta.suffix.lower() == ".pdf" and any(p.sin_texto for p in paginas)


def _cuenta(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def _emitir_documento(d: Doc, paginas: list[Pagina], alertas: list[str], n_hecho: int, n_total: int) -> None:
    n_ocr = sum(1 for p in paginas if p.ocr)
    n_sin = sum(1 for p in paginas if p.sin_texto)
    eventos.emitir(
        "ingesta",
        "lee",
        f"{d.ruta}: {len(paginas)} página{'' if len(paginas) == 1 else 's'}"
        + (f", {n_ocr} leídas con OCR" if n_ocr else "")
        + (f", {n_sin} sin texto legible" if n_sin else "")
        + ".",
        {
            "doc_id": d.doc_id,
            "archivo": d.ruta,
            "paginas": len(paginas),
            "ocr": n_ocr,
            "sin_texto": n_sin,
            "alertas": alertas,
            "n_hecho": n_hecho,
            "n_total": n_total,
        },
    )


def _leer_expediente(
    archivos: list[Path], docs: list[Doc], dir_cache: Path | None
) -> list[tuple[list[Pagina], list[str]]]:
    leidos: list = [None] * len(docs)
    terminados = 0

    def terminar(i: int) -> None:
        nonlocal terminados
        terminados += 1
        _emitir_documento(docs[i], *leidos[i], terminados, len(docs))

    with ThreadPoolExecutor(max_workers=_max_hilos()) as pool:
        futuros = {
            pool.submit(_leer_documento, ruta, d.doc_id): i
            for i, (ruta, d) in enumerate(zip(archivos, docs))
        }
        con_ocr: list[int] = []
        for futuro in as_completed(futuros):
            i = futuros[futuro]
            leidos[i] = futuro.result()
            if dir_cache is not None and _necesita_ocr(archivos[i], leidos[i][0]):
                con_ocr.append(i)
            else:
                terminar(i)
        if con_ocr:
            _leer_con_ocr(pool, sorted(con_ocr), archivos, docs, leidos, dir_cache, terminar)
    return leidos


def _leer_con_ocr(
    pool: ThreadPoolExecutor,
    indices: list[int],
    archivos: list[Path],
    docs: list[Doc],
    leidos: list[tuple[list[Pagina], list[str]]],
    dir_cache: Path,
    terminar,
) -> None:
    pdfs = {i: _PdfOcr(archivos[i]) for i in indices}
    textos: dict[int, dict[int, str]] = {i: {} for i in indices}
    fallos: dict[int, dict[int, BaseException]] = {i: {} for i in indices}
    cola: list[tuple[int, int]] = []
    total = 0
    for i in indices:
        for p in leidos[i][0]:
            if not p.sin_texto:
                continue
            total += 1
            texto = _de_cache(dir_cache / docs[i].sha256 / f"{p.n}.txt")
            if texto is None:
                cola.append((i, p.n))
            else:
                textos[i][p.n] = texto
    hecho = total - len(cola)
    eventos.emitir(
        "ingesta",
        "lee",
        f"OCR: {_cuenta(len(indices), 'documento escaneado', 'documentos escaneados')}, "
        f"{_cuenta(total, 'página', 'páginas')} por leer"
        + (f" ({hecho} ya en caché)" if hecho else "")
        + ".",
        {"ocr_documentos": len(indices), "ocr_paginas": total, "desde_cache": hecho},
    )
    pendientes = Counter(i for i, _ in cola)
    candado = threading.Lock()
    primer_fallo: dict[int, int] = {}

    def reconocer(i: int, n: int) -> str | None:
        with candado:
            tope = primer_fallo.get(i)
        if tope is not None and n > tope:
            return None
        try:
            return _ocr_pagina(pdfs[i], n, docs[i].sha256, dir_cache)
        except Exception:
            with candado:
                primer_fallo[i] = min(primer_fallo.get(i, n), n)
            raise

    def cerrar(i: int) -> None:
        paginas, alertas = leidos[i]
        for p in paginas:
            if not p.sin_texto:
                continue
            if p.n in fallos[i]:
                e = fallos[i][p.n]
                log.warning("OCR falló en %s: %s", archivos[i].name, e)
                alertas.append(f"{docs[i].doc_id} {archivos[i].name}: el OCR falló ({e}).")
                break
            texto = textos[i][p.n]
            if len(texto) >= MIN_CHARS_PAGINA and _legible(texto):
                p.texto, p.ocr, p.sin_texto = texto, True, False
        pdfs[i].close()
        terminar(i)

    try:
        for i in indices:
            if not pendientes[i]:
                cerrar(i)
        futuros = {pool.submit(reconocer, i, n): (i, n) for i, n in cola}
        for futuro in as_completed(futuros):
            i, n = futuros[futuro]
            hecho += 1
            error = futuro.exception()
            if error is not None:
                fallos[i][n] = error
            elif (texto := futuro.result()) is not None:
                textos[i][n] = texto
                eventos.emitir(
                    "ingesta",
                    "lee",
                    f"OCR: {docs[i].ruta}, página {n} de {len(leidos[i][0])}.",
                    {
                        "doc_id": docs[i].doc_id,
                        "archivo": docs[i].ruta,
                        "pagina": n,
                        "paginas": len(leidos[i][0]),
                        "ocr": True,
                        "n_ocr_hecho": hecho,
                        "n_ocr_total": total,
                    },
                )
            pendientes[i] -= 1
            if not pendientes[i]:
                cerrar(i)
    finally:
        for pdf in pdfs.values():
            pdf.close()


_CERTIFICADO = "certificado de existencia y representacion legal"


def _es_certificado(texto: str) -> bool:
    n = re.sub(r"\s+", " ", _plano(texto))
    i = n.find(_CERTIFICADO)
    return 0 <= i < 200 and ("codigo de verificacion" in n or "camara de comercio" in n)


_MESES = {
    m: i
    for i, m in enumerate(
        "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
        1,
    )
}
_F_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})(?![\d/])")
_F_ISO = re.compile(r"(?<![\d\-])(\d{4})-(\d{2})-(\d{2})(?![\d\-])")
_FECHA_CORREO = re.compile(r"^[ \t]*Fecha[ \t]+[^\W\d_]{2,4}\.?[ \t]+(\S+)", re.M)


def _iso(a: str, m: str | int, d: str) -> str | None:
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


_ABREVIATURAS = {m[:3]: i for m, i in _MESES.items()} | {"set": 9}
_MES = re.compile(
    r"(?<![^\W\d_])(" + "|".join(sorted([*_MESES, *_ABREVIATURAS], key=len, reverse=True)) + r")(?![^\W\d_])\.?",
    re.I,
)
_TOKEN = re.compile(r"\d+(?:\.\d{3})?[º°ª]?|[^\W\d_]+")
_ORDINAL = "º°ª"
_ENTRE_DIA_Y_MES = re.compile(r"[\s\-/.º°ª()]*(?:de[\s\-/.]*)?")
_DIAS_DEL_MES = re.compile(r"\s+d[ií]as?\s+del\s+mes\s+de\s*$", re.I)  # «a los veintiocho (28) días del mes de septiembre»


def _dia_antes(izq: str) -> tuple[int, int] | None:
    """Día que precede al mes: «28», «1º» o «veintiocho» (con o sin «(28)»). Devuelve (día, posición)."""
    tokens = list(_TOKEN.finditer(izq))
    j = len(tokens)
    if j and _plano(tokens[j - 1].group()) == "de":
        j -= 1
    if j == 0 or not _ENTRE_DIA_Y_MES.fullmatch(_plano(izq[tokens[j - 1].end() :])):
        return None
    ultimo = tokens[j - 1]
    if ultimo.group()[0].isdigit():
        dia = ultimo.group().rstrip(_ORDINAL)
        if len(dia) > 2:
            return None
        # «veintiocho (28)», con a lo sumo una palabra más antes (día de la semana, «a»); sin cruzar renglones
        en_letras = re.search(r"((?:[^\W\d_]+[ \t]+){0,2}[^\W\d_]+)[ \t]*\([ \t]*$", izq[: ultimo.start()])
        if en_letras:
            palabras = list(re.finditer(r"[^\W\d_]+", en_letras.group(1)))
            for k in range(1, len(palabras) + 1):
                ini = palabras[-k].start()
                if letras_a_entero(en_letras.group(1)[ini:]) == int(dia):
                    return int(dia), en_letras.start(1) + ini
        return int(dia), ultimo.start()
    for k in range(min(3, j), 0, -1):
        grupo = tokens[j - k : j]
        if any(g.group()[0].isdigit() for g in grupo):
            continue
        n = letras_a_entero(" ".join(g.group() for g in grupo))
        if n and 1 <= n <= 31:
            return n, grupo[0].start()
    return None


def _dia_despues(der: str) -> tuple[int, int] | None:
    """Día que sigue al mes: «28» o «veintiocho (28)». Devuelve (día, fin)."""
    d = re.match(r"\s*(\d{1,2})(?!\d)", der)
    if d:
        return int(d.group(1)), d.end()
    d = re.match(r"\s*((?:[^\W\d_]+[ \t]+){0,2}[^\W\d_]+)[ \t]*\(\s*(\d{1,2})\s*\)", der)
    if d and letras_a_entero(d.group(1)) == int(d.group(2)):
        return int(d.group(2)), d.end()
    return None


def _anio_despues(der: str) -> tuple[int, int] | None:
    """Año que sigue al mes: «2026», «2.026» o «dos mil veintiséis» (con o sin «(2026)»). Devuelve (año, fin)."""
    tokens = list(_TOKEN.finditer(der))
    i = 0
    while i < len(tokens) and _plano(tokens[i].group()) in ("de", "del", "ano"):
        i += 1
    if i >= len(tokens):
        return None
    primero = tokens[i]
    if primero.group()[0].isdigit():
        anio = primero.group().replace(".", "")
        return (int(anio), primero.end()) if len(anio) == 4 else None
    palabras = []
    for t in tokens[i : i + 6]:
        if t.group()[0].isdigit():
            break
        palabras.append(t)
    for k in range(len(palabras), 0, -1):
        n = letras_a_entero(" ".join(p.group() for p in palabras[:k]))
        if n and 1900 <= n <= 2100:
            fin = palabras[k - 1].end()
            entre_parentesis = re.match(r"\s*\(\s*\d\.?\d{3}\s*\)", der[fin:])
            return n, fin + (entre_parentesis.end() if entre_parentesis else 0)
    return None


def _fechas_con_mes(texto: str) -> list[tuple[int, int, str | None]]:
    """Fechas con el mes escrito (completo o abreviado), con día y año en cifras o en letras, en el orden
    «día de mes de año» («28 de sep. de 2026», «veintiocho de septiembre de dos mil veintiséis»,
    «28-sep-2026») o «mes día de año» («septiembre 28 de 2026»). Devuelve (inicio, fin, ISO)."""
    halladas = []
    for m in _MES.finditer(texto):
        clave = _plano(m.group(1))
        mes = _MESES.get(clave) or _ABREVIATURAS.get(clave[:3])
        desde = max(0, m.start() - 60)
        izq, der = texto[desde : m.start()], texto[m.end() : m.end() + 90]
        dia = _dia_antes(_DIAS_DEL_MES.sub(" de ", izq))
        if dia is not None:
            anio = _anio_despues(der)
            if anio:
                halladas.append((desde + dia[1], m.end() + anio[1], _iso(str(anio[0]), mes, str(dia[0]))))
            continue
        d = _dia_despues(der)
        anio = _anio_despues(der[d[1] :]) if d else None
        if d and anio:
            halladas.append((m.start(), m.end() + d[1] + anio[1], _iso(str(anio[0]), mes, str(d[0]))))
    return halladas


def _fechas(texto: str) -> list[tuple[int, int, str]]:
    """Todas las fechas del texto como (inicio, fin, ISO), por posición."""
    halladas = _fechas_con_mes(texto)
    halladas += [
        (m.start(), m.end(), _iso(m.group(3), m.group(2), m.group(1)))
        for m in _F_NUM.finditer(texto)
    ]
    halladas += [
        (m.start(), m.end(), _iso(m.group(1), m.group(2), m.group(3)))
        for m in _F_ISO.finditer(texto)
    ]
    return sorted((pos, fin, iso) for pos, fin, iso in halladas if iso)


def fechas_en(texto: str) -> list[tuple[int, str]]:
    return [(pos, iso) for pos, _, iso in _fechas(texto)]


_OFICIO = re.compile(r"oficio\s+(?:no|n[°º.]|\d)|adjunt\w+\s+(?:el\s+)?(?:fallo|sentencia)")
VENTANA_OFICIO = 500
ZONA_ENCABEZADO = 1500  # caracteres desde el inicio; el encabezado no está más lejos
MAX_REINICIOS = 200  # renglones, tras un oficio de notificación, desde los que se vuelve a buscar el encabezado

_PALABRA_MAYUS = r"[A-ZÁÉÍÓÚÑ][^\W\d_]*\.?(?:[A-Z]\.)*"
_LUGAR = rf"{_PALABRA_MAYUS}(?:\s+(?:(?:de|del|la|las|los|y)\s+)*{_PALABRA_MAYUS}){{0,3}}(?:\s*\([^)\d]*\))?"
_LUGARES = rf"{_LUGAR}(?:(?:\s*,\s*|\s+[-–—]\s+){_LUGAR})?"  # «Medellín», «Medellín, Antioquia», «Medellín - Antioquia»
# hueco entre columnas (pdftotext -layout): 3 o más espacios, o un tabulador; no la sangría tras una coma
# («Medellín,   a 28 de …»), que sigue siendo parte del renglón
_COLUMNAS = re.compile(r"(?<![,\s])\s{3,}|\t")
_ANTES_DE_LA_FECHA = r"(?:(?:a|el)\s+)?(?:[^\W\d_]{3,10}\.?,?\s*)?"  # «a», día de la semana (con o sin coma)
# «Medellín, », «Bogotá D.C., », «Santiago de Cali, », «San Pedro de los Milagros, », «Medellín (Antioquia), »,
# «Medellín, Antioquia, », «Medellín, Antioquia. », «Medellín, martes, », «Medellín, a »
_CIUDAD_Y_COMA = re.compile(rf"^\s*{_LUGARES}(?:\s*,\s*|(?<=\.)\s+){_ANTES_DE_LA_FECHA}$")
_CIUDAD_SOLA = re.compile(rf"^\s*{_LUGARES}\s*$")  # «Medellín » (sin coma)
# «medellín, » (minúscula), «Medellín; », «Medellín – »: tiene forma de lugar y separador pero no se lee como encabezado
_LUGAR_CON_SEPARADOR = re.compile(
    r"^\s*[^\W\d_][^\W\d_.]*(?:\s+(?:(?:de|del|la|las|los|y)\s+)*[^\W\d_.]+){0,3}\s*[,;–—-]\s*(?:[^\W\d_]{3,10}\.?,?\s*)?$"
)
# renglón «Ciudad, <fecha>» cuya fecha no se pudo leer («Medellín, 28.IX.2026», «Medellín, Sept. 28/26»). Las cifras
# deben tener forma de fecha (día y mes en números romanos o separados por «/.-», día y mes escrito, mes escrito y
# día): un membrete o una dirección («Palacio de Justicia, Piso 3», «Sede Medellín, Carrera 52 No. 42-43», «Tutela,
# 1ª instancia») no son un encabezado ilegible.
_MES_ESCRITO = rf"(?i:(?:{'|'.join(_ABREVIATURAS)})[^\W\d_]*)"
_CIUDAD_Y_CIFRAS = re.compile(
    rf"^\s*{_LUGARES}\s*,\s*(?:(?:a|el)\s+)?(?:"
    rf"(?:{_MES_ESCRITO}\.?,?\s*)\d{{1,2}}(?!\d)"  # «Sept. 28/26»
    rf"|(?:[^\W\d_]{{3,10}}\.?,?\s*)?\d{{1,2}}(?!\d)"
    rf"(?:[/.\-]\s*(?:\d{{1,2}}|[IVX]{{1,4}})\s*[/.\-]\s*\d"  # «28.IX.2026», «28/9/26»
    rf"|\s*(?:de\s+)?{_MES_ESCRITO}"  # «28 de septiembrre de 2026», «31 de abril de 2026»
    rf"|\s+[IVX]{{1,4}}\b)"  # «28 IX 2026»
    rf")"
)
# fecha en cifras o números romanos que el lector no entiende: «28.IX.2026», «28/09/26». El mes es 1-12 o romano
# («Tel. (4) 23-25-55» no es una fecha).
_FECHA_DUDOSA = re.compile(
    r"(?<![\d/.\-])\d{1,2}[/.\-](?:[IVX]{1,4}|0?[1-9]|1[0-2])[/.\-]\d{2,4}(?![\d/])", re.I
)
_ROTULO_FECHA = re.compile(
    r"^\s*(?:fecha(?:\s+(?:de\s+la|del|de)\s+(?:providencia|sentencia|auto|fallo|decisi[oó]n))?\s*:?\s*)?$", re.I
)
# primer renglón del cuerpo: el encabezado queda antes
_INICIO_SECCION = r"^[ \t]*(?:(?:[IVX]+|\d{1,2})[.)\-][ \t]*)?"
_TITULO_SECCION = r"(?:HECHOS|ANTECEDENTES|CONSIDERACIONES|FUNDAMENTOS|PRETENSIONES)\b|PRIMERO[.:)\-]"
_SECCION = re.compile(_INICIO_SECCION + rf"(?:{_TITULO_SECCION}|\d{{1,2}}[.)][ \t])", re.M | re.I)
# lo mismo sin los párrafos numerados, que también pueden ser los de un oficio de notificación
_SECCION_TITULADA = re.compile(_INICIO_SECCION + rf"(?:{_TITULO_SECCION})", re.M | re.I)


def _fecha_encabezado(texto: str) -> str | None:
    """Fecha del encabezado de la providencia. Solo vale la que está en el encabezado (el comienzo del
    documento, antes del cuerpo), en dos niveles: primero «Ciudad, <fecha>» (lugar con mayúsculas, coma y, si
    acaso, el día de la semana antes de la fecha) y solo si no hay ninguna así, la fecha sola en su renglón
    (con «Fecha:» opcional). Si el encabezado no se puede leer devuelve None en vez de sustituirlo por una fecha
    del cuerpo (hechos, términos): un renglón «Ciudad, <fecha>» que no se entiende (cifras, números romanos o
    mes escrito de una forma que el lector no reconoce) o una fecha en cifras que no se entiende. Lo que no se
    detecta es un encabezado ilegible sin cifras ni mes («Medellín, XXVIII de septiembre…», con el día en
    romanos): si antes del primer renglón de cuerpo hay una fecha con forma de «Ciudad, fecha» o sola en su
    renglón, esa se lee."""
    return _leer_encabezado(unicodedata.normalize("NFC", texto)[:6000])[0]


def _leer_encabezado(texto: str, relectura: bool = False) -> tuple[str | None, bool]:
    """(fecha, hay un encabezado que no se lee) del comienzo de `texto`. Ver `_fecha_encabezado`.
    `relectura`: `texto` empieza en un renglón posterior a un oficio de notificación. Ahí solo vale una
    «Ciudad, fecha» propia (o un encabezado ilegible): la fecha sola y «Fecha:» serían fechas del oficio o
    del cuerpo, no de la providencia, y un encabezado legible que solo menciona un oficio no debe acabar
    leyéndose desde una fecha del cuerpo."""
    seccion = _SECCION.search(texto)
    zona = min(seccion.start() if seccion else len(texto), ZONA_ENCABEZADO)
    fechas = [f for f in _fechas(texto[: zona + 200]) if f[0] < zona]

    def ini_renglon(pos: int) -> int:
        return texto.rfind("\n", 0, pos) + 1

    def fin_renglon(pos: int) -> int:
        fin = texto.find("\n", pos)
        return fin if fin >= 0 else len(texto)

    def antes_de(pos: int) -> str:
        return texto[ini_renglon(pos) : pos]

    def columna(pos: int) -> str:  # «JUZGADO …      Medellín, » en columnas (pdftotext -layout)
        antes = antes_de(pos)
        sin_cola = antes.rstrip()
        return _COLUMNAS.split(sin_cola)[-1] + antes[len(sin_cola) :]

    def cola(fin: int) -> str:  # \r: saltos de línea de pdfium
        return texto[fin : fin_renglon(fin)].strip("\r")

    def con_ciudad(pos: int, fin: int) -> bool:
        if not _CIUDAD_Y_COMA.search(columna(pos)):
            return False
        resto = re.split(r"[ \t]{3,}", cola(fin))[0]  # otra columna a la derecha
        return not re.match(r"[\s.,;:)\-–—]*[a-záéíóúüñ]", resto)  # «…2026: la accionante radicó», «…2026 ocurrió»

    def a_medias(pos: int) -> bool:  # el renglón anterior sigue en este: «…mediante oficio del» ⏎ «20 de agosto…»
        previo = texto[: ini_renglon(pos)].rstrip()
        linea = previo[previo.rfind("\n") + 1 :].rstrip()
        ultima = re.search(r"([^\W\d_]+)[\s)\"'»”]*$", linea)
        return bool(linea) and (linea[-1] in ",;" or bool(ultima and ultima.group(1)[0].islower()))

    def sola(pos: int, fin: int) -> bool:
        antes = antes_de(pos)
        if not _ROTULO_FECHA.match(antes) or cola(fin).strip(" .,;\t"):
            return False
        return antes.strip() != "" or not a_medias(pos)

    def propias(candidatas: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
        return [c for c in candidatas if not _OFICIO.search(_plano(texto[c[0] : c[0] + VENTANA_OFICIO]))]

    ciudad = [f for f in fechas if con_ciudad(f[0], f[1])]
    leidos = {ini_renglon(f[0]) for f in ciudad}
    # Renglón con aire de «Ciudad, fecha» que no se leyó: el encabezado existe pero es ilegible
    # («Medellín, 28.IX.2026», «Medellín 28 de septiembre de 2026», «medellín, 28 de …») o fecha que no se entiende.
    sin_leer = [
        m.start()
        for m in re.finditer(r"^.*\S.*$", texto[:zona], re.M)
        if m.start() not in leidos and any(_CIUDAD_Y_CIFRAS.match(c) for c in _COLUMNAS.split(m.group()))
    ]
    sin_leer += [
        ini_renglon(f[0])
        for f in fechas
        if f not in ciudad
        and not _ROTULO_FECHA.match(antes_de(f[0]))
        and (_CIUDAD_SOLA.match(columna(f[0])) or _LUGAR_CON_SEPARADOR.match(columna(f[0])))
    ]
    sin_leer += [
        ini_renglon(m.start())
        for m in _FECHA_DUDOSA.finditer(texto[:zona])
        if not any(f[0] < m.end() and m.start() < f[1] for f in fechas)
    ]
    ciudad = [f for f in ciudad if f[0] < min(sin_leer, default=len(texto))]
    if ciudad:
        if propias(ciudad):
            return propias(ciudad)[0][2], False
        # Solo hay oficios de notificación: la providencia empieza después, aunque el oficio sea largo (o
        # traiga numerales). Se vuelve a leer el comienzo desde cada renglón con texto que sigue al oficio y
        # que está antes del cuerpo de la providencia (el primer HECHOS, ANTECEDENTES…): una «Ciudad, fecha»
        # citada en el cuerpo no es su encabezado. Si ninguna relectura da una «Ciudad, fecha» propia ni un
        # encabezado ilegible, vale la primera «Ciudad, fecha»: un encabezado legible que solo menciona un
        # oficio (dentro de VENTANA_OFICIO) conserva su fecha.
        if not relectura:
            ini = ciudad[-1][1]
            cuerpo = _SECCION_TITULADA.search(texto, ini)
            limite = cuerpo.start() if cuerpo else len(texto)
            for m in list(re.finditer(r"\n(?=[^\S\n]*\S)", texto[ini:limite]))[:MAX_REINICIOS]:
                fecha, ilegible = _leer_encabezado(texto[ini + m.end() :], relectura=True)
                if fecha or ilegible:
                    return fecha, ilegible
            return ciudad[0][2], False
        return None, False
    if sin_leer:  # hay encabezado y no se lee: ni la fecha sola ni «Fecha:» lo sustituyen
        return None, True
    if relectura:
        return None, False
    solas = [f for f in fechas if sola(f[0], f[1])]
    elegidas = propias(solas) or solas
    return (elegidas[0][2] if elegidas else None), False


def _fecha_correo(texto: str) -> str | None:
    m = _FECHA_CORREO.search(texto[:4000])
    halladas = fechas_en(m.group(1)) if m else []
    return halladas[0][1] if halladas else None


_FILA_PARTE = re.compile(
    r"\b(DEMANDANTE\s*/\s*ACCION\w*|DEMANDADO\s*/\s*INDICIADO\S*)\s*$"
)
_ID = re.compile(r"\b[A-Z]{0,3}\d{5,}\b")
_TIPO_ID = re.compile(
    r"^(?:C[ÉE]DULA\s+DE\s+(?:CIUDADAN[ÍI]A|EXTRANJER[ÍI]A)|NIT|SIN\s+DOCUMENTO|PASAPORTE|TARJETA\s+DE\s+IDENTIDAD|REGISTRO\s+CIVIL|PERMISO\s+\w+(?:\s+\w+){0,3}?)\s+"
)
_CONTINUACION = re.compile(r"^\s*(\S.*?)\s+ANTE\s*$")
_ETIQUETA_PARTE = re.compile(
    r"^[ \t]*(?:(Accionantes?|Accionad[oa]s?|Demandad[oa]s?|Vinculad[oa]s?)(?:[ \t]*:[ \t]*|[ \t]{2,})"
    r"|(ACCIONANTES?|ACCIONAD[OA]S?|DEMANDAD[OA]S?|VINCULAD[OA]S?)[ \t]*:?[ \t]+)(\S.*)$"
)


def _nombre_fila(contenido: str) -> str:
    tipo = _TIPO_ID.match(contenido)
    resto = contenido[tipo.end() :] if tipo else contenido
    i = _ID.search(resto)
    if i:
        return resto[i.end() :].strip()
    if tipo and re.match(r"SIN\s+DOCUMENTO", tipo.group()):
        resto = re.sub(r"^SD(?=\s|[A-ZÁÉÍÓÚÑ])\s*", "", resto)
    return resto.strip()


def _partes_tabla(texto: str) -> tuple[list[str], list[str]]:
    accionantes: list[str] = []
    accionadas: list[str] = []
    lineas = texto.splitlines()
    for k, linea in enumerate(lineas):
        m = _FILA_PARTE.search(linea)
        if not m:
            continue
        contenido = " ".join(linea[: m.start()].split())
        nombre = _nombre_fila(contenido)
        sigue = _CONTINUACION.match(lineas[k + 1]) if k + 1 < len(lineas) else None
        if sigue and m.group(1).startswith("DEMANDADO") and not _TIPO_ID.match(sigue.group(1)):
            nombre = f"{nombre} {' '.join(sigue.group(1).split())}".strip()
        if nombre:
            (accionantes if m.group(1).startswith("DEMANDANTE") else accionadas).append(
                nombre
            )
    return accionantes, accionadas


def _partes_etiquetas(texto: str) -> tuple[list[str], list[str]]:
    accionantes: list[str] = []
    accionadas: list[str] = []
    lineas = texto.splitlines()
    for k, linea in enumerate(lineas):
        m = _ETIQUETA_PARTE.match(linea)
        if not m:
            continue
        etiqueta = _plano(m.group(1) or m.group(2))
        valor = [m.group(3)]
        for sig in lineas[k + 1 : k + 4]:
            if not sig.strip() or not sig[0].isspace() or _ETIQUETA_PARTE.match(sig):
                break
            valor.append(sig)
        nombre = " ".join(" ".join(valor).split())
        if etiqueta.startswith(("accionante", "demandante")):
            accionantes.append(nombre)
        elif not etiqueta.startswith("vinculad"):
            accionadas.append(nombre)
    return accionantes, accionadas


def _unicos(valores: list[str]) -> list[str]:
    return list(dict.fromkeys(valores))


def _un_accionante(acc: list[str], d: Doc, alertas: list[str] | None) -> str | None:
    unicos = _unicos(acc)
    if len(unicos) > 1 and alertas is not None:
        alertas.append(
            f"{d.doc_id} {d.nombre}: hay varios accionantes ({'; '.join(unicos)}), posible agencia oficiosa; se usó el primero ({unicos[0]}), ajustar a mano si corresponde."
        )
    return unicos[0] if unicos else None


def _primera_pagina(d: Doc) -> str:
    return d.paginas[0].texto if d.paginas else ""


def _partes_acta(utiles: list[Doc]) -> tuple[Doc, list[str], list[str]] | None:
    actas = [d for d in utiles if d.rol == "acta_reparto_2a"]
    actas += [d for d in utiles if d.rol == "acta_reparto_1a"]
    for d in actas:
        acc, dem = _partes_tabla(_primera_pagina(d))
        if acc or dem:
            return d, acc, dem
    return None


def _extraer_partes(
    utiles: list[Doc], alertas: list[str] | None = None
) -> tuple[str | None, list[str]]:
    acta = _partes_acta(utiles)
    if acta is not None:
        d, acc, dem = acta
        return _un_accionante(acc, d, alertas), _unicos(dem)
    for d in (d for d in utiles if d.rol in ("fallo_a_quo", "auto_admisorio")):
        acc, dem = _partes_etiquetas(_primera_pagina(d))
        if acc or dem:
            if alertas is not None:
                alertas.append(
                    f"{d.doc_id} {d.nombre}: no hay acta de reparto legible; las partes se tomaron de las etiquetas del documento, revisarlas."
                )
            return _un_accionante(acc, d, alertas), _unicos(dem)
    return None, []


_AMPLIACION = re.compile(r"ampliaci|adicion|complement")


def _asunto(d: Doc) -> str:
    t = _plano(d.texto()[:600])
    i = t.find("desde")
    return t[: i if i >= 0 else 300]


def _extraer_fechas(utiles: list[Doc]) -> Fechas:
    def primero(rol: str) -> Doc | None:
        return next((d for d in utiles if d.rol == rol), None)

    def encabezado(rol: str) -> str | None:
        d = primero(rol)
        return _fecha_encabezado(d.texto()) if d else None

    acta = next((d for d in utiles if d.rol == "acta_reparto_2a"), None)
    reparto = fechas_en(_primera_pagina(acta)) if acta else []
    fallo = encabezado("fallo_a_quo")
    notificaciones = [
        f
        for d in utiles
        if d.rol == "notificacion"
        and re.search(r"fallo|sentencia", _asunto(d) + " " + _plano(d.nombre))
        and (f := _fecha_correo(d.texto()))
        and (not fallo or f >= fallo)
    ]
    impugnaciones = [d for d in utiles if d.rol == "impugnacion"]
    principales = [
        d for d in impugnaciones if not _AMPLIACION.search(_asunto(d) + " " + _plano(d.nombre))
    ] or impugnaciones
    fechas_impugnacion = [f for d in principales if (f := _fecha_correo(d.texto()))]
    if not fechas_impugnacion and principales:
        fechas_impugnacion = [f for f in [_fecha_encabezado(principales[0].texto())] if f]
    fecha_impugnacion = min(fechas_impugnacion, default=None)
    return Fechas(
        admision=encabezado("auto_admisorio"),
        fallo_a_quo=fallo,
        notificacion_fallo=min(notificaciones, default=None),
        impugnacion=fecha_impugnacion,
        concesion_impugnacion=encabezado("auto_concede_impugnacion"),
        reparto_2a=reparto[0][1] if reparto else None,
    )


def _recolectar(base: Path) -> tuple[list[Path], list[str], list[str]]:
    archivos: list[Path] = []
    alertas: list[str] = []
    ignorados: list[str] = []
    todos = sorted(
        base.rglob("*"), key=lambda p: p.relative_to(base).as_posix().casefold()
    )
    nivel = min(
        (
            i
            for p in todos
            for i, c in enumerate(p.relative_to(base).parts[:-1])
            if _es_primera(c)
        ),
        default=0,
    )
    for p in todos:
        if (
            not p.is_file()
            or p.name.startswith((".", "~$"))
            or p.name.lower() == "thumbs.db"
        ):
            continue
        partes = p.relative_to(base).parts
        i = nivel if len(partes) > nivel + 1 and es_segunda(partes[nivel]) else None
        if i is not None:
            carpeta = "/".join(partes[: i + 1])
            if carpeta not in ignorados:
                ignorados.append(carpeta)
            continue
        if p.suffix.lower() in EXTENSIONES:
            archivos.append(p)
        else:
            alertas.append(
                f"{p.relative_to(base).as_posix()}: formato no soportado ({p.suffix or 'sin extensión'}); se omite."
            )
    return archivos, alertas, ignorados


def _cuis_cabecera(d: Doc) -> Counter:
    return Counter(extraer_cuis(texto_cabecera(d)))


ROLES_ANCLA = (
    "escrito_tutela",
    "auto_admisorio",
    "fallo_a_quo",
    "impugnacion",
    "auto_concede_impugnacion",
)


def _prefijo_caso(docs: list[Doc]) -> str | None:
    actas = [d for d in docs if d.rol in ("acta_reparto_2a", "acta_reparto_1a")]
    for fuente in (actas, [d for d in docs if d.rol in ROLES_ANCLA], docs):
        votos: Counter = Counter()
        for d in fuente:
            votos.update({cui[:21] for cui in _cuis_cabecera(d)})
        if votos:
            return votos.most_common(1)[0][0]
    return None


_JUZGADO_PENAL = re.compile(
    r"juzgado\s+(\d+|[^\W\d_]+(?:\s+y\s+[^\W\d_]+)?)\s+(?:\(\s*\d+\s*\)\s+)?penal\s+municipal"
)
_JUZGADO = re.compile(
    r"Juzgado\s+([^\W\d_]+(?:\s+(?:y\s+)?[^\W\d_]+){0,2}?)\s+(?:\(\s*\d+\s*\)\s+)?Penal\s+Municipal(?:\s+de\s+Medell[ií]n)?,?\s+con\s+Funci(ón|ones|on)\s+de\s+(Conocimiento|Control\s+de\s+Garant[ií]as)",
    re.I,
)


def _titulo(letras: str) -> str:
    return " ".join(
        p.lower() if p.lower() == "y" else p.capitalize() for p in letras.split()
    )


def _juzgado_a_quo(docs: list[Doc], cui_1a: str | None, alertas: list[str]) -> dict:
    ref = juzgado_de_radicado(cui_1a) if cui_1a else None
    if ref is None:
        return {}
    fallo = next((d for d in docs if d.rol == "fallo_a_quo" and not d.ruido), None)
    hallados = list(_JUZGADO.finditer(fallo.texto())) if fallo else []
    coincidentes = [
        m for m in hallados if letras_a_numero(m.group(1)) == ref.numero
    ]
    coincide = coincidentes[0] if coincidentes else None
    if coincide is not None:
        funcion = (
            "control_garantias"
            if "garant" in _plano(coincide.group(3))
            else "conocimiento"
        )
        if funcion != ref.funcion:
            alertas.append(
                f"El fallo de 1.ª instancia nombra un juzgado de función distinta a la del radicado ({ref.funcion})."
            )
        j = Juzgado(
            numero=ref.numero,
            funcion=ref.funcion,
            letras=Counter(_titulo(m.group(1)) for m in coincidentes).most_common(
                1
            )[0][0],
            plural=2 * sum(m.group(2).lower() == "ones" for m in coincidentes)
            > len(coincidentes),
        )
        derivado = False
    else:
        j, derivado = ref, True
        if hallados:
            alertas.append(
                f"El juzgado nombrado en el fallo ('{hallados[0].group(1)}') no coincide con el número del radicado ({ref.numero}); se deriva del radicado."
            )
        else:
            alertas.append(
                "No se encontró el nombre del juzgado de origen en el fallo de 1.ª instancia; se deriva del radicado."
            )
    return {
        "juzgado_a_quo": nombre_juzgado(j, "cuerpo"),
        "juzgado_a_quo_numero": j.numero,
        "juzgado_a_quo_funcion": j.funcion,
        "juzgado_a_quo_letras": j.letras,
        "juzgado_a_quo_plural": j.plural,
        "juzgado_a_quo_derivado": derivado,
    }


def _palabras(texto: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", _plano(texto))) + " "


def _nombra_alguno(palabras: str, nombres: list[str]) -> bool:
    frases = (" ".join(_palabras(n).split()) for n in nombres)
    return any(len(f) >= 6 and f" {f} " in palabras for f in frases)


def _nombra_juzgado(texto: str, numero: int) -> bool:
    for m in _JUZGADO_PENAL.finditer(_plano(texto)):
        n = m.group(1)
        if (int(n) if n.isdigit() else letras_a_numero(n)) == numero:
            return True
    return False


def _cuis_ajenos(d: Doc, prefijo: str) -> list[str]:
    if d.rol_origen == "usuario":
        return []
    cabecera = list(_cuis_cabecera(d))
    if not cabecera or any(c.startswith(prefijo) for c in cabecera):
        return []
    if menciona_radicado(texto_cabecera(d), prefijo):
        return []
    return cabecera


def _nombra_al_caso(
    d: Doc, accionantes: list[str], accionadas: list[str], juzgado: Juzgado | None
) -> str | None:
    texto = d.texto()
    palabras = _palabras(texto)
    if _nombra_alguno(palabras, accionantes):
        return "al accionante"
    if _nombra_alguno(palabras, accionadas):
        return "a la accionada"
    if juzgado is not None and _nombra_juzgado(texto, juzgado.numero):
        return "al juzgado de primera instancia"
    return None


def _alertas_fechas(legibles: list[Doc], fechas: Fechas) -> list[str]:
    alertas = []
    for rol, valor, de_que, marca in (
        ("fallo_a_quo", fechas.fallo_a_quo, "del fallo de primera instancia", "⟦FALTA: fecha⟧ en el fallo y ⟦FALTA: fecha de la providencia⟧ en el formato de calidad"),
        ("auto_admisorio", fechas.admision, "del auto admisorio", "⟦FALTA: fecha de admisión⟧ en el formato de calidad"),
    ):
        d = next((d for d in legibles if d.rol == rol), None)
        if d is not None and valor is None:
            alertas.append(
                f"No se pudo leer la fecha {de_que} en el encabezado de «{d.nombre}»; saldrá como {marca}. "
                "Verifíquela en el documento y complétela a mano."
            )
    return alertas


def _derivar(
    docs: list[Doc],
    ignorados: list[str],
    alertas_lectura: list[str],
    llamadas_jev: list[dict] | None = None,
) -> Ingesta:
    derivadas: list[str] = []
    for carpeta in ignorados:
        derivadas.append(
            f"Se ignoró la carpeta {carpeta}: corresponde a segunda instancia y no se lee."
        )

    for d in docs:
        d.cuis = list(Counter(extraer_cuis(d.texto())))
    prefijo = _prefijo_caso(docs)
    ajenos: list[str] = []
    revisar: list[str] = []
    if prefijo is None:
        derivadas.append(
            "No se encontró ningún CUI de 23 dígitos; no se pudo verificar la pertenencia de los documentos al caso."
        )
    else:
        fuera = {d.doc_id: c for d in docs if (c := _cuis_ajenos(d, prefijo))}
        acta = _partes_acta(
            [d for d in docs if d.doc_id not in fuera or d.rol in ROLES_OBLIGATORIOS]
        )
        accionantes = _unicos(acta[1]) if acta else []
        accionadas = _unicos(acta[2]) if acta else []
        juzgado = juzgado_de_radicado(prefijo + "00")
        for d in docs:
            cabecera = fuera.get(d.doc_id)
            if not cabecera:
                continue
            if d.rol in ROLES_OBLIGATORIOS:
                derivadas.append(
                    f"{d.doc_id} {d.nombre}: es {d.rol} pero sus CUIs ({', '.join(cabecera)}) no corresponden al caso {prefijo}; revisar."
                )
                continue
            nombra = _nombra_al_caso(d, accionantes, accionadas, juzgado)
            if nombra:
                revisar.append(d.doc_id)
                derivadas.append(
                    f"{d.doc_id} {d.nombre}: sus CUIs ({', '.join(cabecera)}) no corresponden al caso {prefijo}, pero el texto nombra {nombra}; queda para revisar y se entrega al modelo con una marca."
                )
                continue
            ajenos.append(d.doc_id)
            derivadas.append(
                f"{d.doc_id} {d.nombre}: sus CUIs ({', '.join(cabecera)}) no corresponden al caso {prefijo}; se trata como ajeno."
            )

    vistos: dict[str, str] = {}
    for d in docs:
        d.ruido, d.motivo_ruido = False, ""
        for p in d.paginas:
            p.ruido = not p.sin_texto and _es_certificado(p.texto)
        con_texto = [p for p in d.paginas if not p.sin_texto]
        if con_texto and all(p.ruido for p in con_texto):
            d.ruido, d.motivo_ruido = (
                True,
                "Certificado de existencia y representación legal",
            )
        elif d.sha256 in vistos:
            d.ruido, d.motivo_ruido = True, f"Duplicado exacto de {vistos[d.sha256]}"
        vistos.setdefault(d.sha256, d.doc_id)

    utiles = [d for d in docs if d.doc_id not in ajenos and d.doc_id not in revisar]
    presentes = {d.rol for d in utiles}
    faltantes = [r for r in ROLES_OBLIGATORIOS if r not in presentes]
    esperados = [r for r in ROLES_ESPERADOS if r not in presentes]
    for d in utiles:
        ciegas = [p.n for p in d.paginas if p.sin_texto]
        if d.rol in ROLES_OBLIGATORIOS and ciegas:
            derivadas.append(
                f"{d.doc_id} {d.nombre} ({d.rol}): páginas sin texto legible: {', '.join(map(str, ciegas))}."
            )

    for d in docs:
        if d.doc_id not in ajenos and d.rol == "otro" and d.evidencia.startswith(
            ("Otra sentencia del mismo caso", "Sentencia de otro radicado")
        ):
            derivadas.append(f"{d.doc_id} {d.nombre}: {d.evidencia}")
    for rol in ("fallo_a_quo", "acta_reparto_2a"):
        varios = [d.doc_id for d in utiles if d.rol == rol and not d.ruido]
        if len(varios) > 1:
            derivadas.append(
                f"Hay más de un documento con rol {rol} ({', '.join(varios)}); los metadatos salen del primero."
            )
    if prefijo is not None:
        for d in utiles:
            if d.rol == "fallo_a_quo" and not d.ruido and (
                prefijo + "01" in _cuis_cabecera(d)
                or re.search(r"penal\s+del\s+circuito", _plano(texto_cabecera(d)[:1500]))
            ):
                derivadas.append(
                    f"{d.doc_id} {d.nombre}: el fallo de 1.ª instancia parece de un Juzgado Penal del Circuito o de la impugnación (segunda instancia); revisar."
                )

    accionante, accionadas = _extraer_partes(utiles, derivadas)
    legibles = [d for d in utiles if not d.ruido]
    cui_1a_ = prefijo + "00" if prefijo else None
    metadatos = Metadatos(
        cui_1a=cui_1a_,
        cui_2a=prefijo + "01" if prefijo else None,
        accionante=accionante,
        accionadas=accionadas,
        fechas=_extraer_fechas(legibles),
        **_juzgado_a_quo(legibles, cui_1a_, derivadas),
    )
    derivadas += _alertas_fechas(legibles, metadatos.fechas)
    return Ingesta(
        documentos=docs,
        docs_ajenos=ajenos,
        docs_revisar=revisar,
        faltantes=faltantes,
        esperados_faltantes=esperados,
        alertas=alertas_lectura + derivadas,
        alertas_lectura=alertas_lectura,
        ignorados=ignorados,
        metadatos=metadatos,
        llamadas_jev=list(llamadas_jev or []),
    )


def reaplicar(ing: Ingesta, roles: dict[str, Rol]) -> Ingesta:
    docs = [d.model_copy(deep=True) for d in ing.documentos]
    for d in docs:
        if d.doc_id in roles and (
            roles[d.doc_id] != d.rol
            or d.doc_id in ing.docs_ajenos
            or d.doc_id in ing.docs_revisar
            or d.rol_origen == "jev"
        ):
            d.rol, d.rol_origen = roles[d.doc_id], "usuario"
            d.evidencia = "Rol fijado por el usuario."
    fijados = {d.doc_id: d.rol for d in docs if d.rol_origen == "usuario"}
    if fijados:
        eventos.emitir("ingesta", "lee", f"Se conservan {len(fijados)} roles fijados por el usuario.", {"roles": fijados})
    nueva = _derivar(docs, list(ing.ignorados), list(ing.alertas_lectura), ing.llamadas_jev)
    if fijados:
        _emitir_faltantes(nueva)
    return nueva


def _segunda_opinion_jev(
    docs: list[Doc], cfg: Config, jev: JevClient | None
) -> tuple[list[str], list[dict]]:
    if cfg.jev.modo == "apagado":
        return [], []
    cliente = jev if jev is not None else cliente_jev(cfg)
    if cliente is None:
        return [], []
    llamadas: list[dict] = []
    opiniones, alertas = segunda_opinion(docs, cliente, cfg, llamadas=llamadas)
    return alertas + aplicar(docs, opiniones, cfg), llamadas


def ingerir(caso_dir: Path, cfg: Config, jev: JevClient | None = None) -> Ingesta:
    base = Path(caso_dir) / "insumos"
    if not base.is_dir():
        return Ingesta(
            documentos=[],
            faltantes=list(ROLES_OBLIGATORIOS),
            esperados_faltantes=list(ROLES_ESPERADOS),
            alertas=[f"No existe la carpeta de insumos: {base}."],
        )
    archivos, alertas_lectura, ignorados = _recolectar(base)
    por_tipo = Counter(r.suffix.lower().lstrip(".").upper() for r in archivos)
    eventos.emitir(
        "ingesta",
        "lee",
        f"Se leen {len(archivos)} archivos de insumos ({', '.join(f'{n} {t}' for t, n in sorted(por_tipo.items())) or 'ninguno'})"
        + (f"; {len(alertas_lectura)} con formato no soportado" if alertas_lectura else "")
        + (f"; se ignoran {len(ignorados)} carpetas de segunda instancia" if ignorados else "")
        + ".",
        {"archivos": len(archivos), "por_tipo": dict(por_tipo), "no_soportados": len(alertas_lectura), "ignorados": ignorados},
    )

    docs: list[Doc] = []
    for i, ruta in enumerate(archivos, 1):
        docs.append(
            Doc(
                doc_id=f"1a-{i:03d}",
                ruta=ruta.relative_to(base).as_posix(),
                nombre=ruta.name,
                instancia="1a",
                rol="otro",
                sha256=_sha256(ruta),
                paginas=[],
            )
        )

    ocr = cfg.ocr and _ocr_disponible()
    dir_cache = (cfg.cache_path() / "ocr-psm1") if ocr else None
    previo = os.environ.get("OMP_THREAD_LIMIT")
    os.environ["OMP_THREAD_LIMIT"] = "1"
    try:
        leidos = _leer_expediente(archivos, docs, dir_cache)
    finally:
        if previo is None:
            os.environ.pop("OMP_THREAD_LIMIT", None)
        else:
            os.environ["OMP_THREAD_LIMIT"] = previo
    for d, (paginas, alertas_pagina) in zip(docs, leidos):
        d.paginas = paginas
        alertas_lectura += alertas_pagina
    if not shutil.which("pdftotext") and any(
        r.suffix.lower() == ".pdf" for r in archivos
    ):
        alertas_lectura.append(
            "pdftotext (poppler-utils) no está instalado: se usa pypdf, que ordena peor el texto y puede fallar con PDF cifrados."
        )
    if cfg.ocr and not ocr and any(p.sin_texto for d in docs for p in d.paginas):
        alertas_lectura.append(
            "OCR no disponible (falta tesseract o el extra 'ocr'): las páginas escaneadas no se pueden leer."
        )

    for d in docs:
        d.rol, d.evidencia = clasificar(d)
    prefijo = _prefijo_caso(docs)
    resolver_caso(docs, prefijo)
    alertas_jev, llamadas_jev = _segunda_opinion_jev(docs, cfg, jev)
    alertas_lectura += alertas_jev
    if cfg.jev.modo != "apagado":
        con_opinion = sum(1 for d in docs if d.jev_rol)
        eventos.emitir(
            "ingesta",
            "verifica",
            f"Segunda opinión de Jev (modo {cfg.jev.modo}): {len(llamadas_jev)} consultas, "
            f"{con_opinion} de {len(docs)} documentos con rol propuesto, {len(alertas_jev)} alertas.",
            {"modo": cfg.jev.modo, "consultas": len(llamadas_jev), "con_opinion": con_opinion, "alertas": alertas_jev},
        )
    if cfg.jev.modo == "relleno":
        resolver_caso(docs, prefijo)
        for d in docs:
            if d.rol_origen == "jev" and d.rol != d.jev_rol:
                d.rol_origen = "contenido"
    ing = _derivar(docs, ignorados, alertas_lectura, llamadas_jev)
    for d in ing.documentos:
        jev_txt = (
            f"; Jev propone {d.jev_rol} ({d.jev_confianza:.0%})"
            if d.jev_rol and d.jev_confianza is not None
            else (f"; Jev propone {d.jev_rol}" if d.jev_rol else "")
        )
        eventos.emitir(
            "ingesta",
            "lee",
            f"{d.ruta}: rol {d.rol} (origen: {d.rol_origen}){jev_txt}"
            + ("; ajeno al caso" if d.doc_id in ing.docs_ajenos else "")
            + ("; para revisar" if d.doc_id in ing.docs_revisar else "")
            + (f"; ruido: {d.motivo_ruido}" if d.ruido else "")
            + ".",
            {
                "doc_id": d.doc_id,
                "archivo": d.ruta,
                "rol": d.rol,
                "rol_origen": d.rol_origen,
                "evidencia": d.evidencia,
                "jev_rol": d.jev_rol,
                "jev_confianza": d.jev_confianza,
                "ajeno": d.doc_id in ing.docs_ajenos,
                "revisar": d.doc_id in ing.docs_revisar,
                "ruido": d.ruido,
            },
        )
    _emitir_faltantes(ing)
    return ing


def _emitir_faltantes(ing: Ingesta) -> None:
    eventos.emitir(
        "ingesta",
        "verifica",
        (
            f"Faltan documentos obligatorios: {', '.join(ing.faltantes)}."
            if ing.faltantes
            else f"Están los documentos obligatorios: {', '.join(ROLES_OBLIGATORIOS)}."
        )
        + (f" No se encontraron: {', '.join(ing.esperados_faltantes)}." if ing.esperados_faltantes else "")
        + (f" {len(ing.alertas)} alertas de ingesta." if ing.alertas else ""),
        {"faltantes": ing.faltantes, "esperados_faltantes": ing.esperados_faltantes, "alertas": len(ing.alertas)},
    )


def texto_para_llm(
    ing: Ingesta, roles: set[str] | None = None, max_chars: int = 120000
) -> str:
    bloques = []
    for d in ing.documentos:
        if d.ruido or d.doc_id in ing.docs_ajenos or d.rol == "producto_despacho":
            continue
        if roles is not None and d.rol not in roles:
            continue
        cuerpo = "\n".join(
            f"[p. {p.n}]\n{p.texto}" for p in d.paginas if p.texto and not p.ruido
        )
        if not cuerpo:
            continue
        if len(cuerpo) > max_chars:
            cuerpo = cuerpo[:max_chars] + "\n[... TRUNCADO ...]"
            alerta = f"{d.doc_id} {d.nombre}: texto truncado a {max_chars} caracteres para el LLM."
            if alerta not in ing.alertas:
                ing.alertas.append(alerta)
        if d.doc_id in ing.docs_revisar:
            cuerpo = f"{AVISO_REVISAR}\n{cuerpo}"
        bloques.append(f"### DOC {d.doc_id} | {d.rol} | {d.nombre}\n{cuerpo}")
    return "\n\n".join(bloques)


ETIQUETA_CERTIFICADO = "· CERTIFICADO DE EXISTENCIA"
ROLES_ESCRITOS = ("escrito_tutela", "contestacion", "impugnacion", "memorial")
_CLAVES_APODERADOS = re.compile(
    r"apoderad|abogad|poderdante|\bpoder(?:es)?\s+(?:especial|general|amplio)|\b(?:confiero|otorgo|sustituyo|reasumo)\b"
    r"|\bt\.\s?p\.|\btp\b|tarjeta\s+profesional|representante\s+legal|sustitucion\s+de(?:l)?\s+poder"
)
_PRIORIDAD_CLAVE, _PRIORIDAD_BORDE = 0, 1


def es_pagina_certificado(p: Pagina) -> bool:
    return not p.sin_texto and (p.ruido or _es_certificado(p.texto))


def documentos_para_apoderados(ing: Ingesta) -> list[Doc]:
    return [
        d
        for d in ing.documentos
        if d.doc_id not in ing.docs_ajenos
        and d.rol != "producto_despacho"
        and not (d.ruido and d.motivo_ruido.startswith("Duplicado"))
    ]


def paginas_para_apoderados(ing: Ingesta, max_chars: int = 150_000) -> tuple[str, list[str]]:
    """Páginas del expediente que sirven para identificar a los abogados y sus poderes.

    Toma las páginas que nombran poderes, apoderados, abogados, tarjetas profesionales o
    representantes legales; la primera y la última de cada escrito de parte, y todas las páginas
    de certificados de existencia y representación (que ``texto_para_llm`` omite por ser ruido),
    marcadas con ``ETIQUETA_CERTIFICADO``. Usa el formato ``### DOC`` / ``[p. N]`` de
    ``texto_para_llm``, que no cambia. Si las páginas superan ``max_chars``, deja primero las
    más pertinentes y devuelve una alerta con lo omitido.
    """
    candidatas: list[tuple[int, int, int, Doc, Pagina]] = []
    docs = documentos_para_apoderados(ing)
    for i, d in enumerate(docs):
        legibles = [p for p in d.paginas if p.texto.strip() and not p.sin_texto]
        bordes = {legibles[0].n, legibles[-1].n} if legibles and d.rol in ROLES_ESCRITOS else set()
        for p in legibles:
            if es_pagina_certificado(p) or _CLAVES_APODERADOS.search(_plano(p.texto)):
                candidatas.append((_PRIORIDAD_CLAVE, i, p.n, d, p))
            elif p.n in bordes:
                candidatas.append((_PRIORIDAD_BORDE, i, p.n, d, p))

    def encabezado(d: Doc) -> str:
        aviso = f"\n{AVISO_REVISAR}" if d.doc_id in ing.docs_revisar else ""
        return f"### DOC {d.doc_id} | {d.rol} | {d.nombre}{aviso}"

    restante = max_chars
    elegidas: dict[int, dict[int, str]] = {}
    omitidas, truncada = 0, False
    for prioridad, i, n, d, p in sorted(candidatas, key=lambda c: c[:3]):
        rotulo = f"[p. {p.n}] {ETIQUETA_CERTIFICADO}" if es_pagina_certificado(p) else f"[p. {p.n}]"
        bloque = f"{rotulo}\n{p.texto}"
        extra = 0 if i in elegidas else len(encabezado(d)) + 3
        if len(bloque) + 1 + extra <= restante:
            elegidas.setdefault(i, {})[n] = bloque
            restante -= len(bloque) + 1 + extra
        elif prioridad == _PRIORIDAD_CLAVE and restante - extra > 500:
            elegidas.setdefault(i, {})[n] = bloque[: restante - extra - 30] + "\n[... TRUNCADO ...]"
            restante, truncada = 0, True
        else:
            omitidas += 1

    bloques = [
        f"{encabezado(docs[i])}\n" + "\n".join(paginas[n] for n in sorted(paginas))
        for i, paginas in sorted(elegidas.items())
    ]
    alertas: list[str] = []
    if omitidas or truncada:
        alertas.append(
            f"ALERTA: Identificación de apoderados: las páginas pertinentes superan el tope de {max_chars} caracteres; "
            f"se omitieron {omitidas}{' y se truncó una' if truncada else ''}. Puede faltar algún abogado o poder."
        )
    return "\n\n".join(bloques), alertas
