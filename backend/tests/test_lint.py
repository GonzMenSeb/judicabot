from __future__ import annotations

import pytest

from tutela2 import lint
from tutela2.models import (
    AperturaLLM,
    BloqueLLM,
    CasoConcretoLLM,
    CitaPropuesta,
    CitaVerificada,
    ConsideracionesLLM,
    Decision,
    DisposicionDerecho,
    DisposicionReparo,
    Doc,
    Evento,
    Fechas,
    Ingesta,
    Metadatos,
    MetadatosLLM,
    Orden,
    Pagina,
    ParrafoLLM,
    Reparo,
)


def _prefijados(msgs: list[str]) -> bool:
    return all(m.startswith(("BLOQUEA: ", "ALERTA: ")) for m in msgs)


def _bloquea(msgs: list[str]) -> list[str]:
    assert _prefijados(msgs)
    return [m for m in msgs if m.startswith("BLOQUEA: ")]


def _alerta(msgs: list[str]) -> list[str]:
    assert _prefijados(msgs)
    return [m for m in msgs if m.startswith("ALERTA: ")]


def _doc(doc_id: str, texto: str, rol: str = "escrito_tutela") -> Doc:
    return Doc(
        doc_id=doc_id, ruta=f"{doc_id}.pdf", nombre=f"{doc_id}.pdf", instancia="2a", rol=rol, sha256=doc_id,
        paginas=[Pagina(n=1, texto=texto)],
    )


ESCRITO = (
    "El señor accionante manifiesta que desde el mes de enero la entidad no le ha entregado el medicamento "
    "formulado por su médico tratante, pese a las múltiples solicitudes verbales y escritas que radicó "
    "oportunamente ante la oficina de atención al usuario."
)
IMPUGNACION = (
    "La entidad accionada impugna el fallo porque, a su juicio, el juez de primera instancia desconoció el "
    "principio de subsidiariedad y ordenó un tratamiento que no se encuentra incluido en el plan de beneficios."
)
CONTROL = (
    "Radicado 05001 31 09 003 2023 00123 00. Accionante con C.C. 1.234.567.890. Entidad con NIT 890.900.123-4. "
    "El fallo se profirió el 21 de septiembre de 2026 y se notificó el 05/10/2026. La impugnación se presentó "
    "el veintiuno (21) de octubre de dos mil veintiséis (2026). Correo recibido el 3 oct 2026. "
    "Valor del servicio: $2.300.000,00. Decreto 2591 de 1991, artículo 86. Medellín, septiembre 17 de 2026. "
    "Desde el 1º de noviembre de 2026 rige la medida."
)


@pytest.fixture
def ing() -> Ingesta:
    return Ingesta(
        documentos=[_doc("2a-001", ESCRITO), _doc("2a-002", IMPUGNACION, "impugnacion"), _doc("2a-003", CONTROL, "correo")],
        metadatos=Metadatos(fechas=Fechas(fallo_a_quo="2026-11-02", reparto_2a="2026-11-20")),
    )


def _apertura(cronologia=(), reparos=()) -> AperturaLLM:
    return AperturaLLM(
        metadatos=MetadatosLLM(), cronologia=list(cronologia), antecedentes_hechos="", contestaciones=[],
        sentencia_impugnada="", impugnacion="", reparos=list(reparos),
    )


def _ev(doc_id: str, cita: str) -> Evento:
    return Evento(hecho="h", doc_id=doc_id, cita_literal=cita)


def test_contar_palabras():
    assert lint.contar_palabras("") == 0
    assert lint.contar_palabras("uno  dos\ntres\t[[CITA:c1]]") == 4


def test_lint_prosa_limpia():
    assert lint.lint_prosa("Primer párrafo con prosa.\n\nSegundo párrafo: sigue igual. El actor dijo: no.", "antecedentes") == []


def test_lint_prosa_vinetas_son_alerta_salvo_que_se_permitan():
    texto = "Introducción.\n- uno\n• dos\n* tres\n1. cuatro\n2) cinco\nCierre."
    msgs = lint.lint_prosa(texto, "caso_concreto")
    assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ") and "caso_concreto" in msgs[0]
    assert lint.lint_prosa(texto, "caso_concreto", permitir_listas=True) == []


@pytest.mark.parametrize(
    "texto",
    [
        "## Consideraciones\nTexto.",
        "Texto con **negrita** en medio.",
        "Argumento del despacho: el juez erró.",
        "Hechos: el actor reclamó.",
        "Nota: revisar con el juez.",
        "TODO: completar",
        "Texto.\n\nPROBLEMA JURÍDICO: determinar si procede.",
    ],
)
def test_lint_prosa_formato_prohibido_bloquea(texto):
    msgs = lint.lint_prosa(texto, "impugnacion")
    assert len(_bloquea(msgs)) == 1 and "impugnacion" in msgs[0]


def test_anclas_literales_ok_y_fallos(ing):
    ok = _ev("2a-001", "desde el mes de enero la entidad no le ha entregado el medicamento formulado")
    con_ruido = _ev("2a-001", "DESDE EL MES DE ENERO, la entidad no le ha entregado el medicamento formulado.")
    inventada = _ev("2a-001", "el actor fue agredido físicamente por funcionarios de la entidad en la sede principal")
    otro_doc = _ev("2a-002", "desde el mes de enero la entidad no le ha entregado el medicamento formulado")
    sin_doc = _ev("9z-999", "desde el mes de enero la entidad no le ha entregado el medicamento")
    vacia = _ev("2a-001", "")
    msgs = lint.anclas_literales(_apertura([ok, con_ruido, inventada, otro_doc, sin_doc, vacia]), ing)
    assert len(_bloquea(msgs)) == len(msgs) == 4
    assert "evento 3" in msgs[0] and "2a-001" in msgs[0]
    assert "evento 4" in msgs[1] and "2a-002" in msgs[1]
    assert "evento 5" in msgs[2] and "no existe" in msgs[2]
    assert "evento 6" in msgs[3] and "vacía" in msgs[3]


def test_anclas_literales_reparos_y_citas_cortas(ing):
    buena = Reparo(id="R1", sintesis="s", doc_id="2a-002", cita_literal="desconoció el principio de subsidiariedad")
    mala = Reparo(id="R2", sintesis="s", doc_id="2a-002", cita_literal="desconoció el principio de legalidad penal")
    corta_ok = Reparo(id="R3", sintesis="s", doc_id="2a-002", cita_literal="plan de beneficios")
    corta_mala = Reparo(id="R4", sintesis="s", doc_id="2a-002", cita_literal="plan de salud")
    msgs = lint.anclas_literales(_apertura(reparos=[buena, mala, corta_ok, corta_mala]), ing)
    assert len(msgs) == 2 and "Reparo R2" in msgs[0] and "Reparo R4" in msgs[1]


def test_anclas_literales_parentesis_sin_cerrar_en_el_documento():
    texto = (
        "Solicito la electromiografía (UNO O MÁS MÚSCULOS y la consulta de control. CUARTO: Puedo manifestar "
        "bajo la gravedad del juramento que recientemente no he formulado acción de tutela alguna. "
        "Son competentes: a) los jueces del lugar."
    )
    doc = Ingesta(documentos=[_doc("1a-009", texto, "impugnacion")], metadatos=Metadatos(fechas=Fechas()))
    real = Reparo(
        id="R1", sintesis="s", doc_id="1a-009",
        cita_literal="Puedo manifestar bajo la gravedad del juramento que recientemente no he formulado acción de tutela alguna",
    )
    falsa = Reparo(id="R2", sintesis="s", doc_id="1a-009", cita_literal="el juez desconoció el precedente vertical aplicable")
    msgs = lint.anclas_literales(_apertura(reparos=[real, falsa]), doc)
    assert len(msgs) == 1 and "Reparo R2" in msgs[0]


def test_anclas_literales_umbral_de_cobertura(ing):
    casi = (
        "desde el mes de enero la entidad no le ha entregado el medicamento formulado por su médico tratante "
        "pese a las múltiples solicitudes verbales"
    )
    assert lint.anclas_literales(_apertura([_ev("2a-001", casi)]), ing) == []
    con_relleno = casi + " x y"
    assert len(lint.anclas_literales(_apertura([_ev("2a-001", con_relleno)]), ing)) == 1
    mitad = "desde el mes de enero la entidad no le ha entregado el medicamento " + " ".join(f"inventada{i}" for i in range(9))
    assert len(lint.anclas_literales(_apertura([_ev("2a-001", mitad)]), ing)) == 1


@pytest.mark.parametrize(
    "texto",
    [
        "El proceso 05001310900320230012300 se tramitó en Medellín.",
        "Radicado 05001-31-09-003-2023-00123-00 del caso.",
        "Con cédula 1234567890 y NIT 890900123 respectivamente.",
        "Con C.C. 1.234.567.890 y NIT 890.900.123-4.",
        "Por un valor de $2.300.000.",
        "Se profirió el 21/09/2026 y se notificó el 2026-10-05.",
        "La impugnación se radicó el 21 de octubre de 2026 y el 3 de octubre del 2026.",
        "El Decreto 2591 de 1991, el artículo 86 y la suma de 10.000 pesos no son identificadores.",
        "Los metadatos aceptan el 02/11/2026 y el 20 de noviembre de 2026.",
        "Se firmó el 17 de septiembre de 2026 y rige desde el 01/11/2026 y el 2026/11/01.",
        "Sin datos.",
    ],
)
def test_datos_ajenos_presentes_en_documentos(ing, texto):
    assert lint.datos_ajenos(texto, ing) == []


@pytest.mark.parametrize(
    "texto,fragmento",
    [
        ("Radicado 05001310900320230099900.", "radicado 05001310900320230099900"),
        ("Con cédula 9876543 del accionante.", "9876543"),
        ("NIT 800.111.222-3 de la entidad.", "800111222"),
        ("Por un valor de $9.900.000.", "9900000"),
        ("Se profirió el 15/03/2026.", "15/03/2026"),
        ("Se profirió el 15 de marzo de 2026.", "15/03/2026"),
        ("Se profirió el 2026-12-25.", "25/12/2026"),
    ],
)
def test_datos_ajenos_inexistentes_bloquean(ing, texto, fragmento):
    msgs = lint.datos_ajenos(texto, ing)
    assert len(msgs) == 1 and msgs[0].startswith("BLOQUEA: ")
    assert fragmento.lower() in msgs[0].lower()


@pytest.mark.parametrize(
    "texto",
    [
        "Se notificó el veintiuno de octubre de dos mil veintiséis.",
        "El fallo se profirió el veintiuno de septiembre de dos mil veintiséis y se pagaron dos millones trescientos mil pesos.",
    ],
)
def test_fechas_y_montos_solo_en_letras_presentes_en_documentos(ing, texto):
    assert lint.datos_ajenos(texto, ing) == []


