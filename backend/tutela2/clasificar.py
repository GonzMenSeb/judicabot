# Clasificación determinista por contenido; no hay paso con LLM.
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field

from .models import Doc, Rol


def plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _plegar(s: str) -> str:
    return "".join(
        " " if c.isspace() else unicodedata.normalize("NFD", c)[0].lower() for c in s
    )


_CUI = re.compile(r"(?<!\d)(?<!\d[ \-])(?:\d[ \-]?){22}\d(?!\d)(?![ \-]\d)")


def extraer_cuis(texto: str) -> list[str]:
    return [re.sub(r"\D", "", m.group()) for m in _CUI.finditer(texto.replace("​", ""))]


def menciona_radicado(texto: str, prefijo: str) -> bool:
    anio, seq = prefijo[12:16], int(prefijo[16:21])
    corto = rf"{anio}[ \-/]?0*{seq}(?:[ \-]?0[01])?"
    return re.search(rf"(?<!\d)(?:{prefijo}|{corto})(?!\d)", texto) is not None


MAX_EVIDENCIA = 160
ENCABEZADO = 1500
MAX_PAGINAS_AUTO = 4
MIN_CHARS_FALLO = 10000
CABECERA_DOCX = 4000
EVIDENCIA_SIN_TEXTO = "Sin texto legible."
EVIDENCIA_SIN_ROL = "Sin rasgos de ningún rol."


@dataclass
class _Vista:
    nombre: str
    original: str
    f: str
    npag: int
    limites: list[int] = field(default_factory=list)

    def buscar(
        self, patron: str, fin: int | None = None, inicio: int = 0
    ) -> re.Match | None:
        return re.compile(patron).search(
            self.f, inicio, fin if fin is not None else len(self.f)
        )

    def cita(self, m: re.Match) -> str:
        a = max(0, m.start() - 20)
        trozo = " ".join(self.original[a : m.end() + 60].split())
        return trozo[:MAX_EVIDENCIA]


def _vista(doc: Doc) -> _Vista:
    trozos: list[str] = []
    limites: list[int] = []
    pos = 0
    for p in doc.paginas:
        t = "" if p.sin_texto else p.texto
        trozos.append(t)
        pos += len(t) + 1
        limites.append(pos)
    original = "\n".join(trozos)
    return _Vista(doc.nombre, original, _plegar(original), len(doc.paginas), limites)


_ENCABEZADO_CORREO = re.compile(
    r"desde\s+(.{1,200}?)\s*<([^>\s]+(?:@|[o0©]\s)[^>\s]*\.[^>\s]+)>\s*fecha\b"
)
_DOMINIO_JUZGADO = "cendoj.ramajudicial.gov.co"
_CITADO = re.compile(r"\b(?:de|from):\s*(.{1,120}?)<([^>\s]+@[^>\s]+)>")
_IMPUG = re.compile(r"impugn|apelaci")


def _es_juzgado(remitente: str, direccion: str) -> bool:
    return _DOMINIO_JUZGADO in direccion or remitente.strip().startswith("juzgado")


