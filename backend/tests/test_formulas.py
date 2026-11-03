from __future__ import annotations

import pytest

from tutela2 import formulas as f
from tutela2.models import Compulsa, Decision, DisposicionDerecho, Fechas, Metadatos, NumeralesEstandar, Orden, Plazo

CUI = "05001408801820260053001"


def md(**kw) -> Metadatos:
    base = dict(
        cui_1a="05001408801820260053000",
        cui_2a=CUI,
        accionante="Ana Ejemplo",
        accionadas=["Banco Ejemplo S.A."],
        accionante_tratamiento="la señora",
        accionante_identificacion="identificada con cédula de ciudadanía 1.111.111",
        juzgado_a_quo_numero=18,
        juzgado_a_quo_funcion="control_garantias",
        juzgado_a_quo_letras="Dieciocho",
        resultado_a_quo="declaró improcedente el amparo solicitado.",
        impugnante="Ana Ejemplo",
        derechos_invocados=["mínimo vital", "vida digna"],
        fechas=Fechas(fallo_a_quo="2026-10-06"),
    )
    base.update(kw)
    return Metadatos(**base)


def dec(**kw) -> Decision:
    base = dict(
        accion="decidir",
        resultado="REVOCAR",
        sustitutiva="AMPARAR",
        eje="x",
        derechos=[DisposicionDerecho(derecho="mínimo vital"), DisposicionDerecho(derecho="vida digna")],
        ordenes=[Orden(destinatario="el BANCO EJEMPLO S.A.", conducta="levante la restricción.")],
    )
    base.update(kw)
    return Decision(**base)


def test_juzgado_formas_y_falta():
    m = md()
    assert f.juzgado(m, "cuerpo") == "Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín"
    assert f.juzgado(m, "cuerpo_numero").startswith("Juzgado Dieciocho (18) Penal")
    assert f.juzgado(m, "encabezado").startswith("JUZGADO 18 PENAL")
    assert f.juzgado(md(juzgado_a_quo_numero=None), "cuerpo") == "⟦FALTA: juzgado a quo⟧"
    assert "Funciones de Conocimiento" in f.juzgado(md(juzgado_a_quo_funcion="conocimiento", juzgado_a_quo_plural=True), "cuerpo")


def test_competencia():
    assert f.COMPETENCIA_1.startswith("Este despacho es competente para conocer y resolver")
    assert f.competencia_2(md()) == (
        "Este Despacho es competente para resolver la impugnación presentada contra la sentencia de tutela "
        "proferida el 6 de octubre de 2026 por el Juzgado Dieciocho Penal Municipal con Función de Control de "
        "Garantías de Medellín, de conformidad con el artículo 32 del Decreto 2591 de 1991."
    )


def test_textos_fijos():
    assert f.PROCEDIBILIDAD_P1.startswith("La acción de tutela, consagrada en el artículo 86")
    assert f.PROCEDIBILIDAD_P1.endswith("la inmediatez y la subsidiariedad.")
    assert f.PROCEDIBILIDAD_P2.startswith("En relación con la legitimación en la causa por activa")
    assert f.PROCEDIBILIDAD_P2.endswith("artículo 42 del Decreto 2591 de 1991.")
    assert f.TRANSICION.startswith("Definido el marco jurídico aplicable")
    assert f.MERITO_ANTES + "JUZGADO" + f.MERITO_DESPUES == (
        "En mérito de lo expuesto, el JUZGADO, administrando justicia en nombre de la República y por autoridad de la Ley,"
    )


def test_asunto_singular_plural_y_faltas():
    assert f.asunto(md()) == (
        "Procede el Despacho a resolver la impugnación presentada por Ana Ejemplo contra el fallo de tutela emitido el "
        "seis (06) de octubre de dos mil veintiséis (2026) por el Juzgado Dieciocho Penal Municipal con Función de "
        "Control de Garantías de Medellín, por medio del cual se declaró improcedente el amparo solicitado."
    )
    m = md(impugnantes=["el Banco A", "la Clínica B", "Pedro C"])
    t = f.asunto(m)
    assert "las impugnaciones presentadas por el Banco A, la Clínica B y Pedro C contra" in t
    vacio = f.asunto(md(impugnante=None, resultado_a_quo=None))
    assert "⟦FALTA: impugnante⟧" in vacio and "⟦FALTA: resultado del fallo de primera instancia⟧" in vacio


