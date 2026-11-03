from __future__ import annotations

import hashlib

import re
import sys
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph

from tutela2 import formulas, render
from tutela2.config import Config, LLMConfig
from tutela2.jev import ErrorJev, RespuestaJev, llamada_fallida, llamada_ia
from tutela2.models import (
    AperturaLLM,
    BloqueLLM,
    CasoConcretoLLM,
    CitaPropuesta,
    CitaVerificada,
    Compulsa,
    Contestacion,
    ConsideracionesLLM,
    Decision,
    DisposicionDerecho,
    Evento,
    Fechas,
    Ingesta,
    LlamadaIA,
    Metadatos,
    MetadatosLLM,
    Orden,
    ParrafoLLM,
    Plazo,
    Reparo,
)

HOY = date(2026, 10, 21)

TITULOS = {
    "A": ["I. ASUNTO", "II. ANTECEDENTES DEL CASO", "III. FALLO RECURRIDO", "IV. IMPUGNACIÓN",
          "V. CONSIDERACIONES DEL JUZGADO", "VI. CASO CONCRETO"],
    "B": ["I. ASUNTO", "II. ANTECEDENTES DEL CASO", "III. LA SENTENCIA IMPUGNADA", "IV. LA IMPUGNACIÓN",
          "V. CONSIDERACIONES", "VI. CASO CONCRETO"],
}
ORDINALES = ("PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO", "SEXTO", "SÉPTIMO", "OCTAVO", "NOVENO", "DÉCIMO")


def casi(a, b) -> bool:
    return abs(a - b) <= 635


def t(gen: str, titulo: str) -> str:
    return titulo.replace(". ", ".\t", 1) if gen == "B" else titulo


def parrafos(ruta: Path) -> list[Paragraph]:
    doc = Document(ruta)
    return [Paragraph(p, doc) for p in doc.element.body.iterchildren(qn("w:p"))]


def lineas(ruta: Path) -> list[str]:
    doc = Document(ruta)
    salida: list[str] = []
    for hijo in doc.element.body.iterchildren():
        if hijo.tag == qn("w:p"):
            salida.append(Paragraph(hijo, doc).text)
        elif hijo.tag == qn("w:tbl"):
            for fila in Table(hijo, doc).rows:
                salida.append(" | ".join(c.text for c in fila.cells))
    return salida


def construir_metadatos() -> Metadatos:
    return Metadatos(
        cui_1a="05001999900120260099900",
        cui_2a="05001999900120260099901",
        juzgado_a_quo="Juzgado Dieciocho Penal Municipal de Ejemplo",
        juzgado_a_quo_numero=18,
        juzgado_a_quo_funcion="control_garantias",
        juzgado_a_quo_letras="Dieciocho",
        resultado_a_quo="declaró improcedente la acción de tutela",
        accionante="ANA EJEMPLO PRUEBA",
        accionadas=["BANCO EJEMPLO S.A."],
        vinculadas=["CLÍNICA MODELO S.A.S."],
        impugnante="Ana Ejemplo Prueba",
        impugnante_rol="accionante",
        derechos_invocados=["mínimo vital", "debido proceso"],
        decision_a_quo="Improcedente",
        fechas=Fechas(fallo_a_quo="2026-09-21", reparto_2a="2026-10-20"),
    )


def construir_decision(compulsa: bool = True, **extra) -> Decision:
    base = dict(
        accion="decidir",
        resultado="REVOCAR",
        sustitutiva="AMPARAR",
        eje="El eje de la decisión de ejemplo.",
        derechos=[DisposicionDerecho(derecho="mínimo vital"), DisposicionDerecho(derecho="debido proceso")],
        ordenes=[
            Orden(
                destinatario="BANCO EJEMPLO S.A.",
                conducta="valore integralmente los documentos aportados",
                plazo=Plazo(n=48, unidad="horas_habiles"),
                literales=["La causa concreta de la restricción.", "Los recursos disponibles."],
            )
        ],
        desvincular=["ENTIDAD AJENA S.A."],
        prevenir=["BANCO EJEMPLO S.A."],
        compulsa=Compulsa(respecto_de="el Juzgado Ejemplo", hechos_ref="HECHOS_REF_COMPULSA de ejemplo.") if compulsa else None,
        decidido_por="Juez Ejemplo",
        previo_sha256="d" * 64,
    )
    base.update(extra)
    return Decision(**base)


