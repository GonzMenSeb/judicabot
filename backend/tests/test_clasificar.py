from __future__ import annotations

import pytest

from tutela2.clasificar import clasificar, resolver_caso
from tutela2.models import Doc, Pagina

PREFIJO = "05001408803320270000100"[:21]
CUI = PREFIJO + "00"
OTRO_CUI = "76001310300820150054300"


def doc(texto: str | list[str], nombre: str = "001.pdf", doc_id: str = "1a-001") -> Doc:
    paginas = [texto] if isinstance(texto, str) else texto
    return Doc(
        doc_id=doc_id,
        ruta=nombre,
        nombre=nombre,
        instancia="1a",
        rol="otro",
        sha256=doc_id,
        paginas=[
            Pagina(n=i, texto=t, sin_texto=len(t) < 30)
            for i, t in enumerate(paginas, 1)
        ],
    )


def rol(texto: str | list[str], nombre: str = "001.pdf") -> str:
    return clasificar(doc(texto, nombre))[0]


ACTA = """REPÚBLICA DE COLOMBIA Página 1 RAMA JUDICIAL ACTA INDIVIDUAL DE REPARTO Fecha: 9/02/2027 8:12:44 a. m.
NÚMERO RADICACIÓN: {rad} CLASE PROCESO: {clase} NÚMERO DESPACHO: 003 SECUENCIA: 1
REPARTIDO AL DESPACHO: JUZGADO MUNICIPAL PENAL 033 MEDELLIN
CÉDULA DE CIUDADANIA 12345678 MARIA PRUEBA DEMANDANTE/ACCIONANTE"""

ESCRITO = """Medellín, 9 de febrero de 2027
Señor JUEZ CONSTITUCIONAL (REPARTO)
ACCIÓN DE TUTELA
Accionante: MARIA PRUEBA. Accionada: ENTIDAD PRUEBA S.A.
HECHOS
1. La accionante solicitó un servicio y no obtuvo respuesta.
PRETENSIONES
Solicito se ordene a la accionada responder."""

CONTESTACION = f"""Medellín, 4 de marzo de 2027
Señor JUEZ TREINTA Y TRES PENAL MUNICIPAL
Ref. Radicado acción de tutela {CUI}
Accionante: MARIA PRUEBA
Contestación a la acción de tutela. HECHOS
Me opongo a las pretensiones. Solicito se declare improcedente."""

ADMISORIO = """CONSTANCIA. Señora Juez, se recibió la acción de tutela. A Despacho.
Oficial Mayor
JUZGADO TREINTA Y TRES PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS
Medellín, nueve (9) de febrero de dos mil veintisiete (2027)
Vistos los requisitos del Decreto 2591 de 1991, SE ADMITE la presente acción de tutela instaurada por MARIA PRUEBA.
Notifíquese y cúmplase."""

CONCEDE = """JUZGADO TREINTA Y TRES PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS
Medellín, veinticuatro (24) de marzo de dos mil veintisiete (2027)
Vista la constancia que antecede, concédase en el efecto devolutivo, la impugnación interpuesta por la accionante.
Cúmplase."""

FALLO_PAGINA = (
    "JUZGADO TREINTA Y TRES PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN\n"
    "Accionante MARIA PRUEBA. Acción de tutela. ANTECEDENTES. CONSIDERACIONES. Competencia. RESUELVE: PRIMERO. Niega el amparo. "
    + "texto de relleno de la providencia "
    * 60
)

CORREO_JUZGADO = "Outlook {asunto} Desde Juzgado 33 Penal Municipal Control Garantías - Antioquia - Medellín <pmpal33med@cendoj.ramajudicial.gov.co> Fecha Vie 2027-05-21 13:50 Para {para} {cuerpo}"


@pytest.mark.parametrize(
    "clase,rad,esperado",
    [
        ("TUTELA", "05001408803320270045900", "acta_reparto_1a"),
        ("IMPUGNACIÓN TUTELA", "05001408803320270045900", "acta_reparto_2a"),
        ("TUTELA", "05001408803320270045901", "acta_reparto_2a"),
    ],
)
def test_acta(clase, rad, esperado):
    assert rol(ACTA.format(rad=rad, clase=clase)) == esperado


def test_indice():
    assert (
        rol(
            "Consejo Superior ÍNDICE DEL EXPEDIENTE JUDICIAL ELECTRÓNICO Ciudad MEDELLÍN Despacho Judicial"
        )
        == "indice"
    )


def test_escrito_de_tutela_y_contestacion_no_se_confunden():
    assert rol(ESCRITO) == "escrito_tutela"
    assert rol(CONTESTACION) == "contestacion"


