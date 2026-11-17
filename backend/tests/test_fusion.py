from __future__ import annotations

import random

import pytest

from tutela2.fusion import compactar, escalar, fusionar, hay_conflicto, resultado

BASE = ["a", "b", "c", "d"]


def _sin_conflicto(base, mio, nuevo):
    trozos = fusionar(base, mio, nuevo)
    assert not hay_conflicto(trozos)
    return resultado(trozos)


def test_sin_cambios():
    trozos = fusionar(BASE, BASE, BASE)
    assert trozos == [{"tipo": "ok", "origen": "igual", "parrafos": BASE}]
    assert resultado(trozos) == BASE


def test_base_vacia_sin_cambios():
    assert fusionar([], [], []) == []


def test_solo_mio():
    mio = ["a", "B", "c", "d"]
    trozos = fusionar(BASE, mio, BASE)
    assert [(t["tipo"], t["origen"], t["parrafos"]) for t in trozos] == [
        ("ok", "igual", ["a"]),
        ("ok", "mio", ["B"]),
        ("ok", "igual", ["c", "d"]),
    ]
    assert trozos[1]["base"] == ["b"]
    assert resultado(trozos) == mio


def test_solo_nuevo():
    nuevo = ["a", "b", "C", "d"]
    trozos = fusionar(BASE, BASE, nuevo)
    assert [t["origen"] for t in trozos] == ["igual", "nuevo", "igual"]
    assert resultado(trozos) == nuevo


def test_ambos_identicos():
    cambiado = ["a", "B", "c", "d"]
    trozos = fusionar(BASE, cambiado, cambiado)
    assert [t["origen"] for t in trozos] == ["igual", "ambos", "igual"]
    assert trozos[1]["base"] == ["b"] and trozos[1]["parrafos"] == ["B"]
    assert not hay_conflicto(trozos)
    assert resultado(trozos) == cambiado


def test_choque_en_el_mismo_parrafo():
    trozos = fusionar(BASE, ["a", "mio", "c", "d"], ["a", "nuevo", "c", "d"])
    assert hay_conflicto(trozos)
    conflicto = trozos[1]
    assert conflicto == {"tipo": "conflicto", "base": ["b"], "mio": ["mio"], "nuevo": ["nuevo"]}
    assert resultado(trozos, ["mio"]) == ["a", "mio", "c", "d"]
    assert resultado(trozos, ["nuevo"]) == ["a", "nuevo", "c", "d"]


def test_resultado_exige_elecciones_si_hay_conflicto():
    trozos = fusionar(BASE, ["a", "mio", "c", "d"], ["a", "nuevo", "c", "d"])
    with pytest.raises(ValueError):
        resultado(trozos)
    with pytest.raises(ValueError):
        resultado(trozos, [])
    with pytest.raises(ValueError):
        resultado(trozos, ["otro"])


def test_resultado_con_varios_conflictos_en_orden():
    base = ["a", "b", "c", "d", "e"]
    trozos = fusionar(base, ["a", "m1", "c", "m2", "e"], ["a", "n1", "c", "n2", "e"])
    assert [t["tipo"] for t in trozos] == ["ok", "conflicto", "ok", "conflicto", "ok"]
    assert resultado(trozos, ["mio", "nuevo"]) == ["a", "m1", "c", "n2", "e"]
    assert resultado(trozos, ["nuevo", "mio"]) == ["a", "n1", "c", "m2", "e"]


def test_inserciones_y_borrados_en_lugares_distintos():
    mio = ["a", "x", "b", "c", "d"]
    nuevo = ["a", "b", "d"]
    assert _sin_conflicto(BASE, mio, nuevo) == ["a", "x", "b", "d"]


def test_borrado_de_ambos_lados_del_mismo_parrafo():
    quitado = ["a", "c", "d"]
    trozos = fusionar(BASE, quitado, quitado)
    assert [t["origen"] for t in trozos] == ["igual", "ambos", "igual"]
    assert resultado(trozos) == quitado


def test_borrar_un_parrafo_que_el_otro_lado_edito_es_conflicto():
    trozos = fusionar(BASE, ["a", "c", "d"], ["a", "B", "c", "d"])
    assert hay_conflicto(trozos)
    assert resultado(trozos, ["mio"]) == ["a", "c", "d"]
    assert resultado(trozos, ["nuevo"]) == ["a", "B", "c", "d"]