def construir_estado(compulsa: bool = True) -> dict:
    md = construir_metadatos()
    decision_vigente = construir_decision(compulsa).model_dump(mode="json")
    decision_vigente["fecha"] = "2026-10-20"
    apertura = AperturaLLM(
        metadatos=MetadatosLLM(),
        cronologia=[Evento(fecha="2026-09-21", hecho="Hecho de ejemplo", doc_id="1a-001", cita_literal="x")],
        antecedentes_hechos="ANTECEDENTES_HECHOS primer párrafo.\n\nANTECEDENTES_HECHOS segundo párrafo.",
        contestaciones=[Contestacion(entidad="BANCO EJEMPLO S.A.", texto="CONTESTACION_BANCO guardó absoluto silencio.")],
        sentencia_impugnada="SENTENCIA_IMPUGNADA_TEXTO.",
        impugnacion="IMPUGNACION_TEXTO.",
        reparos=[Reparo(id="R1", sintesis="s", doc_id="1a-002", cita_literal="x")],
    )
    consideraciones = ConsideracionesLLM(
        procedibilidad=(
            "PROCEDIBILIDAD_P1 según lo dicho en [[CITA:c1]] y reiterado en [[CITA:c1]].\n\n"
            "PROCEDIBILIDAD_P2 sin citas."
        ),
        bloques=[
            BloqueLLM(
                titulo="Hábeas data",
                reparo_ids=["R1"],
                texto="BLOQUE_TEXTO se apoya en [[CITA:c2]]. Otra tesis en [[CITA:c3]].",
            )
        ],
        citas=[CitaPropuesta(id="c1", sentencia="T-200 de 2022", texto_citado="x")],
    )
    citas = [
        CitaVerificada(
            id="c1", sentencia_original="T-200 de 2022", sentencia_norm="T-200/22", tipo="T", numero=200,
            anio=2022, texto_citado="QUOTE_C1 fragmento literal uno.", en_dataset=True,
            mp_dataset="José Fernando Reyes Cuartas", url="https://example.test/T-200-22.htm",
            pagina_ok=True, cobertura=1.0, estado="ok",
        ),
        CitaVerificada(
            id="c2", sentencia_original="SU-082/95", sentencia_norm="SU-082/95", tipo="SU", numero=82,
            anio=1995, texto_citado="QUOTE_C2 fragmento literal dos.", en_dataset=True,
            mp_dataset="Jorge Arango Mejía", cobertura=0.6, estado="alerta", motivos=["Cobertura parcial"],
        ),
        CitaVerificada(
            id="c3", sentencia_original="T-999 de 2020", texto_citado="QUOTE_C3_RECHAZADO",
            estado="rechazada", motivos=["La sentencia no existe en el dataset"],
        ),
    ]
    caso = CasoConcretoLLM(
        problema_juridico="PROBLEMA_JURIDICO_TEXTO.",
        parrafos=[
            ParrafoLLM(
                reparo_ids=["R1"],
                texto="CASO_P1 con apoyo en [[CITA:c1]].\n\nTexto previo [[IMAGEN 003 p. 2 Captura del extracto]] texto posterior.",
            )
        ],
        conclusion="CONCLUSION_TEXTO.",
    )
    bitacora = LlamadaIA(
        nodo="apertura", intento=1, proveedor="anthropic", modelo_pedido="claude-opus-5-5",
        modelo_efectivo="claude-opus-5-5", prompt_id="apertura@v1", sha256_instrucciones="a" * 64,
        sha256_entrada="b" * 64, sha256_salida="c" * 64, fecha="2026-10-19T10:00:00",
        tokens_entrada=1000, tokens_salida=500,
    )
    return {
        "ingesta": Ingesta(documentos=[], metadatos=md).model_dump(mode="json"),
        "metadatos": md.model_dump(mode="json"),
        "apertura": apertura.model_dump(mode="json"),
        "consideraciones": consideraciones.model_dump(mode="json"),
        "citas": [c.model_dump(mode="json") for c in citas],
        "decisiones": [
            construir_decision(False, resultado="CONFIRMAR").model_dump(mode="json"),
            decision_vigente,
            Decision(accion="rehacer_apertura", instruccion="otra vez").model_dump(mode="json"),
        ],
        "caso": caso.model_dump(mode="json"),
        "errores": ["BLOQUEA: error vigente de ejemplo"],
        "alertas": {"apertura": ["ALERTA: alerta de apertura de ejemplo"], "caso_concreto": []},
        "bitacora": [bitacora.model_dump(mode="json")],
    }


@pytest.fixture
def estado() -> dict:
    return construir_estado()


def test_reexportaciones():
    assert render.numero_a_letras(2026) == "dos mil veintiséis"
    assert render.numero_a_letras(31, "m") == "treinta y un"
    assert render.decision_encabezado is formulas.encabezado_decision



def test_fecha_larga():
    assert render.fecha_larga("2026-09-21") == "veintiuno (21) de septiembre de dos mil veintiséis (2026)"
    assert render.fecha_larga("2026-03-01T10:00:00") == "uno (01) de marzo de dos mil veintiséis (2026)"
    assert render.fecha_larga("2026-12-31") == "treinta y uno (31) de diciembre de dos mil veintiséis (2026)"


@pytest.mark.parametrize("valor", [None, "", "no es fecha", "2026-13-40"])
def test_fecha_larga_invalida_no_falla(valor):
    assert render.fecha_larga(valor) == "⟦FALTA: fecha⟧"


@pytest.mark.parametrize(
    "resultado, sustitutiva, esperado",
    [
        ("REVOCAR", "AMPARAR", "REVOCA"),
        ("REVOCAR", "NEGAR", "REVOCA Y NIEGA"),
        ("REVOCAR", "IMPROCEDENTE", "REVOCA Y DECLARA IMPROCEDENTE"),
        ("REVOCAR", "CARENCIA_HECHO_SUPERADO", "REVOCA Y DECLARA HECHO SUPERADO"),
        ("CONFIRMAR", "NEGAR", "CONFIRMA"),
        ("CONFIRMAR", "AMPARAR", "CONFIRMA"),
        ("MODIFICAR", "AMPARAR", "MODIFICA"),
        ("MODIFICAR", "NEGAR", "MODIFICA Y NIEGA"),
    ],
)
def test_decision_encabezado(resultado, sustitutiva, esperado):
    d = Decision(accion="decidir", resultado=resultado, sustitutiva=sustitutiva, eje="x")
    assert render.decision_encabezado(d) == esperado


def render_fallo(tmp_path, estado, gen, nombre="fallo.docx"):
    cfg = Config(plantilla_gen=gen)
    return render.render_fallo(estado, cfg, tmp_path / nombre, hoy=HOY)


@pytest.mark.parametrize("gen", ["A", "B"])
@pytest.mark.parametrize("compulsa", [True, False])
def test_fallo_titulos_en_orden_y_numeracion(tmp_path, gen, compulsa):
    ruta = render_fallo(tmp_path, construir_estado(compulsa), gen)
    texto = lineas(ruta)
    esperados = [t(gen, x) for x in TITULOS[gen]]
    if compulsa:
        esperados.append(t(gen, "VII. OTRAS DETERMINACIONES"))
    esperados.append(t(gen, ("VIII. " if compulsa else "VII. ") + ("RESUELVE" if gen == "B" else "PARTE RESOLUTIVA")))
    posiciones = [texto.index(x) for x in esperados]
    assert posiciones == sorted(posiciones)
    assert (t(gen, "VII. OTRAS DETERMINACIONES") in texto) is compulsa
    assert ("HECHOS_REF_COMPULSA de ejemplo." in texto) is compulsa
    if gen == "A":
        assert "RESUELVE" in texto[posiciones[-1]:]


