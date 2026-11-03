from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

FIJOS = {(1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25)}
EMILIANI = {(1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11)}
EMILIANI_2026 = {(7, 9)}
PASCUA = (-3, -2, 43, 64, 71)


def pascua(anio: int) -> date:
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mes, dia = divmod(h + ll - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _lunes_siguiente(dia: date) -> date:
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


@lru_cache(maxsize=None)
def festivos(anio: int) -> frozenset[date]:
    dias = {date(anio, m, d) for m, d in FIJOS}
    movidos = EMILIANI | EMILIANI_2026 if anio >= 2026 else EMILIANI
    dias |= {_lunes_siguiente(date(anio, m, d)) for m, d in movidos}
    p = pascua(anio)
    dias |= {p + timedelta(days=n) for n in PASCUA}
    return frozenset(dias)


def es_festivo(dia: date) -> bool:
    return dia in festivos(dia.year)


def es_habil(dia: date) -> bool:
    return dia.weekday() < 5 and not es_festivo(dia)


def siguiente_habil(dia: date) -> date:
    dia += timedelta(days=1)
    while not es_habil(dia):
        dia += timedelta(days=1)
    return dia
