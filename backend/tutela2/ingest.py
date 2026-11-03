from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
from .config import Config
from .letras import letras_a_numero
from .models import Doc, Fechas, Ingesta, Metadatos, Pagina, Rol
from .radicado import Juzgado, juzgado_de_radicado, nombre_juzgado

log = logging.getLogger("tutela2")

MIN_CHARS_PAGINA = 30
OCR_DPI = 300
EXTENSIONES = {".pdf", ".docx", ".txt"}
ROLES_OBLIGATORIOS = ("escrito_tutela", "fallo_a_quo", "impugnacion")
ROLES_ESPERADOS = ("auto_admisorio", "auto_concede_impugnacion", "acta_reparto_2a")


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


def _ocr_pagina(pdf, n: int, sha: str, dir_cache: Path) -> str:
    import pytesseract

    f = dir_cache / sha / f"{n}.txt"
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        pass
    imagen = pdf[n - 1].render(scale=OCR_DPI / 72).to_pil()
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


def _aplicar_ocr(
    ruta: Path,
    doc_id: str,
    sha: str,
    dir_cache: Path,
    paginas: list[Pagina],
    alertas: list[str],
) -> None:
    import pypdfium2

    pdf = None
    try:
        pdf = pypdfium2.PdfDocument(str(ruta))
        for p in paginas:
            if not p.sin_texto:
                continue
            texto = _ocr_pagina(pdf, p.n, sha, dir_cache)
            if len(texto) >= MIN_CHARS_PAGINA and _legible(texto):
                p.texto, p.ocr, p.sin_texto = texto, True, False
    except Exception as e:
        log.warning("OCR falló en %s: %s", ruta.name, e)
        alertas.append(f"{doc_id} {ruta.name}: el OCR falló ({e}).")
    finally:
        if pdf is not None:
            pdf.close()


def _leer_documento(
    ruta: Path, doc_id: str, sha: str, dir_cache: Path | None
) -> tuple[list[Pagina], list[str]]:
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
    if (
        dir_cache is not None
        and ruta.suffix.lower() == ".pdf"
        and any(p.sin_texto for p in paginas)
    ):
        _aplicar_ocr(ruta, doc_id, sha, dir_cache, paginas, alertas)
    return paginas, alertas


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
_F_LETRAS = re.compile(
    r"(?<!\d)(\d{1,2})\)?\s+de\s+("
    + "|".join(_MESES)
    + r")\s+(?:de|del)\s+(?:[^\W\d_]+(?:\s+[^\W\d_]+){0,4}\s*\(\s*)?(\d\.?\d{3})(?!\d)",
    re.I,
)
_F_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})(?![\d/])")
_F_ISO = re.compile(r"(?<![\d\-])(\d{4})-(\d{2})-(\d{2})(?![\d\-])")
_ENCABEZADO_CIUDAD = re.compile(r"^\s*[^\W\d_][^\d\n,]{0,40},\s*[^\d\n,]*$")
_FECHA_CORREO = re.compile(r"^[ \t]*Fecha[ \t]+[^\W\d_]{2,4}\.?[ \t]+(\S+)", re.M)


def _iso(a: str, m: str | int, d: str) -> str | None:
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def fechas_en(texto: str) -> list[tuple[int, str]]:
    halladas = [
        (
            m.start(),
            _iso(m.group(3).replace(".", ""), _MESES[_plano(m.group(2))], m.group(1)),
        )
        for m in _F_LETRAS.finditer(texto)
    ]
    halladas += [
        (m.start(), _iso(m.group(3), m.group(2), m.group(1)))
        for m in _F_NUM.finditer(texto)
    ]
    halladas += [
        (m.start(), _iso(m.group(1), m.group(2), m.group(3)))
        for m in _F_ISO.finditer(texto)
    ]
    return sorted((pos, iso) for pos, iso in halladas if iso)


