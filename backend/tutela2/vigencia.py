"""Certificado de vigencia de la tarjeta profesional (Rama Judicial, URNA).

Lee y clasifica el PDF del certificado ("Certificado de vigencia RNA-TPA"), extrae los campos
ocultos del formulario público y, con ``COLA``, consulta el certificado de forma automática.

Regla de fondo: ante cualquier duda se falla cerrado. Un certificado que no se pueda leer
entero da ``None`` (o ``ilegible`` al clasificar) y jamás se interpreta como vigente; solo la
palabra exacta ``VIGENTE`` en el estado de la tarjeta, sin observaciones, da ``vigente``.

Para una cédula que no es de un abogado inscrito, la Rama Judicial expide otro certificado, sin
tablas ni nombre: «la persona identificada con Cédula de Ciudadanía N.° …, NO ESTÁ INSCRITA en la
Unidad de Registro Nacional de Abogados…». Se lee con ``inscrito=False`` y da ``no_inscrito``.
Los registros y mensajes de este módulo nunca llevan un número de cédula, ni los nombres de los
archivos que escribe.

La consulta automática (``ColaVigencia``) es un solo hilo para todo el proceso, fuera de los
trabajos y del grafo, así que nunca bloquea un caso. Solo sale el número de cédula y solo hacia
``URL_VIGENCIA``: cada consulta es un GET del formulario seguido enseguida de su POST con exactamente
los siete campos de ``formulario``. La página está detrás de varios servidores (Azure App Gateway): el
POST lleva de vuelta las dos cookies de afinidad que puso su GET (``ApplicationGatewayAffinity`` y
``ApplicationGatewayAffinityCORS``), que no tienen datos personales, para llegar al mismo servidor; no hay
sesión ni inicio de sesión. En la consulta directa ninguna otra cookie sale (un frasco nuevo por consulta);
desde la extensión, el navegador envía además las cookies que tenga de la Rama Judicial, pero ninguna de
otros sitios. Entre dos consultas a la Rama Judicial pasan al
menos ``PAUSA_S``; si no responde (error 5xx, una página en vez del PDF o sin respuesta) la cola entera
espera ``ENFRIAMIENTO_S`` y
cada cédula se intenta sola a lo sumo ``MAX_AUTO_DIA`` veces al día. Los certificados obtenidos se
guardan un día en la caché (``CacheVigencias``) y en el registro de cada caso que los espera, igual
que un certificado subido a mano. Con la consulta ``apagada`` (lo predeterminado) nada se pone en
cola ni sale.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import http.cookiejar
import json
import logging
import os
import re
import tempfile
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Literal, NamedTuple, Protocol

from pydantic import BaseModel, ValidationError

from tutela2 import config as cfgmod
from tutela2 import ingest

if TYPE_CHECKING:
    from tutela2.models import Apoderado
    from tutela2.registro_apoderados import ConsultaVigencia, Registro

log = logging.getLogger("tutela2")

URL_VIGENCIA = "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx"
CAMPOS_OCULTOS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")

ESTADO_VIGENTE = "VIGENTE"
SIN_OBSERVACIONES = "NO REGISTRA"
CEDULA_MIN_DIGITOS = 5
CEDULA_MAX_DIGITOS = 10
MAX_OBSERVACIONES = 1500

EstadoCertificado = Literal["vigente", "vigente_obs", "no_vigente", "no_inscrito", "otra_persona", "ilegible"]


class CertificadoVigencia(BaseModel):
    """Datos leídos del certificado. Todo es texto tal como figura, salvo ``documento``
    (solo dígitos) y ``codigo_verificacion`` (hexadecimal en minúscula).

    ``inscrito`` es ``False`` en el certificado de una cédula que no está inscrita como abogado(a):
    ese certificado no trae nombre (``nombre`` es ``None``) ni las tablas de la inscripción y la tarjeta."""

    inscrito: bool = True
    numero: str | None = None
    nombre: str | None = None
    documento: str | None = None
    rna_estado: str | None = None
    tpa_numero: str | None = None
    tpa_fecha: str | None = None
    tpa_estado: str | None = None
    tpa_observaciones: str | None = None
    rna_observaciones: str | None = None
    expedido: str | None = None
    codigo_verificacion: str | None = None


class _Ocultos(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.valores: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        a = {k.lower(): v for k, v in attrs}
        nombre = a.get("name")
        if (a.get("type") or "").strip().lower() != "hidden" or nombre not in CAMPOS_OCULTOS:
            return
        valor = a.get("value") or ""
        if valor and nombre not in self.valores:
            self.valores[nombre] = valor


def campos_ocultos(html: str) -> dict[str, str] | None:
    """Los tres campos ocultos de ASP.NET que exige el formulario, o ``None`` si falta alguno.

    Admite cualquier orden de atributos, comillas simples o dobles y entidades HTML; un campo
    vacío cuenta como ausente."""
    p = _Ocultos()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return None
    if all(c in p.valores for c in CAMPOS_OCULTOS):
        return {c: p.valores[c] for c in CAMPOS_OCULTOS}
    return None


_FILA_ESTADO = r"[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ()./-]*(?: [A-ZÁÉÍÓÚÜÑ()./-]+){0,3}"
_FECHA = r"\d{2}/\d{2}/\d{4}"

_RE_NUMERO = re.compile(r"CERTIFICADO N\s?\.?\s?[°º]?\s?:?\s?(\d{1,12})(?!\d)")
_RE_PERSONA = re.compile(
    r"se[ñn]or(?:\(a\)|a)? (?P<nombre>[^,]{3,120}?), quien se identifica con "
    r"(?P<tipo>[A-ZÁÉÍÓÚÑ ]{3,40}?) N\s?\.?\s?[°º]? ?(?P<doc>[\d.]{3,20})",
    re.IGNORECASE,
)
_RE_NO_INSCRITA = re.compile(
    r"la persona identificada con (?P<tipo>[A-ZÁÉÍÓÚÑ ]{3,40}?) N\s?\.?\s?[°º]? ?(?P<doc>[\d.]{1,20}) ?, ?"
    r"NO EST[AÁ] INSCRIT(?:[AO]|O\(A\)) en la Unidad (?:del? )?Registro Nacional de Abogados"
    r" y Auxiliares de la Justicia como abogado",
    re.IGNORECASE,
)
_RE_SECCION_RNA = re.compile(r"VIGENCIA RNA")
_RE_SECCION_TPA = re.compile(r"VIGENCIA TPA")
_RE_FIN_SECCION = re.compile(
    r"VIGENCIA (?:RNA|TPA)|La presente|_{3,}|Firmado Por|Este documento fue generado"
    r"|C[óo]digo de verificaci[óo]n"
)
_RE_OBSERVACIONES = re.compile(r"\bOBSERVACIONES\b")
_RE_FILA_TPA = re.compile(
    rf"(?<![\d/])(?P<tp>\d{{3,7}}) (?P<fecha>{_FECHA}) (?P<estado>{_FILA_ESTADO})(?: \d)?$"
)
_RE_FILA_RNA = re.compile(rf"(?P<fecha>{_FECHA}) (?P<estado>{_FILA_ESTADO})(?: \d)?$")
_RE_CODIGO = re.compile(
    r"C[óo]digo de verificaci[óo]n:? ?((?:[0-9a-fA-F] ?){64})(?![0-9a-fA-F])"
)
_RE_EXPEDIDO = re.compile(
    rf"Documento generado en ({_FECHA} \d{{1,2}}:\d{{2}}:\d{{2}}(?: [AaPp]\.? ?[Mm]\.?)?)"
)
# Palabras de los encabezados de la tabla que, según el extractor, pueden quedar pegadas a
# la fila de datos; nunca forman parte de un estado.
_ENCABEZADOS = {"PROFESIONAL", "CALIDAD", "ESTADO", "TARJETA", "FECHA", "EXPEDICIÓN", "INSCRIPCIÓN"}
# Vocabulario de la tabla que tampoco forma parte de un estado: si queda dentro de uno después de
# quitar los encabezados de los bordes, el extractor mezcló las celdas y el estado no se lee.
_VOCABULARIO_TABLA = _ENCABEZADOS | {
    "DE", "DEL", "LA", "EL", "N", "N.", "NO.", "NRO", "NRO.", "TPA", "RNA", "CON", "ABOGADO(A)", "INSCRITO(A)", "OBSERVACIONES",
}


def _colapsar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto).replace("​", "").replace("\xad", "")
    return re.sub(r"\s+", " ", texto).strip()


def _plegar(texto: str) -> list[str]:
    """Palabras en minúscula y sin tildes (la Ñ pasa a N)."""
    s = unicodedata.normalize("NFKD", texto)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", s)


def solo_digitos(texto: str | None) -> str:
    """Los dígitos del texto, escritos con 0-9. Un dígito de otra escritura (de ancho completo, arábigo…) se
    cambia por el suyo, así que el número no cambia (quitarlo daría otra cédula, quizá de otra persona) y
    solo sale lo que admite la lista blanca del formulario."""
    return "".join(str(unicodedata.decimal(c)) for c in texto or "" if c.isdecimal())


def _seccion(texto: str, inicio: int) -> str:
    fin = _RE_FIN_SECCION.search(texto, inicio)
    return texto[inicio : fin.start() if fin else len(texto)].strip()


def _estado_limpio(crudo: str) -> str:
    palabras = crudo.split()
    while palabras and palabras[-1] in _ENCABEZADOS:
        palabras.pop()
    while palabras and palabras[0] in _ENCABEZADOS:
        palabras.pop(0)
    return " ".join(palabras)


def _estado(crudo: str) -> str | None:
    """El estado de una fila sin los encabezados pegados a los bordes, o ``None`` si no se lee con certeza:
    queda vocabulario de la tabla dentro, o menciona VIGENTE sin ser exactamente «VIGENTE» o «NO VIGENTE».

    Así un encabezado intercalado por el extractor ("VIGENTE DE", "VIGENTE FECHA DE") da un
    certificado ilegible (ámbar) y nunca un estado distinto de VIGENTE (rojo)."""
    estado = _estado_limpio(crudo)
    palabras = estado.split()
    if not palabras or any(p in _VOCABULARIO_TABLA for p in palabras):
        return None
    if ESTADO_VIGENTE in estado and estado not in (ESTADO_VIGENTE, f"NO {ESTADO_VIGENTE}"):
        return None
    return estado


def _partir_observaciones(seccion: str) -> tuple[str, str | None]:
    """(texto antes de OBSERVACIONES, texto de las observaciones o ``None`` si no hay rótulo)."""
    m = _RE_OBSERVACIONES.search(seccion)
    if not m:
        return seccion, None
    return seccion[: m.start()].strip(), seccion[m.end() :].strip()[:MAX_OBSERVACIONES] or None


def leer_texto(texto: str) -> CertificadoVigencia | None:
    """Interpreta el texto del certificado (de ``pdftotext -layout`` o de pypdf).

    Tolera saltos de línea dentro de un valor, espacios de más y los números de nota al pie
    que siguen a algunos encabezados. Devuelve ``None`` si no se puede leer con certeza la
    persona y el estado, o si hay una sección de vigencia de la tarjeta que no se logra leer."""
    t = _colapsar(texto)
    if not t:
        return None

    persona = _RE_PERSONA.search(t)
    no_inscrita = _RE_NO_INSCRITA.search(t)
    if no_inscrita:
        # Un certificado con titular y tablas que además diga que no está inscrita no se entiende: se descarta.
        return None if persona else _leer_no_inscrita(t, no_inscrita)
    if not persona:
        return None
    if _plegar(persona["tipo"]) != ["cedula", "de", "ciudadania"]:
        return None
    documento = solo_digitos(persona["doc"])
    if not CEDULA_MIN_DIGITOS <= len(documento) <= CEDULA_MAX_DIGITOS:
        return None

    cert = CertificadoVigencia(documento=documento, nombre=persona["nombre"].strip())
    _datos_del_documento(t, cert)

    rna = _RE_SECCION_RNA.search(t)
    if rna:
        previo, obs = _partir_observaciones(_seccion(t, rna.end()))
        fila = _RE_FILA_RNA.search(previo)
        if fila and (estado := _estado(fila["estado"])) is not None:
            cert.rna_estado = estado
            cert.rna_observaciones = obs

    tpa = _RE_SECCION_TPA.search(t)
    if tpa:
        previo, obs = _partir_observaciones(_seccion(t, tpa.end()))
        fila = _RE_FILA_TPA.search(previo)
        estado = _estado(fila["estado"]) if fila else None
        if estado is None:
            return None
        cert.tpa_numero = fila["tp"]
        cert.tpa_fecha = fila["fecha"]
        cert.tpa_estado = estado
        cert.tpa_observaciones = obs

    if cert.rna_estado is None and cert.tpa_estado is None:
        return None
    return cert


def _datos_del_documento(t: str, cert: CertificadoVigencia) -> None:
    if m := _RE_NUMERO.search(t):
        cert.numero = m.group(1)
    if m := _RE_CODIGO.search(t):
        cert.codigo_verificacion = m.group(1).replace(" ", "").lower()
    if m := _RE_EXPEDIDO.search(t):
        cert.expedido = m.group(1)


def _leer_no_inscrita(t: str, m: re.Match[str]) -> CertificadoVigencia | None:
    """El certificado de una cédula que no está inscrita como abogado(a): sin nombre ni tablas. ``None``
    si no es de una cédula de ciudadanía con 5 a 10 dígitos o si trae alguna tabla de vigencia."""
    if _plegar(m["tipo"]) != ["cedula", "de", "ciudadania"]:
        return None
    documento = solo_digitos(m["doc"])
    if not CEDULA_MIN_DIGITOS <= len(documento) <= CEDULA_MAX_DIGITOS:
        return None
    if _RE_SECCION_RNA.search(t) or _RE_SECCION_TPA.search(t):
        return None
    cert = CertificadoVigencia(inscrito=False, documento=documento)
    _datos_del_documento(t, cert)
    return cert


def leer_certificado(pdf: bytes) -> CertificadoVigencia | None:
    """Lee el PDF del certificado (descifrando la clave de usuario vacía si la hay).

    El texto sale de ``ingest._textos_pdf``: ``pdftotext -layout`` si está instalado y, si no,
    pypdf (que necesita ``cryptography`` para el AES-256 del certificado). ``None`` si los bytes
    no son un PDF, no se puede extraer el texto o el contenido no se entiende por completo."""
    if not pdf.startswith(b"%PDF-"):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="vigencia-") as tmp:
            ruta = Path(tmp) / "certificado.pdf"
            ruta.write_bytes(pdf)
            paginas = ingest._textos_pdf(ruta)
    except Exception as e:
        log.warning("no se pudo extraer el texto del certificado de vigencia (%s)", type(e).__name__)
        return None
    return leer_texto("\n".join(paginas))


def _mismo_nombre(a: str, b: str) -> bool:
    """Los nombres coinciden si las palabras del más corto están todas en el más largo
    (sin tildes ni mayúsculas, en cualquier orden)."""
    x, y = set(_plegar(a)), set(_plegar(b))
    if not x or not y:
        return False
    return x <= y or y <= x


def a_nombre_de(cert: CertificadoVigencia, nombre: str | None) -> bool:
    """El certificado está a nombre de ``nombre`` (las palabras del más corto están todas en el
    más largo, sin tildes ni mayúsculas). Sin un nombre con que comparar no se descarta.

    No sirve para el certificado de una cédula no inscrita (``inscrito=False``), que no trae nombre:
    da ``False`` y quien lo llama debe resolver ese caso antes, solo por la cédula."""
    if not nombre or not _plegar(nombre):
        return True
    return bool(cert.nombre) and _mismo_nombre(cert.nombre, nombre)


def _sin_observaciones(obs: str | None) -> bool:
    return obs is not None and _plegar(obs) == _plegar(SIN_OBSERVACIONES)


def clasificar(
    cert: CertificadoVigencia | None,
    cedula_pedida: str,
    nombre_esperado: str | None = None,
) -> EstadoCertificado:
    """Qué dice el certificado sobre la persona que se consultó.

    - ``ilegible``: no hay certificado, la cédula no coincide o el estado no se puede concluir.
    - ``no_inscrito``: la cédula coincide y el certificado dice que no está inscrita como abogado(a).
      Ese certificado no trae nombre, así que el nombre no se compara (nunca da ``otra_persona``).
    - ``otra_persona``: la cédula coincide pero el nombre no (cédula mal leída o mal emparejada).
    - ``no_vigente``: la tarjeta figura con un estado distinto de ``VIGENTE``, o no hay fila
      de tarjeta y la inscripción en el RNA no está vigente.
    - ``vigente_obs``: ``VIGENTE`` pero con alguna observación o sin poder confirmar la
      inscripción en el RNA.
    - ``vigente``: ``VIGENTE`` en la tarjeta y en el RNA, sin observaciones en ninguna.

    ``cedula_pedida`` admite puntos y espacios. Sin ``nombre_esperado`` no se compara el nombre."""
    if cert is None or not cert.documento:
        return "ilegible"
    pedida = solo_digitos(cedula_pedida)
    if not pedida or pedida != cert.documento:
        return "ilegible"
    if not cert.inscrito:
        return "no_inscrito"
    if not a_nombre_de(cert, nombre_esperado):
        return "otra_persona"

    if cert.tpa_estado is None:
        if cert.rna_estado is not None and cert.rna_estado != ESTADO_VIGENTE:
            return "no_vigente"
        return "ilegible"
    if cert.tpa_estado != ESTADO_VIGENTE:
        return "no_vigente"
    if (
        cert.rna_estado == ESTADO_VIGENTE
        and _sin_observaciones(cert.tpa_observaciones)
        and _sin_observaciones(cert.rna_observaciones)
    ):
        return "vigente"
    return "vigente_obs"


# ------------------------------------------------------------ nombres de archivo


def id_en_archivo(ap_id: str) -> str:
    """El id del apoderado apto para un nombre de archivo: solo minúsculas, dígitos y guiones."""
    return re.sub(r"[^a-z0-9-]", "", ap_id.lower())[:64] or "ap"


def nombre_certificado(ap_id: str, sha256: str) -> str:
    """``<id del apoderado>-<sha256[:16]>.pdf``: el nombre de un certificado guardado en el caso, que
    nunca lleva la cédula. Lo usan la subida manual y la consulta automática."""
    return f"{id_en_archivo(ap_id)}-{sha256[:16]}.pdf"


# ------------------------------------------------------------ consulta automática

ModoConsulta = Literal["extension", "directa", "fake", "apagada"]
MODOS_AUTOMATICOS = ("extension", "directa", "fake")
MODOS_REGISTRO = ("extension", "directa")
"""Los modos que llegan a la Rama Judicial: solo a ellos se aplican la pausa, el enfriamiento, la caché y el
tope de intentos del día (la consulta simulada no le pide nada a nadie: cada caso de prueba la repite)."""

PAUSA_S = 30.0
"""Tiempo mínimo entre dos consultas (GET y su POST) a la Rama Judicial, de todo el proceso. El POST sale
enseguida de su GET: lo que se espera es entre el último pedido de una consulta y el GET de la siguiente."""
ENFRIAMIENTO_S = 15 * 60.0
"""Pausa de toda la cola tras un error 5xx, una página en vez del PDF o la falta de respuesta."""
MAX_AUTO_DIA = 3
"""Intentos automáticos por cédula y día (UTC); ``forzar`` no lo tiene en cuenta."""
TTL_S = 24 * 3600.0
"""Vigencia de un certificado en la caché."""
ESPERA_EXTENSION_S = 75.0
"""Espera de cada pedido a la extensión: más que los 60 s en que ella aborta, menos que su cierre por silencio."""
TIMEOUT_DIRECTA_S = 60.0
REVISION_ESTACIONADOS_S = 60.0
"""Cada cuánto se vuelve a mirar si hay extensión cuando solo quedan pedidos que la esperan (además del aviso al conectar)."""
MAX_BYTES_PDF = 2 * 1024 * 1024

CAMPOS_FIJOS = {"ddlCalidad": "1", "ddlTipoDocumento": "1", "btnTpVigente": "Generar"}
"""Abogado (calidad 1), cédula de ciudadanía (tipo 1) y el botón de la tarjeta vigente; nada más sale."""

SIN_RESPUESTA = "La Rama Judicial no respondió a la consulta del certificado de vigencia."
SIN_CERTIFICADO = "La Rama Judicial respondió sin el certificado de vigencia."
SIN_FORMULARIO = "La página de la Rama Judicial no trae el formulario esperado."
FORMULARIO_RECHAZADO = "El formulario de la Rama Judicial cambió y la consulta no se envió."
DETALLES = {
    "extension": "Consulta automática en la Rama Judicial desde la extensión del navegador.",
    "directa": "Consulta automática en la Rama Judicial desde el servidor.",
    "fake": "Consulta simulada (modo de prueba): el certificado es ficticio.",
}

FaseCola = Literal["en_cola", "consultando"]
EstadoConexion = Literal["conectada", "desactualizada", "no_conectada"]

# Clave del proceso para nombrar una cédula en los registros sin escribirla: no se puede revertir
# con solo el registro (una cédula tiene pocos dígitos y un hash sin clave se recorrería entero).
_CLAVE_REGISTRO = os.urandom(16)


def referencia(cedula: str) -> str:
    """Seudónimo corto de una cédula para los registros, estable mientras dure el proceso."""
    return hmac.new(_CLAVE_REGISTRO, solo_digitos(cedula).encode(), "sha256").hexdigest()[:8]


def cedula_valida(cedula: str | None) -> bool:
    """Solo dígitos ASCII, de 5 a 10: lo único que admite el campo ``txtDocumento`` de la lista blanca."""
    cedula = cedula or ""
    return cedula.isascii() and cedula.isdigit() and CEDULA_MIN_DIGITOS <= len(cedula) <= CEDULA_MAX_DIGITOS


def formulario(campos: dict[str, str], cedula: str) -> dict[str, str]:
    """Los siete campos del POST: los tres ocultos del formulario, los fijos y la cédula (5 a 10 dígitos)."""
    if not cedula_valida(cedula):
        raise ValueError("La cédula para consultar debe tener entre 5 y 10 dígitos.")
    return {**{c: campos[c] for c in CAMPOS_OCULTOS}, **CAMPOS_FIJOS, "txtDocumento": cedula}


def modo_consulta(caso_dir: Path) -> ModoConsulta:
    """El modo de consulta del caso (``config.cargar`` con el entorno); si no se puede leer, apagada."""
    try:
        return cfgmod.cargar(caso_dir).apoderados.consulta
    except Exception as e:
        log.warning(
            "%s: no se pudo leer la configuración (%s); la consulta automática queda apagada",
            Path(caso_dir).name,
            type(e).__name__,
        )
        return "apagada"


def _estado_extension() -> EstadoConexion:
    from tutela2 import extension

    return extension.estado_conexion()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _epoca(iso: str | None) -> float:
    try:
        fecha = datetime.fromisoformat(iso or "")
    except ValueError:
        return 0.0
    return (fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)).timestamp()


def _dia(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


class Titular(NamedTuple):
    """El abogado que el caso espera en el certificado (solo lo usa la consulta simulada)."""

    nombre: str
    tarjeta: str | None = None


class Resultado(NamedTuple):
    """Lo que obtuvo un cliente: ``ok`` con el PDF, o por qué no."""

    estado: Literal["ok", "no_conectada", "desactualizada", "inaccesible"]
    pdf: bytes | None = None
    detalle: str = ""


class ClienteVigencia(Protocol):
    def consultar(self, cedula: str, titular: Titular | None = None) -> Resultado: ...


class _Respuesta(NamedTuple):
    estado: Literal["ok", "no_conectada", "desactualizada", "inaccesible"]
    cuerpo: bytes = b""
    codigo: int | None = None
    tipo: str | None = None
    detalle: str = ""


def _es_pdf(r: _Respuesta) -> bool:
    tipo = (r.tipo or "").split(";")[0].strip().lower()
    return r.cuerpo.startswith(b"%PDF-") and len(r.cuerpo) <= MAX_BYTES_PDF and (not tipo or tipo == "application/pdf")


def _http(codigo: int | None) -> str:
    return f"La Rama Judicial respondió con un error (HTTP {codigo})." if codigo else SIN_RESPUESTA


class _ClienteRegistro:
    """Consulta en la Rama Judicial: cada vez un GET del formulario y, enseguida, el POST con los siete
    campos y las cookies de afinidad que puso ese GET. Antes del GET llama a ``turno``, que espera lo que
    haga falta para respetar ``PAUSA_S`` entre consultas; antes del POST lo llama con ``esperar=False``:
    sin esperar, solo vuelve a comprobar que algún caso todavía necesite la cédula. Los campos ocultos no
    se guardan de una consulta a otra, y una página en vez del PDF tras un GET recién hecho no se reintenta:
    es una falla y la cola la trata como tal (``ENFRIAMIENTO_S``)."""

    origen: str = ""

    def __init__(self, turno: Callable[..., None] | None = None, reloj: Callable[[], float] = time.time) -> None:
        self._turno = turno or (lambda esperar=True: None)
        self._reloj = reloj

    def disponible(self) -> EstadoConexion:
        return "conectada"

    def _pedir(self, metodo: Literal["GET", "POST"], campos: dict[str, str] | None) -> _Respuesta:
        raise NotImplementedError

    def consultar(self, cedula: str, titular: Titular | None = None) -> Resultado:
        if not cedula_valida(cedula):
            raise ValueError("La cédula para consultar debe tener entre 5 y 10 dígitos.")
        disponible = self.disponible()
        if disponible != "conectada":
            return Resultado(disponible)
        self._turno()
        r = self._pedir("GET", None)
        if r.estado != "ok":
            return Resultado(r.estado, None, r.detalle)
        campos = campos_ocultos(r.cuerpo.decode("utf-8", errors="replace"))
        if campos is None:
            return Resultado("inaccesible", None, SIN_FORMULARIO)
        self._turno(esperar=False)
        r = self._pedir("POST", formulario(campos, cedula))
        if r.estado != "ok":
            return Resultado(r.estado, None, r.detalle)
        if _es_pdf(r):
            return Resultado("ok", r.cuerpo, "")
        return Resultado("inaccesible", None, SIN_CERTIFICADO)


class VigenciaExtension(_ClienteRegistro):
    """La consulta sale del navegador por la extensión (1.1.0 o más nueva): la Rama Judicial solo responde a
    conexiones desde Colombia. El navegador guarda entre el GET y el POST las cookies de afinidad que pone la
    propia página de vigencia y envía con ellas las demás que tenga de la Rama Judicial, nunca las de otros
    sitios (la relatoría sigue sin cookies). A una extensión desactualizada no se le pide nada."""

    origen = "extension"

    def disponible(self) -> EstadoConexion:
        return _estado_extension()

    def _pedir(self, metodo: Literal["GET", "POST"], campos: dict[str, str] | None) -> _Respuesta:
        from tutela2 import extension

        try:
            entrega = extension.pedir(
                "vigencia", URL_VIGENCIA, metodo=metodo, formulario=campos, espera_s=ESPERA_EXTENSION_S
            )
        except extension.ExtensionNoConectada:
            return _Respuesta("no_conectada")
        except extension.ExtensionDesactualizada:
            return _Respuesta("desactualizada")
        except TimeoutError:
            return _Respuesta("inaccesible", detalle=SIN_RESPUESTA)
        except ValueError:
            # La lista blanca del servidor rechazó los campos: el formulario de la Rama Judicial cambió.
            log.warning("Vigencia: los campos del formulario no pasaron la lista blanca; no se envió nada")
            return _Respuesta("inaccesible", detalle=FORMULARIO_RECHAZADO)
        if entrega is extension.DESCONECTADA:
            # El navegador se cerró (o se durmió) con el pedido en vuelo: no es una falla de la Rama Judicial. El
            # pedido espera otra extensión sin gastar intentos ni pausar la cola.
            return _Respuesta("no_conectada")
        estado = entrega.estado
        codigo = getattr(entrega, "codigo", None)
        if estado == "ok" and codigo in (None, 200):
            return _Respuesta("ok", entrega.cuerpo or b"", codigo, getattr(entrega, "tipo", None) or None)
        if estado in ("no_conectada", "desactualizada"):
            return _Respuesta(estado)
        return _Respuesta("inaccesible", detalle=_http(codigo) if estado != "sin_respuesta" else SIN_RESPUESTA)


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """No sigue ninguna redirección: un 30x queda como error HTTP antes de contactar otra dirección (y un POST
    nunca se reenvía, ni como GET, a donde diga ``Location``)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl) -> None:  # type: ignore[override]
        return None


