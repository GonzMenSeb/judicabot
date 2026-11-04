from __future__ import annotations

import hashlib
import zipfile
from datetime import date
from io import BytesIO

import pytest
from docx import Document
from test_graph import DECISION, Verificador, ingesta_sintetica

from tutela2 import api, expediente, ingest, render, salidas
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.models import (
    MSG_DECIDIDO_POR_PLACEHOLDER,
    MSG_DECIDIDO_POR_VACIO,
    Decision,
    Doc,
    Metadatos,
    Pagina,
)

PRINCIPAL = "02SegundaInstancia/C01Principal"
ACTA = b"%PDF-1.4 acta de ejemplo"
COMPULSA = {"organo": "Comisión Seccional de Disciplina Judicial de Antioquia", "respecto_de": "la funcionaria encargada"}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


def _caso(tmp_path, monkeypatch, con_acta: bool, ajustar=None):
    carpeta = tmp_path / "caso-x"
    (carpeta / "insumos" / "2a").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    ing = ingesta_sintetica()
    if con_acta:
        (carpeta / "insumos" / "2a" / "001ActaRepartoSegunda.pdf").write_bytes(ACTA)
    else:
        ing.documentos = [d for d in ing.documentos if d.rol != "acta_reparto_2a"]
    if ajustar:
        ajustar(ing)
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ing, raising=False)
    return carpeta


def test_numerados():
    assert expediente.numerados(["ActaRepartoSegunda.pdf", "AutoAsumeSegunda202600530.docx"]) == [
        "001ActaRepartoSegunda.pdf",
        "002AutoAsumeSegunda202600530.docx",
    ]


def test_numerados_reserva_el_001_para_el_acta():
    assert expediente.numerados([None, "AutoAsumeSegunda1.docx", "FalloSegunda1.docx"]) == [
        "002AutoAsumeSegunda1.docx",
        "003FalloSegunda1.docx",
    ]
    assert expediente.numerados(["ActaRepartoSegunda.pdf", "AutoAsumeSegunda1.docx"])[0] == "001ActaRepartoSegunda.pdf"


