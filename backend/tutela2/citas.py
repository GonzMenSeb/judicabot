from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import unicodedata
import urllib.request
from bisect import bisect_right
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

from tutela2 import eventos
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
MARCA_NOTAS = "\ue001"
RUTA_NORMAS = Path(__file__).parent / "assets" / "normas_citables.json"
NGRAMA_NORMA = 4
NGRAMA_CERCANO = 3
UMBRAL_PASAJE_CERCANO = 0.5
MAX_PALABRAS_PASAJE = 150
MIN_TOKENS_ORACION_CERCANA = 5
PREFIJO_REGLA = "Regla de las citas:"

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
_ID_NOTA = re.compile(r"ftn\d+")


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
        self._notas_marcadas = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._OMITIR:
            self._omitir += 1
        elif tag == "a" and any("_ftn" in (v or "") for _, v in attrs):
            self._nota = True
        elif tag in self._BLOQUES:
            self._nota = False
            self.partes.append("\n")
            if tag == "div" and not self._notas_marcadas and any(k == "id" and _ID_NOTA.fullmatch(v or "") for k, v in attrs):
                self._notas_marcadas = True
                self.partes.append(f"{MARCA_NOTAS}\n")

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


class SeccionesRelatoria(NamedTuple):
    mayoria: str
    votos: str
    resto: str
    delimitada: bool = True


_FIN_MAYORIA = re.compile(
    r"^(?:de\s+conformidad\s+con\s+lo\s+dispuesto\s+en\s+[^,]{0,120},\s*)?"
    r"(?:c[oó]piese|notif[ií]quese|comun[ií]quese|publ[ií]quese|c[uú]mplase)\b.{0,200}?"
    r"(?:c[uú]mplase|gaceta|expediente|arch[ií]vese)[^.]{0,80}\.?\s*$",
    re.IGNORECASE,
)
_FIRMA_VOTO = re.compile(
    r"^(?:con\s+)?(?:salvamento|aclaraci[oó]n)\b|\bvoto\s+(?:disidente|particular|concurrente|separado)\b",
    re.IGNORECASE,
)
_FIN_FIRMAS = re.compile(r"^secretari[oa](?:\s+general)?(?:\s*\(e\))?\s*$", re.IGNORECASE)
_TITULO_VOTO = re.compile(
    r"^(?:aclaraci[oó]n|salvamento)(?:\s+(?:y|o)\s+(?:aclaraci[oó]n|salvamento))?(?:\s+parcial)?\s+de\s+voto(?:\s+parcial)?\b"
    r"(?:\s+(?:a|de)\s+la\s+(?:sentencia|providencia|decisi[oó]n)\b.*"
    r"|\s+(?:del|de\s+(?:la|las|los))\s+magistrad[oa]s?\b.*)?\s*$",
    re.IGNORECASE,
)
_COMUNICADO = re.compile(r"^comunicado\b.{0,60}$", re.IGNORECASE)
_AUTO_ANEXO = re.compile(r"^auto\s+\d+\s*/\s*\d{2,4}\s*$", re.IGNORECASE)
_ANEXO = re.compile(
    r"^(?:(?:primer|segundo|tercer|cuarto|quinto)\s+)?anexo(?:\s+(?:n[oº°.]*\s*)?\w{1,4}){0,2}\s*$", re.IGNORECASE
)
MAX_LINEA_FIN_MAYORIA = 400
MAX_LINEA_TITULO_VOTO = 160
MAX_LINEA_COMUNICADO = 80
MAX_LINEA_ANEXO = 30
VENTANA_FIRMAS = 40


def _inicia_votos(linea: str) -> bool:
    return (len(linea) < MAX_LINEA_TITULO_VOTO and _TITULO_VOTO.match(linea) is not None) or (
        len(linea) < MAX_LINEA_COMUNICADO and _COMUNICADO.match(linea) is not None
    )


def _hay_firma_de_voto(lineas: list[str]) -> bool:
    return any(len(ln) < MAX_LINEA_TITULO_VOTO and _FIRMA_VOTO.search(ln) is not None for ln in lineas)


def _termina_votos(linea: str) -> bool:
    return _AUTO_ANEXO.match(linea) is not None or (
        len(linea) < MAX_LINEA_ANEXO and _ANEXO.match(linea) is not None
    )


@lru_cache(maxsize=8)
def separar_secciones(texto: str) -> SeccionesRelatoria:
    lineas = texto.split("\n")
    marca = next((k for k, ln in enumerate(lineas) if ln == MARCA_NOTAS), None)
    cuerpo = lineas if marca is None else lineas[:marca]
    notas = [] if marca is None else lineas[marca + 1 :]
    fin = next((k for k, ln in enumerate(cuerpo) if len(ln) < MAX_LINEA_FIN_MAYORIA and _FIN_MAYORIA.match(ln)), None)
    inicio = None
    base = fin
    if fin is not None:
        firmas = range(fin, min(len(cuerpo), fin + VENTANA_FIRMAS))
        base = next((k for k in firmas if _FIN_FIRMAS.match(cuerpo[k])), fin)
        inicio = next((k for k in range(base + 1, len(cuerpo)) if _inicia_votos(cuerpo[k])), None)
    if inicio is None:
        delimitada = fin is not None and not _hay_firma_de_voto(cuerpo[fin + 1 :])
        return SeccionesRelatoria("\n".join([*cuerpo, *notas]), "", "", delimitada)
    delimitada = not (base > fin and _hay_firma_de_voto(cuerpo[base + 1 : inicio]))
    final = next((k for k in range(inicio + 1, len(cuerpo)) if _termina_votos(cuerpo[k])), len(cuerpo))
    return SeccionesRelatoria(
        "\n".join(cuerpo[:inicio]), "\n".join(cuerpo[inicio:final]), "\n".join([*cuerpo[final:], *notas]), delimitada
    )


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


