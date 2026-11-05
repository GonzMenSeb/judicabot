from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter

from tutela2 import eventos, ingest
from tutela2.config import Config
from tutela2.ingest import (
    ROLES_ESPERADOS,
    ROLES_OBLIGATORIOS,
    extraer_cuis,
    fechas_en,
    ingerir,
    reaplicar,
    texto_para_llm,
)
from tutela2.models import Ingesta

CUI = "05001408803320270000100"
OTRO_CUI = "76001310300820150054300"

ACTA = """\
                         ACTA INDIVIDUAL DE REPARTO                          Fecha: 27/03/2027 3:30:10 p. m.
NÚMERO RADICACIÓN:
                                   {rad}  CLASE PROCESO: {clase} NÚMERO DESPACHO: 003
        TIPO ID          IDENTIFICACIÓN                    NOMBRE                APELLIDO                  PARTE
                                                  ENTIDAD DE PRUEBA S.A. DE MEDELLIN                    DEMANDADO/INDICIADO/CAUS
                                                                                                        ANTE
CÉDULA DE CIUDADANIA                      12345678 MARIA                   PRUEBA UNO                    DEMANDANTE/ACCIONANTE
NIT                                       80000000019 OTRA EMPRESA DE PRUEBA                             DEMANDADO/INDICIADO/CAUS
"""

ESCRITO = "Medellín, 9 de febrero de 2027\nSeñor JUEZ CONSTITUCIONAL (REPARTO)\nACCIÓN DE TUTELA\nAccionante: MARIA PRUEBA\nHECHOS\n1. Algo ocurrió.\nPRETENSIONES\nSolicito amparo.\n"

ADMISORIO = (
    f"CONSTANCIA. Señora Juez, se recibió la acción de tutela.\nJUZGADO TREINTA Y TRES PENAL MUNICIPAL\n"
    f"Medellín, veintitrés (23) de febrero de dos mil veintisiete (2027)\nRadicado: {CUI}\nSE ADMITE la presente acción de tutela. Notifíquese.\n"
)


def fallo(nombre_juzgado: str, cui: str = CUI) -> str:
    cabecera = (
        f"{nombre_juzgado}\nMedellín, doce (12) de marzo de dos mil veintisiete (2027)\nRadicado {cui}\n"
        "Accionante MARIA PRUEBA. Acción de tutela. ANTECEDENTES. CONSIDERACIONES. Competencia. RESUELVE: PRIMERO. Niega el amparo.\n"
    )
    return "\f".join([cabecera] + ["relleno de la providencia " * 100] * 5)


FALLO = fallo(
    "JUZGADO TREINTA Y TRES PENAL MUNICIPAL CON FUNCIONES DE CONTROL DE GARANTÍAS DE MEDELLÍN"
)

IMPUGNACION = "Outlook Radicación de impugnación a la sentencia\nDesde Maria Prueba <maria@correo.com>\nFecha Lun 2027-03-22 09:05\nPara Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co>\nAdjunto escrito.\n"

CONCEDE = f"JUZGADO TREINTA Y TRES PENAL MUNICIPAL\nMedellín, veintisiete (27) de marzo de dos mil veintisiete (2027)\nRadicado: {CUI}\nConcédase la impugnación interpuesta.\n"

NOTIFICA = "Outlook Comunicación de la sentencia\nDesde Juzgado 33 Penal Municipal <pmpal33med@cendoj.ramajudicial.gov.co>\nFecha Mié 2027-03-17 15:20\nPara Maria <maria@correo.com>\nCordial saludo.\n"

P1 = "01PrimeraInstancia/C01Principal/"
P2 = "02SegundaInstancia/C01Principal/"


def escribir(base: Path, rel: str, texto: str) -> Path:
    ruta = base / "insumos" / rel
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def pdf_en_blanco(ruta: Path, paginas: int = 1) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=200, height=200)
    with ruta.open("wb") as f:
        w.write(f)


def por_nombre(ing: Ingesta, nombre: str):
    return next(d for d in ing.documentos if d.nombre == nombre)


@pytest.mark.parametrize(
    "texto,esperados",
    [
        ("Radicado 05001 40 88 033 2027 00123 00", ["05001408803320270012300"]),
        ("Radicado: 050014088033 2027-00123 00", ["05001408803320270012300"]),
        ("050014088034-2027-00456-00", ["05001408803420270045600"]),
        ("05001408803320270012301", ["05001408803320270012301"]),
        ("05001 40 09 035 2027 00789 00​​", ["05001400903520270078900"]),
        ("radicado 050014009035202700789", []),
        ("050014088034-2027-00456", []),
        ("12 050014088034-2027-00456-00", []),
        ("050014088033202700123000", []),
        ("0b7c1d44-5e21-4a9f-9c3d-12ab34cd56ef 7113920", []),
        (
            "05001408803320270012300 y 05001408803320270012301",
            ["05001408803320270012300", "05001408803320270012301"],
        ),
    ],
)
def test_extraer_cuis(texto, esperados):
    assert extraer_cuis(texto) == esperados


@pytest.mark.parametrize(
    "texto,iso",
    [
        (
            "Medellín, treinta (30) de abril de dos mil veintisiete (2.027)",
            "2027-04-30",
        ),
        (
            "Medellín, doce (12) de marzo de dos mil veintisiete (2027)",
            "2027-03-12",
        ),
        ("veinte (20) de enero de 2027, a las 10:12", "2027-01-20"),
        ("Cali, 7 de mayo de 2027", "2027-05-07"),
        ("viernes, 14 de mayo de 2027", "2027-05-14"),
        ("Fecha: 11/05/2027 9:15:30 a. m.", "2027-05-11"),
        ("Fecha Mar 4/05/2027 7:45 AM", "2027-05-04"),
        ("Fecha Vie 2027-05-21 13:50", "2027-05-21"),
        ("el 31 de febrero de 2027", None),
        ("29/9/27, 14:09", None),
        ("RAD 2027-00530", None),
    ],
)
def test_fechas_en(texto, iso):
    halladas = fechas_en(texto)
    assert (halladas[0][1] if halladas else None) == iso


def test_es_certificado_exige_encabezado_y_marcas():
    cert = "Cámara de Comercio de Ciudad Prueba\nSede Virtual\nCERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL\nCÓDIGO DE VERIFICACIÓN: X"
    mencion = "Se aportó como prueba el certificado de existencia y representación legal de la sociedad accionada."
    sin_marcas = "CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL de la sociedad"
    assert ingest._es_certificado(cert)
    assert not ingest._es_certificado(mencion)
    assert not ingest._es_certificado(sin_marcas)
    assert not ingest._es_certificado("x" * 400 + cert)


def test_partes_tabla_acta():
    acc, dem = ingest._partes_tabla(ACTA)
    assert acc == ["MARIA PRUEBA UNO"]
    assert dem == ["ENTIDAD DE PRUEBA S.A. DE MEDELLIN", "OTRA EMPRESA DE PRUEBA"]


def test_partes_etiquetas():
    texto = "Accionante: ANA PRUEBA\nAccionado   EMPRESA UNO S.A.\nVinculado: OTRA S.A.\nAccionado\n"
    acc, dem = ingest._partes_etiquetas(texto)
    assert acc == ["ANA PRUEBA"]
    assert dem == ["EMPRESA UNO S.A."]


