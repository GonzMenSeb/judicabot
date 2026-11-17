"""Identificación de los abogados del expediente y de lo que los faculta para representar a cada parte.

El nodo ``apoderados`` del grafo le pide al modelo una propuesta (``ApoderadosLLM``): partes,
abogados, páginas donde actúan y poderes. Este módulo la comprueba contra el texto del
expediente y descarta lo que no consta, como ``citas.verificar_citas`` con las citas:

- cada cita se busca en la página señalada (``citas.cobertura`` con el umbral de las anclas
  literales de ``lint``) y, si no está ahí, en las demás páginas del mismo documento, corrigiendo
  el número de página;
- el nombre del abogado debe constar en esa página;
- la cédula y la tarjeta profesional se conservan solo si sus dígitos constan junto al nombre del
  abogado en una página comprobada, antes del nombre de otra persona o de la firma de otro; solo
  esas cédulas llegan a consultarse en la Rama Judicial;
- un poder cuenta para la parte que el abogado dice representar si es esa parte la que lo otorga
  o si la página la nombra; va a ``ajenos`` solo si lo otorga otra parte de los metadatos o si su
  otorgante obra como representante de otra parte ("representante legal de …", "X, representada
  legalmente por …"). Un otorgante que coincide con más de una parte no cuenta para ninguna;
- si el modelo no señaló un poder que se pueda comprobar, se busca una página de otorgamiento
  que nombre al abogado;
- para sociedades, el otorgante debe figurar como representante en el certificado de existencia
  y representación del expediente (``Cadena``: confirmada, contradicha, sin_certificado o
  no_aplica).

Ninguna alerta, motivo ni registro de este módulo lleva un número de cédula.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, NamedTuple

from tutela2 import citas, ingest, lint
from tutela2.models import (
    AbogadoLLM,
    Apoderado,
    ApoderadosLLM,
    Cadena,
    Doc,
    EvidenciaDoc,
    Identificacion,
    Ingesta,
    Metadatos,
    Pagina,
    ParteSinApoderado,
    Poder,
    PoderLLM,
    RolParte,
    TipoPoder,
)

VENTANA_NUMEROS = 300
VENTANA_CARGO = 300
VENTANA_OTORGANTE = 300
VENTANA_REPRESENTADA = 60
VENTANA_REPRESENTANTE = 200
VENTANA_OTORGAMIENTO = 600
MIN_PALABRAS_CITA = lint.NGRAMA_ANCLA
MAX_PALABRAS_VENTANA = 60
UMBRAL_PARTE = 0.8
DIGITOS_CEDULA = (5, 10)
DIGITOS_TARJETA = (3, 7)

SIN_CONSULTA_AUTOMATICA = "la vigencia de su tarjeta profesional no se puede consultar automáticamente"
"""Final de los motivos de la identificación que dicen que falta la cédula. ``estado_apoderados`` los
quita cuando la cédula ya se tomó del certificado subido: dejan de describir la situación."""

ALERTA_FALLA = (
    "ALERTA: No se pudieron identificar los apoderados porque la llamada al modelo falló; "
    "verifique a mano la tarjeta profesional y el poder de cada abogado."
)
ALERTA_FALLA_VERIFICACION = (
    "ALERTA: No se pudieron comprobar los apoderados que propuso el modelo por un error interno; "
    "verifique a mano la tarjeta profesional y el poder de cada abogado."
)


class _TablaPlegado(dict):
    def __missing__(self, codigo: int) -> str:
        c = chr(codigo)
        if c.isspace():
            r = " "
        elif unicodedata.combining(c):
            r = ""
        else:
            r = unicodedata.normalize("NFD", c)[0].lower()[:1] or c
        self[codigo] = r
        return r


_TABLA = _TablaPlegado()


def plegar(texto: str) -> str:
    """Minúsculas sin tildes; cada carácter da uno solo, salvo las marcas combinantes, que desaparecen."""
    return texto.translate(_TABLA)


_PALABRA = re.compile(r"[a-z0-9]+")
_PARTICULAS = frozenset("de del la las los el y e da di van von".split())
_TRATAMIENTOS = frozenset("doctor doctora dr dra abogado abogada senor senora sr sra don dona".split())
_GENERICOS_PARTE = frozenset("sas sa ltda eps esp bic sca".split())


def clave(texto: str) -> str:
    return " ".join(_PALABRA.findall(plegar(texto)))


def id_apoderado(nombre: str, parte: str) -> str:
    return "ap-" + hashlib.sha256(f"{clave(nombre)}|{clave(parte)}".encode("utf-8")).hexdigest()[:10]


def huella_ingesta(ing: Ingesta) -> str:
    return hashlib.sha256("\n".join(sorted(d.sha256 for d in ing.documentos)).encode("utf-8")).hexdigest()


CAMPOS_PARTES = ("accionante", "accionadas", "vinculadas", "impugnante", "impugnante_rol", "impugnantes")
"""Campos de los metadatos que recibe el modelo y contra los que se cotejan las partes de los poderes."""


def huella_partes(md: Metadatos) -> str:
    """Huella de las partes de los metadatos: si cambian (``rehacer_apertura`` los vuelve a fusionar),
    la identificación se rehace aunque el expediente sea el mismo."""
    datos = {c: getattr(md, c) for c in CAMPOS_PARTES}
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _digitos(texto: str) -> str:
    """Los dígitos, escritos con 0-9 (uno de otra escritura, de ancho completo o arábigo, vale lo mismo)."""
    return "".join(str(unicodedata.decimal(c)) for c in texto or "" if c.isdecimal())


def _colapsar(texto: str) -> str:
    return " ".join(texto.split())


def tokens_nombre(nombre: str) -> list[str]:
    return list(
        dict.fromkeys(
            t
            for t in _PALABRA.findall(plegar(nombre))
            if len(t) > 1 and not t.isdigit() and t not in _PARTICULAS and t not in _TRATAMIENTOS
        )
    )


def es_particula(palabra: str) -> bool:
    """«de», «del», «la»… dentro de un nombre propio (compara sin tildes ni mayúsculas)."""
    return plegar(palabra).strip() in _PARTICULAS


def tokens_parte(nombre: str) -> list[str]:
    todos = [t for t in dict.fromkeys(_PALABRA.findall(plegar(nombre))) if len(t) > 1 and t not in _PARTICULAS]
    informativos = [t for t in todos if t not in _GENERICOS_PARTE and not t.isdigit()]
    return informativos if len(informativos) >= 2 else todos


def minimo_nombre(n: int) -> int:
    return n if n <= 2 else n - 1


def minimo_parte(n: int) -> int:
    return max(1, math.ceil(UMBRAL_PARTE * n - 1e-9))


@lru_cache(maxsize=4096)
def _patron_token(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])")


def ocurrencias(tokens: list[str], plegado: str, minimo: int) -> list[tuple[int, int]]:
    """Tramos (inicio, fin) del texto plegado donde aparecen juntos al menos ``minimo`` tokens distintos.

    No exige el orden, para admitir "APELLIDOS NOMBRES" y la falta del segundo apellido.
    """
    if not tokens or minimo < 1 or minimo > len(tokens):
        return []
    hallazgos = sorted(
        (m.start(), m.end(), k) for k, t in enumerate(tokens) for m in _patron_token(t).finditer(plegado)
    )
    alcance = 2 * sum(map(len, tokens)) + 60
    tramos: list[tuple[int, int]] = []
    limite = -1
    for i, (ini, fin, k) in enumerate(hallazgos):
        if ini < limite:
            continue
        vistos, fin_tramo = {k}, fin
        for ini2, fin2, k2 in hallazgos[i + 1 :]:
            if ini2 - ini > alcance or (len(vistos) >= minimo and ini2 - fin_tramo > 40):
                break
            if k2 in vistos:
                continue
            vistos.add(k2)
            fin_tramo = max(fin_tramo, fin2)
            if len(vistos) == len(tokens):
                break
        if len(vistos) >= minimo:
            tramos.append((ini, fin_tramo))
            limite = fin_tramo
    return tramos


def presencia(tokens: list[str], plegado: str) -> float:
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if _patron_token(t).search(plegado)) / len(tokens)


def coincide_nombre(a: str, b: str) -> bool:
    ta, tb = set(tokens_nombre(a)), set(tokens_nombre(b))
    if not ta or not tb:
        return False
    comunes = len(ta & tb)
    menor = min(len(ta), len(tb))
    return comunes / menor >= UMBRAL_PARTE and (comunes >= 2 or menor == 1)


def _semejanza(a: str, b: str) -> float:
    """Proporción de palabras comunes sobre el total de ambos nombres (simétrica, a diferencia de
    ``coincide_nombre``, que se mide sobre el más corto)."""
    ta, tb = set(tokens_nombre(a)), set(tokens_nombre(b))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


_JURIDICA = re.compile(
    r"(?<![a-z0-9])(?:s\.?\s?a\.?\s?s|s\.?\s?a|ltda|e\.?\s?s\.?\s?p|e\.?\s?s\.?\s?e|s\.?\s?en\s?c|s\.?\s?c\.?\s?a|bic|eps|ips)"
    r"(?![a-z0-9])|\b(?:sociedad|empresa|entidad|banco|fondo|compania|corporacion|fundacion|cooperativa|asociacion"
    r"|universidad|colegio|clinica|hospital|instituto|secretaria|ministerio|alcaldia|gobernacion|municipio"
    r"|departamento|distrito|superintendencia|unidad|agencia|direccion|fiscalia|policia|ejercito|armada"
    r"|registraduria|contraloria|procuraduria|defensoria|personeria|nacion|consejo|tribunal|juzgado|caja"
    r"|administradora|colpensiones|seguros|aseguradora|comision|servicio|grupo|inversiones|comercializadora"
    r"|distribuidora|distribuciones|industrias?|laboratorios?|organizacion)\b"
)
_SOCIEDAD = re.compile(
    r"(?<![a-z0-9])(?:s\.?\s?a\.?\s?s|s\.?\s?a|ltda|s\.?\s?en\s?c|s\.?\s?c\.?\s?a|bic|eps|ips)(?![a-z0-9])"
    r"|\b(?:sociedad|empresa|compania|cooperativa|aseguradora|seguros|banco|clinica|fundacion|corporacion"
    r"|asociacion|inversiones|comercializadora|distribuidora|distribuciones)\b"
)


def es_juridica(nombre: str) -> bool:
    return bool(_JURIDICA.search(plegar(nombre)))


def requiere_certificado(nombre: str) -> bool:
    """Sociedades y entidades privadas, que acreditan su representación con certificado de existencia."""
    return bool(_SOCIEDAD.search(plegar(nombre)))


_NUM = r"(\d{1,3}(?:[.,]\d{3})+(?!\d)|\d+)"
_ROTULO_NUMERO = r"(?:\s*(?:no|n\.?\s?[°º]|num|numero)\s*\.?)?\s*[:#]?\s*"
_ETIQUETA_CC = re.compile(
    r"(?<![a-z0-9])(?:c\s?\.\s?c\s?\.?|cc(?![a-z0-9])|cedula(?:\s+de\s+ciudadania)?)" + _ROTULO_NUMERO + _NUM
)
_ETIQUETA_TP = re.compile(
    r"(?<![a-z0-9])(?:t\s?\.\s?p\s?\.?|tp(?![a-z0-9])|tarjeta\s+profesional)" + _ROTULO_NUMERO + _NUM
)
_NUMERO = re.compile(r"(?<!\d)" + _NUM)
_ANTES_NIT = re.compile(r"(?<![a-z])nit\W{0,6}$")
_CARGO = re.compile(r"representante\s+legal|suplente|gerente|apoderad[oa]s?")
_APODERADO = re.compile(r"apoderad[oa]s?")
_OTORGAMIENTO = re.compile(
    r"(?<![a-z])(?:confiero|otorgo|sustituyo|reasumo)(?![a-z])|(?<![a-z])(?:confiere|otorga|sustituye)n?\s+(?:el\s+|un\s+)?poder"
)
# Quien otorga un poder en nombre de una parte: "representante legal de la X", "en nombre y
# representación de la X" (la parte va después) o "X, representada legalmente por" (va antes).
_REPRESENTANTE_DE = re.compile(
    r"(?<![a-z])(?:representante\s+legal|apoderad[oa]\s+general|gerente|en\s+(?:su\s+)?(?:nombre|representacion)"
    r"(?:\s+y\s+(?:nombre|representacion))?)(?:\s+(?:principal|suplente|general))?\s+del?(?![a-z])"
)
_REPRESENTADA_POR = re.compile(r"(?<![a-z])representad[oa]\s+(?:legalmente\s+)?por(?![a-z])")
# Rótulos que, al pie de un escrito, separan el bloque de firma del abogado del de otra persona.
_FIRMANTE = re.compile(
    r"(?<![a-z])(?:otorga(?:nte)?|poderdante|sustituye(?:nte)?|representante\s+legal|atentamente|cordialmente)(?![a-z])"
)
_LETRAS = re.compile(r"[a-z]+")
# Entre dos palabras de un mismo nombre solo hay unos pocos espacios; un hueco más ancho es otra
# columna (``pdftotext -layout`` pone lado a lado los bloques de firma).
_HUECO_DE_NOMBRE = re.compile(r"[ \xa0]{1,3}")
MAX_PALABRAS_PEGADAS = 2
# Palabras en mayúscula que no son nombres de persona (rótulos, instituciones, encabezados).
_NO_NOMBRES = frozenset(
    "cedula ciudadania extranjeria tarjeta profesional consejo superior judicatura rama judicial republica colombia "
    "accion tutela poder especial amplio suficiente referencia radicado asunto proceso nro numero nit "
    "abogado abogada apoderado apoderada titulado titulada acepto firma calle carrera avenida oficina "
    "no en con mayor edad identificado identificada portador portadora expedida expedido vecino vecina".split()
)
_NO_TOKENS = _PARTICULAS | _TRATAMIENTOS | _NO_NOMBRES


@dataclass(frozen=True)
class _Numero:
    digitos: str
    inicio: int
    fin: int
    etiqueta: str


class _Palabra(NamedTuple):
    ini: int
    """Inicio en el texto plegado."""
    plegada: str
    mayusculas: bool
    a: int
    """Inicio en el texto original."""
    b: int
    """Fin en el texto original."""


class _Hoja:
    """Una página del expediente con su texto plegado y la correspondencia de posiciones con el original."""

    def __init__(self, doc: Doc, pagina: Pagina) -> None:
        self.doc, self.pagina = doc, pagina
        self.texto = pagina.texto
        self.plegado = plegar(self.texto)
        self._mapa: list[int] | None = None
        if len(self.plegado) != len(self.texto):
            self._mapa = [i for i, c in enumerate(self.texto) if _TABLA[ord(c)]]
        self.certificado = ingest.es_pagina_certificado(pagina)
        self._en_mayusculas: bool | None = None

    def original(self, ini: int, fin: int) -> tuple[int, int]:
        if self._mapa is None:
            return ini, fin
        if not self._mapa:
            return 0, 0
        a = self._mapa[min(ini, len(self._mapa) - 1)]
        b = self._mapa[min(max(fin - 1, 0), len(self._mapa) - 1)] + 1
        while b < len(self.texto) and unicodedata.combining(self.texto[b]):
            b += 1
        return a, b

    def nombra(self, tokens: list[str]) -> list[tuple[int, int]]:
        return ocurrencias(tokens, self.plegado, minimo_nombre(len(tokens)))

    @property
    def en_mayusculas(self) -> bool:
        """La página está escrita casi toda en mayúsculas: ahí una racha en mayúsculas no delata un nombre."""
        if self._en_mayusculas is None:
            letras = [c for c in self.texto if c.isalpha()]
            self._en_mayusculas = bool(letras) and sum(c.isupper() for c in letras) > 0.6 * len(letras)
        return self._en_mayusculas

    def linea_entera(self, a: int, b: int) -> bool:
        """El tramo [a, b) del original ocupa su línea él solo (sin contar espacios ni puntuación final)."""
        inicio = self.texto.rfind("\n", 0, a) + 1
        final = self.texto.find("\n", b)
        final = len(self.texto) if final < 0 else final
        return not self.texto[inicio:a].strip() and not self.texto[b:final].strip(" \t\r\f\xa0,.;:")

    def es_otra_persona(self, racha: list[_Palabra], propios: set[str]) -> bool:
        """Una racha de palabras con inicial mayúscula es el nombre de otra persona si ocupa su línea sola (bloque
        de firma) o, en una página de mayúsculas y minúsculas, si va toda en mayúsculas (dos palabras o más)
        o con inicial mayúscula (tres o más); en ambos casos, con al menos dos palabras que no son del abogado,
        y sin ser un rótulo ni el nombre de una entidad."""
        tokens = [p for p in racha if len(p.plegada) > 1 and p.plegada not in _NO_TOKENS]
        if not tokens or len(tokens) > 6:
            return False
        if self.linea_entera(racha[0].a, racha[-1].b):
            minimo = 2
        elif self.en_mayusculas:
            return False
        else:
            minimo = 2 if all(p.mayusculas for p in tokens) else 3
        ajenas = [p for p in tokens if p.plegada not in propios]
        return (
            len(tokens) >= minimo
            and len(ajenas) >= 2
            and 2 * len(ajenas) >= len(tokens)
            and not es_juridica(" ".join(p.plegada for p in racha))
        )

    def corte_firma(self, ini: int, fin: int, propios: set[str]) -> int:
        """Dónde termina, dentro de [ini, fin), lo que sigue al nombre del abogado y se le puede atribuir: en el
        primer rótulo de firma ("Otorga", "Sustituye", "Atentamente"…) o en el primer nombre de otra persona.

        Una o dos palabras pegadas al nombre (separadas por un espacio o dos, en la misma línea) se tienen
        por el resto de su nombre, que el modelo pudo dar incompleto."""
        m = _FIRMANTE.search(self.plegado, ini, fin)
        if m is not None:
            fin = m.start()
        desde = self.original(ini, ini + 1)[0] if ini < len(self.plegado) else len(self.texto)
        racha: list[_Palabra] = []
        pegada = False

        def cierra() -> bool:
            if pegada and sum(1 for p in racha if p.plegada not in _NO_TOKENS) <= MAX_PALABRAS_PEGADAS:
                return False
            return self.es_otra_persona(racha, propios)

        for m in _LETRAS.finditer(self.plegado, ini, fin):
            a, b = self.original(m.start(), m.end())
            letras = [c for c in self.texto[a:b] if c.isalpha()]
            palabra = _Palabra(m.start(), m.group(), bool(letras) and all(c.isupper() for c in letras), a, b)
            if racha and not _HUECO_DE_NOMBRE.fullmatch(self.texto[racha[-1].b : a]):
                if cierra():
                    return racha[0].ini
                racha, pegada = [], False
            if (letras and letras[0].isupper()) or (racha and palabra.plegada in _PARTICULAS):
                if not racha:
                    pegada = desde >= 0 and bool(_HUECO_DE_NOMBRE.fullmatch(self.texto[desde:a]))
                racha.append(palabra)
            elif racha:
                if cierra():
                    return racha[0].ini
                racha, pegada = [], False
            desde = -1
        if racha and cierra():
            return racha[0].ini
        return fin

    def numeros(self, ini: int, fin: int) -> list[_Numero]:
        trozo = self.plegado[ini : min(len(self.plegado), fin + 20)]
        etiquetas: dict[int, str] = {}
        for etiqueta, rx in (("tp", _ETIQUETA_TP), ("cc", _ETIQUETA_CC)):
            for m in rx.finditer(trozo):
                etiquetas.setdefault(m.start(1), etiqueta)
        salida = []
        for m in _NUMERO.finditer(trozo):
            if ini + m.start(1) >= fin:
                break
            etiqueta = etiquetas.get(m.start(1), "")
            if not etiqueta and _ANTES_NIT.search(trozo[max(0, m.start() - 12) : m.start()]):
                etiqueta = "nit"
            salida.append(_Numero(_digitos(m.group(1)), ini + m.start(1), ini + m.end(1), etiqueta))
        return salida

    def ventana(self, ini: int, fin: int, antes: int = 0, despues: int = 0, recortar_inicio: bool = True) -> tuple[str, int, int]:
        """Fragmento literal de palabras completas que cubre [ini, fin) del plegado, con contexto."""
        a, b = self.original(ini, fin)
        palabras = list(re.finditer(r"\S+", self.texto))
        if not palabras:
            return "", a, b
        primera = next((i for i, w in enumerate(palabras) if w.end() > a), len(palabras) - 1)
        ultima = next((i for i in range(len(palabras) - 1, -1, -1) if palabras[i].start() < b), primera)
        primera, ultima = max(0, primera - antes), min(len(palabras) - 1, max(ultima, primera) + despues)
        if ultima - primera + 1 > MAX_PALABRAS_VENTANA:
            if recortar_inicio:
                primera = ultima - MAX_PALABRAS_VENTANA + 1
            else:
                ultima = primera + MAX_PALABRAS_VENTANA - 1
        inicio, final = palabras[primera].start(), palabras[ultima].end()
        return _colapsar(self.texto[inicio:final]), inicio, final

    def evidencia(self, cita: str, inicio: int | None, fin: int | None, cobertura: float = 1.0) -> EvidenciaDoc:
        return EvidenciaDoc(
            doc_id=self.doc.doc_id,
            pagina=self.pagina.n,
            cita=cita,
            cobertura=round(cobertura, 3),
            ocr=self.pagina.ocr,
            inicio=inicio,
            fin=fin,
        )

    def evidencia_ventana(self, ini: int, fin: int, antes: int = 8, despues: int = 8, recortar_inicio: bool = True) -> EvidenciaDoc:
        cita, a, b = self.ventana(ini, fin, antes, despues, recortar_inicio)
        return self.evidencia(cita, a, b)


def _alinear(cita: str, hoja: _Hoja) -> tuple[int | None, int | None]:
    tokens = _PALABRA.findall(plegar(cita))
    if not tokens:
        return None, None

    def patron(ts: list[str]) -> re.Pattern[str]:
        return re.compile(r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(map(re.escape, ts)) + r"(?![a-z0-9])")

    m = patron(tokens).search(hoja.plegado)
    if m:
        return hoja.original(m.start(), m.end())
    k = min(MIN_PALABRAS_CITA, len(tokens))
    tope = 3 * len(cita) + 100
    for a in patron(tokens[:k]).finditer(hoja.plegado):
        for b in patron(tokens[-k:]).finditer(hoja.plegado, a.end()):
            if b.end() - a.start() > tope:
                break
            return hoja.original(a.start(), b.end())
    return None, None


@dataclass
class _Parte:
    nombre: str
    rol: RolParte
    tokens: list[str]

    @property
    def clave(self) -> str:
        return clave(self.nombre)


@dataclass
class _Contexto:
    abogado: AbogadoLLM
    nombre: str
    tokens: list[str]
    parte_nombre: str
    parte: _Parte | None
    parte_tokens: list[str]
    rol: RolParte
    tipo_persona: str
    otros: list[list[str]]
    menciones: list[tuple[EvidenciaDoc, _Hoja]] = field(default_factory=list)
    poderes: list[tuple[Poder, _Hoja]] = field(default_factory=list)
    ajenos: list[tuple[Poder, _Hoja]] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)

    def paginas_de_poder(self) -> set[tuple[str, int]]:
        return {(p.evidencia.doc_id, p.evidencia.pagina) for p, _ in (*self.poderes, *self.ajenos)}

    def hojas(self) -> list[_Hoja]:
        vistas: dict[tuple[str, int], _Hoja] = {}
        for _, h in (*self.poderes, *self.ajenos, *self.menciones):
            vistas.setdefault((h.doc.doc_id, h.pagina.n), h)
        return list(vistas.values())


_QUE = {
    "poder": "del poder",
    "sustitucion": "de la sustitución de poder",
    "certificado_existencia": "del certificado de existencia",
}


class _Verificador:
    def __init__(self, propuesta: ApoderadosLLM, ing: Ingesta, md: Metadatos) -> None:
        self.propuesta, self.ing = propuesta, ing
        self.docs = {d.doc_id: d for d in ingest.documentos_para_apoderados(ing)}
        self._hojas: dict[tuple[str, int], _Hoja] = {}
        self.partes = _partes_de(md)
        self._grupos: list[list[_Hoja]] | None = None
        self.alertas: list[str] = []

    def hoja(self, d: Doc, p: Pagina) -> _Hoja:
        k = (d.doc_id, p.n)
        if k not in self._hojas:
            self._hojas[k] = _Hoja(d, p)
        return self._hojas[k]

    @staticmethod
    def legibles(d: Doc) -> list[Pagina]:
        return [p for p in d.paginas if p.texto.strip() and not p.sin_texto]

    def grupos_certificado(self) -> list[list[_Hoja]]:
        """Tramos de páginas seguidas de certificado de existencia: un certificado suele nombrar a la sociedad
        en su primera página y a sus representantes en las siguientes."""
        if self._grupos is None:
            self._grupos = []
            for d in self.docs.values():
                grupo: list[_Hoja] = []
                for p in sorted(self.legibles(d), key=lambda p: p.n):
                    if ingest.es_pagina_certificado(p):
                        grupo.append(self.hoja(d, p))
                    elif grupo:
                        self._grupos.append(grupo)
                        grupo = []
                if grupo:
                    self._grupos.append(grupo)
        return self._grupos

    def certificados_de(self, tokens: list[str]) -> list[list[_Hoja]]:
        return [g for g in self.grupos_certificado() if any(presencia(tokens, h.plegado) >= UMBRAL_PARTE for h in g)]

    def resolver_parte(self, texto: str) -> tuple[str, RolParte, _Parte | None]:
        texto = _colapsar(texto)
        k = clave(texto)
        for p in self.partes:
            if p.clave == k:
                return p.nombre, p.rol, p
        tokens = set(tokens_parte(texto))
        mejor, puntaje = None, 0.0
        for p in self.partes:
            comunes = len(tokens & set(p.tokens))
            if not comunes or not p.tokens:
                continue
            a, b = comunes / len(p.tokens), comunes / max(len(tokens), 1)
            if a >= UMBRAL_PARTE and b >= 0.5 and a + b > puntaje:
                mejor, puntaje = p, a + b
        if mejor is not None:
            return mejor.nombre, mejor.rol, mejor
        rol = next((pl.rol_parte for pl in self.propuesta.partes if clave(pl.nombre) == k and k), "otro")
        return texto, rol, None

    def otros_nombres(self, ab: AbogadoLLM) -> list[list[str]]:
        nombres = [a.nombre for a in self.propuesta.abogados if a is not ab]
        nombres += [p.otorgante for a in self.propuesta.abogados for p in a.poderes]
        nombres += [p.nombre for p in self.partes if not es_juridica(p.nombre)]
        propios = set(tokens_nombre(ab.nombre))
        salida = []
        for n in nombres:
            ts = tokens_nombre(n)
            if ts and not (set(ts) <= propios or propios <= set(ts)) and ts not in salida:
                salida.append(ts)
        return salida

    def comprobar(
        self, doc_id: str, pagina: int, cita: str, tokens: list[str], que: str
    ) -> tuple[_Hoja | None, EvidenciaDoc | None, str | None]:
        d = self.docs.get(doc_id)
        if d is None:
            return None, None, f"La cita {que} señala el documento «{doc_id}», que no está entre los revisados; se descartó."
        if citas.contar_palabras(cita) < MIN_PALABRAS_CITA:
            return None, None, f"La cita {que} en {doc_id}, p. {pagina}, es demasiado corta para comprobarla; se descartó."
        sin_nombre = None
        for p in sorted(self.legibles(d), key=lambda p: (p.n != pagina, abs(p.n - pagina), p.n)):
            cob = citas.cobertura(cita, p.texto, lint.NGRAMA_ANCLA) or 0.0
            if cob < lint.COBERTURA_ANCLA:
                continue
            hoja = self.hoja(d, p)
            if not hoja.nombra(tokens):
                sin_nombre = sin_nombre or p.n
                continue
            inicio, fin = _alinear(cita, hoja)
            ev = hoja.evidencia(_colapsar(cita), inicio, fin, cob)
            motivo = None if p.n == pagina else f"La cita {que} estaba en {doc_id}, p. {p.n}, y no en la p. {pagina}; se corrigió la página."
            return hoja, ev, motivo
        if sin_nombre is not None:
            return None, None, f"La cita {que} consta en {doc_id}, p. {sin_nombre}, pero esa página no nombra al abogado; se descartó."
        return None, None, f"La cita {que} no consta en {doc_id}; se descartó."

    def parte_del_poder(self, ctx: _Contexto, hoja: _Hoja, otorgante: str) -> _Parte | Literal["ambigua"] | None:
        """La parte de los metadatos por la que se otorga el poder, si se puede saber.

        1. El otorgante es una de las partes: la que mejor coincide con su nombre; ante un empate gana la
           que el abogado dice representar y, sin ella, es ``"ambigua"`` (también si la que dice representar
           coincide pero otra coincide mejor).
        2. El otorgante obra como representante de una parte: "<otorgante>, representante legal de la X" o
           "X, representada legalmente por <otorgante>".
        3. Si no, ``None``: decide si la página nombra a la parte que el abogado dice representar."""
        if not otorgante:
            return None
        coincidentes = [p for p in self.partes if coincide_nombre(otorgante, p.nombre)]
        if coincidentes:
            puntajes = {p.clave: _semejanza(otorgante, p.nombre) for p in coincidentes}
            mejor = max(puntajes.values())
            primeras = [p for p in coincidentes if puntajes[p.clave] == mejor]
            reclamada = ctx.parte.clave if ctx.parte is not None else None
            if any(p.clave == reclamada for p in primeras):
                return ctx.parte
            if len(primeras) == 1 and reclamada not in puntajes:
                return primeras[0]
            return "ambigua"
        tramos_partes = [(p, ocurrencias(p.tokens, hoja.plegado, minimo_parte(len(p.tokens)))) for p in self.partes]
        for ini, fin in hoja.nombra(tokens_nombre(otorgante)):
            for cargo in _REPRESENTANTE_DE.finditer(hoja.plegado, fin, min(len(hoja.plegado), fin + VENTANA_OTORGANTE)):
                tras = [
                    (a - cargo.end(), p)
                    for p, tramos in tramos_partes
                    for a, _ in tramos
                    if cargo.end() <= a <= cargo.end() + VENTANA_REPRESENTADA
                ]
                if tras:
                    return min(tras, key=lambda t: t[0])[1]
            for cargo in _REPRESENTADA_POR.finditer(hoja.plegado, max(0, ini - VENTANA_REPRESENTADA), ini):
                antes = [
                    (cargo.start() - b, p)
                    for p, tramos in tramos_partes
                    for _, b in tramos
                    if cargo.start() - VENTANA_REPRESENTANTE <= b <= cargo.start()
                ]
                if antes:
                    return min(antes, key=lambda t: t[0])[1]
        return None

    def clasificar_poder(
        self, ctx: _Contexto, tipo: TipoPoder, ev: EvidenciaDoc, hoja: _Hoja, otorgante: str, explicar: bool
    ) -> str | None:
        duena = self.parte_del_poder(ctx, hoja, otorgante)
        if duena == "ambigua":
            if explicar:
                ctx.motivos.append(
                    f"El otorgante del poder de {ev.doc_id}, p. {ev.pagina} ({otorgante}), coincide con más de una parte "
                    "del caso; no se tuvo en cuenta."
                )
            return None
        misma = duena is not None and ctx.parte is not None and duena.clave == ctx.parte.clave
        if duena is not None and not misma:
            if ctx.parte is not None:
                poder = Poder(tipo=tipo, evidencia=ev, otorgante=otorgante, parte=duena.nombre)
                if not any(p.evidencia.doc_id == ev.doc_id and p.evidencia.pagina == ev.pagina for p, _ in ctx.ajenos):
                    ctx.ajenos.append((poder, hoja))
                    ctx.motivos.append(
                        f"El poder de {ev.doc_id}, p. {ev.pagina}, lo otorga {duena.nombre} ({duena.rol}), "
                        f"no {ctx.parte_nombre}."
                    )
                return "ajeno"
            if explicar:
                ctx.motivos.append(
                    f"El poder de {ev.doc_id}, p. {ev.pagina}, lo otorga {duena.nombre}, y {ctx.parte_nombre or 'la parte señalada'} "
                    "no figura entre las partes del caso; no se tuvo en cuenta."
                )
            return None
        if not misma and presencia(ctx.parte_tokens, hoja.plegado) < UMBRAL_PARTE:
            if explicar:
                ctx.motivos.append(
                    f"La p. {ev.pagina} de {ev.doc_id} no nombra a {ctx.parte_nombre or 'la parte representada'}; "
                    "no se tuvo como poder para esa parte."
                )
            return None
        if not any(p.evidencia.doc_id == ev.doc_id and p.evidencia.pagina == ev.pagina for p, _ in ctx.poderes):
            ctx.poderes.append((Poder(tipo=tipo, evidencia=ev, otorgante=otorgante, parte=ctx.parte_nombre), hoja))
        return "poder"

    def apoderado_en_certificado(self, hoja: _Hoja, tokens: list[str]) -> tuple[int, int] | None:
        for ini, fin in hoja.nombra(tokens):
            for m in _APODERADO.finditer(hoja.plegado, max(0, ini - VENTANA_CARGO), fin + VENTANA_CARGO):
                return min(ini, m.start()), max(fin, m.end())
        return None

    def otorgante_en(self, hoja: _Hoja, otorgante: str, ctx: _Contexto) -> str:
        otorgante = _colapsar(otorgante)
        if not otorgante:
            return ""
        if hoja.nombra(tokens_nombre(otorgante)):
            return otorgante
        ctx.motivos.append(
            f"El otorgante que señaló el modelo ({otorgante}) no consta en {hoja.doc.doc_id}, p. {hoja.pagina.n}; "
            "se tiene por no indicado."
        )
        return ""

    def poder_propuesto(self, ctx: _Contexto, pl: PoderLLM) -> None:
        que = _QUE[pl.tipo]
        hoja, ev, motivo = self.comprobar(pl.doc_id, pl.pagina, pl.cita, ctx.tokens, que)
        if motivo:
            ctx.motivos.append(motivo)
        if hoja is None or ev is None:
            return
        if hoja.doc.doc_id in self.ing.docs_revisar:
            ctx.motivos.append(
                f"El poder de {ev.doc_id}, p. {ev.pagina}, está en un documento que parece de otro radicado; no se tuvo en cuenta."
            )
            return
        tipo: TipoPoder = pl.tipo
        if hoja.certificado:
            if self.apoderado_en_certificado(hoja, ctx.tokens) is None:
                ctx.motivos.append(
                    f"El certificado de existencia de {ev.doc_id}, p. {ev.pagina}, no inscribe al abogado como apoderado; "
                    "no se tuvo como poder."
                )
                return
            tipo = "certificado_existencia"
        elif tipo == "certificado_existencia":
            ctx.motivos.append(
                f"La p. {ev.pagina} de {ev.doc_id} no es un certificado de existencia y representación; no se tuvo como poder."
            )
            return
        otorgante = "" if tipo == "certificado_existencia" else self.otorgante_en(hoja, pl.otorgante, ctx)
        self.clasificar_poder(ctx, tipo, ev, hoja, otorgante, explicar=True)

    def buscar_poder(self, ctx: _Contexto, digitos: set[str]) -> bool:
        usadas = ctx.paginas_de_poder()
        propuestos = [_colapsar(p.otorgante) for p in ctx.abogado.poderes if p.otorgante.strip()]
        for d in self.docs.values():
            if d.doc_id in self.ing.docs_revisar:
                continue
            for p in self.legibles(d):
                if (d.doc_id, p.n) in usadas or ingest.es_pagina_certificado(p):
                    continue
                hoja = self.hoja(d, p)
                claves = list(_OTORGAMIENTO.finditer(hoja.plegado))
                if not claves:
                    continue
                nombres = hoja.nombra(ctx.tokens)
                if not nombres:
                    continue
                if digitos and not digitos & {n.digitos for n in hoja.numeros(0, len(hoja.plegado))}:
                    continue
                for kw in claves:
                    tras = [(i, f) for i, f in nombres if kw.start() <= i <= kw.end() + VENTANA_OTORGAMIENTO]
                    if not tras:
                        continue
                    ev = hoja.evidencia_ventana(kw.start(), tras[0][1], antes=0, despues=4)
                    tipo: TipoPoder = "sustitucion" if kw.group().startswith("sustitu") else "poder"
                    otorgante = next((o for o in propuestos if hoja.nombra(tokens_nombre(o))), "")
                    if self.clasificar_poder(ctx, tipo, ev, hoja, otorgante, explicar=False) == "poder":
                        ctx.motivos.append(
                            f"El modelo no señaló un poder comprobable; se halló uno en {d.doc_id}, p. {p.n}."
                        )
                        return True
                    break
        if ctx.tipo_persona == "juridica":
            for grupo in self.certificados_de(ctx.parte_tokens):
                for hoja in grupo:
                    tramo = self.apoderado_en_certificado(hoja, ctx.tokens)
                    if tramo is None:
                        continue
                    ev = hoja.evidencia_ventana(*tramo)
                    ctx.poderes.append(
                        (Poder(tipo="certificado_existencia", evidencia=ev, parte=ctx.parte_nombre), hoja)
                    )
                    ctx.motivos.append(
                        f"El certificado de existencia de {hoja.doc.doc_id}, p. {hoja.pagina.n}, inscribe al abogado como apoderado."
                    )
                    return True
        return False

    def buscar_mencion(self, ctx: _Contexto) -> bool:
        orden = sorted(self.docs.values(), key=lambda d: d.rol not in ingest.ROLES_ESCRITOS)
        for d in orden:
            for p in self.legibles(d):
                if ingest.es_pagina_certificado(p):
                    continue
                hoja = self.hoja(d, p)
                tramos = hoja.nombra(ctx.tokens)
                if tramos:
                    ctx.menciones.append((hoja.evidencia_ventana(*tramos[0], antes=8, despues=12), hoja))
                    ctx.motivos.append(
                        f"El modelo no señaló una mención comprobable del abogado; su nombre consta en {d.doc_id}, p. {p.n}."
                    )
                    return True
        return False

    def identificadores(self, ctx: _Contexto) -> tuple[str | None, str | None, EvidenciaDoc | None, list[str]]:
        hallados: list[tuple[_Hoja, int, _Numero]] = []
        propios = set(ctx.tokens)
        for hoja in ctx.hojas():
            cortes = sorted(i for ts in ctx.otros for i, _ in hoja.nombra(ts))
            for ini, fin in hoja.nombra(ctx.tokens):
                limite = min([c for c in cortes if c >= fin] + [fin + VENTANA_NUMEROS])
                limite = hoja.corte_firma(fin, limite, propios)
                hallados += [(hoja, ini, n) for n in hoja.numeros(fin, limite)]

        def elegir(propuesto: str, etiquetas: set[str], auto: str, rango: tuple[int, int]):
            valido = rango[0] <= len(propuesto) <= rango[1]
            if propuesto and valido:
                for h, ini, n in hallados:
                    if n.digitos == propuesto and n.etiqueta in etiquetas:
                        return propuesto, (h, ini, n), "ok"
            for h, ini, n in hallados:
                if n.etiqueta == auto and rango[0] <= len(n.digitos) <= rango[1]:
                    return n.digitos, (h, ini, n), "auto"
            return None, None, "no_valido" if propuesto and not valido else "ausente"

        motivos: list[str] = []
        cc_propuesta = _digitos(ctx.abogado.cedula_texto)
        cedula, fuente_cc, como = elegir(cc_propuesta, {"cc", ""}, "cc", DIGITOS_CEDULA)
        sin_consulta = SIN_CONSULTA_AUTOMATICA
        if como == "auto" and cc_propuesta:
            motivos.append(
                "La cédula que señaló el modelo no consta junto al nombre del abogado; se tomó la que consta en "
                f"{fuente_cc[0].doc.doc_id}, p. {fuente_cc[0].pagina.n}."
            )
        elif como == "no_valido":
            motivos.append(f"La cédula que señaló el modelo no tiene entre 5 y 10 dígitos; se descartó y {sin_consulta}.")
        elif como == "ausente" and cc_propuesta:
            motivos.append(
                "La cédula que señaló el modelo no consta junto al nombre del abogado en las páginas comprobadas; "
                f"se descartó y {sin_consulta}."
            )
        elif como == "ausente":
            motivos.append(f"No consta la cédula del abogado junto a su nombre en las páginas comprobadas; {sin_consulta}.")
        # El número que propuso el modelo no se repite en el motivo: si no consta como T.P. del abogado
        # puede ser cualquier otro, incluso una cédula.
        tp_propuesta = _digitos(ctx.abogado.tarjeta_texto)
        tarjeta, fuente_tp, como = elegir(tp_propuesta, {"tp"}, "tp", DIGITOS_TARJETA)
        if como == "auto" and tp_propuesta:
            motivos.append(
                "La tarjeta profesional que señaló el modelo no consta junto al nombre del abogado; "
                f"se tomó la {tarjeta}, que consta en {fuente_tp[0].doc.doc_id}, p. {fuente_tp[0].pagina.n}."
            )
        elif como != "ok" and tp_propuesta:
            motivos.append(
                "La tarjeta profesional que señaló el modelo no consta junto al nombre del abogado "
                "en las páginas comprobadas; se descartó."
            )
        elif como == "ausente":
            motivos.append("No consta el número de tarjeta profesional junto al nombre del abogado en las páginas comprobadas.")
        fuente = None
        if fuente_cc is not None:
            hoja, ini, n = fuente_cc
            fuente = hoja.evidencia_ventana(ini, n.fin, antes=0, despues=0)
        return cedula, tarjeta, fuente, motivos

    def cadena(self, ctx: _Contexto, poder: Poder) -> Cadena:
        if ctx.tipo_persona == "natural" or poder.tipo != "poder":
            return Cadena(estado="no_aplica", otorgante=poder.otorgante)
        grupos = self.certificados_de(ctx.parte_tokens)
        if not grupos:
            if requiere_certificado(ctx.parte_nombre):
                ctx.motivos.append(
                    f"No obra certificado de existencia y representación de {ctx.parte_nombre}; "
                    "no se pudo cotejar quién otorgó el poder."
                )
                return Cadena(estado="sin_certificado", otorgante=poder.otorgante)
            return Cadena(estado="no_aplica", otorgante=poder.otorgante)
        referencia = next(h for g in grupos for h in g if presencia(ctx.parte_tokens, h.plegado) >= UMBRAL_PARTE)
        tramo_parte = ocurrencias(ctx.parte_tokens, referencia.plegado, minimo_parte(len(ctx.parte_tokens)))
        ev_referencia = (
            referencia.evidencia_ventana(*tramo_parte[0], antes=4, despues=8)
            if tramo_parte
            else referencia.evidencia_ventana(0, 1, antes=0, despues=12)
        )
        otorgante = poder.otorgante
        if not otorgante or coincide_nombre(otorgante, ctx.parte_nombre):
            ctx.motivos.append(
                f"No se pudo determinar quién otorgó el poder de {poder.evidencia.doc_id}, p. {poder.evidencia.pagina}, a "
                f"nombre de {ctx.parte_nombre}; no se cotejó con el certificado de existencia."
            )
            return Cadena(estado="contradicha", otorgante="", evidencia=ev_referencia)
        tokens = tokens_nombre(otorgante)
        nombrado: tuple[_Hoja, int, int] | None = None
        for grupo in grupos:
            for hoja in grupo:
                for ini, fin in hoja.nombra(tokens):
                    cargo = _cargo_cerca(hoja, ini, fin)
                    if cargo is not None:
                        texto, c_ini, c_fin = cargo
                        return Cadena(
                            estado="confirmada",
                            otorgante=otorgante,
                            cargo=texto,
                            evidencia=hoja.evidencia_ventana(min(ini, c_ini), max(fin, c_fin), antes=4, despues=4),
                        )
                    nombrado = nombrado or (hoja, ini, fin)
        if nombrado is not None:
            hoja, ini, fin = nombrado
            ctx.motivos.append(
                f"El certificado de existencia de {ctx.parte_nombre} nombra a {otorgante} ({hoja.doc.doc_id}, p. {hoja.pagina.n}), "
                "pero no como representante legal, suplente, gerente ni apoderado."
            )
            return Cadena(estado="contradicha", otorgante=otorgante, evidencia=hoja.evidencia_ventana(ini, fin))
        ctx.motivos.append(
            f"El certificado de existencia de {ctx.parte_nombre} ({referencia.doc.doc_id}, p. {referencia.pagina.n}) "
            f"no nombra a {otorgante}, quien otorgó el poder."
        )
        return Cadena(estado="contradicha", otorgante=otorgante, evidencia=ev_referencia)

    def abogado(self, ab: AbogadoLLM) -> Apoderado | None:
        nombre = _colapsar(ab.nombre)
        tokens = tokens_nombre(nombre)
        if not tokens:
            return None
        parte_nombre, rol, parte = self.resolver_parte(ab.parte)
        ctx = _Contexto(
            abogado=ab,
            nombre=nombre,
            tokens=tokens,
            parte_nombre=parte_nombre,
            parte=parte,
            parte_tokens=parte.tokens if parte else tokens_parte(parte_nombre),
            rol=rol,
            tipo_persona="juridica" if es_juridica(parte_nombre) else "natural",
            otros=self.otros_nombres(ab),
        )
        if not parte_nombre:
            ctx.motivos.append("El modelo no indicó a qué parte representa el abogado.")
        elif parte is None:
            ctx.motivos.append(f"La parte «{parte_nombre}» no figura en los metadatos del caso.")
        for m in ab.menciones:
            hoja, ev, motivo = self.comprobar(m.doc_id, m.pagina, m.cita, tokens, "de la mención")
            if motivo:
                ctx.motivos.append(motivo)
            if hoja is not None and ev is not None and (ev.doc_id, ev.pagina) not in {(e.doc_id, e.pagina) for e, _ in ctx.menciones}:
                ctx.menciones.append((ev, hoja))
        for pl in ab.poderes:
            self.poder_propuesto(ctx, pl)
        if not ctx.poderes:
            cedula, tarjeta, _, _ = self.identificadores(ctx)
            if not self.buscar_poder(ctx, {d for d in (cedula, tarjeta) if d}):
                ctx.motivos.append(
                    f"No se halló poder para {parte_nombre or 'la parte representada'} en los {len(self.docs)} documentos revisados."
                )
        if not (ctx.menciones or ctx.poderes or ctx.ajenos) and not self.buscar_mencion(ctx):
            return None
        cedula, tarjeta, fuente, motivos_id = self.identificadores(ctx)
        ctx.motivos += motivos_id
        poderes = [p.model_copy(update={"cadena": self.cadena(ctx, p)}) for p, _ in ctx.poderes]
        return Apoderado(
            id=id_apoderado(nombre, parte_nombre),
            nombre=nombre,
            parte=parte_nombre,
            rol_parte=rol,
            tipo_persona=ctx.tipo_persona,
            cedula=cedula,
            tarjeta=tarjeta,
            cedula_fuente=fuente,
            menciones=[e for e, _ in ctx.menciones],
            poderes=poderes,
            ajenos=[p for p, _ in ctx.ajenos],
            motivos=list(dict.fromkeys(ctx.motivos)),
        )

    def sin_apoderado(self, apoderados: list[Apoderado]) -> list[ParteSinApoderado]:
        representadas = {clave(a.parte) for a in apoderados}
        salida: dict[str, ParteSinApoderado] = {}
        for pl in self.propuesta.partes:
            if not pl.nombre.strip():
                continue
            nombre, rol, parte = self.resolver_parte(pl.nombre)
            k = clave(nombre)
            if k in representadas or k in salida:
                continue
            if pl.con_abogado:
                self.alertas.append(
                    f"ALERTA: Según el modelo, {nombre} actúa por medio de abogado, pero no se pudo comprobar en el "
                    "expediente quién la representa; revíselo."
                )
                continue
            nota = (
                "Actúa por su representante legal o por un funcionario."
                if es_juridica(nombre)
                else "Actúa en nombre propio."
            )
            salida[k] = ParteSinApoderado(nombre=nombre, rol_parte=rol, nota=nota)
        return list(salida.values())

    def red_de_seguridad(self, apoderados: list[Apoderado]) -> list[str]:
        cubiertas = {a.tarjeta for a in apoderados if a.tarjeta}
        vistas: set[str] = set()
        alertas: list[str] = []
        for d in self.docs.values():
            if d.rol not in ingest.ROLES_ESCRITOS or d.doc_id in self.ing.docs_revisar:
                continue
            for p in self.legibles(d):
                if ingest.es_pagina_certificado(p):
                    continue
                hoja = self.hoja(d, p)
                for m in _ETIQUETA_TP.finditer(hoja.plegado):
                    tp = _digitos(m.group(1))
                    if not DIGITOS_TARJETA[0] <= len(tp) <= DIGITOS_TARJETA[1] or tp in cubiertas or tp in vistas:
                        continue
                    vistas.add(tp)
                    alertas.append(
                        f"ALERTA: En {d.doc_id} ({d.nombre}), p. {p.n}, consta la tarjeta profesional {tp}, que no "
                        "corresponde a ningún apoderado identificado; revise si actúa un abogado que no se identificó."
                    )
        return alertas


def _cargo_cerca(hoja: _Hoja, ini: int, fin: int) -> tuple[str, int, int] | None:
    mejor: tuple[int, re.Match[str]] | None = None
    for m in _CARGO.finditer(hoja.plegado, max(0, ini - VENTANA_CARGO), min(len(hoja.plegado), fin + VENTANA_CARGO)):
        distancia = max(0, m.start() - fin, ini - m.end())
        if mejor is None or distancia < mejor[0]:
            mejor = (distancia, m)
    if mejor is None:
        return None
    m = mejor[1]
    a, b = hoja.original(m.start(), m.end())
    return _colapsar(hoja.texto[a:b]).lower(), m.start(), m.end()


def _partes_de(md: Metadatos) -> list[_Parte]:
    crudas: list[tuple[str | None, RolParte]] = [(md.accionante, "accionante")]
    crudas += [(n, "accionada") for n in md.accionadas]
    crudas += [(n, "vinculada") for n in md.vinculadas]
    partes: dict[str, _Parte] = {}
    for nombre, rol in crudas:
        nombre = _colapsar(nombre or "")
        if nombre and clave(nombre) not in partes:
            partes[clave(nombre)] = _Parte(nombre=nombre, rol=rol, tokens=tokens_parte(nombre))
    return list(partes.values())


def _fusionar(a: Apoderado, b: Apoderado) -> Apoderado:
    def unicos(evs: list, clave_de) -> list:
        vistos: dict = {}
        for e in evs:
            vistos.setdefault(clave_de(e), e)
        return list(vistos.values())

    motivos = [*a.motivos, *b.motivos]
    datos: dict = {}
    for campo, fuente in (("cedula", "cedula_fuente"), ("tarjeta", None)):
        x, y = getattr(a, campo), getattr(b, campo)
        if x and y and x != y:
            datos[campo] = None
            if fuente:
                datos[fuente] = None
            motivos.append(
                "Se hallaron dos cédulas distintas para el mismo abogado; no se consultará ninguna."
                if campo == "cedula"
                else f"Se hallaron dos tarjetas profesionales distintas para el mismo abogado ({x} y {y}); se descartaron."
            )
        else:
            datos[campo] = x or y
            if fuente:
                datos[fuente] = getattr(a, fuente) if x else getattr(b, fuente)
    return a.model_copy(
        update={
            **datos,
            "menciones": unicos([*a.menciones, *b.menciones], lambda e: (e.doc_id, e.pagina)),
            "poderes": unicos([*a.poderes, *b.poderes], lambda p: (p.tipo, p.evidencia.doc_id, p.evidencia.pagina)),
            "ajenos": unicos([*a.ajenos, *b.ajenos], lambda p: (p.parte, p.evidencia.doc_id, p.evidencia.pagina)),
            "motivos": list(dict.fromkeys(motivos)),
        }
    )


MIN_PALABRAS_PODER_MANUAL = 8
"""Palabras mínimas de la cita de un poder señalado a mano (si la página las tiene)."""


def evidencia_poder_manual(doc: Doc, pagina: Pagina, nombre: str) -> EvidenciaDoc | None:
    """Comprueba la página que quien revisa señaló a mano como el poder del abogado y devuelve su cita.

    El nombre del abogado debe constar en la página con la misma tolerancia de la identificación
    (en un nombre de tres palabras o más puede faltar una, el segundo apellido). La cita es un
    fragmento literal de 8 a 60 palabras: desde la palabra de otorgamiento más cercana antes del
    nombre ("confiero", "otorgo", "sustituyo"…) hasta unas palabras después de él o, si no la hay,
    el nombre con unas palabras de contexto a cada lado. ``inicio`` y ``fin`` la ubican en el texto
    de la página. ``None`` si la página no tiene texto o no nombra al abogado."""
    tokens = tokens_nombre(nombre)
    if not tokens or pagina.sin_texto or not pagina.texto.strip():
        return None
    hoja = _Hoja(doc, pagina)
    tramos = hoja.nombra(tokens)
    if not tramos:
        return None
    claves = list(_OTORGAMIENTO.finditer(hoja.plegado))
    for ini, fin in tramos:
        previas = [kw for kw in claves if kw.start() <= ini <= kw.end() + VENTANA_OTORGAMIENTO]
        if previas:
            ev = hoja.evidencia_ventana(previas[-1].start(), fin, antes=0, despues=4)
            if citas.contar_palabras(ev.cita) >= MIN_PALABRAS_PODER_MANUAL:
                return ev
    return hoja.evidencia_ventana(*tramos[0], antes=8, despues=12)


def verificar(propuesta: ApoderadosLLM, ing: Ingesta, md: Metadatos) -> Identificacion:
    """Comprueba la propuesta del modelo contra el expediente; lo que no consta se descarta."""
    v = _Verificador(propuesta, ing, md)
    apoderados: dict[str, Apoderado] = {}
    for ab in propuesta.abogados:
        ap = v.abogado(ab)
        if ap is None:
            if _colapsar(ab.nombre):
                v.alertas.append(
                    f"ALERTA: El modelo propuso como abogado a {_colapsar(ab.nombre)}"
                    f"{f' ({_colapsar(ab.parte)})' if ab.parte.strip() else ''}, pero su nombre no consta en el expediente; "
                    "se descartó."
                )
            continue
        apoderados[ap.id] = _fusionar(apoderados[ap.id], ap) if ap.id in apoderados else ap
    lista = list(apoderados.values())
    sin_apoderado = v.sin_apoderado(lista)
    alertas = [*v.alertas, *v.red_de_seguridad(lista)]
    return Identificacion(
        ingesta_sha=huella_ingesta(ing),
        metadatos_sha=huella_partes(md),
        apoderados=lista,
        sin_apoderado=sin_apoderado,
        alertas=list(dict.fromkeys(alertas)),
        documentos_revisados=len(v.docs),
    )