def test_parrafos_adyacentes_se_fusionan_sin_choque():
    mio = ["a", "B", "c", "d"]
    nuevo = ["a", "b", "C", "d"]
    assert _sin_conflicto(BASE, mio, nuevo) == ["a", "B", "C", "d"]


def test_replace_de_igual_largo_se_parte_por_parrafo():
    assert _sin_conflicto(BASE, ["A", "B", "c", "d"], ["a", "b", "C", "D"]) == ["A", "B", "C", "D"]
    assert hay_conflicto(fusionar(BASE, ["a", "B", "c", "d"], ["a", "x", "y", "D"]))


def test_replace_de_distinto_largo_no_se_parte():
    trozos = fusionar(["a", "b", "c"], ["a", "x", "y", "z"], ["a", "b", "C"])
    assert hay_conflicto(trozos)
    assert resultado(trozos, ["mio"]) == ["a", "x", "y", "z"]
    assert resultado(trozos, ["nuevo"]) == ["a", "b", "C"]


def test_dos_inserciones_en_el_mismo_punto_chocan():
    trozos = fusionar(BASE, ["a", "x", "b", "c", "d"], ["a", "y", "b", "c", "d"])
    assert hay_conflicto(trozos)
    conflicto = next(t for t in trozos if t["tipo"] == "conflicto")
    assert conflicto["base"] == [] and conflicto["mio"] == ["x"] and conflicto["nuevo"] == ["y"]


def test_dos_inserciones_identicas_en_el_mismo_punto_no_chocan():
    trozos = fusionar(BASE, ["a", "x", "b", "c", "d"], ["a", "x", "b", "c", "d"])
    assert [t["origen"] for t in trozos] == ["igual", "ambos", "igual"]
    assert resultado(trozos) == ["a", "x", "b", "c", "d"]


def test_insercion_en_el_borde_de_un_rango_no_choca():
    assert _sin_conflicto(BASE, ["a", "x", "b", "c", "d"], ["a", "B", "c", "d"]) == ["a", "x", "B", "c", "d"]
    assert _sin_conflicto(BASE, ["a", "b", "x", "c", "d"], ["a", "B", "c", "d"]) == ["a", "B", "x", "c", "d"]
    assert _sin_conflicto(BASE, ["a", "B", "c", "d"], ["a", "x", "b", "c", "d"]) == ["a", "x", "B", "c", "d"]


def test_insercion_estrictamente_dentro_de_un_rango_choca():
    nuevo = ["a", "N", "d"]
    mio = ["a", "b", "x", "c", "d"]
    trozos = fusionar(BASE, mio, nuevo)
    assert hay_conflicto(trozos)
    assert resultado(trozos, ["mio"]) == mio
    assert resultado(trozos, ["nuevo"]) == nuevo


def test_insercion_al_final_y_al_principio():
    assert _sin_conflicto(BASE, ["x", *BASE], [*BASE, "y"]) == ["x", *BASE, "y"]


def test_racimo_transitivo():
    mio = ["A", "b", "C", "d"]
    nuevo = ["N", "d"]
    trozos = fusionar(BASE, mio, nuevo)
    assert [t["tipo"] for t in trozos] == ["conflicto", "ok"]
    conflicto = trozos[0]
    assert conflicto["base"] == ["a", "b", "c"]
    assert conflicto["mio"] == ["A", "b", "C"]
    assert conflicto["nuevo"] == ["N"]


def test_racimo_sin_solapar_los_extremos_no_se_une():
    trozos = fusionar(BASE, ["A", "b", "C", "d"], ["a", "N", "d"])
    assert [t["tipo"] for t in trozos] == ["ok", "conflicto", "ok"]
    assert trozos[1]["base"] == ["b", "c"] and trozos[1]["mio"] == ["b", "C"] and trozos[1]["nuevo"] == ["N"]


def test_cambio_nulo_no_cuenta_como_cambio():
    assert _sin_conflicto(["a", "b"], ["b", "a"], ["a", "b"]) == ["b", "a"]


def test_compactar_funde_oks_y_quita_origen_y_base():
    base = ["a", "b", "c", "d", "e"]
    trozos = fusionar(base, ["a", "B", "c", "d", "e"], ["a", "b", "c", "D", "e"])
    assert compactar(trozos) == [{"tipo": "ok", "parrafos": ["a", "B", "c", "D", "e"]}]


