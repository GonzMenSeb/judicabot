from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from docx.oxml.ns import qn
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

ARCHIVOS = {"borrador": "previo.vista.json", "fallo": "fallo.vista.json"}
ESTADOS_CITA = {"ok": "verificada", "alerta": "revisar", "rechazada": "rechazada"}

TipoBloque = Literal[
    "titulo", "encabezado", "parrafo", "cita_bloque", "lista", "tabla", "firma", "pie", "resuelve_numeral"
]


def _opcional(**kw):
    return Field(default=None, json_schema_extra=lambda s: s.pop("default", None), **kw)


class Segmento(BaseModel):
    texto: str
    negrita: bool | SkipJsonSchema[None] = _opcional()
    cursiva: bool | SkipJsonSchema[None] = _opcional()
    cita_id: str | SkipJsonSchema[None] = _opcional()


class Bloque(BaseModel):
    id: str
    tipo: TipoBloque
    origen: Literal["plantilla", "modelo"]
    seccion: str | None
    segmentos: list[Segmento]


class PaginaVista(BaseModel):
    bloques: list[Bloque]


class CitaVista(BaseModel):
    id: str
    texto: str
    fuente: str
    cobertura: float | None
    estado: Literal["verificada", "revisar", "rechazada"]
    detalle: str | None


class EntradaIndice(BaseModel):
    id: str
    titulo: str


class Vista(BaseModel):
    tipo: Literal["borrador", "fallo"]
    sha256: str
    paginas: list[PaginaVista]
    citas: list[CitaVista]
    indice: list[EntradaIndice]


_SIN_CONTEXTO = object()