def _abrir(
    pedido: urllib.request.Request, timeout: float, galletas: http.cookiejar.CookieJar | None = None
) -> http.client.HTTPResponse:
    """Abre el pedido sin seguir redirecciones y, si se da ``galletas``, con ese frasco de cookies y ningún
    otro (las pruebas lo reemplazan)."""
    manejadores: list[urllib.request.BaseHandler] = [_SinRedirecciones()]
    if galletas is not None:
        manejadores.append(urllib.request.HTTPCookieProcessor(galletas))
    return urllib.request.build_opener(*manejadores).open(pedido, timeout=timeout)


class VigenciaDirecta(_ClienteRegistro):
    """La consulta sale del servidor con urllib, sin redirecciones. Solo sirve en servidores en Colombia (la
    Rama Judicial responde 403 a las demás conexiones). Antes de enviar valida el pedido con la misma lista
    blanca que la extensión (``extension.SERVICIOS``).

    Cada consulta usa un frasco de cookies nuevo, en memoria, que comparten solo su GET y su POST (para
    devolver las cookies de afinidad de la página) y que se descarta al terminar: nunca se guarda ni pasa a
    la consulta siguiente."""

    origen = "directa"

    def __init__(self, turno: Callable[..., None] | None = None, reloj: Callable[[], float] = time.time) -> None:
        super().__init__(turno, reloj)
        self._galletas: http.cookiejar.CookieJar | None = None

    def consultar(self, cedula: str, titular: Titular | None = None) -> Resultado:
        self._galletas = http.cookiejar.CookieJar()
        try:
            return super().consultar(cedula, titular)
        finally:
            self._galletas = None

    def _pedir(self, metodo: Literal["GET", "POST"], campos: dict[str, str] | None) -> _Respuesta:
        from tutela2 import extension
        from tutela2.citas import USER_AGENT

        try:
            extension._validar("vigencia", URL_VIGENCIA, metodo, campos)
        except ValueError:
            log.warning("Vigencia: los campos del formulario no pasaron la lista blanca; no se envió nada")
            return _Respuesta("inaccesible", detalle=FORMULARIO_RECHAZADO)
        cabeceras = {"User-Agent": USER_AGENT}
        cuerpo = None
        if campos is not None:
            cuerpo = urllib.parse.urlencode(campos).encode("ascii")
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        pedido = urllib.request.Request(URL_VIGENCIA, data=cuerpo, headers=cabeceras, method=metodo)
        try:
            with _abrir(pedido, TIMEOUT_DIRECTA_S, self._galletas) as r:
                final = urllib.parse.urlsplit(r.geturl() or URL_VIGENCIA)
                if (final.scheme, final.netloc, final.path) != urllib.parse.urlsplit(URL_VIGENCIA)[:3]:
                    return _Respuesta("inaccesible", detalle=SIN_CERTIFICADO)
                datos = r.read(MAX_BYTES_PDF + 1)
                return _Respuesta("ok", datos, getattr(r, "status", 200), r.headers.get("Content-Type"))
        except urllib.error.HTTPError as e:
            return _Respuesta("inaccesible", codigo=e.code, detalle=_http(e.code))
        except (OSError, http.client.HTTPException, ValueError):
            return _Respuesta("inaccesible", detalle=SIN_RESPUESTA)


