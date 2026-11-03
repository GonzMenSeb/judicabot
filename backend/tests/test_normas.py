import pytest

from tutela2.normas import extraer_normas


def textos(prosa: str) -> list[str]:
    return [c.texto for c in extraer_normas(prosa)]


def test_articulo_de_decreto():
    prosa = "Conforme al artículo 32 del Decreto 2591 de 1991, la impugnación se resuelve en veinte días."
    [c] = extraer_normas(prosa)
    assert c.texto == "artículo 32 del Decreto 2591 de 1991"
    assert c.norma == "Decreto 2591 de 1991" and c.articulo == "32"
    assert "la impugnación se resuelve" in c.contexto


def test_varios_articulos():
    assert textos("Los artículos 19, 20 y 22 del Decreto 2591 de 1991 regulan la prueba.") == [
        "artículo 19 del Decreto 2591 de 1991",
        "artículo 20 del Decreto 2591 de 1991",
        "artículo 22 del Decreto 2591 de 1991",
    ]


def test_ley_modificada_por_otra_ley():
    prosa = "Según el artículo 41 de la Ley 1122 de 2007, modificado por la Ley 1949 de 2019, la Superintendencia decide."
    assert textos(prosa) == ["artículo 41 de la Ley 1122 de 2007", "Ley 1949 de 2019"]


def test_codigo_y_constitucion():
    prosa = "El artículo 25 del Código General del Proceso y el artículo 86 de la Constitución Política."
    assert textos(prosa) == [
        "artículo 25 del Código General del Proceso",
        "artículo 86 de la Constitución Política",
    ]


def test_ley_primero_y_articulo_despues():
    prosa = "La Ley 1751 de 2015 consagra en su artículo 6 los elementos del derecho a la salud."
    [c] = extraer_normas(prosa)
    assert c.texto == "artículo 6 de la Ley 1751 de 2015"


def test_ley_sin_articulo_y_sin_duplicados():
    prosa = "La Ley 100 de 1993 organiza el sistema. La Ley 100 de 1993 se aplica. El artículo 49 de la Constitución Política."
    assert textos(prosa) == ["Ley 100 de 1993", "artículo 49 de la Constitución Política"]


def test_distintas_en_orden_y_sin_repetir():
    prosa = (
        "El artículo 86 de la Constitución Política y el artículo 25 del Decreto 2591 de 1991; "
        "de nuevo el artículo 86 de la Constitución Política."
    )
    assert textos(prosa) == ["artículo 86 de la Constitución Política", "artículo 25 del Decreto 2591 de 1991"]


def test_bare_ley_se_omite_si_hay_articulo_de_la_misma_ley():
    prosa = "La Ley 1751 de 2015 es estatutaria. El artículo 6 de la Ley 1751 de 2015 lista elementos."
    assert textos(prosa) == ["artículo 6 de la Ley 1751 de 2015"]


@pytest.mark.parametrize("prosa", ["", "Sin normas en este párrafo.", "El artículo 6 dispone lo anterior."])
def test_sin_citas(prosa):
    assert extraer_normas(prosa) == []


def test_articulos_del_acuerdo_y_resolucion():
    prosa = "El artículo 10 del Acuerdo PCSJA24-12243 de 2024 y el artículo 3 de la Resolución 500 de 2020."
    assert textos(prosa) == [
        "artículo 10 del Acuerdo PCSJA24-12243 de 2024",
        "artículo 3 de la Resolución 500 de 2020",
    ]


def test_articulo_posterior_superior_no_se_atribuye_a_la_ley_previa():
    prosa = "La Ley 100 de 1993 creó el sistema, y el artículo 49 superior consagra la salud."
    assert textos(prosa) == ["Ley 100 de 1993", "artículo 49 de la Constitución Política"]


@pytest.mark.parametrize(
    "prosa",
    [
        "El art. 86 C.P. consagra la tutela.",
        "El artículo 86 Superior consagra la tutela.",
        "Se invoca el art. 86 de la C.P.",
        "Se invoca el artículo 86 constitucional.",
    ],
)
def test_alias_de_constitucion(prosa):
    assert textos(prosa) == ["artículo 86 de la Constitución Política"]


def test_alias_cn():
    assert textos("art. 23 de la C.N.") == ["artículo 23 de la Constitución Política"]


def test_decreto_con_fecha_completa():
    assert textos("El Decreto 2591 del 19 de noviembre de 1991 regula la tutela.") == ["Decreto 2591 de 1991"]


def test_rango_de_articulos():
    assert textos("Según los artículos 19 al 22 del Decreto 2591 de 1991.") == [
        f"artículo {n} del Decreto 2591 de 1991" for n in (19, 20, 21, 22)
    ]


def test_articulo_con_letra():
    assert textos("El artículo 20A de la Ley 100 de 1993.") == ["artículo 20A de la Ley 100 de 1993"]


def test_ley_estatutaria_se_normaliza_y_deduplica():
    prosa = "El artículo 6 de la Ley Estatutaria 1751 de 2015 y la Ley 1751 de 2015."
    [c] = extraer_normas(prosa)
    assert c.norma == "Ley 1751 de 2015" and c.texto == "artículo 6 de la Ley 1751 de 2015"


def test_constitucion_sin_articulo_no_es_cita():
    assert textos("Los derechos que consagra la Constitución son fundamentales.") == []


@pytest.mark.parametrize("prosa", ["", "   \n\n ", "artículo", "artículo de la", "Ley de", "art. C.P."])
def test_entradas_vacias_o_degeneradas(prosa):
    extraer_normas(prosa)
