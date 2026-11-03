import pytest

from tutela2 import radicado
from tutela2.radicado import Juzgado

CUI = "05001408801820260053001"


def test_formas_del_radicado():
    assert radicado.corto(CUI) == "202600530"
    assert radicado.espaciado(CUI) == "050014088018 2026 00530 01"
    assert radicado.con_guion(CUI) == "050014088018202600530-01"
    assert radicado.cui_1a(CUI) == "05001408801820260053000"
    assert radicado.cui_2a("05001408801820260053000") == CUI


def test_digitos_ignora_separadores():
    assert radicado.digitos("05001 40 88 018-2026.00530") == "050014088018202600530"
    assert radicado.corto("050014088018 2026 00530 01") == "202600530"


def test_juzgado_control_garantias():
    j = radicado.juzgado_de_radicado(CUI)
    assert j == Juzgado(18, "control_garantias", "Dieciocho")


def test_juzgado_conocimiento():
    j = radicado.juzgado_de_radicado("05001400904720260049501")
    assert j.numero == 47 and j.funcion == "conocimiento" and j.letras == "Cuarenta y Siete"


def test_juzgado_no_penal_municipal():
    assert radicado.juzgado_de_radicado("05001310400320260000101") is None
    assert radicado.juzgado_de_radicado("") is None


@pytest.mark.parametrize(
    "forma,esperado",
    [
        ("cuerpo", "Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín"),
        ("cuerpo_numero", "Juzgado Dieciocho (18) Penal Municipal con Función de Control de Garantías de Medellín"),
        ("digitos", "Juzgado 18 Penal Municipal con Función de Control de Garantías de Medellín"),
        ("encabezado", "JUZGADO 18 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN"),
    ],
)
def test_nombre_juzgado(forma, esperado):
    assert radicado.nombre_juzgado(radicado.juzgado_de_radicado(CUI), forma) == esperado


def test_nombre_juzgado_conocimiento_plural():
    j = Juzgado(47, "conocimiento", "Cuarenta y Siete", plural=True)
    assert radicado.nombre_juzgado(j, "cuerpo") == (
        "Juzgado Cuarenta y Siete Penal Municipal con Funciones de Conocimiento de Medellín"
    )