def test_asunto_usa_la_forma_con_se_y_cae_al_campo_viejo():
    plural = f.asunto(
        md(
            resultado_a_quo="amparó los derechos fundamentales al mínimo vital y a la salud",
            resultado_a_quo_se="ampararon los derechos fundamentales al mínimo vital y a la salud.",
        )
    )
    assert "por medio del cual se ampararon los derechos fundamentales al mínimo vital y a la salud." in plural
    assert "se amparó" not in plural
    viejo = f.asunto(md(resultado_a_quo_se=None))
    assert "por medio del cual se declaró improcedente el amparo solicitado." in viejo
    assert "por medio del cual se declaró improcedente el amparo solicitado." in f.asunto(md(resultado_a_quo_se=""))


def test_etiqueta_parte():
    assert f.etiqueta_parte("Accionad", None, 1) == "Accionada"
    assert f.etiqueta_parte("Accionad", "m", 1) == "Accionado"
    assert f.etiqueta_parte("Vinculad", "m", 2) == "Vinculados"
    assert f.etiqueta_parte("Accionad", "f", 3) == "Accionadas"


def test_filas_encabezado():
    filas = f.filas_encabezado(md(), dec())
    assert [x[0] for x in filas] == ["radicado", "accionante", "accionada", "procedencia", "derechos", "decision"]
    d = {x[0]: x for x in filas}
    assert d["radicado"][1:] == ("Radicado", "050014088018 2026 00530 01")
    assert d["accionante"][2] == "ANA EJEMPLO"
    assert d["accionada"][1:] == ("Accionada", "BANCO EJEMPLO S.A.")
    assert d["procedencia"][2].startswith("JUZGADO 18 PENAL")
    assert d["derechos"][2] == "MÍNIMO VITAL, VIDA DIGNA"
    assert d["decision"][1:] == ("Decisión", "REVOCA")


def test_filas_con_vinculadas_y_sin_decision():
    m = md(vinculadas=["Entidad Uno", "Entidad Dos"], genero_vinculadas="m", accionadas=["A", "B"], genero_accionadas="f", derechos_invocados=[])
    filas = f.filas_encabezado(m, None)
    assert [x[0] for x in filas] == ["radicado", "accionante", "accionada", "vinculada", "procedencia"]
    d = {x[0]: x for x in filas}
    assert d["accionada"][1:] == ("Accionadas", "A, B")
    assert d["vinculada"][1:] == ("Vinculados", "ENTIDAD UNO, ENTIDAD DOS")


@pytest.mark.parametrize(
    "res,sust,esperado",
    [
        ("CONFIRMAR", None, "CONFIRMA"),
        ("REVOCAR", "AMPARAR", "REVOCA"),
        ("REVOCAR", "NEGAR", "REVOCA Y NIEGA"),
        ("MODIFICAR", "IMPROCEDENTE", "MODIFICA Y DECLARA IMPROCEDENTE"),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "REVOCA Y DECLARA HECHO SUPERADO"),
    ],
)
def test_encabezado_decision(res, sust, esperado):
    assert f.encabezado_decision(Decision(accion="decidir", resultado=res, sustitutiva=sust)) == esperado


def test_encabezado_decision_etiqueta_y_falta():
    assert f.encabezado_decision(Decision(accion="decidir", resultado="MODIFICAR", etiqueta_encabezado="CONFIRMA CON MODIFICACIONES")) == "CONFIRMA CON MODIFICACIONES"
    assert f.encabezado_decision(None) == "⟦FALTA: decisión⟧"


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("mínimo vital", "al mínimo vital"),
        ("vida digna", "a la vida digna"),
        ("debido proceso", "al debido proceso"),
        ("hábeas data", "al hábeas data"),
        ("petición", "a la petición"),
        ("libre expresión", "a la libre expresión"),
        ("al trabajo", "al trabajo"),
        ("a la salud", "a la salud"),
        ("a los alimentos", "a los alimentos"),
    ],
)
def test_con_articulo(entrada, esperado):
    assert f.con_articulo(entrada) == esperado