def test_fallo_b_titulos_con_tabulacion(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    titulos = [p.text for p in parrafos(ruta) if re.match(r"^[IVX]+\.\t", p.text)]
    assert len(titulos) == 8
    assert all(re.match(r"^[IVX]+\.\t[A-ZÁÉÍÓÚÑ ]+$", x) for x in titulos)


def test_fallo_b_orden_de_consideraciones(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    v = texto.index(t("B", "V. CONSIDERACIONES"))
    vi = texto.index(t("B", "VI. CASO CONCRETO"))
    competencia_2 = formulas.competencia_2(Metadatos.model_validate(estado["metadatos"]))
    esperado = [
        formulas.SUBTITULO_COMPETENCIA,
        formulas.COMPETENCIA_1,
        competencia_2,
        formulas.SUBTITULO_PROCEDIBILIDAD,
        formulas.PROCEDIBILIDAD_P1,
        formulas.PROCEDIBILIDAD_P2,
    ]
    seccion = [linea for linea in texto[v + 1 : vi] if linea]
    assert seccion[: len(esperado)] == esperado
    assert seccion[len(esperado)].startswith("PROCEDIBILIDAD_P1 según")
    assert [linea for linea in texto[:vi] if linea][-1] == formulas.TRANSICION
    assert texto.count(formulas.COMPETENCIA_1) == 1 and texto.count(formulas.TRANSICION) == 1
    assert "por el " + "Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín" in competencia_2


def test_fallo_a_conserva_competencia_en_caso_concreto(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "A"))
    vi = texto.index("VI. CASO CONCRETO")
    assert formulas.COMPETENCIA_1 not in texto[:vi]
    assert texto[vi + 1] == formulas.COMPETENCIA_1
    assert texto[vi - 1] == formulas.TRANSICION


@pytest.mark.parametrize(
    "gen, merito",
    [
        ("A", "administrando justicia en nombre del Pueblo y por mandato Constitucional,"),
        ("B", "administrando justicia en nombre de la República y por autoridad de la Ley,"),
    ],
)
def test_fallo_formula_de_merito(tmp_path, gen, merito):
    texto = lineas(render_fallo(tmp_path, construir_estado(), gen))
    nombre = Config().despacho.nombre_cuerpo
    assert f"En mérito de lo expuesto, el {nombre}, {merito}" in texto


@pytest.mark.parametrize("gen", ["A", "B"])
def test_fallo_resuelve_consecutivo_y_cierre(tmp_path, gen):
    texto = lineas(render_fallo(tmp_path, construir_estado(), gen))
    inicio = texto.index(t(gen, "VIII. RESUELVE") if gen == "B" else "RESUELVE")
    ordinales = [m.group(1) for linea in texto[inicio:] if (m := re.match(r"^([A-ZÁÉÍÓÚ]+): ", linea))]
    assert ordinales == list(ORDINALES[:8])
    notificar = next(linea for linea in texto if linea.startswith("SÉPTIMO: NOTIFICAR"))
    assert "artículo 30 del Decreto 2591 de 1991" in notificar
    assert next(linea for linea in texto if linea.startswith("OCTAVO: REMITIR")).endswith("para su eventual revisión.")
    assert "a. La causa concreta de la restricción." in texto
    cierre, juez = Config().despacho.cierre_fallo, Config().despacho.juez
    if gen == "B":
        assert texto[-4:] == [cierre, "", juez, "JUEZ"]
    else:
        assert texto[-3:] == [cierre, juez, "JUEZ"]


def test_fallo_nombre_del_juez_desde_config(tmp_path, estado):
    cfg = Config(plantilla_gen="B")
    cfg.despacho.juez = "Juez Ejemplo Prueba"
    ruta = render.render_fallo(estado, cfg, tmp_path / "f.docx", hoy=HOY)
    assert lineas(ruta)[-2:] == ["JUEZ EJEMPLO PRUEBA", "JUEZ"]


def test_fallo_encabezado_gen_b(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert texto[0] == "JUZGADO TERCERO PENAL DEL CIRCUITO CON FUNCIÓN DE CONOCIMIENTO DE MEDELLÍN"
    assert texto[1] == "Medellín, veintiuno (21) de octubre de dos mil veintiséis (2026)"
    assert texto[2] == ""
    assert texto[3:10] == [
        "Radicado | 050019999001 2026 00999 01",
        "Accionante | ANA EJEMPLO PRUEBA",
        "Accionada | BANCO EJEMPLO S.A.",
        "Vinculada | CLÍNICA MODELO S.A.S.",
        "Procedencia | JUZGADO 18 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN",
        "Derechos | MÍNIMO VITAL, DEBIDO PROCESO",
        "Decisión | REVOCA",
    ]


def test_fallo_encabezado_gen_a(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "A"))
    assert texto[2:9] == [
        "ASUNTO | TUTELA DE SEGUNDA INSTANCIA",
        "RADICADO | 050019999001 2026 00999 01",
        "ACCIONANTE | ANA EJEMPLO PRUEBA",
        "ACCIONADA | BANCO EJEMPLO S.A.",
        "VINCULADA | CLÍNICA MODELO S.A.S.",
        "PROCEDENCIA | JUZGADO 18 PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN",
        "DERECHOS | MÍNIMO VITAL, DEBIDO PROCESO",
    ]
    assert texto[9] == "DECISIÓN | REVOCA"


def test_fallo_toma_la_ultima_decision_vigente(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert "Decisión | REVOCA" in texto
    assert not any("CONFIRMAR el fallo" in linea for linea in texto)


def test_fallo_encabezado_sin_vinculadas_ni_derechos(tmp_path):
    estado = construir_estado()
    for md in (estado["metadatos"], estado["ingesta"]["metadatos"]):
        md["vinculadas"] = []
        md["derechos_invocados"] = []
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert not any(linea.startswith(("Vinculada", "Derechos")) for linea in texto)


def test_fallo_asunto(tmp_path, estado):
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert (
        "Procede el Despacho a resolver la impugnación presentada por Ana Ejemplo Prueba contra el fallo de "
        "tutela emitido el veintiuno (21) de septiembre de dos mil veintiséis (2026) por el "
        "Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín, por medio del cual se declaró improcedente la acción de tutela."
    ) in texto


@pytest.mark.parametrize("gen", ["A", "B"])
def test_fallo_citas_y_bloques(tmp_path, gen):
    ruta = render_fallo(tmp_path, construir_estado(), gen)
    texto = lineas(ruta)
    v, vi = texto.index(t(gen, TITULOS[gen][4])), texto.index(t(gen, "VI. CASO CONCRETO"))

    primera = next(i for i, linea in enumerate(texto) if linea.startswith("PROCEDIBILIDAD_P1"))
    assert texto[primera].count("Sentencia T-200 de 2022") == 2
    assert texto[primera + 1] == "“QUOTE_C1 fragmento literal uno.”"
    assert texto[primera + 2].startswith("PROCEDIBILIDAD_P2")
    assert v < primera < vi

    c2 = next(i for i, linea in enumerate(texto) if linea.startswith("BLOQUE_TEXTO"))
    assert "⟦CITA NO VERIFICADA: T-999 de 2020⟧" in texto[c2]
    assert texto[c2 + 1] == "“QUOTE_C2 fragmento literal dos.”"

    plano = "\n".join(texto)
    assert plano.count("QUOTE_C1") == 1
    assert "QUOTE_C3_RECHAZADO" not in plano
    caso_p1 = next(linea for linea in texto if linea.startswith("CASO_P1"))
    assert "Sentencia T-200 de 2022" in caso_p1
    assert "[[" not in plano and "]]" not in plano


def test_cita_bloque_formato(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    cita = next(p for p in parrafos(ruta) if p.text.startswith("“QUOTE_C1"))
    assert abs(cita.paragraph_format.left_indent.pt - 42.62) <= 0.1
    assert abs(cita.paragraph_format.right_indent.pt - 49.95) <= 0.1
    assert abs(cita.paragraph_format.space_before.pt - 12) <= 0.1
    assert abs(cita.paragraph_format.space_after.pt - 12) <= 0.1
    xml = cita._p.xml
    assert xml.count("<w:i/>") == len(cita.runs) and 'w:u w:val="single"' in xml and 'w:sz w:val="22"' in xml
    assert 'w:line="360" w:lineRule="auto"' in xml


def test_cita_bloque_formato_gen_a(tmp_path, estado):
    cita = next(p for p in parrafos(render_fallo(tmp_path, estado, "A")) if p.text.startswith("“QUOTE_C1"))
    assert casi(cita.paragraph_format.left_indent, Cm(1.5))
    assert all(r.italic for r in cita.runs)


def test_marcador_de_imagen_en_parrafo_propio_y_resaltado(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    texto = lineas(ruta)
    i = texto.index("⟦INSERTAR IMAGEN: 003 p. 2 Captura del extracto⟧")
    assert texto[i - 1] == "Texto previo"
    assert texto[i + 1] == "texto posterior."
    parrafo = next(p for p in parrafos(ruta) if p.text.startswith("⟦INSERTAR IMAGEN"))
    assert parrafo.runs[0].font.highlight_color == WD_COLOR_INDEX.YELLOW


def test_cita_rechazada_resaltada(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    parrafo = next(p for p in parrafos(ruta) if p.text.startswith("BLOQUE_TEXTO"))
    marcadas = [r for r in parrafo.runs if r.font.highlight_color == WD_COLOR_INDEX.YELLOW]
    assert [r.text for r in marcadas] == ["⟦CITA NO VERIFICADA: T-999 de 2020⟧"]


def test_cita_con_id_desconocido_se_trata_como_rechazada(tmp_path):
    estado = construir_estado()
    estado["caso"]["conclusion"] = "Cierra con [[CITA:zz]]."
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert "Cierra con ⟦CITA NO VERIFICADA: zz⟧." in texto


def test_formato_gen_a(tmp_path, estado):
    doc = Document(render_fallo(tmp_path, estado, "A"))
    seccion = doc.sections[0]
    assert casi(seccion.page_width, Cm(21.6)) and casi(seccion.page_height, Cm(33.0))
    margenes = (seccion.left_margin, seccion.right_margin, seccion.top_margin, seccion.bottom_margin)
    assert all(casi(m, Cm(2.5)) for m in margenes)
    assert doc.styles["Normal"].font.name == "Bookman Old Style"
    assert Config().despacho.pie in " ".join(p.text for p in seccion.footer.paragraphs)
    titulo = next(p for p in doc.paragraphs if p.text == "I. ASUNTO")
    assert titulo.alignment == 1 and all(r.bold for r in titulo.runs)


def test_formato_gen_b_pagina_cabecera_y_pie(tmp_path, estado):
    doc = Document(render_fallo(tmp_path, estado, "B"))
    seccion = doc.sections[0]
    assert abs(seccion.page_width.pt - 597.48) <= 0.1 and abs(seccion.page_height.pt - 966.0) <= 0.1
    assert abs(seccion.left_margin.pt - 54) <= 0.1 and abs(seccion.right_margin.pt - 54) <= 0.1
    assert abs(seccion.top_margin.pt - 72) <= 0.1 and abs(seccion.bottom_margin.pt - 73.4) <= 0.1
    assert "<w:drawing" in seccion.header._element.xml
    pie = [p.text for p in seccion.footer.paragraphs if p.text.strip() and not p.text.strip().isdigit()]
    assert pie == Config().despacho.pie_fallo
    assert "PAGE" in seccion.footer._element.xml
    assert doc.styles["Normal"].font.name == "Bookman Old Style"
    assert doc.styles["Normal"].font.size == Pt(12)


def test_formato_gen_b_cuerpo(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    asunto = next(p for p in parrafos(ruta) if p.text.startswith("Procede el Despacho"))
    xml = asunto._p.xml
    assert 'w:line="360" w:lineRule="auto"' in xml
    assert 'w:before="283"' in xml or 'w:before="282"' in xml
    assert 'w:w w:val="114"' in xml and 'w:sz w:val="24"' in xml
    assert abs(asunto.paragraph_format.left_indent.pt - 4.44) <= 0.1
    assert abs(asunto.paragraph_format.right_indent.pt - 10.58) <= 0.1
    assert asunto.alignment == 3
    plantilla = next(p for p in parrafos(ruta) if p.text == formulas.COMPETENCIA_1)
    assert abs(plantilla.paragraph_format.left_indent.pt - 11.42) <= 0.1
    assert abs(plantilla.paragraph_format.right_indent.pt - 23.88) <= 0.1
    modelo = next(p for p in parrafos(ruta) if p.text.startswith("BLOQUE_TEXTO"))
    assert abs(modelo.paragraph_format.left_indent.pt - 14.18) <= 0.1


def test_formato_gen_b_titulo_del_juzgado_y_fecha(tmp_path, estado):
    ps = parrafos(render_fallo(tmp_path, estado, "B"))
    titulo, fecha = ps[0], ps[1]
    assert abs(titulo.paragraph_format.left_indent.pt - 197.21) <= 0.1
    assert abs(titulo.paragraph_format.first_line_indent.pt + 140.43) <= 0.1
    assert 'w:w w:val="114"' in titulo._p.xml and all(r.bold for r in titulo.runs)
    assert 'w:w w:val="109"' in fecha._p.xml and fecha.alignment == 1


def test_formato_gen_b_tabla(tmp_path, estado):
    doc = Document(render_fallo(tmp_path, estado, "B"))
    tabla = doc.tables[0]
    xml = tabla._tbl.xml
    assert 'w:top w:val="single" w:sz="4"' in xml
    ancho = [int(c.get(qn("w:w"))) / 20 for c in tabla._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert abs(ancho[0] - 120.39) <= 0.5 and abs(ancho[1] - 250.73) <= 0.5
    ind = tabla._tbl.tblPr.find(qn("w:tblInd"))
    assert abs(int(ind.get(qn("w:w"))) / 20 - 54.02) <= 0.1
    assert len(tabla.rows) == 7
    assert all(abs(f.height.pt - 21.8) <= 0.1 for f in tabla.rows)
    etiqueta = tabla.cell(0, 0).paragraphs[0]
    assert all(r.bold for r in etiqueta.runs)
    valor = tabla.cell(1, 1).paragraphs[0]
    assert valor.text == valor.text.upper() and not any(r.bold for r in valor.runs)


def test_formato_gen_b_merito_y_numerales(tmp_path, estado):
    ruta = render_fallo(tmp_path, estado, "B")
    ps = parrafos(ruta)
    nombre = Config().despacho.nombre_cuerpo
    merito = next(p for p in ps if p.text.startswith("En mérito de lo expuesto"))
    assert [r.text for r in merito.runs if r.bold] == [nombre]
    primero = next(i for i, p in enumerate(ps) if p.text.startswith("PRIMERO: REVOCAR"))
    assert [r.text for r in ps[primero].runs if r.bold] == ["PRIMERO: REVOCAR"]
    assert 'w:w w:val="104"' in ps[primero]._p.xml
    assert ps[primero + 1].text == "" and ps[primero + 2].text.startswith("SEGUNDO: AMPARAR")
    assert "ANA EJEMPLO PRUEBA" in [r.text for r in ps[primero + 2].runs if r.bold]
    tercero = next(i for i, p in enumerate(ps) if p.text.startswith("TERCERO: ORDENAR"))
    assert ps[tercero].text.endswith(":")
    assert [ps[tercero + k].text for k in (1, 2, 3, 4)] == ["", "a. La causa concreta de la restricción.", "", "b. Los recursos disponibles."]


def test_formato_gen_b_espacio_de_firma(tmp_path, estado):
    ps = parrafos(render_fallo(tmp_path, estado, "B"))
    cierre = next(i for i, p in enumerate(ps) if p.text == Config().despacho.cierre_fallo)
    firma = ps[cierre + 1]
    assert firma.text == "" and 'w:lineRule="exact"' in firma._p.xml and 'w:line="1292"' in firma._p.xml
    assert ps[cierre + 2].text == Config().despacho.juez and ps[cierre + 3].text == "JUEZ"
    assert all(r.bold and r.text for r in ps[cierre].runs + ps[cierre + 2].runs + ps[cierre + 3].runs)


def test_fecha_del_fallo_desde_la_decision(tmp_path):
    estado = construir_estado()
    estado["decisiones"][1]["fecha_fallo"] = "2026-11-06"
    assert lineas(render_fallo(tmp_path, estado, "B"))[1] == "Medellín, seis (06) de noviembre de dos mil veintiséis (2026)"


def test_etiqueta_de_decision_sobrescribe_encabezado(tmp_path):
    estado = construir_estado()
    estado["decisiones"][1]["etiqueta_encabezado"] = "CONFIRMA CON MODIFICACIONES"
    assert "Decisión | CONFIRMA CON MODIFICACIONES" in lineas(render_fallo(tmp_path, estado, "B"))


def test_fallo_sin_decision_falla(tmp_path, estado):
    estado["decisiones"] = [Decision(accion="rehacer_apertura", instruccion="x").model_dump(mode="json")]
    with pytest.raises(ValueError, match="decisión"):
        render.render_fallo(estado, Config(), tmp_path / "f.docx", hoy=HOY)


def test_referencia_local_si_no_existe_citas(monkeypatch, tmp_path, estado):
    monkeypatch.setitem(sys.modules, "tutela2.citas", None)
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert any("Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas" in linea for linea in texto)


def test_referencia_usa_citas_si_existe(monkeypatch, tmp_path, estado):
    import types

    falso = types.ModuleType("tutela2.citas")
    falso.formatear_referencia = lambda cv: f"REFERENCIA({cv.id})"
    monkeypatch.setitem(sys.modules, "tutela2.citas", falso)
    texto = lineas(render_fallo(tmp_path, estado, "B"))
    assert any("según lo dicho en REFERENCIA(c1) y reiterado en REFERENCIA(c1)." in linea for linea in texto)


def test_previo(tmp_path, estado):
    ruta = render.render_previo(estado, Config(plantilla_gen="B"), tmp_path / "sub" / "previo.docx")
    texto = lineas(ruta)
    plano = "\n".join(texto)
    for titulo in TITULOS["B"][:5]:
        assert t("B", titulo) in texto
    assert t("B", "VI. CASO CONCRETO") not in texto and "RESUELVE" not in texto
    assert not any(linea.startswith("Decisión") for linea in texto)
    assert formulas.COMPETENCIA_1 in texto and formulas.TRANSICION in texto
    assert "INFORME DE CITAS" in texto and "ALERTAS POR NODO" in texto
    assert "3 citas: 1 ok, 1 con alerta, 1 rechazada." in texto
    assert "Sentencia | Estado | Cobertura | M.P. (dataset) | URL | Motivos" in texto
    assert "T-200/22 | OK | 100 % | José Fernando Reyes Cuartas | https://example.test/T-200-22.htm | —" in texto
    assert "SU-082/95 | ALERTA | 60 % | Jorge Arango Mejía | — | Cobertura parcial" in texto
    assert "T-999 de 2020 | RECHAZADA | — | — | — | La sentencia no existe en el dataset" in texto
    assert "apertura" in texto and "ALERTA: alerta de apertura de ejemplo" in texto
    assert "QUOTE_C1 fragmento literal uno." in plano


def test_previo_gen_a_sin_competencia(tmp_path, estado):
    texto = lineas(render.render_previo(estado, Config(plantilla_gen="A"), tmp_path / "p.docx"))
    assert formulas.COMPETENCIA_1 not in texto
    assert "ASUNTO | TUTELA DE SEGUNDA INSTANCIA" in texto


def test_estado_minimo_muestra_marcadores_y_no_none(tmp_path):
    estado = {"ingesta": Ingesta(documentos=[]).model_dump(mode="json")}
    ruta = render.render_previo(estado, Config(), tmp_path / "p.docx")
    plano = "\n".join(lineas(ruta))
    assert "None" not in plano
    assert "⟦FALTA: impugnante⟧" in plano
    assert "⟦FALTA: fecha⟧" in plano


def test_estado_minimo_completa_metadatos_desde_ingesta_y_apertura(tmp_path):
    md = Metadatos(
        accionante="ANA EJEMPLO PRUEBA",
        fechas=Fechas(fallo_a_quo="2026-09-21"),
        juzgado_a_quo_numero=18,
        juzgado_a_quo_funcion="control_garantias",
        juzgado_a_quo_letras="Dieciocho",
    )
    estado = construir_estado()
    estado["metadatos"] = None
    estado["ingesta"] = Ingesta(documentos=[], metadatos=md).model_dump(mode="json")
    estado["apertura"]["metadatos"]["impugnante"] = "Ana Ejemplo Prueba"
    estado["apertura"]["metadatos"]["juzgado_a_quo"] = "Juzgado Dieciocho Penal Municipal de Ejemplo"
    asunto = next(linea for linea in lineas(render.render_previo(estado, Config(), tmp_path / "p.docx")) if linea.startswith("Procede el Despacho"))
    assert "presentada por Ana Ejemplo Prueba" in asunto
    assert "veintiuno (21) de septiembre de dos mil veintiséis (2026)" in asunto
    assert "por el Juzgado Dieciocho Penal Municipal con Función de Control de Garantías de Medellín" in asunto


def test_informe(tmp_path, estado):
    ruta = render.render_informe(estado, Config(), tmp_path / "informe_verificacion.docx")
    texto = lineas(ruta)
    for titulo in ("I. CITAS DE JURISPRUDENCIA", "II. CITAS NORMATIVAS (NO VERIFICADAS AUTOMÁTICAMENTE)",
                   "III. ALERTAS POR NODO", "IV. ERRORES BLOQUEANTES VIGENTES", "V. BITÁCORA DE LLAMADAS A LA IA"):
        assert titulo in texto
    assert "BLOQUEA: error vigente de ejemplo" in texto
    assert "ALERTA: alerta de apertura de ejemplo" in texto
    plano = "\n".join(texto)
    assert "apertura (intento 1)" in plano
    assert "b" * 64 in plano and "c" * 64 in plano
    assert "T-999 de 2020 | RECHAZADA" in plano


def test_informe_sin_errores_ni_bitacora(tmp_path):
    estado = {"ingesta": Ingesta(documentos=[]).model_dump(mode="json")}
    texto = lineas(render.render_informe(estado, Config(), tmp_path / "i.docx"))
    assert "No hay errores bloqueantes vigentes." in texto
    assert "No se registraron llamadas a la IA." in texto
    assert "Sin alertas." in texto


@pytest.mark.parametrize("compulsa", [True, False])
def test_declaracion_ia(tmp_path, compulsa):
    ruta = render.render_declaracion_ia(construir_estado(compulsa), Config(), tmp_path / "declaracion_ia.docx", hoy=HOY)
    texto = lineas(ruta)
    plano = "\n".join(texto)
    assert "Medellín, veintiuno (21) de octubre de dos mil veintiséis (2026)" in texto
    assert "artículo 10 del Acuerdo PCSJA24-12243" in plano
    assert "Herramienta | tutela2, versión" in plano
    assert "anthropic / claude-opus-5-5" in plano
    assert "apertura@v1" in plano and "a" * 64 in plano and "2026-10-19T10:00:00" in plano
    assert "ANTECEDENTES DEL CASO | IA |" in plano
    assert "CASO CONCRETO | IA |" in plano
    assert "RESUELVE | humano + plantilla + IA |" in plano
    assert "ASUNTO | plantilla + IA |" in plano and "Encabezado (despacho, fecha y cuadro de partes) | plantilla + IA |" in plano
    assert "Empresa proveedora | Anthropic PBC" in plano
    assert "ANEXO: PROMPTS E INSTRUCCIONES UTILIZADAS" in plano
    assert "Instrucciones del mensaje (sin documentos):" in plano
    assert ("OTRAS DETERMINACIONES | plantilla |" in plano) is compulsa
    assert "Decidido por | Juez Ejemplo" in texto
    assert "Fecha | 2026-10-20" in texto
    assert "Sentido | REVOCA" in texto
    assert "Eje de la decisión | El eje de la decisión de ejemplo." in texto


def test_declaracion_ia_anexo_transcribe_el_prompt_vigente_y_las_instrucciones(tmp_path):
    from tutela2 import prompts

    cfg = Config()
    texto, pid = prompts.prompt_para("apertura", cfg)
    estado = construir_estado()
    estado["bitacora"][0].update(
        prompt_id=pid,
        sha256_instrucciones=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        instrucciones="=== EXTENSION ===\nantecedentes: entre 510 y 1140 palabras",
    )
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, cfg, tmp_path / "d.docx", hoy=HOY)))
    assert texto.splitlines()[0] in plano and "antecedentes: entre 510 y 1140 palabras" in plano
    assert "no coincide con la huella" not in plano


def test_declaracion_ia_anexo_advierte_si_el_prompt_cambio(tmp_path):
    plano = "\n".join(lineas(render.render_declaracion_ia(construir_estado(), Config(), tmp_path / "d.docx", hoy=HOY)))
    assert "no coincide con la huella" in plano


def test_declaracion_ia_usa_fecha_del_fallo(tmp_path):
    estado = construir_estado()
    estado["decisiones"][1]["fecha_fallo"] = "2026-10-15"
    texto = lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY))
    assert "Medellín, quince (15) de octubre de dos mil veintiséis (2026)" in texto


def test_declaracion_ia_sin_fecha_ni_decision(tmp_path):
    estado = construir_estado()
    del estado["decisiones"][1]["fecha"]
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY)))
    assert "Fecha | no consta" in plano
    estado["decisiones"] = []
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d2.docx", hoy=HOY)))
    assert "Aún no se ha registrado una decisión humana." in plano