def test_previos_sin_acta_empiezan_en_002(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=False)
    r = api.nuevo(carpeta)
    assert r["estado"] == "revision"
    assert r["salidas"] == [f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx"]


def _parrafos(ruta) -> list[str]:
    return [p.text for p in Document(ruta).paragraphs]


def test_sin_acta_el_expediente_completo_sigue_en_002_y_los_adjuntos_son_pdf(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=False)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    decision = {**DECISION, "generar_formato": True, "compulsa": COMPULSA, "fecha_fallo": "2026-10-20", "fecha_oficio": "2026-10-21"}
    r = api.decidir(carpeta, decision)
    assert r["estado"] == "terminado", r["error"]
    principal = sorted(s for s in r["salidas"] if s.startswith(PRINCIPAL))
    assert principal == [
        f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx",
        f"{PRINCIPAL}/003FalloSegunda202600001.docx",
        f"{PRINCIPAL}/004FormatoCalificacion202600001.docx",
    ]
    base = carpeta / "salidas" / "borradores_correo"
    assert "Adjunto: 003FalloSegunda202600001.pdf" in _parrafos(base / "NotificacionFalloPartes.docx")
    assert "Adjunto: 004FormatoCalificacion202600001.pdf" in _parrafos(base / "EnvioFormatoCalidad.docx")
    assert "Adjunto: 003FalloSegunda202600001.pdf" in _parrafos(base / "RemisionCompulsaCopias.docx")


def test_auto_firmante_del_formulario_llega_al_auto_generado(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    api.nuevo(carpeta)
    api.revisar(carpeta, auto={"firmante": "Juan Prueba Perez", "cargo_firmante": "Juez (E)"})
    efectivo = expediente.auto_efectivo(carpeta, Metadatos())
    assert (efectivo.firmante, efectivo.cargo_firmante) == ("Juan Prueba Perez", "Juez (E)")
    auto = carpeta / "salidas" / PRINCIPAL / "002AutoAsumeSegunda202600001.docx"
    assert _parrafos(auto)[-2:] == ["JUAN PRUEBA PEREZ", "JUEZ (E)"]


def test_arbol_completo_con_formato_y_compulsa(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    assert api.nuevo(carpeta)["salidas"] == [
        f"{PRINCIPAL}/001ActaRepartoSegunda.pdf",
        f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx",
    ]
    assert (carpeta / "salidas" / PRINCIPAL / "001ActaRepartoSegunda.pdf").read_bytes() == ACTA
    assert api.iniciar(carpeta)["estado"] == "esperando_decision"
    decision = {**DECISION, "generar_formato": True, "compulsa": COMPULSA, "fecha_fallo": "2026-10-20", "fecha_oficio": "2026-10-21"}
    r = api.decidir(carpeta, decision)
    assert r["estado"] == "terminado", r["error"]
    assert r["salidas"] == sorted(
        [
            f"{PRINCIPAL}/001ActaRepartoSegunda.pdf",
            f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx",
            f"{PRINCIPAL}/003FalloSegunda202600001.docx",
            f"{PRINCIPAL}/004FormatoCalificacion202600001.docx",
            "por_radicar/OficioRemiteCorteConstitucional.docx",
            "borradores_correo/NotificacionFalloPartes.docx",
            "borradores_correo/EnvioFormatoCalidad.docx",
            "borradores_correo/RemisionCompulsaCopias.docx",
            "trabajo/previo.docx",
            "trabajo/informe_verificacion.docx",
            "trabajo/declaracion_ia.docx",
        ]
    )
    hashes = r["resumen"]["salidas"]
    assert hashes
    for rel, sha in hashes.items():
        assert hashlib.sha256((carpeta / "salidas" / rel).read_bytes()).hexdigest() == sha


def test_sin_formato_no_hay_004_ni_envio(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    r = api.decidir(carpeta, DECISION)
    assert r["estado"] == "terminado", r["error"]
    assert not any(s.startswith(f"{PRINCIPAL}/004") for s in r["salidas"])
    assert "borradores_correo/EnvioFormatoCalidad.docx" not in r["salidas"]
    assert "borradores_correo/RemisionCompulsaCopias.docx" not in r["salidas"]


def test_resolver_rechaza_rutas_fuera(tmp_path):
    (tmp_path / "salidas" / "trabajo").mkdir(parents=True)
    (tmp_path / "salidas" / "trabajo" / "a.docx").write_bytes(b"x")
    assert salidas.resolver(tmp_path, "trabajo/a.docx").read_bytes() == b"x"
    for malo in ("../x", "/etc/passwd", "trabajo/../../x", "..\\x", ""):
        with pytest.raises(ValueError):
            salidas.resolver(tmp_path, malo)
    with pytest.raises(FileNotFoundError):
        salidas.resolver(tmp_path, "trabajo/no.docx")


def test_resolver_rechaza_enlace_que_escapa(tmp_path):
    (tmp_path / "salidas").mkdir()
    (tmp_path / "secreto.txt").write_text("s")
    (tmp_path / "salidas" / "enlace.txt").symlink_to(tmp_path / "secreto.txt")
    with pytest.raises(ValueError):
        salidas.resolver(tmp_path, "enlace.txt")


def test_zip_y_listar(tmp_path):
    (tmp_path / "salidas" / "a" / "b").mkdir(parents=True)
    (tmp_path / "salidas" / "a" / "b" / "c.txt").write_text("c")
    (tmp_path / "salidas" / "d.txt").write_text("d")
    assert salidas.listar(tmp_path) == ["a/b/c.txt", "d.txt"]
    assert salidas.listar(tmp_path / "nada") == []
    with zipfile.ZipFile(BytesIO(salidas.zip_bytes(tmp_path))) as z:
        assert sorted(z.namelist()) == ["a/b/c.txt", "d.txt"]


def test_buzon_del_juzgado_desde_la_ultima_notificacion():
    ing = ingesta_sintetica()
    texto = "Asunto: notificación\nDe: Juzgado Origen <juzgado.origen@cendoj.ramajudicial.gov.co>\nPara: otra@ejemplo.com\n"
    ing.documentos.append(
        Doc(doc_id="1a-090", ruta="n.txt", nombre="n.txt", instancia="1a", rol="notificacion", sha256="0", paginas=[Pagina(n=1, texto=texto)])
    )
    assert expediente._buzon_juzgado(ing) == "juzgado.origen@cendoj.ramajudicial.gov.co"
    assert expediente._buzon_juzgado(ingesta_sintetica()) is None


def _notificacion(doc_id: str, ruta: str, correo: str) -> Doc:
    return Doc(
        doc_id=doc_id, ruta=ruta, nombre=ruta, instancia="1a", rol="notificacion", sha256=doc_id,
        paginas=[Pagina(n=1, texto=f"De: Juzgado <{correo}>\nPara: otra@ejemplo.com\n")],
    )


@pytest.mark.parametrize("variante", ["ajeno", "revisar", "ruido"])
def test_buzon_del_juzgado_ignora_notificacion_posterior_no_confiable(variante):
    ing = ingesta_sintetica()
    valida = _notificacion("1a-090", "a/001.txt", "juzgado.origen@cendoj.ramajudicial.gov.co")
    posterior = _notificacion("1a-091", "a/009.txt", "otro.despacho@ejemplo.gov.co")
    if variante == "ajeno":
        ing.docs_ajenos = [posterior.doc_id]
    elif variante == "revisar":
        ing.docs_revisar = [posterior.doc_id]
    else:
        posterior.ruido = True
    ing.documentos += [valida, posterior]
    assert expediente._buzon_juzgado(ing) == "juzgado.origen@cendoj.ramajudicial.gov.co"
    ing.documentos.remove(valida)
    assert expediente._buzon_juzgado(ing) is None


def _doc_extra(doc_id: str, nombre: str, **cambios) -> Doc:
    return Doc(
        doc_id=doc_id, ruta=f"1a/{nombre}", nombre=nombre, instancia="1a", rol="memorial", sha256=doc_id,
        paginas=[Pagina(n=1, texto="Texto de un documento adicional del expediente.")], **cambios,
    )


def _congelar_hoy(monkeypatch):
    class _Hoy(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 4)

    monkeypatch.setattr(expediente, "date", _Hoy)


def _capturar_pendientes(monkeypatch) -> list[list[str] | None]:
    vistos: list[list[str] | None] = []
    original = render.render_informe

    def espia(estado, cfg, ruta, pendientes=None):
        vistos.append(pendientes)
        return original(estado, cfg, ruta, pendientes=pendientes)

    monkeypatch.setattr(render, "render_informe", espia)
    return vistos


def _seccion_pendientes_del_informe(carpeta) -> list[str]:
    parrafos = _parrafos(carpeta / "salidas" / "trabajo" / "informe_verificacion.docx")
    inicio = next(i for i, p in enumerate(parrafos) if p.endswith(" PENDIENTES Y VALORES POR DEFECTO"))
    fin = next(i for i, p in enumerate(parrafos) if p.endswith(" BITÁCORA DE LLAMADAS A LA IA"))
    return parrafos[inicio + 1 : fin]


def test_faltas_del_docx_cubre_cuerpo_tablas_anidadas_encabezado_y_pie(tmp_path):
    doc = Document()
    doc.add_paragraph("Sin marcador ⟦otra cosa⟧ ni nada.")
    partido = doc.add_paragraph()
    partido.add_run("Texto ⟦FALTA: nom")
    partido.add_run("bre⟧ y más")
    doc.add_paragraph("repetido ⟦FALTA: nombre⟧")
    celda = doc.add_table(rows=1, cols=2).cell(0, 1)
    celda.text = "⟦FALTA: en tabla⟧"
    celda.add_table(rows=1, cols=1).cell(0, 0).text = "⟦FALTA: tabla anidada⟧"
    seccion = doc.sections[0]
    seccion.header.paragraphs[0].text = "⟦FALTA: encabezado⟧"
    seccion.footer.paragraphs[0].text = "⟦FALTA: pie⟧"
    ruta = tmp_path / "d.docx"
    doc.save(ruta)
    assert expediente._faltas_en(ruta) == [
        "⟦FALTA: nombre⟧",
        "⟦FALTA: en tabla⟧",
        "⟦FALTA: tabla anidada⟧",
        "⟦FALTA: encabezado⟧",
        "⟦FALTA: pie⟧",
    ]
    vacio = tmp_path / "v.docx"
    Document().save(vacio)
    assert expediente._faltas_en(vacio) == []


def _decision(**cambios) -> Decision:
    return Decision.model_validate({**DECISION, **cambios})


def test_pendientes_fijos_completo_no_lista_nada():
    assert expediente._pendientes_fijos(_decision(fecha_fallo="2026-10-20"), ingesta_sintetica(), True, "2026-10-20") == []


def test_pendientes_fijos_fecha_por_defecto_y_oficio():
    ing = ingesta_sintetica()
    [con_oficio] = expediente._pendientes_fijos(_decision(fecha_oficio="2026-10-21"), ing, True, "2026-11-04")
    [sin_oficio] = expediente._pendientes_fijos(_decision(), ing, True, "2026-11-04")
    assert con_oficio == "Fecha del fallo: no se indicó; se usó la fecha de hoy (4 de noviembre de 2026)."
    assert sin_oficio == con_oficio + " El oficio a la Corte Constitucional usa la misma fecha."


def test_pendientes_fijos_formato_solo_si_se_genera():
    ing = ingesta_sintetica()
    base = _decision(fecha_fallo="2026-10-20")
    assert expediente._pendientes_fijos(base, ing, True, "2026-10-20") == []
    assert expediente._pendientes_fijos(base.model_copy(update={"generar_formato": True}), ing, True, "2026-10-20") == [
        "Formato de calidad: se generó sin puntajes ni motivación; los completa quien evalúa."
    ]


@pytest.mark.parametrize(
    ("valor", "mensaje"),
    [
        ("", MSG_DECIDIDO_POR_VACIO),
        ("  ", MSG_DECIDIDO_POR_VACIO),
        ("John Doe", MSG_DECIDIDO_POR_PLACEHOLDER),
        ("caso_sintetico", MSG_DECIDIDO_POR_PLACEHOLDER),
        ("Prueba", MSG_DECIDIDO_POR_PLACEHOLDER),
    ],
)
def test_pendientes_fijos_decidido_por_vacio_o_de_prueba(valor, mensaje):
    decision = _decision(decidido_por=valor, fecha_fallo="2026-10-20")
    assert expediente._pendientes_fijos(decision, ingesta_sintetica(), True, "2026-10-20") == [mensaje]


def test_pendientes_fijos_acta_ausente_por_documento_o_por_ingesta():
    decision = _decision(fecha_fallo="2026-10-20")
    esperado = [
        "Acta de reparto de segunda instancia: no se encontró; el expediente se generó sin ella "
        "y la numeración empieza en 002."
    ]
    assert expediente._pendientes_fijos(decision, ingesta_sintetica(), False, "2026-10-20") == esperado
    ing = ingesta_sintetica()
    ing.esperados_faltantes = ["acta_reparto_2a"]
    assert expediente._pendientes_fijos(decision, ing, True, "2026-10-20") == esperado
    ing.esperados_faltantes = ["auto_admisorio"]
    assert expediente._pendientes_fijos(decision, ing, True, "2026-10-20") == []


def test_pendientes_fijos_documentos_revisar_y_ajenos():
    ing = ingesta_sintetica()
    ing.documentos += [
        _doc_extra("1a-050", "CartaAlJuzgado.pdf"),
        _doc_extra("1a-051", "Escaneo.pdf", ruido=True),
        _doc_extra("1a-052", "OtroCaso.pdf"),
        _doc_extra("1a-053", "OtroCasoRevisado.pdf"),
    ]
    ing.docs_revisar = ["1a-050", "1a-051", "1a-053", "9z-999"]
    ing.docs_ajenos = ["1a-052", "1a-053"]
    assert expediente._pendientes_fijos(_decision(fecha_fallo="2026-10-20"), ing, True, "2026-10-20") == [
        "Documento para revisar incluido en el análisis con una marca de advertencia: CartaAlJuzgado.pdf.",
        "Documento para revisar excluido del análisis: Escaneo.pdf.",
        "Documento para revisar excluido del análisis: OtroCasoRevisado.pdf.",
        "Documento para revisar excluido del análisis: 9z-999.",
        "Documento ajeno excluido del análisis: OtroCaso.pdf.",
        "Documento ajeno excluido del análisis: OtroCasoRevisado.pdf.",
    ]


@pytest.mark.parametrize("variante", ["ajeno", "revisar", "ruido"])
def test_acta_no_confiable_no_se_copia_ni_ocupa_el_001(tmp_path, monkeypatch, variante):
    def ajustar(ing):
        acta = next(d for d in ing.documentos if d.rol == "acta_reparto_2a")
        if variante == "ajeno":
            ing.docs_ajenos = [acta.doc_id]
        elif variante == "revisar":
            ing.docs_revisar = [acta.doc_id]
        else:
            acta.ruido = True

    vistos = _capturar_pendientes(monkeypatch)
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True, ajustar=ajustar)
    assert api.nuevo(carpeta)["salidas"] == [f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx"]
    api.iniciar(carpeta)
    r = api.decidir(carpeta, {**DECISION, "fecha_fallo": "2026-10-20"})
    assert r["estado"] == "terminado", r["error"]
    assert not any("ActaRepartoSegunda" in s for s in r["salidas"])
    assert f"{PRINCIPAL}/003FalloSegunda202600001.docx" in r["salidas"]
    [pendientes] = vistos
    assert any(p.startswith("Acta de reparto de segunda instancia: no se encontró") for p in pendientes)


def test_informe_lista_pendientes_y_valores_por_defecto(tmp_path, monkeypatch):
    def ajustar(ing):
        ing.documentos += [_doc_extra("1a-050", "CartaAlJuzgado.pdf"), _doc_extra("1a-052", "OtroCaso.pdf")]
        ing.docs_revisar = ["1a-050"]
        ing.docs_ajenos = ["1a-052"]

    _congelar_hoy(monkeypatch)
    vistos = _capturar_pendientes(monkeypatch)
    carpeta = _caso(tmp_path, monkeypatch, con_acta=False, ajustar=ajustar)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    decision = {**DECISION, "generar_formato": True, "decidido_por": "caso_sintetico"}
    r = api.decidir(carpeta, decision)
    assert r["estado"] == "terminado", r["error"]

    [pendientes] = vistos
    fijos = [
        "Fecha del fallo: no se indicó; se usó la fecha de hoy (4 de noviembre de 2026)."
        " El oficio a la Corte Constitucional usa la misma fecha.",
        "Formato de calidad: se generó sin puntajes ni motivación; los completa quien evalúa.",
        MSG_DECIDIDO_POR_PLACEHOLDER,
        "Acta de reparto de segunda instancia: no se encontró; el expediente se generó sin ella "
        "y la numeración empieza en 002.",
        "Documento para revisar incluido en el análisis con una marca de advertencia: CartaAlJuzgado.pdf.",
        "Documento ajeno excluido del análisis: OtroCaso.pdf.",
    ]
    assert pendientes[: len(fijos)] == fijos
    faltas = pendientes[len(fijos) :]
    esperadas = [
        "003FalloSegunda202600001.docx: ⟦FALTA: juzgado a quo⟧",
        "004FormatoCalificacion202600001.docx: ⟦FALTA: fecha de admisión⟧",
        "NotificacionFalloPartes.docx: ⟦FALTA: destinatarios⟧",
    ]
    posiciones = [faltas.index(e) for e in esperadas]
    assert posiciones == sorted(posiciones)
    assert all(": ⟦FALTA" in f for f in faltas)
    assert not any(f.startswith(("previo.docx", "informe_verificacion.docx")) for f in faltas)
    assert len(pendientes) == len(set(pendientes))
    assert _seccion_pendientes_del_informe(carpeta) == pendientes


def test_informe_completo_solo_lista_los_marcadores_de_los_documentos(tmp_path, monkeypatch):
    vistos = _capturar_pendientes(monkeypatch)
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    r = api.decidir(carpeta, {**DECISION, "fecha_fallo": "2026-10-20"})
    assert r["estado"] == "terminado", r["error"]
    [pendientes] = vistos
    assert all(": ⟦FALTA" in p for p in pendientes)


def test_pendientes_no_incluyen_el_borrador_previo(tmp_path, monkeypatch):
    vistos = _capturar_pendientes(monkeypatch)
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    previo = Document()
    previo.add_paragraph("⟦FALTA: solo en el previo⟧")
    previo.save(carpeta / "salidas" / "trabajo" / "previo.docx")
    r = api.decidir(carpeta, {**DECISION, "fecha_fallo": "2026-10-20"})
    assert r["estado"] == "terminado", r["error"]
    [pendientes] = vistos
    assert not any("solo en el previo" in p for p in pendientes)