class FakeVigencia:
    """Consulta simulada para el proveedor falso, sin red: según el último dígito de la cédula, 0 da
    un certificado con la tarjeta suspendida, 8 el certificado de una cédula no inscrita como abogado(a),
    9 deja la consulta sin respuesta y cualquier otro da un certificado vigente a nombre del abogado que
    espera el caso (con su T.P.)."""

    origen = "fake"

    def __init__(self, reloj: Callable[[], float] = time.time) -> None:
        self._reloj = reloj

    def consultar(self, cedula: str, titular: Titular | None = None) -> Resultado:
        if not cedula_valida(cedula):
            raise ValueError("La cédula para consultar debe tener entre 5 y 10 dígitos.")
        if cedula.endswith("9"):
            return Resultado("inaccesible", None, "Consulta simulada sin respuesta (modo de prueba).")
        fecha = datetime.fromtimestamp(self._reloj(), timezone.utc)
        if cedula.endswith("8"):
            return Resultado("ok", certificado_ficticio_no_inscrito(cedula, fecha=fecha))
        titular = titular or Titular("ABOGADO DE PRUEBA")
        pdf = certificado_ficticio(titular.nombre, cedula, titular.tarjeta, vigente=not cedula.endswith("0"), fecha=fecha)
        return Resultado("ok", pdf)