@pytest.mark.parametrize(
    "texto,fragmento",
    [
        ("Ocurrió el veintidós de marzo de dos mil diecinueve.", "22/03/2019"),
        ("Debe cuarenta y siete millones de pesos.", "47000000"),
        ("Debe cuarenta y siete millones de pesos el treinta de febrero de dos mil veinticinco.", "30/02/2025"),
    ],
)
def test_fechas_y_montos_solo_en_letras_inventados_bloquean(ing, texto, fragmento):
    msgs = lint.datos_ajenos(texto, ing)
    assert any(fragmento in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_datos_ajenos_fecha_imposible(ing):
    msgs = lint.datos_ajenos("Se notificó el 31/09/2026.", ing)
    assert len(msgs) == 1 and "no es una fecha válida" in msgs[0]


def test_datos_ajenos_un_mensaje_por_dato_distinto(ing):
    msgs = lint.datos_ajenos("CC 9876543 y 9876543, y también 1112223334 el 15/03/2026 y el 15/03/2026.", ing)
    assert len(msgs) == 3 and len(_bloquea(msgs)) == 3


def test_datos_ajenos_ignora_documentos_ajenos():
    ajeno = _doc("1a-009", "Cédula 7654321 y radicado 05001310900320200000100 de otro caso.")
    ing = Ingesta(documentos=[_doc("2a-001", ESCRITO), ajeno], docs_ajenos=["1a-009"])
    msgs = lint.datos_ajenos("Cédula 7654321.", ing)
    assert len(msgs) == 1
    ing_sin_marca = Ingesta(documentos=[_doc("2a-001", ESCRITO), ajeno])
    assert lint.datos_ajenos("Cédula 7654321.", ing_sin_marca) == []


def _meta() -> Metadatos:
    return Metadatos(
        cui_1a="05001310900320230012300",
        cui_2a="05001310900320230012301",
        accionante="Juan Carlos Pérez Gómez",
        accionadas=["Nueva EPS S.A.", "Colpensiones"],
        vinculadas=["Clínica del Norte"],
    )


def _cons(procedibilidad: str = "", textos: tuple[str, ...] = (), titulos: tuple[str, ...] = ()) -> ConsideracionesLLM:
    bloques = [
        BloqueLLM(titulo=titulos[i] if i < len(titulos) else "Subsidiariedad", texto=t) for i, t in enumerate(textos)
    ]
    return ConsideracionesLLM(procedibilidad=procedibilidad, bloques=bloques, citas=[])


def test_guardia_p3_limpia():
    cons = _cons("La acción de tutela es subsidiaria y residual.", ("La Corte ha precisado que la legitimación es flexible.",))
    assert lint.guardia_p3(cons, _meta()) == []


@pytest.mark.parametrize(
    "procedibilidad,textos,titulos,fragmento",
    [
        ("Tal como lo afirmó JUAN CARLOS PEREZ GOMEZ en su escrito.", (), (), "accionante"),
        ("", ("El señor Juan Carlos Pérez Gómez no agotó la vía.",), (), "accionante"),
        ("", ("Aplica a la Nueva EPS S.A. en este asunto.",), (), "una accionada"),
        ("", ("Texto.",), ("La Clínica del Norte y la tutela",), "una vinculada"),
        ("Radicado 05001 31 09 003 2023 00123 01.", (), (), "radicado"),
        ("Radicado 05001310900320230012300.", (), (), "radicado"),
    ],
)
def test_guardia_p3_datos_del_caso_bloquean(procedibilidad, textos, titulos, fragmento):
    msgs = lint.guardia_p3(_cons(procedibilidad, textos, titulos), _meta())
    assert len(_bloquea(msgs)) == len(msgs) == 1 and fragmento in msgs[0]


def test_guardia_p3_nombre_dentro_de_parentesis_bloquea():
    cons = _cons("La tutela es subsidiaria (como dijo Juan Carlos Pérez Gómez en su escrito).")
    msgs = lint.guardia_p3(cons, _meta())
    assert len(_bloquea(msgs)) == len(msgs) == 1 and "accionante" in msgs[0]


def test_guardia_p3_parentesis_sin_cerrar_no_oculta_nombre():
    cons = _cons("Regla (sin cerrar. Juan Carlos Pérez Gómez actuó. Lista: a) uno.")
    assert len(_bloquea(lint.guardia_p3(cons, _meta()))) == 1


@pytest.mark.parametrize(
    "accionada,prosa",
    [
        ("Nueva EPS S.A.", "La Nueva EPS no entregó el insumo."),
        ("COMUNICACION MOVIL S.A. E.S.P ANDA", "Comunicación Móvil Anda respondió el requerimiento."),
        ("Juan C. Pérez", "El señor Juan Pérez compareció."),
    ],
)
def test_guardia_p3_ignora_sufijos_societarios_e_iniciales(accionada, prosa):
    meta = Metadatos(accionadas=[accionada])
    msgs = lint.guardia_p3(_cons(prosa), meta)
    assert len(msgs) == 1 and msgs[0].startswith("BLOQUEA: ")


def test_guardia_p3_nombres_de_una_palabra_o_parciales_no_cuentan():
    cons = _cons("Colpensiones y Juan y Pérez y la Clínica del Nortecito.")
    assert lint.guardia_p3(cons, _meta()) == []


def _cv(id_: str, sentencia: str, estado: str = "ok", tipo="T", numero=200, anio=2022) -> CitaVerificada:
    return CitaVerificada(
        id=id_, sentencia_original=sentencia, sentencia_norm=f"{tipo}-{numero:03d}/{anio % 100:02d}", tipo=tipo,
        numero=numero, anio=anio, texto_citado=f"fragmento literal propio de la cita {id_}", estado=estado,
    )


CITAS = [
    _cv("c1", "T-200 de 2022"),
    _cv("c2", "SU-082/95", "alerta", "SU", 82, 1995),
    _cv("c3", "T-892 de 2011", "rechazada", "T", 892, 2011),
]


def _caso(*parrafos: str, problema: str = "Corresponde al Despacho determinar si procede.", conclusion: str = "Se revocará.") -> CasoConcretoLLM:
    return CasoConcretoLLM(
        problema_juridico=problema, parrafos=[ParrafoLLM(reparo_ids=["R1"], texto=p) for p in parrafos], conclusion=conclusion
    )


def test_subconjunto_citas_validas():
    caso = _caso(
        "Como se vio [[CITA:c1]], y también [[CITA: c2 ]] aplica.",
        "Véase la Sentencia T-200 de 2022 y la SU-082/95, así como la T-200 y [[IMAGEN 2a-001 3 pie]].",
    )
    assert lint.subconjunto_citas(caso, CITAS) == []


def test_subconjunto_citas_marcadores_invalidos():
    caso = _caso("Uno [[CITA:c3]] y dos [[CITA:c9]] y de nuevo [[CITA:c9]].")
    msgs = lint.subconjunto_citas(caso, CITAS)
    assert len(_bloquea(msgs)) == len(msgs) == 2
    assert "c3" in msgs[0] and "rechazada" in msgs[0]
    assert "c9" in msgs[1]


@pytest.mark.parametrize("marcador", ["[[cita:c1]]", "[[ CITA:c1 ]]", "[[CITA c1]]"])
def test_subconjunto_citas_marcador_mal_formado(marcador):
    msgs = lint.subconjunto_citas(_caso(f"Texto {marcador} más texto."), CITAS)
    assert len(_bloquea(msgs)) == 1 and "mal formado" in msgs[0]


MARCADORES_SIN_CERRAR = ["[[CITA:c1]", "[CITA:c1]", "[[CITA:c1", "[CITA:c1", "[CITA:c1]]", "[[CITA", "[ cita : c1 ]"]


@pytest.mark.parametrize("marcador", MARCADORES_SIN_CERRAR)
def test_subconjunto_citas_marcador_sin_cerrar_bloquea(marcador):
    msgs = lint.subconjunto_citas(_caso(f"Texto {marcador} más texto."), CITAS)
    assert len(_bloquea(msgs)) == len(msgs) == 1
    assert "mal formado" in msgs[0] and marcador in msgs[0] and "use exactamente [[CITA:id]]" in msgs[0]


@pytest.mark.parametrize("campo", ["problema", "conclusion"])
def test_subconjunto_citas_marcador_sin_cerrar_en_problema_y_conclusion_bloquea(campo):
    caso = _caso("Párrafo [[CITA:c1]].", **{("problema" if campo == "problema" else "conclusion"): "Texto [CITA:c1 roto."})
    msgs = lint.subconjunto_citas(caso, CITAS)
    assert len(_bloquea(msgs)) == 1 and "mal formado" in msgs[0]


def test_subconjunto_citas_marcador_sin_cerrar_seguido_de_uno_valido_se_informa_una_vez():
    msgs = lint.subconjunto_citas(_caso("Uno [[CITA:c1 y dos [[CITA:c2]]."), CITAS)
    assert len(_bloquea(msgs)) == len(msgs) == 1 and "mal formado" in msgs[0]


def test_subconjunto_citas_corchetes_de_prosa_con_la_palabra_cita_no_son_marcadores():
    assert lint.subconjunto_citas(_caso("La [cita] y el [Cita omitida] son texto; véase [[CITA:c1]]."), CITAS) == []


def test_subconjunto_citas_menciones_sueltas():
    caso = _caso(
        "Según la Sentencia T-892 de 2011 el asunto es claro.",
        "También la C-321/22 y la T-300 son relevantes; no así el decreto C-19.",
        conclusion="Se aplica la SU034-18.",
    )
    msgs = lint.subconjunto_citas(caso, CITAS)
    assert len(_bloquea(msgs)) == len(msgs) == 4
    texto = " ".join(msgs)
    for esperado in ("T-892/11", "C-321/22", "SU-034/18", "T-300"):
        assert esperado in texto


def test_subconjunto_citas_sentencia_rechazada_no_cuenta_como_verificada():
    msgs = lint.subconjunto_citas(_caso("Véase la T-892/11."), CITAS)
    assert len(msgs) == 1 and "T-892/11" in msgs[0]


def _cons_con_citas(procedibilidad: str, textos: tuple[str, ...], ids: tuple[str, ...]) -> ConsideracionesLLM:
    c = _cons(procedibilidad, textos)
    c.citas = [CitaPropuesta(id=i, sentencia="T-200 de 2022", texto_citado="x") for i in ids]
    return c


def test_marcadores_consideraciones_correctas():
    cons = _cons_con_citas("Marco general [[CITA:c1]].", ("Bloque uno [[CITA:c2]] y [[CITA:c1]].",), ("c1", "c2"))
    assert lint.marcadores_consideraciones(cons) == []


@pytest.mark.parametrize("marcador", MARCADORES_SIN_CERRAR)
@pytest.mark.parametrize("donde", ["procedibilidad", "bloque"])
def test_marcadores_consideraciones_sin_cerrar_bloquean(marcador, donde):
    roto = f"Marco {marcador} y [[CITA:c1]]."
    cons = (
        _cons_con_citas(roto, ("Bloque [[CITA:c2]].",), ("c1", "c2"))
        if donde == "procedibilidad"
        else _cons_con_citas("Marco [[CITA:c1]].", (f"Bloque {marcador} y [[CITA:c2]].",), ("c1", "c2"))
    )
    msgs = lint.marcadores_consideraciones(cons)
    assert len(_bloquea(msgs)) == len(msgs) == 1
    assert "mal formado" in msgs[0] and "use exactamente [[CITA:id]]" in msgs[0]


def test_marcadores_consideraciones_defectos():
    cons = _cons_con_citas(
        "Marco [[CITA:c1]] y [[CITA:c7]].",
        ("Lo dijo la Sentencia T-200 de 2022 y la T-300 sin marcador.", "Otra vez [[cita:c1]]."),
        ("c1", "c2", "c2"),
    )
    msgs = lint.marcadores_consideraciones(cons)
    assert len(_bloquea(msgs)) == len(msgs)
    texto = "\n".join(msgs)
    assert "mal formado" in texto
    assert "«c2» está repetido" in texto
    assert "[[CITA:c7]] no corresponde" in texto
    assert "La cita c2" in texto and "no se usa" in texto
    assert "T-200/22" in texto and "T-300" in texto


def _cvs(*estados: str) -> list[CitaVerificada]:
    return [_cv(f"c{i}", "T-200 de 2022", e) for i, e in enumerate(estados, 1)]


def test_minimo_citas_ok_suficientes_no_dice_nada():
    assert lint.minimo_citas_ok(_cvs("ok", "ok", "alerta", "rechazada"), 2, 25) == []


@pytest.mark.parametrize("estados", [(), ("rechazada", "rechazada"), ("ok", "alerta", "rechazada")])
def test_minimo_citas_ok_insuficientes_bloquea_con_la_regla(estados):
    msgs = lint.minimo_citas_ok(_cvs(*estados), 2, 25)
    assert len(msgs) == 1 and msgs[0].startswith("BLOQUEA: ")
    texto = msgs[0]
    assert "al menos 2" in texto and "25 palabras" in texto
    assert "ratio decidendi" in texto and "salvamento" in texto
    assert "Constitución" in texto and "no acorte" in texto
    assert f"propuestas: {len(estados)}" in texto


def _sin_acceso(*estados: str) -> list[CitaVerificada]:
    return [
        cv.model_copy(update={"relatoria": "inaccesible"}) if cv.estado == "alerta" else cv for cv in _cvs(*estados)
    ]


def test_minimo_citas_ok_con_la_relatoria_inaccesible_avisa_sin_bloquear():
    (msg,) = lint.minimo_citas_ok(_sin_acceso("alerta", "alerta"), 2, 25)
    assert msg.startswith("ALERTA: ") and "BLOQUEA" not in msg
    assert "tienen 0 citas verificadas" in msg and "no respondió desde el servidor" in msg
    (msg,) = lint.minimo_citas_ok(_sin_acceso("ok", "alerta"), 2, 25)
    assert msg.startswith("ALERTA: ") and "tienen 1 cita verificada " in msg


def test_minimo_citas_ok_sigue_bloqueando_si_ni_verificadas_las_citas_sin_acceso_bastarian():
    (msg,) = lint.minimo_citas_ok(_sin_acceso("alerta"), 2, 25)
    assert msg.startswith("BLOQUEA: ")
    (msg,) = lint.minimo_citas_ok(_sin_acceso("rechazada", "rechazada", "alerta"), 2, 25)
    assert msg.startswith("BLOQUEA: ")


def test_minimo_citas_ok_una_alerta_por_otra_causa_no_se_confunde_con_falta_de_acceso():
    (msg,) = lint.minimo_citas_ok(_cvs("alerta", "alerta"), 2, 25)
    assert msg.startswith("BLOQUEA: ")
    publicada = [cv.model_copy(update={"relatoria": "no_publicada"}) for cv in _cvs("alerta", "alerta")]
    (msg,) = lint.minimo_citas_ok(publicada, 2, 25)
    assert msg.startswith("BLOQUEA: ")


def test_minimo_citas_ok_cuenta_solo_las_ok():
    msgs = lint.minimo_citas_ok(_cvs("ok", "alerta", "alerta", "rechazada"), 2, 14)
    assert "tienen 1 cita verificada;" in msgs[0]
    assert "rechazadas: 1" in msgs[0] and "para revisar: 2" in msgs[0]
    assert "14 palabras" in msgs[0]


def _cv_con_texto(id_: str, texto: str, estado: str = "ok") -> CitaVerificada:
    return _cv(id_, "T-200 de 2022", estado).model_copy(update={"texto_citado": texto})


REGLA_A = "La subsidiariedad exige agotar los mecanismos ordinarios de defensa antes de acudir al juez constitucional."
REGLA_B = "El perjuicio irremediable debe ser grave e inminente y requiere medidas urgentes e impostergables."


def test_minimo_citas_ok_no_cuenta_la_misma_cita_repetida():
    repetidas = [_cv_con_texto("c1", REGLA_A), _cv_con_texto("c2", REGLA_A.upper().replace(".", ","))]
    (texto,) = lint.minimo_citas_ok(repetidas, 2, 25)
    assert texto.startswith("BLOQUEA: ") and "tienen 1 cita verificada distinta; se exigen al menos 2" in texto
    assert "repetidas o contenidas en otra cita verificada: c2," in texto
    assert lint.minimo_citas_ok(repetidas, 1, 25) == []


@pytest.mark.parametrize("orden", [(0, 1), (1, 0)])
def test_minimo_citas_ok_no_cuenta_la_cita_contenida_en_otra(orden):
    larga = f"{REGLA_A} {REGLA_B}"
    citas = [_cv_con_texto("c1", larga), _cv_con_texto("c2", REGLA_B.lower().rstrip("."))]
    (texto,) = lint.minimo_citas_ok([citas[i] for i in orden], 2, 25)
    assert "tienen 1 cita verificada distinta; se exigen al menos 2" in texto
    assert "repetidas o contenidas en otra cita verificada: c2," in texto


def test_minimo_citas_ok_cuenta_las_citas_distintas():
    distintas = [_cv_con_texto("c1", REGLA_A), _cv_con_texto("c2", REGLA_B)]
    assert lint.minimo_citas_ok(distintas, 2, 25) == []
    solapadas = [_cv_con_texto("c1", f"{REGLA_A} Esto no se repite."), _cv_con_texto("c2", f"{REGLA_B} Esto no se repite.")]
    assert lint.minimo_citas_ok(solapadas, 2, 25) == []


def test_minimo_citas_ok_la_contencion_es_por_palabras_completas():
    citas = [_cv_con_texto("c1", "La reacción previa del despacho fue suficiente."), _cv_con_texto("c2", "acción previa del despacho")]
    assert lint.minimo_citas_ok(citas, 2, 25) == []


def test_minimo_citas_ok_los_incisos_y_marcas_del_citante_no_hacen_distinta_una_cita():
    citas = [
        _cv_con_texto("c1", f"{REGLA_A} (subrayado fuera de texto)"),
        _cv_con_texto("c2", f"{REGLA_A} (Cfr. sentencia T-1 de 1990)"),
    ]
    (texto,) = lint.minimo_citas_ok(citas, 2, 25)
    assert "tienen 1 cita verificada distinta; se exigen al menos 2" in texto


def test_minimo_citas_ok_citas_repetidas_que_no_son_ok_no_suman_a_las_repetidas():
    citas = [_cv_con_texto("c1", REGLA_A), _cv_con_texto("c2", REGLA_A, "alerta"), _cv_con_texto("c3", REGLA_B, "rechazada")]
    (texto,) = lint.minimo_citas_ok(citas, 2, 25)
    assert "tienen 1 cita verificada; se exigen al menos 2" in texto and "repetidas o contenidas" not in texto


def test_minimo_citas_ok_cero_con_minimo_cero_alerta_sin_bloquear():
    msgs = lint.minimo_citas_ok(_cvs("alerta"), 0, 25)
    assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ") and "ninguna cita verificada" in msgs[0]
    assert lint.minimo_citas_ok(_cvs("ok"), 0, 25) == []


PASAJE_CERCANO = (
    "El perjuicio ha de ser grave, lo que equivale a la gran intensidad del daño o menoscabo material o moral en el "
    "haber jurídico de la persona."
)
MOTIVO_PASAJE = (
    f"El pasaje más cercano en la sentencia T-225/93 dice textualmente: «{PASAJE_CERCANO}». Si lo usa, cópielo sin "
    "ningún cambio y con al menos 25 palabras."
)
MOTIVO_REGLA = "Regla de las citas: cada cita es un pasaje literal de la ratio decidendi de la mayoría."


def _cv_con_motivos(id_: str, estado: str, motivos: list[str], pasaje: str | None = None, sentencia: str = "T-225 de 1993"):
    return _cv(id_, sentencia, estado, "T", 225, 1993).model_copy(update={"motivos": motivos, "pasaje_cercano": pasaje})


def _citas_con_motivos():
    return [
        _cv_con_motivos("c1", "ok", []),
        _cv_con_motivos(
            "c2", "alerta", ["Solo el 77% del texto citado aparece literalmente. Compárelo con la relatoría.", MOTIVO_PASAJE],
            PASAJE_CERCANO,
        ),
        _cv_con_motivos(
            "c3", "rechazada", ["Solo el 0% del texto citado aparece literalmente; el pasaje no se localizó.", MOTIVO_REGLA],
            sentencia="SU-961 de 1999",
        ),
    ]


def test_minimo_citas_ok_lista_cada_cita_que_no_cuenta_con_id_sentencia_y_motivos():
    (texto,) = lint.minimo_citas_ok(_citas_con_motivos(), 2, 25)
    assert texto.startswith("BLOQUEA: ") and "tienen 1 cita verificada; se exigen al menos 2" in texto
    assert "Cita c2" in texto and "T-225/93" in texto and "para revisar" in texto
    assert "Cita c3" in texto and "SU-961 de 1999" in texto and "rechazada" in texto
    assert "Cita c1" not in texto
    assert "Solo el 77%" in texto and "no se localizó" in texto


def test_minimo_citas_ok_incluye_el_pasaje_cercano_y_la_instruccion_de_copiarlo():
    (texto,) = lint.minimo_citas_ok(_citas_con_motivos(), 2, 25)
    assert f"dice textualmente: «{PASAJE_CERCANO}»" in texto
    assert "cópielo sin ningún cambio" in texto and "al menos 25 palabras" in texto
    assert texto.count(PASAJE_CERCANO) == 1


def test_minimo_citas_ok_no_repite_la_regla_ni_deja_puntuacion_doble():
    (texto,) = lint.minimo_citas_ok(_citas_con_motivos(), 2, 25)
    assert "Regla de las citas:" not in texto and texto.count("ratio decidendi") == 1
    assert ".;" not in texto and ".." not in texto and "; ;" not in texto


def test_minimo_citas_ok_acota_el_largo_de_cada_cita_pero_conserva_el_pasaje():
    largo = "Detalle muy extenso del verificador. " * 200
    citas = [
        _cv_con_motivos("c1", "alerta", [largo, MOTIVO_PASAJE], PASAJE_CERCANO),
        _cv_con_motivos("c2", "rechazada", [largo, MOTIVO_REGLA]),
    ]
    (texto,) = lint.minimo_citas_ok(citas, 2, 25)
    lineas = [ln for ln in texto.split("\n") if ln.startswith("- Cita ")]
    assert len(lineas) == 2 and all(len(ln) <= lint.MAX_CHARS_CITA_EN_MINIMO + 120 for ln in lineas)
    assert f"dice textualmente: «{PASAJE_CERCANO}»" in texto and "cópielo sin ningún cambio" in texto


def test_minimo_citas_ok_cita_sin_motivos_dice_sin_detalle():
    (texto,) = lint.minimo_citas_ok([_cv_con_motivos("c1", "alerta", [])], 2, 25)
    assert "Cita c1" in texto and "sin detalle" in texto


@pytest.mark.parametrize(
    "oracion",
    [
        "La jurisprudencia constitucional ha decantado de manera pacífica que el plazo debe ser razonable.",
        "En todo caso, la jurisprudencia ha dicho que la tutela es residual.",
        "Por su parte, la jurisprudencia de la Corte Constitucional ha sostenido que el daño debe ser inminente.",
        "LA JURISPRUDENCIA CONSTITUCIONAL HA SEÑALADO que procede el amparo.",
        "La jurisprudencia constitucional, de manera reiterada, ha precisado la regla.",
        "La jurisprudencia pacífica ha entendido que el término es razonable.",
    ],
)
def test_jurisprudencia_sin_cita_alerta(oracion):
    msgs = lint.jurisprudencia_sin_cita(oracion, "consideraciones, bloque 1")
    assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ")
    assert "consideraciones, bloque 1" in msgs[0] and "[[CITA:id]]" in msgs[0]


@pytest.mark.parametrize(
    "texto",
    [
        "La jurisprudencia constitucional ha decantado que el plazo debe ser razonable, según la [[CITA:c1]].",
        "En la [[CITA:c1]], la Corte precisó la regla. La jurisprudencia ha dicho lo mismo [[CITA:c2]].",
        "La tutela es un mecanismo residual y subsidiario.",
        "Según la jurisprudencia, el plazo debe ser razonable.",
        "La jurisprudencia constitucional establece que el plazo debe ser razonable.",
        "Hay jurisprudencia que ha dicho lo contrario.",
    ],
)
def test_jurisprudencia_sin_cita_con_marcador_o_sin_formula_no_alerta(texto):
    assert lint.jurisprudencia_sin_cita(texto, "x") == []


def test_jurisprudencia_sin_cita_el_marcador_debe_estar_en_la_misma_oracion():
    texto = "La jurisprudencia constitucional ha sostenido que el plazo es razonable. En la [[CITA:c1]], la Corte lo reiteró."
    assert len(lint.jurisprudencia_sin_cita(texto, "x")) == 1


def test_jurisprudencia_sin_cita_no_parte_oraciones_en_abreviaturas_ni_marcadores():
    texto = "Conforme al art. 86 superior, la jurisprudencia ha dicho que procede según la [[CITA:c1]]."
    assert lint.jurisprudencia_sin_cita(texto, "x") == []


def test_jurisprudencia_sin_cita_limita_los_mensajes():
    texto = " ".join(f"La jurisprudencia ha dicho la regla {i}." for i in range(20))
    assert len(lint.jurisprudencia_sin_cita(texto, "x")) == lint.MAX_LINEAS_CITADAS


def _decision(resultado=None, sustitutiva=None, accion="decidir") -> Decision:
    return Decision(
        accion=accion, resultado=resultado, sustitutiva=sustitutiva, eje="x", instruccion="x",
        ordenes=[Orden(destinatario="la entidad", conducta="entregar el medicamento")],
    )


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion",
    [
        ("REVOCAR", "AMPARAR", "Se revocará el fallo y se amparará el derecho a la salud."),
        ("REVOCAR", "AMPARAR", "Se REVOCARÁ la decisión y se tutelará el derecho invocado."),
        ("CONFIRMAR", "NEGAR", "Procede confirmar la decisión que negó el amparo."),
        ("CONFIRMAR", "NEGAR", "Se confirma el fallo, pues el juez le niega razón al actor."),
        ("MODIFICAR", "IMPROCEDENTE", "Se modificará el fallo para declarar la improcedencia de la acción."),
        ("REVOCAR", "IMPROCEDENTE", "Se revoca y se declara improcedente la acción de tutela."),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Se revocará para declarar la carencia actual de objeto por hecho superado."),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Se revocará al configurarse un hecho superado."),
        ("REVOCAR", "CARENCIA_DANO_CONSUMADO", "Se revocará y se declarará el daño consumado."),
        ("REVOCAR", "CARENCIA_SOBREVINIENTE", "Se revocará por la situación sobreviniente."),
    ],
)
def test_coherencia_decision_coherente(resultado, sustitutiva, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva)) == []


