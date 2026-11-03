from __future__ import annotations

import csv
import io
import logging
import re
import time
import unicodedata
import urllib.request
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from tutela2.config import Config
from tutela2.models import CitaPropuesta, CitaVerificada

log = logging.getLogger("tutela2")

BASE_RELATORIA = "https://www.corteconstitucional.gov.co/relatoria"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
MIN_BYTES_PAGINA = 20_000
EDAD_MAX_DATASET_S = 30 * 24 * 3600
TIMEOUT_S = 60
VENTANA_ID = 6000

NOMBRES_FEMENINOS = {
    "gloria", "diana", "clara", "maria", "cristina", "natalia", "paola",
    "adriana", "carmenza", "carolina", "catalina", "karena", "ligia", "lina",
    "lucy", "marcela", "martha", "myriam",
}
NO_PONENTES = {"sala plena", "conjuez"}
COLUMNAS_DATASET = ("sentencia", "magistrado_a", "fecha_sentencia")

RE_SENTENCIA = re.compile(
    r"\b(SU|T|C)(?:\s?[-.‑–]\s?|\s)?(\d{1,4})([A-Z])?"
    r"(?:\s?[-/]\s?(\d{4}|\d{2})|\s+(?i:de|del)\s+(\d{4}))(?![\dA-Za-z])"
)
RE_MP_DECLARADO = re.compile(
    r"(?i:\bM\.?\s?P\.?|magistrad[oa](?:\s+ponente)?)\s*:?\s*(?i:Dra?\.?\s+)?"
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})"
)

_PARENTESIS = re.compile(r"\([^()]{0,300}\)")
_CORCHETES = re.compile(r"\[[^\[\]]{0,300}\]")
_INVISIBLES = re.compile("[­​-‏⁠﻿]")
_MARCAS = re.compile("[̀-ͯ]")
_NO_ALFANUM = re.compile(r"[^a-z0-9ñ]+")
_ESPACIOS = re.compile(r"\s+")


class ErrorDataset(RuntimeError):
    pass


def _anio4(s: str) -> int:
    v = int(s)
    if len(s) == 4:
        return v
    return 1900 + v if v >= 92 else 2000 + v


def _clave(tipo: str, numero: int, sufijo: str, anio: int) -> str:
    return f"{tipo}-{numero:03d}{sufijo}/{anio % 100:02d}"


def _partes(m: re.Match) -> tuple[str, int, str, int]:
    tipo, numero, sufijo, a2, a4 = m.groups()
    return tipo, int(numero), sufijo or "", _anio4(a2 or a4)


def normalizar_sentencia(s: str) -> tuple[str, int, int] | None:
    m = RE_SENTENCIA.search(s.strip().upper())
    if not m:
        return None
    tipo, numero, sufijo, anio = _partes(m)
    return None if sufijo else (tipo, numero, anio)


def clave_dataset(tipo: str, numero: int, anio: int) -> str:
    return _clave(tipo, numero, "", anio)


def sentencias_en_texto(texto: str) -> set[str]:
    return {_clave(*_partes(m)) for m in RE_SENTENCIA.finditer(texto)}


def url_relatoria(tipo: str, numero: int, anio: int) -> str:
    aa = anio % 100
    nombre = f"SU{numero:03d}-{aa:02d}" if tipo == "SU" else f"{tipo}-{numero:03d}-{aa:02d}"
    return f"{BASE_RELATORIA}/{anio}/{nombre}.htm"


def _indexar(texto: str) -> dict[str, dict]:
    lector = csv.DictReader(io.StringIO(texto))
    faltan = [c for c in COLUMNAS_DATASET if c not in (lector.fieldnames or [])]
    if faltan:
        raise ValueError(f"Al CSV le faltan columnas: {', '.join(faltan)}.")
    return {f["sentencia"].strip(): f for f in lector if f.get("sentencia")}