_ENFASIS = (
    r"(?:subrayad[oa]s?|subrayas?|negrill[oa]s?|negrit[oa]s?|resaltad[oa]s?|resalta|destacad[oa]s?|destaca"
    r"|[eé]nfasis|cursivas?)"
)
_AUTOR_ENFASIS = (
    r"(?:(?:de|del|por)\s+)?(?:(?:el|la)\s+)?(?:despacho|juzgado|sala|suscrit[oa]|tribunal|ponente)"
)
_COLA_ENFASIS = (
    r"(?:(?:por\s+)?fuera\s+(?:de|del)\s+(?:el\s+)?texto(?:\s+original)?|a[ñn]adid[oa]s?|agregad[oa]s?"
    r"|propi[oa]s?|nuestr[oa]s?|intencional(?:es)?|del\s+texto\s+original|en\s+el\s+original"
    rf"|{_AUTOR_ENFASIS})"
)
_REF_SENTENCIA = rf"(?:sentencias?\s+)?{RE_SENTENCIA.pattern}"
_NOMBRE_PONENTE = r"[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+"
_PONENTE = (
    r"(?:M\.?\s?P\.?|magistrad[oa]s?\s+ponentes?)\s*:?\s*(?:Dra?\.?\s+)?"
    rf"(?-i:{_NOMBRE_PONENTE}(?:\s+(?:(?:de|del|la|los|las|y|e)\s+)*{_NOMBRE_PONENTE}){{0,8}})"
)
_OMISION = r"[(\[]\s*(?:\.{3}|…|\.\s\.\s\.)\s*[)\]]"
_NOTA_SENTENCIA = (
    r"[(\[]\s*(?:(?:cfr|ver)\.?\s*:?\s*)?(?:corte\s+constitucional\s*,?\s*)?"
    rf"{_REF_SENTENCIA}(?:\s*(?:,|;|y|e)\s*{_REF_SENTENCIA})*"
    rf"(?:\s*[,;.]\s*{_PONENTE}|\s+{_PONENTE})?\s*[)\]]"
)
_MARCAS_CITANTE = re.compile(
    rf"{_OMISION}"
    r"|[(\[]\s*sic\s*[)\]]"
    r"|[(\[]\s*citas?\s+internas?\s+omitid[oa]s?\s*[)\]]"
    rf"|[(\[]\s*(?:se\s+)?{_ENFASIS}(?:\s*(?:,|y|e)\s*{_ENFASIS})*(?:\s+{_COLA_ENFASIS})?\s*[)\]]"
    r"|\[\s*\d{1,3}\s*\]"
    rf"|{_NOTA_SENTENCIA}",
    re.IGNORECASE,
)
_NOTA_SENTENCIA_RX = re.compile(_NOTA_SENTENCIA, re.IGNORECASE)
_MARCA_NOTA_AL_PIE = re.compile(r"\[\s*\d{1,3}\s*\]")
_OMISION_RX = re.compile(rf"{_OMISION}|…|\.{{3}}")
_CORTE = "\ue000"
_EDICION_LETRA = re.compile(r"\[\s*([^\W\d_])\s*\]")
_CIERRE = {"(": ")", "[": "]"}


def _limpiar_marcas(s: str) -> str:
    return _quitar_marcas(_EDICION_LETRA.sub(r"\1", _INVISIBLES.sub("", s)))


def _limpiar_cita(s: str) -> str:
    return _limpiar_marcas(_OMISION_RX.sub(f" {_CORTE} ", _INVISIBLES.sub("", s)))


def _quitar_marcas(s: str) -> str:
    while True:
        s, n = _MARCAS_CITANTE.subn(" ", s)
        if not n:
            return s


@lru_cache(maxsize=8)
def _ngramas_fuente(texto: str, n: int, incisos: bool) -> frozenset[tuple[str, ...]]:
    grams: set[tuple[str, ...]] = set()
    for base in (_limpiar_marcas(texto), texto):
        t = normalizar_texto(base, incisos).split()
        grams.update(zip(*(t[i:] for i in range(n))))
    return frozenset(grams)


def _cobertura_modo(cita: list[str], texto: str, n: int, incisos: bool) -> float:
    n = min(n, len(cita))
    grams = list(zip(*(cita[i:] for i in range(n))))
    fuente = _ngramas_fuente(texto, n, incisos)
    return sum(g in fuente for g in grams) / len(grams)


def _pares(s: str) -> list[tuple[int, int]]:
    pila: list[tuple[str, int]] = []
    cerrados: list[tuple[int, int]] = []
    for i, c in enumerate(s):
        if c in _CIERRE:
            pila.append((c, i))
        elif c in ")]" and pila and _CIERRE[pila[-1][0]] == c:
            cerrados.append((pila.pop()[1], i + 1))
    return cerrados


def _grupos(s: str) -> list[tuple[int, int]]:
    cerrados = _pares(s)
    externos: list[tuple[int, int]] = []
    fin = -1
    for a, b in sorted(cerrados):
        if a >= fin:
            externos.append((a, b))
            fin = b
    return externos