def test_requerimiento_lista_faltantes(tmp_path):
    ing = Ingesta(
        documentos=[],
        metadatos=construir_metadatos(),
        faltantes=["impugnacion", "auto_concede_impugnacion", "rol_desconocido"],
    )
    cfg = Config()
    cfg.despacho.correo = "despacho@example.test"
    ruta = render.render_requerimiento(ing, cfg, tmp_path / "requerimiento.docx", hoy=HOY)
    texto = lineas(ruta)
    plano = "\n".join(texto)
    assert "Señores: Juzgado Dieciocho Penal Municipal de Ejemplo" in texto
    assert "05001999900120260099900" in plano
    assert "Escrito de impugnación" in texto
    assert "Auto que concede la impugnación" in texto
    assert "Rol_desconocido" in texto
    assert "impugnacion" not in plano.replace("Escrito de impugnación", "")
    assert texto[-1] == "despacho@example.test"


def test_requerimiento_sin_faltantes(tmp_path):
    ing = Ingesta(documentos=[], metadatos=construir_metadatos())
    texto = lineas(render.render_requerimiento(ing, Config(), tmp_path / "r.docx", hoy=HOY))
    assert "No se identificaron documentos faltantes en el expediente recibido." in texto


def test_cierre_del_fallo_viaja_unido(tmp_path, estado):
    ps = parrafos(render_fallo(tmp_path, estado, "B"))
    cierre = next(i for i, p in enumerate(ps) if p.text == Config().despacho.cierre_fallo)
    for p in ps[cierre - 1 : cierre + 3]:
        assert p.paragraph_format.keep_with_next is True


