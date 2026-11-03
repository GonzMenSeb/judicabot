from __future__ import annotations

from docx import Document

from tutela2.config import Config
from tutela2.documentos import correos
from tutela2.models import Compulsa, Decision, Doc, Ingesta, Metadatos, Pagina

CUI_1A = "05001400900120269999900"
CUI_2A = "05001400900120269999901"

NOTIF = """Outlook

NOTIFICACIÓN – FALLO TUTELA

Desde Juzgado Uno Penal Municipal <juz01@ejemplo.gov.co>
Fecha Jue 2/04/2026 9:20 PM
Para    ana@ejemplo.com <ana@ejemplo.com>; notif@empresa.com.co
        <notif@empresa.com.co>; roto@ejemplo.gov.c

  1 archivo adjunto

Cuerpo con otro@ejemplo.com que no cuenta
"""


def doc(ruta: str, rol: str, texto: str, instancia: str = "1a") -> Doc:
    return Doc(
        doc_id=ruta, ruta=ruta, nombre=ruta, instancia=instancia, rol=rol, sha256="x",
        paginas=[Pagina(n=1, texto=texto)],
    )


def md() -> Metadatos:
    return Metadatos(
        cui_1a=CUI_1A, cui_2a=CUI_2A, accionante="Ana Prueba",
        accionadas=["EPS Ficticia", "Banco Ejemplo"], juzgado_a_quo="Juzgado Uno Penal Municipal de Medellín",
    )


def textos(d) -> list[str]:
    return [p.text for p in d.paragraphs]


def test_destinatarios_validos_sin_duplicados_ni_cuerpo():
    ing = Ingesta(documentos=[
        doc("a/001.pdf", "notificacion", "Para: viejo@ejemplo.com"),
        doc("a/002.pdf", "notificacion", NOTIF),
        doc("a/003.pdf", "notificacion", "Para: x@ejemplo.com", instancia="2a"),
    ])
    assert correos.destinatarios_propuestos(ing) == [
        "juz01@ejemplo.gov.co", "ana@ejemplo.com", "notif@empresa.com.co",
    ]


def test_destinatarios_con_dos_puntos_y_duplicados():
    t = "De: a@x.com\nPara: A@x.com; b@x.com\n"
    ing = Ingesta(documentos=[doc("a/001.pdf", "notificacion", t)])
    assert correos.destinatarios_propuestos(ing) == ["a@x.com", "b@x.com"]


def test_destinatarios_sin_notificacion():
    assert correos.destinatarios_propuestos(Ingesta(documentos=[doc("a.pdf", "otro", "Para: a@x.com")])) == []


def test_notificacion(tmp_path):
    ing = Ingesta(documentos=[doc("a/002.pdf", "notificacion", NOTIF)])
    ruta = correos.render_notificacion(md(), ing, Config(), "003Fallo.pdf", tmp_path / "sub" / "n.docx")
    d = Document(ruta)
    t = textos(d)
    assert t[0] == correos.AVISO
    assert t[1] == "Para: juz01@ejemplo.gov.co; ana@ejemplo.com; notif@empresa.com.co"
    assert t[2] == f"Asunto: Notifica fallo de segunda instancia radicado {CUI_2A}"
    assert t[3] == "Adjunto: 003Fallo.pdf"
    assert "Cordial saludo," in t and "Adjunto sentencia de tutela para su conocimiento:" in t
    assert "Cordialmente," in t
    assert t[-6:] == [
        "John Mendoza", "Escribiente", "Juzgado 3 Penal del Circuito con Funciones",
        "de Conocimiento de Medellín", "pcto03med@cendoj.ramajudicial.gov.co", "Tel: 6042328525 Ext. 2903",
    ]
    assert len(d.tables) == 1
    celdas = [c.text for c in d.tables[0].rows[0].cells]
    assert len(d.tables[0].rows) == 1
    assert celdas[1:] == ["ANA PRUEBA", "EPS FICTICIA, BANCO EJEMPLO"]
    assert celdas[0] == "050014009001202699999-01"
    assert d.tables[0]._tbl.tblPr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblBorders"
    ) is not None