def _clasificar_correo(v: _Vista, m: re.Match) -> tuple[Rol, str]:
    asunto = v.f[: m.start()]
    cuerpo_ini = m.end()
    resto = v.f[cuerpo_ini : cuerpo_ini + 2500]
    de_juzgado = _es_juzgado(m.group(1), m.group(2))
    cita_encabezado = v.cita(m)
    if de_juzgado:
        for q in _CITADO.finditer(v.f, cuerpo_ini, cuerpo_ini + 4000):
            if _DOMINIO_JUZGADO in q.group(2):
                continue
            tras = _IMPUG.search(v.f, q.end(), q.end() + 1500)
            if tras:
                return "impugnacion", v.cita(tras)
        if re.search(r"notific|concede|comunic|traslado", asunto):
            return "notificacion", cita_encabezado
        if _IMPUG.search(asunto) and re.search(
            r"ampliaci|argumentos|escrito|memorial|sustentaci", asunto
        ):
            return "impugnacion", cita_encabezado
        if re.search(
            r"\bauto\b|fallo|sentencia|admi[st]|avoca|vincula|requerimiento|oficio|requiere",
            asunto,
        ):
            return "notificacion", cita_encabezado
        return "correo", cita_encabezado
    if _IMPUG.search(asunto) and not re.search(r"contest|respuesta", asunto):
        return "impugnacion", cita_encabezado
    sustento = re.search(
        r"(?:interpongo|presento|formulo|sustento|impugno)\b.{0,60}(?:impugnaci|apelaci|recurso)|(?:impugnaci\w+|apelaci\w+)\s+(?:de|del|contra|al|a)\s+(?:el\s+|la\s+)?(?:fallo|sentencia)",
        resto[:900],
    )
    if sustento and not re.search(r"contest|respuesta|descargos", asunto):
        return "impugnacion", " ".join(
            v.original[
                cuerpo_ini + sustento.start() : cuerpo_ini + sustento.end() + 40
            ].split()
        )[:MAX_EVIDENCIA]
    if re.search(r"contest|respuesta|descargos|informe", asunto):
        return "contestacion", cita_encabezado
    return "correo", cita_encabezado


_SALUDO = re.compile(
    r"\b(?:senor(?:es|a|as)?|honorable|doctor(?:a)?|respetado(?:s)?)\b[^.\n]{0,60}\b(?:juez|jueza|juzgado|magistrad\w+)\b|\be\.?\s?s\.?\s?(?:d|h)\b"
)


_INICIO_JUZGADO = re.compile(
    r"\s*(?:constancia|rad\.\s*no|juzgado|auto\s+n|rama\s+judicial)"
)


def _externo(v: _Vista) -> re.Match | None:
    if _INICIO_JUZGADO.match(v.f):
        return None
    return _SALUDO.search(v.f, 0, ENCABEZADO)


def _acta(v: _Vista) -> tuple[Rol, str] | None:
    fin = v.limites[0] if v.limites else 1200
    m = v.buscar(r"acta\s+individual\s+de\s+reparto", fin)
    if not m:
        return None
    clase = v.buscar(r"impugnaci\w*\s+tutela", fin)
    cui = v.buscar(r"(?<!\d)\d{21}01(?!\d)", fin)
    prueba = clase or cui
    return ("acta_reparto_2a" if prueba else "acta_reparto_1a"), v.cita(prueba or m)


def _sentencia(v: _Vista) -> re.Match | None:
    if len(v.original) < MIN_CHARS_FALLO or _externo(v) or not v.buscar(r"tutela"):
        return None
    grupos = (
        r"antecedentes|identidad\s+de\s+las\s+partes|\bhechos\b|pretensiones",
        r"consideraciones|problema\s+juridico|competencia|marco\s+normativo",
        r"\bresuelve\b|\bfalla\b|\bdecision\b|\bconceder\b|\btutelar\b|\bniega\b|improcedente",
    )
    if not (v.buscar(grupos[0]) and v.buscar(grupos[1])):
        return None
    return v.buscar(grupos[2])


def _paginas_auto(v: _Vista) -> int:
    m = v.buscar(r"notifiquese")
    if not m or not v.limites:
        return v.npag
    return min(v.npag, bisect_right(v.limites, m.start()) + 1)


def _concede(v: _Vista) -> re.Match | None:
    if _paginas_auto(v) > MAX_PAGINAS_AUTO or _externo(v):
        return None
    return v.buscar(
        r"conced\w+[\s,]+(?:[\w,]+\s+){0,6}?(?:impugnaci|apelaci|recurso)|(?:impugnaci|apelaci)\w*.{0,400}?\bse\s+concede\b",
        6000,
    )