def caso_sintetico(base: Path, con_acta_2a: bool = True) -> None:
    escribir(base, P1 + "001ActaReparto.txt", ACTA.format(rad=CUI, clase="TUTELA"))
    escribir(base, P1 + "002Escrito.txt", ESCRITO)
    escribir(base, P1 + "003Admite.txt", ADMISORIO)
    escribir(base, P1 + "004Fallo.txt", FALLO)
    escribir(base, P1 + "005Correo.txt", IMPUGNACION)
    escribir(base, P1 + "006Concede.txt", CONCEDE)
    escribir(base, P1 + "007NotificaFallo.txt", NOTIFICA)
    if con_acta_2a:
        escribir(
            base,
            P1 + "008Acta.txt",
            ACTA.format(rad=CUI[:21] + "01", clase="IMPUGNACIÓN TUTELA"),
        )
    escribir(
        base,
        P1 + "030Ajeno.txt",
        f"Constancia de otro trámite, radicado {OTRO_CUI}\n" + "a" * 60,
    )
    escribir(
        base,
        P1 + "031Copia.txt",
        "Documento sin radicado, texto de prueba. " + "hechos " * 20,
    )
    escribir(
        base,
        P1 + "031CopiaMemorial.txt",
        "Documento sin radicado, texto de prueba. " + "hechos " * 20,
    )
    cert = (
        "Cámara de Comercio de Ciudad Prueba\nCERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL\nCÓDIGO DE VERIFICACIÓN: ABC\n"
        + "datos " * 10
    )
    escribir(
        base,
        P1 + "009RespuestaEmpresa.txt",
        "Contestación de la empresa. " + "defensa " * 20 + ("\f" + cert) * 3,
    )
    escribir(base, P1 + "010SoloCertificado.txt", "\f".join([cert] * 3))
    escribir(
        base, P2 + "001AutoAsume.txt", f"Radicado {CUI}. Texto que no debe filtrarse."
    )
    escribir(base, P2 + "003FalloSegunda.txt", "Dato SOLO_EN_EL_FALLO " + "r" * 40)


