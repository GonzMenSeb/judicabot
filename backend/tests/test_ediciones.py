from __future__ import annotations

import copy
import json
import logging
import os

import pytest

from tutela2 import ediciones, render
from tutela2.ediciones import ErrorEdicion
from tutela2.models import CitaVerificada, Ingesta

SENT1 = "T-200 de 2022"
SENT2 = "SU-082 de 1995"

HECHOS = (
    "La accionante presentó tutela por la demora en la cirugía que ordenó su médico.\n\n"
    "La entidad respondió que no existía autorización vigente."
)
CONT_UNO = "Entidad Uno sostuvo que el trámite estaba en curso y pidió negar el amparo."
CONT_DOS = "Entidad Dos guardó absoluto silencio frente a la acción."
SENTENCIA = "El juzgado negó el amparo porque no halló vulneración alguna."
IMPUGNACION = "La accionante reprocha que el juzgado ignoró la urgencia.\n\nPide revocar la decisión."
PROCEDIBILIDAD = "La tutela exige subsidiariedad e inmediatez.\n\nEl examen se hace caso por caso."
P0 = "Primer párrafo sobre la salud como derecho fundamental [[CITA:c1]]."
P1 = "Segundo párrafo con la imagen [[IMAGEN tabla de plazos]] incluida."
P2 = "Finalmente, el cierre del bloque."
BLOQUE0 = f"{P0}\n\n{P1}\n\n{P2}"
BLOQUE1 = "El principio de continuidad se apoya en [[CITA:c2]]."

TEXTO0 = "consideraciones.bloques.0.texto"
TITULO0 = "consideraciones.bloques.0.titulo"
TEXTO1 = "consideraciones.bloques.1.texto"
HECHOS_P = "apertura.antecedentes_hechos"
CONT0 = "apertura.contestaciones.0.texto"
CONT1 = "apertura.contestaciones.1.texto"
IMPUGNA = "apertura.impugnacion"


def _cita(id_: str, sentencia: str) -> dict:
    return CitaVerificada(id=id_, sentencia_original=sentencia, texto_citado="x").model_dump(mode="json")


def valores() -> dict:
    return {
        "apertura": {
            "metadatos": {},
            "cronologia": [],
            "antecedentes_hechos": HECHOS,
            "contestaciones": [
                {"entidad": "Entidad Uno", "silencio": False, "texto": CONT_UNO},
                {"entidad": "Entidad Dos", "silencio": True, "texto": CONT_DOS},
            ],
            "sentencia_impugnada": SENTENCIA,
            "impugnacion": IMPUGNACION,
            "reparos": [],
        },
        "consideraciones": {
            "procedibilidad": PROCEDIBILIDAD,
            "bloques": [
                {"titulo": "La salud como derecho", "reparo_ids": [], "texto": BLOQUE0},
                {"titulo": "Continuidad del servicio", "reparo_ids": [], "texto": BLOQUE1},
            ],
            "citas": [],
        },
        "citas": [_cita("c1", SENT1), _cita("c2", SENT2)],
        "ingesta": Ingesta(documentos=[]).model_dump(mode="json"),
    }


def vacia() -> dict:
    return {"version": 1, "piezas": {}, "conflictos": {}}


def con(vals: dict, pieza: str, texto: str) -> dict:
    return {**vals, pieza.split(".")[0]: ediciones.fijar(vals, pieza, texto)}


def con_citas(vals: dict, **citas: str) -> dict:
    return {**vals, "citas": [_cita(id_, s) for id_, s in citas.items()]}


def parrafos_de(vals: dict, capa: dict, pieza: str) -> list[str]:
    return ediciones.respuesta(vals, capa)["piezas"][pieza]["parrafos"]


def editar(vals: dict, capa: dict, pieza: str, k: int, texto: str) -> dict:
    return ediciones.editar(vals, capa, pieza, k, parrafos_de(vals, capa, pieza)[k], texto)


def aplicado(vals: dict, capa: dict, pieza: str) -> str:
    return ediciones.obtener(ediciones.aplicar(vals, capa), pieza)


def consolidado(vals: dict, capa: dict) -> dict:
    return {**vals, **ediciones.consolidar(vals, capa)}


P1_HUMANO = "Segundo párrafo con la imagen ⟦imagen · tabla de plazos⟧ revisada por el despacho."
P1_IA = "Segundo párrafo reescrito por la IA con [[IMAGEN tabla de plazos]] al lado."
P0_IA = "Primer párrafo corregido por la IA sobre la salud [[CITA:c1]]."


def con_conflicto() -> tuple[dict, dict, dict]:
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = con(v1, TEXTO0, f"{P0}\n\n{P1_IA}\n\n{P2}")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    return v2, capa2, capa


def sin_mutar(funcion, vals: dict, capa: dict, *args):
    antes_v, antes_c = copy.deepcopy(vals), copy.deepcopy(capa)
    try:
        resultado = funcion(vals, capa, *args)
    finally:
        assert vals == antes_v
        assert capa == antes_c
    return resultado


# ---------------------------------------------------------------- parrafos y fichas


def test_parrafos_y_normalizar():
    assert ediciones.parrafos(None) == []
    assert ediciones.parrafos("  \n ") == []
    assert ediciones.parrafos("a  b\nc\n\n\n  d \n \ne") == ["a b c", "d", "e"]
    assert ediciones.normalizar("a  b\nc\n\n\n  d") == "a b c\n\nd"
    assert ediciones.normalizar(None) == ""


def test_los_patrones_de_marca_son_los_de_render():
    assert ediciones._CITA.pattern == render._CITA.pattern
    assert ediciones._CITA.flags == render._CITA.flags
    assert ediciones._IMAGEN.pattern == render._IMAGEN.pattern
    assert ediciones._IMAGEN.flags == render._IMAGEN.flags


def test_a_editable_muestra_las_marcas_como_fichas():
    mapa = ediciones.mapa_citas(valores())
    assert mapa == {"c1": SENT1, "c2": SENT2}
    texto = "Ver [[CITA:c1]], [[CITA: c9 ]], [[IMAGEN  una   tabla ]] y [[IMAGEN]]."
    assert ediciones.a_editable(texto, mapa) == (
        f"Ver ⟦cita c1 · {SENT1}⟧, ⟦cita c9⟧, ⟦imagen · una tabla⟧ y ⟦imagen⟧."
    )


def test_a_editable_no_deja_que_una_sentencia_rompa_la_ficha():
    editable = ediciones.a_editable("x [[CITA:c1]] y", {"c1": "T-1 ⟦de\n1999⟧  final"})
    assert editable == "x ⟦cita c1 · T-1 de 1999 final⟧ y"
    assert ediciones.fichas(editable) == {("cita", "c1", "T-1 de 1999 final"): 1}


def test_a_canonico_deshace_las_fichas():
    assert ediciones.a_canonico(f"a ⟦cita c1 · {SENT1}⟧ b") == "a [[CITA:c1]] b"
    assert ediciones.a_canonico("a ⟦cita c9⟧ b") == "a [[CITA:c9]] b"
    assert ediciones.a_canonico("⟦imagen · x y⟧ ⟦imagen⟧ ⟦imagen · ⟧") == "[[IMAGEN x y]] [[IMAGEN]] [[IMAGEN]]"


@pytest.mark.parametrize(
    "texto",
    [BLOQUE0, BLOQUE1, "Sin marcas.", "[[CITA:c1]][[CITA:c2]] pegadas [[IMAGEN a b]]\n\n[[IMAGEN]]"],
)
def test_ida_y_vuelta_de_fichas_conserva_las_marcas(texto):
    mapa = ediciones.mapa_citas(valores())
    ida_y_vuelta = ediciones.a_canonico(ediciones.a_editable(texto, mapa))
    assert ida_y_vuelta == texto
    assert ediciones._CITA.findall(ida_y_vuelta) == render._CITA.findall(texto)
    assert ediciones._IMAGEN.findall(ida_y_vuelta) == render._IMAGEN.findall(texto)


def test_ida_y_vuelta_normaliza_las_marcas_con_espacios():
    mapa = ediciones.mapa_citas(valores())
    assert ediciones.a_canonico(ediciones.a_editable("x [[CITA: c1 ]] [[IMAGEN  a  ]]", mapa)) == "x [[CITA:c1]] [[IMAGEN a]]"


def test_fichas_cuentan_id_y_sentencia():
    texto = f"⟦cita c1 · {SENT1}⟧ ⟦cita c1 · {SENT1}⟧ ⟦cita c1 · {SENT2}⟧ ⟦imagen · a⟧ ⟦imagen⟧ ⟦cita c3⟧"
    assert ediciones.fichas(texto) == {
        ("cita", "c1", SENT1): 2,
        ("cita", "c1", SENT2): 1,
        ("imagen", "a"): 1,
        ("imagen", ""): 1,
        ("cita", "c3", ""): 1,
    }


def test_una_sentencia_con_espacios_raros_no_bloquea_la_edicion():
    v = {**valores(), "citas": [_cita("c1", "T-200  de\n2022 ⟦x⟧"), _cita("c2", SENT2)]}
    capa = editar(v, vacia(), TEXTO0, 0, "Primer párrafo nuevo ⟦cita c1 · T-200 de 2022 x⟧.")
    assert "[[CITA:c1]]" in aplicado(v, capa, TEXTO0)
    assert editar(v, capa, TEXTO0, 0, "Otra vez ⟦cita c1 · T-200 de 2022 x⟧.")


# ---------------------------------------------------------------- piezas


def test_catalogo_sigue_el_orden_del_documento():
    assert ediciones.catalogo(valores()) == [
        HECHOS_P,
        CONT0,
        CONT1,
        "apertura.sentencia_impugnada",
        IMPUGNA,
        "consideraciones.procedibilidad",
        TITULO0,
        TEXTO0,
        "consideraciones.bloques.1.titulo",
        TEXTO1,
    ]


def test_catalogo_solo_incluye_lo_que_existe():
    assert ediciones.catalogo({}) == []
    v = valores()
    del v["apertura"]["impugnacion"]
    v["consideraciones"]["bloques"][1]["titulo"] = None
    piezas = ediciones.catalogo(v)
    assert IMPUGNA not in piezas
    assert "consideraciones.bloques.1.titulo" not in piezas
    assert TEXTO1 in piezas
    assert ediciones.catalogo({"apertura": None, "consideraciones": "x"}) == []


def test_es_pieza_acepta_solo_ids_canonicos():
    for pieza in ediciones.catalogo(valores()) + ["apertura.contestaciones.12.texto", "consideraciones.bloques.0.titulo"]:
        assert ediciones.es_pieza(pieza)
    for pieza in [
        "",
        "apertura",
        "apertura.reparos",
        "apertura.contestaciones.01.texto",
        "apertura.contestaciones.-1.texto",
        "apertura.contestaciones.١.texto",
        "apertura.contestaciones.0.entidad",
        "consideraciones.bloques.0",
        "consideraciones.bloques.00.texto",
        "consideraciones.citas",
        "consideraciones.procedibilidad.x",
        "caso_concreto.conclusion",
    ]:
        assert not ediciones.es_pieza(pieza)


def test_seccion_titulo_y_etiqueta():
    v = valores()
    assert ediciones.seccion_de(HECHOS_P) == "antecedentes"
    assert ediciones.seccion_de(CONT1) == "antecedentes"
    assert ediciones.seccion_de("apertura.sentencia_impugnada") == "sentencia_impugnada"
    assert ediciones.seccion_de(IMPUGNA) == "impugnacion"
    assert ediciones.seccion_de("consideraciones.procedibilidad") == "consideraciones"
    assert ediciones.seccion_de(TITULO0) == "consideraciones"
    assert ediciones.seccion_de(TEXTO1) == "consideraciones"
    assert ediciones.es_titulo(TITULO0) and not ediciones.es_titulo(TEXTO0) and not ediciones.es_titulo(HECHOS_P)
    assert ediciones.etiqueta(HECHOS_P, v) == "Antecedentes: hechos"
    assert ediciones.etiqueta(CONT1, v) == "Antecedentes: contestación de Entidad Dos"
    assert ediciones.etiqueta("apertura.sentencia_impugnada", v) == "La sentencia impugnada"
    assert ediciones.etiqueta(IMPUGNA, v) == "La impugnación"
    assert ediciones.etiqueta("consideraciones.procedibilidad", v) == "Consideraciones: procedibilidad"
    assert ediciones.etiqueta("consideraciones.bloques.1.titulo", v) == "Consideraciones: título del bloque 2"
    assert ediciones.etiqueta(TEXTO1, v) == "Consideraciones: bloque 2 (Continuidad del servicio)"


