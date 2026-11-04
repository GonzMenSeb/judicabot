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
    Doc,
    DisposicionReparo,
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
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "Se revocará para declarar la carencia actual de objeto."),
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