def test_ingesta_sintetica(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    m = ing.metadatos
    assert (m.cui_1a, m.cui_2a) == (CUI, CUI[:21] + "01")
    assert m.accionante == "MARIA PRUEBA UNO"
    assert m.accionadas == [
        "ENTIDAD DE PRUEBA S.A. DE MEDELLIN",
        "OTRA EMPRESA DE PRUEBA",
    ]
    f = m.fechas
    assert (
        f.admision,
        f.fallo_a_quo,
        f.notificacion_fallo,
        f.impugnacion,
        f.concesion_impugnacion,
        f.reparto_2a,
    ) == (
        "2027-02-23",
        "2027-03-12",
        "2027-03-17",
        "2027-03-22",
        "2027-03-27",
        "2027-03-27",
    )
    roles = {d.nombre: d.rol for d in ing.documentos}
    assert (
        roles["001ActaReparto.txt"] == "acta_reparto_1a"
        and roles["008Acta.txt"] == "acta_reparto_2a"
    )
    assert (
        roles["002Escrito.txt"] == "escrito_tutela"
        and roles["003Admite.txt"] == "auto_admisorio"
    )
    assert (
        roles["004Fallo.txt"] == "fallo_a_quo"
        and roles["005Correo.txt"] == "impugnacion"
    )
    assert (
        roles["006Concede.txt"] == "auto_concede_impugnacion"
        and roles["007NotificaFallo.txt"] == "notificacion"
    )
    assert all(
        d.instancia == "1a" and d.evidencia and d.rol_origen == "contenido"
        for d in ing.documentos
    )
    assert ing.faltantes == [] and ing.esperados_faltantes == []


def test_instancia_por_carpeta_y_ignorados(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    assert ing.ignorados == ["02SegundaInstancia"]
    assert any("02SegundaInstancia" in a for a in ing.alertas)
    assert not any("02SegundaInstancia" in d.ruta for d in ing.documentos)
    assert not any(d.rol == "producto_despacho" for d in ing.documentos)
    assert "SOLO_EN_EL_FALLO" not in texto_para_llm(
        ing
    ) and "no debe filtrarse" not in texto_para_llm(ing)


def test_carpeta_del_caso_con_segunda_mal_escrita(tmp_path):
    escribir(tmp_path, "05001/01PrimeraInstancia/002Escrito.txt", ESCRITO)
    escribir(tmp_path, "05001/02SegundaInstacia/001Algo.txt", "x" * 50)
    escribir(tmp_path, "05001/Segunda/001Algo.txt", "x" * 50)
    ing = ingerir(tmp_path, Config())
    assert [d.nombre for d in ing.documentos] == ["002Escrito.txt"]
    assert ing.ignorados == ["05001/02SegundaInstacia", "05001/Segunda"]


def test_nombre_del_archivo_no_decide_la_instancia(tmp_path):
    escribir(
        tmp_path, P1 + "001ActaRepartoSegunda.txt", ACTA.format(rad=CUI, clase="TUTELA")
    )
    ing = ingerir(tmp_path, Config())
    d = ing.documentos[0]
    assert d.instancia == "1a" and d.rol == "acta_reparto_1a"


def test_acta_de_segunda_ya_no_es_obligatoria(tmp_path):
    caso_sintetico(tmp_path, con_acta_2a=False)
    ing = ingerir(tmp_path, Config())
    assert ROLES_OBLIGATORIOS == ("escrito_tutela", "fallo_a_quo", "impugnacion")
    assert ing.faltantes == [] and ing.completo
    assert ing.esperados_faltantes == ["acta_reparto_2a"]
    assert ing.metadatos.fechas.reparto_2a is None


def test_ajenos_y_duplicados(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    ajeno = por_nombre(ing, "030Ajeno.txt")
    assert ing.docs_ajenos == [ajeno.doc_id]
    assert por_nombre(ing, "006Concede.txt").doc_id not in ing.docs_ajenos
    assert por_nombre(ing, "031Copia.txt").doc_id not in ing.docs_ajenos
    copia = por_nombre(ing, "031CopiaMemorial.txt")
    assert copia.ruido and copia.motivo_ruido.startswith("Duplicado exacto de ")
    assert not por_nombre(ing, "031Copia.txt").ruido
    contestacion = por_nombre(ing, "009RespuestaEmpresa.txt")
    assert [p.ruido for p in contestacion.paginas] == [
        False,
        True,
        True,
        True,
    ] and not contestacion.ruido
    solo = por_nombre(ing, "010SoloCertificado.txt")
    assert solo.ruido and "Certificado" in solo.motivo_ruido
    texto = texto_para_llm(ing, max_chars=100000)
    assert (
        "030Ajeno" not in texto
        and "031CopiaMemorial" not in texto
        and "010SoloCertificado" not in texto
    )
    assert (
        "CÓDIGO DE VERIFICACIÓN" not in texto and "Contestación de la empresa" in texto
    )


def test_documento_obligatorio_nunca_se_excluye_como_ajeno(tmp_path):
    caso_sintetico(tmp_path)
    escribir(
        tmp_path,
        P1 + "005Correo.txt",
        IMPUGNACION.replace("Adjunto escrito.", f"Radicado {OTRO_CUI}"),
    )
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "005Correo.txt")
    assert d.rol == "impugnacion" and d.doc_id not in ing.docs_ajenos
    assert any(d.doc_id in a and "revisar" in a for a in ing.alertas)
    assert ing.faltantes == []


def test_ajeno_solo_mira_las_dos_primeras_paginas(tmp_path):
    caso_sintetico(tmp_path)
    escribir(
        tmp_path,
        P1 + "011Memorial.txt",
        "Memorial sin radicado. "
        + "x" * 40
        + f"\f{'y' * 40}\f{'z' * 40}\f Radicado {OTRO_CUI}",
    )
    ing = ingerir(tmp_path, Config())
    assert por_nombre(ing, "011Memorial.txt").doc_id not in ing.docs_ajenos


def test_faltantes_y_carpeta_vacia(tmp_path):
    escribir(tmp_path, P1 + "004Escrito.txt", ESCRITO)
    ing = ingerir(tmp_path, Config())
    assert ing.faltantes == ["fallo_a_quo", "impugnacion"]
    assert ing.esperados_faltantes == list(ROLES_ESPERADOS)
    assert not ing.completo and any("CUI" in a for a in ing.alertas)
    ing = ingerir(tmp_path / "otro", Config())
    assert (
        ing.faltantes == list(ROLES_OBLIGATORIOS)
        and ing.documentos == []
        and ing.alertas
    )


def test_alertas_son_lectura_mas_derivadas(tmp_path):
    caso_sintetico(tmp_path)
    (tmp_path / "insumos" / P1 / "foto.jpg").write_bytes(b"\xff\xd8")
    ing = ingerir(tmp_path, Config())
    assert any("foto.jpg" in a for a in ing.alertas_lectura)
    assert ing.alertas[: len(ing.alertas_lectura)] == ing.alertas_lectura
    assert len(ing.alertas) > len(ing.alertas_lectura)


def test_juzgado_a_quo_desde_el_fallo(tmp_path):
    caso_sintetico(tmp_path)
    m = ingerir(tmp_path, Config()).metadatos
    assert (
        m.juzgado_a_quo
        == "Juzgado Treinta y Tres Penal Municipal con Funciones de Control de Garantías de Medellín"
    )
    assert (
        m.juzgado_a_quo_numero,
        m.juzgado_a_quo_funcion,
        m.juzgado_a_quo_letras,
    ) == (33, "control_garantias", "Treinta y Tres")
    assert m.juzgado_a_quo_plural and not m.juzgado_a_quo_derivado


def test_juzgado_a_quo_singular_y_forma_con_numero(tmp_path):
    caso_sintetico(tmp_path)
    escribir(
        tmp_path,
        P1 + "004Fallo.txt",
        fallo(
            "Juzgado Treinta y Tres (33) Penal Municipal con Función de Control de Garantías de Medellín"
        ),
    )
    m = ingerir(tmp_path, Config()).metadatos
    assert not m.juzgado_a_quo_plural and not m.juzgado_a_quo_derivado
    assert (
        m.juzgado_a_quo
        == "Juzgado Treinta y Tres Penal Municipal con Función de Control de Garantías de Medellín"
    )


@pytest.mark.parametrize(
    "singulares, plurales, esperado_plural",
    [(3, 1, False), (1, 3, True), (2, 2, False)],
)
def test_juzgado_a_quo_funcion_por_mayoria(
    tmp_path, singulares, plurales, esperado_plural
):
    caso_sintetico(tmp_path)
    base = "Juzgado Treinta y Tres Penal Municipal con {} de Control de Garantías de Medellín"
    menciones = ["Funciones"] * plurales + ["Función"] * singulares
    escribir(
        tmp_path,
        P1 + "004Fallo.txt",
        fallo("\n".join(base.format(x) for x in menciones)),
    )
    m = ingerir(tmp_path, Config()).metadatos
    assert m.juzgado_a_quo_plural is esperado_plural


def test_juzgado_a_quo_derivado_del_radicado_si_no_aparece(tmp_path):
    caso_sintetico(tmp_path)
    escribir(tmp_path, P1 + "004Fallo.txt", fallo("JUZGADO 33 PENAL MUNICIPAL"))
    ing = ingerir(tmp_path, Config())
    assert (
        ing.metadatos.juzgado_a_quo_derivado
        and ing.metadatos.juzgado_a_quo_letras == "Treinta y Tres"
    )
    assert any("se deriva del radicado" in a for a in ing.alertas)


def test_juzgado_a_quo_discrepante_alerta(tmp_path):
    caso_sintetico(tmp_path)
    escribir(
        tmp_path,
        P1 + "004Fallo.txt",
        fallo(
            "Juzgado Catorce Penal Municipal con Función de Control de Garantías de Medellín"
        ),
    )
    ing = ingerir(tmp_path, Config())
    assert (
        ing.metadatos.juzgado_a_quo_derivado
        and ing.metadatos.juzgado_a_quo_numero == 33
    )
    assert any("no coincide con el número del radicado" in a for a in ing.alertas)


def test_reaplicar_cambia_roles_sin_releer(tmp_path):
    caso_sintetico(tmp_path, con_acta_2a=False)
    ing = ingerir(tmp_path, Config())
    nota = por_nombre(ing, "031Copia.txt")
    acta = por_nombre(ing, "001ActaReparto.txt")
    for f in (tmp_path / "insumos").rglob("*.txt"):
        f.unlink()
    nuevo = reaplicar(
        ing, {nota.doc_id: "acta_reparto_2a", acta.doc_id: "acta_reparto_1a"}
    )
    d = por_nombre(nuevo, "031Copia.txt")
    assert d.rol == "acta_reparto_2a" and d.rol_origen == "usuario" and d.evidencia
    assert por_nombre(nuevo, "001ActaReparto.txt").rol_origen == "contenido"
    assert nuevo.esperados_faltantes == []
    assert nuevo.documentos[0].paginas == ing.documentos[0].paginas
    assert por_nombre(
        ing, "031Copia.txt"
    ).rol != "acta_reparto_2a" and ing.esperados_faltantes == ["acta_reparto_2a"]


def test_reaplicar_recalcula_faltantes_y_metadatos(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    impug = por_nombre(ing, "005Correo.txt")
    quitado = reaplicar(ing, {impug.doc_id: "correo"})
    assert (
        quitado.faltantes == ["impugnacion"]
        and quitado.metadatos.fechas.impugnacion is None
    )
    restituido = reaplicar(quitado, {impug.doc_id: "impugnacion"})
    assert (
        restituido.faltantes == []
        and restituido.metadatos.fechas.impugnacion == "2027-03-22"
    )
    assert (
        restituido.ignorados == ing.ignorados
        and restituido.alertas_lectura == ing.alertas_lectura
    )
    assert Ingesta.model_validate(restituido.model_dump(mode="json")) == restituido


def test_reaplicar_conserva_el_rol_del_usuario_frente_a_un_ajeno(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    ajeno = por_nombre(ing, "030Ajeno.txt")
    nuevo = reaplicar(ing, {ajeno.doc_id: "impugnacion"})
    assert por_nombre(nuevo, "030Ajeno.txt").doc_id not in nuevo.docs_ajenos


def test_texto_para_llm_roles_y_truncado(tmp_path):
    escribir(tmp_path, P1 + "004Escrito.txt", ESCRITO + "a" * 500)
    escribir(tmp_path, P1 + "017Fallo.txt", FALLO)
    ing = ingerir(tmp_path, Config())
    solo_fallo = texto_para_llm(ing, {"fallo_a_quo"}, 100000)
    assert (
        solo_fallo.startswith("### DOC 1a-002 | fallo_a_quo | 017Fallo.txt")
        and "Escrito" not in solo_fallo
    )
    recortado = texto_para_llm(ing, None, 100)
    assert recortado.count("[... TRUNCADO ...]") == 2
    texto_para_llm(ing, None, 100)
    assert sum("truncado" in a for a in ing.alertas) == 2
    assert Ingesta.model_validate(ing.model_dump(mode="json")) == ing


def test_pdf_sin_texto_obligatorio_alerta_con_nombre_y_paginas(tmp_path):
    pdf_en_blanco(tmp_path / "insumos" / P1 / "004EscritoTutela.pdf", paginas=2)
    ing = ingerir(tmp_path, Config(ocr=True, cache_dir=str(tmp_path / "cache")))
    d = por_nombre(ing, "004EscritoTutela.pdf")
    assert (
        d.rol == "escrito_tutela"
        and [p.sin_texto for p in d.paginas] == [True, True]
        and not any(p.ocr for p in d.paginas)
    )
    assert any("004EscritoTutela.pdf" in a and "1, 2" in a for a in ing.alertas)


def test_pdf_sin_texto_no_obligatorio_no_alerta_por_pagina(tmp_path):
    pdf_en_blanco(tmp_path / "insumos" / "anexo.pdf", paginas=2)
    ing = ingerir(tmp_path, Config(ocr=False))
    assert not any("sin texto" in a for a in ing.alertas)


def test_ocr_aplicado_cuando_esta_disponible(tmp_path, monkeypatch):
    pdf_en_blanco(tmp_path / "insumos" / P1 / "004EscritoTutela.pdf", paginas=2)

    def falso_ocr(pdf, n, sha, dir_cache):
        return "texto leído por ocr " * 3 if n == 1 else ""

    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    monkeypatch.setattr(ingest, "_ocr_pagina", falso_ocr)
    ing = ingerir(tmp_path, Config(ocr=True, cache_dir=str(tmp_path / "cache")))
    p1, p2 = ing.documentos[0].paginas
    assert p1.ocr and not p1.sin_texto and p2.sin_texto and not p2.ocr
    assert not any("OCR no disponible" in a for a in ing.alertas)


def test_ocr_desactivado_no_lo_invoca(tmp_path, monkeypatch):
    pdf_en_blanco(tmp_path / "insumos" / "a.pdf")
    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    monkeypatch.setattr(
        ingest, "_ocr_pagina", lambda *a: pytest.fail("no debía invocarse")
    )
    ing = ingerir(tmp_path, Config(ocr=False))
    assert ing.documentos[0].paginas[0].sin_texto


class _PaginaFalsa:
    def render(self, scale):
        return self

    def to_pil(self):
        return "imagen"

    def close(self):
        pass


def test_cache_de_ocr_por_sha_y_pagina(tmp_path, monkeypatch):
    llamadas: list[str] = []
    falso = types.SimpleNamespace(
        image_to_string=lambda imagen, lang, config=None: (
            llamadas.append(imagen),
            "  texto reconocido  ",
        )[1]
    )
    monkeypatch.setitem(sys.modules, "pytesseract", falso)
    cache = tmp_path / "ocr"
    assert (
        ingest._ocr_pagina([_PaginaFalsa()] * 2, 2, "abc", cache) == "texto reconocido"
    )
    assert (cache / "abc" / "2.txt").read_text(encoding="utf-8") == "texto reconocido"
    assert (
        ingest._ocr_pagina([_PaginaFalsa()] * 2, 2, "abc", cache) == "texto reconocido"
    )
    assert len(llamadas) == 1
    ingest._ocr_pagina([_PaginaFalsa()] * 2, 1, "abc", cache)
    ingest._ocr_pagina([_PaginaFalsa()] * 2, 2, "otro", cache)
    assert len(llamadas) == 3
    assert not list(cache.rglob("*.tmp"))


def test_ocr_usa_la_cache_al_releer(tmp_path, monkeypatch):
    pdf_en_blanco(tmp_path / "insumos" / P1 / "004EscritoTutela.pdf", paginas=1)
    llamadas: list[str] = []
    falso = types.SimpleNamespace(
        image_to_string=lambda imagen, lang, config=None: (
            llamadas.append(imagen),
            "texto del ocr " * 4,
        )[1]
    )
    monkeypatch.setitem(sys.modules, "pytesseract", falso)
    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    import pypdfium2

    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda ruta: _PdfFalso())
    cfg = Config(ocr=True, cache_dir=str(tmp_path / "cache"))
    primera = ingerir(tmp_path, cfg)
    segunda = ingerir(tmp_path, cfg)
    assert primera.documentos[0].paginas[0].ocr and segunda.documentos[0].paginas[0].ocr
    assert len(llamadas) == 1


class _PdfFalso:
    def __getitem__(self, i):
        return _PaginaFalsa()

    def close(self):
        pass


def test_omp_thread_limit_solo_mientras_corre_el_pool(tmp_path, monkeypatch):
    escribir(tmp_path, P1 + "004Escrito.txt", ESCRITO)
    vistos: list[str | None] = []
    original = ingest._leer_documento

    def espia(*args):
        vistos.append(os.environ.get("OMP_THREAD_LIMIT"))
        return original(*args)

    monkeypatch.setattr(ingest, "_leer_documento", espia)
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    ingerir(tmp_path, Config())
    assert vistos == ["1"] and "OMP_THREAD_LIMIT" not in os.environ
    monkeypatch.setenv("OMP_THREAD_LIMIT", "4")
    ingerir(tmp_path, Config())
    assert os.environ["OMP_THREAD_LIMIT"] == "4"


def test_pypdf_si_no_hay_pdftotext(tmp_path, monkeypatch):
    pdf_en_blanco(tmp_path / "insumos" / "a.pdf", paginas=3)
    monkeypatch.setattr(ingest.shutil, "which", lambda nombre: None)
    ing = ingerir(tmp_path, Config(ocr=False))
    assert len(ing.documentos[0].paginas) == 3 and all(
        p.sin_texto for p in ing.documentos[0].paginas
    )


def test_fallo_en_docx_de_una_sola_pagina(tmp_path):
    caso_sintetico(tmp_path)
    ruta = tmp_path / "insumos" / P1 / "004Fallo.txt"
    ruta.unlink()
    doc = Document()
    for parrafo in FALLO.split("\f"):
        doc.add_paragraph(parrafo)
    doc.save(tmp_path / "insumos" / P1 / "004Fallo.docx")
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "004Fallo.docx")
    assert len(d.paginas) == 1 and d.rol == "fallo_a_quo"
    assert ing.faltantes == []


def test_pdf_corrupto_no_rompe(tmp_path):
    ruta = tmp_path / "insumos" / "01PrimeraInstancia" / "004EscritoTutela.pdf"
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(b"esto no es un pdf")
    ing = ingerir(tmp_path, Config())
    assert ing.documentos[0].paginas == []
    assert any("no se pudo leer" in a for a in ing.alertas)


def test_formatos(tmp_path):
    ruta = tmp_path / "insumos" / "01PrimeraInstancia" / "004EscritoTutela.docx"
    ruta.parent.mkdir(parents=True)
    doc = Document()
    doc.add_paragraph(
        "Primer párrafo del escrito, con texto suficiente. Señor JUEZ (REPARTO). ACCIÓN DE TUTELA. HECHOS. PRETENSIONES."
    )
    tabla = doc.add_table(rows=1, cols=2)
    tabla.rows[0].cells[0].text = "Accionante"
    tabla.rows[0].cells[1].text = "Persona de prueba"
    doc.save(ruta)
    (ruta.parent / "foto.jpg").write_bytes(b"\xff\xd8")
    (ruta.parent / ".DS_Store").write_bytes(b"x")
    ing = ingerir(tmp_path, Config())
    assert [d.nombre for d in ing.documentos] == ["004EscritoTutela.docx"]
    assert ing.documentos[0].rol == "escrito_tutela"
    assert (
        "Primer párrafo" in ing.documentos[0].texto()
        and "Accionante | Persona de prueba" in ing.documentos[0].texto()
    )
    assert any("foto.jpg" in a and "formato no soportado" in a for a in ing.alertas)


OFICIO_Y_SENTENCIA = (
    "Medellín, veintiuno (21) de agosto de dos mil veintisiete (2027)\n\nOficio No. 986\n"
    "Les adjunto el fallo de tutela.\n\f"
    "JUZGADO TREINTA Y TRES PENAL MUNICIPAL CON FUNCIONES DE CONTROL DE GARANTÍAS DE MEDELLÍN\n"
    f"Medellín, veinte (20) de agosto de dos mil veintisiete (2027)\nRadicado {CUI}\n"
    "Acción de tutela. ANTECEDENTES. CONSIDERACIONES. Competencia. RESUELVE: PRIMERO. Niega.\n"
)


def test_fecha_del_fallo_ignora_el_oficio_de_notificacion():
    assert ingest._fecha_encabezado(OFICIO_Y_SENTENCIA) == "2027-08-20"
    assert ingest._fecha_encabezado("Medellín, 3 de marzo de 2027\nTexto.") == "2027-03-03"


def test_partes_tabla_sin_documento_y_nombre_en_dos_lineas():
    texto = (
        "        TIPO ID          IDENTIFICACIÓN        NOMBRE        APELLIDO        PARTE\n"
        "CÉDULA DE CIUDADANIA       12345678 MARIA          PRUEBA UNO        DEMANDANTE/ACCIONANTE\n"
        "SIN DOCUMENTO              SDCONCEJAL PEDRO         PRUEBA DOS        DEMANDADO/INDICIADO/CAUS\n"
        "                                                                      ANTE\n"
        "NIT                        90000000012 SEGUROS DE PRUEBA S.A          DEMANDADO/INDICIADO/CAUS\n"
        "                           ARL PRUEBA                                 ANTE\n"
    )
    acc, dem = ingest._partes_tabla(texto)
    assert acc == ["MARIA PRUEBA UNO"]
    assert dem == ["CONCEJAL PEDRO PRUEBA DOS", "SEGUROS DE PRUEBA S.A ARL PRUEBA"]


def test_etiquetas_exigen_forma_de_etiqueta_y_juntan_continuaciones():
    texto = (
        "Accionado: EMPRESA UNO S.A., EMPRESA\n      DOS S.A.\n\n"
        "entidad\naccionada y las entidades vinculadas, remitiéndoseles copia\n"
        "Accionada y las entidades vinculadas\nACCIONANTE MARIA PRUEBA\n"
    )
    acc, dem = ingest._partes_etiquetas(texto)
    assert dem == ["EMPRESA UNO S.A., EMPRESA DOS S.A."]
    assert acc == ["MARIA PRUEBA"]


def test_alerta_si_las_partes_salen_de_etiquetas(tmp_path):
    escribir(tmp_path, P1 + "003Admite.txt", ADMISORIO + "Accionado: EMPRESA PRUEBA S.A.\n")
    ing = ingerir(tmp_path, Config())
    assert ing.metadatos.accionadas == ["EMPRESA PRUEBA S.A."]
    assert any("no hay acta de reparto legible" in a for a in ing.alertas)


def test_legible_descarta_basura_de_ocr():
    assert not ingest._legible("9/L1Gv 1 0Ge695-99G8-PAPp-3P|9-LZ0DPOGa " * 10)
    assert ingest._legible("el juzgado resolvió la acción de tutela interpuesta " * 5)
    assert ingest._legible("NÚMERO RADICACIÓN 123")


def test_ocr_usa_psm_1_y_descarta_pagina_ilegible(tmp_path, monkeypatch):
    configs: list[str | None] = []
    basura = "9/L1Gv 1 0Ge695-99G8-PAPp-3P|9-LZ0DPOGa " * 10
    falso = types.SimpleNamespace(
        image_to_string=lambda imagen, lang, config=None: (
            configs.append(config),
            basura,
        )[1]
    )
    monkeypatch.setitem(sys.modules, "pytesseract", falso)
    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    import pypdfium2

    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda ruta: _PdfFalso())
    pdf_en_blanco(tmp_path / "insumos" / P1 / "004EscritoTutela.pdf", paginas=1)
    ing = ingerir(tmp_path, Config(ocr=True, cache_dir=str(tmp_path / "cache")))
    assert configs == ["--psm 1"]
    assert ing.documentos[0].paginas[0].sin_texto


class OcrFalso:
    def __init__(self) -> None:
        self.candado = threading.Lock()
        self.llamadas: list[str] = []
        self.render_activos = self.render_max = 0
        self.ocr_activos = self.ocr_max = 0
        self.omp: set[str | None] = set()
        self.espera = None
        self.falla_en: set[str] = set()

    @staticmethod
    def texto(imagen: str) -> str:
        return " ".join([f"texto reconocido {imagen}"] * 3)

    def reconocer(self, imagen, lang, config=None):
        with self.candado:
            self.llamadas.append(imagen)
            self.omp.add(os.environ.get("OMP_THREAD_LIMIT"))
            self.ocr_activos += 1
            self.ocr_max = max(self.ocr_max, self.ocr_activos)
        try:
            if self.espera:
                self.espera(imagen)
            if imagen in self.falla_en:
                raise RuntimeError("tesseract murió")
            return f"  {self.texto(imagen)}  "
        finally:
            with self.candado:
                self.ocr_activos -= 1


class _PaginaDe:
    def __init__(self, ocr: OcrFalso, nombre: str, n: int) -> None:
        self.ocr, self.nombre, self.n = ocr, nombre, n

    def render(self, scale):
        with self.ocr.candado:
            self.ocr.render_activos += 1
            self.ocr.render_max = max(self.ocr.render_max, self.ocr.render_activos)
        time.sleep(0.02)
        with self.ocr.candado:
            self.ocr.render_activos -= 1
        return self

    def to_pil(self):
        return f"{self.nombre}-p{self.n}"

    def close(self):
        pass


class _PdfDe:
    def __init__(self, ocr: OcrFalso, nombre: str) -> None:
        self.ocr, self.nombre = ocr, nombre

    def __getitem__(self, i):
        return _PaginaDe(self.ocr, self.nombre, i + 1)

    def close(self):
        pass


@pytest.fixture
def ocr_falso(monkeypatch):
    import pypdfium2

    ocr = OcrFalso()
    monkeypatch.setitem(sys.modules, "pytesseract", types.SimpleNamespace(image_to_string=ocr.reconocer))
    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda ruta: _PdfDe(ocr, Path(ruta).stem))
    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    monkeypatch.setattr(ingest, "_max_hilos", lambda: 4)
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    monkeypatch.delenv("TUTELA2_CACHE_DIR", raising=False)
    return ocr