@pytest.mark.parametrize("gen", ["A", "B"])
def test_idioma_es_co(tmp_path, estado, gen):
    ruta = render_fallo(tmp_path, estado, gen)
    langs = Document(str(ruta)).styles.element.findall(".//" + qn("w:lang"))
    assert langs and all(x.get(qn("w:val")) == "es-CO" for x in langs)


def test_resumen_citas_una_rechazada(tmp_path, estado):
    ruta = render.render_previo(estado, Config(plantilla_gen="B"), tmp_path / "p.docx")
    assert "1 rechazada." in "\n".join(lineas(ruta))


def _estado_con_fallo(tmp_path):
    from tutela2 import fallos

    fallos.registrar(tmp_path, {"nodo": "caso_concreto", "fecha": "2026-11-02T10:00:00+00:00", "proveedor": "anthropic",
                                "modelo_pedido": "modelo-x", "prompt_id": "p", "sha256_entrada": "e" * 64,
                                "tipo_error": "ErrorLLM", "error": "respuesta truncada de ejemplo"})
    return {**construir_estado(), "caso_dir": str(tmp_path)}


def test_informe_y_declaracion_listan_llamadas_fallidas(tmp_path):
    estado = _estado_con_fallo(tmp_path)
    informe = "\n".join(lineas(render.render_informe(estado, Config(), tmp_path / "i.docx")))
    declaracion = "\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY)))
    for plano in (informe, declaracion):
        assert "caso_concreto" in plano and "respuesta truncada de ejemplo" in plano and "modelo-x" in plano