def test_coherencia_decision_anuncio_dentro_de_parentesis_no_bloquea():
    conclusion = "Se revocará la sentencia (y, en su lugar, se amparará el derecho)."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion",
    [
        ("CONFIRMAR", "NEGAR", "Se confirmará la sentencia (que negó el amparo)."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia (en su lugar se concede el amparo)."),
        ("REVOCAR", "IMPROCEDENTE", "Se revocará la sentencia (la acción es improcedente)."),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Se revocará la sentencia (hay carencia actual de objeto por hecho superado)."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia y, en su lugar, se concederá la tutela."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia y se concederá la protección del derecho."),
    ],
)
def test_coherencia_decision_trata_igual_dentro_y_fuera_de_parentesis(resultado, sustitutiva, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva)) == []


def test_coherencia_decision_conceder_tutela_contradice_negar():
    msgs = lint.coherencia_decision(
        _caso(conclusion="Se confirmará la sentencia y se concederá la tutela."), _decision("CONFIRMAR", "NEGAR")
    )
    assert any("AMPARAR" in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_parentesis_sin_cerrar_no_oculta_anuncio():
    conclusion = "Se revocará la sentencia (ver nota y se amparará el derecho. Lista: a) uno."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


def test_duplicados_parentesis_no_ocultan_parrafos_iguales():
    p = "El juez analiza el caso concreto y verifica los requisitos de procedencia de la acción "
    msgs = lint.duplicados([p + "(nota", "(aparte " + p + "a) fin"], 0.7)
    assert len(msgs) == 1


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion,faltante",
    [
        ("REVOCAR", "AMPARAR", "Se confirmará el fallo y se amparará el derecho.", "REVOCAR"),
        ("REVOCAR", "AMPARAR", "Se revocará el fallo de la acción de tutela interpuesta.", "AMPARAR"),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia en la tutela de los derechos.", "AMPARAR"),
        ("REVOCAR", "NEGAR", "Se revocará el fallo y se declarará improcedente.", "NEGAR"),
        ("MODIFICAR", "IMPROCEDENTE", "Se amparará el derecho y se revocará.", "MODIFICAR"),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Se revocará y se negará el amparo.", "CARENCIA_HECHO_SUPERADO"),
    ],
)
def test_coherencia_decision_incoherente_bloquea(resultado, sustitutiva, conclusion, faltante):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva))
    assert len(msgs) >= 1 and all(m.startswith("BLOQUEA: ") for m in msgs)
    assert any(faltante in m for m in msgs)


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion",
    [
        ("REVOCAR", "NEGAR", "El Despacho revocará la sentencia, que negó el amparo, y en su lugar se amparará."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia, que amparó los derechos y, en su lugar, se negará."),
        ("CONFIRMAR", "NEGAR", "No hay lugar a confirmar el fallo que negó el amparo; el Despacho lo revocará."),
        ("REVOCAR", "IMPROCEDENTE", "Se revocará la sentencia que declaró improcedente la acción y se amparará."),
        ("REVOCAR", "AMPARAR", "Se revocará el fallo y se amparará el derecho, aunque se declarará la carencia por hecho superado."),
    ],
)
def test_coherencia_decision_conclusion_contraria_bloquea(resultado, sustitutiva, conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva))
    assert msgs and all(m.startswith("BLOQUEA: ") for m in msgs)


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion",
    [
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia, que negó el amparo, y en su lugar se amparará el derecho."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia, que declaró improcedente la acción, y se amparará; no se negará el amparo."),
        ("REVOCAR", "IMPROCEDENTE", "Se revocará la sentencia que amparó los derechos y se declarará improcedente la acción."),
        ("CONFIRMAR", "NEGAR", "Se confirmará el fallo que negó el amparo en un negocio con efectos negativos."),
    ],
)
def test_coherencia_decision_mencionar_al_a_quo_en_pasado_no_bloquea(resultado, sustitutiva, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva)) == []


def test_raiz_neg_no_coincide_con_negocio_ni_negativo():
    msgs = lint.coherencia_decision(
        _caso(conclusion="Se revocará el fallo por el negocio negativo."), _decision("REVOCAR", "NEGAR")
    )
    assert any("NEGAR" in m for m in msgs)


def test_coherencia_decision_ignora_decisiones_sin_resultado_o_que_rehacen():
    assert lint.coherencia_decision(_caso(conclusion="nada"), _decision(accion="rehacer_apertura")) == []
    assert lint.coherencia_decision(_caso(conclusion="nada"), _decision(None, None)) == []


def _reparos() -> list[Reparo]:
    return [Reparo(id=f"R{i}", sintesis="s", doc_id="2a-002", cita_literal="x") for i in (1, 2, 3)]


def test_cobertura_reparos_todos_tratados():
    assert lint.cobertura_reparos([["R1"], ["R2", "R3"]], _reparos()) == []
    assert lint.cobertura_reparos(["R1", "R2", "R3"], _reparos()) == []
    assert lint.cobertura_reparos([["R1", "R2", "R3"]], ["R1", "R2", "R3"]) == []


def test_cobertura_reparos_faltante_es_alerta_salvo_absorbido():
    msgs = lint.cobertura_reparos([["R1"]], _reparos())
    assert len(msgs) == 2 and all(m.startswith("ALERTA: ") for m in msgs)
    assert "R2" in msgs[0] and "R3" in msgs[1]
    decision = Decision(
        accion="decidir",
        por_reparo=[DisposicionReparo(reparo_id="R2", disposicion="ABSORBIDO"), DisposicionReparo(reparo_id="R3", disposicion="ACOGE")],
    )
    msgs = lint.cobertura_reparos([["R1"]], _reparos(), decision)
    assert len(msgs) == 1 and "R3" in msgs[0]


@pytest.mark.parametrize(
    "n,esperado",
    [(99, "por debajo"), (100, None), (150, None), (200, None), (201, "por encima")],
)
def test_extension(n, esperado):
    msgs = lint.extension("palabra " * n, [100, 200], "caso_concreto")
    if esperado is None:
        assert msgs == []
    else:
        assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ") and esperado in msgs[0] and "caso_concreto" in msgs[0]
        assert str(n) in msgs[0]


P1 = "El Despacho considera que la entidad accionada vulneró el derecho a la salud del paciente al negar el suministro del medicamento"
P2 = "El Despacho considera que la entidad accionada vulneró el derecho a la salud del paciente al negar el suministro del insumo"
P3 = "La subsidiariedad exige agotar los mecanismos ordinarios antes de acudir al juez constitucional salvo perjuicio irremediable"


def test_duplicados():
    msgs = lint.duplicados([P1, P3, P2], 0.5)
    assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ") and "1 y 3" in msgs[0]
    assert lint.duplicados([P1, P3], 0.5) == []
    assert lint.duplicados([P1, P1], 0.99)
    assert lint.duplicados([P1, P2], 0.99) == []
    assert lint.duplicados(["Se concluye que sí.", "Se concluye que sí."], 0.5) == []


def test_residuos_limpios_y_marcadores_validos():
    texto = (
        "Corresponde al Despacho determinar si procede el amparo.\n\n"
        "[[CITA:c1]] La Corte ha sostenido que la acción es subsidiaria.\n\n"
        "[[IMAGEN 2a-001 3 pie]]\n\n"
        "Primer reparo: la entidad alega que no se probó la vulneración.\n\n"
        "Cualquier persona puede reclamar.\nTODOS los derechos se protegen."
    )
    assert lint.residuos(texto) == []


@pytest.mark.parametrize(
    "parrafo",
    [
        "Agregar un párrafo sobre la inmediatez.",
        "verificar la fecha del fallo",
        "[Completar con el nombre de la entidad]",
        "Borrador del párrafo final",
        "TODO revisar este párrafo",
        "[[CITA:c1]] [pendiente de redactar]",
    ],
)
def test_residuos_detecta_restos_de_borrador(parrafo):
    msgs = lint.residuos("Texto normal que sí está terminado.\n\n" + parrafo)
    assert len(msgs) == 1 and msgs[0].startswith("ALERTA: ") and "párrafo 2" in msgs[0]


def test_residuos_infinitivo_en_parrafo_largo_no_alerta():
    largo = "Agregar " + "palabra " * 45
    assert lint.residuos(largo) == []


def test_coherencia_decision_mensaje_usa_etiqueta_legible_para_conceder():
    msgs = lint.coherencia_decision(
        _caso(conclusion="Se revocará la sentencia y se dispondrá otra cosa."), _decision("REVOCAR", "AMPARAR")
    )
    texto = " ".join(msgs)
    assert "«conceder la tutela/protección…»" in texto
    assert "\\" not in texto and "(?" not in texto


def test_coherencia_decision_condicional_concederia_del_a_quo_no_bloquea():
    conclusion = "Se revocará la decisión, ya que el a quo concedería la tutela sin pruebas, y se negará el amparo."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "NEGAR")) == []