def _escaneados(base: Path, **paginas: int) -> None:
    for nombre, n in paginas.items():
        pdf_en_blanco(base / "insumos" / P1 / f"{nombre}.pdf", paginas=n)


def _cfg(tmp_path: Path, nombre: str = "cache") -> Config:
    return Config(ocr=True, cache_dir=str(tmp_path / nombre))


def test_ocr_paralelo_por_paginas_da_el_mismo_resultado_que_en_serie(tmp_path, ocr_falso, monkeypatch):
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2, "020Anexo": 4})
    escribir(tmp_path, P1 + "030Nota.txt", ESCRITO)
    resultados = {}
    for hilos in (1, 4):
        monkeypatch.setattr(ingest, "_max_hilos", lambda h=hilos: h)
        resultados[hilos] = ingerir(tmp_path, _cfg(tmp_path, f"cache{hilos}"))
    serie, paralelo = resultados[1], resultados[4]
    assert paralelo.model_dump() == serie.model_dump()
    assert [d.doc_id for d in paralelo.documentos] == ["1a-001", "1a-002", "1a-003", "1a-004"]
    assert [d.nombre for d in paralelo.documentos] == ["004Escrito.pdf", "017Fallo.pdf", "020Anexo.pdf", "030Nota.txt"]
    for d in paralelo.documentos[:3]:
        stem = Path(d.nombre).stem
        assert [p.n for p in d.paginas] == list(range(1, len(d.paginas) + 1))
        for p in d.paginas:
            assert (p.texto, p.ocr, p.sin_texto) == (OcrFalso.texto(f"{stem}-p{p.n}"), True, False)
            en_disco = tmp_path / "cache4" / "ocr-psm1" / d.sha256 / f"{p.n}.txt"
            assert en_disco.read_text(encoding="utf-8") == p.texto
    assert not paralelo.documentos[3].paginas[0].ocr