def test_escrito_sin_saludo_de_reparto():
    texto = "ACCIONANTE: MARIA PRUEBA ACCIONADO: ENTIDAD PRUEBA ASUNTO: Acción de tutela por vulneración de derechos. HECHOS 1. Algo ocurrió. PRETENSIONES Solicito amparo."
    assert rol(texto) == "escrito_tutela"


def test_autos_iniciales():
    assert rol(ADMISORIO) == "auto_admisorio"
    assert (
        rol(
            "JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL Medellín. Se asume el conocimiento de la acción de tutela promovida por MARIA PRUEBA."
        )
        == "auto_admisorio"
    )
    assert (
        rol(
            "Constancia: la tutela fue recibida. JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL Medellín. SE INADMITE la acción de tutela; subsane en tres días."
        )
        == "otro"
    )
    asume_tras_inadmision = "Constancia: luego de inadmitirse la acción de tutela, fue subsanada. JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL Medellín. SE ADMITE la acción de tutela."
    assert rol(asume_tras_inadmision) == "auto_admisorio"
    vinculacion = "JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL Medellín. AUTO. Se ordena la vinculación a la litis de ENTIDAD PRUEBA S.A. dentro de la acción de tutela."
    assert rol(vinculacion) == "auto_vinculacion"


def test_auto_que_concede_impugnacion():
    assert rol(CONCEDE) == "auto_concede_impugnacion"
    secretarial = "JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL Medellín. La accionante allegó escrito de impugnación el 19 de marzo; está en término, en tanto se concede."
    assert rol(secretarial) == "auto_concede_impugnacion"


def test_fallo_exige_estructura_y_extension():
    assert rol([FALLO_PAGINA] * 6) == "fallo_a_quo"
    assert rol([FALLO_PAGINA] * 2) == "otro"


def test_fallo_de_una_sola_pagina_larga():
    assert rol(["\n".join([FALLO_PAGINA] * 6)]) == "fallo_a_quo"


def test_fallo_sin_la_palabra_resuelve():
    pagina = FALLO_PAGINA.replace("RESUELVE", "DECISIÓN")
    assert rol([pagina] * 6) == "fallo_a_quo"


def test_impugnacion_escrita_por_la_parte():
    texto = "Cali 3 de mayo de 2027 SEÑOR(A): JUZGADO TREINTA Y TRES PENAL MUNICIPAL E. S. D. Ref.: RECURSO DE IMPUGNACIÓN CONTRA EL FALLO DE TUTELA. Accionante: MARIA PRUEBA"
    assert rol([texto] + ["argumentos del recurso " * 10] * 3) == "impugnacion"
    titulo = (
        "ACCIÓN DE TUTELA IMPUGNACIÓN Señores Juzgado 33 Penal Municipal Cali, 7 de mayo de 2027 Impugnación sobre fallo de tutela. "
        + "texto " * 20
    )
    assert rol(titulo) == "impugnacion"


def test_la_impugnacion_que_cita_el_fallo_no_es_fallo():
    texto = "SEÑOR JUEZ E. S. D. Ref.: IMPUGNACIÓN DE FALLO DE TUTELA. " + FALLO_PAGINA
    assert rol([texto] + [FALLO_PAGINA] * 6) == "impugnacion"


def test_correo_externo_con_impugnacion():
    texto = "Outlook Radicación de impugnación a la sentencia Desde Maria Prueba <maria@correo.com> Fecha Lun 2027-03-22 09:05 Para Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co> Adjunto escrito."
    assert rol(texto) == "impugnacion"
    sin_asunto = "Outlook Documento adjunto Desde Maria Prueba <maria@correo.com> Fecha Mié 12/05/2027 3:17 PM Para Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co> SEÑOR JUEZ: interpongo recurso de impugnación contra el fallo de tutela."
    assert rol(sin_asunto) == "impugnacion"


def test_correo_externo_que_no_es_impugnacion():
    contestacion = "Outlook Contestación de la acción Desde Entidad <notif@entidad.com> Fecha Mar 18/05/2027 8:41 AM Para Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co> Se adjunta respuesta. No hay impugnaciones."
    assert rol(contestacion) == "contestacion"
    assert (
        rol(
            "Outlook Consulta general Desde Maria <m@correo.com> Fecha Mar 18/05/2027 8:41 AM Para Juzgado 33 <j@cendoj.ramajudicial.gov.co> Quisiera saber el estado."
        )
        == "correo"
    )


def test_correo_del_juzgado_que_trae_una_impugnacion():
    citado = (
        "Se acusa recibido. Cordialmente, Juzgado 33. De: Maria Prueba <maria@correo.com> Enviado: miércoles, 16 de junio de 2027 "
        "Para: Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co> Asunto: Re: Comunicación de la sentencia Es una impugnación al fallo."
    )
    assert (
        rol(
            CORREO_JUZGADO.format(
                asunto="Re: Comunicación de la sentencia",
                para="Maria <maria@correo.com>",
                cuerpo=citado,
            )
        )
        == "impugnacion"
    )


