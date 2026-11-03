from __future__ import annotations

import importlib.util
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from docx import Document
from docx.oxml.ns import qn

from tutela2 import api, formulas, radicado
from tutela2.config import Config, LLMConfig
from tutela2.ingest import ingerir
from tutela2.models import Decision, Ingesta

REFERENCIA = Path(__file__).resolve().parents[2] / "referencia"
CASOS = REFERENCIA / "casos"

pytestmark = [
    pytest.mark.aceptacion,
    pytest.mark.skipif(not CASOS.is_dir(), reason="no existe referencia/casos"),
]

ROLES = {
    "escrito_tutela",
    "fallo_a_quo",
    "impugnacion",
    "auto_admisorio",
    "auto_concede_impugnacion",
    "acta_reparto_2a",
}
ROLES_ANONIMA = ROLES
CASO_SIN_ACTA = "05001408802520260040601"
CASO_COMPULSA = "05001408802220260012001"
PRINCIPAL = "02SegundaInstancia/C01Principal"
COMPARACION = REFERENCIA / "comparacion_visual"
FALLOS_REFERENCIA = {
    "05001408801820260053001": "003FalloSegundaInstanciaRevoca.pdf",
    "05001408802220260012001": "005FalloSegunda.pdf",
}
CASOS_FORMA_B = ("05001400904720260034601", "05001408804320260045901")
FORMA_B_ALTERNA = ("05001400904720260034601",)


def _verdad() -> dict[str, dict]:
    ruta = REFERENCIA / "analisis" / "ground_truth_1a.json"
    if not ruta.is_file():
        return {}
    return {c["case"]: c for c in json.loads(ruta.read_text(encoding="utf-8"))}


VERDAD = _verdad()
TODOS = sorted(VERDAD)


def _primera(caso: str) -> Path:
    return CASOS / caso / "01PrimeraInstancia"