@pytest.mark.parametrize(
    "prep,texto,esperado",
    [
        ("a", "el BANCO X", "al BANCO X"),
        ("a", "El Banco", "al Banco"),
        ("a", "la NUEVA EPS", "a la NUEVA EPS"),
        ("de", "el Juzgado X", "del Juzgado X"),
        ("a", "BANCO X", "a BANCO X"),
        ("de", "los Bancos", "de los Bancos"),
    ],
)
def test_contraer(prep, texto, esperado):
    assert f.contraer(prep, texto) == esperado


def test_ordinal():
    assert [f.ordinal(i) for i in (1, 9, 10, 11, 20, 23)] == [
        "PRIMERO", "NOVENO", "DÉCIMO", "DÉCIMO PRIMERO", "VIGÉSIMO", "VIGÉSIMO TERCERO",
    ]


def por_clave(ns):
    return {n.clave: n for n in ns}


def test_resultado_y_amparar():
    ns = f.numerales(dec(), md())
    n = por_clave(ns)
    assert n["resultado"].texto == (
        "REVOCAR la sentencia proferida el 6 de octubre de 2026 por el Juzgado Dieciocho (18) Penal Municipal con "
        "Función de Control de Garantías de Medellín, que declaró improcedente el amparo solicitado, de conformidad "
        "con lo expuesto en la parte motiva de este proveído."
    )
    assert n["resultado"].negritas == ["REVOCAR"]
    assert n["sustitutiva"].texto == (
        "AMPARAR los derechos fundamentales al mínimo vital y a la vida digna de la señora ANA EJEMPLO, "
        "identificada con cédula de ciudadanía 1.111.111."
    )
    assert n["sustitutiva"].negritas == ["AMPARAR", "ANA EJEMPLO"]


def test_amparar_singular_y_tratamiento_masculino():
    d = dec(derechos=[DisposicionDerecho(derecho="petición")])
    m = md(accionante_tratamiento="el señor", accionante_identificacion=None)
    t = por_clave(f.numerales(d, m))["sustitutiva"].texto
    assert t == "AMPARAR el derecho fundamental a la petición del señor ANA EJEMPLO."


def test_amparar_sin_derechos_usa_invocados():
    t = por_clave(f.numerales(dec(derechos=[]), md()))["sustitutiva"].texto
    assert "al mínimo vital y a la vida digna" in t


def test_negar_plural_y_singular():
    d = dec(sustitutiva="NEGAR", ordenes=[], derechos=[DisposicionDerecho(derecho="mínimo vital", disposicion="NIEGA"), DisposicionDerecho(derecho="vida digna", disposicion="NIEGA")])
    assert por_clave(f.numerales(d, md()))["sustitutiva"].texto == (
        "NEGAR el amparo solicitado por la señora ANA EJEMPLO respecto de los derechos fundamentales al mínimo vital "
        "y a la vida digna, por las razones expuestas en este proveído."
    )
    d = dec(sustitutiva="NEGAR", ordenes=[], derechos=[DisposicionDerecho(derecho="petición", disposicion="NIEGA")])
    assert "respecto del derecho fundamental a la petición," in por_clave(f.numerales(d, md()))["sustitutiva"].texto


def test_improcedente_y_carencia():
    d = dec(sustitutiva="IMPROCEDENTE", ordenes=[])
    assert por_clave(f.numerales(d, md()))["sustitutiva"].texto == (
        "DECLARAR IMPROCEDENTE la acción de tutela promovida por la señora ANA EJEMPLO, por las razones expuestas en este proveído."
    )
    for s, etiqueta in (
        ("CARENCIA_HECHO_SUPERADO", "HECHO SUPERADO"),
        ("CARENCIA_DANO_CONSUMADO", "DAÑO CONSUMADO"),
        ("CARENCIA_SOBREVINIENTE", "SITUACIÓN SOBREVINIENTE"),
    ):
        t = por_clave(f.numerales(dec(sustitutiva=s, ordenes=[]), md()))["sustitutiva"].texto
        assert t == (
            f"DECLARAR LA CARENCIA ACTUAL DE OBJETO POR {etiqueta} en la acción de tutela promovida por la señora "
            "ANA EJEMPLO, por las razones expuestas en este proveído."
        )