def _analizar_cita(
    cita: str,
) -> tuple[list[str], list[str], list[tuple[int, int, str]], list[int]]:
    literal: list[str] = []
    plano: list[str] = []
    grupos: list[tuple[int, int, str]] = []
    cortes: list[int] = []
    pos = 0
    for a, b in [*_grupos(cita), (len(cita), len(cita))]:
        for k, trozo in enumerate(cita[pos:a].split(_CORTE)):
            if k:
                cortes.append(len(literal))
            t = normalizar_texto(trozo, False).split()
            literal += t
            plano += t
        g = normalizar_texto(cita[a:b], False).split()
        if g:
            grupos.append((len(literal), len(literal) + len(g), _ESPACIOS.sub(" ", cita[a:b]).strip()))
            literal += g
        pos = b
    return literal, plano, grupos, cortes


CONTEXTO_GRUPO = 4
MAX_CHARS_INCISO_FUENTE = 300


class _IndiceFuente:
    def __init__(self, texto: str) -> None:
        pares = [(a, b) for a, b in _pares(texto) if b - a <= MAX_CHARS_INCISO_FUENTE]
        cortes = sorted({x for par in pares for x in par})
        self.tokens: list[str] = []
        en: dict[int, int] = {}
        pos = 0
        for c in [*cortes, len(texto)]:
            self.tokens += normalizar_texto(texto[pos:c], False).split()
            en[c] = len(self.tokens)
            pos = c
        self.por_inicio: dict[int, int] = {}
        self.por_fin: dict[int, int] = {}
        for a, b in pares:
            i, j = en[a], en[b]
            if j > i:
                self.por_inicio[i] = max(j, self.por_inicio.get(i, j))
                self.por_fin[j] = min(i, self.por_fin.get(j, i))
        self.posiciones: dict[str, list[int]] = {}
        for k, t in enumerate(self.tokens):
            self.posiciones.setdefault(t, []).append(k)


@lru_cache(maxsize=8)
def _indices_fuente(texto: str) -> tuple[_IndiceFuente, ...]:
    return (_IndiceFuente(_limpiar_marcas(texto)), _IndiceFuente(texto))


def _contexto_coincide(ctx: list[str], idx: _IndiceFuente, pos: int, paso: int, saltos: int | None = None) -> bool:
    if not ctx:
        return True
    if saltos is None:
        saltos = len(ctx)
    tokens = idx.tokens
    k = pos if paso > 0 else pos - 1
    if 0 <= k < len(tokens) and tokens[k] == ctx[0]:
        if _contexto_coincide(ctx[1:], idx, pos + paso, paso, saltos):
            return True
    if saltos <= 0:
        return False
    if paso > 0:
        destino = idx.por_inicio.get(pos)
    else:
        destino = idx.por_fin.get(pos)
    return destino is not None and _contexto_coincide(ctx, idx, destino, paso, saltos - 1)


def _grupo_en_indice(g: list[str], izq: list[str], der: list[str], idx: _IndiceFuente) -> bool:
    for p in idx.posiciones.get(g[0], ()):
        q = p + len(g)
        if idx.tokens[p:q] != g:
            continue
        if _contexto_coincide(izq[::-1], idx, p, -1) and _contexto_coincide(der, idx, q, 1):
            return True
    return False


def _grupo_en_fuente(
    literal: list[str], grupo: tuple[int, int, str], cortes: list[int], texto: str
) -> bool:
    i, j, _ = grupo
    desde = max([0, i - CONTEXTO_GRUPO, *(c for c in cortes if c <= i)])
    hasta = min([len(literal), j + CONTEXTO_GRUPO, *(c for c in cortes if c >= j)])
    izqs = {False: literal[max(0, i - CONTEXTO_GRUPO) : i], True: literal[desde:i]}
    ders = {False: literal[j : j + CONTEXTO_GRUPO], True: literal[j:hasta]}
    vistos = set()
    for ti in (False, True):
        for td in (False, True):
            izq, der = izqs[ti], ders[td]
            clave = (tuple(izq), tuple(der))
            if clave in vistos or (not izq and not der):
                continue
            vistos.add(clave)
            recortado = (ti and izq != izqs[False]) or (td and der != ders[False])
            if recortado and len(izq) + len(der) < CONTEXTO_GRUPO:
                continue
            if any(_grupo_en_indice(literal[i:j], izq, der, idx) for idx in _indices_fuente(texto)):
                return True
    return False


def _grupo_fallido(cita: str, texto: str) -> str | None:
    literal, _, grupos, cortes = _analizar_cita(_limpiar_cita(cita))
    for g in grupos:
        if not _grupo_en_fuente(literal, g, cortes, texto):
            return g[2]
    return None


@lru_cache(maxsize=8)
def _fuente_plana(texto: str) -> str:
    return f" {normalizar_texto(texto, False)} "


def notas_ausentes(cita: str, texto: str, propia: str | None = None) -> list[str]:
    fuente = _fuente_plana(texto)
    ausentes: list[str] = []
    for m in _NOTA_SENTENCIA_RX.finditer(_MARCA_NOTA_AL_PIE.sub("", _INVISIBLES.sub("", cita))):
        nota = _ESPACIOS.sub(" ", m.group()).strip()
        if propia and sentencias_en_texto(nota) == {propia}:
            continue
        if f" {normalizar_texto(nota, False)} " not in fuente and nota not in ausentes:
            ausentes.append(nota)
    return ausentes