def test_etiqueta_no_falla_con_piezas_que_ya_no_existen():
    assert ediciones.etiqueta("consideraciones.bloques.5.texto", {}) == "Consideraciones: bloque 6"
    assert ediciones.etiqueta("apertura.contestaciones.3.texto", {}) == "Antecedentes: contestación 4"
    assert ediciones.etiqueta("apertura.contestaciones.3.texto", {}, "Entidad X") == "Antecedentes: contestación de Entidad X"


def test_obtener_y_fijar():
    v = valores()
    antes = copy.deepcopy(v)
    assert ediciones.obtener(v, CONT1) == CONT_DOS
    assert ediciones.obtener(v, TITULO0) == "La salud como derecho"
    assert ediciones.obtener(v, "consideraciones.bloques.9.texto") is None
    assert ediciones.obtener(v, "apertura.reparos") is None
    assert ediciones.obtener({}, HECHOS_P) is None
    nuevo = ediciones.fijar(v, CONT1, "Nuevo texto")
    assert nuevo["contestaciones"][1]["texto"] == "Nuevo texto"
    assert nuevo["contestaciones"][0] == v["apertura"]["contestaciones"][0]
    assert set(nuevo) == set(v["apertura"])
    assert v == antes
    assert nuevo["contestaciones"] is not v["apertura"]["contestaciones"]
    assert ediciones.fijar(v, TITULO0, "T")["bloques"][0]["titulo"] == "T"
    with pytest.raises(ErrorEdicion) as e:
        ediciones.fijar(v, "consideraciones.bloques.9.texto", "x")
    assert e.value.estado == 404


# ---------------------------------------------------------------- validar


def _validar(pieza: str, nuevo: str, referencia: str, crudo: str | None = None) -> list[str]:
    return ediciones.validar(pieza, nuevo, referencia, nuevo if crudo is None else crudo)


REF_FICHAS = f"Texto con ⟦cita c1 · {SENT1}⟧ y ⟦imagen · tabla⟧ al final."


def test_validar_acepta_un_cambio_de_prosa():
    assert _validar(TEXTO0, REF_FICHAS.replace("Texto", "Otro texto"), REF_FICHAS) == []
    assert _validar(TEXTO0, REF_FICHAS, REF_FICHAS) == []


def test_validar_rechaza_pieza_vacia():
    errores = _validar(HECHOS_P, "", "algo", "  \n ")
    assert len(errores) == 1 and "vacía" in errores[0]


def test_validar_rechaza_saltos_de_linea_en_un_titulo():
    errores = _validar(TITULO0, "Una línea", "Una línea", "Una\nlínea")
    assert any("sola línea" in e for e in errores)
    assert _validar(TITULO0, "Una línea", "Otra", "Una línea") == []
    assert any("sola línea" in e for e in _validar(TITULO0, "Una\n\nlínea", "Otra", "Una línea"))
    assert not any("sola línea" in e for e in _validar(TEXTO0, "Una\n\nlínea", "Otra", "Una\nlínea"))


@pytest.mark.parametrize("caracter", ["\x00", "\x07", "\x08", "\x0e", "\x1b", "\ufffe", "\uffff", "\ud800"])
def test_validar_rechaza_caracteres_de_control_que_romperian_el_word(caracter):
    errores = _validar(HECHOS_P, f"Ver aquí{caracter} fin.", "Ver aquí.")
    assert len(errores) == 1 and "control" in errores[0]
    assert any("control" in e for e in _validar(TITULO0, f"Título{caracter}", "Título"))


@pytest.mark.parametrize("espacio", ["\x0b", "\x0c", "\x1c", "\x1f", "\x85", "\u2028", "\t"])
def test_validar_no_rechaza_los_espacios_raros_que_parrafos_ya_colapsa(espacio):
    assert ediciones.parrafos(f"Ver{espacio}aquí.") == ["Ver aquí."]
    assert _validar(HECHOS_P, ediciones.normalizar(f"Ver{espacio}aquí."), "Ver aquí.", f"Ver{espacio}aquí.") == []


@pytest.mark.parametrize("tecleado", ["Ver [[CITA:c1]] aquí.", "Ver [[IMAGEN x]] aquí.", "Ver [[ aquí.", "Ver ]] aquí."])
def test_validar_rechaza_marcas_tecleadas(tecleado):
    errores = _validar(HECHOS_P, tecleado, "Ver aquí.")
    assert any("[[" in e and "]]" in e for e in errores)


@pytest.mark.parametrize("suelto", ["Ver ⟦ aquí.", "Ver ⟧ aquí.", "Ver ⟦cita c1 sin punto⟧ aquí.", "Ver ⟦otra cosa⟧ aquí."])
def test_validar_rechaza_fichas_sueltas_o_ilegibles(suelto):
    errores = _validar(HECHOS_P, suelto, "Ver aquí.")
    assert any("suelto" in e for e in errores)


def test_validar_rechaza_fichas_que_faltan_sobran_o_cambian():
    faltan = _validar(TEXTO0, "Texto sin nada.", REF_FICHAS)
    assert len(faltan) == 1 and "faltan" in faltan[0] and f"⟦cita c1 · {SENT1}⟧" in faltan[0] and "⟦imagen · tabla⟧" in faltan[0]
    assert "sobran" not in faltan[0]

    sobran = _validar(TEXTO0, REF_FICHAS + " ⟦cita c2 · SU-082 de 1995⟧", REF_FICHAS)
    assert len(sobran) == 1 and "sobran" in sobran[0] and "SU-082 de 1995" in sobran[0] and "faltan" not in sobran[0]

    duplicada = _validar(TEXTO0, REF_FICHAS + " ⟦imagen · tabla⟧", REF_FICHAS)
    assert len(duplicada) == 1 and "sobran" in duplicada[0]

    alterada = _validar(TEXTO0, REF_FICHAS.replace(SENT1, "T-999 de 2023"), REF_FICHAS)
    assert len(alterada) == 1 and "faltan" in alterada[0] and "sobran" in alterada[0] and "T-999 de 2023" in alterada[0]

    renombrada = _validar(TEXTO0, REF_FICHAS.replace("c1", "c2"), REF_FICHAS)
    assert len(renombrada) == 1 and "faltan" in renombrada[0] and "sobran" in renombrada[0]


def test_validar_permite_mover_una_ficha():
    movida = f"⟦imagen · tabla⟧ Texto con ⟦cita c1 · {SENT1}⟧ aquí."
    assert _validar(TEXTO0, movida, REF_FICHAS) == []


def test_validar_rechaza_una_sentencia_nueva_en_consideraciones_y_la_permite_en_apertura():
    nuevo = "Texto base, como dijo la T-300 de 2020."
    errores = _validar(TEXTO0, nuevo, "Texto base.")
    assert len(errores) == 1 and "T-300" in errores[0]
    assert _validar(IMPUGNA, nuevo, "Texto base.") == []
    assert _validar("consideraciones.procedibilidad", nuevo, "Texto base.") != []
    assert _validar(TITULO0, "Según la T-300 de 2020", "Título") != []


def test_validar_rechaza_una_sentencia_sin_anio_nueva_en_consideraciones():
    errores = _validar(TEXTO0, "Texto base, según la sentencia T-300.", "Texto base.")
    assert len(errores) == 1 and "T-300" in errores[0]
    assert _validar(HECHOS_P, "Texto base, según la sentencia T-300.", "Texto base.") == []


def test_validar_no_cuenta_como_nueva_una_sentencia_que_ya_estaba():
    referencia = "Texto base, como dijo la T-300 de 2020."
    assert _validar(TEXTO0, referencia.replace("Texto base", "Texto editado"), referencia) == []
    assert _validar(TEXTO0, "Hoy: " + referencia, referencia) == []
    assert _validar(TEXTO0, "Ahora la T-301 de 2020.", referencia) != []


def test_validar_rechaza_oraciones_nuevas_de_la_jurisprudencia_ha_en_consideraciones():
    nuevo = "Texto base. La jurisprudencia ha señalado que la tutela procede siempre."
    errores = _validar(TEXTO0, nuevo, "Texto base.")
    assert len(errores) == 1 and "jurisprudencia" in errores[0]
    assert _validar(IMPUGNA, nuevo, "Texto base.") == []
    con_ficha = f"Texto base. La jurisprudencia ha señalado que procede ⟦cita c1 · {SENT1}⟧."
    assert _validar(TEXTO0, con_ficha, f"Texto base ⟦cita c1 · {SENT1}⟧.") == []


def test_validar_cuenta_las_oraciones_de_la_jurisprudencia_ha_parrafo_por_parrafo():
    frase = "La jurisprudencia ha dicho algo número {}."
    referencia = "\n\n".join(frase.format(i) for i in range(6))
    assert _validar(TEXTO0, referencia, referencia) == []
    errores = _validar(TEXTO0, referencia + "\n\n" + frase.format(7), referencia)
    assert len(errores) == 1 and "jurisprudencia" in errores[0]
    assert _validar(TEXTO0, referencia.replace("algo", "otra cosa"), referencia) == []


# ---------------------------------------------------------------- avisos


def test_avisos_devuelve_solo_los_mensajes_nuevos():
    ia = "Texto con **negrita** previa.\n\nOtro párrafo."
    nuevo = ia + "\n\nTODO: revisar este punto."
    avisos = ediciones.avisos(HECHOS_P, nuevo, ia, None)
    assert avisos and all("negrita" not in a for a in avisos)
    assert any("residuo" in a for a in avisos)
    assert ediciones.avisos(HECHOS_P, ia, ia, None) == []
    assert ediciones.avisos(HECHOS_P, ia, nuevo, None) == []


def test_avisos_lint_prosa_marca_lo_que_el_humano_agrega():
    avisos = ediciones.avisos(TEXTO0, "Una línea.\n\n# Encabezado markdown", "Una línea.", None)
    assert any("encabezados" in a for a in avisos)


def test_avisos_datos_ajenos_solo_en_piezas_de_apertura():
    ing = Ingesta(documentos=[])
    nuevo = "Hechos del caso. La cédula 1234567890 fue presentada."
    assert any("1234567890" in a for a in ediciones.avisos(HECHOS_P, nuevo, "Hechos del caso.", ing))
    assert not any("1234567890" in a for a in ediciones.avisos(TEXTO0, nuevo, "Hechos del caso.", ing))
    assert not any("1234567890" in a for a in ediciones.avisos(HECHOS_P, nuevo, "Hechos del caso.", None))


def test_los_titulos_no_tienen_avisos():
    assert ediciones.avisos(TITULO0, "# TODO **x**", "Título", Ingesta(documentos=[])) == []


# ---------------------------------------------------------------- editar


def test_editar_crea_la_entrada_con_ia_y_consolidado_en_u():
    v = valores()
    capa = sin_mutar(editar, v, vacia(), TEXTO0, 1, P1_HUMANO)
    e = capa["piezas"][TEXTO0]
    u = ediciones.normalizar(ediciones.a_editable(BLOQUE0, ediciones.mapa_citas(v)))
    assert e["ia"] == e["consolidado"] == u
    assert e["ancla"] == "La salud como derecho"
    assert e["texto"] == u.replace(ediciones.parrafos(u)[1], P1_HUMANO)
    assert e["avisos"] == []
    assert capa["conflictos"] == {}
    assert aplicado(v, capa, TEXTO0) == (
        f"{P0}\n\nSegundo párrafo con la imagen [[IMAGEN tabla de plazos]] revisada por el despacho.\n\n{P2}"
    )


def test_editar_una_contestacion_guarda_el_ancla():
    capa = editar(valores(), vacia(), CONT1, 0, "Entidad Dos respondió a último momento.")
    assert capa["piezas"][CONT1]["ancla"] == "Entidad Dos"