def _auto_inicial(v: _Vista) -> tuple[Rol, str] | None:
    if (
        _paginas_auto(v) > MAX_PAGINAS_AUTO
        or _externo(v)
        or not v.buscar(r"juzgado|despacho")
    ):
        return None
    if m := v.buscar(
        r"\bse\s+inadmite\b|\binadmitase\b|\binadmite\b|\binadmitir\b|\brechaza\b"
    ):
        return "otro", v.cita(m)
    if m := v.buscar(
        r"\bse\s+admite\b|\badmitase\b|\badmite\b|\badmitir\b|\bavocase\b|\bse\s+avoca\b|\bavoca\b|\bavocar\b|\bse\s+asume\b|\basume\s+(?:el\s+)?conocimiento|\basumir\s+el\s+conocimiento|dispone\s+(?:la\s+)?tramitaci"
    ):
        if v.buscar(r"tutela"):
            return "auto_admisorio", v.cita(m)
    if m := v.buscar(
        r"ordena\w*\s+la\s+vinculacion|vinculese|\bse\s+vincula\b|vinculacion\s+a\s+la\s+litis|vincular\s+a\b"
    ):
        return "auto_vinculacion", v.cita(m)
    return None


def _impugnacion_escrito(v: _Vista) -> re.Match | None:
    if not _externo(v):
        return None
    return v.buscar(
        r"^\W*(?:accion\s+de\s+tutela\s+)?(?:escrito\s+de\s+|memorial\s+de\s+)?(?:impugnaci|apelaci)"
        r"|(?:ref\w*|asunto)\W.{0,250}?(?:impugnaci|apelaci)"
        r"|(?:impugnaci|apelaci)\w*\s+(?:\w+\s+){0,2}(?:fallo|sentencia)"
        r"|interpongo\s+(?:recurso\s+de\s+)?(?:impugnaci|apelaci)",
        ENCABEZADO,
    )


_RADICADO = re.compile(r"(?<!\d)(?:\d[ \-]?){20,22}\d(?!\d)")


def _escrito_tutela(v: _Vista) -> re.Match | None:
    if re.search(
        r"contestaci|contesta\b|descargos|informe|da\s+respuesta|dar\s+respuesta|impugn",
        v.f[:700],
    ) or _RADICADO.search(v.original[:ENCABEZADO]):
        return None
    titulo = v.buscar(
        r"accion\s+de\s+tutela|accion\s+constitucional\s+de\s+tutela|amparo\s+constitucional",
        ENCABEZADO,
    )
    if not titulo:
        return None
    if v.buscar(r"\(?\s*reparto\s*\)?", ENCABEZADO) or (
        v.buscar(r"\bhechos\b", 8000)
        and v.buscar(
            r"pretension|solicito|pido\s+(?:al|a\s+su)|petitum|juramento", 12000
        )
    ):
        return titulo
    return None


_PISTAS_NOMBRE: tuple[tuple[str, Rol], ...] = (
    (r"actareparto", "acta_reparto_1a"),
    (r"escritotutela|demandatutela", "escrito_tutela"),
    (r"concede", "auto_concede_impugnacion"),
    (r"impugn|apelaci", "impugnacion"),
    (r"inadmi", "otro"),
    (r"admi|avoca", "auto_admisorio"),
    (r"vincula", "auto_vinculacion"),
    (r"fallo|sentencia", "fallo_a_quo"),
    (r"notifica", "notificacion"),
    (r"respuesta|contestacion", "contestacion"),
    (r"indice", "indice"),
)


def _por_nombre(nombre: str) -> tuple[Rol, str] | None:
    n = re.sub(r"[^a-z0-9]", "", plano(nombre.rsplit(".", 1)[0]))
    for patron, rol in _PISTAS_NOMBRE:
        if re.search(patron, n):
            if rol == "acta_reparto_1a" and re.search(
                r"impugn|segunda|cto|circuito", n
            ):
                rol = "acta_reparto_2a"
            return rol, f"Nombre del archivo: {nombre}"[:MAX_EVIDENCIA]
    return None