def motivo_parentesis(cita: str, texto: str) -> str | None:
    g = _grupo_fallido(cita, texto)
    if g is None:
        return None
    return f"El paréntesis «{g}» no aparece en ese punto de la fuente."


POLARIDAD = frozenset(
    "no nunca jamas tampoco ni sin solo solamente unicamente salvo excepto siempre nada nadie "
    "todo toda todos todas ningun ninguna ninguno ningunos ningunas".split()
)
TOPE_AGREGADOS = 0.79
MARGEN_VENTANA = 3
HOLGURA_DIAGONAL = 150
ANCHO_BIN = 16
MAX_POS_ANCLA = 400
MAX_VENTANAS = 8


class _Linea:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.posiciones: dict[str, list[int]] = {}
        for k, t in enumerate(tokens):
            self.posiciones.setdefault(t, []).append(k)


@lru_cache(maxsize=16)
def _linea_fuente(texto: str, incisos: bool, limpia: bool) -> _Linea:
    base = _limpiar_marcas(texto) if limpia else texto
    return _Linea(normalizar_texto(base, incisos).split())


def _a_una_edicion(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    corto, largo = sorted((a, b), key=len)
    return any(largo[:k] + largo[k + 1 :] == corto for k in range(len(largo)))


PREFIJOS_NEGACION = ("i", "in", "il", "im", "ir", "des", "no")
MAX_HUECO_POLARIDAD = 10
MAX_HUECO_CON_DIGITOS = 6
ENCABEZADO = frozenset("pagina exp expediente folio sentencia decreto ley".split())
CONECTORES_NUMERO = frozenset("de del y e".split())


def _tiene_digito(t: str) -> bool:
    return any(c.isdigit() for c in t)


def _abreviaturas(tokens: list[str]) -> set[int]:
    n = len(tokens)
    res: set[int] = set()
    for k, t in enumerate(tokens):
        if t != "no":
            continue
        j = k + 1
        if j < n and len(tokens[j]) == 1 and tokens[j].isalpha() and j + 1 < n and _tiene_digito(tokens[j + 1]):
            j += 1
        if j < n and _tiene_digito(tokens[j]):
            despues = tokens[j + 1] if j + 1 < n else None
            if despues is None or despues in CONECTORES_NUMERO or _tiene_digito(despues):
                res.add(k)
    return res


def _polares(tokens: list[str]) -> list[str]:
    abrev = _abreviaturas(tokens)
    return [t for k, t in enumerate(tokens) if t in POLARIDAD and k not in abrev]


def _difieren_en_prefijo_negativo(a: str, b: str) -> bool:
    corto, largo = sorted((a, b), key=len)
    return any(largo == p + corto for p in PREFIJOS_NEGACION)


def _casi_igual(t: str, s: str) -> bool:
    if t == s:
        return True
    if _difieren_en_prefijo_negativo(t, s):
        return False
    if (t.isdigit() and s in (t + "o", t + "a")) or (s.isdigit() and t in (s + "o", s + "a")):
        return True
    if len(t) < 4 or len(s) < 4 or t in POLARIDAD or s in POLARIDAD:
        return False
    return _a_una_edicion(t, s)


def _sin_explicar(cita: list[str], fuente: list[str]) -> list[str]:
    if "".join(cita) == "".join(fuente):
        return []
    return [t for t in cita if not any(_casi_igual(t, s) for s in fuente)]


def _ventanas(seg: list[str], linea: _Linea) -> list[tuple[int, int]]:
    diagonales: list[int] = []
    votos: Counter[int] = Counter()
    peso: Counter[int] = Counter()
    for i, t in enumerate(seg):
        pos = linea.posiciones.get(t, ())
        if len(pos) > MAX_POS_ANCLA:
            continue
        for p in pos:
            diagonales.append(p - i)
            votos[(p - i) // ANCHO_BIN] += 1
            peso[(p - i) // ANCHO_BIN] += 1 / len(pos)
    ventanas: list[tuple[int, int]] = []
    elegidos: list[int] = []
    for b in sorted(votos, key=lambda b: (-peso[b], b)):
        if votos[b] < 2 or len(ventanas) == MAX_VENTANAS:
            break
        if any(abs(b - e) <= 1 for e in elegidos):
            continue
        elegidos.append(b)
        centro = b * ANCHO_BIN + ANCHO_BIN // 2
        cerca = [d for d in diagonales if abs(d - centro) <= HOLGURA_DIAGONAL]
        lo = max(0, min(cerca) - MARGEN_VENTANA)
        hi = min(len(linea.tokens), max(cerca) + len(seg) + MARGEN_VENTANA)
        ventanas.append((lo, hi))
    return ventanas


def _hueco_omitido(ops: list, k: int, fuente: list[str]) -> bool:
    j1, j2 = ops[k][3:]
    if j2 - j1 <= 2:
        return True
    hueco = fuente[j1:j2]
    cabecera = any(t in ENCABEZADO for t in hueco)
    if any(_tiene_digito(t) for t in hueco):
        if cabecera or j2 - j1 > MAX_HUECO_CON_DIGITOS or not _polares(hueco):
            return False
    elif j2 - j1 > MAX_HUECO_CON_DIGITOS and (cabecera or not _polares(hueco)):
        return False
    return j2 - j1 <= MAX_HUECO_POLARIDAD and ops[k - 1][0] == "equal" and ops[k + 1][0] == "equal"


def _corridas_segmento(seg: list[str], fuente: list[str]) -> tuple[list[list[str]], list[str]]:
    corridas: list[list[str]] = []
    omitidas: list[str] = []
    ops = SequenceMatcher(None, seg, fuente, autojunk=False).get_opcodes()
    abrev_seg = _abreviaturas(seg)
    abrev_fuente = _abreviaturas(fuente)
    iguales = [k for k, op in enumerate(ops) if op[0] == "equal"]
    interior = range(iguales[0] + 1, iguales[-1]) if iguales else ()
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        propia = [seg[i] for i in range(i1, i2) if i not in abrev_seg]
        if tag == "delete":
            if propia:
                corridas.append(propia)
        elif tag == "replace":
            extra = _sin_explicar(propia, fuente[j1:j2])
            if extra:
                corridas.append(extra)
        if tag in ("insert", "replace") and k in interior and _hueco_omitido(ops, k, fuente):
            propios = set(seg[i1:i2])
            omitidas += [
                fuente[j] for j in range(j1, j2) if fuente[j] in POLARIDAD and j not in abrev_fuente and fuente[j] not in propios
            ]
    return corridas, omitidas


Agregados = tuple[list[list[str]], list[str]]


def _clave_agregados(res: Agregados) -> tuple[int, int]:
    corridas, omitidas = res
    return (
        sum(map(len, corridas)) + len(omitidas),
        sum(t in POLARIDAD for c in corridas for t in c) + len(omitidas),
    )


def _agregados_en_linea(cita: list[str], cortes: list[int], linea: _Linea) -> Agregados:
    corridas: list[list[str]] = []
    omitidas: list[str] = []
    ini = 0
    for fin in [*sorted(cortes), len(cita)]:
        seg, ini = cita[ini:fin], max(ini, fin)
        if len(seg) < 2:
            continue
        mejor: Agregados | None = None
        for lo, hi in _ventanas(seg, linea):
            opcion = _corridas_segmento(seg, linea.tokens[lo:hi])
            if mejor is None or _clave_agregados(opcion) < _clave_agregados(mejor):
                mejor = opcion
            if not any(mejor):
                break
        if mejor:
            corridas += mejor[0]
            omitidas += mejor[1]
    return corridas, omitidas


def _corridas_agregadas(
    literal: list[str], plano: list[str], grupos: list[tuple[int, int, str]], cortes: list[int], texto: str
) -> Agregados:
    cortes_plano = [c - sum(j - i for i, j, _ in grupos if j <= c) for c in cortes]
    intentos = (
        (literal, cortes, False, True),
        (literal, cortes, False, False),
        (plano, cortes_plano, True, True),
        (plano, cortes_plano, True, False),
    )
    mejor: tuple[tuple[int, int], Agregados] | None = None
    for tokens, cs, incisos, limpia in intentos:
        res = _agregados_en_linea(tokens, cs, _linea_fuente(texto, incisos, limpia))
        if not any(res):
            return [], []
        clave = _clave_agregados(res)
        if mejor is None or clave < mejor[0]:
            mejor = (clave, res)
    return mejor[1]


def _tiene_polaridad(res: Agregados) -> bool:
    corridas, omitidas = res
    return bool(omitidas) or any(t in POLARIDAD for c in corridas for t in c)


def motivo_agregados(cita: str, texto: str) -> str | None:
    literal, plano, grupos, cortes = _analizar_cita(_limpiar_cita(cita))
    if not literal or _grupo_fallido(cita, texto) is not None:
        return None
    corridas, omitidas = _corridas_agregadas(literal, plano, grupos, cortes, texto)
    motivos = []
    if corridas:
        palabras = ", ".join(f"«{' '.join(c)}»" for c in corridas)
        motivos.append(f"La cita agrega {palabras}, que no está en la fuente.")
    if omitidas:
        palabras = ", ".join(f"«{t}»" for t in dict.fromkeys(omitidas))
        motivos.append(f"La cita omite {palabras}, que sí está en la fuente.")
    return " ".join(motivos) or None


def _puntaje_ngramas(literal: list[str], plano: list[str], texto: str, n: int) -> float:
    puntajes = [_cobertura_modo(literal, texto, n, False)]
    if plano:
        puntajes.append(_cobertura_modo(plano, texto, n, True))
    return max(puntajes)


def puntaje_ngramas(cita: str, texto: str, n: int = 6) -> float:
    literal, plano, _, _ = _analizar_cita(_limpiar_cita(cita))
    return _puntaje_ngramas(literal, plano, texto, n) if literal else 0.0


def cobertura(cita: str, texto: str, n: int = 6) -> float | None:
    literal, plano, grupos, cortes = _analizar_cita(_limpiar_cita(cita))
    if not literal:
        return None
    if _grupo_fallido(cita, texto) is not None:
        return 0.0
    puntaje = _puntaje_ngramas(literal, plano, texto, n)
    if puntaje == 0.0:
        return puntaje
    res = _corridas_agregadas(literal, plano, grupos, cortes, texto)
    if _tiene_polaridad(res):
        return 0.0
    return min(puntaje, TOPE_AGREGADOS) if res[0] else puntaje


def contar_palabras(cita: str) -> int:
    return len(_analizar_cita(_limpiar_cita(cita))[0])


def _tramos(literal: list[str], cortes: list[int]) -> list[list[str]]:
    return [literal[a:b] for a, b in zip([0, *cortes], [*cortes, len(literal)])]


def _tramo_mas_corto(cita: str) -> int | None:
    literal, _, _, cortes = _analizar_cita(_limpiar_cita(cita))
    largos = [len(t) for t in _tramos(literal, cortes) if t]
    return min(largos) if len(largos) > 1 else None


class NormaCitable(NamedTuple):
    norma: str
    articulo: str
    texto: str
    ngramas: frozenset[tuple[str, ...]]


def _ngramas(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    return list(zip(*(tokens[i:] for i in range(n))))


@lru_cache(maxsize=1)
def normas_citables() -> tuple[NormaCitable, ...]:
    try:
        datos = json.loads(RUTA_NORMAS.read_text(encoding="utf-8"))
        return tuple(
            NormaCitable(
                e["norma"],
                e["articulo"],
                e["texto"],
                frozenset(_ngramas(normalizar_texto(e["texto"], False).split(), NGRAMA_NORMA)),
            )
            for e in datos
        )
    except (OSError, ValueError, TypeError, KeyError) as e:
        log.warning("No se pudo cargar el corpus de normas citables %s: %s", RUTA_NORMAS, e)
        return ()


def norma_transcrita(cita: str, umbral: float) -> tuple[str, str] | None:
    literal, _, _, cortes = _analizar_cita(_limpiar_cita(cita))
    grams = [g for tramo in _tramos(literal, cortes) for g in _ngramas(tramo, NGRAMA_NORMA)]
    if not grams:
        return None
    mejor: tuple[float, NormaCitable] | None = None
    for norma in normas_citables():
        puntaje = sum(g in norma.ngramas for g in grams) / len(grams)
        if mejor is None or puntaje > mejor[0]:
            mejor = (puntaje, norma)
    if mejor is None or mejor[0] < umbral:
        return None
    return mejor[1].norma, mejor[1].articulo


_CIERRES = "\"”»')]"
_APERTURAS = "\"“«'([¿¡"
_ABREVIATURAS = frozenset(
    "art arts no nos núm num sent dr dra cfr ver pág págs pag inc ss vs sr sra ed vol ibíd ibid op cit ord par parág cap fol fls".split()
)


class _FuenteCercana(NamedTuple):
    palabras: tuple[str, ...]
    tokens: tuple[str, ...]
    palabra_de_token: tuple[int, ...]
    oraciones: tuple[tuple[int, int, int], ...]


def _termina_oracion(palabra: str, siguiente: str) -> bool:
    nucleo = palabra.rstrip(_CIERRES)
    if not nucleo or nucleo[-1] not in ".?!":
        return False
    if nucleo[-1] == ".":
        raiz = nucleo.rstrip(".")
        interior = "." in raiz and not raiz.replace(".", "").isdigit()
        if len(raiz) <= 1 or interior or raiz.lower() in _ABREVIATURAS or (raiz.isdigit() and len(raiz) <= 2):
            return False
    inicial = siguiente.lstrip(_APERTURAS)[:1]
    return inicial.isupper() or inicial.isdigit()


@lru_cache(maxsize=8)
def _fuente_cercana(texto: str) -> _FuenteCercana:
    palabras: list[str] = []
    tokens: list[str] = []
    palabra_de_token: list[int] = []
    oraciones: list[tuple[int, int, int]] = []
    for n, linea in enumerate(texto.split("\n")):
        ws = linea.split()
        desde = len(palabras)
        for k, w in enumerate(ws):
            palabras.append(w)
            ts = normalizar_texto(w, False).split()
            tokens += ts
            palabra_de_token += [len(palabras) - 1] * len(ts)
            if k + 1 == len(ws) or _termina_oracion(w, ws[k + 1]):
                oraciones.append((desde, len(palabras), n))
                desde = len(palabras)
    return _FuenteCercana(tuple(palabras), tuple(tokens), tuple(palabra_de_token), tuple(oraciones))


def _ventana_mas_parecida(literal: list[str], tokens: tuple[str, ...]) -> tuple[float, list[int]]:
    grams = _ngramas(literal, NGRAMA_CERCANO)
    ids = {g: i for i, g in enumerate(dict.fromkeys(grams))}
    coincide = [ids.get(g, -1) for g in _ngramas(list(tokens), NGRAMA_CERCANO)]
    ancho = len(grams)
    presentes: Counter[int] = Counter()
    mejor, pos = 0, 0
    for k, x in enumerate(coincide):
        if x >= 0:
            presentes[x] += 1
        saliente = coincide[k - ancho] if k >= ancho else -1
        if saliente >= 0:
            presentes[saliente] -= 1
            if not presentes[saliente]:
                del presentes[saliente]
        if len(presentes) > mejor:
            mejor, pos = len(presentes), max(0, k - ancho + 1)
    cubiertos = sorted(
        {t for k in range(pos, min(pos + ancho, len(coincide))) if coincide[k] >= 0 for t in range(k, k + NGRAMA_CERCANO)}
    )
    return mejor / len(ids), cubiertos


def _vecina(oraciones: tuple[tuple[int, int, int], ...], a: int, b: int) -> tuple[int, int] | None:
    sig = b + 1 if b + 1 < len(oraciones) else None
    ant = a - 1 if a > 0 else None
    if sig is not None and oraciones[sig][2] == oraciones[b][2]:
        return a, sig
    if ant is not None and oraciones[ant][2] == oraciones[a][2]:
        return ant, b
    if sig is not None:
        return a, sig
    if ant is not None:
        return ant, b
    return None


def pasaje_mas_cercano(cita: str, texto: str, min_palabras: int = 0) -> str | None:
    literal = _analizar_cita(_limpiar_cita(cita))[0]
    fuente = _fuente_cercana(texto)
    if len(literal) < NGRAMA_CERCANO or len(fuente.tokens) < NGRAMA_CERCANO:
        return None
    parecido, cubiertos = _ventana_mas_parecida(literal, fuente.tokens)
    if parecido < UMBRAL_PASAJE_CERCANO:
        return None
    oraciones = fuente.oraciones
    inicios = [o[0] for o in oraciones]
    cubiertas = Counter(bisect_right(inicios, fuente.palabra_de_token[t]) - 1 for t in cubiertos)
    a, b = min(cubiertas), max(cubiertas)
    while a < b and cubiertas[a] < MIN_TOKENS_ORACION_CERCANA:
        a += 1
    while b > a and cubiertas[b] < MIN_TOKENS_ORACION_CERCANA:
        b -= 1

    def pasaje(a: int, b: int) -> str:
        return " ".join(fuente.palabras[oraciones[a][0] : oraciones[b][1]])

    while a < b and contar_palabras(pasaje(a, b)) > MAX_PALABRAS_PASAJE:
        if cubiertas[a] < cubiertas[b]:
            a += 1
        else:
            b -= 1
    while contar_palabras(pasaje(a, b)) < min_palabras:
        vecina = _vecina(oraciones, a, b)
        if vecina is None:
            return None
        a, b = vecina
    final = pasaje(a, b)
    return final if contar_palabras(final) <= 2 * MAX_PALABRAS_PASAJE else None


def regla_de_citas(cfg: Config) -> str:
    minimo = f", con un mínimo de {cfg.min_palabras_cita} palabras" if cfg.min_palabras_cita > 0 else ""
    return (
        f"{PREFIJO_REGLA} cada cita es un pasaje literal y exacto de la ratio decidendi de la mayoría "
        f"de la sentencia{minimo} (una a tres frases completas); no se admite texto de la Constitución ni del "
        "Decreto 2591 de 1991, ni pasajes de salvamentos o aclaraciones de voto. No acorte una cita para que "
        "pase la verificación: reemplácela por otro pasaje que cumpla la regla."
    )


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

    eventos.emitir(
        "verificacion",
        "lee",
        f"Verificación de {len(citas)} citas contra el dataset de la Corte Constitucional ({len(dataset)} sentencias).",
        {"citas": len(citas), "dataset": len(dataset), "relatoria": cfg.verificar_relatoria},
    )
    verificadas = []
    for c in citas:
        cv = _verificar(c, cfg, dataset, pagina)
        verificadas.append(cv)
        cobertura_txt = f"cobertura {cv.cobertura:.0%}" if cv.cobertura is not None else "sin cobertura medida"
        motivo = f" {cv.motivos[0]}" if cv.motivos and cv.estado != "ok" else ""
        eventos.emitir(
            "verificacion",
            "verifica",
            f"Cita {cv.id} ({cv.sentencia_norm or cv.sentencia_original}): {_ETIQUETA_ESTADO[cv.estado]}, {cobertura_txt}.{motivo}",
            {
                "id": cv.id,
                "sentencia": cv.sentencia_norm or cv.sentencia_original,
                "estado": cv.estado,
                "cobertura": cv.cobertura,
                "en_dataset": cv.en_dataset,
                "motivos": cv.motivos,
            },
        )
    return verificadas


_ETIQUETA_ESTADO = {"ok": "verificada", "alerta": "para revisar", "rechazada": "rechazada"}


def _verificar(c: CitaPropuesta, cfg: Config, dataset: dict[str, dict], pagina) -> CitaVerificada:
    cv = _aplicar_reglas_de_texto(_contrastar(c, cfg, dataset, pagina), cfg)
    if cv.estado != "ok" and cv.pagina_ok and _necesita_pasaje(cv, cfg):
        _agregar_pasaje_cercano(cv, cfg, pagina(cv.url))
    return cv


def _necesita_pasaje(cv: CitaVerificada, cfg: Config) -> bool:
    return cv.cobertura is None or cv.cobertura < cfg.cobertura_ok or cv.n_palabras < cfg.min_palabras_cita


def _pasaje_verificable(pasaje: str, texto: str, cfg: Config, sentencia: str | None) -> bool:
    cob = cobertura(pasaje, texto, cfg.ngram)
    return (
        cob is not None
        and cob >= cfg.cobertura_ok
        and contar_palabras(pasaje) >= cfg.min_palabras_cita
        and not notas_ausentes(pasaje, texto, sentencia)
        and norma_transcrita(pasaje, cfg.cobertura_ok) is None
    )


def _agregar_pasaje_cercano(cv: CitaVerificada, cfg: Config, texto: str) -> None:
    secciones = separar_secciones(texto)
    if not secciones.delimitada:
        return
    pasaje = pasaje_mas_cercano(cv.texto_citado, secciones.mayoria, cfg.min_palabras_cita)
    if pasaje is None or not _pasaje_verificable(pasaje, texto, cfg, cv.sentencia_norm):
        return
    minimo = f" y con al menos {cfg.min_palabras_cita} palabras" if cfg.min_palabras_cita > 0 else ""
    motivo = (
        f"El pasaje más cercano en la sentencia {cv.sentencia_norm} dice textualmente: «{pasaje}». "
        f"Si lo usa, cópielo sin ningún cambio{minimo}."
    )
    cv.pasaje_cercano = pasaje
    antes_de_la_regla = len(cv.motivos) - 1 if cv.motivos and cv.motivos[-1].startswith(PREFIJO_REGLA) else len(cv.motivos)
    cv.motivos.insert(antes_de_la_regla, motivo)


def _plural(n: int, singular: str) -> str:
    return f"{n} {singular}" if n == 1 else f"{n} {singular}s"


def _aplicar_reglas_de_texto(cv: CitaVerificada, cfg: Config) -> CitaVerificada:
    motivos = []
    if cv.n_palabras < cfg.min_palabras_cita:
        motivos.append(
            f"La cita tiene {_plural(cv.n_palabras, 'palabra')} y el mínimo exigido es de {cfg.min_palabras_cita}."
        )
    minimo_tramo = cfg.min_palabras_cita // 2
    tramo = _tramo_mas_corto(cv.texto_citado)
    if tramo is not None and tramo < minimo_tramo:
        motivos.append(
            f"Un fragmento de la cita separado por omisiones «(...)» tiene {_plural(tramo, 'palabra')}; cada "
            f"fragmento debe tener al menos {minimo_tramo} (la mitad del mínimo de {cfg.min_palabras_cita})."
        )
    norma = norma_transcrita(cv.texto_citado, cfg.cobertura_ok)
    if norma:
        motivos.append(
            f"El texto citado reproduce {norma[0]}, artículo {norma[1]}: no se admite texto normativo como cita de jurisprudencia."
        )
    if motivos:
        cv.estado = "rechazada"
        cv.motivos.extend(motivos)
    if cv.estado == "rechazada" and (motivos or cv.pagina_ok):
        cv.motivos.append(regla_de_citas(cfg))
    return cv


def _ubicar_en_seccion(cv: CitaVerificada, cita: str, texto: str, cfg: Config) -> None:
    secciones = separar_secciones(texto)
    if not secciones.delimitada:
        cv.seccion = "desconocida"
        cv.estado = "alerta"
        cv.motivos.append(
            f"No se pudo delimitar la decisión de la mayoría de la sentencia {cv.sentencia_norm} en la relatoría "
            "(no se reconoce su cierre o la página trae votos separados con un formato no reconocido); verifique "
            "que el pasaje no sea de un salvamento o una aclaración de voto."
        )
        return
    if not secciones.votos:
        cv.seccion = "mayoria"
        return

    def puntaje(region: str) -> float:
        return puntaje_ngramas(cita, region, cfg.ngram) if region else 0.0

    en_mayoria = puntaje(secciones.mayoria)
    if en_mayoria >= cfg.cobertura_ok:
        cv.seccion = "mayoria"
        return
    en_votos = puntaje(secciones.votos)
    if en_votos >= cfg.cobertura_ok:
        cv.seccion = "salvamento"
        cv.estado = "rechazada"
        cv.motivos.append(
            f"El pasaje solo aparece en un voto separado (salvamento o aclaración de voto) de la sentencia "
            f"{cv.sentencia_norm}, no en la decisión de la mayoría; no puede presentarse como posición de la Corte."
        )
        return
    en_resto = puntaje(secciones.resto)
    if en_resto >= cfg.cobertura_ok or cv.estado == "ok":
        cv.seccion = "desconocida"
        cv.estado = "alerta"
        cv.motivos.append(
            f"El pasaje no se puede atribuir a la decisión de la mayoría de la sentencia {cv.sentencia_norm}: "
            "aparece solo en notas al pie o anexos, o repartido entre varias secciones; verifíquelo en la relatoría."
        )
        return
    cv.seccion = "mayoria" if en_mayoria >= max(en_votos, en_resto) else "desconocida"


def _contrastar(c: CitaPropuesta, cfg: Config, dataset: dict[str, dict], pagina) -> CitaVerificada:
    cv = CitaVerificada(
        id=c.id,
        sentencia_original=c.sentencia,
        texto_citado=c.texto_citado,
        reparo_ids=c.reparo_ids,
        n_palabras=contar_palabras(c.texto_citado),
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
    notas = notas_ausentes(c.texto_citado, texto, cv.sentencia_norm) if cob >= cfg.cobertura_alerta else []
    if cob >= cfg.cobertura_ok and not notas:
        cv.estado = "ok"
    elif cob >= cfg.cobertura_alerta:
        cv.estado = "alerta"
        if cob < cfg.cobertura_ok:
            cv.motivos.append(
                f"Solo el {cob:.0%} del texto citado aparece literalmente en la sentencia {cv.sentencia_norm}; "
                f"se exige al menos el {cfg.cobertura_ok:.0%}. Compárelo con la relatoría."
            )
            agregados = motivo_agregados(c.texto_citado, texto)
            if agregados:
                cv.motivos.append(agregados)
        cv.motivos.extend(f"La nota «{n}» no aparece en la fuente; verifíquela." for n in notas)
    else:
        cv.motivos.append(
            f"Solo el {cob:.0%} del texto citado aparece literalmente en la sentencia {cv.sentencia_norm}; "
            "el pasaje no se localizó."
        )
        detalle = None
        if cob == 0.0:
            detalle = motivo_parentesis(c.texto_citado, texto)
            if detalle is None and puntaje_ngramas(c.texto_citado, texto, cfg.ngram) >= cfg.cobertura_alerta:
                detalle = motivo_agregados(c.texto_citado, texto)
        if detalle:
            cv.motivos.append(detalle)
    if cv.estado != "rechazada":
        _ubicar_en_seccion(cv, c.texto_citado, texto, cfg)
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
