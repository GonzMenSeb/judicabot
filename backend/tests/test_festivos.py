from datetime import date

import pytest

from tutela2.festivos import es_festivo, festivos, pascua, siguiente_habil

OFICIAL = {
    2026: ["01-01", "01-12", "03-23", "04-02", "04-03", "05-01", "05-18", "06-08", "06-15", "06-29",
           "07-13", "07-20", "08-07", "08-17", "10-12", "11-02", "11-16", "12-08", "12-25"],
    2027: ["01-01", "01-11", "03-22", "03-25", "03-26", "05-01", "05-10", "05-31", "06-07", "07-05",
           "07-12", "07-20", "08-07", "08-16", "10-18", "11-01", "11-15", "12-08", "12-25"],
}


@pytest.mark.parametrize("anio", [2026, 2027])
def test_lista_anual_fijada(anio):
    assert sorted(festivos(anio)) == [date.fromisoformat(f"{anio}-{x}") for x in OFICIAL[anio]]


@pytest.mark.parametrize("anio,esperada", [(2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2024, date(2024, 3, 31))])
def test_pascua(anio, esperada):
    assert pascua(anio) == esperada


def test_es_festivo_y_siguiente_habil():
    assert es_festivo(date(2026, 10, 12)) and not es_festivo(date(2026, 10, 13))
    assert siguiente_habil(date(2026, 10, 9)) == date(2026, 10, 13)
    assert siguiente_habil(date(2026, 4, 1)) == date(2026, 4, 6)
    assert siguiente_habil(date(2026, 9, 11)) == date(2026, 9, 14)


def test_chiquinquira_desde_2026():
    assert len(festivos(2026)) == len(festivos(2027)) == 19
    assert siguiente_habil(date(2027, 7, 9)) == date(2027, 7, 13)
    assert siguiente_habil(date(2026, 7, 10)) == date(2026, 7, 14)
    assert len(festivos(2025)) == 17
    assert date(2025, 7, 14) not in festivos(2025) and date(2025, 7, 9) not in festivos(2025)