AVISO_FICTICIO = "DOCUMENTO DE PRUEBA GENERADO POR JUDICABOT SIN CONSULTAR A LA RAMA JUDICIAL. NO TIENE VALIDEZ."
_CODIGO_FICTICIO = "0" * 64


def _hora_ficticia(fecha: datetime) -> str:
    return f"{fecha:%d/%m/%Y} {fecha.hour % 12 or 12:02d}:{fecha:%M:%S} {'AM' if fecha.hour < 12 else 'PM'}"


def _texto_ficticio_no_inscrito(cedula: str, fecha: datetime) -> str:
    return "\n".join(
        [
            AVISO_FICTICIO,
            "                                       CERTIFICADO N.°: 0000000",
            "",
            "          EL DIRECTOR DE LA UNIDAD DE REGISTRO NACIONAL DE ABOGADOS Y",
            "         AUXILIARES DE LA JUSTICIA DEL CONSEJO SUPERIOR DE LA JUDICATURA",
            "",
            "                                                CERTIFICA",
            "",
            "Una vez revisados los registros que contienen la base de datos de esta Unidad, se constató que",
            f"la persona identificada con Cédula de Ciudadanía N.° {cedula}, NO ESTÁ INSCRITA en la Unidad de",
            "Registro Nacional de Abogados y Auxiliares de la Justicia como abogado(a).",
            "",
            f"             La presente certificación se expide el {fecha:%d/%m/%Y}, en modo de prueba.",
            "",
            f"Código de verificación: {_CODIGO_FICTICIO}",
            f"                       Documento generado en {_hora_ficticia(fecha)}",
        ]
    )