@pytest.mark.parametrize("resultado", ["NEGAR", "IMPROCEDENTE"])
@pytest.mark.parametrize("giro", ["se concederá el amparo del derecho a la salud", "se concederá la protección del derecho"])
def test_coherencia_decision_conceder_amparo_contradice_negar_e_improcedente(resultado, giro):
    conclusion = f"Se confirmará la sentencia que negó la tutela y {giro}."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", resultado))
    assert any("AMPARAR" in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_concederia_amparo_sigue_excusado():
    conclusion = "Se confirmará la sentencia, ya que el a quo concedería el amparo sin pruebas, y se negará la tutela."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", "NEGAR")) == []


@pytest.mark.parametrize(
    "resultado,sustitutiva,conclusion",
    [
        ("CONFIRMAR", "NEGAR", "Se confirmará la sentencia y, por las mismas razones, tampoco se concederá el amparo frente a la EPS."),
        ("CONFIRMAR", "NEGAR", "Se confirmará, porque a la accionante no se le concederá el amparo sin prueba del perjuicio."),
        ("CONFIRMAR", "NEGAR", "Se confirmará el fallo; ni se concederá el amparo ni se ordenará el pago."),
        ("CONFIRMAR", "NEGAR", "Se confirmará, pues en modo alguno se concederá el amparo de un derecho no vulnerado."),
        ("CONFIRMAR", "IMPROCEDENTE", "Se confirmará, pues solo si se acredita un perjuicio irremediable se concederá el amparo transitorio."),
        ("CONFIRMAR", "NEGAR", "Se confirmará, y si se probara el perjuicio, se concederá el amparo, lo cual no ocurre; se negará la tutela."),
        ("REVOCAR", "NEGAR", "Se revocará la sentencia; nunca se amparará el derecho y se negará la tutela."),
        ("REVOCAR", "AMPARAR", "Se revocará la sentencia y no se negará el amparo, por lo que se concederá la tutela."),
    ],
)
def test_coherencia_decision_negador_o_condicional_previo_excusa_el_anuncio(resultado, sustitutiva, conclusion):
    assert lint._contradicciones(conclusion, _decision(resultado, sustitutiva)) == []


def test_coherencia_decision_negador_lejano_no_excusa_conceder_amparo():
    conclusion = "Se confirmará la sentencia que no negó la tutela por error; se concederá el amparo del derecho."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", "NEGAR"))
    assert any("AMPARAR" in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_conceder_amparo_sin_negador_bajo_negar_bloquea():
    conclusion = "Se confirmará la sentencia y se concederá el amparo."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", "NEGAR"))
    assert any("AMPARAR" in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_si_bien_no_es_condicional():
    conclusion = "Si bien hubo dudas, se confirmará la sentencia y se concederá el amparo."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", "NEGAR"))
    assert any("AMPARAR" in m for m in msgs)


@pytest.mark.parametrize("verbo", ["verificó", "determinó", "estableció", "analizó", "supo", "examinó", "revisó", "constató", "precisó"])
@pytest.mark.parametrize("resultado,sustitutiva", [("CONFIRMAR", "NEGAR"), ("CONFIRMAR", "IMPROCEDENTE")])
def test_coherencia_decision_si_interrogativo_indirecto_no_excusa(verbo, resultado, sustitutiva):
    conclusion = f"Se {verbo} si la EPS cumplió la orden, y por ello se concederá el amparo."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva))
    assert any("AMPARAR" in m and m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_si_condicional_tras_punto_no_bloquea():
    conclusion = "Por ello se confirmará la decisión. Si el accionante acreditara un perjuicio irremediable, se revocaría el fallo."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR")) == []


def test_coherencia_decision_pregunta_indirecta_tras_punto_sigue_bloqueando():
    conclusion = "Se confirmará la decisión. Falta verificar si se revocará el fallo."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR"))
    assert any(m.startswith(lint.BLOQUEA) for m in msgs)


def test_coherencia_decision_si_bien_tras_punto_no_se_excusa():
    conclusion = "Se confirmará la decisión. Si bien se revocará el fallo, nada cambia."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR"))
    assert any(m.startswith(lint.BLOQUEA) for m in msgs)


@pytest.mark.parametrize(
    ("resultado", "sustitutiva", "conclusion"),
    [
        ("CONFIRMAR", None, "Se revocarán las decisiones y se confirmará el fallo."),
        ("REVOCAR", "NEGAR", "Se revocará el fallo y se ampararán los derechos fundamentales."),
        ("REVOCAR", "IMPROCEDENTE", "Se revocará el fallo y se tutelarán los derechos fundamentales."),
        ("REVOCAR", "AMPARAR", "Se revocará el fallo y se negarán las pretensiones."),
        ("REVOCAR", "NEGAR", "Se revocará el fallo y se concederán el amparo y la protección."),
        ("REVOCAR", "AMPARAR", "Se revocará el fallo y se declararán improcedentes las pretensiones; se declararán improcedente la acción."),
        ("CONFIRMAR", None, "Se confirmará el fallo y se revocarían las órdenes."),
    ],
)
def test_coherencia_decision_formas_plurales_del_futuro_bloquean(resultado, sustitutiva, conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva))
    assert any("La conclusión anuncia" in m for m in msgs)


@pytest.mark.parametrize(
    ("resultado", "sustitutiva", "conclusion"),
    [
        ("CONFIRMAR", None, "Advierte la Sala que si la entidad no acredita el pago dentro del término, se revocará la orden, por lo que se confirmará el fallo."),
        ("CONFIRMAR", None, "Se actuará de modo que si el actor incumple, se revocará la orden; se confirmará el fallo."),
        ("CONFIRMAR", None, "Se confirmará el fallo, por lo que si el actor incumple, se revocará la orden."),
        ("CONFIRMAR", None, "Así que si el actor incumple, se revocará la orden; se confirmará el fallo."),
        ("CONFIRMAR", None, "La Corte ha dicho «si el juez constata el daño, revocará la decisión». Por ello, se confirmará el fallo."),
        ("REVOCAR", "AMPARAR", "Se debe aclarar —si hay otro medio, se declarará improcedente la acción—; se revocará el fallo y se amparará el derecho."),
        ("CONFIRMAR", None, "Se confirmará el fallo, pues de lo contrario se revocarían decisiones ejecutoriadas."),
        ("CONFIRMAR", None, "Se confirmará el fallo; en caso contrario, se revocarían las órdenes."),
        ("CONFIRMAR", None, "Se confirmará el fallo; de otro modo se revocarán decisiones firmes."),
    ],
)
def test_coherencia_decision_condicional_y_alternativa_hipotetica_no_bloquean(resultado, sustitutiva, conclusion):
    assert lint._contradicciones(conclusion, _decision(resultado, sustitutiva)) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se confirmará el fallo y se revocará la sentencia.",
        "Advierte la Sala que se verificó si se revocará el fallo.",
        "Se confirmará el fallo. Si bien se revocará la sentencia, nada cambia.",
    ],
)
def test_coherencia_decision_contradiccion_genuina_sigue_bloqueando(conclusion):
    assert lint._contradicciones(conclusion, _decision("CONFIRMAR", None))


@pytest.mark.parametrize(
    "conclusion",
    [
        "No hay razón para mantener la decisión, de modo que procede revocar. Dicho de otro modo, la Sala confirmará el fallo impugnado.",
        "La EPS debía autorizar el servicio; de lo contrario, vulneraba el derecho. Así, se confirmará el fallo y no procede revocarlo.",
    ],
)
def test_coherencia_decision_hipotetico_no_cruza_oraciones_ni_reformulacion(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("CONFIRMAR" in m for m in msgs)


def test_coherencia_decision_de_lo_contrario_en_la_misma_oracion_no_bloquea():
    conclusion = "Se confirmará el fallo, pues de lo contrario se revocarían decisiones ejecutoriadas."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", None)) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se confirmará el fallo, salvo si la entidad no ha cumplido, caso en el cual se revocaría.",
        "Se confirmará el fallo; únicamente si se hubiera acreditado el perjuicio se revocaría la decisión.",
        "Se confirmará el fallo, salvo que la entidad incumpla, pues se revocaría.",
        "Se confirmará el fallo, siempre y cuando se cumpla; a menos que no, se revocaría.",
        "Se confirmará el fallo; en tal caso se revocaría solo si hubiera incumplimiento.",
    ],
)
def test_coherencia_decision_conectores_condicionales_no_bloquean(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", None)) == []


def test_coherencia_decision_salvo_en_otra_oracion_no_excusa():
    conclusion = "Se confirmará el fallo, salvo el numeral 2. La Sala revocará la decisión."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("CONFIRMAR", None))
    assert any("REVOCAR" in m for m in msgs)


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se revocará el fallo, se amparará el derecho de petición y se negarán las demás pretensiones.",
        "Se revocará el fallo, se amparará el derecho de petición y se negará las demás pretensiones.",
        "Se revocará el fallo y se amparará el derecho de petición; las demás pretensiones se negarán.",
    ],
)
def test_coherencia_decision_negar_lo_demas_con_amparo_no_bloquea(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "Por lo demás, la Sala revocará el fallo impugnado y negará el amparo solicitado.",
        "Valoradas las demás pruebas, se revocará el fallo y se negará el amparo.",
        "Analizados los demás argumentos, se revocará el fallo y se negarán las súplicas.",
    ],
)
def test_coherencia_decision_demas_que_no_son_pretensiones_no_excusa_negar(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("NEGAR" in m for m in msgs)


@pytest.mark.parametrize(
    "conclusion",
    [
        "Desestimados los demás reparos, la Sala revocará el fallo y negará el amparo.",
        "Al no prosperar los demás reparos, se revocará el fallo y se negará el amparo.",
        "Revisadas las demás pretensiones, la Sala revocará el fallo y negará el amparo solicitado.",
        "Examinados los demás derechos invocados, se revocará el fallo y se negará el amparo.",
    ],
)
def test_coherencia_decision_demas_en_clausula_introductoria_sin_concesion_bloquea(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("NEGAR" in m for m in msgs)


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se revocará el fallo, se amparará el derecho de petición y se negará en lo demás.",
        "Se revocará el fallo, se amparará el derecho a la salud y se negará el amparo en lo demás.",
        "Se revocará el fallo, se amparará el derecho a la salud; en lo demás, se negará el amparo.",
        "Se revocará el fallo, se amparará el derecho de petición y se negará lo demás pedido.",
        "Se revocará el fallo, se amparará el derecho y se negará el amparo respecto de las demás pretensiones.",
        "Se revocará el fallo, se amparará el derecho y se negarán las demás súplicas.",
        "Se revocará el fallo, se amparará el derecho y se negarán las pretensiones restantes.",
    ],
)
def test_coherencia_decision_negacion_parcial_con_concesion_no_bloquea(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "La Sala revocará el fallo, no amparará el derecho invocado y negará las demás pretensiones.",
        "Se revocará el fallo; no se tutelarán los derechos y se negará lo demás.",
        "Se revocará el fallo. Tampoco se amparará el derecho, y se negará el amparo en lo demás.",
        "La Sala revocará el fallo y negará el amparo del derecho a la salud y las demás pretensiones, pues no se ampararía un derecho sin prueba.",
        "Desestimados los demás reparos, la Sala revocará el fallo y negará el amparo. Se ampararía el derecho solo si se hubiera probado el perjuicio.",
    ],
)
def test_coherencia_decision_concesion_negada_o_hipotetica_no_excusa_la_negacion(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("NEGAR" in m for m in msgs)


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se revocará la sentencia y se amparará el derecho de petición, si bien no en los términos pedidos, y se negarán las demás pretensiones.",
        "Se revocará la sentencia y se amparará el derecho de petición, pues la entidad no indicó si resolvió la solicitud, y se negarán las demás pretensiones.",
        "Se revocará el fallo, se amparará el derecho a la salud, se ordenará a la EPS valorar si requiere la cirugía y se negarán las demás pretensiones.",
    ],
)
def test_coherencia_decision_si_no_condicional_tras_la_concesion_no_la_descarta(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


def test_coherencia_decision_negar_lo_demas_sigue_bloqueando_si_se_decidio_improcedente():
    conclusion = "Se revocará el fallo, se amparará el derecho y se negarán las demás pretensiones."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "IMPROCEDENTE"))
    assert any("AMPARAR" in m for m in msgs)


# --- #87: MODIFICAR confirma una parte y revoca otra -------------------------------------------------------------

@pytest.mark.parametrize(
    "conclusion",
    [
        "Por lo anterior, el Despacho modificará el numeral segundo del fallo de primera instancia y, en lo demás, lo confirmará, amparando los derechos fundamentales.",
        "Por lo anterior, se modificará el fallo impugnado y se confirmarán los demás numerales, de modo que se ampara el derecho a la salud.",
        "Se revocará el numeral tercero y se modificará el cuarto, de manera que se ampara el derecho a la salud.",
        "Se confirmará parcialmente la sentencia impugnada, se modificará el plazo y se amparará el derecho.",
        "Procede modificar la sentencia para amparar el derecho a la salud, adicionando una orden, y confirmarla en lo demás.",
        "Corresponde modificar el numeral segundo, confirmar en lo demás la sentencia y amparar el derecho.",
        "El Despacho considera que debe modificar el fallo, revocando el numeral tercero y confirmando en lo demás, y amparar el derecho.",
    ],
)
def test_coherencia_decision_modificar_admite_confirmar_y_revocar_partes(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("MODIFICAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    ("conclusion", "esperado"),
    [
        ("Se confirmará el fallo y se amparará el derecho a la salud.", "MODIFICAR"),
        ("Se modificará el fallo y se negará el amparo.", "AMPARAR"),
    ],
)
def test_coherencia_decision_modificar_sigue_exigiendo_su_raiz_y_la_sustitutiva(conclusion, esperado):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("MODIFICAR", "AMPARAR"))
    assert msgs and all(m.startswith("BLOQUEA: ") for m in msgs) and any(esperado in m for m in msgs)