def test_dos_paginas_ocr_de_un_mismo_documento_corren_a_la_vez(tmp_path, ocr_falso):
    barrera = threading.Barrier(2, timeout=5)
    ocr_falso.espera = lambda imagen: barrera.wait()
    _escaneados(tmp_path, **{"004Escrito": 2})
    ing = ingerir(tmp_path, _cfg(tmp_path))
    assert [p.ocr for p in ing.documentos[0].paginas] == [True, True]
    assert not any("el OCR falló" in a for a in ing.alertas)
    assert ocr_falso.ocr_max == 2


def test_el_render_de_pdfium_se_serializa_y_el_reconocimiento_no(tmp_path, ocr_falso):
    barrera = threading.Barrier(2, timeout=5)
    ocr_falso.espera = lambda imagen: barrera.wait()
    _escaneados(tmp_path, **{"004Escrito": 4, "017Fallo": 2})
    ing = ingerir(tmp_path, _cfg(tmp_path))
    assert all(p.ocr for d in ing.documentos for p in d.paginas)
    assert ocr_falso.render_max == 1 and ocr_falso.ocr_max == 2


def test_ocr_corre_con_omp_thread_limit_1_y_lo_restituye(tmp_path, ocr_falso):
    _escaneados(tmp_path, **{"004Escrito": 2, "017Fallo": 2})
    ingerir(tmp_path, _cfg(tmp_path))
    assert ocr_falso.omp == {"1"} and "OMP_THREAD_LIMIT" not in os.environ


def test_si_falla_una_pagina_solo_se_conservan_las_anteriores_y_hay_una_alerta(tmp_path, ocr_falso):
    ocr_falso.falla_en = {"004Escrito-p2"}
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2})
    ing = ingerir(tmp_path, _cfg(tmp_path))
    escrito, fallo = ing.documentos
    assert [(p.ocr, p.sin_texto) for p in escrito.paginas] == [(True, False), (False, True), (False, True)]
    assert [(p.ocr, p.sin_texto) for p in fallo.paginas] == [(True, False)] * 2
    fallos = [a for a in ing.alertas if "el OCR falló" in a]
    assert len(fallos) == 1 and "004Escrito.pdf" in fallos[0] and "tesseract murió" in fallos[0]