def test_correo_del_juzgado_que_remite_una_ampliacion_de_la_impugnacion():
    texto = CORREO_JUZGADO.format(
        asunto="RV: Ampliación de los argumentos de la impugnación",
        para="Juzgado 3 Penal Circuito <pcto03med@cendoj.ramajudicial.gov.co>",
        cuerpo="Se remite memorial allegado por la parte accionante.",
    )
    assert rol(texto) == "impugnacion"


@pytest.mark.parametrize(
    "asunto,para,esperado",
    [
        (
            "Aviso de providencia que concede la impugnación",
            "Maria <maria@correo.com>",
            "notificacion",
        ),
        (
            "Notificación: providencia que concede la impugnación con sus anexos",
            "Maria <maria@correo.com>",
            "notificacion",
        ),
        ("Comunicación de la sentencia", "Maria <maria@correo.com>", "notificacion"),
        (
            "Envío del expediente por impugnación",
            "Juzgado 3 <pcto03med@cendoj.ramajudicial.gov.co>",
            "correo",
        ),
    ],
)
def test_correos_del_juzgado(asunto, para, esperado):
    assert (
        rol(CORREO_JUZGADO.format(asunto=asunto, para=para, cuerpo="Cordial saludo."))
        == esperado
    )


def test_correo_sin_encabezado_desde():
    texto = "3/6/27, 11:20 Elementos enviados: Juzgado 33 Penal Municipal - Outlook Microsoft se completó la entrega. Asunto: Notificación de la acción de tutela 2027-00987. SE ADMITE la acción de tutela."
    assert rol(texto) == "notificacion"


def test_dos_impugnaciones_son_impugnacion():
    a = "SEÑOR JUEZ E. S. D. Ref.: IMPUGNACIÓN FALLO de la accionante. " + "texto " * 10
    b = (
        "Señores JUZGADO PENAL MUNICIPAL ASUNTO: IMPUGNACIÓN FALLO de la accionada. "
        + "texto " * 10
    )
    assert rol(a) == "impugnacion" and rol(b) == "impugnacion"


def test_el_contenido_manda_sobre_el_nombre():
    assert rol(ESCRITO, "005AutoAdmisorio.pdf") == "escrito_tutela"
    assert (
        rol(
            ACTA.format(rad="05001408803320270045900", clase="TUTELA"),
            "011FalloTutela.pdf",
        )
        == "acta_reparto_1a"
    )
    assert rol(ESCRITO, "001.pdf") == rol(ESCRITO, "002EscritoTutela.pdf")


def test_el_nombre_solo_desempata_sin_texto():
    vacio = doc([""], "004EscritoTutela.pdf")
    assert clasificar(vacio)[0] == "escrito_tutela"
    assert (
        clasificar(doc([""], "011ActaRepartoImpugnacion.pdf"))[0] == "acta_reparto_2a"
    )
    assert clasificar(doc([""], "001.pdf"))[0] == "otro"


def test_vinculacion_vs_admision_por_nombre_en_caso_ambiguo():
    ambiguo = "JUZGADO TREINTA Y CUATRO PENAL MUNICIPAL. AUTO. Se admite la acción de tutela de MARIA PRUEBA. Se ordena la vinculación a la litis de OTRA S.A."
    assert clasificar(doc(ambiguo, "006VinculaEntidad.pdf"))[0] == "auto_vinculacion"
    assert clasificar(doc(ambiguo, "003AutoAdmite.pdf"))[0] == "auto_admisorio"


def test_evidencia_citada_y_corta():
    for texto in (
        ESCRITO,
        ADMISORIO,
        CONCEDE,
        [FALLO_PAGINA] * 6,
        ACTA.format(rad="05001408803320270045900", clase="TUTELA"),
    ):
        r, ev = clasificar(doc(texto))
        assert r != "otro" and 0 < len(ev) <= 160


def test_sentencia_de_otro_radicado_no_es_fallo_a_quo():
    propia = doc(
        [f"{FALLO_PAGINA} Radicado {CUI}"] + [FALLO_PAGINA] * 5, "a.pdf", "1a-001"
    )
    ajena = doc(
        [f"{FALLO_PAGINA} Radicado {OTRO_CUI}"] + [FALLO_PAGINA] * 5, "b.pdf", "1a-002"
    )
    docs = [propia, ajena]
    for d in docs:
        d.rol, d.evidencia = clasificar(d)
    assert [d.rol for d in docs] == ["fallo_a_quo", "fallo_a_quo"]
    resolver_caso(docs, PREFIJO)
    assert [d.rol for d in docs] == ["fallo_a_quo", "otro"]
    assert "otro radicado" in ajena.evidencia


