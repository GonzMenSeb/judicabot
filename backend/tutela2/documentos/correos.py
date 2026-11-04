from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from tutela2 import formato_b, formulas, radicado
from tutela2.config import Config
from tutela2.models import Decision, Doc, Ingesta, Metadatos

AVISO = "BORRADOR — no es constancia de envío"
PARA_REPARTO = "ofjudmed@cendoj.ramajudicial.gov.co"
FUENTE = "Calibri"
TAMANO = 11

_CORREO = re.compile(
    r"(?<![\w.%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![\w\-@]|\.\w)"
)
_CANDIDATO = re.compile(r"(?<![\w.%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*(?![\w\-@])")
_ENCABEZADO = re.compile(r"^\s*(De|Desde|Para)\s*:?(?:\s+|$)", re.IGNORECASE)
_FALTA = re.compile(r"(⟦FALTA:[^⟧]*⟧)")


def _falta(nombre: str) -> str:
    return f"⟦FALTA: {nombre}⟧"


def _o(valor: str | None, nombre: str) -> str:
    return valor.strip() if valor and valor.strip() else _falta(nombre)


_SISTEMA = re.compile(r"^(microsoftexchange|postmaster|mailer-daemon)|no-?reply", re.IGNORECASE)
_SIGUE = re.compile(r"^\s*(Fecha|Para|Enviado|Asunto|Cc)\b", re.IGNORECASE)


def _es_sistema(linea: str) -> bool:
    return any(_SISTEMA.search(c.split("@")[0]) for c in _CORREO.findall(linea))


def _es_continuacion(linea: str) -> bool:
    return bool(linea.strip()) and (linea[0].isspace() or linea[0] in "<«") and not _SIGUE.match(linea)


def _sigue_encabezado(lineas: list[str], j: int) -> bool:
    while j < len(lineas) and _es_continuacion(lineas[j]):
        j += 1
    return j < len(lineas) and bool(_SIGUE.match(lineas[j]))


def _completar(truncado: str, completos: list[str]) -> str | None:
    prefijo = truncado.lower()
    opciones = {c.lower(): c for c in completos if len(c) > len(truncado) and c.lower().startswith(prefijo)}
    return next(iter(opciones.values())) if len(opciones) == 1 else None


def _correos_linea(linea: str, completos: list[str]) -> list[str]:
    hallados = [(m.start(), m.group()) for m in _CORREO.finditer(linea)]
    cubiertos = [(m.start(), m.end()) for m in _CORREO.finditer(linea)]
    for m in _CANDIDATO.finditer(linea):
        if any(a <= m.start() and m.end() <= b for a, b in cubiertos):
            continue
        completo = _completar(m.group(), completos)
        if completo:
            hallados.append((m.start(), completo))
    return [c for _, c in sorted(hallados)]


def _correos_encabezado(texto: str, completos: list[str] | None = None) -> list[str]:
    encontrados: list[str] = []
    lineas = texto.splitlines()
    en_bloque = False
    sistema = False
    for i, linea in enumerate(lineas):
        m = _ENCABEZADO.match(linea)
        if m and not en_bloque:
            valida = ":" in linea[: m.end()] or _sigue_encabezado(lineas, i + 1)
            if valida:
                en_bloque = True
                sistema = False
        if not linea.strip():
            en_bloque = False
        if en_bloque:
            if m and m.group(1).lower() in ("de", "desde") and _es_sistema(linea):
                sistema = True
            if not sistema:
                encontrados += _correos_linea(linea, completos or [])
    return encontrados


def _unicos(correos: list[str]) -> list[str]:
    vistos: dict[str, str] = {}
    for c in correos:
        vistos.setdefault(c.lower(), c)
    return list(vistos.values())


def es_confiable(ing: Ingesta, d: Doc) -> bool:
    return not (d.ruido or d.doc_id in ing.docs_ajenos or d.doc_id in ing.docs_revisar)


def _ultima_notificacion(ing: Ingesta):
    docs = [d for d in ing.documentos if d.rol == "notificacion" and d.instancia == "1a" and es_confiable(ing, d)]
    return sorted(docs, key=lambda d: d.ruta)[-1] if docs else None


def destinatarios_propuestos(ing: Ingesta) -> list[str]:
    doc = _ultima_notificacion(ing)
    if not doc:
        return []
    visibles = ing.model_copy(update={"docs_ajenos": [*ing.docs_ajenos, *ing.docs_revisar]})
    completos = [c for t in visibles.textos_visibles() for c in _CORREO.findall(t)]
    return _unicos(_correos_encabezado(doc.texto(), completos))


def _cui_2a(md: Metadatos) -> str | None:
    if md.cui_2a:
        return radicado.digitos(md.cui_2a)
    if md.cui_1a:
        return radicado.cui_2a(md.cui_1a)
    return None


def _cui_1a(md: Metadatos) -> str | None:
    return radicado.digitos(md.cui_1a) if md.cui_1a else None


def _adjunto(valor: str | None, nombre: str) -> str:
    return re.sub(r"\.docx$", ".pdf", _o(valor, f"número definitivo del {nombre}"), flags=re.IGNORECASE)


def _mayus(valor: str | None, nombre: str) -> str:
    return valor.strip().upper() if valor and valor.strip() else _falta(nombre)


def _accionadas(md: Metadatos) -> str:
    return ", ".join(a.strip().upper() for a in md.accionadas if a.strip()) or _falta("accionada")


def _parrafo(doc, texto: str = "", *, negrita: bool = False):
    par = doc.add_paragraph()
    formato_b.espaciado(par, despues=6)
    for trozo in _FALTA.split(texto):
        if not trozo:
            continue
        run = par.add_run(trozo)
        formato_b.fuente(run, FUENTE, TAMANO, negrita=negrita or None)
        if _FALTA.fullmatch(trozo):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return par