# --- #88: amparo parcial -------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("resultado", "conclusion"),
    [
        ("REVOCAR", "Se revocará el fallo que negó el amparo y se amparará el derecho a la salud; en cambio, se negará el tratamiento integral por no haberse acreditado una omisión futura."),
        ("REVOCAR", "El Despacho revocará la sentencia de primera instancia, amparará el derecho a la salud y negará la solicitud de exoneración de copagos."),
        ("REVOCAR", "Corresponde revocar el fallo y amparar el derecho; no obstante se negará el pago de transporte."),
        ("CONFIRMAR", "El Despacho confirmará la sentencia impugnada, que amparó los derechos, y negará la solicitud de reembolso formulada por la accionada."),
        ("REVOCAR", "El Despacho considera que debe revocar el fallo, amparar el derecho a la salud y negar el tratamiento integral."),
        ("REVOCAR", "Se revocará el fallo, se amparará el derecho a la salud y se negarán los copagos y el transporte."),
        ("REVOCAR", "Se revocará el fallo, se amparará el derecho a la salud y se negará la pretensión de tratamiento integral."),
        ("REVOCAR", "Se revocará el fallo, se amparará el derecho y se negará su pretensión de ser exonerada de copagos."),
        ("REVOCAR", "El Despacho revocaría la sentencia, ampararía el derecho y negaría los copagos."),
        ("REVOCAR", "Se revocará el fallo, se ampararán los derechos a la salud y a la vida y se negarán los viáticos y el hospedaje."),
        ("REVOCAR", "Se revocará el fallo, amparando el derecho a la salud, y se negará el tratamiento integral."),
        ("REVOCAR", "Se revocará el fallo, se ampara el derecho a la salud y se negará el tratamiento integral."),
    ],
)
def test_coherencia_decision_negar_una_pretension_accesoria_no_contradice_amparar(resultado, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "Se revocará el fallo y se negará el amparo.",
        "Se revocará el fallo y se negará la tutela.",
        "Se revocará el fallo y se negarán las pretensiones de la acción de tutela.",
        "Se revocará el fallo y se negarán las pretensiones.",
        "Se revocará el fallo y se negará la solicitud de amparo.",
        "Se revocará el fallo y se negará la acción de tutela.",
        "Se revocará el fallo, se amparará el derecho y se negará.",
        "Se revocará el fallo, se amparará el derecho y se negará por falta de prueba.",
        "Se revocará el fallo, se amparará el derecho y se negará lo solicitado.",
        "Se revocará el fallo, se amparará el derecho y se negará el derecho a la salud.",
        "Se revocará el fallo, se amparará el derecho y se negará su pretensión.",
        "Se revocará el fallo, se amparará el derecho y se negarán todas las pretensiones.",
        "Se revocará el fallo, se amparará el derecho y se negará integralmente el amparo.",
        "La Sala revocará el fallo, no amparará el derecho invocado y negará el tratamiento integral.",
    ],
)
def test_coherencia_decision_negar_el_amparo_mismo_sigue_bloqueando_bajo_amparar(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia NEGAR" in m for m in msgs)


def test_coherencia_decision_confirmar_amparo_y_negar_el_amparo_bloquea():
    msgs = lint.coherencia_decision(
        _caso(conclusion="Se confirmará el fallo y se negará el amparo."), _decision("CONFIRMAR", "AMPARAR")
    )
    assert any("anuncia NEGAR" in m for m in msgs)


def test_coherencia_decision_derecho_marcado_niega_admite_negar_el_amparo_de_ese_derecho():
    conclusion = "Se revocará el fallo, se amparará la salud y se negará el amparo respecto del mínimo vital."
    derechos = [DisposicionDerecho(derecho="salud", disposicion="AMPARA"), DisposicionDerecho(derecho="mínimo vital", disposicion="NIEGA")]
    decision = _decision("REVOCAR", "AMPARAR").model_copy(update={"derechos": derechos})
    assert lint.coherencia_decision(_caso(conclusion=conclusion), decision) == []
    sin_marca = _decision("REVOCAR", "AMPARAR")
    assert any("anuncia NEGAR" in m for m in lint.coherencia_decision(_caso(conclusion=conclusion), sin_marca))


def test_coherencia_decision_el_mensaje_orienta_en_vez_de_hablar_del_a_quo_en_general():
    msgs = lint.coherencia_decision(_caso(conclusion="Se revocará el fallo y se negará el amparo."), _decision("REVOCAR", "AMPARAR"))
    texto = " ".join(msgs)
    assert "«amparar»" in texto and "pretensión accesoria" in texto
    msgs = lint.coherencia_decision(_caso(conclusion="Se confirmará el fallo y se amparará el derecho."), _decision("REVOCAR", "AMPARAR"))
    assert "«revocar»" in " ".join(msgs) and "pretensión accesoria" not in " ".join(msgs)


# --- #89: infinitivo y tipo de carencia ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("sustitutiva", "conclusion"),
    [
        ("CARENCIA_DANO_CONSUMADO", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por hecho superado."),
        ("CARENCIA_HECHO_SUPERADO", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por situación sobreviniente."),
        ("CARENCIA_SOBREVINIENTE", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por daño consumado."),
        ("CARENCIA_HECHO_SUPERADO", "Se revocará el fallo y se declarará la carencia actual de objeto por daño consumado."),
        ("AMPARAR", "Corresponde revocar la sentencia y negar el amparo."),
        ("AMPARAR", "Procede revocar la sentencia, amparar el derecho a la salud y, en su lugar, negar la tutela."),
        ("AMPARAR", "Por lo anterior, el Despacho debe revocar el fallo, amparar el derecho y negar el amparo solicitado por la accionante."),
        ("AMPARAR", "El Despacho decide revocar el fallo, amparar el derecho y negar las pretensiones de la acción de tutela."),
        ("AMPARAR", "Corresponde revocar la sentencia de primera instancia, amparar el derecho y declarar improcedente la acción de tutela."),
        ("AMPARAR", "Corresponde revocar la sentencia, amparar el derecho a la salud y declarar la carencia actual de objeto por hecho superado."),
        ("NEGAR", "Corresponde revocar la sentencia, negar la tutela y conceder el amparo."),
    ],
)
def test_coherencia_decision_detecta_contradiccion_en_infinitivo_y_tipo_de_carencia_equivocado(sustitutiva, conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", sustitutiva))
    assert msgs and all(m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_resultado_en_infinitivo_contradictorio_bloquea():
    msgs = lint.coherencia_decision(_caso(conclusion="Corresponde confirmar la sentencia y amparar el derecho."), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs)


@pytest.mark.parametrize(
    ("resultado", "sustitutiva", "conclusion"),
    [
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por hecho superado."),
        ("REVOCAR", "CARENCIA_DANO_CONSUMADO", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por daño consumado."),
        ("REVOCAR", "CARENCIA_SOBREVINIENTE", "Corresponde revocar la sentencia y declarar la carencia actual de objeto por situación sobreviniente."),
        ("REVOCAR", "CARENCIA_DANO_CONSUMADO", "El Despacho considera que debe revocar el fallo y declarar la carencia actual de objeto por daño consumado, y no por hecho superado."),
        ("REVOCAR", "AMPARAR", "En consecuencia, el Despacho considera que debe revocar el fallo de primera instancia y amparar los derechos fundamentales invocados."),
        ("CONFIRMAR", "NEGAR", "En consecuencia, el Despacho considera que debe confirmar el fallo de primera instancia y negar el amparo solicitado."),
        ("REVOCAR", "IMPROCEDENTE", "En consecuencia, el Despacho considera que debe revocar el fallo de primera instancia y declarar improcedente la acción de tutela."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar la sentencia, que decidió negar el amparo, y amparar el derecho a la salud."),
        ("REVOCAR", "AMPARAR", "El a quo erró al negar el amparo; por eso corresponde revocar el fallo y amparar el derecho."),
        ("REVOCAR", "AMPARAR", "No corresponde confirmar el fallo; procede revocarlo y amparar el derecho a la salud."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar la sentencia y amparar el derecho, sin negar el amparo."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar la sentencia y amparar el derecho, no negar el amparo."),
        ("REVOCAR", "AMPARAR", "No es necesario negar el amparo: corresponde revocar y amparar el derecho."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar la sentencia y amparar el derecho; no procede negar el amparo."),
        ("REVOCAR", "AMPARAR", "Dado que la decisión de negar el amparo no se sostiene, corresponde revocar el fallo y amparar el derecho."),
        ("REVOCAR", "AMPARAR", "Si se acreditara el perjuicio, correspondería negar el amparo; como no es así, corresponde revocar y amparar."),
        ("CONFIRMAR", "NEGAR", "Corresponde confirmar la decisión de primera instancia de negar el amparo."),
        ("CONFIRMAR", "NEGAR", "Corresponde confirmar la sentencia, que negó el amparo."),
        ("CONFIRMAR", "IMPROCEDENTE", "Corresponde confirmar la decisión del a quo de declarar improcedente la acción de tutela."),
        ("REVOCAR", "NEGAR", "Corresponde revocar el fallo, que había decidido amparar los derechos, y negar la tutela."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar el fallo y amparar el derecho a la salud, ordenando a la EPS autorizar el procedimiento y confirmar la fecha de la cita."),
        ("REVOCAR", "AMPARAR", "Corresponde revocar el fallo, amparar el derecho a la salud y ordenar a la EPS entregar el medicamento y confirmar su entrega."),
        ("REVOCAR", "AMPARAR", "El Despacho debe revocar el fallo y amparar el derecho a la salud, ordenando a la EPS programar la cirugía y confirmar la fecha por escrito."),
    ],
)
def test_coherencia_decision_infinitivo_coherente_o_descriptivo_no_bloquea(resultado, sustitutiva, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, sustitutiva)) == []


_INTRODUCCIONES_DE_ORDEN = (
    "Corresponde {res} el fallo y amparar el derecho a la salud, ordenando a la EPS",
    "El Despacho debe {res} el fallo y amparar el derecho a la salud, ordenando a la EPS",
    "Corresponde {res} el fallo, amparar el derecho a la salud y ordenar a la EPS",
)
_VERBOS_DE_ORDEN = ("autorizar", "programar", "entregar", "suministrar", "garantizar", "practicar")
_ENLACES_DE_ORDEN = (" y", ", y", " o", ", además,")
# (resultado decidido, su infinitivo, el otro verbo de resultado que una orden a la EPS puede traer, su complemento)
_RESULTADO_Y_VERBO_DE_TERCERO = (
    ("REVOCAR", "revocar", "confirmar", "la fecha de la cita"),
    ("CONFIRMAR", "confirmar", "revocar", "la negativa previa"),
)


@pytest.mark.parametrize(("resultado", "infinitivo", "tercero", "complemento"), _RESULTADO_Y_VERBO_DE_TERCERO)
@pytest.mark.parametrize("enlace", _ENLACES_DE_ORDEN)
@pytest.mark.parametrize("orden", _VERBOS_DE_ORDEN)
@pytest.mark.parametrize("introduccion", _INTRODUCCIONES_DE_ORDEN)
def test_coherencia_decision_el_verbo_de_una_orden_a_un_tercero_no_es_el_resultado_anunciado(
    introduccion, orden, enlace, resultado, infinitivo, tercero, complemento
):
    # «confirmar» o «revocar» coordinado con otro verbo de orden («programar la cirugía y confirmar la fecha») lo hace
    # un tercero: el anuncio del Despacho acaba donde empiezan las órdenes.
    conclusion = f"{introduccion.format(res=infinitivo)} {orden} el tratamiento{enlace} {tercero} {complemento}."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "Corresponde confirmar el fallo y amparar el derecho a la salud, ordenando a la EPS autorizar el procedimiento.",
        "Corresponde confirmar el fallo y ordenar a la EPS entregar el medicamento.",
        "Corresponde revocar el fallo y negar el amparo, ordenando a la EPS programar la cirugía.",
        "El Despacho debe confirmar el fallo, amparar el derecho a la salud y ordenar a la EPS programar la cirugía y confirmar la fecha.",
    ],
)
def test_coherencia_decision_la_contradiccion_escrita_antes_de_las_ordenes_sigue_bloqueando(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert msgs and all(m.startswith("BLOQUEA: ") for m in msgs)


def test_coherencia_decision_carencia_sin_tipo_ya_no_basta():
    msgs = lint.coherencia_decision(
        _caso(conclusion="Se revocará para declarar la carencia actual de objeto."), _decision("REVOCAR", "CARENCIA_HECHO_SUPERADO")
    )
    assert any("«declarar la carencia actual de objeto por hecho superado»" in m for m in msgs)


@pytest.mark.parametrize(
    ("sustitutiva", "conclusion"),
    [
        ("CARENCIA_SOBREVINIENTE", "Corresponde revocar y declarar la carencia actual de objeto por situación sobreviniente, distinta del hecho superado."),
        ("CARENCIA_SOBREVINIENTE", "Se revocará el fallo y se declarará la carencia actual de objeto por situación sobreviniente, distinta del hecho superado."),
        ("CARENCIA_DANO_CONSUMADO", "Corresponde revocar y declarar la carencia actual de objeto por daño consumado, a diferencia del hecho superado."),
        ("CARENCIA_DANO_CONSUMADO", "Se revocará el fallo y se declarará la carencia actual de objeto por daño consumado, a diferencia del hecho superado."),
    ],
)
def test_coherencia_decision_el_tipo_de_carencia_decidido_no_se_confunde_con_otro_que_solo_se_contrasta(sustitutiva, conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", sustitutiva)) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "El Despacho considera que debe confirmar el fallo y amparar el derecho a la salud.",
        "Por lo anterior, el Despacho debe confirmar la sentencia y amparar el derecho a la salud.",
        "La Sala deberá confirmar la sentencia y amparar el derecho a la salud.",
        "Por lo expuesto, debe confirmar el fallo y amparar el derecho a la salud.",
        "Corresponde amparar el derecho a la salud; en consecuencia, deberá confirmar el fallo.",
        "Corresponde amparar el derecho a la salud. Así las cosas, por lo tanto, debe confirmar el fallo.",
        "Corresponde amparar el derecho a la salud; el Despacho, por tanto, debe confirmar el fallo.",
    ],
)
def test_coherencia_decision_deber_con_sujeto_el_despacho_anuncia_un_resultado_contradictorio(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs)


@pytest.mark.parametrize(
    "conclusion",
    [
        "El Despacho considera que debe revocar el fallo y amparar el derecho a la salud, y la accionada deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud. La EPS debe confirmar la cita médica del accionante.",
        "El Despacho debe revocar el fallo y amparar el derecho a la salud, mientras que las entidades deben confirmar la cita.",
        # Un sujeto nominal con un inciso antes de «deber» sigue siendo un tercero: la coma del inciso no deja el sujeto implícito.
        "Corresponde revocar el fallo y amparar el derecho a la salud; la EPS, por tanto, deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la entidad accionada, en consecuencia, deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; las demás entidades, además, deben confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; el hospital, por su parte, deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la Nueva EPS S.A., desde ahora, deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, y la EPS, así las cosas, deberá confirmar la cita.",
        # El punto de una sigla o abreviatura no cierra la oración: el sujeto sigue siendo la entidad.
        "Corresponde revocar el fallo y amparar el derecho a la salud; la Nueva EPS S.A. deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la Nueva EPS S.A.S. debe confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la E.P.S. deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la Clínica Los Andes Ltda. deberá confirmar la cita.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la Dra. deberá confirmar la cita.",
    ],
)
def test_coherencia_decision_deber_de_un_tercero_no_anuncia_el_resultado(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize("sujeto", ["la EPS", "la entidad accionada", "las demás entidades", "el hospital", "la Nueva EPS S.A."])
@pytest.mark.parametrize("inciso", [", por tanto,", ", en consecuencia,", ", además,", ", por su parte,", ", desde ahora,", ", por lo expuesto,"])
@pytest.mark.parametrize("verbo", ["deberá", "debe"])
def test_coherencia_decision_deber_de_un_sujeto_nominal_con_inciso_no_anuncia_el_resultado(sujeto, inciso, verbo):
    conclusion = f"Corresponde revocar el fallo y amparar el derecho a la salud; {sujeto}{inciso} {verbo} confirmar la cita."
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


# --- Convergencia de la regla del infinitivo -----------------------------------------------------------------------------
# Un infinitivo solo es el resultado que anuncia la conclusión si el Despacho es, sin ambigüedad, quien lo anuncia. Estas
# tablas recorren todas las combinaciones (disparador × tercero o Despacho × verbo directo o coordinado × decisión) con un
# vocabulario propio, distinto del de lint.py: ningún tercero bloquea y todo anuncio del Despacho se detecta. Cada una
# aserta su tamaño, para que las cifras que cita el PR sigan siendo las que se ejecutan.

_IMPERSONALES = ("corresponde", "procede", "se impone", "hay que", "se debe", "es necesario", "es preciso", "resulta procedente", "lo procedente es")
_IMPERSONALES_CON_DATIVO = ("corresponde", "es necesario", "es preciso", "resulta procedente")  # admiten «a la EPS le corresponde»
_MODALES = ("debe", "deberá", "deben", "deberán", "ha de", "habrá de", "han de", "habrán de", "procederá a", "procederán a")
_MODALES_CON_SUJETO_POSPUESTO = ("debe", "deberá", "deben", "deberán")  # «debe la entidad confirmar la cita»
_TERCEROS = ("la EPS", "el accionado", "las demás entidades", "la Nueva EPS S.A.", "Sura", "ella")
# (resultado decidido, su infinitivo, el verbo contrario que un tercero puede traer, los complementos que puede llevar). Los
# complementos incluyen el objeto judicial («confirmar el fallo»): es el caso natural de las partes, y es el que la regla de
# objeto («confirmar la cita» no se examina) no descarta de antemano.
_DECISIONES_Y_VERBO_DE_TERCERO = (
    ("REVOCAR", "revocar", "confirmar", ("la cita médica", "el fallo", "la sentencia")),
    ("CONFIRMAR", "confirmar", "revocar", ("la glosa", "el fallo", "la sentencia")),
)
_ORDENES_PREVIAS = ("autorizar el procedimiento", "programar la cirugía", "entregar el medicamento")
_ENLACES_DE_TERCERO = (" y", ", además,")
# «. » abre otra oración; «, y » y «, pues » dejan al tercero dentro de la misma oración que el anuncio del Despacho.
_UNIONES_CON_EL_ANUNCIO_DEL_DESPACHO = (". ", ", y ", ", pues ")


def _en_mayuscula_inicial(frase: str) -> str:
    return frase[0].upper() + frase[1:]


def _cadenas_de_tercero(verbo: str, complemento: str) -> list[str]:
    # directa («confirmar la cita») o coordinada con otras órdenes («programar la cirugía y confirmar la cita»)
    return [f"{verbo} {complemento}"] + [f"{o}{e} {verbo} {complemento}" for o in _ORDENES_PREVIAS for e in _ENLACES_DE_TERCERO]


def _frases_de_tercero_impersonales(tercero: str, cadena: str) -> list[str]:
    frases = []
    for d in _IMPERSONALES:
        frases += [f"a {tercero} {d} {cadena}", f"a {tercero}, en consecuencia, {d} {cadena}", f"para {tercero}, {d} {cadena}",
                   f"según {tercero}, {d} {cadena}", f"{tercero} sostiene que {d} {cadena}"]
        if d in _IMPERSONALES_CON_DATIVO:
            frases.append(f"a {tercero} le {d} {cadena}")
    return frases


def _frases_de_tercero_con_modal(tercero: str, cadena: str) -> list[str]:
    frases = []
    for m in _MODALES:
        frases += [f"{tercero} {m} {cadena}", f"{tercero}, por tanto, {m} {cadena}", f"{tercero}, por su parte, {m} {cadena}",
                   f"{tercero} considera que {m} {cadena}"]
        if m in _MODALES_CON_SUJETO_POSPUESTO:
            frases.append(f"{m} {tercero} {cadena}")
    return frases


def _conclusiones_de_tercero(frases_de) -> list[tuple[str, str]]:
    casos = []
    for resultado, infinitivo, tercero_verbo, complementos in _DECISIONES_Y_VERBO_DE_TERCERO:
        cabeza = f"Corresponde {infinitivo} el fallo y amparar el derecho a la salud"
        for complemento in complementos:
            for tercero in _TERCEROS:
                for cadena in _cadenas_de_tercero(tercero_verbo, complemento):
                    for frase in frases_de(tercero, cadena):
                        for union in _UNIONES_CON_EL_ANUNCIO_DEL_DESPACHO:
                            casos.append((resultado, f"{cabeza}{union}{_en_mayuscula_inicial(frase)}."))
    return casos


_CONCLUSIONES_DE_TERCERO_IMPERSONALES = _conclusiones_de_tercero(_frases_de_tercero_impersonales)
_CONCLUSIONES_DE_TERCERO_CON_MODAL = _conclusiones_de_tercero(_frases_de_tercero_con_modal)


@pytest.mark.parametrize(
    ("familia", "casos", "tamano"),
    [
        ("impersonal con dativo, atribución o «que» ajeno", _CONCLUSIONES_DE_TERCERO_IMPERSONALES, 37044),
        ("«deber», «ha de» o «habrá de» con sujeto ajeno", _CONCLUSIONES_DE_TERCERO_CON_MODAL, 33264),
    ],
)
def test_coherencia_decision_ningun_tercero_anuncia_el_resultado_tabla_exhaustiva(familia, casos, tamano):
    assert len(casos) == tamano, familia
    falsos = [c for resultado, c in casos if lint.coherencia_decision(_caso(conclusion=c), _decision(resultado, "AMPARAR")) != []]
    assert falsos == [], f"{len(falsos)} falsos BLOQUEA de {len(casos)} ({familia}); por ejemplo: {falsos[:3]}"


_LEADS_DEL_DESPACHO = (
    "", "Por lo expuesto, ", "En consecuencia, ", "A la luz de lo expuesto, ", "De acuerdo con lo anterior, ",
    "Dado que la decisión de primera instancia desconoció el derecho, ", "En cuanto al derecho a la salud, ",
)
_DESPACHOS = ("El Despacho", "La Sala", "Este Juzgado")
_VERBOS_QUE_DECIDEN = ("decide", "resuelve", "dispone")


def _cadenas_del_despacho(ok: str, contrario: str) -> list[str]:
    return [
        f"{contrario} el fallo de primera instancia",
        f"amparar el derecho a la salud y {contrario} la sentencia",
        f"amparar el derecho a la salud, {contrario} el fallo",
        f"amparar el derecho a la salud y, en su lugar, {contrario} la decisión",
        f"{ok} el numeral primero, amparar el derecho y {contrario} el numeral segundo",
    ]


def _frases_del_despacho_impersonales(cadena: str) -> list[str]:
    frases = [f"{lead}{d} {cadena}" for d in _IMPERSONALES for lead in _LEADS_DEL_DESPACHO]
    for d in _IMPERSONALES_CON_DATIVO:
        frases += [f"A este Despacho le {d} {cadena}", f"Al Despacho le {d} {cadena}", f"A esta Sala le {d} {cadena}"]
    return frases


def _frases_del_despacho_con_modal(cadena: str) -> list[str]:
    frases = []
    for m in _MODALES:
        for d in _DESPACHOS:
            frases += [f"{d} {m} {cadena}", f"{d} considera que {m} {cadena}", f"{d}, por tanto, {m} {cadena}"]
        frases += [f"Por lo expuesto, {m} {cadena}", f"En consecuencia, {m} {cadena}", f"Así las cosas, por lo tanto, {m} {cadena}"]
    return frases


def _frases_del_despacho_que_decide(cadena: str) -> list[str]:
    return [f"{d} {v} {cadena}" for d in _DESPACHOS for v in _VERBOS_QUE_DECIDEN]


def _conclusiones_del_despacho(frases_de) -> list[tuple[str, str, str]]:
    casos = []
    for resultado, infinitivo, contrario, _ in _DECISIONES_Y_VERBO_DE_TERCERO:
        otro = "CONFIRMAR" if resultado == "REVOCAR" else "REVOCAR"
        for cadena in _cadenas_del_despacho(infinitivo, contrario):
            for frase in frases_de(cadena):
                casos.append((resultado, otro, f"{_en_mayuscula_inicial(frase)}."))
    return casos


@pytest.mark.parametrize(
    ("familia", "casos", "tamano"),
    [
        ("impersonal sin otro actor", _conclusiones_del_despacho(_frases_del_despacho_impersonales), 750),
        ("«deber», «ha de» o «habrá de» con el Despacho como sujeto", _conclusiones_del_despacho(_frases_del_despacho_con_modal), 1200),
        ("«el Despacho decide…»", _conclusiones_del_despacho(_frases_del_despacho_que_decide), 90),
    ],
)
def test_coherencia_decision_todo_anuncio_del_despacho_se_detecta_tabla_exhaustiva(familia, casos, tamano):
    assert len(casos) == tamano, familia
    perdidos = []
    for resultado, otro, conclusion in casos:
        msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, "AMPARAR"))
        if not any(m.startswith("BLOQUEA: ") and f"anuncia {otro} como el resultado" in m for m in msgs):
            perdidos.append(conclusion)
    assert perdidos == [], f"{len(perdidos)} sin detectar de {len(casos)} ({familia}); por ejemplo: {perdidos[:3]}"


# Las oraciones literales de las revisiones anteriores de este PR (REVOCAR/AMPARAR): ninguna debe bloquear.
_CABEZA = "Corresponde revocar el fallo y amparar el derecho a la salud"
_REPRODUCCIONES_DE_LAS_REVISIONES = [
    # «deber» con inciso y siglas
    *(f"{_CABEZA}; {s}{i} deberá confirmar la cita." for s in ("la EPS", "la entidad accionada", "las demás entidades", "el hospital", "la Nueva EPS S.A.")
      for i in (", por tanto,", ", en consecuencia,", ", además,", ", por su parte,", ", desde ahora,")),
    f"{_CABEZA}; la Nueva EPS S.A.S. debe confirmar la cita.",
    f"{_CABEZA}; la E.P.S. deberá confirmar la cita.",
    f"{_CABEZA}; la Dra. deberá confirmar la cita.",
    # verbos de orden a un tercero
    f"{_CABEZA}, ordenando a la EPS autorizar el procedimiento y confirmar la fecha de la cita.",
    "Corresponde revocar el fallo, amparar el derecho a la salud y ordenar a la EPS entregar el medicamento y confirmar su entrega.",
    f"El Despacho debe revocar el fallo y amparar el derecho a la salud, ordenando a la EPS programar la cirugía y confirmar la fecha por escrito.",
    # «ha de», «habrá de» y el dativo
    f"{_CABEZA}; la EPS habrá de confirmar la cita.",
    f"{_CABEZA}; la EPS ha de confirmar la cita médica.",
    f"{_CABEZA}; la accionada habrá de confirmar la fecha.",
    f"{_CABEZA}; a la accionada le corresponde confirmar la cita.",
    f"{_CABEZA}; a la entidad accionada corresponde confirmar la autorización.",
    f"{_CABEZA}; a la EPS le corresponde programar la cirugía y confirmar la fecha.",
    f"{_CABEZA}. Corresponde a la EPS programar y confirmar la cita.",
    f"{_CABEZA}; la Nueva EPS S.A. ha de confirmar la cita.",
    f"{_CABEZA}; respecto de la EPS, procede confirmar la cita.",
    f"{_CABEZA}; frente a la EPS, es necesario confirmar la cita.",
    # un verbo de orden a un tercero antes del «confirmar» sin «que» ni verbo de orden
    f"{_CABEZA}, para lo cual la EPS deberá autorizar y programar la cirugía y confirmar la fecha.",
    f"{_CABEZA}, debiendo la EPS programar la cirugía y confirmar la fecha.",
    f"{_CABEZA}, así como garantizar la prestación del servicio y confirmar la cita.",
    f"{_CABEZA}, con el fin de garantizar el tratamiento y confirmar la cita.",
    f"{_CABEZA}, y garantizar el suministro del medicamento y confirmar su entrega.",
    f"{_CABEZA}, a efectos de autorizar el procedimiento y confirmar la cita.",
    f"{_CABEZA}, con lo cual se podrá autorizar el procedimiento y confirmar la cita.",
    f"{_CABEZA}, para garantizar el acceso al procedimiento y confirmar la cita.",
]


def test_coherencia_decision_reproducciones_de_las_revisiones_no_bloquean():
    assert len(_REPRODUCCIONES_DE_LAS_REVISIONES) == 49
    falsos = [c for c in _REPRODUCCIONES_DE_LAS_REVISIONES if lint.coherencia_decision(_caso(conclusion=c), _decision("REVOCAR", "AMPARAR")) != []]
    assert falsos == []


@pytest.mark.parametrize(
    "conclusion",
    [
        "La EPS sostiene que procede confirmar el fallo, pero corresponde revocarlo y amparar el derecho a la salud.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la EPS procederá a confirmar la sentencia de primera instancia.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, y la EPS, por tanto, procederá a confirmar el fallo.",
        "Aunque la EPS sostiene que procede confirmar el fallo, corresponde revocar la sentencia y amparar el derecho a la salud.",
        "Según la impugnante, corresponde confirmar la sentencia; sin embargo, corresponde revocar el fallo y amparar el derecho a la salud.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; en criterio del a quo, procede confirmar su decisión.",
        "El a quo consideró que corresponde confirmar su propia decisión; corresponde revocar el fallo y amparar el derecho a la salud.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; la accionada considera que debe confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, y rechazar la tesis de la EPS según la cual procede confirmar el fallo.",
    ],
)
def test_coherencia_decision_la_postura_de_un_tercero_no_es_el_anuncio_del_despacho(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


# Una atribución o un dativo que no abre la oración: un inciso cerrado con coma justo antes del disparador («…, aunque, según
# la EPS, procede confirmar el fallo»). El objeto judicial es el caso natural de las partes: piden «confirmar el fallo».
@pytest.mark.parametrize(
    "conclusion",
    [
        "El Despacho considera que debe revocar el fallo y amparar el derecho a la salud, a pesar de que, según la EPS, procede confirmar el fallo.",
        "El Despacho considera que debe revocar el fallo y amparar el derecho a la salud, a pesar de que, para la EPS, procede confirmar la sentencia.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, aunque, según la EPS, corresponde confirmar la sentencia de primera instancia.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, mientras que a juicio de la EPS, corresponde negar la tutela.",
        "El Despacho revocará el fallo y amparará el derecho. A criterio de la EPS, hay que confirmar el fallo; a criterio del Despacho, no.",
        # la misma atribución abriendo la oración, tras «. » o «; »
        "Corresponde revocar el fallo y amparar el derecho a la salud. A criterio de la EPS, hay que confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; a criterio del accionado, corresponde confirmar la sentencia.",
    ],
)
def test_coherencia_decision_una_atribucion_entre_comas_antes_del_disparador_no_es_del_despacho(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


_ATRIBUCIONES_DE_INCISO = (
    "a criterio de la EPS", "según la EPS", "para la EPS", "a juicio de la EPS", "en opinión de la EPS", "de acuerdo con la EPS",
    "conforme a la EPS", "en criterio del accionado", "a criterio del accionado",
)
_UNIONES_DE_INCISO = (", aunque, ", ", mientras que ", ", a pesar de que, ", ", si bien, ", ", pero, ", ", ya que ", ", dado que, ", ", y, ", ", pues, ")
_CONCLUSIONES_CON_INCISO_DE_TERCERO = [
    (resultado, f"Corresponde {infinitivo} el fallo y amparar el derecho a la salud{union}{atribucion}, {d} {contrario} {objeto}.")
    for resultado, infinitivo, contrario in (("REVOCAR", "revocar", "confirmar"), ("CONFIRMAR", "confirmar", "revocar"))
    for union in _UNIONES_DE_INCISO
    for atribucion in _ATRIBUCIONES_DE_INCISO
    for d in ("corresponde", "procede", "hay que")
    for objeto in ("el fallo", "la sentencia de primera instancia")
]


def test_coherencia_decision_ningun_inciso_de_tercero_con_objeto_judicial_anuncia_el_resultado():
    assert len(_CONCLUSIONES_CON_INCISO_DE_TERCERO) == 972
    falsos = [c for r, c in _CONCLUSIONES_CON_INCISO_DE_TERCERO if lint.coherencia_decision(_caso(conclusion=c), _decision(r, "AMPARAR")) != []]
    assert falsos == [], f"{len(falsos)} falsos BLOQUEA; por ejemplo: {falsos[:3]}"


# --- «tercero + verbo de decir + que + inciso» ----------------------------------------------------------------------------
# «La EPS sostiene que, en este caso, procede confirmar el fallo»: el «que» es del tercero aunque lo siga un inciso cerrado con
# coma, y el Despacho que dice «considera que, en este caso, procede…» sigue siendo quien anuncia. Vocabulario propio, distinto
# del de lint.py y del de las tablas anteriores: el defecto de esta familia se escapó dos veces porque las tablas se construían
# con las mismas palabras que la guarda.
_TERCEROS_QUE_DICEN = (
    "El Ministerio Público", "La Procuraduría", "La IPS", "El apoderado de la accionada", "La impugnante", "El vinculado",
    "La aseguradora", "La Superintendencia de Salud",
)
_VERBOS_DE_DECIR_CON_QUE = ("sostiene que", "conceptúa que", "alega que", "afirma que", "insiste en que", "argumenta que")
_INCISOS_TRAS_QUE = (
    "en este caso", "en su sentir", "a su juicio", "en principio", "de entrada", "por lo visto",
    "en este caso, a su juicio", "como ya se dijo, y por lo visto", "en el presente asunto concreto y bajo las circunstancias descritas",
    "por lo que consta en el expediente", "en lo que a este caso respecta",  # un «que» relativo dentro del inciso no lo corta
)
_DISPARADORES_DE_LA_CLAUSULA_DEL_QUE = ("procede", "corresponde", "hay que", "se impone", "debe")
_OBJETOS_JUDICIALES = (
    ("REVOCAR", "revocar", "confirmar", ("el fallo", "la providencia impugnada")),
    ("CONFIRMAR", "confirmar", "revocar", ("la sentencia de primera instancia", "la decisión del a quo")),
)
_CIERRE_DEL_DESPACHO = "Por ello, el Despacho {futuro} el fallo y amparará el derecho a la salud."
_FUTURO_DE = {"revocar": "revocará", "confirmar": "confirmará"}


def _conclusiones_con_que_e_inciso(sujetos, verbos, incisos, disparadores) -> list[tuple[str, str]]:
    casos = []
    for resultado, infinitivo, contrario, objetos in _OBJETOS_JUDICIALES:
        cierre = _CIERRE_DEL_DESPACHO.format(futuro=_FUTURO_DE[infinitivo])
        for sujeto in sujetos:
            for verbo in verbos:
                for inciso in incisos:
                    for d in disparadores:
                        for objeto in objetos:
                            casos.append((resultado, f"{sujeto} {verbo}, {inciso}, {d} {contrario} {objeto}. {cierre}"))
    return casos


_CONCLUSIONES_DE_TERCERO_CON_QUE_E_INCISO = _conclusiones_con_que_e_inciso(
    _TERCEROS_QUE_DICEN, _VERBOS_DE_DECIR_CON_QUE, _INCISOS_TRAS_QUE, _DISPARADORES_DE_LA_CLAUSULA_DEL_QUE
)
_CONCLUSIONES_DEL_DESPACHO_CON_QUE_E_INCISO = _conclusiones_con_que_e_inciso(
    ("El Despacho", "Este Juzgado", "La Sala"),
    ("considera que", "estima que", "advierte que", "observa que", "concluye que", "entiende que"),
    _INCISOS_TRAS_QUE,
    _DISPARADORES_DE_LA_CLAUSULA_DEL_QUE[:4],  # «debe» con inciso tras el «que» del Despacho es un falso negativo aceptado
)


def test_coherencia_decision_ningun_tercero_con_que_e_inciso_anuncia_el_resultado():
    assert len(_CONCLUSIONES_DE_TERCERO_CON_QUE_E_INCISO) == 10560
    falsos = [c for r, c in _CONCLUSIONES_DE_TERCERO_CON_QUE_E_INCISO if lint.coherencia_decision(_caso(conclusion=c), _decision(r, "AMPARAR")) != []]
    assert falsos == [], f"{len(falsos)} falsos BLOQUEA; por ejemplo: {falsos[:3]}"


def test_coherencia_decision_todo_anuncio_del_despacho_con_que_e_inciso_se_detecta():
    assert len(_CONCLUSIONES_DEL_DESPACHO_CON_QUE_E_INCISO) == 3168
    sin_detectar = [
        c for r, c in _CONCLUSIONES_DEL_DESPACHO_CON_QUE_E_INCISO
        if not any("anuncia" in m for m in lint.coherencia_decision(_caso(conclusion=c), _decision(r, "AMPARAR")))
    ]
    assert sin_detectar == [], f"{len(sin_detectar)} sin detectar; por ejemplo: {sin_detectar[:3]}"


@pytest.mark.parametrize(
    "conclusion",
    [
        # las tres frases con las que se encontró el defecto (el cierre es la decisión del Despacho: revocar y amparar)
        "La EPS sostiene que, en este caso, procede confirmar el fallo. Por ello, el Despacho revocará el fallo y amparará el derecho a la salud.",
        "El Ministerio Público conceptúa que, en su sentir, procede confirmar la sentencia. Por ello, el Despacho revocará el fallo y amparará el derecho a la salud.",
        "El Despacho observa que la EPS cree que corresponde confirmar el fallo; no obstante, revocará y amparará.",
        # el «que» ajeno más cercano manda, aunque antes haya otro del Despacho
        "El Despacho observa que la EPS cree que, en este caso, corresponde confirmar el fallo; no obstante, revocará y amparará.",
        "El Despacho considera que la EPS alega que, a su juicio, procede confirmar la sentencia, pero revocará el fallo y amparará el derecho.",
        # varios incisos tras el «que», o uno largo
        "La EPS sostiene que, en este caso, a su juicio, procede confirmar el fallo. Por ello, el Despacho revocará el fallo y amparará el derecho a la salud.",
        "La EPS sostiene que, en el presente asunto concreto, y a la luz de la prueba, procede confirmar el fallo; el Despacho revocará y amparará.",
        # un «que» relativo dentro del inciso no es el «que» de la atribución
        "La EPS sostiene que, por lo que consta en el expediente, procede confirmar el fallo. Por ello, el Despacho revocará y amparará el derecho.",
        "El Ministerio Público conceptúa que, según lo que alegó la parte, corresponde confirmar la sentencia; el Despacho revocará y amparará.",
        "El Despacho observa que la EPS cree que, en lo que a este caso respecta, corresponde confirmar el fallo; no obstante, revocará y amparará.",
        # sin inciso (ya pasaba en main)
        "La EPS sostiene que procede confirmar el fallo. Por ello, el Despacho revocará el fallo y amparará el derecho a la salud.",
    ],
)
def test_coherencia_decision_el_que_de_un_tercero_con_inciso_no_es_el_anuncio_del_despacho(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        # el «que» es del Despacho, de una oración impersonal o de una locución con la que abre el Despacho: el inciso no lo oculta
        "El Despacho considera que, en este caso, procede confirmar el fallo y amparar el derecho a la salud.",
        "Este Despacho estima que, en consecuencia, corresponde confirmar la sentencia y amparar el derecho a la salud.",
        "El Despacho advierte que, por lo expuesto, hay que confirmar el fallo y amparar el derecho a la salud.",
        "El Despacho considera que, por lo que consta en el expediente, procede confirmar el fallo y amparar el derecho a la salud.",
        "Es claro que, en este caso, procede confirmar el fallo y amparar el derecho a la salud.",
        "Resulta evidente que, a esta altura, corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Se concluye que, a la luz del expediente, procede confirmar la sentencia y amparar el derecho a la salud.",
        "Dado que, en este caso, la EPS incumplió, corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Teniendo en cuenta que, en este caso, la EPS incumplió, corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Corresponde revocar el fallo y amparar el derecho a la salud; a pesar de que, en consecuencia, procede confirmar la sentencia.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, mientras que, a juicio del Despacho, corresponde confirmar el fallo.",
        # un tercero que habló antes no oculta lo que dice el Despacho después
        "La EPS sostiene que no procede el amparo. El Despacho considera que, en este caso, procede confirmar el fallo y amparar el derecho.",
    ],
)
def test_coherencia_decision_el_que_del_despacho_con_inciso_sigue_siendo_el_anuncio_del_despacho(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs), conclusion


@pytest.mark.parametrize(
    "conclusion",
    [
        # Residuo aceptado que sí bloquea: la guarda ve a través de incisos de hasta 80 caracteres sin signo de fin de oración;
        # un inciso más largo, o que contiene un punto o un punto y coma, deja de verse y la cláusula se lee como del Despacho.
        "La EPS sostiene que, en el presente asunto concreto y bajo las circunstancias descritas en el expediente allegado por las partes, procede confirmar el fallo.",
        "La EPS sostiene que, en este caso; a su juicio, procede confirmar el fallo.",
    ],
)
def test_coherencia_decision_residuo_aceptado_que_bloquea_un_inciso_tras_el_que_demasiado_largo(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion + " Por ello, el Despacho revocará y amparará."), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs), conclusion


@pytest.mark.parametrize(
    "conclusion",
    [
        # Un inciso que es solo un conectivo no es una atribución: el sujeto sigue siendo el del propio Despacho.
        "Corresponde revocar el fallo y amparar el derecho a la salud, y, por lo expuesto, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, aunque, en este caso, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, a pesar de que, en consecuencia, procede confirmar la sentencia.",
        # La atribución es del propio Despacho o es una locución, no de un tercero.
        "Corresponde revocar el fallo y amparar el derecho a la salud, mientras que, a juicio del Despacho, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, aunque, a la luz de la sentencia, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, a esta altura, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, y, de acuerdo con el material probatorio, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, y, según el expediente, procede confirmar la sentencia.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, pero, al caso concreto, corresponde confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, aunque, a mi juicio, hay que confirmar el fallo.",
        "Corresponde revocar el fallo y amparar el derecho a la salud, aunque, a criterio del suscrito, procede confirmar el fallo.",
        # Una cláusula anterior que nombra a otro no rige al disparador si no es el inciso que lo precede.
        "Como el a quo negó el amparo a la accionante, corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Como el a quo negó el amparo a la accionante, y por lo expuesto, corresponde confirmar el fallo.",
    ],
)
def test_coherencia_decision_un_inciso_que_no_es_de_un_tercero_no_excusa_el_anuncio_del_despacho(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs), conclusion


@pytest.mark.parametrize(
    ("resultado", "conclusion"),
    [
        # Residuo aceptado que sí bloquea (documentado en docs/CONTRATO_IMPLEMENTACION.md): el inciso que precede al disparador
        # empieza por otra cosa («para lo cual…») y la atribución va después, o es un delimitador de alcance con objeto judicial.
        ("CONFIRMAR", "Corresponde confirmar el fallo y amparar el derecho a la salud, para lo cual según la ARL, procede revocar la sentencia."),
        ("CONFIRMAR", "Corresponde confirmar el fallo y amparar el derecho a la salud; en cuanto a la IPS, corresponde revocar la sentencia."),
    ],
)
def test_coherencia_decision_residuo_aceptado_que_bloquea_atribucion_lejana_o_delimitador_de_alcance(resultado, conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, "AMPARAR"))
    assert any("anuncia REVOCAR como el resultado" in m for m in msgs), conclusion


@pytest.mark.parametrize(
    "conclusion",
    [
        "El Despacho considera que corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Se concluye que procede confirmar la sentencia y amparar el derecho a la salud.",
        "Es claro que procede confirmar el fallo y amparar el derecho a la salud.",
        "A este Despacho le corresponde confirmar la sentencia de primera instancia y amparar el derecho a la salud.",
        "Como el a quo negó el amparo a la accionante, corresponde confirmar el fallo y amparar el derecho a la salud.",
        "En el caso concreto, con base en el material probatorio, corresponde confirmar el fallo y amparar el derecho.",
        "Procede amparar el derecho a la salud y confirmar en su integridad la providencia impugnada.",
        "Corresponde confirmar y amparar el derecho a la salud.",
    ],
)
def test_coherencia_decision_el_anuncio_del_despacho_con_un_antecedente_o_incidental_sigue_bloqueando(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs)


@pytest.mark.parametrize(
    ("sujeto_o_inicio", "bloquea"),
    [
        ("la cita se debe confirmar", False),
        ("la sentencia se debe confirmar", False),
        ("Se debe confirmar el fallo", True),
        ("Por lo expuesto, se debe confirmar el fallo", True),
        ("Dado que la EPS negó la cita, se debe confirmar el fallo", True),
        ("Por ello se debe confirmar el fallo", True),
    ],
)
def test_coherencia_decision_se_debe_con_un_sustantivo_delante_es_una_pasiva_con_sujeto_y_no_un_impersonal(sujeto_o_inicio, bloquea):
    conclusion = f"Corresponde revocar el fallo y amparar el derecho a la salud. {sujeto_o_inicio}."
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert any("anuncia CONFIRMAR como el resultado" in m for m in msgs) is bloquea


@pytest.mark.parametrize(
    ("resultado", "infinitivo", "contrario", "objeto", "bloquea"),
    [
        ("REVOCAR", "revocar", "confirmar", "el fallo de primera instancia", True),
        ("REVOCAR", "revocar", "confirmar", "la sentencia proferida por el Juzgado Tercero Civil el 3 de mayo de 2023", True),
        ("REVOCAR", "revocar", "confirmar", "en su integridad el fallo", True),
        ("REVOCAR", "revocar", "confirmar", "parcialmente la providencia", True),
        ("REVOCAR", "revocar", "confirmar", "la decisión del a quo", True),
        ("REVOCAR", "revocar", "confirmar", "la cita con la EPS", False),
        ("REVOCAR", "revocar", "confirmar", "la fecha de la cirugía", False),
        ("REVOCAR", "revocar", "confirmar", "su entrega", False),
        ("REVOCAR", "revocar", "confirmar", "la decisión de la EPS", False),
        ("REVOCAR", "revocar", "confirmar", "la sentencia de Sura", False),
        ("CONFIRMAR", "confirmar", "revocar", "el fallo de primera instancia", True),
        ("CONFIRMAR", "confirmar", "revocar", "la glosa", False),
        ("CONFIRMAR", "confirmar", "revocar", "la autorización previa", False),
        ("CONFIRMAR", "confirmar", "revocar", "la decisión de la entidad", False),
    ],
)
@pytest.mark.parametrize("disparador", ["Corresponde", "Hay que", "El Despacho decide", "Por lo expuesto, debe"])
def test_coherencia_decision_confirmar_o_revocar_solo_son_el_resultado_si_recaen_sobre_una_decision_judicial(
    disparador, resultado, infinitivo, contrario, objeto, bloquea
):
    conclusion = f"{disparador} {infinitivo} el fallo y amparar el derecho a la salud; {disparador.lower()} {contrario} {objeto}."
    otro = "CONFIRMAR" if resultado == "REVOCAR" else "REVOCAR"
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision(resultado, "AMPARAR"))
    assert any(f"anuncia {otro} como el resultado" in m for m in msgs) is bloquea, conclusion


@pytest.mark.parametrize(
    "conclusion",
    [
        "Corresponde revocar el fallo y amparar el derecho a la salud y confirmar que la EPS cumpla lo ordenado.",
        "El Despacho debe revocar el fallo y amparar el derecho a la salud y confirmar, además, que la EPS cumpla.",
    ],
)
def test_coherencia_decision_confirmar_que_comprueba_un_hecho_y_no_anuncia_el_resultado(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR")) == []


@pytest.mark.parametrize(
    "conclusion",
    [
        # Falsos negativos aceptados (documentados en docs/CONTRATO_IMPLEMENTACION.md): sin un sujeto ni un objeto que
        # permitan afirmar que es el Despacho quien decide, el infinitivo no se examina.
        "Corresponde confirmarlo y amparar el derecho a la salud.",
        "Corresponde amparar el derecho a la salud y confirmarla.",
        "A la EPS corresponde confirmar el fallo y amparar el derecho a la salud.",
        "Corresponde amparar el derecho a la salud, garantizando la atención, y confirmar el fallo.",
        "Corresponde amparar el derecho a la salud y, para garantizar la atención, confirmar el fallo.",
        "Corresponde amparar el derecho a la salud, que la EPS reclama, y confirmar el fallo.",
        # el Despacho con una aposición entre comas no se reconoce como el sujeto del «que», con o sin inciso tras él
        "La Sala, por mayoría, entiende que procede confirmar el fallo y amparar el derecho a la salud.",
        "La Sala, por mayoría, entiende que, en este caso, procede confirmar el fallo y amparar el derecho a la salud.",
    ],
)
def test_coherencia_decision_falsos_negativos_aceptados_no_se_examinan(conclusion):
    msgs = lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "AMPARAR"))
    assert not any("anuncia" in m and "no anuncia" not in m for m in msgs)


# --- #149: formas conjugadas de «negar» ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "conclusion",
    [
        "Se revocará el fallo y se negarán las pretensiones de la acción de tutela.",
        "Se revocará la decisión de primera instancia y, en su lugar, se negarán las pretensiones.",
        "Se revocará el fallo y se negarían las pretensiones.",
        "Se revocará el fallo y se negará el amparo solicitado.",
        "Corresponde revocar la sentencia y negar el amparo.",
        "Se revocará el fallo, por lo que corresponde negarse a conceder lo pedido.",
        "Se revocará el fallo y se negaron las pretensiones.",
    ],
)
def test_coherencia_decision_reconoce_todas_las_formas_de_negar(conclusion):
    assert lint.coherencia_decision(_caso(conclusion=conclusion), _decision("REVOCAR", "NEGAR")) == []


def test_coherencia_decision_mensaje_de_negar_muestra_las_formas_completas():
    msgs = lint.coherencia_decision(_caso(conclusion="Se revocará el fallo y se declarará improcedente."), _decision("REVOCAR", "NEGAR"))
    texto = " ".join(msgs)
    assert "«negar»" in texto and "«negarán»" in texto and "«negarían»" in texto and "«neg…»" not in texto


def test_coherencia_decision_neg_sigue_sin_coincidir_con_negocio_ni_negligencia():
    for palabra in ("negocio", "negativo", "negligencia", "negociación"):
        msgs = lint.coherencia_decision(_caso(conclusion=f"Se revocará el fallo por el {palabra}."), _decision("REVOCAR", "NEGAR"))
        assert any("NEGAR" in m for m in msgs), palabra


TEXTO_CITA = (
    "La carencia actual de objeto por hecho superado se configura cuando desaparece la afectación que dio origen "
    "a la acción de tutela y la pretensión queda satisfecha por una conducta voluntaria de la entidad accionada."
)


def _cita_con_texto(id_: str = "c1", estado: str = "ok") -> CitaVerificada:
    return _cv(id_, "T-200 de 2022", estado).model_copy(update={"texto_citado": TEXTO_CITA})


def test_cita_verificada_en_caso_con_marcador_ok_no_bloquea():
    caso = _caso("El hecho consta; por eso el reparo no prospera, como lo explicó la [[CITA:c1]].")
    assert lint.cita_verificada_en_caso(caso, CITAS, False) == []


def test_cita_verificada_en_caso_sin_marcador_bloquea_con_la_regla_y_lista_las_citas_utilizables():
    msgs = lint.cita_verificada_en_caso(_caso("El reparo no prospera por las razones expuestas."), CITAS, False)
    assert len(_bloquea(msgs)) == len(msgs) == 1
    assert "Ningún párrafo del caso concreto contiene un marcador" in msgs[0] and "[[CITA:id]]" in msgs[0] and "no lo transcriba" in msgs[0]
    assert "[[CITA:c1]]" in msgs[0] and "T-200 de 2022" in msgs[0]
    assert "c2" not in msgs[0] and "c3" not in msgs[0]


def test_cita_verificada_en_caso_el_marcador_debe_estar_en_los_parrafos():
    caso = _caso("Sin marcador.", problema="Corresponde determinar [[CITA:c1]].", conclusion="Se revocará [[CITA:c1]].")
    assert len(_bloquea(lint.cita_verificada_en_caso(caso, CITAS, False))) == 1


def test_cita_verificada_en_caso_una_cita_en_alerta_solo_cuenta_si_no_se_verifica_la_relatoria():
    caso = _caso("Esto se apoya en la [[CITA:c2]].")
    msgs = lint.cita_verificada_en_caso(caso, CITAS, False)
    assert len(_bloquea(msgs)) == 1 and "[[CITA:c1]]" in msgs[0] and "[[CITA:c2]]" not in msgs[0]
    assert lint.cita_verificada_en_caso(caso, CITAS, True) == []


def test_cita_verificada_en_caso_un_marcador_rechazado_no_cuenta():
    caso = _caso("Esto se apoya en la [[CITA:c3]].")
    assert len(_bloquea(lint.cita_verificada_en_caso(caso, CITAS, True))) == 1


def test_cita_verificada_en_caso_sin_citas_utilizables_alerta_y_no_bloquea():
    caso = _caso("Sin marcador.")
    msgs = lint.cita_verificada_en_caso(caso, _cvs("rechazada", "alerta"), False)
    assert len(_alerta(msgs)) == len(msgs) == 1 and "ninguna cita verificada" in msgs[0]
    assert lint.cita_verificada_en_caso(caso, [], True)[0].startswith("ALERTA: ")
    assert len(_bloquea(lint.cita_verificada_en_caso(caso, _cvs("rechazada", "alerta"), True))) == 1


def _ing_con(*textos: str) -> Ingesta:
    return Ingesta(documentos=[_doc(f"2a-{i:03d}", t) for i, t in enumerate(textos, 1)])


def test_pasajes_entre_comillas_del_expediente_no_bloquean():
    caso = _caso(
        "La accionante afirma que «desde el mes de enero la entidad no le ha entregado el medicamento formulado» "
        "y el Despacho lo tiene por cierto."
    )
    assert lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO), CITAS) == []


