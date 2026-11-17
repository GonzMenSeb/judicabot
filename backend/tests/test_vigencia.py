"""Lectura y clasificación del certificado de vigencia de la tarjeta profesional.

Todos los fixtures de tests/fixtures/vigencia son sintéticos (ver LEEME.md). Ninguna prueba
usa la red.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import shutil
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pypdf import PdfReader

from tutela2 import extension, ingest, registro_apoderados, vigencia
from tutela2.extension import Entrega
from tutela2.models import Apoderado, Identificacion
from tutela2.vigencia import (
    URL_VIGENCIA,
    CertificadoVigencia,
    campos_ocultos,
    clasificar,
    leer_certificado,
    leer_texto,
)

FIXTURES = Path(__file__).parent / "fixtures" / "vigencia"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

CEDULA = "1000000001"
NOMBRE = "MARIA FERNANDA PRUEBA LOPEZ"
CODIGO = "0123456789abcdef" * 4


_ABRIR_REAL = vigencia._abrir


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None, galletas=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)
    monkeypatch.setattr(vigencia, "_abrir", _falla)


def _txt(nombre: str) -> str:
    return (FIXTURES / f"{nombre}.txt").read_text(encoding="utf-8")


def _leer(nombre: str) -> CertificadoVigencia | None:
    """Interpreta un fixture de texto sin pasar por la extracción del PDF."""
    return leer_texto(_txt(nombre))


def _cambiar(texto: str, viejo: str, nuevo: str) -> str:
    assert texto.count(viejo) == 1, viejo
    return texto.replace(viejo, nuevo)


def _modulo(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


VIGENTE = CertificadoVigencia(
    numero="1234567",
    nombre=NOMBRE,
    documento=CEDULA,
    rna_estado="VIGENTE",
    tpa_numero="123456",
    tpa_fecha="04/12/2006",
    tpa_estado="VIGENTE",
    tpa_observaciones="NO REGISTRA",
    rna_observaciones="NO REGISTRA",
    expedido="16/11/2026 10:48:33 PM",
    codigo_verificacion=CODIGO,
)


# ---------------------------------------------------------------- lectura del texto


def test_vigente_se_lee_completo():
    assert _leer("vigente") == VIGENTE


def test_no_vigente_lee_el_estado_y_la_observacion():
    cert = _leer("no_vigente")
    assert cert is not None
    assert cert.documento == "1000000002"
    assert cert.tpa_numero == "123457"
    assert cert.tpa_estado == "SUSPENDIDO"
    assert cert.rna_estado == "VIGENTE"
    assert cert.tpa_observaciones is not None
    assert cert.tpa_observaciones.startswith("Suspendido(a) del ejercicio de la profesión")
    assert cert.tpa_observaciones.endswith("a partir de su ejecutoria.")
    assert "\n" not in cert.tpa_observaciones
    assert cert.rna_observaciones == "NO REGISTRA"


def test_observaciones_en_dos_lineas_se_unen():
    cert = _leer("observaciones")
    assert cert is not None
    assert cert.tpa_estado == "VIGENTE"
    assert cert.tpa_observaciones == (
        "Registra sanción de censura impuesta mediante providencia del 15/03/2024 de una Comisión "
        "Seccional de Disciplina Judicial ficticia, la cual ya fue cumplida."
    )


def test_sin_tpa_deja_vacios_los_campos_de_la_tarjeta():
    cert = _leer("sin_tpa")
    assert cert is not None
    assert cert.documento == "1000000004"
    assert cert.rna_estado == "EXCLUIDO(A)"
    assert cert.rna_observaciones is not None and cert.rna_observaciones.startswith("Excluido(a)")
    assert (cert.tpa_numero, cert.tpa_fecha, cert.tpa_estado, cert.tpa_observaciones) == (None,) * 4
    assert cert.codigo_verificacion is not None


def test_otra_cedula_se_lee_como_un_certificado_valido_de_otra_persona():
    cert = _leer("otra_cedula")
    assert cert is not None
    assert cert.documento == "1000000099"
    assert cert.nombre == "PEDRO JOSE FICTICIO MORA"


@pytest.mark.parametrize("texto", ["", "\n\n  \f\n", "Texto cualquiera sin certificado", "<html>403 Forbidden</html>"])
def test_texto_sin_certificado_es_none(texto):
    assert leer_texto(texto) is None
    assert _leer("vacio") is None


def test_cada_fixture_tiene_un_codigo_de_verificacion_de_64_hex():
    for nombre in ("vigente", "no_vigente", "observaciones", "sin_tpa", "otra_cedula"):
        cert = _leer(nombre)
        assert cert is not None
        assert cert.codigo_verificacion is not None and len(cert.codigo_verificacion) == 64


# ------------------------------------------------------------ cédula no inscrita

CEDULA_NO_INSCRITA = "1000000006"
FRASE_NO_INSCRITA = "Cédula de Ciudadanía N.° 1, NO ESTÁ INSCRITA en la Unidad de\n"


def _no_inscrito() -> str:
    """El texto anonimizado de la Rama Judicial (cédula «1») con una cédula ficticia de longitud válida."""
    return _cambiar(_txt("no_inscrito"), "N.° 1, NO", f"N.° {CEDULA_NO_INSCRITA}, NO")


NO_INSCRITO = CertificadoVigencia(
    inscrito=False,
    documento=CEDULA_NO_INSCRITA,
    numero="7654321",
    expedido="16/11/2026 10:48:33 PM",
    codigo_verificacion=CODIGO,
)


def test_no_inscrito_se_lee_sin_nombre_ni_tablas():
    assert leer_texto(_no_inscrito()) == NO_INSCRITO
    assert NO_INSCRITO.nombre is None and VIGENTE.inscrito is True


def test_no_inscrito_con_la_cedula_del_fixture_de_un_digito_falla_cerrado():
    # El fixture conserva la cédula «1» del anonimizado: no es una cédula que se pueda consultar.
    assert FRASE_NO_INSCRITA in _txt("no_inscrito")
    assert leer_texto(_txt("no_inscrito")) is None


def _variantes_no_inscrito() -> dict[str, str]:
    base = _no_inscrito()
    lineas = [ln.strip() for ln in base.splitlines() if ln.strip()]
    return {
        "pypdf_lineas_recortadas": "\n".join(lineas),
        "todo_en_una_linea": " ".join(lineas),
        "sin_tilde": _cambiar(base, "NO ESTÁ INSCRITA", "NO ESTA INSCRITA"),
        "inscrito": _cambiar(base, "NO ESTÁ INSCRITA", "NO ESTÁ INSCRITO"),
        "inscrito_a": _cambiar(base, "NO ESTÁ INSCRITA", "NO ESTÁ INSCRITO(A)"),
        "salto_dentro_de_la_frase": _cambiar(base, "NO ESTÁ INSCRITA en", "NO ESTÁ\n   INSCRITA\nen"),
        "cedula_partida": _cambiar(base, f"N.° {CEDULA_NO_INSCRITA},", f"N.°\n{CEDULA_NO_INSCRITA} ,"),
        "cedula_con_puntos": _cambiar(base, f"{CEDULA_NO_INSCRITA},", "1.000.000.006,"),
        "tildes_descompuestas": unicodedata.normalize("NFD", base),
        "saltos_de_windows": base.replace("\n", "\r\n"),
    }


VARIANTES_NO_INSCRITO = _variantes_no_inscrito()


@pytest.mark.parametrize("variante", list(VARIANTES_NO_INSCRITO))
def test_no_inscrito_se_lee_igual_con_otra_extraccion(variante):
    assert leer_texto(VARIANTES_NO_INSCRITO[variante]) == NO_INSCRITO


@pytest.mark.parametrize(
    "cambio",
    [
        ("Cédula de Ciudadanía", "Cédula de Extranjería"),
        (f"N.° {CEDULA_NO_INSCRITA},", "N.° 1234,"),
        (f"N.° {CEDULA_NO_INSCRITA},", "N.° 12345678901,"),
        ("NO ESTÁ INSCRITA", "ESTÁ INSCRITA"),
        ("como abogado(a)", "como auxiliar de la justicia"),
    ],
    ids=["otro_documento", "cedula_corta", "cedula_larga", "sin_negacion", "otra_calidad"],
)
def test_no_inscrito_falla_cerrado(cambio):
    assert leer_texto(_cambiar(_no_inscrito(), *cambio)) is None


def test_un_certificado_con_titular_o_tablas_que_ademas_diga_no_inscrita_es_none():
    frase = f"la persona identificada con Cédula de Ciudadanía N.° {CEDULA_NO_INSCRITA}, NO ESTÁ INSCRITA en la Unidad de Registro Nacional de Abogados y Auxiliares de la Justicia como abogado(a).\n"
    assert leer_texto(_txt("vigente") + frase) is None
    con_tabla = _no_inscrito() + "\n                    VIGENCIA RNA\n    ABOGADO(A) INSCRITO(A)   04/12/2006   VIGENTE\n"
    assert leer_texto(con_tabla) is None


def test_clasificar_no_inscrito_solo_por_la_cedula():
    cert = leer_texto(_no_inscrito())
    for nombre in (None, "", NOMBRE, "CUALQUIER OTRO NOMBRE"):
        assert clasificar(cert, CEDULA_NO_INSCRITA, nombre) == "no_inscrito"
    assert clasificar(cert, "1.000.000.006") == "no_inscrito"
    # Otra cédula: la regla de siempre.
    assert clasificar(cert, CEDULA, NOMBRE) == "ilegible"
    assert clasificar(cert, CEDULA_NO_INSCRITA[:-1]) == "ilegible"
    # Sin nombre, el nombre no se puede cotejar: a_nombre_de no lo da por bueno, por eso clasificar decide antes.
    assert vigencia.a_nombre_de(cert, NOMBRE) is False


@pytest.mark.parametrize(
    "extractor",
    [
        "pypdf",
        pytest.param(
            "pdftotext",
            marks=pytest.mark.skipif(not shutil.which("pdftotext"), reason="requiere pdftotext"),
        ),
    ],
)
def test_pdf_no_inscrito_de_punta_a_punta(extractor, monkeypatch):
    if extractor == "pypdf":
        monkeypatch.setattr(ingest.shutil, "which", lambda _nombre: None)
    lector = PdfReader(FIXTURES / "no_inscrito.pdf")
    assert lector.is_encrypted and lector.trailer["/Encrypt"]["/V"] == 5
    cert = leer_certificado((FIXTURES / "no_inscrito.pdf").read_bytes())
    assert cert == NO_INSCRITO
    assert clasificar(cert, CEDULA_NO_INSCRITA, NOMBRE) == "no_inscrito"


def test_el_script_hace_el_pdf_no_inscrito_para_una_cedula(tmp_path):
    modulo = _modulo("fixture_vigencia")
    salida = tmp_path / "no_inscrito.pdf"
    assert modulo.main(["--estado", "no_inscrito", "--cedula", "1.000.000.007", "-s", str(salida)]) == 0
    cert = leer_certificado(salida.read_bytes())
    assert cert == NO_INSCRITO.model_copy(update={"documento": "1000000007"})
    with pytest.raises(SystemExit):
        modulo.main(["--estado", "no_inscrito", "--cedula", "1000000007", "--nombre", "NOMBRE FICTICIO", "-s", str(salida)])


# ------------------------------------------------- tolerancia a la extracción del texto


FILA_TPA = "123456                     04/12/2006                 VIGENTE\n"
ENCABEZADO_PROFESIONAL = "                                  PROFESIONAL\n"


def _variantes() -> dict[str, str]:
    base = _txt("vigente")
    lineas = [ln.strip() for ln in base.splitlines() if ln.strip()]
    return {
        "pypdf_lineas_recortadas": "\n".join(lineas),
        "todo_en_una_linea": " ".join(lineas),
        "salto_de_pagina_tras_la_fila": _cambiar(base, FILA_TPA, FILA_TPA[:-1] + "\f\n"),
        "nombre_partido": _cambiar(base, NOMBRE, "MARIA FERNANDA\nPRUEBA   LOPEZ"),
        "cedula_con_puntos": _cambiar(base, "1000000001,", "1.000.000.001,"),
        "numero_de_certificado_en_otra_linea": _cambiar(base, "N.°: 1234567", "N.°:\n 1234567"),
        "encabezado_despues_de_la_fila": _cambiar(
            _cambiar(base, ENCABEZADO_PROFESIONAL, ""),
            FILA_TPA,
            FILA_TPA + ENCABEZADO_PROFESIONAL,
        ),
        "nota_al_pie_tras_el_estado": _cambiar(base, FILA_TPA, FILA_TPA[:-1] + " 2\n"),
        "codigo_partido": _cambiar(base, CODIGO, CODIGO[:32] + "\n                       " + CODIGO[32:]),
        "espacios_duros_y_ancho_cero": base.replace("VIGENTE", "VIGEN\u200bTE").replace("NO REGISTRA", "NO\u00a0REGISTRA"),
        "tildes_descompuestas": unicodedata.normalize("NFD", base),
        "saltos_de_windows": base.replace("\n", "\r\n"),
    }


VARIANTES = _variantes()


@pytest.mark.parametrize("variante", list(VARIANTES))
def test_el_mismo_certificado_se_lee_igual_con_otra_extraccion(variante):
    assert leer_texto(VARIANTES[variante]) == VIGENTE


# ------------------------------------------------------------------- falla cerrado


def test_seccion_tpa_sin_fila_legible_es_none():
    sin_fila = _cambiar(_txt("vigente"), "  ABOGADO(A) CON TPA                  " + FILA_TPA, "")
    assert leer_texto(sin_fila) is None


def test_columnas_en_otro_orden_no_se_adivinan():
    otro_orden = _cambiar(_txt("vigente"), FILA_TPA, "VIGENTE                 123456                     04/12/2006\n")
    assert leer_texto(otro_orden) is None


def test_estado_en_minuscula_no_se_acepta():
    assert leer_texto(_cambiar(_txt("vigente"), FILA_TPA, FILA_TPA.replace("VIGENTE", "Vigente"))) is None


def test_documento_que_no_es_cedula_de_ciudadania_es_none():
    texto = _cambiar(_txt("vigente"), "CÉDULA DE CIUDADANÍA", "CÉDULA DE EXTRANJERÍA")
    assert leer_texto(texto) is None


@pytest.mark.parametrize("doc", ["1234", "12345678901"])
def test_cedula_con_longitud_imposible_es_none(doc):
    assert leer_texto(_cambiar(_txt("vigente"), CEDULA, doc)) is None


def test_sin_ninguna_seccion_de_vigencia_es_none():
    t = _txt("vigente")
    corto = t[: t.index("VIGENCIA RNA")]
    assert leer_texto(corto) is None


def test_una_fecha_dentro_de_las_observaciones_no_se_toma_por_la_fila():
    # La fila de la tarjeta está dañada; la fecha y las mayúsculas de la observación no la reemplazan.
    t = _txt("no_vigente")
    t = _cambiar(t, "123457                     04/12/2006                 SUSPENDIDO\n", "")
    t = _cambiar(t, "providencia del 01/02/2026,", "providencia del 01/02/2026 SUSPENDIDO")
    assert leer_texto(t) is None


def test_estado_no_vigente_se_lee_tal_cual():
    cert = leer_texto(_cambiar(_txt("vigente"), FILA_TPA, FILA_TPA.replace("VIGENTE", "NO VIGENTE")))
    assert cert is not None and cert.tpa_estado == "NO VIGENTE"


@pytest.mark.parametrize(
    "estado",
    ["VIGENTE DE TARJETA", "VIGENTE FECHA DE", "VIGENTE DE", "DE VIGENTE", "NO VIGENTE DE", "VIGENTE TPA", "SUSPENDIDO DE"],
)
def test_encabezado_intercalado_en_el_estado_de_la_tarjeta_es_ilegible(estado):
    # El extractor (sobre todo pypdf, cuando falta pdftotext) puede intercalar celdas del encabezado en la fila.
    cert = leer_texto(_cambiar(_txt("vigente"), FILA_TPA, FILA_TPA.replace("VIGENTE", estado)))
    assert cert is None
    assert clasificar(cert, CEDULA, NOMBRE) == "ilegible"


FILA_RNA = "04/12/2006                           VIGENTE\n"


def test_encabezado_intercalado_en_el_estado_del_rna_no_da_rojo():
    con_tarjeta = leer_texto(_cambiar(_txt("vigente"), FILA_RNA, FILA_RNA.replace("VIGENTE", "VIGENTE DE")))
    assert con_tarjeta is not None and con_tarjeta.tpa_estado == "VIGENTE"
    assert (con_tarjeta.rna_estado, con_tarjeta.rna_observaciones) == (None, None)
    assert clasificar(con_tarjeta, CEDULA, NOMBRE) == "vigente_obs"

    fila_excluido = "04/12/2006                          EXCLUIDO(A)\n"
    sin_tarjeta = leer_texto(_cambiar(_txt("sin_tpa"), fila_excluido, fila_excluido.replace("EXCLUIDO(A)", "EXCLUIDO(A) DE")))
    assert sin_tarjeta is None
    assert clasificar(sin_tarjeta, "1000000004") == "ilegible"


# ---------------------------------------------------------------- PDF cifrado


def _pdf() -> bytes:
    return (FIXTURES / "sintetico.pdf").read_bytes()


def test_sintetico_esta_cifrado_con_aes_256_y_clave_vacia():
    lector = PdfReader(FIXTURES / "sintetico.pdf")
    assert lector.is_encrypted
    assert lector.trailer["/Encrypt"]["/V"] == 5
    assert len(lector.pages) == 2
    lector.decrypt("")
    assert "CERTIFICADO" in (lector.pages[0].extract_text() or "")


@pytest.mark.parametrize(
    "extractor",
    [
        "pypdf",
        pytest.param(
            "pdftotext",
            marks=pytest.mark.skipif(not shutil.which("pdftotext"), reason="requiere pdftotext"),
        ),
    ],
)
def test_pdf_sintetico_de_punta_a_punta(extractor, monkeypatch):
    if extractor == "pypdf":
        monkeypatch.setattr(ingest.shutil, "which", lambda _nombre: None)
    cert = leer_certificado(_pdf())
    assert cert == VIGENTE
    assert clasificar(cert, CEDULA, NOMBRE) == "vigente"


def test_leer_certificado_rechaza_lo_que_no_es_un_pdf_sin_extraer_texto(monkeypatch):
    def _no_debe_llamarse(_ruta):
        raise AssertionError("no se debe extraer texto de algo que no es un PDF")

    monkeypatch.setattr(ingest, "_textos_pdf", _no_debe_llamarse)
    assert leer_certificado(b"") is None
    assert leer_certificado(b"<html>Request blocked</html>") is None


def test_leer_certificado_con_pdf_dañado_es_none():
    assert leer_certificado(b"%PDF-1.7\nesto no es un pdf") is None
    assert leer_certificado(_pdf()[:300]) is None


def test_leer_certificado_con_pdf_ajeno_es_none(tmp_path):
    modulo = _modulo("fixture_vigencia")
    ajeno = tmp_path / "ajeno.pdf"
    with ajeno.open("wb") as f:
        modulo.construir("Una carta cualquiera\nsin certificado de vigencia").write(f)
    assert leer_certificado(ajeno.read_bytes()) is None


def test_el_script_regenera_un_pdf_que_se_lee_igual(tmp_path):
    modulo = _modulo("fixture_vigencia")
    salida = tmp_path / "otro.pdf"
    assert modulo.main(["-e", str(FIXTURES / "no_vigente.txt"), "-s", str(salida)]) == 0
    cert = leer_certificado(salida.read_bytes())
    assert cert == _leer("no_vigente")
    assert PdfReader(salida).is_encrypted


# --------------------------------------------------------------- campos ocultos


def _html() -> str:
    return (FIXTURES / "formulario.html").read_text(encoding="utf-8")


def test_url_del_certificado():
    assert URL_VIGENCIA == "https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx"


def test_campos_ocultos_del_formulario_publico():
    campos = campos_ocultos(_html())
    assert campos is not None
    assert list(campos) == ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"]
    assert campos["__VIEWSTATEGENERATOR"] == "EC7CB15A"
    assert campos["__VIEWSTATE"].startswith("/wEPDw") and len(campos["__VIEWSTATE"]) > 400
    assert campos["__EVENTVALIDATION"].startswith("/wEd")


def test_el_formulario_tiene_los_controles_que_se_envian():
    html = _html()
    for esperado in (
        'method="post"',
        'action="./Certificados.aspx"',
        'id="form1"',
        'name="ddlCalidad"',
        'name="ddlTipoDocumento"',
        'name="txtDocumento"',
        'maxlength="10"',
        'name="btnTpVigente"',
        'value="Generar"',
        '<option value="1">ABOGADO</option>',
        "<option value=\"1\">C&#201;DULA DE CIUDADAN&#205;A</option>",
    ):
        assert esperado in html


def test_los_valores_del_formulario_encajan_con_la_lista_blanca_de_la_extension():
    # Mismas expresiones que usará extension/puente.js para validar el cuerpo del POST.
    campos = campos_ocultos(_html())
    assert campos is not None
    assert re.fullmatch(r"[A-Za-z0-9+/=]{1,200000}", campos["__VIEWSTATE"])
    assert re.fullmatch(r"[0-9A-F]{8}", campos["__VIEWSTATEGENERATOR"])
    assert re.fullmatch(r"[A-Za-z0-9+/=]{1,20000}", campos["__EVENTVALIDATION"])


def test_campos_ocultos_con_atributos_en_otro_orden_y_comillas_simples():
    html = (
        "<form>"
        "<input value='AAA+/=' id='__VIEWSTATE' name='__VIEWSTATE' type='hidden'>"
        '<INPUT ID="x" VALUE="EC7CB15A" NAME="__VIEWSTATEGENERATOR" TYPE="HIDDEN" />'
        '<input\n  value="BBB"\n  type="hidden"\n  name="__EVENTVALIDATION"\n>'
        "</form>"
    )
    assert campos_ocultos(html) == {
        "__VIEWSTATE": "AAA+/=",
        "__VIEWSTATEGENERATOR": "EC7CB15A",
        "__EVENTVALIDATION": "BBB",
    }


def test_campos_ocultos_decodifica_entidades():
    html = (
        '<input type="hidden" name="__VIEWSTATE" value="a&#43;b&amp;c&#x2F;d&quot;e" />'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" value="EC7CB15A" />'
        '<input type="hidden" name="__EVENTVALIDATION" value="x&#61;&#61;" />'
    )
    campos = campos_ocultos(html)
    assert campos == {"__VIEWSTATE": 'a+b&c/d"e', "__VIEWSTATEGENERATOR": "EC7CB15A", "__EVENTVALIDATION": "x=="}


@pytest.mark.parametrize("falta", ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"])
def test_campos_ocultos_exige_los_tres(falta):
    html = "".join(
        f'<input type="hidden" name="{c}" value="v{c}" />'
        for c in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
        if c != falta
    )
    assert campos_ocultos(html) is None


def test_campos_ocultos_ignora_los_que_no_son_ocultos_o_estan_vacios():
    visible = (
        '<input type="text" name="__VIEWSTATE" value="x" />'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" value="EC7CB15A" />'
        '<input type="hidden" name="__EVENTVALIDATION" value="y" />'
    )
    assert campos_ocultos(visible) is None
    vacio = visible.replace('type="text" name="__VIEWSTATE" value="x"', 'type="hidden" name="__VIEWSTATE" value=""')
    assert campos_ocultos(vacio) is None
    assert campos_ocultos("") is None
    assert campos_ocultos("<html>Request blocked</html>") is None


def test_campos_ocultos_toma_el_primero_si_se_repite():
    html = (
        '<input type="hidden" name="__VIEWSTATE" value="primero" />'
        '<input type="hidden" name="__VIEWSTATE" value="segundo" />'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" value="EC7CB15A" />'
        '<input type="hidden" name="__EVENTVALIDATION" value="y" />'
    )
    campos = campos_ocultos(html)
    assert campos is not None and campos["__VIEWSTATE"] == "primero"


# ----------------------------------------------------------------- clasificar


@pytest.mark.parametrize(
    "pedida",
    [CEDULA, "1.000.000.001", "1 000 000 001", "C.C. 1.000.000.001", f" {CEDULA}\n"],
)
def test_vigente_acepta_la_cedula_con_puntos_y_espacios(pedida):
    assert clasificar(_leer("vigente"), pedida, NOMBRE) == "vigente"


@pytest.mark.parametrize(
    "esperado",
    [
        NOMBRE,
        "María Fernanda Prueba López",
        "maría fernanda prueba lópez",
        "PRUEBA LOPEZ, MARIA FERNANDA",
        "Maria Fernanda Prueba",
        "MARÍA  FERNANDA   PRUEBA   LÓPEZ   DE LA ESPRIELLA",
        None,
        "",
    ],
)
def test_vigente_pliega_tildes_mayusculas_y_orden_del_nombre(esperado):
    assert clasificar(_leer("vigente"), CEDULA, esperado) == "vigente"


def test_nombre_distinto_con_la_misma_cedula_es_otra_persona():
    assert clasificar(_leer("vigente"), CEDULA, "CARLOS ANDRES EJEMPLO RIOS") == "otra_persona"
    assert clasificar(_leer("vigente"), CEDULA, "María Fernanda Pérez") == "otra_persona"


def test_la_ñ_se_pliega_con_la_n():
    cert = _leer("vigente").model_copy(update={"nombre": "MARIA NUÑEZ PEREZ"})
    assert clasificar(cert, CEDULA, "Maria Nunez Perez") == "vigente"
    assert clasificar(cert, CEDULA, "Maria Nuñez") == "vigente"


def test_observaciones_dan_vigente_obs():
    cert = _leer("observaciones")
    assert clasificar(cert, "1000000003", "LUIS ALBERTO MUESTRA PEREZ") == "vigente_obs"


@pytest.mark.parametrize("campo", ["tpa_observaciones", "rna_observaciones"])
@pytest.mark.parametrize("valor", ["Registra una anotación", "", "NO REGISTRA SANCIONES", None])
def test_cualquier_observacion_distinta_de_no_registra_no_es_verde(campo, valor):
    cert = _leer("vigente").model_copy(update={campo: valor})
    assert clasificar(cert, CEDULA, NOMBRE) == "vigente_obs"


def test_no_registra_se_reconoce_con_puntuacion_y_tildes_distintas():
    cert = _leer("vigente").model_copy(update={"tpa_observaciones": "No registra.", "rna_observaciones": "NO  REGISTRA"})
    assert clasificar(cert, CEDULA, NOMBRE) == "vigente"


def test_tarjeta_vigente_sin_poder_leer_el_rna_no_es_verde():
    cert = _leer("vigente").model_copy(update={"rna_estado": None, "rna_observaciones": None})
    assert clasificar(cert, CEDULA, NOMBRE) == "vigente_obs"
    cert = _leer("vigente").model_copy(update={"rna_estado": "SUSPENDIDO"})
    assert clasificar(cert, CEDULA, NOMBRE) == "vigente_obs"


def test_tarjeta_con_otro_estado_es_no_vigente():
    assert clasificar(_leer("no_vigente"), "1000000002", "CARLOS ANDRES EJEMPLO RIOS") == "no_vigente"
    for estado in ("NO VIGENTE", "CANCELADA", "vigente", "VIGENTES", "VIGENTE."):
        cert = _leer("vigente").model_copy(update={"tpa_estado": estado})
        assert clasificar(cert, CEDULA, NOMBRE) == "no_vigente", estado


def test_sin_fila_de_tarjeta_y_rna_no_vigente_es_no_vigente():
    assert clasificar(_leer("sin_tpa"), "1000000004", "ANA MARIA EJEMPLO GOMEZ") == "no_vigente"


def test_sin_fila_de_tarjeta_y_rna_vigente_o_ausente_no_se_concluye():
    cert = _leer("sin_tpa")
    assert clasificar(cert.model_copy(update={"rna_estado": "VIGENTE"}), "1000000004") == "ilegible"
    assert clasificar(cert.model_copy(update={"rna_estado": None}), "1000000004") == "ilegible"


def test_ilegible_cuando_no_hay_certificado():
    assert clasificar(None, CEDULA, NOMBRE) == "ilegible"
    assert clasificar(_leer("vacio"), CEDULA, NOMBRE) == "ilegible"
    assert clasificar(CertificadoVigencia(), CEDULA, NOMBRE) == "ilegible"


def test_cedula_distinta_es_ilegible_aunque_el_certificado_sea_valido():
    assert clasificar(_leer("otra_cedula"), CEDULA, NOMBRE) == "ilegible"
    assert clasificar(_leer("otra_cedula"), CEDULA, "PEDRO JOSE FICTICIO MORA") == "ilegible"
    assert clasificar(_leer("otra_cedula"), "1000000099", "PEDRO JOSE FICTICIO MORA") == "vigente"


@pytest.mark.parametrize("pedida", ["", "   ", "C.C.", "sin dígitos"])
def test_cedula_pedida_vacia_es_ilegible(pedida):
    assert clasificar(_leer("vigente"), pedida, NOMBRE) == "ilegible"


def test_cedula_que_solo_comparte_un_prefijo_no_coincide():
    assert clasificar(_leer("vigente"), CEDULA[:-1], NOMBRE) == "ilegible"
    assert clasificar(_leer("vigente"), CEDULA + "0", NOMBRE) == "ilegible"


def test_cedula_distinta_pesa_mas_que_el_nombre_distinto():
    assert clasificar(_leer("vigente"), "1000000002", "OTRO NOMBRE COMPLETO") == "ilegible"


def test_el_resultado_es_uno_de_los_seis_estados():
    posibles = {"vigente", "vigente_obs", "no_vigente", "no_inscrito", "otra_persona", "ilegible"}
    for nombre in ("vigente", "no_vigente", "observaciones", "sin_tpa", "otra_cedula", "vacio"):
        cert = _leer(nombre)
        doc = cert.documento if cert else CEDULA
        assert clasificar(cert, doc or CEDULA, cert.nombre if cert else None) in posibles


def test_ningun_mensaje_ni_registro_del_modulo_lleva_la_cedula(caplog):
    with caplog.at_level("DEBUG", logger="tutela2"):
        assert leer_certificado(b"%PDF-1.7\nroto") is None
        leer_certificado(_pdf())
        clasificar(_leer("vigente"), CEDULA, NOMBRE)
    assert CEDULA not in caplog.text


# ------------------------------------------------------- script de anonimización


def test_anonimizar_reemplaza_los_datos_personales_con_la_misma_longitud():
    anon = _modulo("anonimizar_certificado")
    base = _txt("vigente")
    real = (
        base.replace(NOMBRE, "ÁNGELA MARÍA CÁRDENAS NÚÑEZ")
        .replace("1000000001", "1032456789")
        .replace("123456  ", "987654  ")
        .replace("1234567\n", "7654321\n")
        .replace(CODIGO, "9f" * 32)
        .replace("Nombre Ficticio Del Firmante", "Carlos Real Del Cargo Directivo")
    )
    for dato in ("ÁNGELA", "1032456789", "987654", "7654321", "9f9f9f9f", "Carlos Real"):
        assert dato in real

    texto, conteo = anon.anonimizar(real)

    for dato in ("ÁNGELA", "CÁRDENAS", "1032456789", "987654", "7654321", "9f9f9f9f", "Carlos", "Cargo Directivo"):
        assert dato not in texto
    assert conteo["nombre"] == conteo["cedula"] == conteo["tarjeta"] == conteo["numero"] == conteo["firmante"] == 1
    assert conteo["codigo"] == 2
    real_lineas, anon_lineas = real.splitlines(), texto.splitlines()
    assert [len(x) for x in real_lineas] == [len(x) for x in anon_lineas]
    cert = leer_texto(texto)
    assert cert is not None
    assert (cert.documento, cert.tpa_numero, cert.numero) == ("1000000001", "123456", "1234567")
    assert cert.codigo_verificacion == CODIGO
    assert cert.nombre is not None and cert.nombre != NOMBRE and len(cert.nombre) == len("ÁNGELA MARÍA CÁRDENAS NÚÑEZ")
    assert clasificar(cert, "1000000001", NOMBRE) == "otra_persona"


def test_anonimizar_conserva_la_cedula_con_puntos_y_los_puntos():
    anon = _modulo("anonimizar_certificado")
    real = _cambiar(_txt("vigente"), "1000000001,", "1.032.456.789,")
    texto, _ = anon.anonimizar(real)
    assert "1.032.456.789" not in texto
    assert "1.000.000.001," in texto


def test_anonimizar_falla_si_no_hay_titular():
    anon = _modulo("anonimizar_certificado")
    with pytest.raises(ValueError):
        anon.anonimizar("Un texto cualquiera\nsin certificado")


def test_anonimizar_acepta_un_fixture_ya_ficticio():
    anon = _modulo("anonimizar_certificado")
    texto, _ = anon.anonimizar(_txt("vigente"))
    cert = leer_texto(texto)
    assert cert is not None and cert.documento == "1000000001" and cert.tpa_estado == "VIGENTE"


def test_anonimizar_por_linea_de_comandos(tmp_path, capsys):
    anon = _modulo("anonimizar_certificado")
    entrada = tmp_path / "real.txt"
    entrada.write_text(_cambiar(_txt("vigente"), "1000000001,", "1032456789,"), encoding="utf-8")
    salida = tmp_path / "anonimo.txt"
    assert anon.main([str(entrada), "-o", str(salida)]) == 0
    assert "1032456789" not in salida.read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert "1032456789" not in err and "cedula=1" in err
    assert anon.main([str(tmp_path / "no_existe.txt")]) == 1
    vacio = tmp_path / "vacio.txt"
    vacio.write_text("", encoding="utf-8")
    assert anon.main([str(vacio)]) == 2


# ------------------------------------------------------- consulta automática: cola

CC_A = "1017234567"
CC_B = "52345671"
TITULARES = {CC_A: ("ANDREA PAOLA GIRALDO MONTOYA", "287415"), CC_B: ("CARLOS ANDRES EJEMPLO RIOS", "123457")}
AP_A, AP_B = "ap-aaaaaaaaaa", "ap-bbbbbbbbbb"
T0 = datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc).timestamp()
NOMBRE_CERTIFICADO = re.compile(r"ap-[a-z0-9]{10}-[0-9a-f]{16}\.pdf")
HTML_ERROR = b"<!DOCTYPE html><html><body>Error en la solicitud</body></html>"


class Reloj:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


def _dormir(reloj: Reloj):
    def dormir(segundos: float) -> bool:
        reloj.avanzar(segundos)
        return False

    return dormir


class RamaFalsa:
    """La Rama Judicial vista a través de la extensión: anota cada llamada a ``extension.pedir`` con su
    hora, el método y el formulario. Los POST responden en orden lo que haya en ``respuestas`` (un código
    HTTP, ``"html"``, ``"timeout"``, ``"no_vigente"``) y, si no queda nada, el certificado vigente."""

    def __init__(self, reloj: Reloj) -> None:
        self.reloj = reloj
        self.estado = "conectada"
        self.llamadas: list[tuple[float, str, dict | None]] = []
        self.respuestas: list = []
        self.html = (FIXTURES / "formulario.html").read_bytes()

    def pedir(self, servicio, url, metodo="GET", formulario=None, espera_s=75.0):
        assert (servicio, url, espera_s) == ("vigencia", URL_VIGENCIA, 75.0)
        self.llamadas.append((self.reloj(), metodo, dict(formulario) if formulario is not None else None))
        if self.estado == "no_conectada":
            raise extension.ExtensionNoConectada("sin extensión")
        if self.estado == "desactualizada":
            raise extension.ExtensionDesactualizada("vieja")
        if metodo == "GET":
            return Entrega("ok", self.html, "", 200, "text/html; charset=utf-8")
        respuesta = self.respuestas.pop(0) if self.respuestas else "vigente"
        if respuesta in ("vigente", "no_vigente"):
            cc = formulario["txtDocumento"]
            nombre, tarjeta = TITULARES[cc]
            fecha = datetime.fromtimestamp(self.reloj(), timezone.utc)
            pdf = vigencia.certificado_ficticio(nombre, cc, tarjeta, vigente=respuesta == "vigente", fecha=fecha)
            return Entrega("ok", pdf, "", 200, "application/pdf")
        if respuesta == "html":
            return Entrega("ok", HTML_ERROR, "", 200, "text/html; charset=utf-8")
        if respuesta == "timeout":
            raise TimeoutError("la extensión no respondió a tiempo")
        return Entrega("rechazo", None, f"HTTP {respuesta}", respuesta, "text/html")

    @property
    def metodos(self) -> list[str]:
        return [m for _, m, _ in self.llamadas]

    @property
    def horas(self) -> list[float]:
        return [t for t, _, _ in self.llamadas]


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def rama(monkeypatch, reloj) -> RamaFalsa:
    r = RamaFalsa(reloj)
    monkeypatch.setattr(extension, "pedir", r.pedir)
    monkeypatch.setattr(extension, "estado_conexion", lambda servicio="vigencia": r.estado)
    return r


@pytest.fixture
def modos() -> dict[str, str]:
    """Modo de consulta por nombre de caso; los que no están consultan por la extensión."""
    return {}


def _nueva_cola(reloj: Reloj, tmp_path: Path, modos: dict[str, str]) -> vigencia.ColaVigencia:
    return vigencia.ColaVigencia(
        reloj=reloj,
        dormir=_dormir(reloj),
        carpeta_cache=tmp_path / "cache" / "vigencias",
        modo_de=lambda caso: modos.get(caso.name, "extension"),
    )


@pytest.fixture
def cola(reloj, tmp_path, rama, modos) -> vigencia.ColaVigencia:
    return _nueva_cola(reloj, tmp_path, modos)


def _procesar(cola: vigencia.ColaVigencia, reloj: Reloj, horizonte: float = 3600.0) -> None:
    """Corre la cola como lo haría su hilo, adelantando el reloj en vez de esperar, hasta que no quede
    nada que hacer o hasta ``horizonte`` segundos más tarde."""
    limite = reloj() + horizonte
    for _ in range(10_000):
        espera = cola.paso()
        if espera is None:
            return
        if espera > 0:
            if reloj() + espera > limite:
                return
            reloj.avanzar(espera)
    raise AssertionError("la cola no terminó")


def _ap(cedula: str, ap_id: str, **cambios) -> Apoderado:
    nombre, tarjeta = TITULARES[cedula]
    return Apoderado(
        **{"id": ap_id, "nombre": nombre.title(), "parte": "Entidad Prestadora Uno", "cedula": cedula, "tarjeta": tarjeta, **cambios}
    )


def _caso(tmp_path: Path, nombre: str, *apoderados: Apoderado) -> Path:
    caso = tmp_path / "casos" / nombre
    caso.mkdir(parents=True)
    registro_apoderados.espejar(caso, Identificacion(ingesta_sha="abc", apoderados=list(apoderados), documentos_revisados=3))
    return caso


def _consulta(caso: Path, cedula: str):
    return registro_apoderados.leer(caso).consultas.get(cedula)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _espaciadas(rama: RamaFalsa) -> bool:
    """Cada POST sale enseguida de su GET (sin esperar: lleva las cookies de afinidad de ese GET) y entre el
    último pedido de una consulta y el GET de la siguiente pasan al menos ``PAUSA_S``."""
    for i, (t, metodo, _) in enumerate(rama.llamadas):
        if i == 0:
            continue
        previa = rama.llamadas[i - 1]
        if metodo == "POST" and (previa[1] != "GET" or t != previa[0]):
            return False
        if metodo == "GET" and t - previa[0] < vigencia.PAUSA_S:
            return False
    return True


def test_consulta_por_la_extension_con_pedidos_espaciados_y_guarda_como_la_subida(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A), _ap(CC_B, AP_B))
    assert cola.encolar(caso, [CC_A, "52.345.671"]) == 2
    assert (cola.fase(CC_A, caso), cola.fase(CC_B), cola.activa(caso)) == ("en_cola", "en_cola", True)

    _procesar(cola, reloj)

    # Cada consulta pide su propio formulario y lo envía enseguida; entre dos consultas pasan al menos 30 s.
    assert rama.metodos == ["GET", "POST", "GET", "POST"]
    assert _espaciadas(rama)
    assert rama.horas[1] == rama.horas[0] and rama.horas[2] - rama.horas[1] >= vigencia.PAUSA_S
    campos = campos_ocultos(_html())
    posts = [f for _, m, f in rama.llamadas if m == "POST"]
    for enviado, cc in zip(posts, [CC_A, CC_B], strict=True):
        assert enviado == {**campos, "ddlCalidad": "1", "ddlTipoDocumento": "1", "txtDocumento": cc, "btnTpVigente": "Generar"}
    for cc, ap_id in ((CC_A, AP_A), (CC_B, AP_B)):
        c = _consulta(caso, cc)
        assert (c.estado, c.origen, c.detalle) == ("vigente", "extension", vigencia.DETALLES["extension"])
        assert c.datos.documento == cc and c.datos.tpa_numero == TITULARES[cc][1]
        assert c.intentos_auto == 0 and c.proximo_intento is None
        nombre = Path(c.certificado).name
        assert NOMBRE_CERTIFICADO.fullmatch(nombre) and nombre.startswith(ap_id)
        pdf = registro_apoderados.ruta_certificado(caso, c.certificado).read_bytes()
        assert hashlib.sha256(pdf).hexdigest() == c.sha256
    assert (cola.fase(CC_A, caso), cola.activa(caso), cola.pausa_hasta()) == (None, False, None)


def test_el_formulario_que_se_envia_pasa_la_lista_blanca_de_la_extension():
    campos = vigencia.formulario(campos_ocultos(_html()), CC_A)
    assert len(campos) == 7
    extension._validar("vigencia", URL_VIGENCIA, "POST", campos)
    for mala in ("1234", "12345678901", "12a45678", " 1017234567", ""):
        with pytest.raises(ValueError):
            vigencia.formulario(campos_ocultos(_html()), mala)


@pytest.mark.parametrize("fallo", [500, 503, 429, 403, "html", "timeout"])
def test_un_fallo_pausa_toda_la_cola_15_minutos_y_deja_reintento(cola, rama, reloj, tmp_path, fallo):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A), _ap(CC_B, AP_B))
    rama.respuestas = [fallo]
    cola.encolar(caso, [CC_A, CC_B])
    _procesar(cola, reloj, horizonte=120)

    t_fallo = rama.horas[-1]
    assert rama.metodos == ["GET", "POST"]
    c = _consulta(caso, CC_A)
    assert (c.estado, c.origen, c.intentos_auto) == ("inaccesible", "extension", 1)
    assert c.proximo_intento == _iso(t_fallo + vigencia.ENFRIAMIENTO_S) and c.certificado is None
    assert cola.pausa_hasta() == datetime.fromtimestamp(t_fallo + vigencia.ENFRIAMIENTO_S, timezone.utc)
    # Mientras espera el reintento, el caso ve que necesita ayuda; la otra cédula sigue en cola.
    assert (cola.fase(CC_A, caso), cola.fase(CC_B, caso), _consulta(caso, CC_B)) == (None, "en_cola", None)

    _procesar(cola, reloj, horizonte=2 * 3600)
    despues = [t for t in rama.horas if t > t_fallo]
    assert despues and min(despues) >= t_fallo + vigencia.ENFRIAMIENTO_S
    assert _espaciadas(rama)
    assert (_consulta(caso, CC_A).estado, _consulta(caso, CC_B).estado) == ("vigente", "vigente")
    assert cola.pausa_hasta() is None


def test_el_formulario_no_se_guarda_de_una_consulta_a_otra(cola, rama, reloj, tmp_path):
    """Dos consultas, dos GET: los campos ocultos son del servidor que atendió ese GET (afinidad)."""
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A), _ap(CC_B, AP_B))
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj)
    reloj.avanzar(5)
    cola.encolar(caso, [CC_B])
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST", "GET", "POST"]
    assert _espaciadas(rama)
    assert (_consulta(caso, CC_A).estado, _consulta(caso, CC_B).estado) == ("vigente", "vigente")
    assert not hasattr(cliente_de(cola), "_campos")


def test_una_pagina_de_error_500_tras_el_get_enfria_la_cola_sin_reintentar_enseguida(cola, rama, reloj, tmp_path, monkeypatch):
    """Con la afinidad, un error tras un GET recién hecho es una falla real: no se vuelve a pedir el formulario."""
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    error_runtime = b"<!DOCTYPE html><html><head><title>Error en runtime</title></head><body>Server Error</body></html>"

    def responde_500(servicio, url, metodo="GET", formulario=None, espera_s=75.0):
        if metodo == "POST":
            rama.llamadas.append((reloj(), metodo, dict(formulario)))
            return Entrega("rechazo", error_runtime, "HTTP 500", 500, "text/html; charset=utf-8")
        return rama.pedir(servicio, url, metodo, formulario, espera_s)

    monkeypatch.setattr(extension, "pedir", responde_500)
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=vigencia.ENFRIAMIENTO_S - 1)
    assert rama.metodos == ["GET", "POST"]
    c = _consulta(caso, CC_A)
    assert (c.estado, c.intentos_auto, c.detalle) == ("inaccesible", 1, "La Rama Judicial respondió con un error (HTTP 500).")
    assert cola.pausa_hasta() == datetime.fromtimestamp(rama.horas[-1] + vigencia.ENFRIAMIENTO_S, timezone.utc)

    # Lo mismo con una página HTML en vez del PDF y código 200 (otra cola, otro caso): no hay segundo GET.
    otro = _caso(tmp_path, "dos", _ap(CC_B, AP_B))
    otra_cola = _nueva_cola(reloj, tmp_path, modos={})
    monkeypatch.setattr(extension, "pedir", rama.pedir)
    rama.llamadas.clear()
    rama.respuestas = ["html"]
    otra_cola.encolar(otro, [CC_B])
    _procesar(otra_cola, reloj, horizonte=vigencia.ENFRIAMIENTO_S - 1)
    assert rama.metodos == ["GET", "POST"]
    c = _consulta(otro, CC_B)
    assert (c.estado, c.detalle) == ("inaccesible", vigencia.SIN_CERTIFICADO) and otra_cola.pausa_hasta() is not None


def test_dos_casos_que_esperan_la_misma_cedula_reciben_una_sola_consulta(cola, rama, reloj, tmp_path):
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    dos = _caso(tmp_path, "dos", _ap(CC_A, "ap-cccccccccc", parte="Otra Entidad"), _ap(CC_B, AP_B))
    assert cola.encolar(uno, [CC_A]) == 1
    assert cola.encolar(dos, [CC_A, CC_A]) == 1
    assert cola.fase(CC_A, uno) == cola.fase(CC_A, dos) == "en_cola"
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST"]
    a, b = _consulta(uno, CC_A), _consulta(dos, CC_A)
    assert a.estado == b.estado == "vigente" and a.sha256 == b.sha256
    assert Path(a.certificado).name.startswith(AP_A) and Path(b.certificado).name.startswith("ap-cccccccccc")
    assert _consulta(dos, CC_B) is None


def test_la_cache_sirve_un_dia_y_luego_se_consulta_de_nuevo(cola, rama, reloj, tmp_path):
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    cola.encolar(uno, [CC_A])
    _procesar(cola, reloj)
    original = _consulta(uno, CC_A)
    cache = tmp_path / "cache" / "vigencias"
    assert sorted(p.name for p in cache.iterdir()) == sorted(
        f"{hashlib.sha256(CC_A.encode()).hexdigest()}{s}" for s in (".json", ".pdf")
    )

    reloj.avanzar(vigencia.TTL_S - 60)
    dos = _caso(tmp_path, "dos", _ap(CC_A, AP_A))
    cola.encolar(dos, [CC_A])
    rama.estado = "no_conectada"  # la caché no necesita la extensión
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST"]
    copia = _consulta(dos, CC_A)
    assert (copia.estado, copia.origen, copia.consultado_en, copia.sha256) == (
        "vigente", "extension", original.consultado_en, original.sha256
    )

    rama.estado = "conectada"
    reloj.avanzar(120)
    tres = _caso(tmp_path, "tres", _ap(CC_A, AP_A))
    cola.encolar(tres, [CC_A])
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST", "GET", "POST"]
    assert _consulta(tres, CC_A).consultado_en == _iso(rama.horas[-1])


def test_sin_extension_la_consulta_espera_sin_gastar_intentos_y_sigue_al_conectar(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    cola.encolar(caso, [CC_A])
    assert cola.paso() == 0.0  # mira la caché
    assert cola.paso() == vigencia.REVISION_ESTACIONADOS_S
    _procesar(cola, reloj, horizonte=3 * 3600)
    assert rama.llamadas == [] and _consulta(caso, CC_A) is None
    assert (cola.fase(CC_A, caso), cola.activa(caso)) == (None, False)

    rama.estado = "conectada"
    cola.despertar()
    assert cola.fase(CC_A, caso) == "en_cola"
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST"] and _consulta(caso, CC_A).estado == "vigente"


def test_si_la_extension_se_cae_a_mitad_la_consulta_vuelve_a_esperar(cola, rama, reloj, tmp_path, monkeypatch):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))

    def se_cae(*args, **kwargs):
        rama.estado = "no_conectada"
        return rama.pedir(*args, **kwargs)

    monkeypatch.setattr(extension, "pedir", se_cae)
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=600)
    assert _consulta(caso, CC_A) is None and cola._intentos == {}
    monkeypatch.setattr(extension, "pedir", rama.pedir)
    rama.estado = "conectada"
    _procesar(cola, reloj)
    assert _consulta(caso, CC_A).estado == "vigente"


def test_a_una_extension_desactualizada_no_se_le_pide_nada(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.estado = "desactualizada"
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=6 * 3600)
    assert rama.llamadas == [] and _consulta(caso, CC_A) is None and cola.fase(CC_A, caso) is None

    cliente = vigencia.VigenciaExtension()
    assert cliente.consultar(CC_A) == vigencia.Resultado("desactualizada")
    assert rama.llamadas == []


def test_maximo_tres_intentos_automaticos_por_dia(cola, rama, reloj, tmp_path, modos):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.respuestas = [500] * 10
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=4 * 3600)
    posts = [t for t, m, _ in rama.llamadas if m == "POST"]
    assert len(posts) == vigencia.MAX_AUTO_DIA
    assert all(b - a >= vigencia.ENFRIAMIENTO_S for a, b in zip(posts, posts[1:]))
    c = _consulta(caso, CC_A)
    assert (c.estado, c.intentos_auto, c.proximo_intento) == ("inaccesible", 3, None)
    assert cola.fase(CC_A, caso) is None and cola._pedidos == {}

    assert cola.encolar(caso, [CC_A]) == 0
    # El tope se recuerda aunque el servidor se reinicie: sale del registro del caso.
    assert _nueva_cola(reloj, tmp_path, modos).encolar(caso, [CC_A]) == 0
    reloj.t = datetime(2026, 11, 18, 0, 0, 1, tzinfo=timezone.utc).timestamp()
    assert cola.encolar(caso, [CC_A]) == 1


def test_forzar_ignora_el_resultado_la_cache_y_el_tope_pero_no_el_enfriamiento(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj)
    primero = _consulta(caso, CC_A)
    assert cola.encolar(caso, [CC_A]) == 0  # ya tiene resultado

    reloj.avanzar(60)
    rama.respuestas = ["no_vigente"]
    assert cola.encolar(caso, [CC_A], forzar=True) == 1
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST", "GET", "POST"]  # sin caché
    segundo = _consulta(caso, CC_A)
    assert segundo.estado == "no_vigente" and segundo.sha256 != primero.sha256
    # El certificado reemplazado se borra: ya nadie lo usa.
    assert registro_apoderados.ruta_certificado(caso, primero.certificado) is None
    assert registro_apoderados.ruta_certificado(caso, segundo.certificado) is not None

    rama.respuestas = [500, 500, 500, 500]
    for _ in range(3):
        cola.encolar(caso, [CC_A], forzar=True)
        _procesar(cola, reloj, horizonte=60)
    t_fallo = rama.horas[-1]
    assert cola.pausa_hasta() is not None
    assert _consulta(caso, CC_A).estado == "no_vigente"  # un fallo no pisa un resultado

    assert cola.encolar(caso, [CC_A], forzar=True) == 1
    assert cola.fase(CC_A, caso) == "en_cola"
    _procesar(cola, reloj, horizonte=2 * 3600)
    assert rama.horas[-1] >= t_fallo + vigencia.ENFRIAMIENTO_S


def test_un_resultado_que_llega_tarde_no_pisa_el_certificado_subido_a_mano(cola, rama, reloj, tmp_path, monkeypatch):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    manual = registro_apoderados.ConsultaVigencia(
        estado="no_vigente", origen="manual", consultado_en=_iso(reloj()), certificado="certificados/x.pdf", sha256="ab" * 32
    )

    def sube_mientras_tanto(servicio, url, metodo="GET", formulario=None, espera_s=75.0):
        # El despacho sube el certificado con el POST ya en camino: la respuesta llega tarde.
        if metodo == "POST":
            registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CC_A: manual}))
        return rama.pedir(servicio, url, metodo, formulario, espera_s)

    monkeypatch.setattr(extension, "pedir", sube_mientras_tanto)
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST"]
    assert _consulta(caso, CC_A) == manual


def test_no_consulta_ni_guarda_una_cedula_que_ningun_apoderado_del_caso_usa(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    assert cola.encolar(caso, [CC_B]) == 1
    _procesar(cola, reloj)
    assert rama.llamadas == [] and cola._pedidos == {}
    assert registro_apoderados.leer(caso).consultas == {}
    assert not (caso / "apoderados" / "certificados").exists()


def _posts(rama: RamaFalsa) -> list[str]:
    return [f["txtDocumento"] for _, m, f in rama.llamadas if m == "POST"]


def test_apagar_la_consulta_despues_de_encolar_no_envia_nada(cola, rama, reloj, tmp_path, modos):
    """Compuerta legal: con la consulta apagada nada sale, tampoco lo que ya estaba en cola."""
    # Un pedido que esperaba la extensión.
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    assert cola.encolar(uno, [CC_A]) == 1
    _procesar(cola, reloj, horizonte=600)
    modos["uno"] = "apagada"
    rama.estado = "conectada"
    cola.despertar()
    _procesar(cola, reloj)
    assert rama.llamadas == [] and cola._pedidos == {} and _consulta(uno, CC_A) is None

    # Un reintento automático programado tras un fallo.
    dos = _caso(tmp_path, "dos", _ap(CC_B, AP_B))
    rama.respuestas = [503]
    cola.encolar(dos, [CC_B])
    _procesar(cola, reloj, horizonte=60)
    assert rama.metodos == ["GET", "POST"] and _consulta(dos, CC_B).proximo_intento is not None
    modos["dos"] = "directa"  # otro modo tampoco hereda el pedido: el caso lo vuelve a pedir si quiere
    _procesar(cola, reloj, horizonte=2 * 3600)
    assert rama.metodos == ["GET", "POST"] and cola._pedidos == {}


@pytest.mark.parametrize("cambio", ["apagar", "retirar", "borrar", "otra_cedula"])
def test_lo_que_cambia_entre_el_formulario_y_el_envio_detiene_el_post(cola, rama, reloj, tmp_path, modos, monkeypatch, cambio):
    """Se comprueba justo antes de cada pedido, también antes del POST que sigue a su GET: la cédula no sale."""
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A).model_copy(update={"cedula": None}))
    registro_apoderados.actualizar(caso, lambda r: r.ajustes.update({AP_A: registro_apoderados.Ajuste(cedula=CC_A)}))

    def cambia_tras_el_get(servicio, url, metodo="GET", formulario=None, espera_s=75.0):
        entrega = rama.pedir(servicio, url, metodo, formulario, espera_s)
        if metodo == "GET":
            if cambio == "apagar":
                modos["uno"] = "apagada"
            elif cambio == "retirar":
                assert cola.retirar(caso) == 1
            elif cambio == "borrar":
                registro_apoderados.borrar(caso)
            else:
                registro_apoderados.actualizar(caso, lambda r: r.ajustes.update({AP_A: registro_apoderados.Ajuste(cedula=CC_B)}))
        return entrega

    monkeypatch.setattr(extension, "pedir", cambia_tras_el_get)
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj)
    assert rama.metodos == ["GET"]
    assert cola._pedidos == {} and cola._intentos == {} and cola.pausa_hasta() is None
    assert cambio == "borrar" or _consulta(caso, CC_A) is None


def test_una_cedula_corregida_no_se_envia_aunque_ya_estuviera_en_cola(cola, rama, reloj, tmp_path):
    """Una cédula mal escrita puede ser de otra persona: corregida, la vieja no sale aunque esperara en cola."""
    mal = "52345671"  # la de otro abogado, escrita por error
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A).model_copy(update={"cedula": None}))
    registro_apoderados.actualizar(caso, lambda r: r.ajustes.update({AP_A: registro_apoderados.Ajuste(cedula=mal)}))
    rama.estado = "no_conectada"
    assert cola.encolar(caso, [mal]) == 1
    _procesar(cola, reloj, horizonte=600)

    registro_apoderados.actualizar(caso, lambda r: r.ajustes.update({AP_A: registro_apoderados.Ajuste(cedula=CC_A)}))
    assert cola.encolar(caso, [CC_A]) == 1
    rama.estado = "conectada"
    cola.despertar()
    _procesar(cola, reloj)
    assert _posts(rama) == [CC_A]
    assert _consulta(caso, CC_A).estado == "vigente" and _consulta(caso, mal) is None


def test_un_certificado_subido_a_mano_saca_el_pedido_sin_enviarlo(cola, rama, reloj, tmp_path):
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    dos = _caso(tmp_path, "dos", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    cola.encolar(uno, [CC_A])
    cola.encolar(dos, [CC_A])
    _procesar(cola, reloj, horizonte=600)
    manual = registro_apoderados.ConsultaVigencia(estado="vigente", origen="manual", consultado_en=_iso(reloj()))
    for caso in (uno, dos):
        registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CC_A: manual}))
    rama.estado = "conectada"
    # La subida lo retira enseguida, así la pestaña deja de verlo «En cola»...
    assert cola.retirar(uno, ["1.017.234.567"]) == 1
    assert (cola.fase(CC_A, uno), cola.fase(CC_A, dos), cola.activa(uno)) == (None, "en_cola", False)
    # ...y si no se retiró, la cola lo comprueba antes de enviar: el caso ya tiene su certificado.
    cola.despertar()
    _procesar(cola, reloj)
    assert rama.llamadas == [] and cola._pedidos == {}
    assert _consulta(uno, CC_A) == manual == _consulta(dos, CC_A)
    # Un caso que pidió forzar sí espera la consulta aunque tenga resultado.
    assert cola.encolar(dos, [CC_A], forzar=True) == 1
    _procesar(cola, reloj)
    assert rama.metodos == ["GET", "POST"] and _consulta(dos, CC_A).origen == "extension"


def test_un_caso_reiniciado_no_consulta_lo_que_esperaba(cola, rama, reloj, tmp_path):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=600)
    registro_apoderados.borrar(caso)  # api.nuevo
    rama.estado = "conectada"
    cola.despertar()
    _procesar(cola, reloj)
    assert rama.llamadas == [] and cola._pedidos == {}
    assert not registro_apoderados.carpeta(caso).exists()


def test_retirar_saca_al_caso_y_deja_a_los_demas(cola, rama, reloj, tmp_path):
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A), _ap(CC_B, AP_B))
    dos = _caso(tmp_path, "dos", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    cola.encolar(uno, [CC_A, CC_B])
    cola.encolar(dos, [CC_A])
    assert cola.retirar(uno, [CC_B, "123"]) == 1
    assert sorted(c for _, c in cola._pedidos) == [CC_A]
    assert cola.retirar(uno) == 1 and cola.retirar(uno) == 0
    assert [list(p.casos) for p in cola._pedidos.values()] == [[dos.resolve()]]


def test_si_la_extension_se_desconecta_con_el_pedido_en_vuelo_no_gasta_intentos_ni_pausa(cola, rama, reloj, tmp_path, monkeypatch):
    """Cerrar el navegador (o que se duerma) no es una falla de la Rama Judicial: el pedido espera otra extensión."""
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))

    def se_desconecta(servicio, url, metodo="GET", formulario=None, espera_s=75.0):
        rama.llamadas.append((reloj(), metodo, formulario))
        rama.estado = "no_conectada"
        return extension.DESCONECTADA  # lo que entrega extension.pedir si el socket se cierra con el pedido en vuelo

    monkeypatch.setattr(extension, "pedir", se_desconecta)
    cola.encolar(caso, [CC_A])
    _procesar(cola, reloj, horizonte=600)
    assert rama.metodos == ["GET"]
    assert _consulta(caso, CC_A) is None and cola._intentos == {} and cola.pausa_hasta() is None
    assert cliente_de(cola).consultar(CC_A) == vigencia.Resultado("no_conectada")

    monkeypatch.setattr(extension, "pedir", rama.pedir)
    rama.estado = "conectada"
    cola.despertar()
    _procesar(cola, reloj)
    assert _consulta(caso, CC_A).estado == "vigente"


def cliente_de(cola: vigencia.ColaVigencia) -> vigencia.VigenciaExtension:
    cliente = cola.clientes["extension"]
    assert isinstance(cliente, vigencia.VigenciaExtension)
    return cliente


@pytest.mark.parametrize("escrita", ["１０１７２３４５６７", "١٠١٧٢٣٤٥٦٧", "1.017.２３４.567"])
def test_una_cedula_con_digitos_de_otra_escritura_sale_con_0_9(cola, rama, reloj, tmp_path, escrita):
    """La lista blanca solo admite 0-9: el número se escribe con ellos, sin cambiar (quitar los dígitos daría otra cédula)."""
    assert not vigencia.cedula_valida(escrita)
    assert vigencia.solo_digitos(escrita) == CC_A
    with pytest.raises(ValueError):
        vigencia.formulario(campos_ocultos(_html()), escrita)
    with pytest.raises(ValueError):
        vigencia.VigenciaExtension().consultar(escrita)
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    assert cola.encolar(caso, [escrita]) == 1
    _procesar(cola, reloj)
    assert _posts(rama) == [CC_A] and _consulta(caso, CC_A).estado == "vigente"


def test_cedulas_invalidas_y_consulta_apagada_no_ponen_nada_en_cola(reloj, tmp_path, rama, monkeypatch):
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)
    monkeypatch.delenv("TUTELA2_CONSULTA_VIGENCIA", raising=False)
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    cola = vigencia.ColaVigencia(reloj=reloj, dormir=_dormir(reloj), carpeta_cache=tmp_path / "cache")
    assert vigencia.modo_consulta(caso) == "apagada"
    assert cola.encolar(caso, [CC_A]) == 0
    assert cola.paso() is None and cola.fase(CC_A) is None
    monkeypatch.setenv("TUTELA2_CONSULTA_VIGENCIA", "extension")
    assert cola.encolar(caso, ["", "123", "12345678901", "abc"]) == 0
    assert cola.encolar(caso, [CC_A]) == 1
    assert rama.llamadas == []


def test_consulta_simulada_por_el_ultimo_digito_sin_red_ni_pausa(reloj, tmp_path, rama, modos):
    modos["uno"] = "fake"
    cola = _nueva_cola(reloj, tmp_path, modos)
    verde, rojo, mudo, sin_inscribir = "1017234567", "1017234560", "1017234569", "1017234568"
    caso = _caso(
        tmp_path,
        "uno",
        _ap(CC_A, AP_A),
        Apoderado(id=AP_B, nombre="Pedro Ficticio Mora", parte="X", cedula=rojo, tarjeta="1234"),
        Apoderado(id="ap-cccccccccc", nombre="Ana Ficticia Ruiz", parte="Y", cedula=mudo),
        Apoderado(id="ap-dddddddddd", nombre="Luis Ficticio Paz", parte="Z", cedula=sin_inscribir),
    )
    inicio = reloj()
    cola.encolar(caso, [verde, rojo, mudo, sin_inscribir])
    _procesar(cola, reloj, horizonte=1)
    assert reloj() == inicio and rama.llamadas == [] and not (tmp_path / "cache").exists()
    v, r, m = (_consulta(caso, c) for c in (verde, rojo, mudo))
    assert (v.estado, v.origen, v.datos.nombre, v.datos.tpa_numero) == ("vigente", "fake", "ANDREA PAOLA GIRALDO MONTOYA", "287415")
    assert (r.estado, r.datos.tpa_estado, r.datos.nombre) == ("no_vigente", "SUSPENDIDO", "PEDRO FICTICIO MORA")
    assert (m.estado, m.intentos_auto, m.proximo_intento) == ("inaccesible", 1, _iso(inicio + vigencia.ENFRIAMIENTO_S))
    n = _consulta(caso, sin_inscribir)
    assert (n.estado, n.datos.inscrito, n.datos.documento, n.datos.nombre) == ("no_inscrito", False, sin_inscribir, None)
    texto = "\n".join(p.extract_text() for p in PdfReader(registro_apoderados.ruta_certificado(caso, v.certificado)).pages)
    assert vigencia.AVISO_FICTICIO in texto
    assert cola.pausa_hasta() is None  # la consulta simulada no pausa la cola real


def test_la_consulta_simulada_no_tiene_tope_diario(reloj, tmp_path, rama, modos):
    """Con el proveedor de prueba cada caso sintético repite la consulta de la misma abogada ficticia (no hay
    caché): el tope de intentos del día protege a la Rama Judicial y la consulta simulada no llega a ella."""
    cola = _nueva_cola(reloj, tmp_path, modos)
    verde = "1017234567"
    for i in range(vigencia.MAX_AUTO_DIA + 2):
        nombre = f"caso-{i}"
        modos[nombre] = "fake"
        caso = _caso(tmp_path, nombre, _ap(CC_A, AP_A))
        assert cola.encolar(caso, [verde]) == 1, nombre
        _procesar(cola, reloj, horizonte=1)
        assert (_consulta(caso, verde).estado, _consulta(caso, verde).origen) == ("vigente", "fake"), nombre
    assert rama.llamadas == []


def test_el_cliente_falso_y_el_certificado_ficticio():
    fecha = datetime(2026, 11, 17, 15, 4, 5, tzinfo=timezone.utc)
    pdf = vigencia.certificado_ficticio("Andrea Paola, Giraldo Montoya", CC_A, None, vigente=True, fecha=fecha)
    cert = leer_certificado(pdf)
    assert (cert.nombre, cert.documento, cert.tpa_numero, cert.expedido) == (
        "ANDREA PAOLA GIRALDO MONTOYA", CC_A, "000000", "17/11/2026 03:04:05 PM"
    )
    assert clasificar(cert, CC_A, "Andrea Paola Giraldo Montoya") == "vigente"
    fake = vigencia.FakeVigencia(lambda: fecha.timestamp())
    assert fake.consultar("12345679").estado == "inaccesible"
    assert clasificar(leer_certificado(fake.consultar("12345670").pdf), "12345670") == "no_vigente"
    # El 8 da el certificado de una cédula no inscrita como abogado(a): sin nombre, aunque el caso espere uno.
    no_inscrito = leer_certificado(fake.consultar("12345678", vigencia.Titular("ANDREA PAOLA GIRALDO MONTOYA", "287415")).pdf)
    assert (no_inscrito.inscrito, no_inscrito.documento, no_inscrito.nombre) == (False, "12345678", None)
    assert clasificar(no_inscrito, "12345678", "Andrea Paola Giraldo Montoya") == "no_inscrito"
    texto = leer_certificado(vigencia.certificado_ficticio_no_inscrito("12345678", fecha=fecha))
    assert texto == no_inscrito
    with pytest.raises(ValueError):
        fake.consultar("1234")


class _Respuesta(io.BytesIO):
    def __init__(self, cuerpo: bytes, tipo: str, url: str = URL_VIGENCIA) -> None:
        super().__init__(cuerpo)
        self.status, self._url = 200, url
        self.headers = {"Content-Type": tipo}

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_consulta_directa_con_los_siete_campos_y_un_frasco_de_cookies_por_consulta(monkeypatch, reloj):
    pedidos: list[urllib.request.Request] = []
    frascos: list = []

    def abrir(req, timeout=None, galletas=None):
        pedidos.append(req)
        frascos.append(galletas)
        if req.get_method() == "GET":
            return _Respuesta((FIXTURES / "formulario.html").read_bytes(), "text/html")
        nombre, tarjeta = TITULARES[CC_A]
        return _Respuesta(vigencia.certificado_ficticio(nombre, CC_A, tarjeta, vigente=True, fecha=datetime.now(timezone.utc)), "application/pdf")

    monkeypatch.setattr(vigencia, "_abrir", abrir)
    turnos: list[bool] = []
    cliente = vigencia.VigenciaDirecta(lambda esperar=True: turnos.append(esperar), reloj)
    r = cliente.consultar(CC_A)
    assert r.estado == "ok" and leer_certificado(r.pdf).documento == CC_A
    # Solo el GET espera su turno; el POST sale enseguida, tras volver a comprobar que la cédula hace falta.
    assert turnos == [True, False]
    # El GET y el POST comparten un frasco nuevo; la consulta siguiente usa otro y ninguno queda en el cliente.
    assert frascos[0] is not None and frascos[0] is frascos[1] and cliente._galletas is None
    cliente.consultar(CC_A)
    assert frascos[2] is frascos[3] and frascos[2] is not frascos[0]
    get, post = pedidos[:2]
    assert (get.get_method(), get.full_url, get.data) == ("GET", URL_VIGENCIA, None)
    assert post.get_method() == "POST" and post.full_url == URL_VIGENCIA
    assert dict(urllib.parse.parse_qsl(post.data.decode())) == vigencia.formulario(campos_ocultos(_html()), CC_A)
    for req in pedidos:
        assert "cookie" not in {k.lower() for k, _ in req.header_items()}  # este abridor falso no pone cookies
    assert post.get_header("Content-type") == "application/x-www-form-urlencoded"


def test_consulta_directa_con_error_o_redireccion_ajena_queda_sin_respuesta(monkeypatch, reloj):
    def error(req, timeout=None, galletas=None):
        raise urllib.error.HTTPError(URL_VIGENCIA, 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(vigencia, "_abrir", error)
    r = vigencia.VigenciaDirecta(None, reloj).consultar(CC_A)
    assert r.estado == "inaccesible" and "HTTP 500" in r.detalle

    monkeypatch.setattr(vigencia, "_abrir", lambda req, timeout=None, galletas=None: _Respuesta(b"x", "text/html", "https://otro.example/x"))
    assert vigencia.VigenciaDirecta(None, reloj).consultar(CC_A).estado == "inaccesible"
    # El sin_red de este archivo: sin red, la consulta directa no se cae, queda sin respuesta.
    monkeypatch.setattr(vigencia, "_abrir", lambda req, timeout=None, galletas=None: (_ for _ in ()).throw(urllib.error.URLError("sin red")))
    assert vigencia.VigenciaDirecta(None, reloj).consultar(CC_A) == vigencia.Resultado("inaccesible", None, vigencia.SIN_RESPUESTA)


def test_consulta_directa_pasa_por_la_lista_blanca_antes_de_enviar(monkeypatch, reloj):
    """Como la extensión: un campo oculto fuera de lo permitido no sale; el GET del formulario sí salió."""
    html = _html()
    estado = campos_ocultos(html)["__VIEWSTATE"]
    pedidos: list[urllib.request.Request] = []

    def abrir(req, timeout=None, galletas=None):
        pedidos.append(req)
        return _Respuesta(html.replace(estado, "abc$def").encode("utf-8"), "text/html")

    monkeypatch.setattr(vigencia, "_abrir", abrir)
    r = vigencia.VigenciaDirecta(None, reloj).consultar(CC_A)
    assert r == vigencia.Resultado("inaccesible", None, vigencia.FORMULARIO_RECHAZADO)
    assert [p.get_method() for p in pedidos] == ["GET"]


def test_consulta_directa_no_sigue_ninguna_redireccion(monkeypatch, reloj):
    """El abridor real, sin red: un 302 queda como error y nunca se pide la dirección de ``Location``."""
    import email.message
    import urllib.response

    pedidos: list[str] = []

    def responder(self, req):
        pedidos.append(f"{req.get_method()} {req.full_url}")
        cabeceras = email.message.Message()
        cabeceras["Location"] = "https://otro.example/robado"
        respuesta = urllib.response.addinfourl(io.BytesIO(b""), cabeceras, req.full_url, 302)
        respuesta.msg = "Found"
        return respuesta

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", responder)
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", responder)
    monkeypatch.setattr(vigencia, "_abrir", _ABRIR_REAL)
    with pytest.raises(urllib.error.HTTPError) as e:
        vigencia._abrir(urllib.request.Request(URL_VIGENCIA, data=b"x=1", method="POST"), 5)
    assert e.value.code == 302 and pedidos == [f"POST {URL_VIGENCIA}"]
    pedidos.clear()
    r = vigencia.VigenciaDirecta(None, reloj).consultar(CC_A)
    assert (r.estado, pedidos) == ("inaccesible", [f"GET {URL_VIGENCIA}"]) and "HTTP 302" in r.detalle


def test_consulta_directa_devuelve_en_el_post_las_cookies_de_su_get_y_no_las_lleva_a_la_siguiente(monkeypatch, reloj):
    """El abridor real con un manejador HTTPS falso (sin red): las cookies de afinidad que pone el GET vuelven en
    su POST, y la consulta siguiente empieza sin ninguna."""
    import email.message
    import urllib.response

    vistos: list[tuple[str, str | None]] = []
    nombre, tarjeta = TITULARES[CC_A]
    pdf = vigencia.certificado_ficticio(nombre, CC_A, tarjeta, vigente=True, fecha=datetime.now(timezone.utc))
    servidor = iter(["1", "2"])

    def responder(self, req):
        vistos.append((req.get_method(), req.get_header("Cookie")))
        cabeceras = email.message.Message()
        if req.get_method() == "GET":
            instancia = next(servidor)
            cabeceras["Content-Type"] = "text/html; charset=utf-8"
            cabeceras["Set-Cookie"] = f"ApplicationGatewayAffinity=inst{instancia}; Path=/"
            cabeceras["Set-Cookie"] = f"ApplicationGatewayAffinityCORS=inst{instancia}; Path=/; SameSite=None; Secure"
            cuerpo = (FIXTURES / "formulario.html").read_bytes()
        else:
            cabeceras["Content-Type"] = "application/pdf"
            cuerpo = pdf
        respuesta = urllib.response.addinfourl(io.BytesIO(cuerpo), cabeceras, req.full_url, 200)
        respuesta.msg = "OK"
        return respuesta

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", responder)
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", responder)
    monkeypatch.setattr(vigencia, "_abrir", _ABRIR_REAL)
    cliente = vigencia.VigenciaDirecta(None, reloj)
    assert cliente.consultar(CC_A).estado == "ok"
    assert cliente.consultar(CC_A).estado == "ok"
    assert [m for m, _ in vistos] == ["GET", "POST", "GET", "POST"]
    assert vistos[0][1] is None and vistos[2][1] is None
    for (_, galletas), instancia in ((vistos[1], "1"), (vistos[3], "2")):
        assert galletas is not None
        assert sorted(galletas.split("; ")) == [
            f"ApplicationGatewayAffinity=inst{instancia}",
            f"ApplicationGatewayAffinityCORS=inst{instancia}",
        ]
    assert cliente._galletas is None


def test_una_caida_inesperada_saca_el_pedido_sin_registrar_la_cedula(cola, rama, reloj, tmp_path, caplog, monkeypatch):
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))

    def revienta(pdf):
        raise RuntimeError(f"dato roto {CC_A}")

    monkeypatch.setattr(vigencia, "leer_certificado", revienta)
    cola.encolar(caso, [CC_A])
    with caplog.at_level("DEBUG", logger="tutela2"):
        _procesar(cola, reloj)
    assert cola._pedidos == {} and _consulta(caso, CC_A) is None
    assert "RuntimeError" in caplog.text and CC_A not in caplog.text


def test_ninguna_cedula_en_los_registros_ni_en_las_rutas(cola, rama, reloj, tmp_path, caplog):
    uno = _caso(tmp_path, "uno", _ap(CC_A, AP_A), _ap(CC_B, AP_B))
    dos = _caso(tmp_path, "dos", _ap(CC_A, AP_A))
    rama.respuestas = [500]
    with caplog.at_level("DEBUG", logger="tutela2"):
        cola.encolar(uno, [CC_A, CC_B])
        cola.encolar(dos, [CC_A], forzar=True)
        _procesar(cola, reloj, horizonte=3 * 3600)
        rama.estado = "desactualizada"
        cola.encolar(dos, [CC_B])
        _procesar(cola, reloj, horizonte=600)
    assert _consulta(uno, CC_A).estado == _consulta(uno, CC_B).estado == "vigente"
    texto = caplog.text + "".join(str(r.args) for r in caplog.records)
    rutas = [str(p) for p in tmp_path.rglob("*")]
    for cc in (CC_A, CC_B, "52.345.671", "1.017.234.567"):
        assert cc not in texto
        assert not any(cc in r for r in rutas)
    assert "Vigencia" in caplog.text


def test_el_hilo_atiende_la_cola_y_despierta_al_conectarse_la_extension(rama, reloj, tmp_path, monkeypatch, modos):
    avisos: list = []
    monkeypatch.setattr(extension, "al_conectar", lambda fn: avisos.append(fn) or fn)
    caso = _caso(tmp_path, "uno", _ap(CC_A, AP_A))
    rama.estado = "no_conectada"
    cola = _nueva_cola(reloj, tmp_path, modos)
    cola.iniciar()
    cola.iniciar()
    try:
        assert avisos == [cola.despertar]
        cola.encolar(caso, [CC_A])
        time.sleep(0.2)
        assert _consulta(caso, CC_A) is None and rama.llamadas == []
        rama.estado = "conectada"
        avisos[0]()
        limite = time.monotonic() + 10
        while _consulta(caso, CC_A) is None and time.monotonic() < limite:
            time.sleep(0.02)
        assert _consulta(caso, CC_A).estado == "vigente"
    finally:
        cola.detener()
    assert not cola._hilo.is_alive()