def test_notificacion_faltantes_resaltados(tmp_path):
    ruta = correos.render_notificacion(Metadatos(), Ingesta(documentos=[]), Config(), "f.pdf", tmp_path / "n.docx")
    d = Document(ruta)
    assert "⟦FALTA: destinatarios⟧" in textos(d)[1]
    resaltados = [r.text for p in d.paragraphs for r in p.runs if r.font.highlight_color]
    assert "⟦FALTA: destinatarios⟧" in resaltados


def test_envio_formato(tmp_path):
    ruta = correos.render_envio_formato(md(), Config(), "004Formato.pdf", tmp_path / "e.docx", para="juz01@ejemplo.gov.co")
    t = textos(Document(ruta))
    assert t[0] == correos.AVISO
    assert t[1] == "Para: juz01@ejemplo.gov.co"
    assert t[2] == f"Asunto: Envio formato calificación de calidad radicado {CUI_1A}"
    assert "Señores" in t and "Juzgado Uno Penal Municipal de Medellín" in t
    assert f"Radicado: {CUI_1A}" in t
    assert "Adjunto archivo en PDF." in t and "Atentamente," in t
    assert any(x.startswith("Por medio del presente, se remite el Formato Factor Calidad") for x in t)


def test_envio_formato_sin_para(tmp_path):
    ruta = correos.render_envio_formato(md(), Config(), "f.pdf", tmp_path / "e.docx")
    assert "⟦FALTA: correo del juzgado de origen⟧" in textos(Document(ruta))[1]


def test_compulsa(tmp_path):
    dec = Decision(accion="decidir", compulsa=Compulsa(respecto_de="el Juzgado Ficticio", organo="Comisión Seccional de Prueba"))
    ruta = correos.render_compulsa(md(), dec, Config(), "003Fallo.pdf", tmp_path / "c.docx")
    t = textos(Document(ruta))
    assert t[1] == "Para: ofjudmed@cendoj.ramajudicial.gov.co"
    assert t[2] == f"Asunto: Remisión compulsa copias en tutela radicado: {CUI_2A}"
    assert "Oficina de Reparto" in t and "Comisión Seccional de Prueba" in t
    assert any(
        x == "Por medio del presente, y dando cumplimiento a lo ordenado por el señor Juez "
        "SANTIAGO ALEJANDRO CADAVID DUQUE dentro del fallo adjunto me permito remitirle el link del "
        "expediente de la tutela, donde es accionante ANA PRUEBA." for x in t
    )
    assert "Dicha providencia dispuso lo siguiente:" in t
    assert any(x.startswith("TERCERO: COMPULSAR COPIAS ante la Comisión Seccional de Prueba") and "respecto del Juzgado Ficticio," in x for x in t)
    assert "Link de acceso al expediente:" in t
    assert "⟦FALTA: link del expediente⟧" in t


def _para(texto):
    return correos.destinatarios_propuestos(Ingesta(documentos=[doc("a/1.pdf", "notificacion", texto)]))


def test_destinatarios_ignora_avisos_de_sistema():
    t = (
        "Desde Juzgado Uno <juz01@ejemplo.gov.co>\nFecha Jue 2/04/2026\nPara ana@ejemplo.com\n\n"
        "Desde Microsoft Outlook <MicrosoftExchangeabc@cendoj.ramajudicial.gov.co>\n"
        "Fecha Jue 2/04/2026\nPara rebote@ejemplo.com\n\n"
        "Desde postmaster@outlook.com <postmaster@outlook.com>\nFecha Jue\nPara otro@ejemplo.com\n"
    )
    assert _para(t) == ["juz01@ejemplo.gov.co", "ana@ejemplo.com"]


def test_destinatarios_encabezado_outlook_en_varias_lineas():
    t = (
        "Desde Juzgado Uno Penal Municipal - Medellín\n<juz01@ejemplo.gov.co>\nFecha Vie 2026-09-25 13:56\n"
        "Para    ana@ejemplo.com <ana@ejemplo.com>; Estudio Juridico\n<estudio@ejemplo.com>; notif <notif@empresa.com>;\n"
        "<otro@ejemplo.com>\n\nCuerpo con ajeno@ejemplo.com\n"
    )
    assert _para(t) == ["juz01@ejemplo.gov.co", "ana@ejemplo.com", "estudio@ejemplo.com", "notif@empresa.com", "otro@ejemplo.com"]


