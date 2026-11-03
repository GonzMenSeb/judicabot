from __future__ import annotations

import hashlib
import re
import shutil
from datetime import date
from pathlib import Path

from tutela2 import radicado, render, salidas
from tutela2.config import Config
from tutela2.documentos import auto as doc_auto
from tutela2.documentos import correos, formato, oficio
from tutela2.festivos import siguiente_habil
from tutela2.letras import _a_fecha
from tutela2.models import DatosAuto, Decision, Ingesta, Metadatos

_CORREO = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_REMITENTE = re.compile(r"^\s*(?:De|Desde)\s*:?(?:\s+|$)", re.IGNORECASE)


def numerados(nombres: list[str]) -> list[str]:
    return [f"{i:03d}{n}" for i, n in enumerate(nombres, 1)]


def auto_efectivo(caso_dir: Path, md: Metadatos, guardado: DatosAuto | None = None) -> DatosAuto:
    base = doc_auto.auto_por_defecto(md)
    ruta = Path(caso_dir) / "auto.json"
    if guardado is None:
        if not ruta.exists():
            return base
        guardado = DatosAuto.model_validate_json(ruta.read_text(encoding="utf-8"))
    efectivo = base.model_copy(update={k: v for k, v in guardado.model_dump().items() if v is not None})
    if guardado.fecha is None and guardado.fecha_reparto:
        reparto = _a_fecha(guardado.fecha_reparto)
        if reparto:
            efectivo.fecha = siguiente_habil(reparto).isoformat()
    return efectivo


def _corto(md: Metadatos) -> str:
    return radicado.corto(md.cui_2a or md.cui_1a or "")


def _acta(caso_dir: Path, ing: Ingesta):
    for d in ing.documentos:
        if d.rol == "acta_reparto_2a" and not d.ruido and d.doc_id not in ing.docs_ajenos:
            origen = Path(caso_dir) / "insumos" / d.ruta
            if origen.is_file():
                return origen
    return None


def _nombres_previos(origen: Path | None, md: Metadatos) -> list[str]:
    nombres = []
    if origen is not None:
        nombres.append(f"ActaRepartoSegunda{origen.suffix.lower()}")
    nombres.append(f"AutoAsumeSegunda{_corto(md)}.docx")
    return nombres


def generar_previos(caso_dir: Path, ing: Ingesta, cfg: Config, auto: DatosAuto) -> list[str]:
    caso_dir = Path(caso_dir)
    carpeta = salidas.principal(caso_dir)
    temporal = carpeta.with_name(carpeta.name + ".tmp")
    shutil.rmtree(temporal, ignore_errors=True)
    temporal.mkdir(parents=True)
    origen = _acta(caso_dir, ing)
    nombres = numerados(_nombres_previos(origen, ing.metadatos))
    try:
        if origen is not None:
            shutil.copyfile(origen, temporal / nombres[0])
        doc_auto.render_auto(ing.metadatos, auto, cfg, temporal / nombres[-1])
    except Exception:
        shutil.rmtree(temporal, ignore_errors=True)
        raise
    shutil.rmtree(carpeta, ignore_errors=True)
    temporal.rename(carpeta)
    return [(carpeta / n).relative_to(salidas.raiz(caso_dir)).as_posix() for n in nombres]


def _buzon_juzgado(ing: Ingesta) -> str | None:
    docs = sorted((d for d in ing.documentos if d.rol == "notificacion"), key=lambda d: d.ruta)
    if not docs:
        return None
    lineas = docs[-1].texto().splitlines()
    for i, linea in enumerate(lineas):
        if _REMITENTE.match(linea):
            bloque = " ".join(lineas[i : i + 2])
            m = _CORREO.search(bloque)
            if m:
                return m.group(0)
    return None


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def generar_final(caso_dir: Path, estado: dict, cfg: Config) -> dict[str, str]:
    caso_dir = Path(caso_dir)
    raiz = salidas.raiz(caso_dir)
    ing = Ingesta.model_validate(estado["ingesta"])
    md = Metadatos.model_validate(estado["metadatos"])
    ing = ing.model_copy(update={"metadatos": md})
    decision = None
    for item in reversed(estado.get("decisiones") or []):
        if item.get("accion") == "decidir":
            decision = Decision.model_validate(item)
            break
    if decision is None:
        raise ValueError("No hay una decisión registrada: no se puede ensamblar el expediente.")

    fecha_fallo = decision.fecha_fallo or date.today().isoformat()
    generados = generar_previos(caso_dir, ing, cfg, auto_efectivo(caso_dir, md))
    origen = _acta(caso_dir, ing)
    corto = _corto(md)
    nombres = _nombres_previos(origen, md) + [f"FalloSegunda{corto}.docx"]
    if decision.generar_formato:
        nombres.append(f"FormatoCalificacion{corto}.docx")
    nombres = numerados(nombres)
    carpeta = salidas.principal(caso_dir)

    fallo = nombres[len(generados)]
    render.render_fallo(estado, cfg, carpeta / fallo)
    generados.append((carpeta / fallo).relative_to(raiz).as_posix())
    formato_nombre = None
    if decision.generar_formato:
        formato_nombre = nombres[-1]
        formato.render_formato(md, decision, cfg, carpeta / formato_nombre)
        generados.append((carpeta / formato_nombre).relative_to(raiz).as_posix())

    por_radicar = salidas.por_radicar(caso_dir)
    oficio.render_oficio(md, decision.fecha_oficio or fecha_fallo, cfg, por_radicar / "OficioRemiteCorteConstitucional.docx")
    generados.append("por_radicar/OficioRemiteCorteConstitucional.docx")

    borr = salidas.borradores(caso_dir)
    correos.render_notificacion(md, ing, cfg, fallo, borr / "NotificacionFalloPartes.docx")
    generados.append("borradores_correo/NotificacionFalloPartes.docx")
    if formato_nombre:
        correos.render_envio_formato(md, cfg, formato_nombre, borr / "EnvioFormatoCalidad.docx", para=_buzon_juzgado(ing))
        generados.append("borradores_correo/EnvioFormatoCalidad.docx")
    if decision.compulsa:
        correos.render_compulsa(md, decision, cfg, fallo, borr / "RemisionCompulsaCopias.docx")
        generados.append("borradores_correo/RemisionCompulsaCopias.docx")

    trabajo = salidas.trabajo(caso_dir)
    render.render_informe(estado, cfg, trabajo / "informe_verificacion.docx")
    render.render_declaracion_ia(estado, cfg, trabajo / "declaracion_ia.docx")
    generados += ["trabajo/informe_verificacion.docx", "trabajo/declaracion_ia.docx"]

    return {rel: _sha(raiz / rel) for rel in generados}