def test_la_segunda_lectura_sale_de_la_cache_sin_reconocer(tmp_path, ocr_falso):
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2})
    primera = ingerir(tmp_path, _cfg(tmp_path))
    assert len(ocr_falso.llamadas) == 5
    segunda = ingerir(tmp_path, _cfg(tmp_path))
    assert len(ocr_falso.llamadas) == 5
    assert segunda.model_dump() == primera.model_dump()


@pytest.fixture
def buffer_job():
    buffer = eventos.Buffer()
    token = eventos.activar(buffer)
    yield buffer
    eventos.desactivar(token)


def _lee(buffer: eventos.Buffer) -> list[dict]:
    return [e for e in buffer.leer(0)[0] if e["etapa"] == "ingesta" and e["tipo"] == "lee"]


def _de_documento(e: dict) -> bool:
    return bool(e["datos"]) and "paginas" in e["datos"] and "pagina" not in e["datos"]


def _de_pagina(e: dict) -> bool:
    return bool(e["datos"]) and "pagina" in e["datos"]


def _de_arranque(e: dict) -> bool:
    return bool(e["datos"]) and "ocr_documentos" in e["datos"]


def test_el_evento_de_cada_documento_sale_al_terminar_no_en_orden_de_archivo(tmp_path, ocr_falso, buffer_job):
    _escaneados(tmp_path, **{"004Escrito": 2})
    escribir(tmp_path, P1 + "030Nota.txt", ESCRITO)
    ingerir(tmp_path, _cfg(tmp_path))
    lee = _lee(buffer_job)
    documentos = [e for e in lee if _de_documento(e)]
    assert [e["datos"]["doc_id"] for e in documentos] == ["1a-002", "1a-001"]
    assert [(e["datos"]["n_hecho"], e["datos"]["n_total"]) for e in documentos] == [(1, 2), (2, 2)]
    posicion = {id(e): i for i, e in enumerate(lee)}
    [arranque] = [e for e in lee if _de_arranque(e)]
    assert posicion[id(documentos[0])] < posicion[id(arranque)] < posicion[id(documentos[1])]
    assert all(set(e["datos"]) >= {"doc_id", "archivo", "paginas", "ocr", "sin_texto", "alertas", "n_hecho", "n_total"} for e in documentos)


def test_arranque_del_ocr_y_un_evento_por_pagina_con_contador(tmp_path, ocr_falso, buffer_job):
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2})
    ingerir(tmp_path, _cfg(tmp_path))
    lee = _lee(buffer_job)
    [arranque] = [e for e in lee if _de_arranque(e)]
    assert arranque["texto"] == "OCR: 2 documentos escaneados, 5 páginas por leer."
    assert arranque["datos"] == {"ocr_documentos": 2, "ocr_paginas": 5, "desde_cache": 0}
    paginas = [e for e in lee if _de_pagina(e)]
    assert len(paginas) == 5
    assert sorted(e["datos"]["n_ocr_hecho"] for e in paginas) == [1, 2, 3, 4, 5]
    assert {e["datos"]["n_ocr_total"] for e in paginas} == {5}
    assert all(set(e["datos"]) == {"doc_id", "archivo", "pagina", "paginas", "ocr", "n_ocr_hecho", "n_ocr_total"} for e in paginas)
    assert all(e["datos"]["ocr"] is True for e in paginas)
    por_doc = {(e["datos"]["doc_id"], e["datos"]["pagina"]): e for e in paginas}
    assert set(por_doc) == {("1a-001", 1), ("1a-001", 2), ("1a-001", 3), ("1a-002", 1), ("1a-002", 2)}
    ejemplo = por_doc[("1a-001", 2)]
    assert ejemplo["texto"] == f"OCR: {P1}004Escrito.pdf, página 2 de 3."
    assert ejemplo["datos"]["archivo"] == f"{P1}004Escrito.pdf" and ejemplo["datos"]["paginas"] == 3
    posicion = {id(e): i for i, e in enumerate(lee)}
    assert all(posicion[id(arranque)] < posicion[id(e)] for e in paginas)
    for d in ("1a-001", "1a-002"):
        [final] = [e for e in lee if _de_documento(e) and e["datos"]["doc_id"] == d]
        assert all(posicion[id(e)] < posicion[id(final)] for (doc, _), e in por_doc.items() if doc == d)
        assert final["datos"]["ocr"] == (3 if d == "1a-001" else 2)


def test_arranque_en_singular(tmp_path, ocr_falso, buffer_job):
    _escaneados(tmp_path, **{"004Escrito": 1})
    ingerir(tmp_path, _cfg(tmp_path))
    [arranque] = [e for e in _lee(buffer_job) if _de_arranque(e)]
    assert arranque["texto"] == "OCR: 1 documento escaneado, 1 página por leer."


def test_las_paginas_desde_cache_no_emiten_evento(tmp_path, ocr_falso, buffer_job):
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2})
    ingerir(tmp_path, _cfg(tmp_path))
    buffer_job.agregar("sistema", "sistema", "corte")
    desde = buffer_job.leer(0)[0][-1]["n"]
    ingerir(tmp_path, _cfg(tmp_path))
    nuevos = [e for e in buffer_job.leer(desde)[0] if e["etapa"] == "ingesta" and e["tipo"] == "lee"]
    assert not [e for e in nuevos if _de_pagina(e)]
    [arranque] = [e for e in nuevos if _de_arranque(e)]
    assert arranque["texto"] == "OCR: 2 documentos escaneados, 5 páginas por leer (5 ya en caché)."
    assert arranque["datos"] == {"ocr_documentos": 2, "ocr_paginas": 5, "desde_cache": 5}
    documentos = [e for e in nuevos if _de_documento(e)]
    assert sorted(e["datos"]["ocr"] for e in documentos) == [2, 3]
    assert sorted(e["datos"]["n_hecho"] for e in documentos) == [1, 2]


def test_con_cache_parcial_el_contador_llega_al_total_con_un_solo_evento_de_pagina(tmp_path, ocr_falso, buffer_job):
    _escaneados(tmp_path, **{"004Escrito": 3, "017Fallo": 2})
    primera = ingerir(tmp_path, _cfg(tmp_path))
    borrada = tmp_path / "cache" / "ocr-psm1" / primera.documentos[0].sha256 / "2.txt"
    borrada.unlink()
    buffer_job.agregar("sistema", "sistema", "corte")
    desde = buffer_job.leer(0)[0][-1]["n"]
    segunda = ingerir(tmp_path, _cfg(tmp_path))
    nuevos = [e for e in buffer_job.leer(desde)[0] if e["etapa"] == "ingesta" and e["tipo"] == "lee"]
    [arranque] = [e for e in nuevos if _de_arranque(e)]
    assert arranque["datos"] == {"ocr_documentos": 2, "ocr_paginas": 5, "desde_cache": 4}
    [pagina] = [e for e in nuevos if _de_pagina(e)]
    assert (pagina["datos"]["pagina"], pagina["datos"]["n_ocr_hecho"], pagina["datos"]["n_ocr_total"]) == (2, 5, 5)
    assert segunda.model_dump() == primera.model_dump()
    assert len(ocr_falso.llamadas) == 6


def test_sin_paginas_escaneadas_no_hay_evento_de_arranque_del_ocr(tmp_path, ocr_falso, buffer_job):
    escribir(tmp_path, P1 + "030Nota.txt", ESCRITO)
    ingerir(tmp_path, _cfg(tmp_path))
    lee = _lee(buffer_job)
    assert not [e for e in lee if _de_arranque(e) or _de_pagina(e)]
    [documento] = [e for e in lee if _de_documento(e)]
    assert (documento["datos"]["n_hecho"], documento["datos"]["n_total"]) == (1, 1)