def _campo(doc, etiqueta: str, valor: str) -> None:
    par = _parrafo(doc)
    run = par.add_run(f"{etiqueta}: ")
    formato_b.fuente(run, FUENTE, TAMANO, negrita=True)
    for trozo in _FALTA.split(valor):
        if not trozo:
            continue
        run = par.add_run(trozo)
        formato_b.fuente(run, FUENTE, TAMANO)
        if _FALTA.fullmatch(trozo):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def _firma(doc, cfg: Config) -> None:
    d = cfg.despacho
    for i, linea in enumerate(
        (
            d.escribiente,
            d.cargo_escribiente,
            *d.firma_correo,
            d.correo,
            d.telefono_correo,
        )
    ):
        par = _parrafo(doc, linea)
        formato_b.espaciado(par)
        if i == 0:
            par.paragraph_format.space_before = formato_b.Pt(12)


def _base(para: str, asunto: str, adjunto: str):
    doc = Document()
    formato_b.configurar_oficio(doc)
    formato_b.ajustes_word(doc)
    _parrafo(doc, AVISO, negrita=True)
    _campo(doc, "Para", para)
    _campo(doc, "Asunto", asunto)
    _campo(doc, "Adjunto", adjunto)
    return doc


def _guardar(doc, ruta: Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.save(ruta)
    return ruta


def render_notificacion(md: Metadatos, ing: Ingesta, cfg: Config, adjunto: str | None, ruta: Path) -> Path:
    cui = _cui_2a(md)
    para = "; ".join(destinatarios_propuestos(ing)) or _falta("destinatarios")
    doc = _base(para, f"Notifica fallo de segunda instancia radicado {cui or _falta('radicado')}", _adjunto(adjunto, "fallo"))
    _parrafo(doc, "Cordial saludo,")
    _parrafo(doc, "Adjunto sentencia de tutela para su conocimiento:")
    tabla = doc.add_table(rows=1, cols=3)
    formato_b.bordes_tabla(tabla)
    valores = (
        radicado.con_guion(cui) if cui else _falta("radicado"),
        _mayus(md.accionante, "accionante"),
        _accionadas(md),
    )
    for celda, valor in zip(tabla.rows[0].cells, valores):
        celda.text = ""
        par = celda.paragraphs[0]
        formato_b.espaciado(par)
        for trozo in _FALTA.split(valor):
            if not trozo:
                continue
            run = par.add_run(trozo)
            formato_b.fuente(run, FUENTE, TAMANO)
            if _FALTA.fullmatch(trozo):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    _parrafo(doc)
    _parrafo(doc, "Cordialmente,")
    _firma(doc, cfg)
    return _guardar(doc, ruta)


def _origen_digitos(md: Metadatos) -> str:
    if md.juzgado_a_quo_numero is not None and md.juzgado_a_quo_funcion is not None:
        return formulas.juzgado(md, "digitos")
    return _o(md.juzgado_a_quo, "juzgado de origen")


def render_envio_formato(
    md: Metadatos, cfg: Config, adjunto: str | None, ruta: Path, para: str | None = None
) -> Path:
    cui = _cui_1a(md)
    cui_txt = cui or _falta("radicado")
    doc = _base(
        _o(para, "correo del juzgado de origen"),
        f"Envio formato calificación de calidad radicado {cui_txt}",
        _adjunto(adjunto, "formato"),
    )
    _parrafo(doc, "Señores")
    _parrafo(doc, _origen_digitos(md))
    _parrafo(doc, "Cordial saludo,")
    _parrafo(
        doc,
        "Por medio del presente, se remite el Formato Factor Calidad correspondiente a la evaluación "
        "de la sentencia de primera instancia proferida por ese despacho dentro del siguiente proceso:",
    )
    _campo(doc, "Radicado", cui_txt)
    _parrafo(doc, "Adjunto archivo en PDF.")
    _parrafo(doc, "Atentamente,")
    _firma(doc, cfg)
    return _guardar(doc, ruta)


def _texto_compulsa(decision: Decision, md: Metadatos) -> str:
    if decision.compulsa is None:
        return _falta("numeral de compulsa")
    ns = formulas.numerales(decision, md)
    for i, n in enumerate(ns):
        if n.clave == "compulsa":
            return f"{formulas.ordinal(i + 1)}: {n.texto}"
    return _falta("numeral de compulsa")


def render_compulsa(md: Metadatos, decision: Decision, cfg: Config, adjunto: str | None, ruta: Path) -> Path:
    cui = _cui_2a(md)
    doc = _base(
        PARA_REPARTO,
        f"Remisión compulsa copias en tutela radicado: {cui or _falta('radicado')}",
        _adjunto(adjunto, "fallo"),
    )
    organo = decision.compulsa.organo if decision.compulsa else _falta("órgano de la compulsa")
    _parrafo(doc, "Señores")
    _parrafo(doc, "Oficina de Reparto")
    _parrafo(doc, organo)
    _parrafo(
        doc,
        f"Por medio del presente, y dando cumplimiento a lo ordenado por el señor Juez {cfg.despacho.juez} "
        "dentro del fallo adjunto me permito remitirle el link del expediente de la tutela, donde es "
        f"accionante {_mayus(md.accionante, 'accionante')}.",
    )
    _parrafo(doc, "Dicha providencia dispuso lo siguiente:")
    _parrafo(doc, _texto_compulsa(decision, md))
    _parrafo(doc, "Link de acceso al expediente:")
    _parrafo(doc, _falta("link del expediente"))
    _parrafo(doc, "Atentamente,")
    _firma(doc, cfg)
    return _guardar(doc, ruta)
