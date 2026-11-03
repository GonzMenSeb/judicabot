import pytest

from tutela2 import letras
from tutela2.render import numero_a_letras as render_numero


def test_fecha_larga_dos_cifras():
    assert letras.fecha_larga("2026-10-06") == "seis (06) de octubre de dos mil veintiséis (2026)"
    assert letras.fecha_larga("2026-10-21") == "veintiuno (21) de octubre de dos mil veintiséis (2026)"
    assert letras.fecha_larga("2026-10-01") == "uno (01) de octubre de dos mil veintiséis (2026)"


@pytest.mark.parametrize("valor", [None, "", "2026-13-01", "basura"])
def test_fecha_invalida(valor):
    assert letras.fecha_larga(valor) == "⟦FALTA: fecha⟧"
    assert letras.fecha_corta(valor) == "⟦FALTA: fecha⟧"


def test_fecha_corta():
    assert letras.fecha_corta("2026-09-21") == "21 de septiembre de 2026"


@pytest.mark.parametrize("n", [0, 1, 21, 31, 100, 101, 999, 1000, 2026, 21000, 21001, 999999])
@pytest.mark.parametrize("genero", ["", "m", "f"])
def test_numero_a_letras_igual_a_render(n, genero):
    assert letras.numero_a_letras(n, genero) == render_numero(n, genero)


def test_numero_a_letras_fuera_de_rango():
    with pytest.raises(ValueError):
        letras.numero_a_letras(1_000_000)


@pytest.mark.parametrize(
    "n,esperado",
    [(18, "Dieciocho"), (47, "Cuarenta y Siete"), (21, "Veintiuno"), (3, "Tres"), (100, "Cien")],
)
def test_numero_titulo(n, esperado):
    assert letras.numero_titulo(n) == esperado


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Dieciocho", 18),
        ("Cuarenta y Siete", 47),
        ("Décimo", 10),
        ("decimo", 10),
        ("Veintidós", 22),
        ("veintidos", 22),
        ("primero", 1),
        ("VIGÉSIMO SEGUNDO", 22),
        ("  Cuarenta   y siete ", 47),
        ("xyz", None),
        ("", None),
    ],
)
def test_letras_a_numero(texto, esperado):
    assert letras.letras_a_numero(texto) == esperado


def test_ida_y_vuelta():
    for n in range(1, 200):
        assert letras.letras_a_numero(letras.numero_titulo(n)) == n
