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
        "pese a las múltiples solicitudes verbales x y"
    )
    cumple = lint.anclas_literales(_apertura([_ev("2a-001", casi)]), ing)
    assert cumple == []
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
        numero=numero, anio=anio, texto_citado="x", estado=estado,
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