def test_confirmar_sin_sustitutiva():
    ns = f.numerales(Decision(accion="decidir", resultado="CONFIRMAR", eje="x"), md())
    assert [n.clave for n in ns] == ["resultado", "notificar", "remitir"]


def test_orden_ordenar_basica_y_via():
    n = por_clave(f.numerales(dec(), md()))["orden:0"]
    assert n.texto == (
        "ORDENAR al BANCO EJEMPLO S.A. a través de su representante legal y/o quien haga sus veces, que, dentro de las "
        "cuarenta y ocho (48) horas hábiles siguientes a la notificación de esta providencia, levante la restricción."
    )
    assert n.negritas == ["ORDENAR", "BANCO EJEMPLO S.A."]
    sin = dec(ordenes=[Orden(destinatario="la NUEVA EPS", via_representante=False, conducta="autorice", plazo=Plazo(n=1, unidad="dias_habiles"))])
    assert por_clave(f.numerales(sin, md()))["orden:0"].texto == (
        "ORDENAR a la NUEVA EPS que, dentro de un (1) día hábil siguiente a la notificación de esta providencia, autorice."
    )


def test_orden_mismo_termino_y_literales():
    o = Orden(destinatario="el BANCO X", via_representante=False, conducta="emita una decisión. Deberá indicar", mismo_termino=True, literales=["La causa.", "La fecha."])
    n = por_clave(f.numerales(dec(ordenes=[o]), md()))["orden:0"]
    assert n.texto == "ORDENAR al BANCO X que, dentro del mismo término, emita una decisión. Deberá indicar:"
    assert n.literales == ["a. La causa.", "b. La fecha."]


def test_orden_con_condicion():
    o = Orden(destinatario="la FEDERACIÓN", via_representante=False, conducta="actualice", condicion="una vez recibida la información.", plazo=Plazo(n=10, unidad="dias_habiles"))
    assert por_clave(f.numerales(dec(ordenes=[o]), md()))["orden:0"].texto == (
        "ORDENAR a la FEDERACIÓN que, dentro de los diez (10) días hábiles siguientes a la notificación de esta "
        "providencia, actualice, una vez recibida la información."
    )


def test_orden_prevenir_y_advertir():
    o1 = Orden(verbo="PREVENIR", destinatario="el Banco X S.A.", conducta=", al decidir, valore los recursos.")
    o2 = Orden(verbo="PREVENIR", destinatario="la EPS", conducta="no reincida")
    o3 = Orden(verbo="ADVERTIR", destinatario="el accionante", conducta="deberá acudir ante el juzgado")
    n = por_clave(f.numerales(dec(ordenes=[o1, o2, o3]), md()))
    assert n["orden:0"].texto == "PREVENIR al Banco X S.A. para que, al decidir, valore los recursos."
    assert n["orden:0"].negritas == ["PREVENIR", "Banco X S.A."]
    assert n["orden:1"].texto == "PREVENIR a la EPS para que no reincida."
    assert n["orden:2"].texto == "ADVERTIR al accionante que deberá acudir ante el juzgado."