def _llamada(modelo_pedido: str, modelo_efectivo: str | None, intento: int = 1) -> dict:
    return LlamadaIA(
        nodo="apertura", intento=intento, proveedor="anthropic", modelo_pedido=modelo_pedido,
        modelo_efectivo=modelo_efectivo, prompt_id="apertura@v1", sha256_instrucciones="a" * 64,
        sha256_entrada="b" * 64, sha256_salida="c" * 64, fecha="2026-10-19T10:00:00",
    ).model_dump(mode="json")


def test_declaracion_modelos_usados_desde_la_bitacora(tmp_path):
    estado = construir_estado()
    estado["bitacora"] = [
        _llamada("claude-haiku-5-5", "claude-sonnet-5-5"),
        _llamada("claude-opus-5-5", None, 2),
        _llamada("claude-sonnet-5-5", "claude-sonnet-5-5", 3),
    ]
    cfg = Config(llm=LLMConfig(modelo="claude-fable-5-1"))
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, cfg, tmp_path / "d.docx", hoy=HOY)))
    assert "Modelos usados | claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5" in plano
    assert "Modelo configurado" not in plano and "claude-fable-5-1" not in plano


def _llamada_jev(nodo: str) -> dict:
    return llamada_ia(nodo, "estado", {"p": {}}, RespuestaJev("jev-1.14.0", {}, 10, 1), "jev-latest")


