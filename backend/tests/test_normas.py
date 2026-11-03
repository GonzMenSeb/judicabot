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


@pytest.mark.parametrize(
    "prosa",
    [
        "Según el art. 30 C.P.P. la competencia es del juez penal.",
        "Conforme al artículo 25 C.P.C., la demanda debe contener los requisitos.",
        "El art. 137 C.P.A.C.A. regula la nulidad.",
        "El artículo 6 C.P.T. y de la S.S. regula la reclamación.",
        "Según el art. 30 C. P. P. la competencia es del juez penal.",
    ],
)
def test_abreviaturas_de_codigos_no_son_constitucion(prosa):
    assert textos(prosa) == []


def test_alias_cp_con_espacio():
    assert textos("art. 86 C. P. consagra la tutela.") == ["artículo 86 de la Constitución Política"]


@pytest.mark.parametrize(
    "prosa, esperado",
    [
        (
            "El Decreto 2591 de 1991, que reglamenta la acción constitucional de tutela, en su artículo 6 fija las causales.",
            ["artículo 6 del Decreto 2591 de 1991"],
        ),
        (
            "La Ley 1751 de 2015, estatutaria del derecho constitucional a la salud, en su artículo 6 fija los principios.",
            ["artículo 6 de la Ley 1751 de 2015"],
        ),
        (
            "La Ley 906 de 2004, aplicada por el Tribunal Superior, artículo 30.",
            ["artículo 30 de la Ley 906 de 2004"],
        ),
    ],
)
def test_superior_lejos_de_un_articulo_no_corta_la_ventana(prosa, esperado):
    assert textos(prosa) == esperado


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


@pytest.mark.parametrize(
    ("prosa", "esperado"),
    [
        (
            "En virtud de la Ley 1751 de 2015 y del mandato constitucional contenido en el artículo 49, se decide.",
            ["Ley 1751 de 2015"],
        ),
        (
            "El Decreto 2591 de 1991 desarrolla el mecanismo constitucional del artículo 86 de la Carta.",
            ["Decreto 2591 de 1991"],
        ),
        (
            "La Ley 100 de 1993 y la norma superior del artículo 48 fijan el sistema.",
            ["Ley 100 de 1993"],
        ),
        (
            "El Decreto 2591 de 1991, que reglamenta la acción constitucional de tutela, en su artículo 6 fija las causales.",
            ["artículo 6 del Decreto 2591 de 1991"],
        ),
        ("Ley 906 de 2004, aplicada por el Tribunal Superior, artículo 30.", ["artículo 30 de la Ley 906 de 2004"]),
    ],
)
def test_articulo_constitucional_posterior_no_se_atribuye_a_la_norma_previa(prosa, esperado):
    assert textos(prosa) == esperado


@pytest.mark.parametrize("parte", ["inciso 2", "numeral 3", "literal b", "parágrafo 1", "inciso final"])
def test_parte_de_articulo_de_norma_constitucional_no_corta_la_ventana(parte):
    prosa = f"la Ley 1755 de 2015, de rango constitucional, en el {parte} del artículo 14 fija el término"
    assert textos(prosa) == ["artículo 14 de la Ley 1755 de 2015"]


@pytest.mark.parametrize("pad", range(0, 10))
def test_numero_de_articulo_no_se_parte_en_el_limite_de_la_ventana(pad):
    cabeza = "La Ley 1437 de 2011,"
    cola = " en el inciso final del artículo 145 fija el término"
    corte = cola.index("145") + 2
    relleno = " " + "x" * (80 - corte + pad - 1)
    assert textos(cabeza + relleno + cola) == ["artículo 145 de la Ley 1437 de 2011"]


@pytest.mark.parametrize(
    "prosa,esperado",
    [
        ("La Ley 1751 de 2015 desarrolla el mandato constitucional del inciso 2 del artículo 49.", ["Ley 1751 de 2015"]),
        (
            "El Decreto 2591 de 1991 reglamenta el mecanismo constitucional previsto en el inciso 1 del artículo 86.",
            ["Decreto 2591 de 1991"],
        ),
        (
            "La Ley 1755 de 2015 protege el derecho constitucional consagrado en el inciso 1 del artículo 23.",
            ["Ley 1755 de 2015"],
        ),
        ("La Ley 100 de 1993 recoge el principio superior del numeral 3 del artículo 48.", ["Ley 100 de 1993"]),
    ],
)
def test_adjetivo_constitucional_gobierna_el_inciso_y_corta(prosa, esperado):
    assert textos(prosa) == esperado


def test_inciso_introducido_por_separado_sigue_exento():
    prosa = "la Ley 1755 de 2015, de rango constitucional, en su inciso 2 del artículo 14 fija el término"
    assert textos(prosa) == ["artículo 14 de la Ley 1755 de 2015"]


@pytest.mark.parametrize("pad", range(56, 72, 2))
def test_lista_larga_de_articulos_no_se_trunca(pad):
    lista = "en los artículos 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24 y 25 fijan"
    prosa = "La Ley 1437 de 2011," + " " + "x" * (pad - 2) + " " + lista
    esperado = [f"artículo {n} de la Ley 1437 de 2011" for n in range(14, 26)]
    assert textos(prosa) == esperado


def test_lista_larga_se_detiene_en_punto_y_no_parte_numeros_con_puntos():
    prosa = "La Ley 1437 de 2011, " + "x" * 60 + " en los artículos 14, 15 y 16. Luego el artículo 2.2.3.1 del Decreto 1069 de 2015"
    assert textos(prosa) == [
        "artículo 14 de la Ley 1437 de 2011",
        "artículo 15 de la Ley 1437 de 2011",
        "artículo 16 de la Ley 1437 de 2011",
        "artículo 2.2.3.1 del Decreto 1069 de 2015",
    ]