def clasificar(doc: Doc) -> tuple[Rol, str]:
    v = _vista(doc)
    if not v.original.strip():
        return _por_nombre(doc.nombre) or ("otro", EVIDENCIA_SIN_TEXTO)
    if (r := _acta(v)) is not None:
        return r
    if v.buscar(r"indice\s+del\s+expediente|indice\s+electronico", 700):
        return "indice", v.cita(
            v.buscar(r"indice\s+(?:del\s+expediente|electronico)", 700)
        )
    m = _ENCABEZADO_CORREO.search(v.f, 0, 1500)
    if m:
        return _clasificar_correo(v, m)
    if re.search(
        r"outlook|bandeja\s+de\s+entrada|elementos\s+enviados|gmail\s+-", v.f[:500]
    ):
        asunto = v.f[: max(v.f.find("desde"), 0) or 500]
        if (
            _IMPUG.search(asunto)
            and not re.search(r"contest|respuesta", asunto)
            and _DOMINIO_JUZGADO not in v.f[:900]
        ):
            return "impugnacion", v.cita(_IMPUG.search(asunto))
        return ("notificacion" if "notific" in v.f[:900] else "correo"), v.cita(
            re.search(
                r"outlook|bandeja\s+de\s+entrada|elementos\s+enviados|gmail\s+-",
                v.f[:500],
            )
        )
    if (m := _impugnacion_escrito(v)) is not None:
        return "impugnacion", v.cita(m)
    if (m := _concede(v)) is not None:
        return "auto_concede_impugnacion", v.cita(m)
    if (m := _sentencia(v)) is not None:
        return "fallo_a_quo", v.cita(m)
    if (r := _auto_inicial(v)) is not None:
        if r[0] in ("auto_admisorio", "auto_vinculacion"):
            pista = _por_nombre(doc.nombre)
            if pista and pista[0] in ("auto_admisorio", "auto_vinculacion"):
                return pista[0], r[1]
        return r
    if (m := _escrito_tutela(v)) is not None:
        return "escrito_tutela", v.cita(m)
    if (
        m := v.buscar(r"contestaci\w+|\brespuesta\b|descargos|rinde\s+informe", 700)
    ) is not None and _externo(v):
        return "contestacion", v.cita(m)
    if (m := v.buscar(r"\bmemorial\b", ENCABEZADO)) is not None:
        return "memorial", v.cita(m)
    return "otro", EVIDENCIA_SIN_ROL


def texto_cabecera(d: Doc) -> str:
    if d.nombre.lower().endswith(".docx"):
        return "\n".join(p.texto for p in d.paginas)[:CABECERA_DOCX]
    return "\n".join(p.texto for p in d.paginas[:2])


def _cabecera_cuis(d: Doc) -> list[str]:
    return list(Counter(extraer_cuis(texto_cabecera(d))))


def resolver_caso(docs: list[Doc], prefijo: str | None) -> None:
    fallos = [d for d in docs if d.rol == "fallo_a_quo"]
    if prefijo is not None:
        for d in fallos:
            cuis = _cabecera_cuis(d)
            cabecera = texto_cabecera(d)
            if (
                cuis
                and not any(c.startswith(prefijo) for c in cuis)
                and not menciona_radicado(cabecera, prefijo)
            ):
                d.rol, d.evidencia = (
                    "otro",
                    f"Sentencia de otro radicado ({', '.join(cuis)})."[:MAX_EVIDENCIA],
                )
    fallos = [d for d in docs if d.rol == "fallo_a_quo"]
    if len(fallos) > 1:

        def propio(d: Doc) -> tuple[bool, bool, bool, int]:
            cabeza = plano(texto_cabecera(d)[:1500])
            circuito = re.search(r"penal\s+del\s+circuito|juzgado[^.\n]{0,40}circuito", cabeza)
            return (
                prefijo is not None
                and any(c.startswith(prefijo) for c in _cabecera_cuis(d)),
                circuito is None,
                re.search(r"penal\s+municipal", cabeza) is not None,
                len(d.paginas),
            )

        elegido = max(fallos, key=propio)
        for d in fallos:
            if d is not elegido:
                d.rol, d.evidencia = (
                    "otro",
                    f"Otra sentencia del mismo caso; se conserva {elegido.doc_id} como fallo de 1.ª instancia."[
                        :MAX_EVIDENCIA
                    ],
                )
    actas = [d for d in docs if d.rol == "acta_reparto_2a"]
    for d in actas[:-1]:
        d.rol, d.evidencia = (
            "otro",
            f"Acta de impugnación anterior a {actas[-1].doc_id}; la última es la vigente."[
                :MAX_EVIDENCIA
            ],
        )