def _linea(plano: str, prefijo: str) -> str:
    return next(linea for linea in plano.splitlines() if linea.startswith(prefijo))


def test_declaracion_con_llamadas_de_jev_nombra_a_cada_proveedor_con_sus_modelos(tmp_path):
    estado = construir_estado()
    estado["bitacora"] = [_llamada("claude-sonnet-5-5", "claude-sonnet-5-5"), _llamada_jev("roles"), _llamada_jev("metadatos")]
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY)))
    assert "Empresa proveedora | Anthropic PBC; TypeSafe AI" in plano
    assert "Modelos usados | Anthropic PBC: claude-sonnet-5-5; TypeSafe AI: jev-latest, jev-1.14.0" in plano
    uso = _linea(plano, "Uso |")
    assert "TypeSafe AI" in uso and "rol de cada documento" in uso and "sentido de la decisión" in uso
    assert "fragmentos" in uso and "Redacción de antecedentes" in uso


def test_declaracion_con_jev_solo_menciona_lo_que_se_le_pidio(tmp_path):
    estado = construir_estado()
    estado["bitacora"] = [_llamada("claude-sonnet-5-5", "claude-sonnet-5-5"), _llamada_jev("roles")]
    uso = _linea("\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY))), "Uso |")
    assert "rol de cada documento" in uso and "sentido de la decisión" not in uso
    estado["bitacora"] = [_llamada("claude-sonnet-5-5", "claude-sonnet-5-5"), _llamada_jev("metadatos")]
    uso = _linea("\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d2.docx", hoy=HOY))), "Uso |")
    assert "sentido de la decisión" in uso and "rol de cada documento" not in uso