def test_prevenir_desvincular_compulsa():
    d = dec(
        prevenir=["el Banco X"],
        desvincular=["la FISCALÍA", "el MUNICIPIO Y"],
        compulsa=Compulsa(respecto_de="el Juzgado Veintidós"),
    )
    n = por_clave(f.numerales(d, md()))
    assert n["prevenir"].texto == (
        "PREVENIR al Banco X para que, en lo sucesivo, no vuelva a incurrir en las acciones u omisiones que dieron "
        "lugar a la presente acción de tutela."
    )
    assert "no vuelvan a incurrir" in f.numerales(dec(prevenir=["A", "B"]), md())[3].texto
    assert n["desvincular"].texto == (
        "DESVINCULAR de la presente acción de tutela a la FISCALÍA y al MUNICIPIO Y, por las razones expuestas en la "
        "parte motiva de esta providencia."
    )
    assert n["compulsa"].texto == (
        "COMPULSAR COPIAS ante la Comisión Seccional de Disciplina Judicial de Antioquia para que, de estimarlo "
        "pertinente, adelante las actuaciones a que haya lugar respecto del Juzgado Veintidós, conforme a lo indicado "
        "en el acápite de otras determinaciones de este proveído."
    )
    assert n["compulsa"].negritas == ["COMPULSAR COPIAS"]
    assert por_clave(f.numerales(dec(desvincular=["el MUNICIPIO Y"]), md()))["desvincular"].texto.startswith(
        "DESVINCULAR de la presente acción de tutela al MUNICIPIO Y,"
    )


def test_libres_notificar_remitir():
    d = dec(numerales_libres=["CONFIRMAR en lo demás la sentencia.", "Se advierte algo."])
    n = por_clave(f.numerales(d, md()))
    assert n["libre:0"].texto == "CONFIRMAR en lo demás la sentencia." and n["libre:0"].negritas == ["CONFIRMAR"]
    assert n["libre:1"].negritas == []
    assert n["notificar"].texto == (
        "NOTIFICAR esta providencia a las partes por el medio más expedito, de conformidad con lo dispuesto en el "
        "artículo 30 del Decreto 2591 de 1991."
    )
    assert n["remitir"].texto == "REMITIR el expediente a la Honorable Corte Constitucional para su eventual revisión."


def test_numerales_estandar_apagados():
    d = dec(numerales=NumeralesEstandar(notificar=False, remitir_corte=False))
    assert [n.clave for n in f.numerales(d, md())] == ["resultado", "sustitutiva", "orden:0"]


def test_orden_por_defecto_c3():
    d = dec(
        prevenir=["X"],
        desvincular=["Y"],
        compulsa=Compulsa(respecto_de="Z"),
        numerales_libres=["A uno", "B dos"],
        ordenes=[Orden(destinatario="W", conducta="c"), Orden(destinatario="V", conducta="c")],
    )
    assert [n.clave for n in f.numerales(d, md())] == [
        "resultado", "sustitutiva", "orden:0", "orden:1", "prevenir", "desvincular", "compulsa",
        "libre:0", "libre:1", "notificar", "remitir",
    ]


def test_orden_numerales_parcial_y_sin_repetir():
    d = dec(numerales_libres=["A uno"], orden_numerales=["libre:0", "orden:0", "libre:0", "compulsa"])
    assert [n.clave for n in f.numerales(d, md())] == [
        "libre:0", "orden:0", "resultado", "sustitutiva", "notificar", "remitir",
    ]


def test_cierre_otras_determinaciones():
    c = Compulsa(respecto_de="el Juzgado Veintidós")
    assert f.cierre_otras_determinaciones(c) == (
        "Por lo anterior, en cumplimiento del deber legal que le asiste a este funcionario, se dispondrá a compulsar "
        "copias de lo actuado ante la Comisión Seccional de Disciplina Judicial de Antioquia para que, dentro del "
        "marco de sus competencias, evalúe las situaciones descritas respecto del Juzgado Veintidós."
    )


def test_prevenir_y_desvincular_repiten_preposicion():
    ns = por_clave(f.numerales(dec(prevenir=["el BANCO X", "la NUEVA EPS"], desvincular=["FENALCO", "el MUNICIPIO DE MEDELLÍN"]), md()))
    assert ns["prevenir"].texto.startswith("PREVENIR al BANCO X y a la NUEVA EPS para que")
    assert "a FENALCO y al MUNICIPIO DE MEDELLÍN, por las" in ns["desvincular"].texto