def test_pasajes_entre_comillas_cortos_o_terminos_no_bloquean():
    caso = _caso("Se trata de un «perjuicio irremediable» y de la «carencia actual de objeto» alegada.")
    assert lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO), CITAS) == []


@pytest.mark.parametrize(
    "abre,cierra",
    [("«", "»"), ("“", "”"), ('"', '"')],
)
def test_pasajes_entre_comillas_que_reproducen_una_cita_bloquean_y_senalan_el_marcador(abre, cierra):
    caso = _caso(f"Como lo dijo la Corte, {abre}{TEXTO_CITA}{cierra}.")
    msgs = lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO), [_cita_con_texto()])
    assert len(_bloquea(msgs)) == len(msgs) == 1
    assert "c1" in msgs[0] and "[[CITA:c1]]" in msgs[0] and "Caso concreto, párrafo 1" in msgs[0]


def test_pasajes_entre_comillas_que_no_constan_en_el_expediente_bloquean():
    caso = _caso(
        "Dijo el juez «la entidad estaba obligada a entregar el insumo sin demora alguna ni condicionamientos» en su fallo."
    )
    msgs = lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO), [_cita_con_texto()])
    assert len(_bloquea(msgs)) == 1 and "no consta en el expediente" in msgs[0] and "[[CITA:id]]" in msgs[0]