def _clave(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-") or "seccion"


class Registro:
    def __init__(self) -> None:
        self.tipo = "parrafo"
        self.origen = "plantilla"
        self.cita: str | None = None
        self.spans: list[tuple[int, int, str]] = []
        self.seccion: str | None = None
        self.claves: set[str] = set()
        self.parrafos: dict[Any, dict] = {}

    @contextmanager
    def como(self, tipo=_SIN_CONTEXTO, *, origen=_SIN_CONTEXTO, cita=_SIN_CONTEXTO, spans=_SIN_CONTEXTO):
        cambios = {k: v for k, v in (("tipo", tipo), ("origen", origen), ("cita", cita), ("spans", spans)) if v is not _SIN_CONTEXTO}
        previo = {k: getattr(self, k) for k in cambios}
        for k, v in cambios.items():
            setattr(self, k, v)
        try:
            yield
        finally:
            for k, v in previo.items():
                setattr(self, k, v)

    def abrir_seccion(self, texto: str) -> None:
        base = clave = _clave(texto)
        n = 2
        while clave in self.claves:
            clave, n = f"{base}-{n}", n + 1
        self.claves.add(clave)
        self.seccion = clave

    def segmento(self, elemento, texto: str, negrita, cursiva) -> None:
        entrada = self.parrafos.get(elemento)
        if entrada is None:
            entrada = self.parrafos[elemento] = {
                "tipo": self.tipo,
                "origen": self.origen,
                "seccion": self.seccion,
                "cita": self.cita,
                "spans": self.spans,
                "segmentos": [],
            }
        entrada["segmentos"].append((texto.replace("\r", "\n"), bool(negrita), bool(cursiva)))


def _con_citas(segmentos: list[tuple[str, bool, bool]], spans, cita) -> list[tuple[str, bool, bool, str | None]]:
    salida = []
    pos = 0
    for texto, negrita, cursiva in segmentos:
        ini, fin = pos, pos + len(texto)
        cortes = sorted({ini, fin, *(x for a, b, _ in spans for x in (a, b) if ini < x < fin)})
        for a, b in zip(cortes, cortes[1:]):
            dentro = next((c for s, e, c in spans if s <= a and b <= e), cita)
            salida.append((texto[a - ini : b - ini], negrita, cursiva, dentro))
        pos = fin
    return salida


def _fundir(piezas) -> list[dict]:
    salida: list[dict] = []
    previo = None
    for texto, negrita, cursiva, cita in piezas:
        if not texto:
            continue
        clave = (negrita, cursiva, cita)
        if salida and clave == previo:
            salida[-1]["texto"] += texto
            continue
        salida.append(_seg(texto, negrita, cursiva, cita))
        previo = clave
    return salida


def _seg(texto: str, negrita: bool = False, cursiva: bool = False, cita: str | None = None) -> dict:
    s: dict[str, Any] = {"texto": texto}
    if negrita:
        s["negrita"] = True
    if cursiva:
        s["cursiva"] = True
    if cita:
        s["cita_id"] = cita
    return s


def _celda(registro: Registro, celda) -> tuple[dict, dict | None]:
    piezas, meta = [], None
    for p in celda.iterchildren(qn("w:p")):
        entrada = registro.parrafos.get(p)
        if entrada is None:
            continue
        meta = meta or entrada
        piezas.extend(entrada["segmentos"])
    texto = "".join(t for t, _, _ in piezas)
    return _seg(texto, bool(piezas) and all(n for _, n, _ in piezas), bool(piezas) and all(c for _, _, c in piezas)), meta


def bloques_cuerpo(registro: Registro, doc) -> list[dict]:
    crudos: list[dict] = []
    for hijo in doc.element.body.iterchildren():
        if hijo.tag == qn("w:p"):
            entrada = registro.parrafos.get(hijo)
            if entrada is None:
                continue
            segmentos = _fundir(_con_citas(entrada["segmentos"], entrada["spans"], entrada["cita"]))
            if segmentos:
                crudos.append({**entrada, "segmentos": segmentos})
        elif hijo.tag == qn("w:tbl"):
            for fila in hijo.iterchildren(qn("w:tr")):
                celdas = [_celda(registro, c) for c in fila.iterchildren(qn("w:tc"))]
                meta = next((m for _, m in celdas if m is not None), None)
                if meta is None or not any(s["texto"] for s, _ in celdas):
                    continue
                crudos.append({**meta, "tipo": "tabla", "segmentos": [s for s, _ in celdas]})
    contadores: dict[str | None, int] = {}
    bloques = []
    for b in crudos:
        seccion = b["seccion"]
        if b["tipo"] == "titulo" and seccion not in contadores:
            id_ = seccion
            contadores[seccion] = 0
        else:
            contadores[seccion] = contadores.get(seccion, 0) + 1
            id_ = f"{seccion or 'encabezado'}-{contadores[seccion]}"
        bloques.append(
            {"id": id_, "tipo": b["tipo"], "origen": b["origen"], "seccion": seccion, "segmentos": b["segmentos"]}
        )
    return bloques


def textos_pie(doc) -> list[str]:
    salida = []
    for p in doc.sections[0].footer.paragraphs:
        if p._p.xpath(".//w:fldSimple | .//w:instrText"):
            continue
        if p.text.strip():
            salida.append(p.text)
    return salida


LINEAS_PAGINA = {"A": 50, "B": 39}
CARACTERES_LINEA = {"A": 70, "B": 70}
CARACTERES_CITA = 55


def _lineas(bloque: dict, gen: str) -> int:
    texto = "".join(s["texto"] for s in bloque["segmentos"])
    tipo = bloque["tipo"]
    if tipo == "tabla":
        return max(2, math.ceil(max((len(s["texto"]) for s in bloque["segmentos"]), default=0) / 40) + 1)
    ancho = CARACTERES_CITA if tipo == "cita_bloque" else CARACTERES_LINEA[gen]
    extra = 3 if tipo == "titulo" else 1
    return max(1, math.ceil(len(texto) / ancho)) + extra


def paginar(bloques: list[dict], gen: str) -> list[list[dict]]:
    """Paginación aproximada de vista previa, no la de Word.

    Cada bloque ocupa ceil(caracteres / CARACTERES_LINEA[gen]) líneas (CARACTERES_CITA en las citas en bloque,
    una línea por cada 40 caracteres de la celda más larga en las filas de tabla) más una línea de espacio
    (tres en los títulos). Una página admite LINEAS_PAGINA[gen] líneas. Los bloques no se parten: si un bloque
    no cabe, empieza página nueva. Un título o encabezado solo se queda en la página si cabe junto con los
    títulos o encabezados que lo siguen y el primer bloque posterior a ellos, como "conservar con el
    siguiente" en Word.
    """
    capacidad = LINEAS_PAGINA[gen]
    lineas = [_lineas(b, gen) for b in bloques]
    paginas: list[list[dict]] = [[]]
    usadas = 0
    for i, bloque in enumerate(bloques):
        n = minimo = lineas[i]
        j = i
        while bloques[j]["tipo"] in ("titulo", "encabezado") and j + 1 < len(bloques):
            j += 1
            minimo += lineas[j]
        huerfano = bool(paginas[-1]) and paginas[-1][-1]["tipo"] in ("titulo", "encabezado")
        if paginas[-1] and not huerfano and usadas + minimo > capacidad:
            paginas.append([])
            usadas = 0
        paginas[-1].append(bloque)
        usadas += n
    return paginas


def cita_vista(cv, referencia: str) -> dict:
    return {
        "id": cv.id,
        "texto": cv.texto_citado,
        "fuente": referencia if cv.estado != "rechazada" else cv.sentencia_original,
        "cobertura": cv.cobertura,
        "estado": ESTADOS_CITA[cv.estado],
        "detalle": "; ".join(cv.motivos) or None,
    }


def armar(tipo: str, sha256: str, bloques: list[dict], pie: list[str], citas: list[dict], gen: str) -> dict:
    paginas = []
    for n, contenido in enumerate(paginar(bloques, gen), 1):
        pies = [
            {"id": f"pie-{n}-{k}", "tipo": "pie", "origen": "plantilla", "seccion": None, "segmentos": [_seg(t)]}
            for k, t in enumerate(pie, 1)
        ]
        paginas.append({"bloques": contenido + pies})
    indice = [
        {"id": b["id"], "titulo": " ".join("".join(s["texto"] for s in b["segmentos"]).split())}
        for b in bloques
        if b["tipo"] == "titulo"
    ]
    return {"tipo": tipo, "sha256": sha256, "paginas": paginas, "citas": citas, "indice": indice}


def guardar(datos: dict, ruta: Path) -> Path:
    ruta = Path(ruta)
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    try:
        temporal.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporal, ruta)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise
    return ruta