def _archivos_primera(caso: str) -> list[Path]:
    base = _primera(caso)
    return sorted(
        (p for p in base.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(base).as_posix().casefold(),
    )


def _preparar_a(caso: str, destino: Path) -> Path:
    insumos = destino / caso / "insumos"
    shutil.copytree(_primera(caso), insumos)
    return destino / caso


def _preparar_b(caso: str, destino: Path) -> Path:
    insumos = destino / caso / "insumos"
    shutil.copytree(CASOS / caso, insumos)
    return destino / caso


def _preparar_anonima(caso: str, destino: Path) -> tuple[Path, dict[str, str]]:
    insumos = destino / caso / "insumos" / "C01Principal"
    insumos.mkdir(parents=True)
    equivalencia: dict[str, str] = {}
    for i, origen in enumerate(_archivos_primera(caso), start=1):
        anonimo = f"{i:03d}{origen.suffix}"
        shutil.copy2(origen, insumos / anonimo)
        equivalencia[anonimo] = origen.name
    return destino / caso, equivalencia


def _diferencias(
    caso: str, ing: Ingesta, roles: set[str], equivalencia: dict[str, str] | None = None
) -> list[str]:
    verdad = {}
    for d in VERDAD[caso]["docs"]:
        nombre = Path(d["file"]).name
        assert nombre not in verdad, f"{caso}: nombre repetido en la verdad: {nombre}"
        verdad[nombre] = d
    equivalencia = equivalencia or {}
    prediccion = {}
    for doc in ing.documentos:
        if doc.instancia != "1a":
            continue
        nombre = equivalencia.get(doc.nombre, doc.nombre)
        prediccion[nombre] = doc
    diffs: list[str] = []
    for nombre in sorted(set(verdad) | set(prediccion)):
        v = verdad.get(nombre)
        doc = prediccion.get(nombre)
        esperado = v["role"] if v else "(no existe en la verdad)"
        obtenido = doc.rol if doc else "(no leído)"
        evidencia = doc.evidencia if doc else ""
        if v is None:
            if obtenido in roles:
                diffs.append(f"{nombre}: esperado {esperado}, obtenido {obtenido} (evidencia: {evidencia})")
            continue
        if obtenido in roles:
            malo = obtenido != esperado
        else:
            malo = esperado in roles and v["confidence"] != "medium"
        if malo:
            diffs.append(f"{nombre}: esperado {esperado}, obtenido {obtenido} (evidencia: {evidencia})")
    return diffs


def _por_prefijo(ing: Ingesta, prefijo: str):
    docs = [d for d in ing.documentos if d.nombre.startswith(prefijo)]
    assert len(docs) == 1, f"se esperaba un documento con prefijo {prefijo!r}, hay {len(docs)}"
    return docs[0]


def _sin_diferencias(diffs: list[str]) -> None:
    assert not diffs, "\n" + "\n".join(diffs)


@pytest.mark.parametrize("caso", TODOS)
def test_ingesta_forma_a(caso: str, tmp_path: Path) -> None:
    ing = ingerir(_preparar_a(caso, tmp_path), Config())
    _sin_diferencias(_diferencias(caso, ing, ROLES))
    assert ing.faltantes == []
    if caso == "05001400904720260034601":
        assert _por_prefijo(ing, "022SentenciaTutela02072024").rol != "fallo_a_quo"
        assert _por_prefijo(ing, "025ImpugancionAccionante").rol == "impugnacion"


@pytest.mark.parametrize("caso", CASOS_FORMA_B)
def test_ingesta_forma_b(caso: str, tmp_path: Path) -> None:
    ing = ingerir(_preparar_b(caso, tmp_path), Config())
    _sin_diferencias(_diferencias(caso, ing, ROLES))
    assert ing.faltantes == []
    assert ing.ignorados
    en_segunda = [d.ruta for d in ing.documentos if any(p.casefold().startswith("02segunda") for p in Path(d.ruta).parts)]
    assert en_segunda == []
    if caso in FORMA_B_ALTERNA:
        assert _por_prefijo(ing, "022SentenciaTutela02072024").rol != "fallo_a_quo"
        assert _por_prefijo(ing, "025ImpugancionAccionante").rol == "impugnacion"


@pytest.mark.parametrize("caso", TODOS)
def test_ingesta_anonima(caso: str, tmp_path: Path) -> None:
    caso_dir, equivalencia = _preparar_anonima(caso, tmp_path)
    ing = ingerir(caso_dir, Config())
    assert ing.faltantes == []
    _sin_diferencias(_diferencias(caso, ing, ROLES_ANONIMA, equivalencia))


@pytest.mark.parametrize("caso", TODOS)
def test_decision_fixture_valida(caso: str) -> None:
    ruta = REFERENCIA / "decisiones" / f"{caso}.json"
    assert ruta.is_file(), f"falta {ruta}"
    decision = Decision.model_validate_json(ruta.read_text(encoding="utf-8"))
    assert decision.errores() == []
    assert decision.decidido_por == "prueba"


def _plano(texto: str) -> str:
    return " ".join(texto.split())


def _preparar_fake(caso: str, destino: Path) -> Path:
    caso_dir = _preparar_a(caso, destino)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (caso_dir / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    return caso_dir


def _esperadas(caso_dir: Path, decision: Decision, con_acta: bool) -> tuple[list[str], str, str | None]:
    ing = Ingesta.model_validate_json((caso_dir / "caso.json").read_text(encoding="utf-8"))
    corto = radicado.corto(ing.metadatos.cui_2a)
    nombres = (["ActaRepartoSegunda.pdf"] if con_acta else []) + [f"AutoAsumeSegunda{corto}.docx", f"FalloSegunda{corto}.docx"]
    formato = f"FormatoCalificacion{corto}.docx" if decision.generar_formato else None
    if formato:
        nombres.append(formato)
    numerados = [f"{PRINCIPAL}/{i:03d}{n}" for i, n in enumerate(nombres, 1)]
    fallo = next(n for n in numerados if "FalloSegunda" in n)
    return numerados, fallo, formato


def _comprobar_formato_fallo(ruta: Path, decision: Decision, cfg: Config) -> None:
    doc = Document(ruta)
    seccion = doc.sections[0]
    assert abs(seccion.page_width.pt - 597.48) <= 0.5
    assert abs(seccion.page_height.pt - 966.0) <= 0.5
    assert seccion.header._element.findall(".//" + qn("w:drawing")) or seccion.header._element.findall(".//" + qn("w:pict"))
    pie = [p.text.strip() for p in seccion.footer.paragraphs]
    for linea in cfg.despacho.pie_fallo:
        assert linea in pie

    parrafos = list(doc.paragraphs)
    textos = [_plano(p.text) for p in parrafos]
    titulos = [p.text for p in parrafos if re.match(r"^[IVX]+\.\t", p.text)]
    assert len(titulos) >= 7, titulos

    cuerpo = next(p for p in parrafos if _plano(p.text) == _plano(formulas.COMPETENCIA_1))
    assert cuerpo.runs and all(r.font.name == "Bookman Old Style" and r.font.size.pt == 12 for r in cuerpo.runs if r.text.strip())
    spacing = cuerpo._p.pPr.find(qn("w:spacing"))
    assert spacing.get(qn("w:line")) == "360" and spacing.get(qn("w:lineRule")) == "auto"

    plano = "\n".join(textos)
    for fijo in (
        formulas.COMPETENCIA_1,
        formulas.PROCEDIBILIDAD_P1,
        formulas.PROCEDIBILIDAD_P2,
        formulas.TRANSICION,
        formulas.MERITO_DESPUES,
    ):
        assert _plano(fijo) in plano
    if decision.numerales.remitir_corte:
        assert "REMITIR el expediente a la Honorable Corte Constitucional para su eventual revisión." in plano

    primero = next(p for p in parrafos if p.text.startswith("PRIMERO: "))
    assert primero.runs[0].bold and primero.runs[0].text.startswith("PRIMERO")


def _texto_docx(ruta: Path) -> str:
    cuerpo = Document(ruta).element.body
    return "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in cuerpo.iter(qn("w:p")))


def _comprobar_salidas_generales(
    caso: str, caso_dir: Path, salidas_dir: Path, principal: list[str], fallo: str, fecha_auto: str | None
) -> None:
    ing = Ingesta.model_validate_json((caso_dir / "caso.json").read_text(encoding="utf-8"))
    auto = next(n for n in principal if "AutoAsumeSegunda" in n)
    textos = {
        "fallo": _texto_docx(salidas_dir / fallo),
        "auto": _texto_docx(salidas_dir / auto),
        "oficio": _texto_docx(salidas_dir / "por_radicar/OficioRemiteCorteConstitucional.docx"),
    }
    for nombre, texto in textos.items():
        assert "SIN DOCUMENTO" not in texto, nombre
        assert not re.search(r"\bSD\b", texto), nombre

    correo = _texto_docx(salidas_dir / "borradores_correo/NotificacionFalloPartes.docx")
    para = [linea for linea in correo.splitlines() if linea.startswith("Para")]
    assert para, "sin línea Para"
    for linea in para:
        assert "⟦FALTA" not in linea, linea
        assert not re.search(r"microsoftexchange|postmaster|noreply|no-reply|mailer-daemon", linea, re.I), linea

    reparto = ing.metadatos.fechas.reparto_2a
    if reparto:
        dia_reparto = date.fromisoformat(reparto)
        dia_auto = date.fromisoformat(fecha_auto)
        assert dia_auto.weekday() < 5, fecha_auto
        assert dia_auto > dia_reparto, (fecha_auto, reparto)
        if dia_auto != dia_reparto + timedelta(days=1):
            assert "el día de ayer" not in textos["auto"]

    if caso == "05001408801820260053001":
        filas = [
            " ".join(c.text for c in fila.cells)
            for tabla in Document(salidas_dir / fallo).tables
            for fila in tabla.rows
            if fila.cells[0].text.strip().upper().startswith("PROCEDENCIA")
        ]
        assert filas, "sin fila Procedencia"
        assert any("CON FUNCIÓN DE CONTROL" in f for f in filas), filas
        assert not any("FUNCIONES" in f for f in filas), filas

    assert ing.metadatos.fechas.fallo_a_quo == VERDAD[caso]["fallo_a_quo_date"]


def _comparar_visual():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "comparar_visual.py"
    spec = importlib.util.spec_from_file_location("comparar_visual", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.comparar


@pytest.mark.parametrize("caso", TODOS)
def test_punta_a_punta(caso: str, tmp_path: Path) -> None:
    caso_dir = _preparar_fake(caso, tmp_path)
    decision_json = json.loads((REFERENCIA / "decisiones" / f"{caso}.json").read_text(encoding="utf-8"))
    decision = Decision.model_validate(decision_json)
    cfg = Config()

    r = api.nuevo(caso_dir)
    assert r["estado"] == "revision", r["error"]
    fecha_auto = r["resumen"]["auto"]["fecha"]
    r = api.iniciar(caso_dir)
    assert r["estado"] == "esperando_decision", r["error"]
    r = api.decidir(caso_dir, decision_json)
    assert r["estado"] == "terminado", r["error"]

    con_acta = caso != CASO_SIN_ACTA
    principal, fallo, formato = _esperadas(caso_dir, decision, con_acta)
    esperadas = set(principal) | {
        "por_radicar/OficioRemiteCorteConstitucional.docx",
        "borradores_correo/NotificacionFalloPartes.docx",
        "trabajo/previo.docx",
        "trabajo/informe_verificacion.docx",
        "trabajo/declaracion_ia.docx",
    }
    if formato:
        esperadas.add("borradores_correo/EnvioFormatoCalidad.docx")
    if caso == CASO_COMPULSA:
        esperadas.add("borradores_correo/RemisionCompulsaCopias.docx")
    assert [s for s in r["salidas"] if s.startswith("trabajo/requerimiento")] == []
    assert set(r["salidas"]) == esperadas, sorted(set(r["salidas"]) ^ esperadas)
    assert (decision.compulsa is not None) == (caso == CASO_COMPULSA)

    salidas_dir = caso_dir / "salidas"
    if con_acta:
        ing = Ingesta.model_validate_json((caso_dir / "caso.json").read_text(encoding="utf-8"))
        acta = next(d for d in ing.documentos if d.rol == "acta_reparto_2a" and not d.ruido)
        assert (salidas_dir / principal[0]).read_bytes() == (caso_dir / "insumos" / acta.ruta).read_bytes()
    else:
        assert not any("ActaReparto" in n for n in r["salidas"])

    _comprobar_formato_fallo(salidas_dir / fallo, decision, cfg)
    _comprobar_salidas_generales(caso, caso_dir, salidas_dir, principal, fallo, fecha_auto)

    if caso in FALLOS_REFERENCIA:
        referencia = CASOS / caso / "02SegundaInstancia" / "C01Principal" / FALLOS_REFERENCIA[caso]
        destino = salidas_dir / "trabajo" / "comparacion_visual"
        pngs = _comparar_visual()(salidas_dir / fallo, referencia, destino)
        assert len(pngs) == 3 and all(p.is_file() for p in pngs)
        persistente = COMPARACION / caso
        shutil.rmtree(persistente, ignore_errors=True)
        shutil.copytree(destino, persistente)