def _descargar_dataset(url: str, destino: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        datos = r.read()
    _indexar(datos.decode("utf-8-sig"))
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_bytes(datos)
    tmp.replace(destino)


def cargar_dataset(cfg: Config) -> dict[str, dict]:
    ruta = cfg.cache_path() / "cc_sentencias.csv"
    vigente = ruta.is_file() and time.time() - ruta.stat().st_mtime < EDAD_MAX_DATASET_S
    if not vigente:
        try:
            _descargar_dataset(cfg.dataset_csv_url, ruta)
        except (OSError, ValueError, csv.Error) as e:
            if not ruta.is_file():
                raise ErrorDataset(
                    f"No se pudo descargar el dataset de sentencias ({e}) y no hay copia local en {ruta}."
                ) from e
            log.warning("No se pudo actualizar el dataset (%s); se usa la copia local %s", e, ruta)
    try:
        return _indexar(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, csv.Error) as e:
        raise ErrorDataset(f"La copia local del dataset es ilegible ({e}): {ruta}.") from e


class _ExtractorTexto(HTMLParser):
    _OMITIR = {"script", "style", "title"}
    _BLOQUES = {
        "p", "br", "div", "tr", "td", "th", "li", "ul", "ol", "table", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._omitir = 0
        self._nota = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._OMITIR:
            self._omitir += 1
        elif tag == "a" and any("_ftn" in (v or "") for _, v in attrs):
            self._nota = True
        elif tag in self._BLOQUES:
            self._nota = False
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._OMITIR:
            self._omitir = max(0, self._omitir - 1)
        elif tag == "a":
            self._nota = False
        elif tag in self._BLOQUES:
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._omitir and not self._nota:
            self.partes.append(_ESPACIOS.sub(" ", data))


def _html_a_texto(html: str) -> str:
    p = _ExtractorTexto()
    p.feed(html)
    p.close()
    lineas = (_ESPACIOS.sub(" ", ln).strip() for ln in "".join(p.partes).split("\n"))
    return "\n".join(ln for ln in lineas if ln)


def _decodificar(crudo: bytes) -> str:
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError:
        return crudo.decode("cp1252", errors="replace")


def _bajar_pagina(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.read()
    except OSError as e:
        log.warning("No se pudo descargar %s: %s", url, e)
        return None


def _es_pagina_de(url: str, texto: str) -> bool:
    partes = normalizar_sentencia(Path(urlparse(url).path).stem)
    return partes is None or _pagina_corresponde(normalizar_texto(texto), *partes)


def texto_relatoria(url: str, cfg: Config) -> str | None:
    destino = cfg.cache_path() / "relatoria" / Path(urlparse(url).path).name
    en_cache = destino.is_file()
    crudo = destino.read_bytes() if en_cache else _bajar_pagina(url)
    if crudo is None or len(crudo) < MIN_BYTES_PAGINA:
        return None
    texto = _html_a_texto(_decodificar(crudo))
    if not en_cache and _es_pagina_de(url, texto):
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + ".tmp")
        tmp.write_bytes(crudo)
        tmp.replace(destino)
    return texto


def _quitar(rx: re.Pattern, s: str) -> str:
    while True:
        s, n = rx.subn(" ", s)
        if not n:
            return s


def normalizar_texto(s: str, incisos: bool = True) -> str:
    s = _INVISIBLES.sub("", s)
    if incisos:
        s = _quitar(_CORCHETES, _quitar(_PARENTESIS, s))
    s = unicodedata.normalize("NFKD", s.replace("…", " ").lower()).replace("ñ", "ñ")
    return _NO_ALFANUM.sub(" ", _MARCAS.sub("", s)).strip()


@lru_cache(maxsize=8)
def _ngramas_fuente(texto: str, n: int, incisos: bool) -> frozenset[tuple[str, ...]]:
    t = normalizar_texto(texto, incisos).split()
    return frozenset(zip(*(t[i:] for i in range(n))))


def _cobertura_modo(cita: list[str], texto: str, n: int, incisos: bool) -> float:
    n = min(n, len(cita))
    grams = list(zip(*(cita[i:] for i in range(n))))
    fuente = _ngramas_fuente(texto, n, incisos)
    return sum(g in fuente for g in grams) / len(grams)


_ENFASIS = r"(?:subrayad[oa]s?|negrill[oa]s?|subrayas?|resaltad[oa]s?|[eé]nfasis|cursivas?)"
_MARCAS_CITANTE = re.compile(
    r"[(\[]\s*(?:\.{3}|…)\s*[)\]]"
    r"|[(\[]\s*sic\s*[)\]]"
    rf"|[(\[]\s*{_ENFASIS}(?:\s*(?:,|y|e)\s*{_ENFASIS})*\s+fuera\s+(?:de|del)\s+(?:el\s+)?texto(?:\s+original)?\s*[)\]]"
    r"|\[\s*\d{1,3}\s*\]"
    rf"|\(\s*(?:sentencias?\s+)?{RE_SENTENCIA.pattern}\s*\)",
    re.IGNORECASE,
)


def cobertura(cita: str, texto: str, n: int = 6) -> float | None:
    limpia = normalizar_texto(_quitar(_MARCAS_CITANTE, _INVISIBLES.sub("", cita)), False).split()
    if not limpia:
        return None
    return max(_cobertura_modo(limpia, texto, n, incisos) for incisos in (False, True))


def _pagina_corresponde(texto_norm: str, tipo: str, numero: int, anio: int) -> bool:
    patron = rf"\b{tipo.lower()}\s*0*{numero}\s+(?:de\s+)?(?:{anio}|{anio % 100:02d})\b"
    return re.search(patron, texto_norm[:VENTANA_ID]) is not None


def _ponentes(mp: str | None) -> list[str]:
    nombres = [n.strip() for n in (mp or "").split(";")]
    return [n for n in nombres if n and normalizar_texto(n) not in NO_PONENTES]


def _es_femenino(nombre: str) -> bool:
    primero = normalizar_texto(nombre).split()
    return bool(primero) and primero[0] in NOMBRES_FEMENINOS


def _mp_coincide(declarado: str, mp_dataset: str) -> bool:
    d = set(normalizar_texto(declarado).split())
    for nombre in _ponentes(mp_dataset):
        n = set(normalizar_texto(nombre).split())
        if n <= d or d <= n:
            return True
    return False


def verificar_citas(
    citas: list[CitaPropuesta], cfg: Config, dataset: dict[str, dict]
) -> list[CitaVerificada]:
    paginas: dict[str, str | None] = {}

    def pagina(url: str) -> str | None:
        if url not in paginas:
            texto = texto_relatoria(url, cfg)
            paginas[url] = texto
        return paginas[url]

    return [_verificar(c, cfg, dataset, pagina) for c in citas]


def _verificar(c: CitaPropuesta, cfg: Config, dataset: dict[str, dict], pagina) -> CitaVerificada:
    cv = CitaVerificada(
        id=c.id,
        sentencia_original=c.sentencia,
        texto_citado=c.texto_citado,
        reparo_ids=c.reparo_ids,
    )
    partes = normalizar_sentencia(c.sentencia)
    if partes is None:
        cv.motivos.append(f"No se pudo interpretar el identificador de la sentencia «{c.sentencia}».")
        return cv
    tipo, numero, anio = partes
    cv.tipo, cv.numero, cv.anio = tipo, numero, anio
    cv.sentencia_norm = clave_dataset(tipo, numero, anio)
    cv.url = url_relatoria(tipo, numero, anio)

    fila = dataset.get(cv.sentencia_norm)
    if fila is None:
        cv.motivos.append(
            f"La sentencia {cv.sentencia_norm} no figura en el dataset oficial de la Corte Constitucional."
        )
        return cv
    cv.en_dataset = True
    cv.mp_dataset = (fila.get("magistrado_a") or "").strip() or None
    cv.fecha_dataset = (fila.get("fecha_sentencia") or "")[:10] or None

    if cv.fecha_dataset and cv.fecha_dataset[:4] != str(anio):
        cv.motivos.append(
            f"El año citado ({anio}) no coincide con la fecha de la sentencia en el dataset ({cv.fecha_dataset})."
        )
        return cv
    if not _ponentes(cv.mp_dataset):
        if cfg.exigir_mp:
            cv.motivos.append("El dataset no registra el magistrado ponente, que es obligatorio en la referencia.")
            return cv
    elif ";" in cv.mp_dataset or "(" in cv.mp_dataset:
        cv.motivos.append(f"El dataset registra una ponencia compuesta ({cv.mp_dataset}); revísela antes de firmar.")
    declarado = RE_MP_DECLARADO.search(c.sentencia)
    if declarado and cv.mp_dataset and not _mp_coincide(declarado.group(1), cv.mp_dataset):
        cv.motivos.append(
            f"El M.P. indicado ({declarado.group(1)}) no coincide con el del dataset ({cv.mp_dataset})."
        )
        return cv

    if not cfg.verificar_relatoria:
        cv.estado = "alerta"
        cv.motivos.append(
            "No se verificó el texto en la relatoría (verificación desactivada); solo se comprobó que la sentencia existe en el dataset."
        )
        return cv

    texto = pagina(cv.url)
    if texto is None:
        cv.motivos.append(f"No se encontró la página de la relatoría ({cv.url}); no se puede verificar la cita.")
        return cv
    if not _pagina_corresponde(normalizar_texto(texto), tipo, numero, anio):
        cv.motivos.append(f"La página de la relatoría ({cv.url}) no corresponde a la sentencia {cv.sentencia_norm}.")
        return cv
    cv.pagina_ok = True

    cob = cobertura(c.texto_citado, texto, cfg.ngram)
    if cob is None:
        cv.motivos.append("La cita no tiene texto que se pueda verificar.")
        return cv
    cv.cobertura = round(cob, 4)
    if cob >= cfg.cobertura_ok:
        cv.estado = "ok"
    elif cob >= cfg.cobertura_alerta:
        cv.estado = "alerta"
        cv.motivos.append(
            f"Solo el {cob:.0%} del texto citado aparece literalmente en la sentencia {cv.sentencia_norm}; "
            f"se exige al menos el {cfg.cobertura_ok:.0%}. Compárelo con la relatoría."
        )
    else:
        cv.motivos.append(
            f"Solo el {cob:.0%} del texto citado aparece literalmente en la sentencia {cv.sentencia_norm}; "
            "el pasaje no se localizó."
        )
    return cv


def _frase_ponencia(nombres: list[str]) -> str:
    fem = [_es_femenino(n) for n in nombres]
    if len(nombres) == 1:
        return f"de la Magistrada {nombres[0]}" if fem[0] else f"del Magistrado {nombres[0]}"
    lista = ", ".join(nombres[:-1]) + f" y {nombres[-1]}"
    return f"de las Magistradas {lista}" if all(fem) else f"de los Magistrados {lista}"


def formatear_referencia(cv: CitaVerificada) -> str:
    if cv.tipo and cv.numero and cv.anio:
        base = f"Sentencia {cv.tipo}-{cv.numero:03d} de {cv.anio}"
    else:
        base = f"Sentencia {cv.sentencia_original}"
    nombres = _ponentes(cv.mp_dataset)
    return f"{base}, con ponencia {_frase_ponencia(nombres)}" if nombres else base