def test_un_solo_fallo_del_caso():
    uno = doc(
        [f"{FALLO_PAGINA} Radicado {CUI}"] + [FALLO_PAGINA] * 5, "a.pdf", "1a-001"
    )
    otro = doc(
        [f"{FALLO_PAGINA} Radicado {CUI}"] + [FALLO_PAGINA] * 8, "b.pdf", "1a-002"
    )
    for d in (uno, otro):
        d.rol = "fallo_a_quo"
    resolver_caso([uno, otro], PREFIJO)
    assert (uno.rol, otro.rol) == ("otro", "fallo_a_quo")


def test_la_ultima_acta_de_impugnacion_es_la_vigente():
    a, b, c = (doc("x" * 40, f"{i}.pdf", f"1a-00{i}") for i in range(1, 4))
    a.rol, b.rol, c.rol = "acta_reparto_2a", "acta_reparto_1a", "acta_reparto_2a"
    resolver_caso([a, b, c], PREFIJO)
    assert (a.rol, b.rol, c.rol) == ("otro", "acta_reparto_1a", "acta_reparto_2a")


def test_resolver_caso_sin_prefijo_no_falla():
    d = doc([FALLO_PAGINA] * 6)
    d.rol = "fallo_a_quo"
    resolver_caso([d], None)
    assert d.rol == "fallo_a_quo"


def test_acta_de_impugnacion_con_columnas_en_otro_orden():
    texto = (
        "ACTA INDIVIDUAL DE REPARTO Fecha: 9/02/2027\nNÚMERO RADICACIÓN:\nCLASE PROCESO:\n"
        "NÚMERO DESPACHO:\nREPARTIDO AL DESPACHO:\n" + PREFIJO + "01\nIMPUGNACIÓN TUTELA\n003"
    )
    assert rol(texto) == "acta_reparto_2a"
    solo_cui = texto.replace("IMPUGNACIÓN TUTELA", "TUTELA")
    assert rol(solo_cui) == "acta_reparto_2a"
    primera = solo_cui.replace(PREFIJO + "01", PREFIJO + "00")
    assert rol(primera) == "acta_reparto_1a"


def test_correo_de_outlook_con_arroba_mal_leida_por_ocr():
    texto = (
        "Outlook IMPUGNACIÓN CONTRA EL FALLO DE TUTELA\nBandeja de entrada\n"
        "Desde relaciones financieras <relacionesfinancierasO gmail.com> Fecha Lun 2027-03-22\n"
        "Para Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co>\nAdjunto escrito."
    )
    assert rol(texto) == "impugnacion"


def test_bandeja_sin_encabezado_con_asunto_de_impugnacion():
    texto = "Bandeja de entrada\nIMPUGNACIÓN CONTRA EL FALLO\nDesde algo ilegible\n" + "x" * 40
    assert rol(texto) == "impugnacion"
    assert rol("Bandeja de entrada\nCitación a audiencia\n" + "x" * 40) == "correo"


def test_admisorio_con_se_dispone_la_tramitacion_y_vinculacion():
    texto = (
        "JUZGADO PENAL MUNICIPAL\nMedellín, 9 de febrero de 2027\n"
        "Se dispone la tramitación de esta acción de tutela y, de manera oficiosa, se ordena la vinculación de la entidad."
    )
    r, ev = clasificar(doc(texto, "005.pdf"))
    assert r == "auto_admisorio" and "tramitaci" in ev


def test_auto_con_oficios_anexos_no_cuenta_las_paginas_del_anexo():
    auto = "JUZGADO PENAL MUNICIPAL\nMedellín, 9 de febrero de 2027\nSe concede la impugnación contra el fallo de tutela.\nNOTIFÍQUESE Y CÚMPLASE"
    paginas = [auto, "oficio anexo " * 10, "oficio anexo " * 10, "oficio anexo " * 10, "oficio anexo " * 10]
    assert rol(paginas, "003.pdf") == "auto_concede_impugnacion"
    sin_firma = [auto.replace("NOTIFÍQUESE", "")] + paginas[1:]
    assert rol(sin_firma, "003.pdf") == "otro"


def test_sentencia_del_circuito_no_desplaza_a_la_municipal():
    municipal = doc(
        ["JUZGADO TREINTA Y TRES PENAL MUNICIPAL " + f"Radicado {CUI} " + FALLO_PAGINA]
        + [FALLO_PAGINA] * 2,
        "a.pdf",
        "1a-001",
    )
    circuito = doc(
        ["JUZGADO TERCERO PENAL DEL CIRCUITO " + f"Radicado {CUI} " + FALLO_PAGINA]
        + [FALLO_PAGINA] * 8,
        "b.pdf",
        "1a-002",
    )
    for d in (municipal, circuito):
        d.rol = "fallo_a_quo"
    resolver_caso([municipal, circuito], PREFIJO)
    assert (municipal.rol, circuito.rol) == ("fallo_a_quo", "otro")