def test_pasajes_entre_comillas_de_la_decision_o_de_cualquier_documento_no_bloquean():
    eje = "La entidad no acreditó la autorización del procedimiento y la demora compromete la salud de la accionante"
    caso = _caso(f"Para el Despacho «{eje}», de modo que prospera.", conclusion=f"Se revocará: «{IMPUGNACION[:90]}».")
    assert lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO, IMPUGNACION, eje), CITAS) == []


def test_pasajes_entre_comillas_revisa_problema_y_conclusion_y_limita_los_mensajes():
    inventado = "uno dos tres cuatro cinco seis siete ocho"
    caso = _caso(
        *[f"Texto «{inventado} {i}»." for i in range(8)],
        problema=f"Corresponde «{inventado} p»",
        conclusion=f"Se revocará «{inventado} c»",
    )
    msgs = lint.pasajes_entre_comillas(caso, _ing_con(ESCRITO), CITAS)
    assert len(msgs) == lint.MAX_LINEAS_CITADAS and msgs[0].startswith("BLOQUEA: ")
    solo = _caso("Hecho.", problema=f"Corresponde «{inventado} p»", conclusion=f"Se revocará «{inventado} c»")
    campos = " ".join(lint.pasajes_entre_comillas(solo, _ing_con(ESCRITO), CITAS))
    assert "problema jurídico" in campos and "conclusión" in campos


