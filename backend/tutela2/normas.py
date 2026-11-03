from __future__ import annotations

import re
from dataclasses import dataclass

_TIPO = (
    r"(?:Decreto(?:[- ]Ley|\s+(?:Legislativo|Ley|Estatutario|Reglamentario|Único))?"
    r"|Ley(?:\s+(?:Estatutaria|Orgánica))?|Acuerdo|Resolución|Circular)"
)
_LEY = re.compile(
    rf"(?P<tipo>{_TIPO})\s+(?:(?:No\.?|N\.º|N°|número)\s*)?(?P<num>[A-Z]{{0,8}}\d+(?:[-.]\d+)*)\s*(?:de|del|/)\s*(?:\d{{1,2}}\s+de\s+[a-záéíóúñ]+\s+de\s+)?(?P<anio>\d{{4}})",
    re.I,
)
_CODIGOS = {
    "código general del proceso": "Código General del Proceso",
    "código de procedimiento administrativo y de lo contencioso administrativo": "Código de Procedimiento Administrativo y de lo Contencioso Administrativo",
    "código de procedimiento civil": "Código de Procedimiento Civil",
    "código de procedimiento penal": "Código de Procedimiento Penal",
    "código penal": "Código Penal",
    "código civil": "Código Civil",
    "código de comercio": "Código de Comercio",
    "código sustantivo del trabajo": "Código Sustantivo del Trabajo",
    "código disciplinario único": "Código Disciplinario Único",
    "código de la infancia y la adolescencia": "Código de la Infancia y la Adolescencia",
    "código nacional de policía y convivencia": "Código Nacional de Policía y Convivencia",
    "constitución política de colombia": "Constitución Política",
    "constitución política": "Constitución Política",
    "constitución nacional": "Constitución Política",
    "carta política": "Constitución Política",
    "c.p.": "Constitución Política",
    "c.n.": "Constitución Política",
    "constitución": "Constitución Política",
    "cgp": "Código General del Proceso",
    "cpaca": "Código de Procedimiento Administrativo y de lo Contencioso Administrativo",
}
_ALTERNATIVAS = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in sorted(_CODIGOS, key=len, reverse=True))
_CODIGO = re.compile(rf"(?<!\w)(?P<cod>{_ALTERNATIVAS})(?!\w)", re.I)
_NORMA = rf"(?:{_LEY.pattern}|(?<!\w)(?:{_ALTERNATIVAS})(?!\w))"
_NUM = r"\d+(?:\.\d+)*(?:-?(?-i:[A-Z])(?![A-Za-z0-9]))?[º°]?"
_ARTS = rf"{_NUM}(?:\s*(?:,|y|e|al|a|hasta\s+el)\s*{_NUM})*"
_SUPERIOR = r"(?:superior(?:es)?|constitucional(?:es)?|C\.\s?P\.?|C\.\s?N\.?)(?!\w)"
_CORTE_SUPERIOR = re.compile(r"\b(?:superior(?:es)?|constitucional(?:es)?)\b|(?<!\w)C\.\s?[PN]\b", re.I)
_CONSTITUCION = "Constitución Política"
_ARTICULO_PRIMERO = re.compile(
    rf"\bart(?:[ií]culos?|s?\.)\s*(?P<arts>{_ARTS})\s*,?\s*"
    rf"(?:de\s+la|de\s+el|del|de\s+los|de\s+las|de)\s+(?P<norma>{_NORMA})",
    re.I,
)
_ARTICULO_SUELTO = re.compile(
    rf"\bart(?:[ií]culos?|s?\.)\s*(?P<arts>{_ARTS})",
    re.I,
)
_ARTICULO_SUPERIOR = re.compile(
    rf"\bart(?:[ií]culos?|s?\.)\s*(?P<arts>{_ARTS})\s*,?\s*{_SUPERIOR}",
    re.I,
)
_VENTANA = 80
_CONTEXTO = 70


@dataclass(frozen=True)
class CitaNorma:
    texto: str
    norma: str
    articulo: str | None
    contexto: str


