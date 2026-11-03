from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from tutela2 import radicado
from tutela2.models import Ingesta

pytestmark = pytest.mark.skipif(
    not (shutil.which("soffice") and shutil.which("pdftotext")), reason="requiere soffice y pdftotext"
)

ROLES = {
    "001.pdf": "acta_reparto_1a",
    "002.pdf": "escrito_tutela",
    "003.pdf": "auto_admisorio",
    "004.pdf": "contestacion",
    "005.pdf": "fallo_a_quo",
    "006.pdf": "impugnacion",
    "007.pdf": "auto_concede_impugnacion",
    "008.pdf": "notificacion",
    "009.pdf": "acta_reparto_2a",
}


def _modulo():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "caso_sintetico.py"
    spec = importlib.util.spec_from_file_location("caso_sintetico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def caso(tmp_path_factory) -> tuple[object, Path, dict]:
    modulo = _modulo()
    carpeta = tmp_path_factory.mktemp("sintetico")
    modulo.generar(carpeta)
    modulo.preparar(carpeta, "fake")
    resultados = modulo.ejecutar(carpeta, modulo.DECISION_POR_DEFECTO)
    return modulo, carpeta, resultados


def _ingesta(carpeta: Path) -> Ingesta:
    return Ingesta.model_validate_json((carpeta / "caso.json").read_text(encoding="utf-8"))


def test_genera_nueve_pdf_con_nombres_neutros(caso) -> None:
    _, carpeta, _ = caso
    nombres = sorted(p.name for p in (carpeta / "01PrimeraInstancia" / "C01Principal").iterdir())
    assert nombres == sorted(ROLES)


def test_ingesta_completa(caso) -> None:
    _, carpeta, resultados = caso
    assert resultados["nuevo"]["estado"] == "revision", resultados["nuevo"]["error"]
    ing = _ingesta(carpeta)
    assert ing.faltantes == []
    assert ing.esperados_faltantes == []
    assert ing.docs_ajenos == []


def test_clasifica_los_nueve_documentos(caso) -> None:
    _, carpeta, _ = caso
    obtenidos = {d.nombre: d.rol for d in _ingesta(carpeta).documentos}
    assert obtenidos == ROLES


def test_juzgado_de_origen_es_el_noveno_de_control_de_garantias(caso) -> None:
    _, carpeta, _ = caso
    meta = _ingesta(carpeta).metadatos
    assert meta.juzgado_a_quo_numero == 9
    assert meta.juzgado_a_quo_funcion == "control_garantias"
    assert meta.juzgado_a_quo_derivado is False
    assert meta.juzgado_a_quo == "Juzgado Noveno Penal Municipal con Función de Control de Garantías de Medellín"
    assert meta.cui_2a == meta.cui_1a[:21] + "01"


def test_flujo_completo_fake_termina_con_el_arbol_de_salidas(caso) -> None:
    modulo, carpeta, resultados = caso
    assert resultados["iniciar"]["estado"] == "esperando_decision", resultados["iniciar"]["error"]
    r = resultados["decidir"]
    assert r["estado"] == "terminado", r["error"]
    corto = radicado.corto(_ingesta(carpeta).metadatos.cui_2a)
    esperadas = {
        "02SegundaInstancia/C01Principal/001ActaRepartoSegunda.pdf",
        f"02SegundaInstancia/C01Principal/002AutoAsumeSegunda{corto}.docx",
        f"02SegundaInstancia/C01Principal/003FalloSegunda{corto}.docx",
        f"02SegundaInstancia/C01Principal/004FormatoCalificacion{corto}.docx",
        "borradores_correo/EnvioFormatoCalidad.docx",
        "borradores_correo/NotificacionFalloPartes.docx",
        "por_radicar/OficioRemiteCorteConstitucional.docx",
        "trabajo/declaracion_ia.docx",
        "trabajo/informe_verificacion.docx",
        "trabajo/previo.docx",
    }
    assert set(r["salidas"]) == esperadas, sorted(set(r["salidas"]) ^ esperadas)