def test_orden_conducta_con_dos_puntos_finales():
    o = Orden(destinatario="el BANCO X", conducta="emita una decisión. La decisión deberá indicar:", literales=["La causa", "Los recursos."])
    assert f._orden(0, o).texto.endswith("deberá indicar:")
    assert not f._orden(0, o).texto.endswith("::")


def test_amparar_sin_punto_doble():
    ns = por_clave(f.numerales(dec(), md(accionante="Une S.A.", accionante_tratamiento="la sociedad", accionante_identificacion=None)))
    assert ns["sustitutiva"].texto.endswith("UNE S.A.") or ns["sustitutiva"].texto.endswith("S.A.")
    assert not ns["sustitutiva"].texto.endswith("..")
    ns = por_clave(f.numerales(dec(), md(accionante_identificacion="identificada con C.C. 1.000.000.001.")))
    assert not ns["sustitutiva"].texto.endswith("..")


def test_con_articulo_con_articulo_previo():
    assert f.con_articulo("el debido proceso") == "al debido proceso"
    assert f.con_articulo("la vida digna") == "a la vida digna"
    assert f.con_articulo("los derechos") == "a los derechos"


def test_competencia_2_plural():
    assert "la impugnación presentada" in f.competencia_2(md())
    assert "las impugnaciones presentadas" in f.competencia_2(md(impugnantes=["a", "b"]))


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("identificada con C.C. 1000000001", "identificada con C.C. 1.000.000.001"),
        ("identificado con CC 12345678", "identificado con CC 12.345.678"),
        ("con cédula de ciudadanía No. 1000000001", "con cédula de ciudadanía No. 1.000.000.001"),
        ("con cédula de ciudadanía número 12345678", "con cédula de ciudadanía número 12.345.678"),
        ("C.C. 1.000.000.001", "C.C. 1.000.000.001"),
        ("NIT 900123456", "NIT 900123456"),
        ("C.C. No. 1000000001", "C.C. No. 1.000.000.001"),
        ("C.C. N° 1000000001", "C.C. N° 1.000.000.001"),
        ("CC. 1000000001", "CC. 1.000.000.001"),
        ("cédula de ciudadanía Nro. 1000000001", "cédula de ciudadanía Nro. 1.000.000.001"),
        ("cédula de ciudadanía n.° 1000000001", "cédula de ciudadanía n.° 1.000.000.001"),
        ("identificado con cédula 1000000001", "identificado con cédula 1.000.000.001"),
        ("C.C.1000000001", "C.C.1.000.000.001"),
        ("CC 900123456-1", "CC 900123456-1"),
        ("C.C. N.º 1000000001", "C.C. N.º 1.000.000.001"),
        ("cédula de ciudadanía N.º 1000000001", "cédula de ciudadanía N.º 1.000.000.001"),
        ("CC: 1000000001", "CC: 1.000.000.001"),
        ("cédula de ciudadanía número: 1000000001", "cédula de ciudadanía número: 1.000.000.001"),
        ("NIT: 900123456", "NIT: 900123456"),
        ("la sociedad con NIT 900123456 y C.C. 1000000001", "la sociedad con NIT 900123456 y C.C. 1.000.000.001"),
    ],
)
def test_formatear_cedulas(entrada, esperado):
    assert f.formatear_cedulas(entrada) == esperado


def test_asunto_formatea_cedula_de_impugnantes():
    texto = f.asunto(md(impugnantes=["la ciudadana Ana Ejemplo identificada con C.C. 1000000001", "Banco Ejemplo S.A. NIT 900123456"]))
    assert "C.C. 1.000.000.001" in texto
    assert "NIT 900123456" in texto


def test_persona_formatea_identificacion():
    _, _, ident = f._persona(md(accionante_identificacion="identificada con cédula de ciudadanía No. 1000000001"))
    assert ident == ", identificada con cédula de ciudadanía No. 1.000.000.001"


def test_formatear_cedulas_idempotente():
    t = "C.C. No. 1000000001, cédula 12345678 y CC 900123456-1"
    assert f.formatear_cedulas(f.formatear_cedulas(t)) == f.formatear_cedulas(t)