def test_compactar_deja_los_conflictos_con_mio_y_nuevo():
    base = ["a", "b", "c"]
    trozos = fusionar(base, ["a", "m", "c"], ["a", "n", "c"])
    assert compactar(trozos) == [
        {"tipo": "ok", "parrafos": ["a"]},
        {"tipo": "conflicto", "mio": ["m"], "nuevo": ["n"]},
        {"tipo": "ok", "parrafos": ["c"]},
    ]


def test_compactar_descarta_oks_vacios_y_resultado_sigue_igual():
    trozos = fusionar(BASE, ["a", "c", "d"], ["a", "c", "d"])
    compactos = compactar(trozos)
    assert all(t["parrafos"] for t in compactos)
    assert resultado(compactos) == ["a", "c", "d"]


def test_resultado_funciona_sobre_trozos_compactados():
    trozos = compactar(fusionar(BASE, ["a", "m", "c", "d"], ["a", "n", "c", "d"]))
    assert resultado(trozos, ["mio"]) == ["a", "m", "c", "d"]
    assert resultado(trozos, ["nuevo"]) == ["a", "n", "c", "d"]


def test_escalar_convierte_los_ok_mio_en_conflictos():
    base = ["a", "b", "c", "d"]
    trozos = fusionar(base, ["a", "B", "c", "d"], ["a", "b", "c", "D"])
    assert not hay_conflicto(trozos)
    escalados = escalar(trozos)
    assert hay_conflicto(escalados)
    assert compactar(escalados) == [
        {"tipo": "ok", "parrafos": ["a"]},
        {"tipo": "conflicto", "mio": ["B"], "nuevo": ["b"]},
        {"tipo": "ok", "parrafos": ["c", "D"]},
    ]
    assert resultado(escalados, ["nuevo"]) == ["a", "b", "c", "D"]
    assert resultado(escalados, ["mio"]) == ["a", "B", "c", "D"]


def test_escalar_no_toca_nuevo_ambos_ni_conflictos():
    trozos = fusionar(BASE, ["a", "B", "c", "d"], ["a", "B", "c", "D"])
    assert [t["origen"] for t in trozos] == ["igual", "ambos", "igual", "nuevo"]
    assert escalar(trozos) == trozos
    con_choque = fusionar(BASE, ["a", "m", "c", "d"], ["a", "n", "c", "d"])
    assert escalar(con_choque) == con_choque


def test_no_muta_las_entradas():
    base, mio, nuevo = list(BASE), ["a", "B", "c", "d"], ["a", "b", "C", "d"]
    trozos = fusionar(base, mio, nuevo)
    trozos[0]["parrafos"].append("zzz")
    compactar(trozos)[0]["parrafos"].append("yyy")
    assert (base, mio, nuevo) == (BASE, ["a", "B", "c", "d"], ["a", "b", "C", "d"])


@pytest.mark.parametrize("semilla", range(300))
def test_invariantes_con_listas_al_azar(semilla):
    azar = random.Random(semilla)

    def lista():
        return [azar.choice("abcdef") + str(azar.randrange(3)) for _ in range(azar.randrange(7))]

    base, mio, nuevo = lista(), lista(), lista()
    assert _sin_conflicto(base, mio, base) == mio
    assert _sin_conflicto(base, base, nuevo) == nuevo
    assert _sin_conflicto(base, mio, mio) == mio
    trozos = fusionar(base, mio, nuevo)
    espejo = fusionar(base, nuevo, mio)
    assert hay_conflicto(trozos) == hay_conflicto(espejo)
    if not hay_conflicto(trozos):
        assert resultado(trozos) == resultado(espejo)
    elecciones_mio = ["mio"] * sum(t["tipo"] == "conflicto" for t in trozos)
    elecciones_nuevo = ["nuevo"] * len(elecciones_mio)
    for elecciones in (elecciones_mio, elecciones_nuevo):
        assert resultado(compactar(trozos), elecciones) == resultado(trozos, elecciones)
    escalados = escalar(trozos)
    n = sum(t["tipo"] == "conflicto" for t in escalados)
    assert resultado(escalados, ["nuevo"] * n) == nuevo


def test_las_bases_de_los_trozos_recomponen_la_base():
    azar = random.Random(7)
    for _ in range(200):
        base = [azar.choice("abcde") for _ in range(azar.randrange(8))]
        mio = [azar.choice("abcde") for _ in range(azar.randrange(8))]
        nuevo = [azar.choice("abcde") for _ in range(azar.randrange(8))]
        recompuesta: list[str] = []
        for t in fusionar(base, mio, nuevo):
            recompuesta += t["parrafos"] if t.get("origen") == "igual" else t["base"]
        assert recompuesta == base