def _canon_norma(fragmento: str) -> str:
    m = _LEY.fullmatch(fragmento.strip())
    if m:
        tipo = re.sub(r"[\s-]+", " ", m["tipo"]).strip().title()
        if tipo.startswith("Ley "):
            tipo = "Ley"
        return f"{tipo} {m['num']} de {m['anio']}"
    return _CODIGOS[re.sub(r"\s+", " ", fragmento.strip()).lower()]


def _articulos(arts: str) -> list[str]:
    salida: list[str] = []
    rango = False
    for m in re.finditer(rf"({_NUM})|\b(?:al|a|hasta\s+el)\b", arts, re.I):
        if m[1] is None:
            rango = True
            continue
        art = m[1].rstrip(".")
        if rango and salida and salida[-1].isdigit() and art.isdigit() and 0 < int(art) - int(salida[-1]) <= 100:
            salida.extend(str(i) for i in range(int(salida[-1]) + 1, int(art) + 1))
        else:
            salida.append(art)
        rango = False
    return salida


def _contexto(texto: str, ini: int, fin: int) -> str:
    previo = max(0, ini - _CONTEXTO)
    recorte = " ".join(texto[previo : fin + _CONTEXTO].split())
    return f"{'…' if previo else ''}{recorte}{'…' if fin + _CONTEXTO < len(texto) else ''}"


def _texto_cita(articulo: str | None, norma: str) -> str:
    if articulo is None:
        return norma
    articulo_def = "del" if norma.startswith(("Decreto", "Código", "Acuerdo")) else "de la"
    return f"artículo {articulo} {articulo_def} {norma}"


def extraer_normas(texto: str) -> list[CitaNorma]:
    brutas: list[tuple[int, str | None, str, int, int]] = []
    ocupado: list[tuple[int, int]] = []
    for m in _ARTICULO_PRIMERO.finditer(texto):
        norma = _canon_norma(m["norma"])
        ocupado.append(m.span())
        for art in _articulos(m["arts"]):
            brutas.append((m.start(), art, norma, m.start(), m.end()))
    for m in _ARTICULO_SUPERIOR.finditer(texto):
        if any(m.start() < b and a < m.end() for a, b in ocupado):
            continue
        ocupado.append(m.span())
        for art in _articulos(m["arts"]):
            brutas.append((m.start(), art, _CONSTITUCION, m.start(), m.end()))

    def libre(ini: int, fin: int) -> bool:
        return not any(ini < b and a < fin for a, b in ocupado)

    menciones = [(m.start(), m.end(), _canon_norma(m[0])) for m in _LEY.finditer(texto) if libre(*m.span())]
    menciones += [(m.start(), m.end(), _canon_norma(m[0])) for m in _CODIGO.finditer(texto) if libre(*m.span())]
    for ini, fin, norma in sorted(menciones):
        ventana = texto[fin : fin + _VENTANA]
        corte = re.search(r"[.;]", ventana)
        ventana = ventana[: corte.start()] if corte else ventana
        tope = _CORTE_SUPERIOR.search(ventana)
        if tope:
            ventana = ventana[: tope.start()]
        sig = _LEY.search(ventana) or _CODIGO.search(ventana)
        if sig:
            ventana = ventana[: sig.start()]
        suelto = _ARTICULO_SUELTO.search(ventana)
        if suelto and libre(fin + suelto.start(), fin + suelto.end()):
            ocupado.append((fin + suelto.start(), fin + suelto.end()))
            for art in _articulos(suelto["arts"]):
                brutas.append((ini, art, norma, ini, fin + suelto.end()))
        elif norma != _CONSTITUCION:
            brutas.append((ini, None, norma, ini, fin))

    brutas.sort(key=lambda b: b[0])
    con_articulo = {b[2] for b in brutas if b[1] is not None}
    vistas: set[tuple[str | None, str]] = set()
    salida: list[CitaNorma] = []
    for _, art, norma, ini, fin in brutas:
        if art is None and norma in con_articulo:
            continue
        clave = (art, norma.lower())
        if clave in vistas:
            continue
        vistas.add(clave)
        salida.append(CitaNorma(_texto_cita(art, norma), norma, art, _contexto(texto, ini, fin)))
    return salida