CONCLUSION = (
    "En consecuencia, el Despacho considera que debe revocar el fallo de primera instancia y amparar los derechos "
    "fundamentales al mínimo vital y a la seguridad social de la accionante, ordenando a la entidad que pague las "
    "incapacidades que cumplan los requisitos legales."
)
RELLENO = (
    "El Despacho advierte que la accionante estuvo incapacitada de manera continua desde el veinte de mayo, que la "
    "entidad reconoció las primeras prórrogas y que la última fue rechazada por un defecto en el certificado de "
    "incapacidad expedido por la institución prestadora del servicio, circunstancia que la entidad califica de "
    "insubsanable mientras la afiliada sostiene que depende de la institución y no de ella. "
)


RELLENO_B = (
    "Respecto de la inmediatez, la última negativa de pago ocurrió pocas semanas antes de presentarse el escrito y la "
    "vulneración persiste en el tiempo, lo cual descarta cualquier inactividad; en cuanto a la subsidiariedad, el medio "
    "ordinario ante la Superintendencia carece de idoneidad cuando el subsidio constituye el único ingreso del hogar. "
)


def test_duplicados_con_contencion_detecta_la_repeticion_dentro_de_un_texto_mas_largo():
    largo = RELLENO + RELLENO_B + CONCLUSION
    assert lint.duplicados([largo, CONCLUSION], 0.5) == []
    msgs = lint.duplicados([largo, CONCLUSION], 0.5, contencion=lint.UMBRAL_CONTENCION)
    assert len(_alerta(msgs)) == len(msgs) == 1 and "contención 100%" in msgs[0] and "1 y 2" in msgs[0]


def test_duplicados_con_contencion_no_marca_parrafos_distintos_de_la_misma_causa():
    otro = (
        "En cuanto a la inmediatez, el Despacho encuentra que la tutela se interpuso en un plazo razonable, porque la "
        "última negativa de pago ocurrió pocas semanas antes de la presentación del escrito y la vulneración persiste."
    )
    assert lint.duplicados([RELLENO, otro, CONCLUSION], 0.5, contencion=lint.UMBRAL_CONTENCION) == []


def test_duplicados_sin_contencion_conserva_el_mensaje_y_el_resultado_de_siempre():
    msgs = lint.duplicados([P1, P3, P2], 0.5)
    assert msgs == ["ALERTA: Los párrafos 1 y 3 son casi idénticos (similitud 89%)."]


def test_duplicados_con_etiquetas_nombra_cada_texto():
    msgs = lint.duplicados(
        [P1, P3, P2], 0.5, etiquetas=["el problema jurídico", "el párrafo 1", "la conclusión"]
    )
    assert msgs == ["ALERTA: El problema jurídico y la conclusión son casi idénticos (similitud 89%)."]


def test_duplicados_caso_conclusion_repetida_en_el_ultimo_parrafo_bloquea():
    caso = _caso("Primer argumento distinto sobre la subsidiariedad del reclamo.", RELLENO + CONCLUSION, conclusion=CONCLUSION)
    msgs = lint.duplicados_caso(caso, 0.5)
    assert len(_bloquea(msgs)) == len(msgs) == 1
    assert "último párrafo" in msgs[0] and "párrafo 2" in msgs[0] and "solo en el campo conclusion" in msgs[0]


def test_duplicados_caso_conclusion_repetida_con_poca_similitud_de_jaccard_pero_alta_contencion():
    largo = RELLENO + RELLENO_B + CONCLUSION
    assert lint.duplicados([largo, CONCLUSION], 0.5) == []
    msgs = lint.duplicados_caso(_caso(largo, conclusion=CONCLUSION), 0.5)
    assert len(_bloquea(msgs)) == 1


def test_duplicados_caso_conclusion_repetida_en_otro_parrafo_solo_alerta():
    caso = _caso(RELLENO + CONCLUSION, "Último párrafo con otro contenido sobre el plazo y la inmediatez del reclamo.", conclusion=CONCLUSION)
    msgs = lint.duplicados_caso(caso, 0.5)
    assert len(_alerta(msgs)) == len(msgs) == 1 and "párrafo 1 y la conclusión" in msgs[0]


def test_duplicados_caso_incluye_el_problema_juridico():
    problema = "Corresponde al Despacho determinar si la entidad vulneró el derecho a la salud de la accionante al negar el procedimiento"
    caso = _caso("Argumento previo sobre otra cosa muy distinta del asunto, la inmediatez y el plazo del reclamo.", problema + ", como se verá.", problema=problema)
    msgs = lint.duplicados_caso(caso, 0.5)
    assert len(_alerta(msgs)) == len(msgs) == 1 and "el problema jurídico y el párrafo 2" in msgs[0]


def test_duplicados_caso_textos_distintos_o_sin_parrafos_no_marcan():
    assert lint.duplicados_caso(_caso(RELLENO, conclusion=CONCLUSION), 0.5) == []
    assert lint.duplicados_caso(_caso(conclusion=CONCLUSION), 0.5) == []


def _decision_con(*ordenes: Orden) -> Decision:
    return Decision(accion="decidir", resultado="REVOCAR", sustitutiva="AMPARAR", eje="x", ordenes=list(ordenes))


def _orden(destinatario: str = "la entidad", **kw) -> Orden:
    return Orden(destinatario=destinatario, conducta="pague las incapacidades", **kw)


@pytest.mark.parametrize(
    "texto",
    [
        "La entidad deberá cumplir dentro de las cuarenta y ocho (48) horas hábiles siguientes.",
        "El término de 48 horas resulta proporcional.",
        "Se fija un plazo de cuarenta y ocho horas para cumplir.",
    ],
)
def test_plazos_en_caso_menciona_el_plazo_de_la_orden(texto):
    assert lint.plazos_en_caso(_caso(texto), _decision_con(_orden())) == []


@pytest.mark.parametrize(
    "texto",
    [
        "La entidad debe pagar las incapacidades.",
        "El plazo es de cuarenta y ocho días.",
        "Se otorgan 72 horas para cumplir.",
    ],
)
def test_plazos_en_caso_sin_el_plazo_alerta_y_no_bloquea(texto):
    msgs = lint.plazos_en_caso(_caso(texto), _decision_con(_orden()))
    assert len(_alerta(msgs)) == len(msgs) == 1
    assert "48 horas hábiles" in msgs[0] and "orden 1" in msgs[0] and "alcance y el plazo" in msgs[0]


def test_plazos_en_caso_solo_cuenta_los_parrafos():
    caso = _caso("Sin plazo.", conclusion="Se amparará y la entidad cumplirá en 48 horas.")
    assert len(lint.plazos_en_caso(caso, _decision_con(_orden()))) == 1


def test_plazos_en_caso_solo_ordenar_con_plazo_propio():
    d = _decision_con(
        _orden(verbo="PREVENIR"), _orden(verbo="ADVERTIR"), _orden(mismo_termino=True)
    )
    assert lint.plazos_en_caso(_caso("Nada."), d) == []
    assert lint.plazos_en_caso(_caso("Nada."), _decision_con()) == []


def test_plazos_en_caso_unidades_singular_y_dias():
    uno = _decision_con(_orden(plazo={"n": 1, "unidad": "dias_habiles"}))
    assert lint.plazos_en_caso(_caso("Cumplirá en un (1) día hábil."), uno) == []
    assert "1 día hábil" in lint.plazos_en_caso(_caso("Nada."), uno)[0]
    cinco = _decision_con(_orden(plazo={"n": 5, "unidad": "dias"}))
    assert lint.plazos_en_caso(_caso("Dentro de cinco (5) días siguientes."), cinco) == []
    assert lint.plazos_en_caso(_caso("Dentro de 5 horas."), cinco)


def test_plazos_en_caso_agrupa_las_ordenes_con_el_mismo_plazo():
    d = _decision_con(_orden("la entidad uno"), _orden("la entidad dos"), _orden("la entidad tres", plazo={"n": 3, "unidad": "dias"}))
    msgs = lint.plazos_en_caso(_caso("Nada."), d)
    assert len(msgs) == 2
    assert "órdenes 1 y 2" in msgs[0] and "48 horas hábiles" in msgs[0]
    assert "orden 3" in msgs[1] and "3 días" in msgs[1]