def test_declaracion_sin_llamadas_de_jev_no_menciona_a_typesafe(tmp_path):
    plano = "\n".join(lineas(render.render_declaracion_ia(construir_estado(), Config(), tmp_path / "d.docx", hoy=HOY)))
    assert "TypeSafe" not in plano and "Jev" not in plano
    assert "Empresa proveedora | Anthropic PBC" in plano and "Modelos usados | claude-opus-5-5" in plano


def test_declaracion_marca_la_llamada_fallida_de_jev(tmp_path):
    estado = construir_estado()
    estado["bitacora"].append(llamada_fallida("roles", "e", {"p": {}}, "jev-latest", ErrorJev("Jev respondió 500: boom", enviada=True)))
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, Config(), tmp_path / "d.docx", hoy=HOY)))
    assert "jev / jev-latest" in plano and "Jev respondió 500: boom" in plano
    assert "Empresa proveedora | Anthropic PBC; TypeSafe AI" in plano


def test_declaracion_modelos_usados_sin_llamadas_dice_ninguno(tmp_path):
    estado = construir_estado()
    estado["bitacora"] = []
    cfg = Config(llm=LLMConfig(modelo="claude-haiku-5-5"))
    plano = "\n".join(lineas(render.render_declaracion_ia(estado, cfg, tmp_path / "d.docx", hoy=HOY)))
    assert "Modelos usados | ninguno" in plano and "claude-haiku-5-5" not in plano


def test_informe_lista_citas_normativas_sin_verificar(tmp_path):
    estado = construir_estado()
    estado["apertura"]["antecedentes_hechos"] = "Se invocó el artículo 25 del Código General del Proceso."
    estado["apertura"]["impugnacion"] = "Reclama el artículo 25 del Código General del Proceso y la Ley 1751 de 2015."
    estado["consideraciones"]["procedibilidad"] = "Según el artículo 86 de la Constitución Política."
    estado["caso"]["conclusion"] = "Por el artículo 32 del Decreto 2591 de 1991."
    texto = lineas(render.render_informe(estado, Config(), tmp_path / "i.docx"))
    plano = "\n".join(texto)
    assert "NO se verifican automáticamente" in plano
    assert plano.count("artículo 25 del Código General del Proceso |") == 1
    assert "artículo 25 del Código General del Proceso | Antecedentes, Impugnación |" in plano
    assert "Ley 1751 de 2015 | Impugnación |" in plano
    assert "artículo 86 de la Constitución Política | Consideraciones |" in plano
    assert "artículo 32 del Decreto 2591 de 1991 | Caso concreto |" in plano


def test_informe_sin_citas_normativas(tmp_path):
    texto = lineas(render.render_informe(construir_estado(), Config(), tmp_path / "i.docx"))
    assert "No se detectaron citas normativas en el texto generado." in texto
