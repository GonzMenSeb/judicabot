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


def cobertura(cita: str, texto: str, n: int = 6) -> float | None:
    literal, plano, _, _ = _analizar_cita(_limpiar_cita(cita))
    if not literal:
        return None
    if _grupo_fallido(cita, texto) is not None:
        return 0.0
    puntajes = [_cobertura_modo(literal, texto, n, False)]
    if plano:
        puntajes.append(_cobertura_modo(plano, texto, n, True))
    return max(puntajes)


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
        cv.motivos.extend(f"La nota «{n}» no aparece en la fuente; verifíquela." for n in notas)
    else:
        cv.motivos.append(
            f"Solo el {cob:.0%} del texto citado aparece literalmente en la sentencia {cv.sentencia_norm}; "
            "el pasaje no se localizó."
        )
        detalle = motivo_parentesis(c.texto_citado, texto) if cob == 0.0 else None
        if detalle:
            cv.motivos.append(detalle)
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