def _texto_ficticio(nombre: str, cedula: str, tarjeta: str, vigente: bool, fecha: datetime) -> str:
    estado = ESTADO_VIGENTE if vigente else "SUSPENDIDO"
    observaciones = SIN_OBSERVACIONES if vigente else "Sanción disciplinaria ficticia del modo de prueba."
    hora = _hora_ficticia(fecha)
    return "\n".join(
        [
            AVISO_FICTICIO,
            "                                       CERTIFICADO N.°: 0000000",
            "",
            "          EL DIRECTOR DE LA UNIDAD DE REGISTRO NACIONAL DE ABOGADOS Y",
            "         AUXILIARES DE LA JUSTICIA DEL CONSEJO SUPERIOR DE LA JUDICATURA",
            "",
            "                                                CERTIFICA",
            "",
            "Una vez revisados los registros que contienen la base de datos de esta Unidad, se constató que el(la)",
            f"señor(a) {nombre}, quien se identifica con CÉDULA DE CIUDADANÍA N.°",
            f"{cedula}, registra la siguiente información:",
            "",
            "                                                VIGENCIA RNA",
            "              CALIDAD                     FECHA DE INSCRIPCIÓN RNA          ESTADO DE INSCRIPCIÓN RNA",
            "      ABOGADO(A) INSCRITO(A)                        01/01/2010                           VIGENTE",
            "                                               OBSERVACIONES",
            SIN_OBSERVACIONES,
            "",
            "                                                VIGENCIA TPA",
            "         CALIDAD               N.° DE TARJETA PROFESIONAL      FECHA DE EXPEDICIÓN               ESTADO",
            f"  ABOGADO(A) CON TPA                  {tarjeta:<7}                    01/01/2010                 {estado}",
            "                                               OBSERVACIONES",
            observaciones,
            "",
            f"             La presente certificación se expide el {fecha:%d/%m/%Y}, en modo de prueba.",
            "",
            f"Código de verificación: {_CODIGO_FICTICIO}",
            f"                       Documento generado en {hora}",
        ]
    )


def _pdf_de_lineas(lineas: list[str]) -> bytes:
    """Un PDF de una página con las líneas en Helvetica (WinAnsi), cada tramo en su columna."""
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

    def literal(texto: str) -> bytes:
        crudo = texto.encode("cp1252", errors="replace")
        return b"(" + crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

    partes: list[bytes] = []
    y = 792 - 56
    for linea in lineas:
        for tramo in re.finditer(r"\S+(?: \S+)*", linea):
            partes.append(b"BT /F1 8 Tf 1 0 0 1 %.2f %.2f Tm %s Tj ET" % (36 + tramo.start() * 4.6, y, literal(tramo.group())))
        y -= 11
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
    pagina = w.add_blank_page(612, 792)
    flujo = DecodedStreamObject()
    flujo.set_data(b"\n".join(partes))
    pagina[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): fuente})})
    pagina[NameObject("/Contents")] = w._add_object(flujo)
    pagina[NameObject("/MediaBox")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(612), NumberObject(792)])
    w.add_metadata({"/Title": "Certificado de vigencia ficticio (modo de prueba)", "/Producer": "judicabot"})
    salida = BytesIO()
    w.write(salida)
    return salida.getvalue()


def certificado_ficticio(nombre: str, cedula: str, tarjeta: str | None, *, vigente: bool, fecha: datetime) -> bytes:
    """PDF ficticio con el diseño del certificado real, que ``leer_certificado`` lee igual: tarjeta
    ``VIGENTE`` sin observaciones o ``SUSPENDIDO`` con una. Lleva un aviso de que no tiene validez."""
    nombre = " ".join(re.sub(r"[,\x00-\x1f]", " ", nombre).split()).upper() or "ABOGADO DE PRUEBA"
    tp = solo_digitos(tarjeta)
    tp = tp if 3 <= len(tp) <= 7 else "000000"
    return _pdf_de_lineas(_texto_ficticio(nombre, cedula, tp, vigente, fecha).splitlines())


def certificado_ficticio_no_inscrito(cedula: str, *, fecha: datetime) -> bytes:
    """PDF ficticio con el diseño del certificado de una cédula no inscrita como abogado(a) (sin nombre ni
    tablas), que ``leer_certificado`` lee con ``inscrito=False``. Lleva un aviso de que no tiene validez."""
    return _pdf_de_lineas(_texto_ficticio_no_inscrito(solo_digitos(cedula), fecha).splitlines())


# ------------------------------------------------------------ caché


class Guardado(NamedTuple):
    consulta: ConsultaVigencia
    pdf: bytes