def test_editar_reemplaza_un_parrafo_por_cero_uno_o_varios():
    v = valores()
    base = parrafos_de(v, vacia(), TEXTO0)
    uno = editar(v, vacia(), TEXTO0, 2, "Un solo párrafo nuevo.")
    assert parrafos_de(v, uno, TEXTO0) == [*base[:2], "Un solo párrafo nuevo."]

    varios = editar(v, vacia(), TEXTO0, 2, "Nuevo uno.\n\n  \nNuevo dos\ncontinúa.")
    assert parrafos_de(v, varios, TEXTO0) == [*base[:2], "Nuevo uno.", "Nuevo dos continúa."]
    assert ediciones.respuesta(v, varios)["piezas"][TEXTO0]["editados"] == [2, 3]

    ninguno = editar(v, vacia(), TEXTO0, 2, "  \n ")
    assert parrafos_de(v, ninguno, TEXTO0) == base[:2]
    assert ediciones.respuesta(v, ninguno)["piezas"][TEXTO0]["editados"] == []
    assert ninguno["piezas"][TEXTO0]["texto"] == "\n\n".join(base[:2])
    assert aplicado(v, ninguno, TEXTO0) == f"{P0}\n\n{P1}"


def test_editar_sucesivo_usa_el_texto_ya_editado():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "Dos finales.\n\nDos finales bis.")
    capa = editar(v, capa, TEXTO0, 3, "Cuarto cambiado.")
    assert parrafos_de(v, capa, TEXTO0)[2:] == ["Dos finales.", "Cuarto cambiado."]
    assert ediciones.respuesta(v, capa)["piezas"][TEXTO0]["editados"] == [2, 3]


def test_editar_no_puede_dejar_la_pieza_vacia():
    v = valores()
    with pytest.raises(ErrorEdicion) as e:
        editar(v, vacia(), TEXTO1, 0, "")
    assert e.value.estado == 422 and "vacía" in e.value.mensaje


def test_editar_responde_409_si_el_original_esta_desfasado():
    v = valores()
    with pytest.raises(ErrorEdicion) as e:
        ediciones.editar(v, vacia(), TEXTO0, 1, "Otro texto que ya no es el del borrador", "x")
    assert e.value.estado == 409 and "recargue el borrador" in e.value.mensaje

    capa = editar(v, vacia(), TEXTO0, 2, "Cambiado una vez.")
    with pytest.raises(ErrorEdicion) as e:
        ediciones.editar(v, capa, TEXTO0, 2, parrafos_de(v, vacia(), TEXTO0)[2], "x")
    assert e.value.estado == 409


def test_editar_acepta_el_original_con_otros_espacios():
    v = valores()
    original = parrafos_de(v, vacia(), TEXTO0)[2]
    assert ediciones.editar(v, vacia(), TEXTO0, 2, f"  {original.replace(' ', '   ')}\n", "Nuevo.")


@pytest.mark.parametrize("k", [-1, 3, 99])
def test_editar_responde_409_si_el_parrafo_esta_fuera_de_rango(k):
    with pytest.raises(ErrorEdicion) as e:
        ediciones.editar(valores(), vacia(), TEXTO0, k, P2, "x")
    assert e.value.estado == 409 and "recargue el borrador" in e.value.mensaje


def test_editar_responde_404_si_la_pieza_no_existe():
    for pieza in ["apertura.nada", "consideraciones.bloques.7.texto", "apertura.contestaciones.2.texto", ""]:
        with pytest.raises(ErrorEdicion) as e:
            ediciones.editar(valores(), vacia(), pieza, 0, "x", "y")
        assert e.value.estado == 404


def test_editar_responde_409_si_la_pieza_esta_en_conflicto():
    v2, capa, _ = con_conflicto()
    with pytest.raises(ErrorEdicion) as e:
        ediciones.editar(v2, capa, TEXTO0, 0, parrafos_de(v2, capa, TEXTO0)[0], "x")
    assert e.value.estado == 409 and "conflicto" in e.value.mensaje


def test_editar_responde_409_en_un_conflicto_huerfano():
    v = valores()
    capa = editar(v, vacia(), TEXTO1, 0, f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v)
    del v2["consideraciones"]["bloques"][1]
    capa, _ = ediciones.sincronizar(v2, capa)
    assert capa["conflictos"][TEXTO1]["huerfana"]
    with pytest.raises(ErrorEdicion) as e:
        ediciones.editar(v2, capa, TEXTO1, 0, "x", "y")
    assert e.value.estado == 409


@pytest.mark.parametrize(
    "texto, fragmento",
    [
        ("Con [[CITA:c1]] tecleada.", "[["),
        ("Sin la ficha de la cita.", "faltan"),
        (P0.replace("[[CITA:c1]]", "⟦cita c1 · T-1 de 2000⟧"), "sobran"),
        ("Con ⟦ suelto.", "suelto"),
        ("Cita nueva: la T-300 de 2020.", "T-300"),
        ("La jurisprudencia ha dicho cualquier cosa.", "jurisprudencia"),
    ],
)
def test_editar_responde_422_si_la_validacion_falla(texto, fragmento):
    v = valores()
    p0 = parrafos_de(v, vacia(), TEXTO0)[0]
    with pytest.raises(ErrorEdicion) as e:
        sin_mutar(lambda vals, capa: ediciones.editar(vals, capa, TEXTO0, 0, p0, texto), v, vacia())
    assert e.value.estado == 422 and fragmento in e.value.mensaje


def test_editar_un_titulo():
    v = valores()
    capa = editar(v, vacia(), TITULO0, 0, "Un título corregido")
    assert aplicado(v, capa, TITULO0) == "Un título corregido"
    with pytest.raises(ErrorEdicion) as e:
        editar(v, vacia(), TITULO0, 0, "Dos\nlíneas")
    assert e.value.estado == 422 and "sola línea" in e.value.mensaje
    with pytest.raises(ErrorEdicion) as e:
        editar(v, vacia(), TITULO0, 0, "Dos\n\nlíneas")
    assert e.value.estado == 422
    with pytest.raises(ErrorEdicion) as e:
        editar(v, vacia(), TITULO0, 0, " ")
    assert e.value.estado == 422 and "vacía" in e.value.mensaje


def test_editar_guarda_los_avisos_nuevos():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "TODO: terminar de redactar el cierre.")
    assert any("residuo" in a for a in capa["piezas"][TEXTO0]["avisos"])
    assert ediciones.respuesta(v, capa)["piezas"][TEXTO0]["avisos"] == capa["piezas"][TEXTO0]["avisos"]
    capa = editar(v, capa, TEXTO0, 2, "Un cierre normal del bloque.")
    assert capa["piezas"][TEXTO0]["avisos"] == []


def test_editar_borra_la_entrada_cuando_el_texto_vuelve_al_de_la_ia():
    v = valores()
    original = parrafos_de(v, vacia(), TEXTO0)[2]
    capa = editar(v, vacia(), TEXTO0, 2, "Otro texto.")
    assert TEXTO0 in capa["piezas"]
    capa = editar(v, capa, TEXTO0, 2, original)
    assert capa["piezas"] == {}


def test_editar_sin_cambios_no_crea_entrada():
    v = valores()
    assert editar(v, vacia(), TEXTO0, 1, parrafos_de(v, vacia(), TEXTO0)[1])["piezas"] == {}


def test_editar_tolera_una_apertura_sin_ingesta():
    v = valores()
    del v["ingesta"]
    capa = editar(v, vacia(), HECHOS_P, 0, "Hechos nuevos con la cédula 1234567890.")
    assert capa["piezas"][HECHOS_P]["avisos"] == []
    assert ediciones.respuesta(v, capa)["piezas"][HECHOS_P]["parrafos"][0].startswith("Hechos nuevos")
    v["ingesta"] = {"basura": True}
    assert editar(v, vacia(), HECHOS_P, 0, "Otros hechos.")


# ---------------------------------------------------------------- sincronizar


def test_sincronizar_sin_cambios_es_un_no_op():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 1, P1_HUMANO)
    capa2, eventos = sin_mutar(ediciones.sincronizar, v, capa)
    assert capa2 == capa and eventos == []


def test_sincronizar_no_hace_nada_si_u_es_el_texto_humano():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "Texto humano.")
    u_humano = ediciones.a_canonico(capa["piezas"][TEXTO0]["texto"])
    v2 = con(v, TEXTO0, u_humano)
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert eventos == []
    assert capa2["piezas"][TEXTO0]["consolidado"] == capa["piezas"][TEXTO0]["texto"]
    assert {k: x for k, x in capa2["piezas"][TEXTO0].items() if k != "consolidado"} == {
        k: x for k, x in capa["piezas"][TEXTO0].items() if k != "consolidado"
    }
    assert capa2["conflictos"] == {}


def test_sincronizar_borra_la_entrada_si_todo_coincide_con_u():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "Texto humano.")
    capa["piezas"][TEXTO0].update(texto=capa["piezas"][TEXTO0]["ia"], consolidado="otro")
    capa2, _ = ediciones.sincronizar(v, capa)
    assert capa2["piezas"] == {}


def test_los_saltos_de_linea_simples_no_disparan_un_rebase():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 1, P1_HUMANO)
    con_saltos = BLOQUE0.replace("sobre la salud como", "sobre la salud\ncomo").replace("Finalmente, el", "Finalmente,\nel")
    assert con_saltos != BLOQUE0
    capa2, eventos = ediciones.sincronizar(con(v, TEXTO0, con_saltos), capa)
    assert capa2 == capa and eventos == []


def test_rebase_limpio_cuando_la_ia_y_el_humano_tocan_parrafos_distintos():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = con(v1, TEXTO0, f"{P0_IA}\n\n{P1}\n\n{P2}")
    capa2, eventos = sin_mutar(ediciones.sincronizar, v2, capa)
    e = capa2["piezas"][TEXTO0]
    u = ediciones.normalizar(ediciones.a_editable(ediciones.obtener(v2, TEXTO0), ediciones.mapa_citas(v2)))
    assert e["ia"] == e["consolidado"] == u
    assert ediciones.parrafos(e["texto"]) == [ediciones.parrafos(u)[0], P1_HUMANO, P2]
    assert capa2["conflictos"] == {}
    assert [(ev["accion"], ev["pieza"], ev["ia"], ev["texto"]) for ev in eventos] == [("rebase", TEXTO0, u, e["texto"])]
    assert set(eventos[0]) == {"accion", "pieza", "ia", "texto"}
    assert ediciones.respuesta(v2, capa2)["piezas"][TEXTO0]["editados"] == [1]
    capa3, eventos3 = ediciones.sincronizar(v2, capa2)
    assert capa3 == capa2 and eventos3 == []


def test_rebase_limpio_borra_la_entrada_si_la_fusion_es_igual_a_u():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Cierre corregido.")
    v2 = con(v1, TEXTO0, f"{P0_IA}\n\n{P1}\n\nCierre corregido.")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["piezas"] == {} and capa2["conflictos"] == {}
    assert [e["accion"] for e in eventos] == ["rebase"]


def test_si_la_ia_adopta_justo_el_texto_humano_la_entrada_se_queda_hasta_que_ia_y_texto_coincidan():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Cierre corregido.")
    v2 = con(v1, TEXTO0, f"{P0}\n\n{P1}\n\nCierre corregido.")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert eventos == [] and capa2["conflictos"] == {}
    e = capa2["piezas"][TEXTO0]
    assert e["texto"] == e["consolidado"] != e["ia"]
    assert ediciones.respuesta(v2, capa2)["piezas"][TEXTO0]["editados"] == [2]


def test_rebase_cuando_el_humano_ya_no_difiere_de_la_ia_no_genera_evento():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    capa["piezas"][TEXTO0].update(texto=capa["piezas"][TEXTO0]["ia"], consolidado="otro")
    v2 = con(v1, TEXTO0, f"{P0_IA}\n\n{P1}\n\n{P2}")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["piezas"] == {} and eventos == []


def test_conflicto_guardado_cuando_ambos_tocan_el_mismo_parrafo():
    v2, capa2, capa = con_conflicto()
    u = ediciones.normalizar(ediciones.a_editable(ediciones.obtener(v2, TEXTO0), ediciones.mapa_citas(v2)))
    assert capa2["conflictos"][TEXTO0] == {
        "ia": u,
        "huerfana": False,
        "trozos": [
            {"tipo": "ok", "parrafos": [ediciones.parrafos(u)[0]]},
            {"tipo": "conflicto", "mio": [P1_HUMANO], "nuevo": [ediciones.parrafos(u)[1]]},
            {"tipo": "ok", "parrafos": [P2]},
        ],
    }
    assert capa2["piezas"] == capa["piezas"]