def test_un_documento_ilegible_cuenta_como_terminado(tmp_path, ocr_falso, buffer_job):
    ruta = tmp_path / "insumos" / P1 / "004Escrito.pdf"
    ruta.parent.mkdir(parents=True)
    ruta.write_bytes(b"esto no es un pdf")
    escribir(tmp_path, P1 + "030Nota.txt", ESCRITO)
    ingerir(tmp_path, _cfg(tmp_path))
    documentos = [e for e in _lee(buffer_job) if _de_documento(e)]
    assert sorted(e["datos"]["n_hecho"] for e in documentos) == [1, 2]
    assert {e["datos"]["n_total"] for e in documentos} == {2}


def test_segunda_solo_en_la_carpeta_hermana_de_la_primera(tmp_path):
    escribir(tmp_path, "01PrimeraInstancia/C01Principal/002Escrito.txt", ESCRITO)
    escribir(tmp_path, "01PrimeraInstancia/C01Principal/Sub/02 Anexos/003Escrito.txt", ESCRITO)
    escribir(tmp_path, "2ª Instancia/C01Principal/001Algo.txt", "x" * 50)
    escribir(tmp_path, "Impugnación Circuito/001Algo.txt", "x" * 50)
    ing = ingerir(tmp_path, Config())
    assert sorted(d.nombre for d in ing.documentos) == ["002Escrito.txt", "003Escrito.txt"]
    assert sorted(ing.ignorados) == ["2ª Instancia", "Impugnación Circuito"]


def test_alerta_si_se_descarta_una_sentencia_candidata(tmp_path):
    caso_sintetico(tmp_path)
    escribir(tmp_path, P1 + "040OtroFallo.txt", fallo("JUZGADO TERCERO PENAL DEL CIRCUITO DE MEDELLÍN"))
    ing = ingerir(tmp_path, Config())
    assert por_nombre(ing, "040OtroFallo.txt").rol == "otro"
    assert any("040OtroFallo.txt" in a and "Otra sentencia" in a for a in ing.alertas)


def test_reaplicar_respeta_rol_del_usuario_en_documento_ajeno(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    ajeno = por_nombre(ing, "030Ajeno.txt")
    assert ajeno.doc_id in ing.docs_ajenos
    nuevo = reaplicar(ing, {ajeno.doc_id: "auto_concede_impugnacion"})
    assert ajeno.doc_id not in nuevo.docs_ajenos
    assert not any("se trata como ajeno" in a and ajeno.doc_id in a for a in nuevo.alertas)


def test_reaplicar_alerta_con_dos_fallos(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    notif = por_nombre(ing, "007NotificaFallo.txt")
    nuevo = reaplicar(ing, {notif.doc_id: "fallo_a_quo"})
    assert any("más de un documento con rol fallo_a_quo" in a for a in nuevo.alertas)


def test_fecha_de_notificacion_e_impugnacion_por_contenido(tmp_path):
    caso_sintetico(tmp_path)
    escribir(
        tmp_path,
        P1 + "002aNotificaAdmision.txt",
        "Outlook Notificación del auto admisorio\nDesde Juzgado 33 Penal Municipal <pmpal33med@cendoj.ramajudicial.gov.co>\nFecha Mar 2027-02-24 10:00\nPara Maria\nCordial saludo.\n",
    )
    escribir(
        tmp_path,
        P1 + "005aAmpliacion.txt",
        "Outlook Ampliación de la impugnación\nDesde Maria Prueba <maria@correo.com>\nFecha Lun 2027-03-20 09:05\nPara Juzgado 33 <pmpal33med@cendoj.ramajudicial.gov.co>\nAmplío la impugnación a la sentencia.\n",
    )
    ing = ingerir(tmp_path, Config())
    assert por_nombre(ing, "005aAmpliacion.txt").rol == "impugnacion"
    assert por_nombre(ing, "002aNotificaAdmision.txt").rol == "notificacion"
    f = ing.metadatos.fechas
    assert f.notificacion_fallo == "2027-03-17"
    assert f.impugnacion == "2027-03-22"


def test_docx_con_cuadro_de_texto_encabezado_y_tabla_anidada(tmp_path):
    from docx.oxml import parse_xml

    ruta = tmp_path / "insumos" / P1 / "004Fallo.docx"
    ruta.parent.mkdir(parents=True)
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "ENCABEZADO DE PRUEBA"
    p = doc.add_paragraph("Cuerpo.")
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    p._p.append(
        parse_xml(
            f'<w:r {ns}><w:pict><w:txbxContent><w:p><w:r><w:t>TEXTO EN CUADRO</w:t></w:r></w:p></w:txbxContent></w:pict></w:r>'
        )
    )
    tabla = doc.add_table(rows=1, cols=1)
    interna = tabla.rows[0].cells[0].add_table(rows=1, cols=1)
    interna.rows[0].cells[0].text = "CELDA ANIDADA"
    doc.save(ruta)
    texto = "\n".join(ingest._textos_docx(ruta))
    assert "TEXTO EN CUADRO" in texto and "ENCABEZADO DE PRUEBA" in texto
    assert "CELDA ANIDADA" in texto and texto.count("TEXTO EN CUADRO") == 1


def test_docx_casi_vacio_alerta_la_causa(tmp_path):
    ruta = tmp_path / "insumos" / P1 / "004Fallo.docx"
    ruta.parent.mkdir(parents=True)
    Document().save(ruta)
    ing = ingerir(tmp_path, Config())
    assert any("conviértalo a PDF" in a for a in ing.alertas)


def test_docx_largo_toma_la_cabecera_por_caracteres(tmp_path):
    caso_sintetico(tmp_path)
    ruta = tmp_path / "insumos" / P1 / "004Escrito.docx"
    doc = Document()
    doc.add_paragraph(ESCRITO + "relleno " * 1000 + f"Anexo de otro trámite {OTRO_CUI}")
    doc.save(ruta)
    ing = ingerir(tmp_path, Config())
    assert not any("004Escrito.docx" in a and "CUI" in a for a in ing.alertas)


PDF_CON_TEXTO = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 150 Td (TEXTO DE PRUEBA) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF\n"
)


def test_respaldo_pdfium_cuando_pypdf_falla(tmp_path, monkeypatch):
    ruta = tmp_path / "a.pdf"
    ruta.write_bytes(PDF_CON_TEXTO)

    def falla(*a, **k):
        raise RuntimeError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(ingest, "PdfReader", falla)
    monkeypatch.setattr(ingest.shutil, "which", lambda nombre: None)
    assert "TEXTO DE PRUEBA" in "".join(ingest._textos_pdf(ruta))


def test_alerta_si_falta_pdftotext(tmp_path, monkeypatch):
    pdf_en_blanco(tmp_path / "insumos" / "a.pdf")
    monkeypatch.setattr(ingest.shutil, "which", lambda nombre: None)
    ing = ingerir(tmp_path, Config(ocr=False))
    assert any("pdftotext" in a for a in ing.alertas)


def test_subcarpetas_numeradas_dentro_de_primera_no_son_segunda(tmp_path):
    escribir(tmp_path, P1 + "003Escrito.txt", ESCRITO)
    escribir(tmp_path, P1 + "010AnexosTutela/a.txt", "anexo " * 20)
    escribir(tmp_path, P1 + "024ImpugnacionAccionante/escrito.txt", "impugno " * 20)
    ing = ingerir(tmp_path, Config())
    assert ing.ignorados == []
    assert any("024ImpugnacionAccionante" in d.ruta for d in ing.documentos)


def test_ocr_con_pdf_que_pdfium_no_abre_genera_alerta(tmp_path, monkeypatch):
    import pypdfium2

    def falla(*a, **k):
        raise pypdfium2.PdfiumError("Data format error")

    monkeypatch.setattr(pypdfium2, "PdfDocument", falla)
    monkeypatch.setitem(sys.modules, "pytesseract", types.SimpleNamespace(image_to_string=lambda *a, **k: "x"))
    monkeypatch.setattr(ingest, "_ocr_disponible", lambda: True)
    pdf_en_blanco(tmp_path / "insumos" / "x.pdf", paginas=2)
    ing = ingerir(tmp_path, Config(ocr=True, cache_dir=str(tmp_path / "cache")))
    alertas = [a for a in ing.alertas if "el OCR falló" in a]
    assert len(alertas) == 1 and "x.pdf" in alertas[0] and "Data format error" in alertas[0]
    assert all(p.sin_texto and not p.ocr for p in ing.documentos[0].paginas)


def test_varios_accionantes_no_se_unen(tmp_path):
    acta = ACTA + (
        "CÉDULA DE CIUDADANIA                      87654321 ANA                   OTRA PRUEBA                    DEMANDANTE/ACCIONANTE\n"
    )
    escribir(tmp_path, P1 + "001Acta.txt", acta.format(rad=CUI, clase="TUTELA"))
    ing = ingerir(tmp_path, Config())
    assert ing.metadatos.accionante == "MARIA PRUEBA UNO"
    assert any("varios accionantes" in a and "ANA OTRA PRUEBA" in a for a in ing.alertas)


def test_reaplicar_confirmar_mismo_rol_rescata_ajeno(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    ajeno = por_nombre(ing, "030Ajeno.txt")
    assert ajeno.doc_id in ing.docs_ajenos
    nuevo = reaplicar(ing, {ajeno.doc_id: ajeno.rol})
    assert nuevo.docs_ajenos == []
    assert por_nombre(nuevo, "030Ajeno.txt").rol_origen == "usuario"


def ajena(base: Path, nombre: str, texto: str) -> None:
    escribir(base, P1 + nombre, f"Constancia de otro trámite, radicado {OTRO_CUI}\n{texto}\n" + "a" * 60)


def test_ajeno_sin_nombres_del_caso_sigue_ajeno(tmp_path):
    caso_sintetico(tmp_path)
    ing = ingerir(tmp_path, Config())
    assert ing.docs_revisar == []
    assert por_nombre(ing, "030Ajeno.txt").doc_id in ing.docs_ajenos


@pytest.mark.parametrize(
    "texto",
    [
        "Solicitud presentada por MARIA PRUEBA UNO ante otro despacho.",
        "Se reclama a ENTIDAD DE PRUEBA S.A. DE MEDELLIN el cumplimiento.",
        "Respuesta de otra empresa de prueba al requerimiento.",
        "Oficio dirigido al Juzgado 33 Penal Municipal de Medellín.",
        "Oficio dirigido al Juzgado Treinta y Tres Penal Municipal con Funciones de Control de Garantías.",
        "Oficio dirigido al Juzgado Treinta y Tres (33) Penal Municipal.",
        "Desde Juzgado 33 Penal Municipal Control Garantías - Antioquia - Medellín",
    ],
)
def test_ajeno_que_nombra_al_caso_queda_para_revisar(tmp_path, texto):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", texto)
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "032Cartas.txt")
    assert ing.docs_revisar == [d.doc_id]
    assert d.doc_id not in ing.docs_ajenos
    assert ing.docs_ajenos == [por_nombre(ing, "030Ajeno.txt").doc_id]
    assert any(d.doc_id in a and "para revisar" in a for a in ing.alertas)
    assert not any(d.doc_id in a and "se trata como ajeno" in a for a in ing.alertas)
    assert ing.faltantes == []
    assert Ingesta.model_validate(ing.model_dump(mode="json")) == ing


def test_para_revisar_llega_al_modelo_con_linea_de_marca(tmp_path):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", "Solicitud presentada por MARIA PRUEBA UNO.")
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "032Cartas.txt")
    texto = texto_para_llm(ing, max_chars=100000)
    cabecera = f"### DOC {d.doc_id} | {d.rol} | 032Cartas.txt\n"
    assert cabecera + ingest.AVISO_REVISAR + "\n[p. 1]\n" in texto
    assert "Solicitud presentada por MARIA PRUEBA UNO." in texto
    assert texto.count(ingest.AVISO_REVISAR) == 1
    assert "030Ajeno" not in texto
    solo = texto_para_llm(ing, {d.rol}, 100000)
    assert ingest.AVISO_REVISAR in solo