class CacheVigencias:
    """Certificados obtenidos en los últimos ``TTL_S`` segundos, compartidos por todos los casos:
    ``<carpeta>/<sha256(cédula)>.json`` (la consulta, sin la ruta del caso) y ``.pdf``. Ningún
    nombre lleva la cédula; los archivos vencidos o dañados se borran."""

    def __init__(self, carpeta: Path) -> None:
        self.carpeta = Path(carpeta)

    @staticmethod
    def _base(cedula: str) -> str:
        return hashlib.sha256(solo_digitos(cedula).encode()).hexdigest()

    def _borrar(self, base: str) -> None:
        for sufijo in (".json", ".pdf"):
            (self.carpeta / f"{base}{sufijo}").unlink(missing_ok=True)

    def leer(self, cedula: str, ahora: float) -> Guardado | None:
        from tutela2.registro_apoderados import ConsultaVigencia

        base = self._base(cedula)
        try:
            meta = json.loads((self.carpeta / f"{base}.json").read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or not 0 <= ahora - float(meta["guardado"]) < TTL_S:
                self._borrar(base)
                return None
            pdf = (self.carpeta / f"{base}.pdf").read_bytes()
            consulta = ConsultaVigencia.model_validate(meta["consulta"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, ValidationError):
            log.warning("Vigencia: se descarta una entrada dañada de la caché")
            self._borrar(base)
            return None
        if consulta.sha256 != hashlib.sha256(pdf).hexdigest():
            self._borrar(base)
            return None
        return Guardado(consulta, pdf)

    def _escribir(self, destino: Path, datos: bytes) -> None:
        fd, temporal = tempfile.mkstemp(dir=self.carpeta, prefix=".vigencia-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(datos)
            os.replace(temporal, destino)
        except BaseException:
            Path(temporal).unlink(missing_ok=True)
            raise

    def guardar(self, cedula: str, ahora: float, consulta: ConsultaVigencia, pdf: bytes) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
        base = self._base(cedula)
        meta = {"guardado": ahora, "consulta": consulta.model_copy(update={"certificado": None}).model_dump(mode="json")}
        self._escribir(self.carpeta / f"{base}.pdf", pdf)
        self._escribir(self.carpeta / f"{base}.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    def podar(self, ahora: float) -> None:
        """Borra las entradas vencidas o a medias y los temporales que quedaron de una escritura cortada."""
        if not self.carpeta.is_dir():
            return
        for ruta in self.carpeta.iterdir():
            try:
                if ruta.name.startswith(".vigencia-") and ahora - ruta.stat().st_mtime > TTL_S:
                    ruta.unlink(missing_ok=True)
                elif ruta.suffix == ".json":
                    meta = json.loads(ruta.read_text(encoding="utf-8"))
                    if not 0 <= ahora - float(meta["guardado"]) < TTL_S:
                        self._borrar(ruta.stem)
                elif ruta.suffix == ".pdf" and not ruta.with_suffix(".json").exists() and ahora - ruta.stat().st_mtime > TTL_S:
                    ruta.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError):
                self._borrar(ruta.stem)


# ------------------------------------------------------------ cola


class _Detenida(Exception):
    """La cola se detuvo mientras esperaba su turno; el pedido sigue en cola."""


class _Retirado(Exception):
    """Ningún caso necesita ya la consulta en curso: no se envía nada más y el pedido sale de la cola."""


@dataclass(eq=False)
class _Pedido:
    cedula: str
    modo: str
    casos: dict[Path, bool] = field(default_factory=dict)
    """Casos que esperan el resultado y, por cada uno, si pidió ``forzar`` (reemplazar un resultado que ya tenga)."""
    forzar: bool = False
    no_antes: float = 0.0
    reintento: bool = False
    """Espera un reintento automático tras quedar sin respuesta: mientras tanto el caso ve ``inaccesible``."""
    cache_revisada: bool = False
    consultando: bool = False


def cedula_de(ap: Apoderado, reg: Registro) -> str:
    """La cédula con que se consulta a un apoderado: la del ajuste manda sobre la del expediente."""
    ajuste = reg.ajustes.get(ap.id)
    return solo_digitos((ajuste.cedula if ajuste is not None and ajuste.cedula else None) or ap.cedula)


def _menor(a: float | None, b: float | None) -> float | None:
    return b if a is None else a if b is None else min(a, b)


class ColaVigencia:
    """Cola única de consultas de vigencia del proceso (ver el docstring del módulo).

    Los pedidos se agrupan por cédula: los casos que esperan la misma cédula reciben el mismo
    resultado. Un pedido de la extensión espera sin gastar intentos mientras no haya una conectada y
    al día, y sigue cuando se conecta (``despertar``, registrado con ``extension.al_conectar`` al
    iniciar). El reloj, la espera y los clientes se pueden inyectar; sin ``iniciar`` no hay hilo y
    ``paso`` atiende un pedido cada vez.

    Lo que se decidió al encolar se vuelve a comprobar justo antes de cada pedido a la Rama Judicial
    (``_depurar``): solo siguen esperando los casos con la consulta todavía en el mismo modo, con algún
    apoderado que use esa cédula y sin un resultado que la consulta ya no pueda reemplazar. Si no queda
    ninguno, nada sale: así apagar la consulta, corregir una cédula mal escrita, subir el certificado a
    mano o reiniciar el caso detienen también los pedidos ya puestos en cola."""

    def __init__(
        self,
        *,
        reloj: Callable[[], float] = time.time,
        dormir: Callable[[float], bool] | None = None,
        clientes: dict[str, ClienteVigencia] | None = None,
        carpeta_cache: Path | None = None,
        estado_extension: Callable[[], EstadoConexion] | None = None,
        modo_de: Callable[[Path], ModoConsulta] | None = None,
    ) -> None:
        self._reloj = reloj
        self._parada = threading.Event()
        self._despertador = threading.Event()
        self._dormir = dormir or self._parada.wait
        self._estado_extension = estado_extension or _estado_extension
        self._modo_de = modo_de or modo_consulta
        self._carpeta_cache = Path(carpeta_cache) if carpeta_cache is not None else None
        self._candado = threading.Lock()
        self._pedidos: dict[tuple[str, str], _Pedido] = {}
        self._intentos: dict[tuple[str, str], tuple[str, int]] = {}
        self._ultimo_pedido: float | None = None
        self._pausa_hasta = 0.0
        self._en_curso: _Pedido | None = None
        self._hilo: threading.Thread | None = None
        self._registrada = False
        self.clientes: dict[str, ClienteVigencia] = clientes or {
            "extension": VigenciaExtension(self.esperar_turno, reloj),
            "directa": VigenciaDirecta(self.esperar_turno, reloj),
            "fake": FakeVigencia(reloj),
        }

    # --- consultas desde el resto del servidor

    def encolar(self, caso_dir: Path, cedulas: Iterable[str], forzar: bool = False) -> int:
        """Pone en cola las cédulas para el caso y devuelve cuántas quedaron esperando.

        No hace nada con la consulta apagada. Sin ``forzar`` se saltan las cédulas que ya tienen un
        resultado en el registro del caso (cualquiera menos ``inaccesible``) y las que agotaron sus
        intentos automáticos del día; un reintento ya programado se respeta. ``forzar`` pide una
        consulta nueva aunque haya resultado, caché o tope diario, pero espera el enfriamiento."""
        caso = Path(caso_dir).resolve()
        validas = [c for c in dict.fromkeys(solo_digitos(c) for c in cedulas) if cedula_valida(c)]
        if not validas:
            return 0
        modo = self._modo_de(caso)
        if modo not in MODOS_AUTOMATICOS:
            return 0
        from tutela2 import registro_apoderados

        try:
            previas = registro_apoderados.leer(caso).consultas
        except registro_apoderados.RegistroInvalido:
            return 0
        ahora = self._reloj()
        hoy = _dia(ahora)
        n = 0
        with self._candado:
            for cedula in validas:
                clave = (modo, cedula)
                previa = previas.get(cedula)
                inaccesible = previa is not None and previa.estado == "inaccesible"
                if inaccesible and _dia(_epoca(previa.consultado_en)) == hoy:
                    self._sembrar_intentos(clave, hoy, previa.intentos_auto)
                pedido = self._pedidos.get(clave)
                if not forzar:
                    if previa is not None and not inaccesible:
                        continue
                    if pedido is None and modo in MODOS_REGISTRO and self._intentos_de(clave, hoy) >= MAX_AUTO_DIA:
                        continue
                if pedido is None:
                    pedido = self._pedidos[clave] = _Pedido(cedula, modo)
                    proximo = _epoca(previa.proximo_intento) if inaccesible and previa.proximo_intento else 0.0
                    if not forzar and proximo > ahora:
                        pedido.no_antes, pedido.reintento, pedido.cache_revisada = proximo, True, True
                pedido.casos[caso] = pedido.casos.get(caso, False) or forzar
                if forzar:
                    pedido.forzar, pedido.reintento, pedido.no_antes = True, False, 0.0
                n += 1
        if n:
            log.info("Vigencia: %d cédula(s) en cola para %s (%s%s)", n, caso.name, modo, ", forzada" if forzar else "")
            self._despertador.set()
        return n

    def fase(self, cedula: str, caso_dir: Path | None = None) -> FaseCola | None:
        """``consultando`` o ``en_cola`` si la cola atiende o atenderá esa cédula (para ``caso_dir``,
        si se da); ``None`` si no está en cola, si espera un reintento tras quedar sin respuesta o si
        espera una extensión conectada y al día: entonces el caso necesita ayuda."""
        cedula = solo_digitos(cedula)
        caso = Path(caso_dir).resolve() if caso_dir is not None else None
        with self._candado:
            pedidos = [p for (_, c), p in self._pedidos.items() if c == cedula and (caso is None or caso in p.casos)]
            if any(p.consultando for p in pedidos):
                return "consultando"
            ahora = self._reloj()
            pedidos = [p for p in pedidos if not (p.reintento and p.no_antes > ahora)]
        if any(p.modo != "extension" for p in pedidos):
            return "en_cola"
        if pedidos and self._estado_extension_seguro() == "conectada":
            return "en_cola"
        return None

    def activa(self, caso_dir: Path) -> bool:
        """La cola atiende o atenderá alguna cédula de este caso."""
        caso = Path(caso_dir).resolve()
        with self._candado:
            cedulas = {c for (_, c), p in self._pedidos.items() if caso in p.casos}
        return any(self.fase(c, caso) for c in cedulas)

    def pausa_hasta(self) -> datetime | None:
        """Hasta cuándo la cola no pide nada a la Rama Judicial tras quedar sin respuesta."""
        with self._candado:
            hasta = self._pausa_hasta
        return datetime.fromtimestamp(hasta, timezone.utc) if hasta > self._reloj() else None

    def retirar(self, caso_dir: Path, cedulas: Iterable[str] | None = None) -> int:
        """Saca el caso de los pedidos de esas cédulas (de todas, sin ``cedulas``) porque ya no los necesita:
        subió el certificado a mano, corrigió la cédula o se reinició. Así ``fase`` deja de verlas en cola
        enseguida. Un pedido sin casos sale de la cola; si está en curso, no envía nada más y su resultado
        no se guarda en el caso. Devuelve de cuántos pedidos salió el caso."""
        caso = Path(caso_dir).resolve()
        filtro = None if cedulas is None else {solo_digitos(c) for c in cedulas} - {""}
        n = 0
        with self._candado:
            for clave, pedido in list(self._pedidos.items()):
                if caso not in pedido.casos or (filtro is not None and pedido.cedula not in filtro):
                    continue
                del pedido.casos[caso]
                n += 1
                if not pedido.casos and not pedido.consultando:
                    del self._pedidos[clave]
        if n:
            log.info("Vigencia: %s ya no espera %d consulta(s)", caso.name, n)
        return n

    def despertar(self) -> None:
        self._despertador.set()

    # --- hilo

    def iniciar(self) -> None:
        """Arranca el hilo de la cola (idempotente) y la registra para despertar al conectarse la extensión."""
        with self._candado:
            self._parada.clear()
            if self._hilo is None or not self._hilo.is_alive():
                self._hilo = threading.Thread(target=self._bucle, name="cola-vigencias", daemon=True)
                self._hilo.start()
        if not self._registrada:
            try:
                from tutela2 import extension

                extension.al_conectar(self.despertar)
                self._registrada = True
            except Exception as e:
                log.warning(
                    "Vigencia: la cola no se pudo registrar para despertar al conectar la extensión (%s)", type(e).__name__
                )

    def detener(self, espera_s: float = 5.0) -> None:
        """Detiene el hilo; los pedidos pendientes quedan en la cola."""
        self._parada.set()
        self._despertador.set()
        hilo = self._hilo
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(espera_s)

    def _bucle(self) -> None:
        while not self._parada.is_set():
            try:
                espera = self.paso()
            except Exception as e:
                log.error("Vigencia: error inesperado en la cola (%s)", type(e).__name__)
                espera = REVISION_ESTACIONADOS_S
            if self._parada.is_set():
                break
            if espera is None or espera > 0:
                self._despertador.wait(espera)
                self._despertador.clear()

    # --- atención de los pedidos

    def paso(self) -> float | None:
        """Atiende a lo sumo un pedido. Devuelve cuántos segundos esperar antes del siguiente paso
        (0: seguir ya) o ``None`` si no queda nada que hacer hasta un nuevo pedido o un aviso."""
        with self._candado:
            hay_extension = any(p.modo == "extension" for p in self._pedidos.values())
        extension = self._estado_extension_seguro() if hay_extension else "no_conectada"
        with self._candado:
            pedido, espera = self._elegir(self._reloj(), extension)
            if pedido is None:
                return espera
            pedido.consultando = True
            self._en_curso = pedido
        try:
            self._atender(pedido, extension)
        except _Detenida:
            return None
        except _Retirado:
            log.info("Vigencia %s: ningún caso necesita ya la consulta; no se envía", referencia(pedido.cedula))
            self._quitar(pedido)
        except Exception as e:
            marco = traceback.extract_tb(e.__traceback__)[-1]
            log.error(
                "Vigencia %s: la consulta falló (%s en %s:%s); se saca de la cola",
                referencia(pedido.cedula), type(e).__name__, Path(marco.filename).name, marco.lineno,
            )
            self._quitar(pedido)
        finally:
            with self._candado:
                pedido.consultando = False
                self._en_curso = None
        return 0.0

    def esperar_turno(self, esperar: bool = True) -> None:
        """Espera hasta que hayan pasado ``PAUSA_S`` desde el último pedido a la Rama Judicial y lo anota.

        El cliente lo llama antes del GET de cada consulta y, con ``esperar=False``, antes de su POST: este
        sale enseguida (con las cookies de afinidad del GET), así que ``PAUSA_S`` separa consultas, no el GET
        de su POST. La espera nunca pasa de ``PAUSA_S``, aunque el reloj del sistema retroceda. Después de
        esperar, y justo antes de que salga el pedido, vuelve a comprobar que algún caso todavía necesite la
        consulta en curso (``_Retirado`` si no: no sale nada)."""
        with self._candado:
            espera = 0.0 if self._ultimo_pedido is None else min(PAUSA_S, self._ultimo_pedido + PAUSA_S - self._reloj())
            en_curso = self._en_curso
        if esperar and espera > 0 and self._dormir(espera):
            raise _Detenida()
        if en_curso is not None and not self._depurar(en_curso):
            raise _Retirado()
        with self._candado:
            self._ultimo_pedido = self._reloj()

    def _estado_extension_seguro(self) -> EstadoConexion:
        try:
            return self._estado_extension()
        except Exception as e:
            log.warning("Vigencia: no se pudo saber si la extensión está conectada (%s)", type(e).__name__)
            return "no_conectada"

    def _bloqueo(self, pedido: _Pedido, ahora: float, extension: EstadoConexion) -> float | None:
        """Segundos que le faltan al pedido para poder salir (0: ya), o ``None`` si espera la extensión."""
        espera = 0.0
        if pedido.no_antes > ahora:
            espera = pedido.no_antes - ahora
        if pedido.modo in MODOS_REGISTRO:
            if self._pausa_hasta > ahora:
                espera = max(espera, self._pausa_hasta - ahora)
            if self._ultimo_pedido is not None and self._ultimo_pedido <= ahora < self._ultimo_pedido + PAUSA_S:
                espera = max(espera, self._ultimo_pedido + PAUSA_S - ahora)
            if espera == 0 and pedido.modo == "extension" and extension != "conectada":
                return None
        return espera

    def _elegir(self, ahora: float, extension: EstadoConexion) -> tuple[_Pedido | None, float | None]:
        espera: float | None = None
        for pedido in self._pedidos.values():
            if pedido.consultando:
                continue
            if not pedido.forzar and not pedido.cache_revisada:
                return pedido, 0.0
            bloqueo = self._bloqueo(pedido, ahora, extension)
            if bloqueo == 0:
                return pedido, 0.0
            espera = _menor(espera, REVISION_ESTACIONADOS_S if bloqueo is None else bloqueo)
        return None, espera

    def _cache(self, pedido: _Pedido) -> CacheVigencias | None:
        if pedido.modo not in MODOS_REGISTRO:
            return None
        if self._carpeta_cache is not None:
            return CacheVigencias(self._carpeta_cache)
        for caso in list(pedido.casos):
            try:
                return CacheVigencias(cfgmod.cargar(caso).cache_path() / "vigencias")
            except Exception as e:
                log.warning("%s: no se pudo abrir la caché de vigencias (%s)", caso.name, type(e).__name__)
        return None

    def _intentos_de(self, clave: tuple[str, str], hoy: str) -> int:
        dia, n = self._intentos.get(clave, (hoy, 0))
        return n if dia == hoy else 0

    def _sembrar_intentos(self, clave: tuple[str, str], hoy: str, n: int) -> None:
        self._intentos[clave] = (hoy, max(self._intentos_de(clave, hoy), n))

    def _quitar(self, pedido: _Pedido) -> dict[Path, bool]:
        with self._candado:
            if self._pedidos.get((pedido.modo, pedido.cedula)) is pedido:
                del self._pedidos[(pedido.modo, pedido.cedula)]
            return dict(pedido.casos)

    def _necesita(self, caso: Path, pedido: _Pedido, forzar: bool) -> bool:
        """El caso todavía espera esta consulta: sigue en el modo del pedido, algún apoderado usa la cédula y
        no tiene un resultado (salvo ``inaccesible``) que la consulta no reemplazaría. Lo mismo que exige
        ``guardar_en_caso`` para guardar el resultado; ante cualquier duda, no."""
        from tutela2 import registro_apoderados

        try:
            if self._modo_de(caso) != pedido.modo:
                return False
            reg = registro_apoderados.leer(caso)
        except Exception as e:
            log.warning("%s: no se pudo comprobar si el caso espera la consulta de vigencia (%s)", caso.name, type(e).__name__)
            return False
        apoderados = reg.identificacion.apoderados if reg.identificacion is not None else []
        if not any(cedula_de(ap, reg) == pedido.cedula for ap in apoderados):
            return False
        previa = reg.consultas.get(pedido.cedula)
        return forzar or previa is None or previa.estado == "inaccesible"

    def _depurar(self, pedido: _Pedido) -> bool:
        """Deja en el pedido solo los casos que todavía lo necesitan (``_necesita``) y dice si queda alguno.

        Lee los registros fuera del candado; un caso que ``encolar`` volvió a pedir entretanto con otro
        ``forzar`` se conserva."""
        with self._candado:
            casos = dict(pedido.casos)
        fuera = {caso: forzar for caso, forzar in casos.items() if not self._necesita(caso, pedido, forzar)}
        with self._candado:
            for caso, forzar in fuera.items():
                if pedido.casos.get(caso) == forzar:
                    del pedido.casos[caso]
            return bool(pedido.casos)

    def _atender(self, pedido: _Pedido, extension: EstadoConexion) -> None:
        ref = referencia(pedido.cedula)
        clave = (pedido.modo, pedido.cedula)
        if not self._depurar(pedido):
            raise _Retirado()
        cache = self._cache(pedido)
        ahora = self._reloj()
        if cache is not None:
            cache.podar(ahora)
        if not pedido.forzar and not pedido.cache_revisada:
            guardado = cache.leer(pedido.cedula, ahora) if cache is not None else None
            if guardado is not None:
                log.info("Vigencia %s: resultado de la caché (%s)", ref, guardado.consulta.estado)
                self._repartir(self._quitar(pedido), pedido.cedula, guardado.consulta, guardado.pdf)
                return
            with self._candado:
                pedido.cache_revisada = True
            if self._bloqueo(pedido, ahora, extension) != 0:
                return
        with self._candado:
            agotado = not pedido.forzar and pedido.modo in MODOS_REGISTRO and self._intentos_de(clave, _dia(ahora)) >= MAX_AUTO_DIA
        if agotado:
            log.info("Vigencia %s: se agotaron los intentos automáticos del día", ref)
            self._quitar(pedido)
            return

        titular = self._titular(pedido) if pedido.modo == "fake" else None
        inicio = self._reloj()
        log.info("Vigencia %s: consultando (%s)", ref, pedido.modo)
        resultado = self.clientes[pedido.modo].consultar(pedido.cedula, titular)
        ahora = self._reloj()
        if resultado.estado in ("no_conectada", "desactualizada"):
            log.info(
                "Vigencia %s: la extensión está %s; la consulta espera sin gastar intentos",
                ref,
                resultado.estado.replace("_", " "),
            )
            return
        with self._candado:
            n = self._intentos_de(clave, _dia(ahora)) + 1
            self._intentos[clave] = (_dia(ahora), n)
        if resultado.estado == "inaccesible" or resultado.pdf is None:
            self._sin_respuesta(pedido, resultado, n, ahora)
            return

        pdf = resultado.pdf
        cert = leer_certificado(pdf)
        estado = clasificar(cert, pedido.cedula) if cert is not None else "ilegible"
        from tutela2.registro_apoderados import ConsultaVigencia

        consulta = ConsultaVigencia(
            estado=estado,
            origen=pedido.modo,
            consultado_en=_iso(ahora),
            sha256=hashlib.sha256(pdf).hexdigest(),
            datos=cert,
            detalle=DETALLES[pedido.modo],
        )
        if cache is not None and cert is not None:
            try:
                cache.guardar(pedido.cedula, ahora, consulta, pdf)
            except OSError as e:
                log.warning("Vigencia %s: no se pudo guardar en la caché (%s)", ref, type(e).__name__)
        log.info("Vigencia %s: %s en %.1f s (%s)", ref, estado, ahora - inicio, pedido.modo)
        self._repartir(self._quitar(pedido), pedido.cedula, consulta, pdf)

    def _sin_respuesta(self, pedido: _Pedido, resultado: Resultado, n: int, ahora: float) -> None:
        from tutela2.registro_apoderados import ConsultaVigencia

        proximo = ahora + ENFRIAMIENTO_S
        with self._candado:
            if pedido.modo in MODOS_REGISTRO:
                self._pausa_hasta = max(self._pausa_hasta, proximo)
            casos = dict(pedido.casos)
            # Sin casos que esperen (los retiraron mientras se consultaba) no se programa otro intento.
            otro = n < MAX_AUTO_DIA and bool(casos)
            if otro:
                # El reintento vuelve a consultar: la caché ya se miró o se saltó a propósito (forzar).
                pedido.no_antes, pedido.reintento, pedido.forzar, pedido.cache_revisada = proximo, True, False, True
                pedido.casos = dict.fromkeys(casos, False)
            elif self._pedidos.get((pedido.modo, pedido.cedula)) is pedido:
                del self._pedidos[(pedido.modo, pedido.cedula)]
        log.warning(
            "Vigencia %s: sin respuesta (%s); intento %d de %d del día%s",
            referencia(pedido.cedula), pedido.modo, n, MAX_AUTO_DIA,
            f", la cola espera {ENFRIAMIENTO_S / 60:.0f} min" if pedido.modo in MODOS_REGISTRO else "",
        )
        consulta = ConsultaVigencia(
            estado="inaccesible",
            origen=pedido.modo,
            consultado_en=_iso(ahora),
            detalle=resultado.detalle or SIN_RESPUESTA,
            intentos_auto=n,
            proximo_intento=_iso(proximo) if otro else None,
        )
        self._repartir(casos, pedido.cedula, consulta, None)

    def _titular(self, pedido: _Pedido) -> Titular | None:
        from tutela2 import registro_apoderados

        for caso in list(pedido.casos):
            try:
                reg = registro_apoderados.leer(caso)
            except registro_apoderados.RegistroInvalido:
                continue
            for ap in reg.identificacion.apoderados if reg.identificacion is not None else []:
                if cedula_de(ap, reg) == pedido.cedula:
                    return Titular(ap.nombre, ap.tarjeta)
        return None

    def _repartir(self, casos: dict[Path, bool], cedula: str, consulta: ConsultaVigencia, pdf: bytes | None) -> None:
        for caso, forzar in casos.items():
            guardar_en_caso(caso, cedula, consulta, pdf, reemplazar=forzar)


def guardar_en_caso(
    caso_dir: Path, cedula: str, consulta: ConsultaVigencia, pdf: bytes | None, *, reemplazar: bool = False
) -> bool:
    """Guarda una consulta automática en el registro del caso, igual que la subida manual: el PDF en
    ``apoderados/certificados/`` con el nombre de ``nombre_certificado`` y la consulta bajo la cédula.

    Solo si algún apoderado del caso usa esa cédula (no se guardan datos de quien no es parte). Un
    resultado que ya tenga el caso (cualquiera menos ``inaccesible``) se conserva, salvo con
    ``reemplazar`` y un resultado nuevo que no sea ``inaccesible``: así una consulta que llega tarde
    no pisa el certificado que el despacho subió entretanto (ni vence su revisión). El certificado
    que se reemplaza se borra si ya nadie lo usa. Devuelve si guardó la consulta."""
    from tutela2 import registro_apoderados

    caso_dir = Path(caso_dir)
    reemplazadas: list[str] = []
    nuevas: list[str] = []
    guardada: list[bool] = []

    def poner(reg: Registro) -> None:
        apoderados = reg.identificacion.apoderados if reg.identificacion is not None else []
        ids = sorted(ap.id for ap in apoderados if cedula_de(ap, reg) == cedula)
        if not ids:
            return
        previa = reg.consultas.get(cedula)
        if previa is not None and previa.estado != "inaccesible" and (consulta.estado == "inaccesible" or not reemplazar):
            return
        nueva = consulta.model_copy(update={"certificado": None})
        if pdf is not None and consulta.sha256:
            nueva.certificado = registro_apoderados.guardar_certificado(caso_dir, nombre_certificado(ids[0], consulta.sha256), pdf)
            nuevas.append(nueva.certificado)
        if previa is not None and previa.certificado and previa.certificado != nueva.certificado:
            reemplazadas.append(previa.certificado)
        reg.consultas[cedula] = nueva
        guardada.append(True)

    try:
        reg = registro_apoderados.actualizar(caso_dir, poner)
    except registro_apoderados.RegistroInvalido:
        log.warning("%s: el registro de apoderados no es válido; no se guarda la consulta de vigencia", caso_dir.name)
        return False
    except Exception as e:
        log.warning("%s: no se pudo guardar la consulta de vigencia (%s)", caso_dir.name, type(e).__name__)
        registro_apoderados.borrar_certificados_sin_uso(caso_dir, nuevas)
        return False
    if reg is None:
        return False
    if reemplazadas:
        registro_apoderados.borrar_certificados_sin_uso(caso_dir, reemplazadas)
    return bool(guardada)


COLA = ColaVigencia()
"""La cola del proceso. El servidor la arranca y la detiene con su ciclo de vida; en las pruebas no hay hilo."""