_OFICIO = re.compile(r"oficio\s+(?:no|n[°º.]|\d)|adjunt\w+\s+(?:el\s+)?(?:fallo|sentencia)")
VENTANA_OFICIO = 500


def _fecha_encabezado(texto: str) -> str | None:
    texto = texto[:6000]
    halladas = fechas_en(texto)
    con_ciudad = [
        (pos, iso)
        for pos, iso in halladas
        if _ENCABEZADO_CIUDAD.search(texto[texto.rfind("\n", 0, pos) + 1 : pos])
    ]
    propias = [
        (pos, iso)
        for pos, iso in con_ciudad
        if not _OFICIO.search(_plano(texto[pos : pos + VENTANA_OFICIO]))
    ]
    for pos, iso in propias or con_ciudad:
        return iso
    return halladas[0][1] if halladas else None


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


def _extraer_partes(
    utiles: list[Doc], alertas: list[str] | None = None
) -> tuple[str | None, list[str]]:
    actas = [d for d in utiles if d.rol == "acta_reparto_2a"]
    actas += [d for d in utiles if d.rol == "acta_reparto_1a"]
    for d in actas:
        acc, dem = _partes_tabla(_primera_pagina(d))
        if acc or dem:
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


def _derivar(
    docs: list[Doc], ignorados: list[str], alertas_lectura: list[str]
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
    if prefijo is None:
        derivadas.append(
            "No se encontró ningún CUI de 23 dígitos; no se pudo verificar la pertenencia de los documentos al caso."
        )
    else:
        for d in docs:
            if d.rol_origen == "usuario":
                continue
            cabecera = list(_cuis_cabecera(d))
            if not cabecera or any(c.startswith(prefijo) for c in cabecera):
                continue
            if menciona_radicado(texto_cabecera(d), prefijo):
                continue
            if d.rol in ROLES_OBLIGATORIOS:
                derivadas.append(
                    f"{d.doc_id} {d.nombre}: es {d.rol} pero sus CUIs ({', '.join(cabecera)}) no corresponden al caso {prefijo}; revisar."
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

    utiles = [d for d in docs if d.doc_id not in ajenos]
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
    return Ingesta(
        documentos=docs,
        docs_ajenos=ajenos,
        faltantes=faltantes,
        esperados_faltantes=esperados,
        alertas=alertas_lectura + derivadas,
        alertas_lectura=alertas_lectura,
        ignorados=ignorados,
        metadatos=metadatos,
    )


def reaplicar(ing: Ingesta, roles: dict[str, Rol]) -> Ingesta:
    docs = [d.model_copy(deep=True) for d in ing.documentos]
    for d in docs:
        if d.doc_id in roles and (roles[d.doc_id] != d.rol or d.doc_id in ing.docs_ajenos):
            d.rol, d.rol_origen = roles[d.doc_id], "usuario"
            d.evidencia = "Rol fijado por el usuario."
    return _derivar(docs, list(ing.ignorados), list(ing.alertas_lectura))


def ingerir(caso_dir: Path, cfg: Config) -> Ingesta:
    base = Path(caso_dir) / "insumos"
    if not base.is_dir():
        return Ingesta(
            documentos=[],
            faltantes=list(ROLES_OBLIGATORIOS),
            esperados_faltantes=list(ROLES_ESPERADOS),
            alertas=[f"No existe la carpeta de insumos: {base}."],
        )
    archivos, alertas_lectura, ignorados = _recolectar(base)

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
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
            leidos = list(
                pool.map(
                    lambda t: _leer_documento(
                        t[0], t[1].doc_id, t[1].sha256, dir_cache
                    ),
                    zip(archivos, docs),
                )
            )
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
    resolver_caso(docs, _prefijo_caso(docs))
    return _derivar(docs, ignorados, alertas_lectura)


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
        bloques.append(f"### DOC {d.doc_id} | {d.rol} | {d.nombre}\n{cuerpo}")
    return "\n\n".join(bloques)