def test_sincronizar_es_idempotente_con_un_conflicto_pendiente():
    v2, capa2, _ = con_conflicto()
    capa3, eventos = sin_mutar(ediciones.sincronizar, v2, capa2)
    assert capa3 == capa2 and eventos == []


def test_un_conflicto_se_reemplaza_si_la_ia_vuelve_a_cambiar():
    v2, capa2, _ = con_conflicto()
    v3 = con(v2, TEXTO0, f"{P0}\n\nTercera versión de la IA con [[IMAGEN tabla de plazos]].\n\n{P2}")
    capa3, eventos = ediciones.sincronizar(v3, capa2)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    assert capa3["conflictos"][TEXTO0]["trozos"][1]["nuevo"] == ["Tercera versión de la IA con ⟦imagen · tabla de plazos⟧."]


def test_un_conflicto_desaparece_si_la_ia_vuelve_al_texto_de_base():
    v2, capa2, capa = con_conflicto()
    capa3, eventos = ediciones.sincronizar(valores(), capa2)
    assert capa3["conflictos"] == {} and eventos == []
    assert capa3["piezas"][TEXTO0]["texto"] == capa["piezas"][TEXTO0]["texto"]


def test_ids_de_cita_reasignados_no_cambian_la_sentencia_en_silencio():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 0, f"Primer párrafo editado por el despacho ⟦cita c1 · {SENT1}⟧.")
    v2 = con_citas(v1, c1="T-999 de 2023", c2=SENT1)
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    assert TEXTO0 in capa2["conflictos"]
    trozo = ediciones.respuesta(v2, capa2)["conflictos"][0]["trozos"][0]
    assert trozo["tipo"] == "conflicto" and trozo["mio_permitido"] is False
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(v2, capa2, TEXTO0, ["mio"])
    assert e.value.estado == 422
    assert aplicado(v2, capa2, TEXTO0) == BLOQUE0
    capa3 = ediciones.resolver(v2, capa2, TEXTO0, ["nuevo"])
    assert capa3["piezas"] == {} and capa3["conflictos"] == {}
    assert parrafos_de(v2, capa3, TEXTO0)[0] == "Primer párrafo sobre la salud como derecho fundamental ⟦cita c1 · T-999 de 2023⟧."
    assert aplicado(v2, capa3, TEXTO0) == BLOQUE0


def test_ids_de_cita_reasignados_sin_tocar_el_parrafo_de_la_cita_se_toman_de_la_ia():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Cierre corregido por el despacho.")
    v2 = con_citas(v1, c1="T-999 de 2023", c2=SENT1)
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"] == {}
    editable = ediciones.obtener(ediciones.aplicar(v2, capa2), TEXTO0)
    assert "[[CITA:c1]]" in editable
    texto = capa2["piezas"][TEXTO0]["texto"]
    assert "⟦cita c1 · T-999 de 2023⟧" in texto and SENT1 not in ediciones.parrafos(texto)[0]


def _entrada_con_fichas_descuadradas() -> tuple[dict, dict]:
    v1 = valores()
    ia = ediciones.normalizar(ediciones.a_editable(BLOQUE0, ediciones.mapa_citas(v1)))
    partes = ediciones.parrafos(ia)
    texto = "\n\n".join([partes[0].replace(f"⟦cita c1 · {SENT1}⟧", "").strip(), partes[1], partes[2]])
    capa = vacia()
    capa["piezas"][TEXTO0] = {"ia": ia, "texto": texto, "consolidado": ia, "ancla": None, "avisos": []}
    v2 = con(v1, TEXTO0, f"{BLOQUE0}\n\nPárrafo nuevo de la IA al final.")
    return v2, capa


def test_fusion_limpia_con_fichas_descuadradas_se_convierte_en_conflicto():
    v2, capa = _entrada_con_fichas_descuadradas()
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    conflicto = capa2["conflictos"][TEXTO0]
    assert not conflicto["huerfana"]
    tipos = [t["tipo"] for t in conflicto["trozos"]]
    assert "conflicto" in tipos
    trozo = next(t for t in conflicto["trozos"] if t["tipo"] == "conflicto")
    assert trozo["nuevo"] != trozo["mio"]
    respuesta = ediciones.respuesta(v2, capa2)
    assert [t for t in respuesta["conflictos"][0]["trozos"] if t["tipo"] == "conflicto"][0]["mio_permitido"] is False
    capa3 = ediciones.resolver(v2, capa2, TEXTO0, ["nuevo"])
    assert capa3["conflictos"] == {} and capa3["piezas"] == {}
    assert aplicado(v2, capa3, TEXTO0) == ediciones.obtener(v2, TEXTO0)


def test_sincronizar_reanclar_contestaciones_reordenadas():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido por el despacho.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"].reverse()
    capa2, eventos = sin_mutar(ediciones.sincronizar, v2, capa)
    assert list(capa2["piezas"]) == [CONT1]
    assert capa2["piezas"][CONT1]["ancla"] == "Entidad Uno"
    assert capa2["conflictos"] == {} and eventos == []
    aplicada = ediciones.aplicar(v2, capa2)["apertura"]["contestaciones"]
    assert [c["texto"] for c in aplicada] == [CONT_DOS, "Uno corregido por el despacho."]
    assert ediciones.respuesta(v2, capa2)["piezas"][CONT1]["editados"] == [0]


def test_sincronizar_reanclar_un_intercambio_de_dos_contestaciones():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido.")
    capa = editar(v1, capa, CONT1, 0, "Dos corregido.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"].reverse()
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert eventos == [] and capa2["conflictos"] == {}
    assert capa2["piezas"][CONT0]["ancla"] == "Entidad Dos" and capa2["piezas"][CONT0]["texto"] == "Dos corregido."
    assert capa2["piezas"][CONT1]["ancla"] == "Entidad Uno" and capa2["piezas"][CONT1]["texto"] == "Uno corregido."
    assert [c["texto"] for c in ediciones.aplicar(v2, capa2)["apertura"]["contestaciones"]] == ["Dos corregido.", "Uno corregido."]


def test_sincronizar_reanclar_lleva_el_conflicto_con_la_entrada():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido por el despacho.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"].reverse()
    v2["apertura"]["contestaciones"][1]["texto"] = "Uno reescrito por la IA."
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert list(capa2["conflictos"]) == [CONT1] and list(capa2["piezas"]) == [CONT1]
    assert [e["pieza"] for e in eventos] == [CONT1]
    assert ediciones.respuesta(v2, capa2)["conflictos"][0]["etiqueta"] == "Antecedentes: contestación de Entidad Uno"
    assert aplicado(v2, capa2, CONT1) == "Uno reescrito por la IA."
    with pytest.raises(ErrorEdicion) as e:
        editar(v2, capa2, CONT1, 0, "x")
    assert e.value.estado == 409
    capa3 = ediciones.sincronizar(v2, ediciones.restaurar(v2, capa2, CONT1))[0]
    assert capa3["piezas"] == {} and capa3["conflictos"] == {}


def test_una_contestacion_que_cambia_de_entidad_en_su_lugar_es_huerfana():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido por el despacho.")
    v2 = copy.deepcopy(v1)
    del v2["apertura"]["contestaciones"][0]
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"][CONT0] == {"ia": None, "huerfana": True, "trozos": []}
    assert [(e["accion"], e["pieza"], e["ia"]) for e in eventos] == [("conflicto", CONT0, None)]
    assert aplicado(v2, capa2, CONT0) == CONT_DOS
    respuesta = ediciones.respuesta(v2, capa2)
    assert respuesta["conflictos"] == [
        {
            "pieza": CONT0,
            "etiqueta": "Antecedentes: contestación de Entidad Uno",
            "huerfana": True,
            "trozos": [{"tipo": "ok", "parrafos": ["Uno corregido por el despacho."]}],
        }
    ]
    assert respuesta["piezas"][CONT0]["parrafos"] == [CONT_DOS]
    capa3, eventos3 = ediciones.sincronizar(v2, capa2)
    assert capa3 == capa2 and eventos3 == []


def test_un_huerfano_no_pisa_a_una_entrada_reanclada_en_su_indice():
    v1 = valores()
    v1["apertura"]["contestaciones"].append({"entidad": "Entidad Tres", "silencio": False, "texto": "Tres respondió."})
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido.")
    capa = editar(v1, capa, CONT1, 0, "Dos corregido.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"] = [
        {"entidad": "Entidad Tres", "silencio": False, "texto": "Tres respondió."},
        {"entidad": "Entidad Uno", "silencio": False, "texto": CONT_UNO},
    ]
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert len(capa2["piezas"]) == 2
    textos = {e["texto"] for e in capa2["piezas"].values()}
    assert textos == {"Uno corregido.", "Dos corregido."}
    assert capa2["piezas"][CONT1]["texto"] == "Uno corregido."
    huerfana = next(p for p, e in capa2["piezas"].items() if e["texto"] == "Dos corregido.")
    assert huerfana != CONT1 and capa2["conflictos"][huerfana]["huerfana"]
    assert ediciones.obtener(v2, huerfana) is None
    assert aplicado(v2, capa2, CONT1) == "Uno corregido."
    assert ediciones.respuesta(v2, capa2)["conflictos"][0]["etiqueta"] == "Antecedentes: contestación de Entidad Dos"


def test_una_entrada_de_contestacion_sin_ancla_conserva_su_clave_y_no_se_pisa():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido.")
    capa["piezas"][CONT0]["ancla"] = None
    capa2, eventos = ediciones.sincronizar(v1, capa)
    assert capa2 == capa and eventos == []

    capa = editar(v1, capa, CONT1, 0, "Dos corregido.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"].reverse()
    capa3, _ = ediciones.sincronizar(v2, capa)
    assert {p: e["texto"] for p, e in capa3["piezas"].items()} == {CONT0: "Uno corregido.", CONT1: "Dos corregido."}
    assert capa3["piezas"][CONT0]["ancla"] is None and capa3["piezas"][CONT1]["ancla"] == "Entidad Dos"
    assert not capa3["conflictos"][CONT0]["huerfana"] and capa3["conflictos"][CONT1]["huerfana"]