def test_marca_de_revisar_no_cuenta_en_el_truncado(tmp_path):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", "MARIA PRUEBA UNO " + "x" * 400)
    ing = ingerir(tmp_path, Config())
    texto = texto_para_llm(ing, max_chars=50)
    assert ingest.AVISO_REVISAR in texto and "[... TRUNCADO ...]" in texto


@pytest.mark.parametrize(
    "texto",
    [
        "Solicitud presentada por MARIA PRUEBA UNOS.",
        "Solicitud presentada por MARIA PRUEBA.",
        "Solicitud sobre otra EMPRESA en la EPS de prueba.",
        "Oficio dirigido al Juzgado 34 Penal Municipal de Medellín.",
        "Oficio dirigido al Juzgado 133 Penal Municipal de Medellín.",
        "Oficio dirigido al Juzgado 33 Civil Municipal de Medellín.",
    ],
)
def test_nombres_parciales_o_de_otro_juzgado_no_rescatan(tmp_path, texto):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", texto)
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "032Cartas.txt")
    assert d.doc_id in ing.docs_ajenos and ing.docs_revisar == []


def test_sin_acta_no_se_rescata_por_nombre_de_partes(tmp_path):
    escribir(tmp_path, P1 + "002Escrito.txt", ESCRITO)
    escribir(tmp_path, P1 + "003Admite.txt", ADMISORIO)
    escribir(tmp_path, P1 + "004Fallo.txt", FALLO)
    escribir(tmp_path, P1 + "005Correo.txt", IMPUGNACION)
    ajena(tmp_path, "032Cartas.txt", "Solicitud presentada por MARIA PRUEBA UNO y por MARIA PRUEBA.")
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "032Cartas.txt")
    assert ing.metadatos.cui_1a == CUI
    assert d.doc_id in ing.docs_ajenos and ing.docs_revisar == []


def test_sin_acta_se_rescata_por_el_juzgado_a_quo(tmp_path):
    escribir(tmp_path, P1 + "002Escrito.txt", ESCRITO)
    escribir(tmp_path, P1 + "003Admite.txt", ADMISORIO)
    escribir(tmp_path, P1 + "004Fallo.txt", FALLO)
    escribir(tmp_path, P1 + "005Correo.txt", IMPUGNACION)
    ajena(tmp_path, "032Cartas.txt", "Escrito al Juzgado 33 Penal Municipal.")
    ing = ingerir(tmp_path, Config())
    assert ing.docs_revisar == [por_nombre(ing, "032Cartas.txt").doc_id]


def test_para_revisar_no_alimenta_los_metadatos(tmp_path):
    caso_sintetico(tmp_path, con_acta_2a=False)
    escribir(
        tmp_path,
        P1 + "008Acta.txt",
        ACTA.format(rad=OTRO_CUI, clase="IMPUGNACIÓN TUTELA"),
    )
    ing = ingerir(tmp_path, Config())
    acta = por_nombre(ing, "008Acta.txt")
    assert acta.rol == "acta_reparto_2a"
    assert ing.docs_revisar == [acta.doc_id]
    assert ing.esperados_faltantes == ["acta_reparto_2a"]
    assert ing.metadatos.fechas.reparto_2a is None


def test_reaplicar_confirmar_mismo_rol_saca_el_documento_de_revisar(tmp_path):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", "Solicitud presentada por MARIA PRUEBA UNO.")
    ing = ingerir(tmp_path, Config())
    d = por_nombre(ing, "032Cartas.txt")
    assert ing.docs_revisar == [d.doc_id]
    nuevo = reaplicar(ing, {d.doc_id: d.rol})
    assert nuevo.docs_revisar == [] and nuevo.docs_ajenos == ing.docs_ajenos
    assert por_nombre(nuevo, "032Cartas.txt").rol_origen == "usuario"
    assert ingest.AVISO_REVISAR not in texto_para_llm(nuevo, max_chars=100000)
    assert not any("para revisar" in a and d.doc_id in a for a in nuevo.alertas)


def test_reaplicar_conserva_revisar_si_no_se_toca_el_documento(tmp_path):
    caso_sintetico(tmp_path)
    ajena(tmp_path, "032Cartas.txt", "Solicitud presentada por MARIA PRUEBA UNO.")
    ing = ingerir(tmp_path, Config())
    escrito = por_nombre(ing, "002Escrito.txt")
    nuevo = reaplicar(ing, {escrito.doc_id: "memorial"})
    assert nuevo.docs_revisar == ing.docs_revisar