def test_destinatarios_ignora_lineas_de_cuerpo():
    assert _para("Cordial saludo,\n\nDe manera atenta escriba a cuerpo@ejemplo.com\n") == []
    assert _para("Para efectos de notificación use abogado@ejemplo.com\n") == []


def test_compulsa_normaliza_espacios_y_lleva_ordinal(tmp_path):
    dec = Decision(accion="decidir", compulsa=Compulsa(respecto_de=" el Juzgado Ficticio ", organo="Comisión Seccional de Prueba"))
    ruta = correos.render_compulsa(md(), dec, Config(), "f.pdf", tmp_path / "c.docx")
    x = next(p for p in textos(Document(ruta)) if "COMPULSAR COPIAS" in p)
    assert "respecto del Juzgado Ficticio, conforme" in x
    assert x.split(":")[0].isupper()


def test_envio_formato_juzgado_en_digitos(tmp_path):
    m = md().model_copy(update={"juzgado_a_quo_numero": 18, "juzgado_a_quo_funcion": "control_garantias"})
    ruta = correos.render_envio_formato(m, Config(), "004Formato.pdf", tmp_path / "e.docx", para="a@b.co")
    assert "Juzgado 18 Penal Municipal con Función de Control de Garantías de Medellín" in textos(Document(ruta))


NOTIF_CORTADA = """Desde Juzgado Uno Penal Municipal <juz01@ejemplo.gov.co>
Fecha Jue 2/04/2026 9:20 PM
Para    ana@ejemplo.com; persona.apellido@ejemplo.gov.c;
        otra@ejemplo.gov.c

  1 archivo adjunto
"""


def test_destinatario_truncado_se_completa_con_direccion_del_expediente():
    ing = Ingesta(documentos=[
        doc("n.pdf", "notificacion", NOTIF_CORTADA),
        doc("c.pdf", "contestacion", "Notificaciones: persona.apellido@ejemplo.gov.co, telefono 123"),
    ])
    assert correos.destinatarios_propuestos(ing) == ["juz01@ejemplo.gov.co", "ana@ejemplo.com", "persona.apellido@ejemplo.gov.co"]


def test_destinatario_truncado_ambiguo_se_omite():
    ing = Ingesta(documentos=[
        doc("n.pdf", "notificacion", NOTIF_CORTADA),
        doc("c.pdf", "contestacion", "persona.apellido@ejemplo.gov.co y persona.apellido@ejemplo.gov.cu"),
    ])
    assert correos.destinatarios_propuestos(ing) == ["juz01@ejemplo.gov.co", "ana@ejemplo.com"]


def test_destinatario_truncado_sin_coincidencia_no_se_inventa():
    ing = Ingesta(documentos=[
        doc("n.pdf", "notificacion", NOTIF_CORTADA),
        doc("c.pdf", "contestacion", "otro.apellido@ejemplo.gov.co"),
    ])
    assert correos.destinatarios_propuestos(ing) == ["juz01@ejemplo.gov.co", "ana@ejemplo.com"]


def test_destinatario_truncado_ignora_documentos_ajenos_ruido_y_producto():
    for kw in ({"docs_ajenos": ["c.pdf"]}, {}):
        c = doc("c.pdf", "contestacion", "persona.apellido@ejemplo.gov.co")
        if not kw:
            c = doc("c.pdf", "producto_despacho", "persona.apellido@ejemplo.gov.co")
        ing = Ingesta(documentos=[doc("n.pdf", "notificacion", NOTIF_CORTADA), c], **kw)
        assert "persona.apellido@ejemplo.gov.co" not in correos.destinatarios_propuestos(ing)
    c = doc("c.pdf", "contestacion", "persona.apellido@ejemplo.gov.co")
    c.paginas[0].ruido = True
    ing = Ingesta(documentos=[doc("n.pdf", "notificacion", NOTIF_CORTADA), c])
    assert "persona.apellido@ejemplo.gov.co" not in correos.destinatarios_propuestos(ing)


def test_destinatario_truncado_ignora_documento_con_ruido():
    c = doc("c.pdf", "contestacion", "persona.apellido@ejemplo.gov.co")
    c.ruido = True
    ing = Ingesta(documentos=[doc("n.pdf", "notificacion", NOTIF_CORTADA), c])
    assert "persona.apellido@ejemplo.gov.co" not in correos.destinatarios_propuestos(ing)