def test_un_bloque_que_desaparece_es_huerfano():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO1, 0, f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    del v2["consideraciones"]["bloques"][1]
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"][TEXTO1] == {"ia": None, "huerfana": True, "trozos": []}
    assert capa2["piezas"][TEXTO1] == capa["piezas"][TEXTO1]
    assert [e["accion"] for e in eventos] == ["conflicto"]
    assert TEXTO1 not in ediciones.respuesta(v2, capa2)["piezas"]
    conflicto = ediciones.respuesta(v2, capa2)["conflictos"][0]
    assert conflicto["etiqueta"] == "Consideraciones: bloque «Continuidad del servicio»"
    assert conflicto["trozos"] == [{"tipo": "ok", "parrafos": [f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧."]}]
    assert ediciones.aplicar(v2, capa2) == v2


def test_sin_apertura_ni_consideraciones_las_piezas_son_huerfanas():
    v1 = valores()
    capa = editar(v1, vacia(), IMPUGNA, 0, "Impugnación corregida.")
    capa = editar(v1, capa, TEXTO0, 0, f"Primero {P0.replace('[[CITA:c1]]', '⟦cita c1 · T-200 de 2022⟧')}")
    capa2, _ = ediciones.sincronizar({"citas": v1["citas"]}, capa)
    assert set(capa2["conflictos"]) == {IMPUGNA, TEXTO0}
    assert all(c["huerfana"] for c in capa2["conflictos"].values())


def test_un_huerfano_se_recupera_si_la_pieza_reaparece():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO1, 0, f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    del v2["consideraciones"]["bloques"][1]
    capa2, _ = ediciones.sincronizar(v2, capa)
    capa3, _ = ediciones.sincronizar(v1, capa2)
    assert capa3["conflictos"] == {} and capa3["piezas"][TEXTO1]["texto"] == capa["piezas"][TEXTO1]["texto"]


# ---------------------------------------------------------------- reanclaje de bloques por título

TITULO1 = "consideraciones.bloques.1.titulo"
EXTRA0 = "Párrafo del despacho sobre la salud como derecho."
TITULO_HUMANO = "La salud, un derecho fundamental"


def con_bloque0_editado(v1: dict, con_titulo: bool = False) -> dict:
    capa = editar(v1, vacia(), TEXTO0, 2, f"{P2}\n\n{EXTRA0}")
    return editar(v1, capa, TITULO0, 0, TITULO_HUMANO) if con_titulo else capa


def test_editar_un_bloque_ancla_titulo_y_texto_al_titulo_de_la_ia():
    capa = con_bloque0_editado(valores(), con_titulo=True)
    assert capa["piezas"][TEXTO0]["ancla"] == capa["piezas"][TITULO0]["ancla"] == "La salud como derecho"


def test_bloques_reordenados_el_texto_humano_sigue_a_su_bloque():
    v1 = valores()
    capa = con_bloque0_editado(v1, con_titulo=True)
    v2 = copy.deepcopy(v1)
    v2["consideraciones"]["bloques"].reverse()
    capa2, eventos = sin_mutar(ediciones.sincronizar, v2, capa)
    assert eventos == [] and capa2["conflictos"] == {}
    assert capa2["piezas"] == {TEXTO1: capa["piezas"][TEXTO0], TITULO1: capa["piezas"][TITULO0]}
    bloques = ediciones.aplicar(v2, capa2)["consideraciones"]["bloques"]
    assert bloques[0] == v2["consideraciones"]["bloques"][0]
    assert bloques[1]["titulo"] == TITULO_HUMANO and bloques[1]["texto"] == f"{BLOQUE0}\n\n{EXTRA0}"
    resp = ediciones.respuesta(v2, capa2)
    assert resp["piezas"][TEXTO1]["editados"] == [3] and resp["piezas"][TEXTO0]["editados"] == []
    assert ediciones.sincronizar(v2, capa2) == (capa2, [])


def test_un_bloque_cuyo_titulo_ya_no_existe_deja_huerfana_su_edicion_y_la_muestra():
    v1 = valores()
    capa = con_bloque0_editado(v1)
    v2 = copy.deepcopy(v1)
    v2["consideraciones"]["bloques"][0]["titulo"] = "El carácter fundamental de la salud"
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"] == {TEXTO0: {"ia": None, "huerfana": True, "trozos": []}}
    assert [(e["accion"], e["pieza"]) for e in eventos] == [("conflicto", TEXTO0)]
    assert ediciones.aplicar(v2, capa2) == v2
    assert ediciones.respuesta(v2, capa2)["conflictos"] == [
        {
            "pieza": TEXTO0,
            "etiqueta": "Consideraciones: bloque «La salud como derecho»",
            "huerfana": True,
            "trozos": [{"tipo": "ok", "parrafos": parrafos_de(v1, capa, TEXTO0)}],
        }
    ]
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(v2, capa2, TEXTO0, [])
    assert e.value.estado == 422
    capa3 = ediciones.restaurar(v2, capa2, TEXTO0)
    assert capa3 == vacia() | {"version": capa3["version"]}


def test_un_titulo_humano_que_la_ia_cambia_queda_huerfano():
    v1 = valores()
    capa = editar(v1, vacia(), TITULO0, 0, "Título del despacho")
    capa2, _ = ediciones.sincronizar(con(v1, TITULO0, "Título de la IA"), capa)
    assert capa2["conflictos"][TITULO0]["huerfana"]
    [conflicto] = ediciones.respuesta(con(v1, TITULO0, "Título de la IA"), capa2)["conflictos"]
    assert conflicto["etiqueta"] == "Consideraciones: título del bloque «La salud como derecho»"
    assert conflicto["trozos"] == [{"tipo": "ok", "parrafos": ["Título del despacho"]}]


def test_un_bloque_huerfano_no_pisa_al_bloque_que_llega_a_su_indice():
    v1 = valores()
    capa = con_bloque0_editado(v1)
    capa = editar(v1, capa, TEXTO1, 0, f"Continuidad revisada ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    b0, b1 = v2["consideraciones"]["bloques"]
    b0["titulo"] = "Otro tema"
    v2["consideraciones"]["bloques"] = [b1, b0]
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert capa2["piezas"][TEXTO0]["texto"] == f"Continuidad revisada ⟦cita c2 · {SENT2}⟧."
    assert TEXTO0 not in capa2["conflictos"] and TEXTO1 not in capa2["piezas"]
    huerfana = next(p for p, e in capa2["piezas"].items() if e["texto"].endswith(EXTRA0))
    assert huerfana == "consideraciones.bloques.2.texto" and capa2["conflictos"][huerfana]["huerfana"]
    assert ediciones.obtener(v2, huerfana) is None
    aplicado_v2 = ediciones.aplicar(v2, capa2)["consideraciones"]["bloques"]
    assert aplicado_v2[0]["texto"] == "Continuidad revisada [[CITA:c2]]." and aplicado_v2[1] == b0
    assert ediciones.sincronizar(v2, capa2) == (capa2, [])


def test_un_titulo_humano_consolidado_que_la_ia_conserva_no_deja_huerfano_al_bloque():
    v1 = valores()
    capa = con_bloque0_editado(v1, con_titulo=True)
    v2 = consolidado(v1, capa)
    assert v2["consideraciones"]["bloques"][0]["titulo"] == TITULO_HUMANO
    v3 = copy.deepcopy(v2)
    v3["consideraciones"]["bloques"].reverse()
    capa3, eventos = ediciones.sincronizar(v3, capa)
    assert capa3["conflictos"] == {} and eventos == []
    assert set(capa3["piezas"]) == {TEXTO1, TITULO1}
    bloques = ediciones.aplicar(v3, capa3)["consideraciones"]["bloques"]
    assert bloques[1]["titulo"] == TITULO_HUMANO and bloques[1]["texto"] == f"{BLOQUE0}\n\n{EXTRA0}"
    assert bloques[0] == v3["consideraciones"]["bloques"][0]


def test_el_texto_de_un_bloque_con_titulo_humano_se_aplica_aunque_el_titulo_se_fije_antes():
    v1 = valores()
    capa = con_bloque0_editado(v1, con_titulo=True)
    capa["piezas"] = {TITULO0: capa["piezas"][TITULO0], TEXTO0: capa["piezas"][TEXTO0]}
    bloque = ediciones.aplicar(v1, capa)["consideraciones"]["bloques"][0]
    assert bloque["titulo"] == TITULO_HUMANO and bloque["texto"].endswith(EXTRA0)


def test_una_entrada_de_bloque_sin_ancla_sigue_por_indice():
    v1 = valores()
    capa = con_bloque0_editado(v1)
    capa["piezas"][TEXTO0]["ancla"] = None
    v2 = copy.deepcopy(v1)
    v2["consideraciones"]["bloques"][0]["titulo"] = "Otro título"
    assert ediciones.sincronizar(v2, capa) == (capa, [])
    assert aplicado(v2, capa, TEXTO0).endswith(EXTRA0)


def test_un_texto_editado_tras_consolidar_un_titulo_hereda_el_ancla_del_titulo():
    v1 = valores()
    capa = editar(v1, vacia(), TITULO0, 0, "Título humano 1")
    v2 = consolidado(v1, capa)
    capa, _ = ediciones.sincronizar(v2, capa)
    assert capa["conflictos"] == {}
    capa = editar(v2, capa, TEXTO0, 2, f"{P2}\n\n{EXTRA0}")
    assert capa["piezas"][TEXTO0]["ancla"] == capa["piezas"][TITULO0]["ancla"] == "La salud como derecho"
    capa = editar(v2, capa, TITULO0, 0, "Título humano 2")
    v3 = consolidado(v2, capa)
    assert v3["consideraciones"]["bloques"][0]["titulo"] == "Título humano 2"
    capa3, eventos = ediciones.sincronizar(v3, capa)
    assert capa3["conflictos"] == {} and eventos == []
    bloque = ediciones.aplicar(v3, capa3)["consideraciones"]["bloques"][0]
    assert bloque["titulo"] == "Título humano 2" and bloque["texto"].endswith(EXTRA0)
    # una IA que vuelve al título original tampoco deja huérfano el texto
    v4 = con(v3, TITULO0, "La salud como derecho")
    capa4, _ = ediciones.sincronizar(v4, capa3)
    assert capa4["conflictos"] == {} and aplicado(v4, capa4, TEXTO0).endswith(EXTRA0)


def test_una_entrada_creada_al_resolver_hereda_el_ancla_de_su_hermana():
    v1 = valores()
    capa = editar(v1, vacia(), TITULO0, 0, "Título humano")
    v2 = consolidado(v1, capa)
    capa, _ = ediciones.sincronizar(v2, capa)
    partes = parrafos_de(v2, capa, TEXTO0)
    capa["conflictos"][TEXTO0] = {
        "ia": "\n\n".join(partes),
        "huerfana": False,
        "trozos": [
            {"tipo": "conflicto", "mio": [partes[0].replace("Primer", "Primerísimo")], "nuevo": [partes[0]]},
            {"tipo": "ok", "parrafos": partes[1:]},
        ],
    }
    capa2 = ediciones.resolver(v2, capa, TEXTO0, ["mio"])
    assert capa2["piezas"][TEXTO0]["ancla"] == capa2["piezas"][TITULO0]["ancla"] == "La salud como derecho"


def test_sincronizar_es_idempotente_cuando_una_entrada_borrada_libera_un_sitio():
    def vals(bloques):
        v = valores()
        v["consideraciones"]["bloques"] = [{"titulo": t, "reparo_ids": [], "texto": x} for t, x in bloques]
        return v

    def x(n):
        return f"Párrafo {n} uno.\n\nPárrafo {n} dos.\n\nPárrafo {n} tres."

    v1 = vals([("Z", x("a")), ("Z", x("b"))])
    capa = editar(v1, vacia(), TEXTO0, 1, "Párrafo a dos humano.")
    capa = editar(v1, capa, TEXTO1, 1, "Párrafo b dos humano.")
    v2 = vals([("Z", x("a").replace("a dos", "a dos IA")), ("B", x("c"))])
    capa, _ = ediciones.sincronizar(v2, capa)
    capa = ediciones.restaurar(v2, capa, TEXTO0)
    s1, _ = ediciones.sincronizar(v2, capa)
    assert ediciones.sincronizar(v2, s1) == (s1, [])


def test_al_buscar_su_bloque_el_titulo_exacto_de_la_ia_gana_a_un_titulo_humano():
    v1 = valores()
    # el despacho tituló el bloque 0 igual que el bloque 1 de la IA
    capa = editar(v1, vacia(), TITULO0, 0, "Continuidad del servicio")
    capa = editar(v1, capa, TEXTO0, 2, f"{P2}\n\n{EXTRA0}")
    capa = editar(v1, capa, TEXTO1, 0, f"Continuidad revisada ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    v2["consideraciones"]["bloques"].reverse()
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"] == {} and eventos == []
    assert set(capa2["piezas"]) == {TITULO1, TEXTO1, "consideraciones.bloques.0.texto"}
    bloques = ediciones.aplicar(v2, capa2)["consideraciones"]["bloques"]
    assert bloques[0]["titulo"] == "Continuidad del servicio" and bloques[0]["texto"] == "Continuidad revisada [[CITA:c2]]."
    assert bloques[1]["titulo"] == "Continuidad del servicio" and bloques[1]["texto"].endswith(EXTRA0)
    assert ediciones.sincronizar(v2, capa2) == (capa2, [])


def test_dos_bloques_que_se_intercambian_llevan_cada_uno_su_edicion():
    v1 = valores()
    capa = con_bloque0_editado(v1)
    capa = editar(v1, capa, TEXTO1, 0, f"Continuidad revisada ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    v2["consideraciones"]["bloques"].reverse()
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert eventos == [] and capa2["conflictos"] == {}
    bloques = ediciones.aplicar(v2, capa2)["consideraciones"]["bloques"]
    assert bloques[0]["titulo"] == "Continuidad del servicio" and bloques[0]["texto"] == "Continuidad revisada [[CITA:c2]]."
    assert bloques[1]["titulo"] == "La salud como derecho" and bloques[1]["texto"].endswith(EXTRA0)


def test_restaurar_despues_de_consolidar_devuelve_el_texto_de_la_ia_y_sobrevive_al_rebase():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = consolidado(v1, capa)
    assert "revisada por el despacho" in ediciones.obtener(v2, TEXTO0)
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert eventos == [] and capa2["conflictos"] == {}
    assert capa2["piezas"][TEXTO0]["consolidado"] == capa["piezas"][TEXTO0]["texto"]

    capa3 = sin_mutar(ediciones.restaurar, v2, capa2, TEXTO0)
    assert TEXTO0 in capa3["piezas"]
    assert capa3["piezas"][TEXTO0]["texto"] == capa3["piezas"][TEXTO0]["ia"]
    assert parrafos_de(v2, capa3, TEXTO0)[1] == ediciones.parrafos(ediciones.a_editable(BLOQUE0, ediciones.mapa_citas(v2)))[1]
    assert ediciones.respuesta(v2, capa3)["piezas"][TEXTO0]["editados"] == []
    assert aplicado(v2, capa3, TEXTO0) == BLOQUE0

    capa4, eventos4 = ediciones.sincronizar(v2, capa3)
    assert capa4 == capa3 and eventos4 == []
    assert aplicado(v2, capa4, TEXTO0) == BLOQUE0
    assert ediciones.consolidar(v2, capa4)["consideraciones"]["bloques"][0]["texto"] == BLOQUE0


def test_volver_a_editar_el_mismo_parrafo_despues_de_consolidar_no_da_conflicto_falso():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = consolidado(v1, capa)
    capa2, _ = ediciones.sincronizar(v2, capa)
    capa3 = editar(v2, capa2, TEXTO0, 1, "Segunda edición del mismo párrafo ⟦imagen · tabla de plazos⟧.")
    capa4, eventos = ediciones.sincronizar(v2, capa3)
    assert capa4["conflictos"] == {} and eventos == []
    assert capa4 == capa3
    assert capa4["piezas"][TEXTO0]["ia"] != capa4["piezas"][TEXTO0]["consolidado"]
    assert parrafos_de(v2, capa4, TEXTO0)[1] == "Segunda edición del mismo párrafo ⟦imagen · tabla de plazos⟧."
    assert ediciones.respuesta(v2, capa4)["piezas"][TEXTO0]["editados"] == [1]


def test_una_correccion_de_la_ia_despues_de_consolidar_se_funde_con_el_texto_humano():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = consolidado(v1, capa)
    capa2, _ = ediciones.sincronizar(v2, capa)
    v3 = con(v2, TEXTO0, f"{P0_IA}\n\n{ediciones.parrafos(ediciones.obtener(v2, TEXTO0))[1]}\n\n{P2}")
    capa3, eventos = ediciones.sincronizar(v3, capa2)
    assert capa3["conflictos"] == {} and [e["accion"] for e in eventos] == ["rebase"]
    assert capa3["piezas"] == {} or capa3["piezas"][TEXTO0]["ia"] == capa3["piezas"][TEXTO0]["consolidado"]


def test_sincronizar_con_titulos_sin_ancla():
    # Una entrada sin ancla (capa anterior al anclaje de bloques) sigue el índice: el cambio de título es un conflicto.
    v1 = valores()
    capa = editar(v1, vacia(), TITULO0, 0, "Título del despacho")
    capa["piezas"][TITULO0]["ancla"] = None
    v2 = con(v1, TITULO0, "Título de la IA")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    assert capa2["conflictos"][TITULO0]["trozos"] == [{"tipo": "conflicto", "mio": ["Título del despacho"], "nuevo": ["Título de la IA"]}]
    capa3 = ediciones.resolver(v2, capa2, TITULO0, ["mio"])
    assert aplicado(v2, capa3, TITULO0) == "Título del despacho"
    capa4, eventos = ediciones.sincronizar(v2, capa3)
    assert capa4 == capa3 and eventos == []


# ---------------------------------------------------------------- restaurar


def test_restaurar_una_pieza_editada_la_deja_como_la_ia():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "Otro.")
    capa2 = sin_mutar(ediciones.restaurar, v, capa, TEXTO0)
    assert capa2["piezas"] == {}
    assert aplicado(v, capa2, TEXTO0) == BLOQUE0


def test_restaurar_sin_entrada_no_cambia_nada_y_una_pieza_desconocida_es_404():
    v = valores()
    assert ediciones.restaurar(v, vacia(), TEXTO0) == vacia()
    with pytest.raises(ErrorEdicion) as e:
        ediciones.restaurar(v, vacia(), "apertura.nada")
    assert e.value.estado == 404


def test_restaurar_una_pieza_en_conflicto_toma_el_texto_de_la_correccion():
    v2, capa, _ = con_conflicto()
    capa2 = sin_mutar(ediciones.restaurar, v2, capa, TEXTO0)
    u = capa["conflictos"][TEXTO0]["ia"]
    assert capa2["conflictos"] == {}
    assert capa2["piezas"][TEXTO0]["ia"] == capa2["piezas"][TEXTO0]["texto"] == u
    assert aplicado(v2, capa2, TEXTO0) == ediciones.obtener(v2, TEXTO0)
    capa3, eventos = ediciones.sincronizar(v2, capa2)
    assert capa3["piezas"] == {} and capa3["conflictos"] == {} and eventos == []


def test_restaurar_una_pieza_huerfana_la_descarta():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO1, 0, f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    del v2["consideraciones"]["bloques"][1]
    capa2, _ = ediciones.sincronizar(v2, capa)
    capa3 = sin_mutar(ediciones.restaurar, v2, capa2, TEXTO1)
    assert capa3["piezas"] == {} and capa3["conflictos"] == {}


# ---------------------------------------------------------------- resolver


def test_resolver_elige_por_trozo_y_limpia_el_conflicto():
    v2, capa, _ = con_conflicto()
    u = capa["conflictos"][TEXTO0]["ia"]
    capa_mio = sin_mutar(ediciones.resolver, v2, capa, TEXTO0, ["mio"])
    assert capa_mio["conflictos"] == {}
    e = capa_mio["piezas"][TEXTO0]
    assert e["ia"] == e["consolidado"] == u
    assert ediciones.parrafos(e["texto"])[1] == P1_HUMANO
    assert ediciones.respuesta(v2, capa_mio)["piezas"][TEXTO0]["editados"] == [1]
    assert "revisada por el despacho" in aplicado(v2, capa_mio, TEXTO0)
    assert ediciones.sincronizar(v2, capa_mio)[1] == []

    capa_nuevo = ediciones.resolver(v2, capa, TEXTO0, ["nuevo"])
    assert capa_nuevo["conflictos"] == {} and capa_nuevo["piezas"] == {}
    assert aplicado(v2, capa_nuevo, TEXTO0) == ediciones.obtener(v2, TEXTO0)


def test_resolver_con_varios_conflictos_toma_las_elecciones_en_orden():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 0, f"Cero del despacho {P0.replace('[[CITA:c1]]', f'⟦cita c1 · {SENT1}⟧')}")
    capa = editar(v1, capa, TEXTO0, 2, "Dos del despacho.")
    v2 = con(v1, TEXTO0, f"Cero de la IA [[CITA:c1]].\n\n{P1}\n\nDos de la IA.")
    capa2, _ = ediciones.sincronizar(v2, capa)
    pendientes = [t for t in capa2["conflictos"][TEXTO0]["trozos"] if t["tipo"] == "conflicto"]
    assert len(pendientes) == 2
    final = ediciones.resolver(v2, capa2, TEXTO0, ["nuevo", "mio"])
    partes = ediciones.parrafos(final["piezas"][TEXTO0]["texto"])
    assert partes[0].startswith("Cero de la IA") and partes[2] == "Dos del despacho."
    final = ediciones.resolver(v2, capa2, TEXTO0, ["mio", "nuevo"])
    partes = ediciones.parrafos(final["piezas"][TEXTO0]["texto"])
    assert partes[0].startswith("Cero del despacho") and partes[2] == "Dos de la IA."


def test_resolver_rechaza_un_numero_de_elecciones_que_no_cuadra():
    v2, capa, _ = con_conflicto()
    for elecciones in ([], ["mio", "nuevo"]):
        with pytest.raises(ErrorEdicion) as e:
            sin_mutar(ediciones.resolver, v2, capa, TEXTO0, elecciones)
        assert e.value.estado == 422
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(v2, capa, TEXTO0, ["ambos"])
    assert e.value.estado == 422


def test_resolver_sin_conflicto_es_409():
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(valores(), vacia(), TEXTO0, ["mio"])
    assert e.value.estado == 409


def test_resolver_una_pieza_huerfana_es_422():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO1, 0, f"Texto nuevo del bloque dos ⟦cita c2 · {SENT2}⟧.")
    v2 = copy.deepcopy(v1)
    del v2["consideraciones"]["bloques"][1]
    capa2, _ = ediciones.sincronizar(v2, capa)
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(v2, capa2, TEXTO1, [])
    assert e.value.estado == 422 and "descartar" in e.value.mensaje


def test_resolver_rechaza_mio_cuando_las_fichas_difieren():
    v2, capa, _ = _conflicto_con_fichas_distintas()
    pendiente = [t for t in ediciones.respuesta(v2, capa)["conflictos"][0]["trozos"] if t["tipo"] == "conflicto"]
    assert [t["mio_permitido"] for t in pendiente] == [False]
    with pytest.raises(ErrorEdicion) as e:
        sin_mutar(ediciones.resolver, v2, capa, TEXTO0, ["mio"])
    assert e.value.estado == 422 and "citas o imágenes" in e.value.mensaje
    assert ediciones.resolver(v2, capa, TEXTO0, ["nuevo"])["conflictos"] == {}


def _conflicto_con_fichas_distintas() -> tuple[dict, dict, dict]:
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = con(v1, TEXTO0, f"{P0}\n\nSegundo párrafo de la IA sin imagen.\n\n{P2}")
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert TEXTO0 in capa2["conflictos"]
    return v2, capa2, capa


def test_mio_permitido_se_calcula_por_trozo():
    v2, capa, _ = con_conflicto()
    conflicto = ediciones.respuesta(v2, capa)["conflictos"][0]
    assert [t["tipo"] for t in conflicto["trozos"]] == ["ok", "conflicto", "ok"]
    assert conflicto["trozos"][1]["mio_permitido"] is True


def test_resolver_valida_el_resultado_contra_la_ia():
    v2, capa, _ = con_conflicto()
    capa["conflictos"][TEXTO0]["trozos"][1]["mio"] = ["Con [[CITA:c1]] tecleada."]
    capa["conflictos"][TEXTO0]["trozos"][1]["nuevo"] = ["Con [[CITA:c1]] tecleada."]
    with pytest.raises(ErrorEdicion) as e:
        ediciones.resolver(v2, capa, TEXTO0, ["mio"])
    assert e.value.estado == 422


# ---------------------------------------------------------------- integridad de las fichas


@pytest.mark.parametrize(
    "k, roto",
    [
        (0, f"Primer párrafo ⟦cita c1\n\n· {SENT1}⟧ cierre."),
        (0, f"Primer párrafo ⟦cita c1 ·\n\n{SENT1}⟧ cierre."),
        (0, f"Primer párrafo ⟦cita c1 · {SENT1}\n\n⟧ cierre."),
        (0, f"Primer párrafo ⟦cita\n\nc1 · {SENT1}⟧ cierre."),
        (1, "Segundo párrafo ⟦imagen\n\n· tabla de plazos⟧ incluida."),
        (1, "Segundo párrafo ⟦imagen ·\n\ntabla de plazos⟧ incluida."),
    ],
)
def test_una_ficha_partida_por_una_linea_en_blanco_se_rechaza(k, roto):
    v = valores()
    with pytest.raises(ErrorEdicion) as e:
        sin_mutar(lambda vals, capa: editar(vals, capa, TEXTO0, k, roto), v, vacia())
    assert e.value.estado == 422 and "suelto" in e.value.mensaje


def test_una_ficha_no_cruza_el_limite_entre_parrafos():
    assert ediciones.fichas(f"⟦cita c1\n\n· {SENT1}⟧") == {}
    assert ediciones.fichas(f"a ⟦cita c1 ·\n\n{SENT1}⟧ ⟦imagen\n\n· x⟧") == {}
    assert ediciones.a_canonico("⟦imagen\n\n· x⟧") == "⟦imagen\n\n· x⟧"
    assert ediciones.fichas(f"a ⟦cita c1 ·  {SENT1} ⟧ ⟦imagen ·  tabla  ⟧") == {
        ("cita", "c1", SENT1): 1,
        ("imagen", "tabla"): 1,
    }


@pytest.mark.parametrize(
    "roto, esperados",
    [
        (
            "Uno [[CITA:c1]].\n\n[[IMAGEN captura 1\n\nde la historia clinica]]\n\nTres [[CITA:c2]] final.",
            [
                f"Uno ⟦cita c1 · {SENT1}⟧.",
                "[[IMAGEN captura 1",
                "de la historia clinica]]",
                f"Tres ⟦cita c2 · {SENT2}⟧ final.",
            ],
        ),
        ("Ver [[CITA:c1\n\n]] aquí.\n\nFin.", ["Ver [[CITA:c1", "]] aquí.", "Fin."]),
        ("Ver [[IMAGEN a\n\nb]] [[CITA:c1]]\n\nFin.", ["Ver [[IMAGEN a", f"b]] ⟦cita c1 · {SENT1}⟧", "Fin."]),
    ],
)
def test_los_parrafos_editables_son_los_del_canonico_aunque_la_ia_deje_una_marca_rota(roto, esperados):
    v = con(valores(), TEXTO0, roto)
    assert len(ediciones.parrafos(roto)) == len(esperados)
    assert parrafos_de(v, vacia(), TEXTO0) == esperados
    corregido = esperados[-1][:-1] + " corregido."
    capa = editar(v, vacia(), TEXTO0, len(esperados) - 1, corregido)
    editables = parrafos_de(v, capa, TEXTO0)
    assert editables[:-1] == esperados[:-1] and editables[-1] == corregido
    assert len(ediciones.parrafos(aplicado(v, capa, TEXTO0))) == len(editables)


STRAY = "Segundo párrafo con [[CITA: c1 c2]] mal formado."


def test_un_resto_mal_formado_de_la_ia_no_bloquea_la_edicion_de_otro_parrafo():
    v = con(valores(), TEXTO0, f"{P0}\n\n{STRAY}\n\n{P2}")
    capa = editar(v, vacia(), TEXTO0, 2, "Finalmente, el cierre corregido.")
    assert aplicado(v, capa, TEXTO0) == f"{P0}\n\n{STRAY}\n\nFinalmente, el cierre corregido."
    capa = editar(v, capa, TEXTO0, 1, STRAY.replace("mal formado", "mal formado, pero ahí sigue"))
    assert "[[CITA: c1 c2]]" in aplicado(v, capa, TEXTO0)
    assert ediciones.obtener(ediciones.aplicar(v, capa), TEXTO0).count("[[CITA: c1 c2]]") == 1


def test_un_resto_mal_formado_de_la_ia_se_puede_quitar_pero_no_repetir_ni_agregar_otro():
    v = con(valores(), TEXTO0, f"{P0}\n\n{STRAY}\n\n{P2}")
    assert "[[CITA: c1 c2]]" not in aplicado(v, editar(v, vacia(), TEXTO0, 1, "Segundo párrafo ya bien formado."), TEXTO0)
    for texto in (f"{STRAY} Otro [[ más.", f"{STRAY} y ]] otro.", f"{STRAY} [[CITA: c1 c2]]"):
        with pytest.raises(ErrorEdicion) as e:
            editar(v, vacia(), TEXTO0, 1, texto)
        assert e.value.estado == 422 and "[[" in e.value.mensaje


def test_un_resto_con_corchetes_de_ficha_que_ya_traia_el_texto_de_la_ia_no_bloquea_la_apertura():
    v = con(valores(), HECHOS_P, "La accionante dijo ⟦FALTA: fecha⟧ algo.\n\nLa entidad respondió.")
    capa = editar(v, vacia(), HECHOS_P, 1, "La entidad respondió tarde.")
    assert aplicado(v, capa, HECHOS_P) == "La accionante dijo ⟦FALTA: fecha⟧ algo.\n\nLa entidad respondió tarde."
    with pytest.raises(ErrorEdicion) as e:
        editar(v, vacia(), HECHOS_P, 1, "La entidad respondió ⟦FALTA: otra⟧ tarde.")
    assert e.value.estado == 422 and "suelto" in e.value.mensaje


def test_no_se_puede_armar_una_marca_completa_con_los_restos_de_una_marca_rota():
    roto = "Uno.\n\n[[IMAGEN captura 1\n\nde la historia clinica]]\n\nTres final."
    v = con(valores(), TEXTO0, roto)
    capa = editar(v, vacia(), TEXTO0, 2, "Texto.")
    assert parrafos_de(v, capa, TEXTO0) == ["Uno.", "[[IMAGEN captura 1", "Texto.", "Tres final."]
    with pytest.raises(ErrorEdicion) as e:
        editar(v, capa, TEXTO0, 1, "[[IMAGEN captura 1 de la historia clinica]]")
    assert e.value.estado == 422 and "[[" in e.value.mensaje
    with pytest.raises(ErrorEdicion) as e:
        editar(v, capa, TEXTO0, 1, "[[IMAGEN captura]]")
    assert e.value.estado == 422 and "[[" in e.value.mensaje
    roto_cita = "Uno.\n\nVer [[CITA:c2\n\n]] aquí.\n\nTres final."
    v2 = con(valores(), TEXTO0, roto_cita)
    capa2 = editar(v2, vacia(), TEXTO0, 2, "Aquí.")
    with pytest.raises(ErrorEdicion) as e:
        editar(v2, capa2, TEXTO0, 1, "Ver [[CITA:c2]]")
    assert e.value.estado == 422


def test_un_resto_mal_formado_en_la_nueva_version_de_la_ia_no_vuelve_conflicto_una_fusion_limpia():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Finalmente, el cierre humano.")
    v2 = con(v1, TEXTO0, f"Primer párrafo con [[CITA: c1 c2]] mal formado y [[CITA:c1]].\n\n{P1}\n\n{P2}")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert capa2["conflictos"] == {}
    assert [e["accion"] for e in eventos] == ["rebase"]
    assert aplicado(v2, capa2, TEXTO0).endswith("Finalmente, el cierre humano.")
    assert "[[CITA: c1 c2]]" in aplicado(v2, capa2, TEXTO0)


@pytest.mark.parametrize("lado", ["mio", "nuevo"])
def test_un_conflicto_con_un_resto_mal_formado_de_la_ia_se_puede_resolver_de_los_dos_lados(lado):
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Finalmente, el cierre humano.")
    v2 = con(v1, TEXTO0, f"{P0}\n\n{P1}\n\nFinalmente, hay [[CITA: c1 c2]] mal formado.")
    capa2, eventos = ediciones.sincronizar(v2, capa)
    assert [e["accion"] for e in eventos] == ["conflicto"]
    capa3 = ediciones.resolver(v2, capa2, TEXTO0, [lado])
    assert capa3["conflictos"] == {}
    esperado = "Finalmente, el cierre humano." if lado == "mio" else "Finalmente, hay [[CITA: c1 c2]] mal formado."
    assert aplicado(v2, capa3, TEXTO0).endswith(esperado)


def test_editar_compacta_los_espacios_dentro_de_una_ficha():
    v = valores()
    p0 = f"Primer párrafo sobre la salud como derecho fundamental ⟦cita c1 · {SENT1}⟧."
    assert editar(v, vacia(), TEXTO0, 0, p0.replace(f"{SENT1}⟧", f"{SENT1}  ⟧"))["piezas"] == {}
    capa = editar(v, vacia(), TEXTO0, 1, "Segundo con ⟦imagen · tabla de plazos ⟧ aquí.")
    assert ediciones.parrafos(capa["piezas"][TEXTO0]["texto"])[1] == "Segundo con ⟦imagen · tabla de plazos⟧ aquí."


# ---------------------------------------------------------------- aplicar y consolidar


def test_aplicar_fija_el_texto_canonico_de_cada_pieza_editada():
    v = valores()
    antes = copy.deepcopy(v)
    capa = editar(v, vacia(), TEXTO0, 1, P1_HUMANO)
    capa = editar(v, capa, IMPUGNA, 1, "Pide confirmar la decisión.")
    capa = editar(v, capa, TITULO0, 0, "Título nuevo")
    aplicada = sin_mutar(ediciones.aplicar, v, capa)
    assert v == antes
    assert aplicada["consideraciones"]["bloques"][0]["titulo"] == "Título nuevo"
    assert aplicada["consideraciones"]["bloques"][0]["texto"] == (
        f"{P0}\n\nSegundo párrafo con la imagen [[IMAGEN tabla de plazos]] revisada por el despacho.\n\n{P2}"
    )
    assert aplicada["apertura"]["impugnacion"] == "La accionante reprocha que el juzgado ignoró la urgencia.\n\nPide confirmar la decisión."
    assert aplicada["consideraciones"]["bloques"][1] == v["consideraciones"]["bloques"][1]
    assert aplicada["apertura"]["antecedentes_hechos"] == HECHOS
    assert aplicada["citas"] == v["citas"]
    assert ediciones.aplicar(v, vacia()) == v


def test_aplicar_conserva_el_texto_de_la_ia_en_las_piezas_en_conflicto():
    v2, capa, _ = con_conflicto()
    capa = editar(v2, capa, IMPUGNA, 0, "Impugnación editada.")
    aplicada = ediciones.aplicar(v2, capa)
    assert ediciones.obtener(aplicada, TEXTO0) == ediciones.obtener(v2, TEXTO0)
    assert ediciones.obtener(aplicada, IMPUGNA).startswith("Impugnación editada.")


def test_aplicar_no_aplica_una_contestacion_cuya_entidad_ya_no_coincide():
    v1 = valores()
    capa = editar(v1, vacia(), CONT0, 0, "Uno corregido.")
    v2 = copy.deepcopy(v1)
    v2["apertura"]["contestaciones"].reverse()
    assert aplicado(v2, capa, CONT0) == CONT_DOS
    assert aplicado(v2, capa, CONT1) == CONT_UNO
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert aplicado(v2, capa2, CONT1) == "Uno corregido."


def test_aplicar_escribe_el_texto_de_la_ia_cuando_restaurar_dejo_la_entrada():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = consolidado(v1, capa)
    capa2 = ediciones.restaurar(v2, ediciones.sincronizar(v2, capa)[0], TEXTO0)
    assert ediciones.obtener(v2, TEXTO0) != BLOQUE0
    assert aplicado(v2, capa2, TEXTO0) == BLOQUE0


def test_consolidar_devuelve_los_objetos_completos_y_la_union_de_secciones():
    v = valores()
    v["ediciones_humanas"] = ["impugnacion"]
    capa = editar(v, vacia(), TEXTO0, 1, P1_HUMANO)
    capa = editar(v, capa, CONT1, 0, "Dos corregido.")
    antes = copy.deepcopy(v)
    update = sin_mutar(ediciones.consolidar, v, capa)
    assert v == antes
    assert set(update) == {"apertura", "consideraciones", "ediciones_humanas"}
    assert update["ediciones_humanas"] == ["antecedentes", "consideraciones", "impugnacion"]
    assert set(update["apertura"]) == set(v["apertura"]) and set(update["consideraciones"]) == set(v["consideraciones"])
    assert update["apertura"]["contestaciones"][1]["texto"] == "Dos corregido."
    assert update["apertura"]["reparos"] == [] and update["consideraciones"]["citas"] == []
    assert update["consideraciones"]["bloques"][0]["texto"].count("revisada por el despacho") == 1
    for prohibida in ("errores", "intentos", "decisiones", "bitacora", "alertas"):
        assert prohibida not in update


def test_consolidar_no_marca_secciones_cuyo_texto_volvio_al_de_la_ia():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    v2 = consolidado(v1, capa)
    capa2 = ediciones.restaurar(v2, ediciones.sincronizar(v2, capa)[0], TEXTO0)
    update = ediciones.consolidar(v2, capa2)
    assert update["ediciones_humanas"] == ["consideraciones"]
    assert update["consideraciones"]["bloques"][0]["texto"] == BLOQUE0
    capa3 = editar(v1, vacia(), TEXTO0, 1, P1_HUMANO)
    capa3["piezas"][TEXTO0].update(texto=capa3["piezas"][TEXTO0]["ia"], consolidado="otro")
    assert ediciones.consolidar(v1, capa3)["ediciones_humanas"] == []


def test_consolidar_con_la_capa_vacia_devuelve_vacio():
    assert ediciones.consolidar(valores(), vacia()) == {}


def test_consolidar_con_conflictos_lanza_409():
    v2, capa, _ = con_conflicto()
    with pytest.raises(ErrorEdicion) as e:
        sin_mutar(ediciones.consolidar, v2, capa)
    assert e.value.estado == 409
    v3 = valores()
    del v3["consideraciones"]["bloques"][1]
    capa = editar(valores(), vacia(), TEXTO1, 0, f"Nuevo ⟦cita c2 · {SENT2}⟧.")
    capa2, _ = ediciones.sincronizar(v3, capa)
    with pytest.raises(ErrorEdicion) as e:
        ediciones.consolidar(v3, capa2)
    assert e.value.estado == 409


def test_consolidar_solo_devuelve_las_secciones_que_hay():
    v = valores()
    capa = editar(v, vacia(), IMPUGNA, 0, "Impugnación nueva.")
    sin_consideraciones = {k: x for k, x in v.items() if k != "consideraciones"}
    update = ediciones.consolidar(sin_consideraciones, capa)
    assert set(update) == {"apertura", "ediciones_humanas"}


# ---------------------------------------------------------------- respuesta


def test_respuesta_no_editable_no_trae_piezas_ni_conflictos():
    v2, capa, _ = con_conflicto()
    assert sin_mutar(ediciones.respuesta, v2, capa, False, "Hay un proceso en curso.") == {
        "editable": False,
        "motivo": "Hay un proceso en curso.",
        "piezas": {},
        "conflictos": [],
    }


def test_respuesta_incluye_todas_las_piezas_del_catalogo():
    v = valores()
    r = sin_mutar(ediciones.respuesta, v, vacia())
    assert r["editable"] is True and r["motivo"] is None and r["conflictos"] == []
    assert list(r["piezas"]) == ediciones.catalogo(v)
    assert r["piezas"][TEXTO0] == {
        "parrafos": [
            f"Primer párrafo sobre la salud como derecho fundamental ⟦cita c1 · {SENT1}⟧.",
            "Segundo párrafo con la imagen ⟦imagen · tabla de plazos⟧ incluida.",
            P2,
        ],
        "editados": [],
        "modificada": False,
        "avisos": [],
    }
    assert r["piezas"][TITULO0]["parrafos"] == ["La salud como derecho"]


def test_respuesta_marca_los_parrafos_editados_respecto_de_la_ia_no_de_u():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "Uno.\n\nDos.")
    assert ediciones.respuesta(v1, capa)["piezas"][TEXTO0]["editados"] == [2, 3]
    v2 = consolidado(v1, capa)
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert ediciones.respuesta(v2, capa2)["piezas"][TEXTO0]["editados"] == [2, 3]


def test_respuesta_marca_modificada_cuando_solo_se_quitaron_parrafos():
    v = valores()
    assert ediciones.respuesta(v, vacia())["piezas"][TEXTO0]["modificada"] is False

    sin_ultimo = editar(v, vacia(), TEXTO0, 2, "  \n ")
    pieza = ediciones.respuesta(v, sin_ultimo)["piezas"][TEXTO0]
    assert pieza["editados"] == [] and pieza["modificada"] is True
    assert len(pieza["parrafos"]) == 2

    reemplazo = editar(v, vacia(), TEXTO0, 2, "Otro texto.")
    assert ediciones.respuesta(v, reemplazo)["piezas"][TEXTO0]["modificada"] is True

    restaurada = ediciones.restaurar(v, sin_ultimo, TEXTO0)
    assert ediciones.respuesta(v, restaurada)["piezas"][TEXTO0]["modificada"] is False


def test_respuesta_modificada_sobrevive_a_la_consolidacion_y_no_marca_un_conflicto():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO0, 2, "  \n ")
    v2 = consolidado(v1, capa)
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert ediciones.respuesta(v2, capa2)["piezas"][TEXTO0]["modificada"] is True

    v3, capa3, _ = con_conflicto()
    assert ediciones.respuesta(v3, capa3)["piezas"][TEXTO0]["modificada"] is False


def test_respuesta_de_un_conflicto():
    v2, capa, _ = con_conflicto()
    r = sin_mutar(ediciones.respuesta, v2, capa)
    u = ediciones.parrafos(capa["conflictos"][TEXTO0]["ia"])
    assert r["piezas"][TEXTO0] == {"parrafos": u, "editados": [], "modificada": False, "avisos": []}
    assert r["conflictos"] == [
        {
            "pieza": TEXTO0,
            "etiqueta": "Consideraciones: bloque 1 (La salud como derecho)",
            "huerfana": False,
            "trozos": [
                {"tipo": "ok", "parrafos": [u[0]]},
                {"tipo": "conflicto", "mio": [P1_HUMANO], "nuevo": [u[1]], "mio_permitido": True},
                {"tipo": "ok", "parrafos": [u[2]]},
            ],
        }
    ]


def test_respuesta_ordena_los_conflictos_como_el_documento():
    v1 = valores()
    capa = editar(v1, vacia(), TEXTO1, 0, f"Del despacho ⟦cita c2 · {SENT2}⟧.")
    capa = editar(v1, capa, HECHOS_P, 0, "Hechos del despacho.")
    v2 = con(con(v1, TEXTO1, "De la IA [[CITA:c2]]."), HECHOS_P, "Hechos de la IA.\n\nSegundo.")
    capa2, _ = ediciones.sincronizar(v2, capa)
    assert [c["pieza"] for c in ediciones.respuesta(v2, capa2)["conflictos"]] == [HECHOS_P, TEXTO1]


# ---------------------------------------------------------------- archivo


def test_leer_sin_archivo_devuelve_la_capa_vacia(tmp_path):
    assert ediciones.leer(tmp_path) == vacia()
    assert not ediciones.hay_conflictos(tmp_path)


@pytest.mark.parametrize(
    "contenido",
    ["{no es json", "[]", '"texto"', '{"piezas": [], "conflictos": {}}', '{"piezas": {"p": {"ia": 1}}, "conflictos": {}}', '{"piezas": {}}'],
)
def test_leer_tolera_un_archivo_corrupto_y_avisa(tmp_path, caplog, contenido):
    (tmp_path / ediciones.ARCHIVO).write_text(contenido, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="tutela2.ediciones"):
        assert ediciones.leer(tmp_path) == vacia()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_leer_sin_archivo_no_avisa(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="tutela2.ediciones"):
        ediciones.leer(tmp_path)
    assert caplog.records == []


def test_guardar_y_leer_son_inversos(tmp_path):
    v2, capa, _ = con_conflicto()
    ruta = ediciones.guardar(tmp_path, capa)
    assert ruta == tmp_path / "ediciones.json" and ediciones.ARCHIVO == "ediciones.json" and ediciones.LOG == "ediciones.jsonl"
    assert ediciones.leer(tmp_path) == capa
    assert ediciones.hay_conflictos(tmp_path)
    assert "ediciones.json" in {p.name for p in tmp_path.iterdir()}
    assert json.loads(ruta.read_text(encoding="utf-8"))["version"] == 1


def test_leer_completa_los_campos_que_faltan(tmp_path):
    crudo = {"piezas": {TEXTO0: {"ia": "a", "texto": "b"}}, "conflictos": {TEXTO0: {"trozos": []}}}
    (tmp_path / ediciones.ARCHIVO).write_text(json.dumps(crudo), encoding="utf-8")
    capa = ediciones.leer(tmp_path)
    assert capa["piezas"][TEXTO0] == {"ia": "a", "texto": "b", "consolidado": "a", "ancla": None, "avisos": []}
    assert capa["conflictos"][TEXTO0] == {"trozos": [], "ia": None, "huerfana": False}


def test_guardar_es_atomico(tmp_path, monkeypatch):
    ediciones.guardar(tmp_path, vacia())
    antes = (tmp_path / ediciones.ARCHIVO).read_text(encoding="utf-8")

    def falla(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", falla)
    capa = vacia()
    capa["piezas"][TEXTO0] = {"ia": "a", "texto": "b", "consolidado": "a", "ancla": None, "avisos": []}
    with pytest.raises(OSError):
        ediciones.guardar(tmp_path, capa)
    assert (tmp_path / ediciones.ARCHIVO).read_text(encoding="utf-8") == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == [ediciones.ARCHIVO]


def test_guardar_usa_un_temporal_y_os_replace(tmp_path, monkeypatch):
    llamadas = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda o, d: (llamadas.append((os.fspath(o), os.fspath(d))), real(o, d))[1])
    ediciones.guardar(tmp_path, vacia())
    assert len(llamadas) == 1
    origen, destino = llamadas[0]
    assert destino == str(tmp_path / ediciones.ARCHIVO) and origen != destino and origen.startswith(str(tmp_path))


def test_registrar_agrega_una_linea_json_por_accion(tmp_path):
    ediciones.registrar(tmp_path, "editar", TEXTO0, "ia", "texto")
    ediciones.registrar(tmp_path, "conflicto", TEXTO1, None, "áéí")
    lineas = (tmp_path / ediciones.LOG).read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 2
    primero, segundo = (json.loads(x) for x in lineas)
    assert set(primero) == {"fecha", "accion", "pieza", "ia", "texto"}
    assert (primero["accion"], primero["pieza"], primero["ia"], primero["texto"]) == ("editar", TEXTO0, "ia", "texto")
    assert (segundo["ia"], segundo["texto"]) == (None, "áéí")
    assert "áéí" in lineas[1]


def test_los_eventos_de_sincronizar_se_pueden_registrar(tmp_path):
    v2, capa, previa = con_conflicto()
    _, eventos = ediciones.sincronizar(v2, previa)
    for evento in eventos:
        ediciones.registrar(tmp_path, **evento)
    assert [json.loads(x)["accion"] for x in (tmp_path / ediciones.LOG).read_text(encoding="utf-8").splitlines()] == ["conflicto"]


def test_error_edicion_lleva_estado_y_mensaje():
    error = ErrorEdicion(422, "mensaje")
    assert (error.estado, error.mensaje, str(error)) == (422, "mensaje", "mensaje")
    assert isinstance(error, Exception)


def test_las_funciones_con_capa_devuelven_una_capa_nueva_aunque_no_cambie_nada():
    v = valores()
    capa = editar(v, vacia(), TEXTO0, 2, "Otro.")
    assert ediciones.sincronizar(v, capa)[0] is not capa
    assert ediciones.restaurar(v, vacia(), TEXTO0) is not None
    vieja = vacia()
    assert ediciones.restaurar(v, vieja, TEXTO0) is not vieja
    assert ediciones.sincronizar(v, vieja)[0] is not vieja
    assert editar(v, vieja, TEXTO0, 2, "Nuevo.")["piezas"] is not vieja["piezas"]
    assert vieja == vacia()
    capa2 = ediciones.sincronizar(v, capa)[0]
    capa2["piezas"][TEXTO0]["texto"] = "mutado"
    assert capa["piezas"][TEXTO0]["texto"] != "mutado"


def test_respuesta_tolera_un_estado_sin_ingesta_o_con_citas_ausentes():
    v = valores()
    capa = editar(v, vacia(), HECHOS_P, 0, "Hechos nuevos.")
    for estado in ({k: x for k, x in v.items() if k != "ingesta"}, {**v, "ingesta": "basura"}, {**v, "citas": None}):
        r = ediciones.respuesta(estado, capa)
        assert r["piezas"][HECHOS_P]["parrafos"][0] == "Hechos nuevos."
    sin_citas = ediciones.respuesta({**v, "citas": []}, vacia())
    assert sin_citas["piezas"][TEXTO0]["parrafos"][0].endswith("⟦cita c1⟧.")
