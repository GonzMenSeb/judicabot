from __future__ import annotations

import csv
import io
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tutela2 import citas
from tutela2.config import Config
from tutela2.models import CitaPropuesta, CitaVerificada

COLUMNAS = [
    "proceso", "expediente_tipo", "expediente_numero", "magistrado_a", "sala",
    "sentencia_tipo", "sentencia", "fecha_sentencia", "sv_spv", "av_apv",
]
FILAS = [
    ("T-200/22", "José Fernando Reyes Cuartas", "2022-06-06"),
    ("SU-082/95", "Jorge Arango Mejía", "1995-03-01"),
    ("T-892/11", "Nilson Pinilla Pinilla", "2011-11-30"),
    ("SU-712/13", "Jorge Iván Palacio Palacio", "2013-10-17"),
    ("T-157/14", "María Victoria Calle Correa", "2014-03-14"),
    ("C-252/94", "Antonio Barrera Carbonell; Vladimiro Naranjo Mesa", "1994-05-26"),
    ("T-212/21", "Sala Plena; José Fernando Reyes Cuartas", "2021-07-02"),
    ("C-681/03", "Ligia Galvis Ortiz (Conjuez)", "2003-08-06"),
    ("T-539A/93", "Carlos Gaviria Díaz", "1993-11-22"),
    ("T-1000/99", "Alfredo Beltrán Sierra", "1999-12-02"),
]
TEXTO_BASE = (
    "La subsidiariedad de la acción de tutela exige que el afectado agote los mecanismos ordinarios de defensa "
    "antes de acudir al juez constitucional, salvo que estos no resulten idóneos ni eficaces para evitar la "
    "consumación de un perjuicio irremediable sobre sus derechos fundamentales."
)
PARRAFO_HTML = (
    "<p class=MsoNormal>La subsidiariedad de la acci&oacute;n de tutela exige que el afectado agote los "
    "mecanismos\r\nordinarios de defensa antes de acudir al juez constitucional,"
    '<a href="#_ftn1" name="_ftnref1"><sup>[1]</sup></a> salvo que estos no resulten '
    "id<span>&oacute;</span>neos ni eficaces para evitar la consumación de un <i>perjuicio</i> "
    "irremediable sobre sus derechos fundamentales.</p>"
)
SOFT_404 = b"<html><body>" + b"x" * 8587 + b"</body></html>"


def _csv_bytes() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(COLUMNAS)
    for clave, mp, fecha in FILAS:
        w.writerow(["Tutela", "T", "1", mp, "Salas de Revisión", clave.split("-")[0], clave, fecha + "T00:00:00.000", "s.d.", "s.d."])
    return buf.getvalue().encode("utf-8")


def _pagina(ident: str, cuerpo: str = PARRAFO_HTML, encoding: str = "cp1252", cierre: bool = True) -> bytes:
    relleno = "".join(f"<p>Fundamento {i} alfa{i} beta{i} gamma{i} delta{i} epsilon{i}</p>\r\n" for i in range(500))
    if cierre:
        relleno += "<p>Cópiese, notifíquese, comuníquese y cúmplase.</p><p>Magistrado</p><p>Secretaria General</p>"
    html = (
        "<script language='JavaScript1.2' src='/relatoria/encabezado.js'> </script> "
        f"<a href='/sentencias/x/{ident}.rtf'> {ident} </a>\r\n<html><head>"
        f"<meta http-equiv=Content-Type content=\"text/html; charset={encoding}\">"
        "<title>REPUBLICA DE COLOMBIA</title><style><!-- p.MsoNormal {margin:0cm} --></style></head><body>"
        f"<p>SENTENCIA {ident}</p>{cuerpo}{relleno}</body></html>"
    )
    return html.encode(encoding)


class _Resp:
    def __init__(self, datos: bytes):
        self.datos = datos

    def read(self) -> bytes:
        return self.datos

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(cache_dir=str(tmp_path / "cache"))
    (c.cache_path() / "cc_sentencias.csv").write_bytes(_csv_bytes())
    return c


def _poner_pagina(cfg: Config, nombre: str, datos: bytes) -> None:
    d = cfg.cache_path() / "relatoria"
    d.mkdir(exist_ok=True)
    (d / nombre).write_bytes(datos)


def _red(monkeypatch, datos: bytes | None = None, error: Exception | None = None) -> list[str]:
    llamadas: list[str] = []

    def fake(req, timeout=None):
        llamadas.append(req.full_url)
        if error:
            raise error
        return _Resp(datos)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return llamadas


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("T-048/10", ("T", 48, 2010)),
        ("T-048 de 2010", ("T", 48, 2010)),
        ("SU-082/95", ("SU", 82, 1995)),
        ("SU082-95", ("SU", 82, 1995)),
        ("SU.082/95", ("SU", 82, 1995)),
        ("C 321 de 2022", ("C", 321, 2022)),
        ("c-321/22", ("C", 321, 2022)),
        ("Sentencia T-200 de 2022, M.P. José Fernando Reyes Cuartas", ("T", 200, 2022)),
        ("T-1000/99", ("T", 1000, 1999)),
        ("T-200/2022", ("T", 200, 2022)),
        ("T-001/92", ("T", 1, 1992)),
        ("T-539A/93", None),
        ("T-200", None),
        ("basura", None),
        ("", None),
    ],
)
def test_normalizar_sentencia(texto, esperado):
    assert citas.normalizar_sentencia(texto) == esperado


@pytest.mark.parametrize(
    "args,esperado",
    [
        (("T", 48, 2010), "T-048/10"),
        (("SU", 82, 1995), "SU-082/95"),
        (("C", 321, 2022), "C-321/22"),
        (("T", 1000, 1999), "T-1000/99"),
        (("T", 5, 2003), "T-005/03"),
    ],
)
def test_clave_dataset(args, esperado):
    assert citas.clave_dataset(*args) == esperado


@pytest.mark.parametrize(
    "args,esperado",
    [
        (("T", 892, 2011), "https://www.corteconstitucional.gov.co/relatoria/2011/T-892-11.htm"),
        (("C", 321, 2022), "https://www.corteconstitucional.gov.co/relatoria/2022/C-321-22.htm"),
        (("SU", 82, 1995), "https://www.corteconstitucional.gov.co/relatoria/1995/SU082-95.htm"),
        (("T", 48, 2010), "https://www.corteconstitucional.gov.co/relatoria/2010/T-048-10.htm"),
    ],
)
def test_url_relatoria(args, esperado):
    assert citas.url_relatoria(*args) == esperado


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Acción de TUTELA", "accion de tutela"),
        ("Año  y\ncompañía", "año y compañia"),
        ("La Corte (sentencia T-1/92) dijo [sic] que… sí", "la corte dijo que si"),
        ("nivel (uno (dos) tres) final", "nivel final"),
        ("pro­cede​ ya", "procede ya"),
        ("«Artículo 86»: 'x' - y", "articulo 86 x y"),
        ("ÑANDÚ", "ñandu"),
    ],
)
def test_normalizar_texto(texto, esperado):
    assert citas.normalizar_texto(texto) == esperado


@pytest.mark.parametrize("texto", ["Año (1) [x] ÑANDÚ… nº 5 – «cita»", TEXTO_BASE, "  "])
def test_normalizar_texto_es_idempotente(texto):
    una = citas.normalizar_texto(texto)
    assert citas.normalizar_texto(una) == una


def test_html_a_texto_ancla_de_nota_sin_cerrar_no_se_traga_el_resto():
    texto = citas._html_a_texto("<p>uno <a href='#_ftn1'>[1]<p>dos</p><p>tres</p>")
    assert texto.split("\n") == ["uno", "dos", "tres"]


def test_cobertura_exacta_parcial_y_nula():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert citas.cobertura(TEXTO_BASE, fuente) == 1.0
    assert citas.cobertura("¡" + TEXTO_BASE.upper() + "!", fuente) == 1.0
    assert citas.cobertura("nada que ver con la fuente original de este texto", fuente) == 0.0
    mitad = " ".join(TEXTO_BASE.split()[:20]) + " relleno inventado " * 10
    assert 0.2 < citas.cobertura(mitad, fuente) < 0.6


def test_cobertura_cita_corta_y_vacia():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert citas.cobertura("la acción de tutela", fuente) == 1.0
    assert citas.cobertura("la acción de amparo", fuente) == 0.0
    assert citas.cobertura("", fuente) is None
    assert citas.cobertura("(...) [sic]", fuente) is None


def test_cobertura_ignora_notas_entre_parentesis():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    con_nota = TEXTO_BASE.replace("tutela", "tutela (Sentencia T-1 de 1992)").replace("juez", "juez [12]")
    assert citas.cobertura(con_nota, fuente) == 1.0


def test_cobertura_con_parentesis_sin_cerrar_en_la_fuente():
    fuente = "la orden (uno o más músculos " + TEXTO_BASE + " son competentes: a) los jueces"
    assert citas.cobertura(TEXTO_BASE, fuente) == 1.0
    assert citas.cobertura("nada que ver con la fuente original de este texto", fuente) == 0.0


FUENTE_NOTAS = (
    TEXTO_BASE.replace("tutela", "tutela (Sentencia T-1 de 1992)", 1)
    .replace("ordinarios", "ordinarios (art. 6 del Decreto 2591)")
    .replace("juez", "juez (cfr. fundamento 4)")
)
RELLENO_LARGO = "palabras de relleno sin relevancia alguna para la cita " * 8


def test_cobertura_parentesis_sin_cerrar_lejos_de_inciso_no_borra_la_fuente():
    fuente = "la orden (uno o mas musculos " + RELLENO_LARGO + FUENTE_NOTAS + " son competentes: a) los jueces"
    assert citas.cobertura(TEXTO_BASE, fuente) >= 0.8


def test_cobertura_acepta_marcas_agregadas_por_el_citante():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert citas.cobertura(TEXTO_BASE.replace("tutela", "tutela [sic]"), fuente) == 1.0
    assert citas.cobertura(TEXTO_BASE + " (subrayado fuera de texto)", fuente) == 1.0


def test_cobertura_parentesis_inventado_no_se_acepta():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    inventada = TEXTO_BASE.replace(
        "que el afectado",
        "que el afectado (procede siempre contra providencias judiciales sin requisito alguno de ninguna clase "
        "y sin importar la existencia de otros mecanismos de defensa judicial ordinarios disponibles)",
    )
    assert citas.cobertura(inventada, fuente) < 0.8
    corta = "La subsidiariedad (procede siempre contra providencias judiciales sin requisito alguno de ninguna clase)"
    assert citas.cobertura(corta, fuente) < 0.8


def test_cobertura_parentesis_inventado_menor_al_30_por_ciento_no_se_acepta():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    inventada = TEXTO_BASE.replace(
        "que el afectado", "que el afectado (salvo que sea una persona de especial protección)"
    )
    assert citas.cobertura(inventada, fuente) < 0.8


@pytest.mark.parametrize(
    "cita",
    [
        "La subsidiariedad de la acción de tutela (subrayado fuera de texto)",
        "agote los mecanismos ordinarios de defensa (negrillas y subrayas fuera del texto original)",
        "La subsidiariedad de la acción de tutela exige que el afectado agote los mecanismos ordinarios "
        "(Negrillas y subrayas fuera del texto original)",
        "La subsidiariedad de la acción de tutela (...) exige que el afectado [...] agote los mecanismos ordinarios",
        "La subsidiariedad (…) de la acción de tutela exige que el afectado […] agote los mecanismos ordinarios",
        "La subsidiariedad de la acción (sic) de tutela exige que el afectado agote los mecanismos ordinarios",
        "La subsidiariedad de la acción de tutela [12] exige que el afectado agote los mecanismos ordinarios",
        "La subsidiariedad de la acción de tutela (T-123/20) exige que el afectado agote los mecanismos ordinarios",
        "La subsidiariedad de la acción de tutela (SU-082 de 1995) exige que el afectado agote los mecanismos",
        "La subsidiariedad de la acción de tutela (C-543/92) exige que el afectado agote los mecanismos",
    ],
)
def test_cobertura_acepta_cada_marca_del_citante(cita):
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert citas.cobertura(cita, fuente) >= 0.8


def test_cobertura_cita_sin_parentesis_de_la_fuente_mas_nota_del_citante():
    fuente = TEXTO_BASE.replace("ordinarios", "ordinarios (art. 6 del Decreto 2591)")
    cita = "agote los mecanismos ordinarios de defensa antes de acudir (subrayado fuera de texto)"
    assert citas.cobertura(cita, fuente) >= 0.8


PASAJE_LARGO = (
    "Esta Corporación ha sostenido de manera reiterada que el derecho fundamental a la salud comprende el acceso "
    "oportuno, eficaz y de calidad a los servicios que se requieran para preservar la integridad de la persona, "
    "de modo que las entidades promotoras no pueden anteponer barreras administrativas, financieras o de cualquier "
    "otra índole que impidan la prestación efectiva del servicio, pues ello desconoce los principios de "
    "continuidad, integralidad y oportunidad que gobiernan el sistema y vulnera los mandatos de la Constitución "
    "Política y de la ley estatutaria que regula la materia en el ordenamiento jurídico colombiano vigente."
)


def _insertar(texto: str, nota: str, pos: int) -> str:
    palabras = texto.split()
    return " ".join(palabras[:pos] + [nota] + palabras[pos:])


def test_cobertura_cita_literal_con_sic_y_otro_parentesis_de_la_fuente():
    fuente = (
        "Esta Corporación ha sostenido que la acción de tutela (sic) procede cuando el afectado carece de "
        "otro medio de defensa judicial (art. 86 C.P.) idóneo para proteger sus derechos."
    )
    assert 25 <= len(fuente.split()) <= 32
    assert citas.cobertura(fuente, fuente) == 1.0


def test_cobertura_conserva_un_parentesis_y_omite_el_otro_de_la_fuente():
    antes = "El accionante solicitó a la EPS la entrega del medicamento"
    medio = "formulado por el médico tratante y la entidad negó"
    despues = "la solicitud por falta de requisitos y archivó."
    fuente = f"{antes} (Nueva EPS S.A.) {medio} (radicado interno 4455) {despues}"
    assert 15 <= len(fuente.split()) <= 35
    assert citas.cobertura(f"{antes} (Nueva EPS S.A.) {medio} {despues}", fuente) >= 0.8
    assert citas.cobertura(f"{antes} {medio} (radicado interno 4455) {despues}", fuente) >= 0.8
    assert citas.cobertura(f"{antes} {medio} {despues}", fuente) >= 0.8


@pytest.mark.parametrize("nota", ["(no)", "(nunca)", "(salvo excepciones)"])
def test_cobertura_parentesis_inventado_de_una_palabra_en_cita_larga(nota):
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert len(TEXTO_BASE.split()) == 43
    assert citas.cobertura(_insertar(TEXTO_BASE, nota, 21), fuente) == 0.0
    assert citas.cobertura(TEXTO_BASE + " " + nota, fuente) == 0.0


def test_cobertura_parentesis_inventado_de_ocho_palabras_en_pasaje_literal_largo():
    inventada = _insertar(PASAJE_LARGO, "(salvo que sea una persona de especial protección constitucional)", 50)
    assert len(PASAJE_LARGO.split()) > 90
    assert citas.cobertura(inventada, PASAJE_LARGO) == 0.0
    assert citas.cobertura(PASAJE_LARGO, PASAJE_LARGO) == 1.0


def test_cobertura_parentesis_inventado_con_marca_valida_al_lado():
    inventada = _insertar(TEXTO_BASE, "(nunca) (sic)", 21)
    assert citas.cobertura(inventada, TEXTO_BASE) == 0.0


NOTAS_CITANTE = [
    "(subrayado fuera de texto)", "(Subrayado fuera del texto original)", "(negrilla fuera de texto)",
    "(negrillas fuera de texto)", "(negrita fuera de texto)", "(resaltado fuera del texto)",
    "(destacado fuera de texto)", "(destacados fuera de texto original)", "(énfasis añadido)",
    "(Énfasis agregado)", "(subrayas propias)", "(negrillas añadidas)", "(resaltado del Despacho)",
    "(Subraya el Despacho)", "(Destaca la Sala)", "(subrayado de la Sala)", "(negrillas del texto original)",
    "(subrayado en el original)", "(subrayado y negrilla fuera de texto)", "(cursiva fuera de texto)",
    "(Se destaca)", "(Se resalta)", "(citas internas omitidas)", "(…)", "(...)", "(. . .)", "[…]", "[...]",
    "[sic]", "(sic)", "[12]", "[3]",
    "(Sentencia T-123 de 2020)", "(T-123/20)", "(SU-082 de 1995)", "(C-543/92)",
    "(Sentencia T-123 de 2020, M.P. Jorge Iván Palacio)", "(T-760/08, M.P. Manuel José Cepeda Espinosa)",
    "(Cfr. Sentencia T-123 de 2020)", "(Ver sentencia SU-082 de 1995)", "(cfr. T-123/20, M.P. María Victoria Calle)",
    "(Sentencias T-760 de 2008 y T-121 de 2015)", "(Cfr. Sentencias T-760 de 2008 y T-121 de 2015)",
    "(Sentencia T-760 de 2008. M.P. Manuel José Cepeda Espinosa)",
    "(Sentencia T-760 de 2008; M.P. Manuel José Cepeda Espinosa)",
    "(Sentencia C-543 de 1992 M.P. José Gregorio Hernández Galindo)",
    "(Sentencia T-760 de 2008, Magistrado Ponente: Manuel José Cepeda Espinosa)",
    "(Sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa y Rodrigo Escobar Gil)",
    "(Sentencia T-760 de 2008, M.P. Dr. Manuel José Cepeda Espinosa)",
    "(Corte Constitucional, Sentencia T-760 de 2008)",
    "(Corte Constitucional, Sentencia T-760 de 2008, M.P. Manuel José Cepeda Espinosa)",
    "(negrilla por fuera del texto)", "(Subrayado del Juzgado)", "(Resaltado por el Despacho)",
    "(subrayado nuestro)", "(Negrillas del suscrito)", "(Negrilla intencional)", "(Destacado del Juzgado)",
    "(Subrayado y negrillas por fuera del texto original)",
]


@pytest.mark.parametrize("nota", NOTAS_CITANTE)
def test_cobertura_acepta_cada_nota_del_citante_corta_y_a_media_cita(nota):
    fuente = citas.normalizar_texto(TEXTO_BASE)
    corta = "agote los mecanismos ordinarios de defensa"
    assert citas.cobertura(f"{corta} {nota}", fuente) == 1.0
    assert citas.cobertura(f"{nota} {corta}", fuente) == 1.0
    assert citas.cobertura(_insertar(TEXTO_BASE, nota, 21), fuente) == 1.0
    assert citas.cobertura(_insertar(TEXTO_BASE, nota, 9), TEXTO_BASE) == 1.0


@pytest.mark.parametrize(
    "nota",
    [
        "(Sentencia T-760 de 2008, M.P. Manuel Cepeda salvo que sea persona protegida)",
        "(Sentencia T-760 de 2008. M.P. Manuel Cepeda, reiterada en la T-121 de 2015)",
        "(Subrayado nunca del Juzgado)",
        "(Negrilla por fuera del texto salvo excepciones)",
    ],
)
def test_cobertura_nota_con_texto_libre_tras_la_marca_no_se_acepta(nota):
    assert citas.cobertura(_insertar(TEXTO_BASE, nota, 21), TEXTO_BASE) == 0.0


def test_cobertura_nota_del_citante_en_la_fuente_no_rompe_costuras():
    fuente = _insertar(TEXTO_BASE, "(subrayado fuera de texto)", 21).replace("tutela", "tutela [12]")
    assert citas.cobertura(TEXTO_BASE, fuente) == 1.0


CONTRARIO = " Por el contrario, cuando el afectado no cuenta con otro medio, la acción de tutela no es procedente."


@pytest.mark.parametrize(
    "cita",
    [
        "La subsidiariedad de la acción de tutela (no) exige que el afectado agote los mecanismos ordinarios",
        "La subsidiariedad de la acción de tutela exige que el afectado (no) agote los mecanismos ordinarios",
        "La subsidiariedad de la acción de tutela exige (no) que el afectado agote los mecanismos ordinarios",
    ],
)
def test_cobertura_parentesis_no_anclado_en_fuente_larga_se_rechaza(cita):
    assert citas.cobertura(cita, TEXTO_BASE + CONTRARIO) == 0.0
    assert citas.cobertura(cita, TEXTO_BASE) == 0.0


def test_cobertura_parentesis_inventado_cuyas_palabras_estan_en_otro_lugar_de_la_fuente():
    inventada = "(salvo que sea una persona de especial protección constitucional)"
    palabras = PASAJE_LARGO.split()
    cita = _insertar(PASAJE_LARGO, inventada, 50)
    fuente = PASAJE_LARGO + " " + " ".join(palabras[48:50]) + " " + inventada[1:-1] + " " + " ".join(palabras[50:52])
    assert len(palabras) > 90
    assert citas.cobertura(cita, fuente) == 0.0
    assert citas.cobertura(PASAJE_LARGO, fuente) == 1.0


def test_cobertura_parentesis_de_la_fuente_se_acepta_en_su_sitio_y_con_otro_omitido():
    fuente = "uno dos tres cuatro cinco (alfa beta) seis siete (gamma) ocho nueve diez once doce trece catorce"
    assert citas.cobertura("uno dos tres cuatro cinco (alfa beta) seis siete ocho nueve diez", fuente) == 1.0
    assert citas.cobertura("cuatro cinco seis siete (gamma) ocho nueve diez once", fuente) == 1.0
    assert citas.cobertura("uno dos tres cuatro cinco (alfa beta)", fuente) == 1.0
    assert citas.cobertura("(alfa beta) seis siete (gamma) ocho nueve diez once", fuente) == 1.0
    assert citas.cobertura("uno dos tres cuatro cinco (alfa beta) seis siete ocho (gamma) nueve diez", fuente) == 0.0


def test_cobertura_solo_el_parentesis_sin_contexto_se_rechaza():
    assert citas.cobertura("(alfa beta)", "uno dos (alfa beta) tres cuatro") == 0.0


def test_cobertura_ventana_que_corta_una_nota_de_la_fuente():
    fuente = TEXTO_BASE.replace("tutela", "tutela (T-760 de 2008)", 1)
    inicio = "2008) exige que el afectado agote los mecanismos ordinarios de defensa antes de acudir"
    assert citas.cobertura(inicio, fuente) == 1.0
    final = "La subsidiariedad de la acción de tutela (T-760 de"
    assert citas.cobertura(final, fuente) == 1.0


def test_motivo_parentesis_nombra_el_parentesis_no_hallado():
    fuente = TEXTO_BASE + CONTRARIO
    cita = "La subsidiariedad de la acción de tutela (no) exige que el afectado agote los mecanismos"
    assert citas.motivo_parentesis(cita, fuente) == "El paréntesis «(no)» no aparece en ese punto de la fuente."
    assert citas.motivo_parentesis(TEXTO_BASE, fuente) is None
    assert citas.motivo_parentesis("La subsidiariedad de la acción de tutela (sic) exige", fuente) is None


def test_verificar_motivo_especifico_del_parentesis_inventado(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", f"<p>{TEXTO_BASE}{CONTRARIO}</p>"))
    cita = "La subsidiariedad de la acción de tutela exige que el afectado (no) agote los mecanismos ordinarios"
    bien, mal = _verificar(cfg, _p("T-200/22", TEXTO_BASE), _p("T-200/22", cita, "c2"))
    assert bien.estado == "ok"
    assert mal.estado == "rechazada" and mal.cobertura == 0.0
    assert "no se localizó" in mal.motivos[0]
    assert "El paréntesis «(no)» no aparece en ese punto de la fuente." in mal.motivos


def test_cobertura_nota_pegada_a_texto_inventado_no_se_acepta():
    fuente = citas.normalizar_texto(TEXTO_BASE)
    assert citas.cobertura(_insertar(TEXTO_BASE, "(T-123/20, M.P. salvo que sea persona protegida)", 21), fuente) == 0.0
    assert citas.cobertura(_insertar(TEXTO_BASE, "(subrayado nunca fuera de texto)", 21), fuente) == 0.0


@pytest.mark.parametrize(
    "cita",
    [
        "[l]a subsidiariedad de la acción de tutela exige que el afectado agote",
        "[L]a subsidiariedad de la acción de tutela exige que el afectado agote",
        "exige que [e]l afectado agote los mecanismos ordinarios de defensa",
        "La subsidiariedad de la acción de tutela exige que [e]l afectado agote [l]os mecanismos ordinarios",
    ],
)
def test_cobertura_edicion_de_una_letra_entre_corchetes(cita):
    assert citas.cobertura(cita, TEXTO_BASE) == 1.0
    assert citas.cobertura(cita, TEXTO_BASE.replace("La", "[L]a", 1).replace("el afectado", "[e]l afectado")) == 1.0


def test_cobertura_corchete_con_palabras_inventadas_no_se_acepta():
    assert citas.cobertura("La subsidiariedad [de la tutela] exige que el afectado agote los mecanismos", TEXTO_BASE) == 0.0


def test_cobertura_solo_marcas_o_solo_parentesis_ajeno():
    assert citas.cobertura("(Sentencia T-1 de 1992) [12] [sic] (...)", TEXTO_BASE) is None
    assert citas.cobertura("(procede siempre)", TEXTO_BASE) == 0.0


def test_sentencias_en_texto():
    texto = (
        "Véase la Sentencia T-200 de 2022, M.P. José Fernando Reyes Cuartas, y la SU-082/95; también la "
        "sentencia SU082-95, la C 321 de 2022, la T-539A/93 y la T-1000/99. Cite T-777 sin año y el "
        "oficio ACTA-12/20 de la ciudad."
    )
    assert citas.sentencias_en_texto(texto) == {
        "T-200/22", "SU-082/95", "C-321/22", "T-539A/93", "T-1000/99",
    }
    assert citas.sentencias_en_texto("sin menciones") == set()


def _cv(**kw) -> CitaVerificada:
    base = dict(id="c1", sentencia_original="T-200 de 2022", texto_citado="x", tipo="T", numero=200, anio=2022)
    return CitaVerificada(**{**base, **kw})


@pytest.mark.parametrize(
    "kw,esperado",
    [
        (
            dict(mp_dataset="José Fernando Reyes Cuartas"),
            "Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas",
        ),
        (
            dict(mp_dataset="María Victoria Calle Correa"),
            "Sentencia T-200 de 2022, con ponencia de la Magistrada María Victoria Calle Correa",
        ),
        (dict(mp_dataset="Gloria Stella Ortiz Delgado"), "Sentencia T-200 de 2022, con ponencia de la Magistrada Gloria Stella Ortiz Delgado"),
        (dict(mp_dataset=None), "Sentencia T-200 de 2022"),
        (dict(mp_dataset=""), "Sentencia T-200 de 2022"),
        (
            dict(mp_dataset="Sala Plena; José Fernando Reyes Cuartas"),
            "Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas",
        ),
        (
            dict(mp_dataset="Antonio Barrera Carbonell; Vladimiro Naranjo Mesa"),
            "Sentencia T-200 de 2022, con ponencia de los Magistrados Antonio Barrera Carbonell y Vladimiro Naranjo Mesa",
        ),
        (
            dict(mp_dataset="Cristina Pardo Schlesinger; Diana Constanza Fajardo Rivera"),
            "Sentencia T-200 de 2022, con ponencia de las Magistradas Cristina Pardo Schlesinger y Diana Constanza Fajardo Rivera",
        ),
        (dict(mp_dataset="Conjuez"), "Sentencia T-200 de 2022"),
        (dict(tipo="SU", numero=82, anio=1995, mp_dataset="Jorge Arango Mejía"), "Sentencia SU-082 de 1995, con ponencia del Magistrado Jorge Arango Mejía"),
        (dict(tipo=None, numero=None, anio=None, sentencia_original="algo raro"), "Sentencia algo raro"),
    ],
)
def test_formatear_referencia(kw, esperado):
    assert citas.formatear_referencia(_cv(**kw)) == esperado


def test_cargar_dataset_usa_cache_vigente_sin_red(cfg):
    ds = citas.cargar_dataset(cfg)
    assert set(ds) == {c for c, _, _ in FILAS}
    assert ds["T-892/11"]["magistrado_a"] == "Nilson Pinilla Pinilla"
    assert ds["T-892/11"]["fecha_sentencia"].startswith("2011-11-30")


def test_cargar_dataset_cache_vieja_sin_red_la_usa(cfg):
    ruta = cfg.cache_path() / "cc_sentencias.csv"
    viejo = time.time() - 40 * 24 * 3600
    os.utime(ruta, (viejo, viejo))
    assert "T-200/22" in citas.cargar_dataset(cfg)


def test_cargar_dataset_cache_vieja_con_red_la_renueva(cfg, monkeypatch):
    ruta = cfg.cache_path() / "cc_sentencias.csv"
    viejo = time.time() - 40 * 24 * 3600
    os.utime(ruta, (viejo, viejo))
    nuevo = _csv_bytes().replace(b"T-200/22", b"T-201/22")
    llamadas = _red(monkeypatch, nuevo)
    ds = citas.cargar_dataset(cfg)
    assert llamadas == [cfg.dataset_csv_url]
    assert "T-201/22" in ds and "T-200/22" not in ds
    assert ruta.read_bytes() == nuevo


def test_cargar_dataset_sin_cache_ni_red_falla_claro(cfg):
    (cfg.cache_path() / "cc_sentencias.csv").unlink()
    with pytest.raises(citas.ErrorDataset, match="No se pudo descargar"):
        citas.cargar_dataset(cfg)


def test_cargar_dataset_descarga_invalida_no_pisa_la_cache(cfg, monkeypatch):
    ruta = cfg.cache_path() / "cc_sentencias.csv"
    viejo = time.time() - 40 * 24 * 3600
    os.utime(ruta, (viejo, viejo))
    antes = ruta.read_bytes()
    _red(monkeypatch, b"<html>Servicio no disponible</html>")
    assert "T-200/22" in citas.cargar_dataset(cfg)
    assert ruta.read_bytes() == antes


def test_cargar_dataset_exige_las_columnas_usadas(cfg, monkeypatch):
    ruta = cfg.cache_path() / "cc_sentencias.csv"
    ruta.unlink()
    sin_mp = _csv_bytes().replace(b'"magistrado_a"', b'"ponente"')
    _red(monkeypatch, sin_mp)
    with pytest.raises(citas.ErrorDataset, match="magistrado_a"):
        citas.cargar_dataset(cfg)
    assert not ruta.exists()


def test_texto_relatoria_desde_cache_cp1252(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    texto = citas.texto_relatoria(citas.url_relatoria("T", 200, 2022), cfg)
    assert texto is not None
    assert "<" not in texto and "&oacute;" not in texto and "REPUBLICA" not in texto and "p.MsoNormal" not in texto
    assert "SENTENCIA T-200-22" in texto
    assert "idóneos" in texto and "consumación" in texto and "acción de tutela" in texto
    assert "mecanismos ordinarios" in texto
    assert "[1]" not in texto


def test_texto_relatoria_utf8(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", encoding="utf-8"))
    texto = citas.texto_relatoria(citas.url_relatoria("T", 200, 2022), cfg)
    assert texto and "idóneos" in texto


def test_texto_relatoria_soft_404_en_cache(cfg):
    _poner_pagina(cfg, "T-999-22.htm", SOFT_404)
    assert citas.texto_relatoria(citas.url_relatoria("T", 999, 2022), cfg) is None


def test_texto_relatoria_sin_red_ni_cache(cfg):
    assert citas.texto_relatoria(citas.url_relatoria("T", 200, 2022), cfg) is None


def test_texto_relatoria_descarga_y_guarda(cfg, monkeypatch):
    llamadas = _red(monkeypatch, _pagina("T-200-22"))
    url = citas.url_relatoria("T", 200, 2022)
    assert citas.texto_relatoria(url, cfg)
    assert llamadas == [url]
    assert [f.name for f in (cfg.cache_path() / "relatoria").iterdir()] == ["T-200-22.htm"]
    assert citas.texto_relatoria(url, cfg)
    assert len(llamadas) == 1


def test_texto_relatoria_descarga_de_otra_sentencia_se_devuelve_pero_no_se_guarda(cfg, monkeypatch):
    _red(monkeypatch, _pagina("T-892-11"))
    url = citas.url_relatoria("T", 200, 2022)
    assert citas.texto_relatoria(url, cfg)
    assert list((cfg.cache_path() / "relatoria").glob("*")) == []


def test_texto_relatoria_descarga_soft_404_no_se_guarda(cfg, monkeypatch):
    _red(monkeypatch, SOFT_404)
    assert citas.texto_relatoria(citas.url_relatoria("T", 999, 2022), cfg) is None
    assert not (cfg.cache_path() / "relatoria" / "T-999-22.htm").exists()


def test_texto_relatoria_error_http_devuelve_none(cfg, monkeypatch):
    _red(monkeypatch, error=urllib.error.HTTPError("u", 404, "no", {}, None))
    assert citas.texto_relatoria(citas.url_relatoria("T", 200, 2022), cfg) is None


def _verificar(cfg: Config, *propuestas: CitaPropuesta) -> list[CitaVerificada]:
    return citas.verificar_citas(list(propuestas), cfg, citas.cargar_dataset(cfg))


def _p(sentencia: str, texto: str = TEXTO_BASE, id_: str = "c1") -> CitaPropuesta:
    return CitaPropuesta(id=id_, sentencia=sentencia, texto_citado=texto, reparo_ids=["R1"])


def test_verificar_ok(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200 de 2022"))
    assert cv.estado == "ok" and cv.cobertura == 1.0 and cv.pagina_ok and cv.en_dataset
    assert cv.sentencia_norm == "T-200/22" and (cv.tipo, cv.numero, cv.anio) == ("T", 200, 2022)
    assert cv.mp_dataset == "José Fernando Reyes Cuartas" and cv.fecha_dataset == "2022-06-06"
    assert cv.url.endswith("/relatoria/2022/T-200-22.htm")
    assert cv.reparo_ids == ["R1"] and cv.motivos == []


def test_verificar_alerta_y_rechazada_por_cobertura(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    palabras = TEXTO_BASE.split()
    parcial = " ".join(palabras[:26]) + " " + " ".join(f"inventada{i}" for i in range(10))
    inventada = " ".join(f"fantasia{i}" for i in range(40))
    alerta, rechazada = _verificar(cfg, _p("T-200/22", parcial), _p("T-200/22", inventada, "c2"))
    assert alerta.estado == "alerta" and 0.5 <= alerta.cobertura < 0.8
    assert "%" in alerta.motivos[0]
    assert rechazada.estado == "rechazada" and rechazada.cobertura == 0.0 and rechazada.pagina_ok
    assert "no se localizó" in rechazada.motivos[0]


def test_verificar_umbrales_configurables(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    parcial = " ".join(TEXTO_BASE.split()[:26]) + " " + " ".join(f"inventada{i}" for i in range(10))
    cfg.cobertura_alerta = 0.9
    assert _verificar(cfg, _p("T-200/22", parcial))[0].estado == "rechazada"
    cfg.cobertura_ok = 0.4
    assert _verificar(cfg, _p("T-200/22", parcial))[0].estado == "ok"


def test_verificar_no_existe_en_dataset(cfg):
    (cv,) = _verificar(cfg, _p("T-999 de 2022"))
    assert cv.estado == "rechazada" and not cv.en_dataset and cv.sentencia_norm == "T-999/22"
    assert "no figura en el dataset" in cv.motivos[0]


def test_verificar_identificador_ilegible(cfg):
    (cv,) = _verificar(cfg, _p("la sentencia sobre subsidiariedad"))
    assert cv.estado == "rechazada" and cv.sentencia_norm is None and "interpretar" in cv.motivos[0]


def test_verificar_sufijo_de_letra_no_se_confunde_con_otra_sentencia(cfg):
    (cv,) = _verificar(cfg, _p("T-539A/93"))
    assert cv.estado == "rechazada" and cv.sentencia_norm is None


def test_verificar_pagina_no_encontrada(cfg):
    (cv,) = _verificar(cfg, _p("SU-082/95"))
    assert cv.estado == "rechazada" and cv.en_dataset and not cv.pagina_ok and cv.cobertura is None
    assert "No se encontró la página" in cv.motivos[0]


def test_verificar_soft_404_en_cache(cfg):
    _poner_pagina(cfg, "SU082-95.htm", SOFT_404)
    (cv,) = _verificar(cfg, _p("SU-082/95"))
    assert cv.estado == "rechazada" and not cv.pagina_ok


def test_verificar_pagina_de_otra_sentencia(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-892-11"))
    (cv,) = _verificar(cfg, _p("T-200/22"))
    assert cv.estado == "rechazada" and not cv.pagina_ok and cv.cobertura is None
    assert "no corresponde" in cv.motivos[0]


def test_verificar_pagina_sin_identificador(cfg):
    sin_id = _pagina("X", cuerpo=PARRAFO_HTML).replace(b"SENTENCIA X", b"DOCUMENTO").replace(b"> X <", b"> otra <")
    _poner_pagina(cfg, "T-200-22.htm", sin_id)
    (cv,) = _verificar(cfg, _p("T-200/22"))
    assert cv.estado == "rechazada" and not cv.pagina_ok


def test_verificar_mp_declarado(cfg):
    _poner_pagina(cfg, "T-892-11.htm", _pagina("T-892-11"))
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    mal, bien = _verificar(
        cfg,
        _p("T-892 de 2011, M.P. Luis Ernesto Vargas Silva"),
        _p("Sentencia T-200 de 2022 (M.P. José Fernando Reyes Cuartas)", id_="c2"),
    )
    assert mal.estado == "rechazada" and "no coincide" in mal.motivos[0] and "Nilson Pinilla Pinilla" in mal.motivos[0]
    assert bien.estado == "ok"


def test_verificar_anio_inconsistente_con_dataset(cfg):
    (cv,) = _verificar(cfg, _p("T-200 de 1922"))
    assert cv.estado == "rechazada" and "no coincide con la fecha" in cv.motivos[0]


def test_verificar_sin_relatoria_solo_comprueba_dataset(cfg, monkeypatch):
    llamadas = _red(monkeypatch, _pagina("T-200-22"))
    cfg.verificar_relatoria = False
    existe, no_existe = _verificar(cfg, _p("T-200/22"), _p("T-999/22", id_="c2"))
    assert existe.estado == "alerta" and existe.cobertura is None and not existe.pagina_ok
    assert existe.mp_dataset == "José Fernando Reyes Cuartas" and "desactivada" in existe.motivos[0]
    assert no_existe.estado == "rechazada"
    assert llamadas == []


def test_verificar_mp_obligatorio(cfg):
    dataset = {"T-001/92": {"magistrado_a": "Conjuez", "fecha_sentencia": "1992-04-03T00:00:00.000"}}
    cfg.verificar_relatoria = False
    (exigido,) = citas.verificar_citas([_p("T-001/92")], cfg, dataset)
    assert exigido.estado == "rechazada" and "magistrado ponente" in exigido.motivos[0]
    cfg.exigir_mp = False
    (laxo,) = citas.verificar_citas([_p("T-001/92")], cfg, dataset)
    assert laxo.estado == "alerta"
    assert citas.formatear_referencia(laxo) == "Sentencia T-001 de 1992"


def test_verificar_ponencia_compuesta_se_avisa(cfg):
    cfg.verificar_relatoria = False
    compuesta, conjuez, simple = _verificar(
        cfg, _p("C-252/94"), _p("C-681/03", id_="c2"), _p("T-1000/99", id_="c3")
    )
    assert any("compuesta" in m for m in compuesta.motivos)
    assert any("compuesta" in m for m in conjuez.motivos)
    assert not any("compuesta" in m for m in simple.motivos)
    assert simple.sentencia_norm == "T-1000/99" and simple.url.endswith("/1999/T-1000-99.htm")


def test_verificar_descarga_la_pagina_una_sola_vez(cfg, monkeypatch):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    llamadas: list[str] = []
    original = citas.texto_relatoria

    def contar(url, c):
        llamadas.append(url)
        return original(url, c)

    monkeypatch.setattr(citas, "texto_relatoria", contar)
    resultado = _verificar(cfg, _p("T-200/22"), _p("T-200 de 2022", "otra cosa distinta " * 5, "c2"))
    assert len(llamadas) == 1
    assert [r.estado for r in resultado] == ["ok", "rechazada"]


def test_verificar_cita_literal_con_parentesis_sin_cerrar_en_la_pagina(cfg):
    cuerpo = (
        "<p>La orden (uno o mas musculos " + RELLENO_LARGO + "</p>"
        "<p>" + TEXTO_BASE + "</p><p>son competentes: a) los jueces</p>"
    )
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", cuerpo))
    (cv,) = _verificar(cfg, _p("T-200/22"))
    assert cv.estado == "ok" and cv.cobertura == 1.0


def test_verificar_cita_literal_con_cierre_suelto_dentro_de_la_cita(cfg):
    cita = TEXTO_BASE.replace("defensa antes", "defensa a) antes")
    cuerpo = "<p>La orden (uno o mas musculos de relleno</p><p>" + cita + "</p><p>son competentes los jueces</p>"
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", cuerpo))
    (cv,) = _verificar(cfg, _p("T-200/22", cita))
    assert cv.estado == "ok" and cv.cobertura == 1.0


DATOS = os.environ.get("TUTELA2_DATOS")
real = pytest.mark.skipif(
    not DATOS or not (Path(DATOS or ".") / "datos" / "cc_sentencias.csv").is_file(),
    reason="TUTELA2_DATOS no apunta a la carpeta con datos/ y relatoria/",
)
PAGINAS_REALES = {
    "T-892-11.htm": ("T", 892, 2011), "T-048-10.htm": ("T", 48, 2010), "T-210-14.htm": ("T", 210, 2014),
    "T-554-19.htm": ("T", 554, 2019), "T-225-93.htm": ("T", 225, 1993), "SU391-16.htm": ("SU", 391, 2016),
    "SU712-13.htm": ("SU", 712, 2013), "C-321-22.htm": ("C", 321, 2022), "T-200-22.htm": ("T", 200, 2022),
    "T-157-14.htm": ("T", 157, 2014), "T-468-03.htm": ("T", 468, 2003), "SU082-95.htm": ("SU", 82, 1995),
}
CITA_T892 = (
    "La acción de tutela es un mecanismo de protección judicial de carácter subsidiario, excepcional y residual, "
    "que solo procede cuando no existen otros medios de defensa judicial, o cuando existiendo, estos no resultan "
    "eficaces para la protección inmediata de los derechos fundamentales vulnerados"
)
CITA_SU712_CORTA = "La naturaleza subsidiaria de la tutela pretende evitar que se soslayen los cauces ordinarios"
CITA_SU712 = (
    "La naturaleza subsidiaria de la tutela pretende evitar que se soslayen los cauces ordinarios para la "
    "resolución de las controversias jurídicas, se convierta en un instrumento supletorio cuando no se han "
    "utilizado oportunamente dichos medios, o sea una instancia adicional para reabrir debates concluidos."
)


@pytest.fixture
def cfg_real(tmp_path) -> Config:
    c = Config(cache_dir=str(tmp_path / "cache"))
    origen = Path(DATOS)
    shutil.copyfile(origen / "datos" / "cc_sentencias.csv", c.cache_path() / "cc_sentencias.csv")
    destino = c.cache_path() / "relatoria"
    destino.mkdir()
    for nombre in PAGINAS_REALES:
        shutil.copyfile(origen / "relatoria" / nombre, destino / nombre)
    return c


@real
def test_real_dataset_completo(cfg_real):
    ds = citas.cargar_dataset(cfg_real)
    assert len(ds) > 29000
    assert ds["T-892/11"]["magistrado_a"] == "Nilson Pinilla Pinilla"
    assert ds["SU-034/18"]["magistrado_a"] == "Alberto Rojas Ríos"
    assert "T-539A/93" in ds and "T-1000/99" in ds


@real
@pytest.mark.parametrize("nombre,partes", PAGINAS_REALES.items())
def test_real_cada_pagina_se_reconoce_por_contenido(cfg_real, nombre, partes):
    texto = citas.texto_relatoria(citas.url_relatoria(*partes), cfg_real)
    assert texto
    assert citas._pagina_corresponde(citas.normalizar_texto(texto), *partes)


@real
def test_real_t892_cita_no_localizada_y_mp_del_dataset(cfg_real):
    ds = citas.cargar_dataset(cfg_real)
    (cv,) = citas.verificar_citas([_p("T-892 de 2011", CITA_T892)], cfg_real, ds)
    assert cv.estado == "rechazada" and cv.pagina_ok
    assert cv.mp_dataset == "Nilson Pinilla Pinilla"
    assert 0.01 < cv.cobertura < 0.06


@real
def test_real_su712_cita_literal_al_100(cfg_real):
    ds = citas.cargar_dataset(cfg_real)
    larga, corta = citas.verificar_citas(
        [_p("SU-712/13", CITA_SU712), _p("SU712-13", CITA_SU712_CORTA, "c2")], cfg_real, ds
    )
    assert larga.estado == "ok" and larga.cobertura == 1.0 and larga.seccion == "mayoria"
    assert corta.estado == "rechazada" and corta.cobertura == 1.0 and corta.n_palabras == 14
    assert larga.mp_dataset == "Jorge Iván Palacio Palacio"


@real
def test_real_su712_con_pasaje_de_otra_sentencia_se_rechaza(cfg_real):
    ds = citas.cargar_dataset(cfg_real)
    (cv,) = citas.verificar_citas([_p("T-200/22", CITA_SU712)], cfg_real, ds)
    assert cv.estado == "rechazada" and cv.cobertura < 0.1


@real
def test_real_pagina_que_no_es_sentencia_o_cambiada(cfg_real):
    destino = cfg_real.cache_path() / "relatoria"
    shutil.copyfile(Path(DATOS) / "relatoria" / "d2591.htm", destino / "T-200-22.htm")
    shutil.copyfile(Path(DATOS) / "relatoria" / "T-892-11.htm", destino / "T-157-14.htm")
    ds = citas.cargar_dataset(cfg_real)
    decreto, cambiada = citas.verificar_citas(
        [_p("T-200/22", CITA_SU712), _p("T-157/14", CITA_T892, "c2")], cfg_real, ds
    )
    assert decreto.estado == "rechazada" and not decreto.pagina_ok
    assert cambiada.estado == "rechazada" and not cambiada.pagina_ok


@real
def test_real_referencias(cfg_real):
    ds = citas.cargar_dataset(cfg_real)
    cvs = citas.verificar_citas(
        [_p("T-200 de 2022", "x", "c1"), _p("T-157/14", "x", "c2"), _p("SU-082/95", "x", "c3")], cfg_real, ds
    )
    refs = [citas.formatear_referencia(c) for c in cvs]
    assert refs == [
        "Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas",
        "Sentencia T-157 de 2014, con ponencia de la Magistrada María Victoria Calle Correa",
        "Sentencia SU-082 de 1995, con ponencia del Magistrado Jorge Arango Mejía",
    ]


@real
def test_real_prosa_con_menciones():
    prosa = "Según la Sentencia T-200 de 2022, M.P. José Fernando Reyes Cuartas, y la SU-082/95, reiteradas en C-321/22."
    assert citas.sentencias_en_texto(prosa) == {"T-200/22", "SU-082/95", "C-321/22"}


ENUMERACION = (
    "Para que proceda el amparo transitorio se requiere: (i) que el perjuicio sea inminente y cierto; "
    "(ii) que las medidas sean urgentes e impostergables; (iii) que el perjuicio sea grave, esto es, de "
    "gran intensidad frente a los derechos fundamentales del afectado en el caso concreto."
)


@pytest.mark.parametrize("marca", ["(...)", "[...]", "(…)", "[…]", "…", "..."])
def test_cobertura_marca_de_omision_junto_a_parentesis_conservado(marca):
    cita = (
        "Para que proceda el amparo transitorio se requiere: (i) que el perjuicio sea inminente "
        f"{marca} (iii) que el perjuicio sea grave, esto es, de gran intensidad frente a los derechos "
        "fundamentales del afectado en el caso concreto."
    )
    assert citas.cobertura(cita, ENUMERACION) >= 0.8
    assert citas.motivo_parentesis(cita, ENUMERACION) is None


def test_cobertura_omision_justo_antes_y_justo_despues_del_grupo_conservado():
    antes = "(...) (ii) que las medidas sean urgentes e impostergables; (iii) que el perjuicio sea grave"
    despues = "se requiere: (i) (...) que el perjuicio sea inminente y cierto; (ii) que las medidas"
    for cita in (antes, despues):
        assert citas.motivo_parentesis(cita, ENUMERACION) is None
        assert citas.cobertura(cita, ENUMERACION) >= 0.8


@pytest.mark.parametrize(
    "cita",
    [
        "se requiere: (no) (...) que el perjuicio sea inminente y cierto; que las medidas",
        "se requiere que el perjuicio sea inminente (...) (no) (iii) que el perjuicio sea grave",
        "(...) (no) (...)",
        "se requiere (no) … que el perjuicio sea inminente",
    ],
)
def test_cobertura_parentesis_inventado_junto_a_omision_se_rechaza(cita):
    assert citas.cobertura(cita, ENUMERACION) == 0.0


def test_cobertura_conserva_un_parentesis_y_omite_dos_previos():
    fuente = "uno dos tres (a) (b) (c) cuatro cinco seis siete ocho nueve diez"
    assert citas.cobertura("uno dos tres (c) cuatro cinco seis siete ocho nueve diez", fuente) == 1.0
    assert citas.cobertura("dos tres (c) cuatro cinco seis", fuente) == 1.0
    assert citas.cobertura("uno dos tres (c) cuatro cinco seis siete ocho nueve diez", "uno dos tres cuatro cinco") == 0.0


def test_cobertura_salta_varios_parentesis_hacia_la_derecha():
    fuente = "uno dos tres cuatro (a) (b) cinco seis siete ocho nueve diez"
    assert citas.cobertura("uno dos tres (xx) cuatro cinco seis", fuente + " (xx)") == 0.0
    cita = "uno dos tres cuatro (b) cinco seis siete ocho nueve diez"
    assert citas.cobertura(cita, fuente) == 1.0


NOTA = "(T-760 de 2008, M.P. Jaime Araújo Rentería)"
FUENTE_NOTA = f"<p>{TEXTO_BASE[:60]} {NOTA} {TEXTO_BASE[60:]}</p>"


def test_notas_ausentes():
    fuente = f"{TEXTO_BASE[:60]} {NOTA} {TEXTO_BASE[60:]}"
    assert citas.notas_ausentes(TEXTO_BASE, fuente) == []
    assert citas.notas_ausentes(f"{TEXTO_BASE[:60]} {NOTA} {TEXTO_BASE[60:]}", fuente) == []
    mala = "(T-760 de 2008, M.P. Manuel José Cepeda Espinosa)"
    assert citas.notas_ausentes(f"{TEXTO_BASE[:60]} {mala} {TEXTO_BASE[60:]}", fuente) == [mala]
    assert citas.notas_ausentes(f"{TEXTO_BASE[:60]} (subrayado fuera del texto) {TEXTO_BASE[60:]}", fuente) == []
    assert citas.notas_ausentes(f"{TEXTO_BASE[:60]} (...) {TEXTO_BASE[60:]}", fuente) == []


def test_verificar_nota_de_sentencia_presente_en_la_fuente_sigue_ok(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", FUENTE_NOTA))
    (cv,) = _verificar(cfg, _p("T-200/22", f"{TEXTO_BASE[:60]} {NOTA} {TEXTO_BASE[60:]}"))
    assert cv.estado == "ok" and cv.motivos == []


def test_verificar_nota_de_sentencia_ausente_en_la_fuente_es_alerta(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", FUENTE_NOTA))
    mala = "(T-760 de 2008, M.P. Manuel José Cepeda Espinosa)"
    (cv,) = _verificar(cfg, _p("T-200/22", f"{TEXTO_BASE[:60]} {mala} {TEXTO_BASE[60:]}"))
    assert cv.estado == "alerta" and cv.cobertura >= 0.8
    assert cv.motivos == [f"La nota «{mala}» no aparece en la fuente; verifíquela."]


def test_verificar_nota_de_enfasis_u_omision_no_cambia_el_estado(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    texto = f"{TEXTO_BASE[:60]} (subrayado fuera del texto) {TEXTO_BASE[60:]}"
    (cv,) = _verificar(cfg, _p("T-200/22", texto))
    assert cv.estado == "ok" and cv.motivos == []


FUENTE_OMISIONES = (
    "La entidad debe actuar con diligencia frente a lo pedido por el ciudadano y no la dilató en ningún caso. "
    "En consecuencia cumplió lo ordenado sin dilaciones injustificadas ante el juez de instancia, con lo cual "
    "se garantizó la defensa. Lo dicho vale también para el caso en que se resolvió pronto la petición, y así, "
    "sin embargo la medida prosperó. Se reitera lo anterior respecto de los demás. ...\" "
    '(Cfr. "Título", Editorial X, págs. 45 y 46, 1979) Fin del apartado sobre la materia y texto adicional. '
    "Los hechos quedaron sin especificar en el expediente según la actora ...\" (Aportado 05/12/2023) y luego "
    "se resolvió lo pertinente al asunto."
)
INICIO_OMISIONES = "La entidad debe actuar con diligencia frente a lo pedido por el ciudadano"


@pytest.mark.parametrize(
    "cita",
    [
        f"{INICIO_OMISIONES} … (no) la … cumplió lo ordenado sin dilaciones injustificadas",
        f"{INICIO_OMISIONES} [...] (no) la [...] cumplió lo ordenado sin dilaciones injustificadas",
        f"{INICIO_OMISIONES} (...) (no) la (...) cumplió lo ordenado",
        "así … (sin embargo) la … la medida prosperó",
    ],
)
def test_cobertura_parentesis_inventado_entre_omisiones_con_segmento_corto_se_rechaza(cita):
    assert citas.cobertura(cita, FUENTE_OMISIONES) == 0.0
    assert citas.motivo_parentesis(cita, FUENTE_OMISIONES) is not None


def test_cobertura_parentesis_inventado_al_final_tras_omision_se_rechaza():
    cita = f"{INICIO_OMISIONES} ... (no) de"
    assert citas.cobertura(cita, FUENTE_OMISIONES) == 0.0


@pytest.mark.parametrize(
    "cita",
    [
        'Se reitera lo anterior respecto de los demás. ..." (Cfr. "Título", Editorial X, págs. 45 y 46, 1979)',
        'Se reitera lo anterior respecto de los demás. ... (Cfr. "Título", Editorial X, págs. 45 y 46, 1979)',
        'Los hechos quedaron sin especificar en el expediente según la actora ..." (Aportado 05/12/2023)',
        '..." (Cfr. "Título", Editorial X, págs. 45 y 46, 1979) Fin del apartado sobre la materia y texto adicional',
        'Los hechos quedaron sin especificar en el expediente según la actora ..." (Aportado 05/12/2023) y luego',
    ],
)
def test_cobertura_cita_que_empieza_o_termina_en_parentesis_de_la_fuente_junto_a_puntos_suspensivos(cita):
    assert citas.cobertura(cita, FUENTE_OMISIONES) >= 0.8
    assert citas.motivo_parentesis(cita, FUENTE_OMISIONES) is None


def test_notas_ausentes_ignora_marcador_de_nota_al_pie_dentro_de_la_nota():
    fuente = "alfa beta gamma delta epsilon zeta eta theta"
    cita = "alfa beta (Sentencia T-999 de 2015[3]) gamma delta"
    assert citas.notas_ausentes(cita, fuente) == ["(Sentencia T-999 de 2015)"]
    assert citas.notas_ausentes(cita, "alfa beta (Sentencia T-999 de 2015) gamma delta") == []


def test_notas_ausentes_nota_a_la_propia_sentencia_citada_cuenta_como_presente():
    fuente = "alfa beta gamma delta epsilon zeta eta theta"
    cita = "alfa beta (Sentencia T-200 de 2022) gamma delta"
    assert citas.notas_ausentes(cita, fuente) == ["(Sentencia T-200 de 2022)"]
    assert citas.notas_ausentes(cita, fuente, "T-200/22") == []
    assert citas.notas_ausentes(cita, fuente, "T-201/22") == ["(Sentencia T-200 de 2022)"]
    mixta = "alfa beta (Sentencia T-200 de 2022 y T-999 de 2015) gamma delta"
    assert citas.notas_ausentes(mixta, fuente, "T-200/22") == ["(Sentencia T-200 de 2022 y T-999 de 2015)"]


def test_verificar_nota_a_la_propia_sentencia_no_genera_alerta(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    nota = "(Sentencia T-200 de 2022)"
    (cv,) = _verificar(cfg, _p("T-200/22", f"{TEXTO_BASE[:60]} {nota} {TEXTO_BASE[60:]}"))
    assert cv.estado == "ok" and cv.motivos == []


def test_verificar_nota_con_marcador_al_pie_ausente_en_la_fuente_es_alerta(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    nota = "(Sentencia T-999 de 2015[3])"
    (cv,) = _verificar(cfg, _p("T-200/22", f"{TEXTO_BASE[:60]} {nota} {TEXTO_BASE[60:]}"))
    assert cv.estado == "alerta"
    assert cv.motivos == ["La nota «(Sentencia T-999 de 2015)» no aparece en la fuente; verifíquela."]


FUENTE_AGREGADOS = (
    "Antecedentes del asunto. La Sala advierte que la entidad accionada debe garantizar la continuidad del tratamiento "
    "ordenado por el médico tratante, pues la interrupción injustificada de los servicios de salud vulnera el derecho "
    "fundamental a la vida digna de los pacientes con enfermedades graves (artículo 49 de la Constitución) y "
    "compromete la estabilidad de su condición clínica. En consecuencia, las barreras administrativas no pueden "
    "trasladarse al usuario, quien tampoco está obligado a soportar demoras en la autorización de procedimientos "
    "prescritos. Finalmente, la Corte Constitucional ha reiterado que constitucional-\n"
    "mente corresponde al juez de tutela proteger de manera inmediata los derechos amenazados por la omisión estatal."
)
CITA_AGREGADOS = (
    "la entidad accionada debe garantizar la continuidad del tratamiento ordenado por el médico tratante, pues la "
    "interrupción injustificada de los servicios de salud vulnera el derecho fundamental a la vida digna de los "
    "pacientes con enfermedades graves"
)


def _con(cita: str, palabra: str, tras: str) -> str:
    assert tras in cita
    return cita.replace(tras, f"{tras} {palabra}", 1)


def test_cobertura_agregados_cita_textual_no_se_penaliza():
    assert len(CITA_AGREGADOS.split()) >= 35
    assert citas.cobertura(CITA_AGREGADOS, FUENTE_AGREGADOS) == 1.0
    assert citas.motivo_agregados(CITA_AGREGADOS, FUENTE_AGREGADOS) is None


@pytest.mark.parametrize("palabra", ["no", "nunca", "solo", "tampoco", "sin", "jamás", "salvo", "ninguna", "No"])
def test_cobertura_palabra_de_polaridad_suelta_en_cita_larga_da_cero(palabra):
    cita = _con(CITA_AGREGADOS, palabra, "debe garantizar")
    assert citas.cobertura(cita, FUENTE_AGREGADOS) == 0.0


@pytest.mark.parametrize(
    "marca", ["{no}", "（no）", "⟨no⟩", "(no", "no)", "«no»", "— no —", "[no", "no]"]
)
def test_cobertura_polaridad_con_delimitadores_raros_da_cero(marca):
    cita = _con(CITA_AGREGADOS, marca, "debe garantizar")
    assert citas.cobertura(cita, FUENTE_AGREGADOS) == 0.0


def test_cobertura_polaridad_al_inicio_o_al_final_da_cero():
    assert citas.cobertura(f"no {CITA_AGREGADOS}", FUENTE_AGREGADOS) == 0.0
    assert citas.cobertura(f"{CITA_AGREGADOS} nunca", FUENTE_AGREGADOS) == 0.0


def test_cobertura_polaridad_tras_omision_da_cero():
    cita = "la entidad accionada debe garantizar la continuidad (...) pues no la interrupción injustificada de los servicios de salud vulnera el derecho"
    assert citas.cobertura(cita, FUENTE_AGREGADOS) == 0.0


@pytest.mark.parametrize("palabra", ["claramente", "evidentemente grave"])
def test_cobertura_palabra_neutra_agregada_queda_bajo_el_umbral(palabra):
    cita = _con(CITA_AGREGADOS, palabra, "debe garantizar")
    assert 0.0 < citas.cobertura(cita, FUENTE_AGREGADOS) < 0.8


def test_motivo_agregados_nombra_las_palabras():
    cita = _con(CITA_AGREGADOS, "no", "debe garantizar")
    assert citas.motivo_agregados(cita, FUENTE_AGREGADOS) == "La cita agrega «no», que no está en la fuente."
    cita = _con(CITA_AGREGADOS, "claramente", "debe garantizar")
    assert "«claramente»" in citas.motivo_agregados(cita, FUENTE_AGREGADOS)


def test_verificar_polaridad_agregada_se_bloquea_con_motivo(cfg):
    cuerpo = f"<p>{FUENTE_AGREGADOS}</p>"
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", cuerpo))
    (cv,) = _verificar(cfg, _p("T-200/22", _con(CITA_AGREGADOS, "no", "debe garantizar")))
    assert cv.estado != "ok" and cv.cobertura == 0.0
    assert "La cita agrega «no», que no está en la fuente." in cv.motivos


def test_verificar_palabra_neutra_agregada_es_alerta_con_motivo(cfg):
    cuerpo = f"<p>{FUENTE_AGREGADOS}</p>"
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", cuerpo))
    (cv,) = _verificar(cfg, _p("T-200/22", _con(CITA_AGREGADOS, "claramente", "debe garantizar")))
    assert cv.estado == "alerta"
    assert "La cita agrega «claramente», que no está en la fuente." in cv.motivos


@pytest.mark.parametrize(
    "cita",
    [
        CITA_AGREGADOS.replace("la entidad", "[L]a entidad").replace("la continuidad", "[l]a continuidad"),
        CITA_AGREGADOS.upper(),
        CITA_AGREGADOS.replace("médico", "medico").replace("injustificada", "injustificáda"),
        CITA_AGREGADOS.replace("derecho fundamental", "derecho (sic) fundamental"),
        CITA_AGREGADOS.replace("tratante,", "tratante [1],"),
        CITA_AGREGADOS.replace("tratamiento", "tratamiento (...)"),
        CITA_AGREGADOS.replace("tratante, pues la", "tratante (...) pues la"),
        CITA_AGREGADOS.replace("la continuidad del tratamiento ordenado por el médico tratante,", "… el médico tratante,"),
        CITA_AGREGADOS.replace("graves", "graves (Se subraya)"),
        CITA_AGREGADOS.replace("graves", "graves (Sentencia T-100 de 2020)"),
    ],
)
def test_cobertura_variantes_legitimas_conservan_el_puntaje(cita):
    assert citas.cobertura(cita, FUENTE_AGREGADOS) >= 0.8
    assert citas.motivo_agregados(cita, FUENTE_AGREGADOS) is None


def test_cobertura_conserva_o_quita_incisos_de_la_fuente():
    con = CITA_AGREGADOS.replace("graves", "graves (artículo 49 de la Constitución) y compromete")
    sin = CITA_AGREGADOS.replace("graves", "graves y compromete")
    assert citas.cobertura(con, FUENTE_AGREGADOS) >= 0.8
    assert citas.cobertura(sin, FUENTE_AGREGADOS) >= 0.8


def test_cobertura_ya_presente_en_la_fuente_no_es_agregado():
    cita = (
        "los pacientes con enfermedades graves (artículo 49 de la Constitución) y compromete la estabilidad de su "
        "condición clínica. En consecuencia, las barreras administrativas no pueden trasladarse al usuario, quien "
        "tampoco está obligado a soportar demoras en la autorización"
    )
    assert citas.cobertura(cita, FUENTE_AGREGADOS) >= 0.8


def test_cobertura_particion_por_guion_no_cuenta_como_agregado():
    unida = CITA_AGREGADOS.replace("continuidad", "continui- dad")
    cita = "la Corte Constitucional ha reiterado que constitucionalmente corresponde al juez de tutela proteger de manera inmediata"
    assert citas.motivo_agregados(unida, FUENTE_AGREGADOS) is None
    assert citas.motivo_agregados(cita, FUENTE_AGREGADOS) is None
    assert citas.cobertura(cita, FUENTE_AGREGADOS) == citas._cobertura_modo(cita.lower().split(), FUENTE_AGREGADOS, 6, False)


FUENTE_OMISION = (
    "Consideraciones previas del despacho. En el presente asunto la Sala advierte que en el caso concreto no procede "
    "la acción de tutela contra providencias judiciales cuando el accionante dispone de otros medios de defensa "
    "judicial idóneos y eficaces, razón por la cual la solicitud de amparo debe ser negada por improcedente. "
    "Adicionalmente, el juez nunca puede sustituir al funcionario competente, ni actuar sin que medie una orden "
    "previa, y tampoco le corresponde ampliar el objeto del debate más allá de lo pedido por las partes. "
    "Concluido el estudio correspondiente se dispondrá lo pertinente."
)
CITA_OMISION = (
    "en el presente asunto la Sala advierte que en el caso concreto no procede la acción de tutela contra "
    "providencias judiciales cuando el accionante dispone de otros medios de defensa judicial idóneos y eficaces, "
    "razón por la cual la solicitud de amparo debe ser negada por improcedente"
)
CITA_OMISION_2 = (
    "el juez nunca puede sustituir al funcionario competente, ni actuar sin que medie una "
    "orden previa, y tampoco le corresponde ampliar el objeto del debate más allá de lo pedido por las partes"
)


def test_cobertura_cita_omision_textual_sin_cambios():
    assert len(CITA_OMISION.split()) >= 40
    assert citas.cobertura(CITA_OMISION, FUENTE_OMISION) == 1.0
    assert citas.cobertura(CITA_OMISION_2, FUENTE_OMISION) == 1.0
    assert citas.motivo_agregados(CITA_OMISION, FUENTE_OMISION) is None


@pytest.mark.parametrize(
    "cita,palabra",
    [
        (CITA_OMISION, "no"),
        (CITA_OMISION_2, "nunca"),
        (CITA_OMISION_2, "sin"),
        (CITA_OMISION_2, "tampoco"),
    ],
)
def test_cobertura_polaridad_omitida_da_cero(cita, palabra):
    mutilada = cita.replace(f" {palabra} ", " ", 1)
    assert mutilada != cita
    assert citas.cobertura(mutilada, FUENTE_OMISION) == 0.0
    assert citas.motivo_agregados(mutilada, FUENTE_OMISION) == f"La cita omite «{palabra}», que sí está en la fuente."


def test_cobertura_polaridad_omitida_entre_parentesis_de_omision_no_se_penaliza():
    cita = (
        "en el presente asunto la Sala advierte que en el caso concreto (...) la acción de tutela contra "
        "providencias judiciales cuando el accionante dispone de otros medios de defensa judicial idóneos y eficaces"
    )
    assert citas.cobertura(cita, FUENTE_OMISION) >= 0.8
    assert citas.motivo_agregados(cita, FUENTE_OMISION) is None


def test_cobertura_polaridad_fuera_del_tramo_alineado_no_se_penaliza():
    cita = "procede la acción de tutela contra providencias judiciales cuando el accionante dispone de otros medios"
    assert citas.cobertura(cita, FUENTE_OMISION) == 1.0


def test_cobertura_palabra_neutra_omitida_conserva_el_puntaje_ngramas():
    mutilada = CITA_OMISION.replace("judicial idóneos", "idóneos", 1)
    assert 0.0 < citas.cobertura(mutilada, FUENTE_OMISION) < 1.0
    assert citas.motivo_agregados(mutilada, FUENTE_OMISION) is None


def test_verificar_polaridad_omitida_se_bloquea_con_motivo(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", f"<p>{FUENTE_OMISION}</p>"))
    mutilada = CITA_OMISION.replace(" no procede", " procede", 1)
    (cv,) = _verificar(cfg, _p("T-200/22", mutilada))
    assert cv.estado != "ok" and cv.cobertura == 0.0
    assert "La cita omite «no», que sí está en la fuente." in cv.motivos


def test_verificar_pasaje_inventado_no_lista_agregados(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", f"<p>{FUENTE_OMISION}</p>"))
    inventada = (
        "la garantía de los derechos sociales prestacionales requiere una intervención decidida del legislador "
        "para asegurar la progresividad presupuestal de las políticas públicas destinadas a poblaciones vulnerables"
    )
    assert len(inventada.split()) >= 25
    (cv,) = _verificar(cfg, _p("T-200/22", inventada))
    assert cv.cobertura == 0.0 and cv.estado != "ok"
    assert any("no se localizó" in m for m in cv.motivos)
    assert not any("agrega" in m or "omite" in m for m in cv.motivos)


_RELLENO_NEG = " ".join(f"palabra{i} texto{i} relleno{i}." for i in range(60))
_BASE_NEG = (
    "La Corte ha reiterado que la accion de tutela resulta procedente para proteger los derechos "
    "fundamentales de las personas cuando la actuacion de la administracion fue ilegal y vulnero "
    "de manera grave el debido proceso del ciudadano que acudio ante la jurisdiccion constitucional "
    "en busca de amparo inmediato y efectivo frente a la amenaza alegada en el escrito de tutela."
)
_GAP_NEG = (
    "Esta Corporacion ha sostenido que nunca y bajo ninguna circunstancia procede la tutela contra "
    "las decisiones adoptadas por los jueces dentro de un proceso ordinario debidamente tramitado y "
    "concluido conforme a las reglas procesales vigentes en el ordenamiento juridico colombiano actual."
)
_FUENTE_NEG = f"{_RELLENO_NEG} {_BASE_NEG} {_RELLENO_NEG} {_GAP_NEG} {_RELLENO_NEG}"


@pytest.mark.parametrize(
    "viejo,nuevo",
    [("ilegal", "legal"), ("ilegal y", "ilicito y"), ("procedente", "improcedente")],
)
def test_cobertura_prefijo_negativo_no_es_errata(viejo, nuevo):
    cita = _BASE_NEG.replace(viejo, nuevo)
    puntaje = citas.cobertura(cita, _FUENTE_NEG)
    assert puntaje is not None and puntaje <= citas.TOPE_AGREGADOS
    assert "agrega" in citas.motivo_agregados(cita, _FUENTE_NEG)


def test_cobertura_errata_de_una_letra_sigue_tolerada():
    cita = _BASE_NEG.replace("ciudadano", "ciudadnao".replace("nao", "ano"))
    assert citas.cobertura(cita, _FUENTE_NEG) >= 0.8
    assert citas.cobertura(_BASE_NEG.replace("grave", "grabe"), _FUENTE_NEG) >= 0.8


def test_cobertura_negacion_omitida_en_medio_de_la_cita():
    cita = _GAP_NEG.replace("que nunca y bajo ninguna circunstancia procede", "que procede")
    assert citas.cobertura(cita, _FUENTE_NEG) == 0.0
    assert "omite" in citas.motivo_agregados(cita, _FUENTE_NEG)


@pytest.mark.parametrize(
    "encabezado",
    [
        "Expediente No. T-8.123.456 Sentencia T-123 de 2020",
        "Exp. Nº 8123",
        "Página 5 de 12 sin título",
    ],
)
def test_cobertura_encabezado_de_pagina_no_es_negacion_omitida(encabezado):
    mitad = len(_GAP_NEG) // 2
    corte = _GAP_NEG.index(" ", mitad)
    fuente = f"{_RELLENO_NEG} {_GAP_NEG[:corte]} {encabezado} {_GAP_NEG[corte + 1:]} {_RELLENO_NEG}"
    assert citas.cobertura(_GAP_NEG, fuente) >= 0.8


_RELLENO_AB = " ".join(f"palabra{i} texto{i} relleno{i}." for i in range(60))
_TRAMO_AB = (
    "En virtud de lo dispuesto en el {a} de 2020 las audiencias se realizarán de manera virtual por regla "
    "general en todos los despachos judiciales del pais segun lo previsto."
)


@pytest.mark.parametrize(
    ("fuente", "cita"),
    [
        ("Decreto 806", "Decreto No. 806"),
        ("Decreto No. 806", "Decreto 806"),
        ("Resolucion numero 4521", "Resolucion No. 4521"),
        ("Sentencia Nº 8123", "Sentencia 8123"),
        ("Proceso No. T-8.123.456", "Proceso T-8.123.456"),
        ("Decreto 806", "Decreto No 806"),
    ],
)
def test_cobertura_abreviatura_no_numero_no_es_negacion(fuente, cita):
    f = f"{_RELLENO_AB} {_TRAMO_AB.format(a=fuente)} {_RELLENO_AB}"
    q = _TRAMO_AB.format(a=cita)
    assert citas.cobertura(q, f) > 0.7
    assert citas.motivo_agregados(q, f) is None


def test_cobertura_no_genuino_sigue_siendo_negacion():
    f = f"{_RELLENO_AB} {_TRAMO_AB.format(a='caso')} {_RELLENO_AB}"
    assert citas.cobertura(_TRAMO_AB.format(a="caso no procede"), f) == 0.0
    assert citas.cobertura(_TRAMO_AB.format(a="no 806 personas"), f) == 0.0
    f2 = f"{_RELLENO_AB} {_TRAMO_AB.format(a='caso no procede')} {_RELLENO_AB}"
    assert citas.cobertura(_TRAMO_AB.format(a="caso"), f2) == 0.0


_TRAMO_TUTELA = (
    "ha sostenido esta corporacion de manera reiterada que la accion de tutela{neg} procede contra providencias "
    "judiciales salvo que se acredite el cumplimiento de los requisitos generales y especificos de procedibilidad "
    "establecidos por la jurisprudencia constitucional para proteger los derechos fundamentales de las partes"
)


def test_cobertura_no_tras_tipo_de_documento_sin_numero_es_negacion():
    sin, con = _TRAMO_TUTELA.format(neg=""), _TRAMO_TUTELA.format(neg=" no")
    assert len(con.split()) >= 40
    assert citas.cobertura(con, sin) == 0.0
    assert citas.motivo_agregados(con, sin) is not None
    assert citas.cobertura(sin, con) == 0.0


@pytest.mark.parametrize("tipo", ["sentencia", "ley", "auto", "fallo", "sala", "proceso"])
def test_cobertura_tipo_de_documento_seguido_de_no_y_palabras_es_polaridad(tipo):
    base = f"{_RELLENO_AB} {_TRAMO_AB.format(a=f'el {tipo} aplica')} {_RELLENO_AB}"
    q = _TRAMO_AB.format(a=f"el {tipo} no aplica")
    assert citas.cobertura(q, base) == 0.0
    assert citas.cobertura(_TRAMO_AB.format(a=f"el {tipo} aplica"), base.replace("aplica", "no aplica")) == 0.0


def test_cobertura_digito_junto_a_negacion_no_excusa_la_omision():
    cita = _GAP_NEG.replace("que nunca y bajo ninguna circunstancia procede", "que procede")
    fuente = _FUENTE_NEG.replace("nunca y bajo", "nunca 15 y bajo")
    assert citas.cobertura(cita, fuente) == 0.0


def test_cobertura_negacion_omitida_en_hueco_largo():
    cita = _GAP_NEG.replace("que nunca y bajo ninguna circunstancia procede", "que procede")
    fuente = _FUENTE_NEG.replace("nunca y bajo ninguna", "en ningun caso y bajo ninguna")
    assert citas.cobertura(cita, fuente) == 0.0


@pytest.mark.parametrize("marca", ["(...)", "…"])
def test_cobertura_omision_marcada_no_se_penaliza(marca):
    cita = _GAP_NEG.replace("nunca y bajo ninguna circunstancia", marca)
    assert citas.cobertura(cita, _FUENTE_NEG) >= 0.8


FIXTURES = Path(__file__).parent / "fixtures" / "relatoria"
MP_FIXTURES = {
    "C-543-92": ("C", 543, 1992, "José Gregorio Hernández Galindo"),
    "C-774-01": ("C", 774, 2001, "Rodrigo Escobar Gil"),
    "T-1215-03": ("T", 1215, 2003, "Clara Inés Vargas Hernández"),
    "C-313-14": ("C", 313, 2014, "Gabriel Eduardo Mendoza Martelo"),
}
DATASET_FIXTURES = {
    citas.clave_dataset(t, n, a): {"magistrado_a": mp, "fecha_sentencia": f"{a}-01-01"}
    for t, n, a, mp in MP_FIXTURES.values()
}


def _html_fixture(nombre: str) -> str:
    return citas._decodificar((FIXTURES / f"{nombre}.min.html").read_bytes())


def _secciones_fixture(nombre: str) -> citas.SeccionesRelatoria:
    return citas.separar_secciones(citas._html_a_texto(_html_fixture(nombre)))


def _verificar_fixture(cfg: Config, nombre: str, texto: str, id_: str = "c1") -> CitaVerificada:
    datos = (FIXTURES / f"{nombre}.min.html").read_bytes()
    relleno = max(0, citas.MIN_BYTES_PAGINA - len(datos))
    _poner_pagina(cfg, f"{nombre}.htm", datos + b"<!-- " + b"x" * relleno + b" -->")
    tipo, numero, anio, _ = MP_FIXTURES[nombre]
    (cv,) = citas.verificar_citas([_p(f"{tipo}-{numero} de {anio}", texto, id_)], cfg, DATASET_FIXTURES)
    return cv


MAYORIA_C543 = (
    "La Corte ha señalado que dos de las características esenciales de esta figura en el ordenamiento jurídico "
    "colombiano son la subsidiariedad y la inmediatez: la primera por cuanto tan sólo resulta procedente instaurar "
    "la acción en subsidio o a falta de instrumento constitucional o legal diferente, susceptible de ser alegado "
    "ante los jueces"
)
SALVAMENTO_C543 = (
    "Es evidente que si contra una sentencia dictada por el Juez en abierta violación de los derechos "
    "constitucionales fundamentales, se ejercen todos los medios de impugnación ordinarios y, no obstante, la "
    "vulneración persiste, no disponiendo el afectado de otro medio de defensa judicial - se han agotado todos - "
    "sólo le queda la acción de tutela"
)
MAYORIA_C774 = (
    "La cosa juzgada constitucional es una institución jurídico procesal que tiene su fundamento en el artículo "
    "243 de la Constitución Política y mediante la cual se otorga a las decisiones plasmadas en una sentencia de "
    "constitucionalidad, el carácter de inmutables, vinculantes y definitivas."
)
ACLARACION_C774 = (
    "Con el debido respeto por la mayoría de la Corte y por el magistrado ponente, aclaro mi voto respecto de un "
    "par de asuntos puntuales porque en general comparto tanto los argumentos plasmados en la sentencia como el "
    "espíritu garantista de la libertad personal que la anima."
)
PARAFRASIS_T1215 = (
    "Para prevenir actitudes deshonestas y contradictorias, específicamente frente al ejercicio de la tutela, el "
    "Decreto 2591 de 1991 consagró que cuando sin motivo expresamente justificado una persona presente ante varios "
    "jueces la misma acción de tutela con fundamento en los mismos hechos y pidiendo la protección de los mismos "
    "derechos de origen constitucional, se rechazarán o decidirán desfavorablemente todas las solicitudes."
)
CITAS_DEBILES_406 = [
    ("C-543-92", "cuando el afectado no disponga de otro medio de defensa judicial", 11),
    ("C-774-01", "inmutables, vinculantes y definitivas", 4),
    ("T-1215-03", "sin motivo expresamente justificado", 4),
    ("C-313-14", "El derecho fundamental a la salud es autónomo e irrenunciable en lo individual y en lo colectivo.", 17),
]
VOTO_SINTETICO = (
    "El salvamento sostiene que la tutela procede contra providencias judiciales aunque se hayan agotado los "
    "recursos ordinarios cuando la vulneración persiste y no existe otro medio idóneo para evitar un perjuicio "
    "irremediable a los derechos fundamentales de la persona afectada."
)


def _pagina_con_votos(ident: str, mayoria: str, voto: str = "", nota: str = "") -> bytes:
    cuerpo = f"<p>{mayoria}</p><p>Notifíquese, comuníquese y cúmplase.</p><p>Magistrado</p><p>Secretaria General</p>"
    if voto:
        cuerpo += f"<p>Salvamento de voto a la Sentencia No. T-200</p><p>{voto}</p>"
    if nota:
        cuerpo += f"<div><div id=ftn1><p>{nota}</p></div></div>"
    return _pagina(ident, cuerpo, cierre=False)


def test_contar_palabras_ignora_omisiones_y_cuenta_incisos():
    assert citas.contar_palabras("uno dos (...) tres [...] cuatro") == 4
    assert citas.contar_palabras("(i) uno, (ii) dos") == 4
    assert citas.contar_palabras("") == 0
    assert citas.contar_palabras(TEXTO_BASE) == 43


def test_marca_de_notas_no_agrega_tokens_al_texto():
    assert citas.normalizar_texto(citas.MARCA_NOTAS) == ""
    sin = citas._html_a_texto("<p>uno dos tres</p><div><p>notas</p></div>")
    con = citas._html_a_texto("<p>uno dos tres</p><div><div id=ftn1><p>notas</p></div></div>")
    assert citas.normalizar_texto(con) == citas.normalizar_texto(sin)
    assert citas.MARCA_NOTAS in con and citas.MARCA_NOTAS not in sin


def test_marca_de_notas_solo_en_el_primer_bloque_de_notas():
    texto = citas._html_a_texto("<p>a</p><div id=ftn1><p>n1</p></div><div id=ftn2><p>n2</p></div>")
    assert texto.count(citas.MARCA_NOTAS) == 1


def test_separar_secciones_c543_salvamento_comunicado_y_notas():
    s = _secciones_fixture("C-543-92")
    assert "R E S U E L V E" in s.mayoria and "Secretaria General" in s.mayoria
    assert "dos (2) de junio" not in s.votos and "aclaración de voto formulada" in s.mayoria
    assert s.votos.startswith("COMUNICADO Sentencia C-543")
    assert "Salvamento de voto a la Sentencia No. C-543" in s.votos and SALVAMENTO_C543 in s.votos
    assert "Enciclopedia Jurídica OMEBA" in s.resto and "Enciclopedia" not in s.votos
    assert citas.MARCA_NOTAS not in s.mayoria + s.votos + s.resto


def test_separar_secciones_aclaracion_sin_salvamento_c774():
    s = _secciones_fixture("C-774-01")
    assert MAYORIA_C774 in s.mayoria and "Secretaria General" in s.mayoria
    assert s.votos.startswith("Aclaración de voto a la Sentencia C-774/01") and ACLARACION_C774 in s.votos
    assert "Ver entre otras las sentencias" in s.resto and "Ver entre otras" not in s.votos


def test_separar_secciones_c313_firmas_anexo_votos_y_autos():
    s = _secciones_fixture("C-313-14")
    assert "Con salvamento parcial de voto" in s.mayoria and "ANEXO" in s.mayoria
    assert "ACLARACION DE VOTO DEL MAGISTRADO" in s.votos and "ACLARACIÓN Y SALVAMENTO PARCIAL DE VOTO" in s.votos
    assert "ACLARACION DE VOTO DE LA MAGISTRADA" in s.votos
    assert "Auto 377/14" in s.resto and "Auto 078/15" in s.resto and "Auto 377/14" not in s.votos


def test_separar_secciones_su712_variantes_de_titulo():
    s = _secciones_fixture("SU712-13")
    assert "SALVAMENTO DE VOTO DEL MAGISTRADO" in s.votos and "ACLARACIÓN DE VOTO DEL MAGISTRADO" in s.votos
    assert "Notifíquese, comuníquese y cúmplase." in s.mayoria and "Con salvamento de voto" in s.mayoria


def test_separar_secciones_sin_votos_todo_es_mayoria():
    s = _secciones_fixture("T-1215-03")
    assert s.votos == "" and s.resto == ""
    assert "Cuarto.- ORDENAR" in s.mayoria and PARAFRASIS_T1215 in s.mayoria
    assert citas.MARCA_NOTAS not in s.mayoria


def test_separar_secciones_pagina_sin_marcadores_es_mayoria_completa():
    texto = citas._html_a_texto(_pagina("T-200-22").decode("cp1252"))
    s = citas.separar_secciones(texto)
    assert s.votos == "" and s.resto == "" and "SENTENCIA T-200-22" in s.mayoria


def test_separar_secciones_ignora_menciones_de_votos_antes_del_cierre():
    texto = "La Corte acoge la aclaración de voto formulada por otro magistrado.\nSalvamento de voto a la Sentencia No. 1\nNotifíquese y cúmplase.\nSecretaria General"
    s = citas.separar_secciones(texto)
    assert s.votos == "" and "aclaración de voto formulada" in s.mayoria and s.delimitada


CIERRE_ESTANDAR = "Notifíquese, comuníquese y cúmplase."
CIERRES_CUMPLASE_PRIMERO = [
    "Cúmplase, cópiese, publíquese, comuníquese a quien corresponda, insértese en la Gaceta de la Corte "
    "Constitucional y archívese el expediente.",
    "Cúmplase, cópiese, publíquese, comuníquese y archívese.",
]


def _texto_con_voto(cierre: str | None, titulo: str, firma: str | None = "Con salvamento de voto") -> str:
    lineas = [
        "SENTENCIA T-200/22", TEXTO_BASE, cierre, "JUAN PEREZ", "Magistrado", firma, "Secretaria General", titulo,
        VOTO_SINTETICO,
    ]
    return "\n".join(ln for ln in lineas if ln)


@pytest.mark.parametrize("cierre", CIERRES_CUMPLASE_PRIMERO)
def test_cierres_que_empiezan_por_cumplase_delimitan_la_mayoria(cierre):
    s = citas.separar_secciones(_texto_con_voto(cierre, "Salvamento de voto a la Sentencia T-200"))
    assert s.delimitada and VOTO_SINTETICO in s.votos and VOTO_SINTETICO not in s.mayoria
    assert TEXTO_BASE in s.mayoria


TITULO_NEUTRO = "Me aparto respetuosamente de la decisión de la mayoría"


@pytest.mark.parametrize(
    "firma",
    ["Con salvamento de voto", "Con aclaración de voto", "Salvamento parcial de voto", "Con salvamento parcial y aclaración de voto"],
)
def test_firma_corta_de_voto_sin_titulo_reconocido_no_se_delimita(firma):
    s = citas.separar_secciones(_texto_con_voto(CIERRE_ESTANDAR, TITULO_NEUTRO, firma))
    assert not s.delimitada and s.votos == ""


@pytest.mark.parametrize(
    "titulo",
    [
        "Salvamento de voto del doctor JUAN PEREZ",
        "Aclaración de voto de Juan Pérez, magistrado, a la presente providencia",
        "VOTO DISIDENTE DEL MAGISTRADO JUAN PEREZ",
        "Voto particular del magistrado Juan Pérez",
        "Voto concurrente del magistrado Juan Pérez",
        "VOTO SEPARADO",
    ],
)
def test_titulo_de_voto_no_estandar_sin_firma_no_se_delimita(titulo):
    s = citas.separar_secciones(_texto_con_voto(CIERRE_ESTANDAR, titulo, None))
    assert not s.delimitada and s.votos == ""


def test_linea_larga_despues_del_cierre_no_cuenta_como_firma_de_voto():
    larga = "Aclaración sobre la cuantía de las costas del proceso, " + "que se liquidarán en la forma ordinaria " * 6
    assert len(larga) > citas.MAX_LINEA_TITULO_VOTO
    assert citas.separar_secciones(_texto_con_voto(CIERRE_ESTANDAR, larga, None)).delimitada


@pytest.mark.parametrize("cierre", [None, "Así se resuelve el asunto sometido a revisión."])
def test_texto_sin_cierre_reconocido_de_la_mayoria_no_se_delimita(cierre):
    s = citas.separar_secciones(_texto_con_voto(cierre, "Salvamento de voto a la Sentencia T-200", None))
    assert not s.delimitada


def test_primer_voto_con_titulo_no_estandar_antes_de_uno_estandar_no_se_delimita():
    texto = "\n".join(
        [
            "SENTENCIA T-200/22", TEXTO_BASE, CIERRE_ESTANDAR, "Magistrado", "Secretaria General",
            "Salvamento de voto del doctor JUAN PEREZ", VOTO_SINTETICO,
            "Aclaración de voto a la Sentencia T-200", "Aclaro mi voto.",
        ]
    )
    assert not citas.separar_secciones(texto).delimitada


def test_cierre_estandar_sin_votos_ni_firmas_de_voto_se_delimita():
    s = citas.separar_secciones(_texto_con_voto(CIERRE_ESTANDAR, "Anexo de la mayoría", None))
    assert s.delimitada and s.votos == ""


def test_firma_de_voto_en_las_notas_al_pie_no_impide_delimitar():
    texto = "\n".join(
        [
            "SENTENCIA T-200/22", TEXTO_BASE, CIERRE_ESTANDAR, "Magistrado", "Secretaria General", citas.MARCA_NOTAS,
            "Salvamento de voto de los magistrados Jaime Araújo y Clara Vargas.",
        ]
    )
    s = citas.separar_secciones(texto)
    assert s.delimitada and s.votos == ""


@pytest.mark.parametrize("nombre", ["C-543-92", "C-774-01", "T-1215-03", "C-313-14", "SU712-13"])
def test_fixtures_reales_se_delimitan(nombre):
    assert _secciones_fixture(nombre).delimitada


@pytest.mark.parametrize("nombre,texto,palabras", CITAS_DEBILES_406)
def test_cuatro_citas_debiles_del_406_se_rechazan_con_la_regla(cfg, nombre, texto, palabras):
    cv = _verificar_fixture(cfg, nombre, texto)
    assert cv.estado == "rechazada" and cv.n_palabras == palabras
    assert any(f"tiene {palabras} palabra" in m and "es de 25" in m for m in cv.motivos)
    regla = cv.motivos[-1]
    for fragmento in ("ratio decidendi", "25 palabras", "Decreto 2591", "salvamento", "No acorte"):
        assert fragmento in regla


def test_citas_debiles_del_406_texto_normativo_se_nombra(cfg):
    cv = _verificar_fixture(cfg, "T-1215-03", "sin motivo expresamente justificado")
    assert any("Decreto 2591 de 1991, artículo 38" in m for m in cv.motivos)
    cv = _verificar_fixture(cfg, "C-313-14", CITAS_DEBILES_406[3][1])
    assert any("Ley 1751 de 2015, artículo 2" in m for m in cv.motivos)
    cv = _verificar_fixture(cfg, "C-774-01", "inmutables, vinculantes y definitivas")
    assert not any("artículo" in m and "transcribe" in m for m in cv.motivos)


def test_cita_corta_que_si_esta_en_la_mayoria_conserva_cobertura_y_seccion(cfg):
    cv = _verificar_fixture(cfg, "C-774-01", "inmutables, vinculantes y definitivas")
    assert cv.estado == "rechazada" and cv.cobertura == 1.0 and cv.pagina_ok and cv.seccion == "mayoria"


def test_cita_de_una_palabra_ya_no_pasa(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200/22", "subsidiariedad"))
    assert cv.estado == "rechazada" and cv.n_palabras == 1
    assert "tiene 1 palabra y" in cv.motivos[0]
    assert cv.cobertura == 1.0


def test_verificar_puebla_n_palabras_y_seccion(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200/22"))
    assert cv.estado == "ok" and cv.n_palabras == 43 and cv.seccion == "mayoria"
    assert cv.motivos == []


def test_n_palabras_se_puebla_aunque_la_cita_falle_antes(cfg):
    no_existe, ilegible = _verificar(cfg, _p("T-999 de 2022"), _p("sin identificador", id_="c2"))
    assert no_existe.n_palabras == 43 and ilegible.n_palabras == 43
    assert no_existe.seccion is None and ilegible.seccion is None


def test_longitud_minima_configurable(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    corta = " ".join(TEXTO_BASE.split()[:20])
    assert _verificar(cfg, _p("T-200/22", corta))[0].estado == "rechazada"
    cfg.min_palabras_cita = 20
    assert _verificar(cfg, _p("T-200/22", corta))[0].estado == "ok"
    cfg.min_palabras_cita = 21
    assert _verificar(cfg, _p("T-200/22", corta))[0].estado == "rechazada"
    cfg.min_palabras_cita = 0
    assert _verificar(cfg, _p("T-200/22", "subsidiariedad"))[0].estado == "ok"


def _con_cortes(*tramos: tuple[int, int]) -> str:
    palabras = TEXTO_BASE.split()
    return " (...) ".join(" ".join(palabras[a:b]) for a, b in tramos)


def test_cita_con_cortes_y_un_tramo_bajo_la_mitad_del_minimo_se_rechaza(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    corta = _con_cortes((0, 11), (15, 36))
    assert citas.contar_palabras(corta) == 32 >= cfg.min_palabras_cita
    (cv,) = _verificar(cfg, _p("T-200/22", corta))
    assert cv.estado == "rechazada" and cv.cobertura >= cfg.cobertura_ok and cv.seccion == "mayoria"
    motivo = next(m for m in cv.motivos if "omisiones" in m)
    assert "tiene 11 palabras" in motivo and "al menos 12" in motivo and "mitad del mínimo de 25" in motivo
    assert "ratio decidendi" in cv.motivos[-1]


def test_cita_con_cortes_y_todos_los_tramos_en_la_mitad_del_minimo_pasa(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200/22", _con_cortes((0, 15), (19, 35))))
    assert (cv.estado, cv.motivos) == ("ok", [])


def test_tramos_vacios_por_omision_al_inicio_o_al_final_no_cuentan(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    texto = " ".join(TEXTO_BASE.split()[:30])
    for cita in (f"(...) {texto}", f"{texto} (...)", f"(...) {texto} (...) (...)"):
        (cv,) = _verificar(cfg, _p("T-200/22", cita))
        assert (cv.estado, cv.motivos) == ("ok", []), cita


def test_tramo_corto_se_mide_con_el_minimo_configurado(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    cita = _con_cortes((0, 11), (15, 36))
    cfg.min_palabras_cita = 22
    assert _verificar(cfg, _p("T-200/22", cita))[0].estado == "ok"
    cfg.min_palabras_cita = 24
    (cv,) = _verificar(cfg, _p("T-200/22", cita))
    assert cv.estado == "rechazada" and any("al menos 12" in m for m in cv.motivos)
    cfg.min_palabras_cita = 0
    assert _verificar(cfg, _p("T-200/22", cita))[0].estado == "ok"


def test_cita_sin_cortes_no_recibe_el_motivo_por_tramo(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200/22", " ".join(TEXTO_BASE.split()[:11])))
    assert cv.estado == "rechazada" and not any("omisiones" in m for m in cv.motivos)


def test_rechazo_por_cobertura_tambien_enuncia_la_regla(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    inventada = " ".join(f"fantasia{i}" for i in range(40))
    (cv,) = _verificar(cfg, _p("T-200/22", inventada))
    assert cv.estado == "rechazada" and "no se localizó" in cv.motivos[0]
    assert "ratio decidendi" in cv.motivos[-1] and "25 palabras" in cv.motivos[-1]
    assert len(cv.motivos) == 2


def test_motivos_de_dataset_o_pagina_no_agregan_la_regla_si_la_cita_es_valida(cfg):
    no_existe, sin_pagina = _verificar(cfg, _p("T-999 de 2022"), _p("SU-082/95", id_="c2"))
    for cv in (no_existe, sin_pagina):
        assert cv.estado == "rechazada" and len(cv.motivos) == 1


def test_alerta_por_cobertura_parcial_no_agrega_la_regla(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    parcial = " ".join(TEXTO_BASE.split()[:26]) + " " + " ".join(f"inventada{i}" for i in range(10))
    (cv,) = _verificar(cfg, _p("T-200/22", parcial))
    assert cv.estado == "alerta" and not any("ratio decidendi" in m for m in cv.motivos)


def test_pasaje_solo_en_el_salvamento_c543_se_rechaza(cfg):
    cv = _verificar_fixture(cfg, "C-543-92", SALVAMENTO_C543)
    assert cv.estado == "rechazada" and cv.seccion == "salvamento" and cv.n_palabras >= 25
    assert cv.cobertura == 1.0 and cv.pagina_ok
    assert "voto separado" in cv.motivos[0] and "salvamento" in cv.motivos[0] and "C-543/92" in cv.motivos[0]
    assert "ratio decidendi" in cv.motivos[-1]


def test_pasaje_de_la_mayoria_c543_es_ok(cfg):
    cv = _verificar_fixture(cfg, "C-543-92", MAYORIA_C543)
    assert cv.estado == "ok" and cv.seccion == "mayoria" and cv.motivos == []


def test_aclaracion_de_voto_c774_se_trata_como_voto_separado(cfg):
    voto = _verificar_fixture(cfg, "C-774-01", ACLARACION_C774)
    mayoria = _verificar_fixture(cfg, "C-774-01", MAYORIA_C774, "c2")
    assert voto.estado == "rechazada" and voto.seccion == "salvamento"
    assert mayoria.estado == "ok" and mayoria.seccion == "mayoria"


def test_pagina_sin_votos_t1215_parafrasis_de_la_norma_no_es_texto_normativo(cfg):
    cv = _verificar_fixture(cfg, "T-1215-03", PARAFRASIS_T1215)
    assert cv.estado == "ok" and cv.seccion == "mayoria" and cv.motivos == []


def test_seccion_sintetica_mayoria_voto_y_notas(cfg):
    nota = "La nota al pie recuerda que la doctrina constitucional ha explicado de manera reiterada que los jueces deben motivar sus providencias con suficiencia y coherencia argumentativa en cada caso."
    _poner_pagina(cfg, "T-200-22.htm", _pagina_con_votos("T-200-22", TEXTO_BASE, VOTO_SINTETICO, nota))
    mayoria, voto, en_nota = _verificar(
        cfg, _p("T-200/22", TEXTO_BASE), _p("T-200/22", VOTO_SINTETICO, "c2"), _p("T-200/22", nota, "c3")
    )
    assert (mayoria.estado, mayoria.seccion) == ("ok", "mayoria")
    assert (voto.estado, voto.seccion) == ("rechazada", "salvamento")
    assert (en_nota.estado, en_nota.seccion) == ("alerta", "desconocida")
    assert "no se puede atribuir" in en_nota.motivos[0]
    assert not any("ratio decidendi" in m for m in en_nota.motivos)


def test_nota_al_pie_sin_votos_separados_es_de_la_mayoria(cfg):
    nota = "La nota al pie recuerda que la doctrina constitucional ha explicado de manera reiterada que los jueces deben motivar sus providencias con suficiencia y coherencia argumentativa en cada caso."
    _poner_pagina(cfg, "T-200-22.htm", _pagina_con_votos("T-200-22", TEXTO_BASE, nota=nota))
    (cv,) = _verificar(cfg, _p("T-200/22", nota))
    assert (cv.estado, cv.seccion) == ("ok", "mayoria")


def test_pasaje_repartido_entre_mayoria_y_voto_no_queda_ok(cfg):
    mitad_a = " ".join(TEXTO_BASE.split()[:22])
    mitad_b = " ".join(VOTO_SINTETICO.split()[:22])
    _poner_pagina(cfg, "T-200-22.htm", _pagina_con_votos("T-200-22", TEXTO_BASE, VOTO_SINTETICO))
    (cv,) = _verificar(cfg, _p("T-200/22", f"{mitad_a} {mitad_b}"))
    assert cv.estado != "ok"


def test_pasaje_en_mayoria_y_en_el_voto_se_toma_de_la_mayoria(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina_con_votos("T-200-22", TEXTO_BASE, TEXTO_BASE))
    (cv,) = _verificar(cfg, _p("T-200/22", TEXTO_BASE))
    assert (cv.estado, cv.seccion) == ("ok", "mayoria")


def _pagina_voto_con_titulo_no_estandar() -> bytes:
    cuerpo = (
        f"<p>{TEXTO_BASE}</p><p>{CIERRE_ESTANDAR}</p><p>Magistrado</p><p>Con salvamento de voto</p>"
        f"<p>Secretaria General</p><p>Salvamento de voto del doctor JUAN PEREZ</p><p>{VOTO_SINTETICO}</p>"
    )
    return _pagina("T-200-22", cuerpo, cierre=False)


@pytest.mark.parametrize("texto", [VOTO_SINTETICO, TEXTO_BASE])
def test_pagina_con_voto_de_titulo_no_estandar_no_deja_ok_a_ninguna_cita(cfg, texto):
    _poner_pagina(cfg, "T-200-22.htm", _pagina_voto_con_titulo_no_estandar())
    (cv,) = _verificar(cfg, _p("T-200/22", texto))
    assert (cv.estado, cv.seccion) == ("alerta", "desconocida")
    assert cv.cobertura == 1.0
    assert any("No se pudo delimitar la decisión de la mayoría" in m and "salvamento" in m and "T-200/22" in m for m in cv.motivos)


def test_pagina_sin_cierre_reconocido_deja_la_cita_en_alerta_y_sin_pasaje_cercano(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", f"<p>{S_GRAVE}</p><p>{TEXTO_BASE}</p>", cierre=False))
    literal, cercana = _verificar(cfg, _p("T-200/22", TEXTO_BASE), _p("T-200/22", NEAR_77, "c2"))
    assert (literal.estado, literal.seccion) == ("alerta", "desconocida")
    assert any("No se pudo delimitar la decisión de la mayoría" in m for m in literal.motivos)
    assert cercana.estado == "alerta" and cercana.pasaje_cercano is None
    assert not any("pasaje más cercano" in m for m in cercana.motivos)


def test_pagina_con_cierre_estandar_y_sin_votos_sigue_ok_como_mayoria(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
    (cv,) = _verificar(cfg, _p("T-200/22"))
    assert (cv.estado, cv.seccion, cv.motivos) == ("ok", "mayoria", [])


def _norma(norma: str, articulo: str) -> str:
    return next(e.texto for e in citas.normas_citables() if e.norma == norma and e.articulo == articulo)


def test_corpus_de_normas_cubre_las_diez_entradas():
    claves = {(e.norma, e.articulo) for e in citas.normas_citables()}
    assert ("Constitución Política", "86") in claves and ("Ley 1751 de 2015", "2") in claves
    assert {a for n, a in claves if n == "Decreto 2591 de 1991"} == {"1", "5", "6", "8", "10", "13", "38", "42"}


def test_texto_normativo_se_rechaza_aunque_este_en_la_mayoria(cfg):
    texto = _norma("Decreto 2591 de 1991", "10")
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", f"<p>{texto}</p>"))
    (cv,) = _verificar(cfg, _p("T-200/22", texto))
    assert cv.estado == "rechazada" and cv.cobertura == 1.0 and cv.seccion == "mayoria"
    assert "Decreto 2591 de 1991, artículo 10" in cv.motivos[0] and "no se admite" in cv.motivos[0]
    assert "Decreto 2591" in cv.motivos[-1]


def test_texto_normativo_con_una_palabra_distinta_sigue_detectado():
    texto = _norma("Decreto 2591 de 1991", "1")
    assert "en las casos" in texto
    corregido = texto.replace("en las casos", "en los casos")
    assert citas.norma_transcrita(corregido, 0.8) == ("Decreto 2591 de 1991", "1")
    assert citas.norma_transcrita(texto, 0.8) == ("Decreto 2591 de 1991", "1")


def test_norma_transcrita_con_omisiones_no_cruza_los_cortes():
    texto = _norma("Constitución Política", "86")
    palabras = texto.split()
    cita = " ".join(palabras[:12]) + " (...) " + " ".join(palabras[40:52]) + " (...) " + " ".join(palabras[80:92])
    assert citas.norma_transcrita(cita, 0.8) == ("Constitución Política", "86")


def test_norma_transcrita_no_marca_jurisprudencia_ni_comentario_mixto():
    assert citas.norma_transcrita(TEXTO_BASE, 0.8) is None
    assert citas.norma_transcrita(PARAFRASIS_T1215, 0.8) is None
    texto = _norma("Constitución Política", "86")
    mixto = " ".join(texto.split()[:12]) + " " + VOTO_SINTETICO
    assert citas.norma_transcrita(mixto, 0.8) is None
    assert citas.norma_transcrita("", 0.8) is None
    assert citas.norma_transcrita("acción de tutela", 0.8) is None


def test_corpus_de_normas_ausente_no_rompe_la_verificacion(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(citas, "RUTA_NORMAS", tmp_path / "no_existe.json")
    citas.normas_citables.cache_clear()
    try:
        assert citas.norma_transcrita("Toda persona tendrá acción de tutela para reclamar ante los jueces", 0.8) is None
        _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22"))
        assert _verificar(cfg, _p("T-200/22"))[0].estado == "ok"
    finally:
        citas.normas_citables.cache_clear()


def test_corpus_de_normas_corrupto_se_ignora(monkeypatch, tmp_path):
    malo = tmp_path / "normas.json"
    malo.write_text("{no es json", encoding="utf-8")
    monkeypatch.setattr(citas, "RUTA_NORMAS", malo)
    citas.normas_citables.cache_clear()
    try:
        assert citas.normas_citables() == ()
    finally:
        citas.normas_citables.cache_clear()


def test_modo_fake_no_se_altera_con_las_citas_de_llm_fake(cfg):
    from tutela2.llm import CITAS_FAKE

    cfg.verificar_relatoria = False
    propuestas = [_p(s, t, i) for i, (s, t) in CITAS_FAKE.items()]
    cvs = _verificar(cfg, *propuestas)
    assert [cv.estado for cv in cvs] == ["alerta", "alerta"]
    assert all(cv.n_palabras >= cfg.min_palabras_cita and cv.seccion is None for cv in cvs)
    assert all("desactivada" in cv.motivos[0] and len(cv.motivos) == 1 for cv in cvs)


def test_modo_fake_tambien_exige_longitud_y_no_texto_normativo(cfg):
    cfg.verificar_relatoria = False
    corta, norma = _verificar(
        cfg, _p("T-200/22", "dos palabras"), _p("T-200/22", _norma("Decreto 2591 de 1991", "5"), "c2")
    )
    assert corta.estado == "rechazada" and any("tiene 2 palabras" in m for m in corta.motivos)
    assert norma.estado == "rechazada" and any("artículo 5" in m for m in norma.motivos)


def test_config_min_palabras_cita_por_defecto_es_el_p10_medido():
    assert Config().min_palabras_cita == 25


S_INMINENTE = (
    "El perjuicio ha de ser inminente, lo que significa que amenaza con ocurrir de manera próxima porque existen "
    "evidencias fácticas de su presencia real en un corto lapso."
)
S_GRAVE = (
    "No basta cualquier perjuicio, se requiere que este sea grave, lo que equivale a la gran intensidad del daño o "
    "menoscabo material o moral en el haber jurídico de la persona."
)
S_URGENTE = (
    "La urgencia exige que las medidas de protección se adopten sin demora para que resulten eficaces frente a la amenaza."
)
S_CORTA = "La tutela es un mecanismo residual y subsidiario de protección."
S_SIGUE = (
    "Por eso el juez debe verificar primero si existen otros medios de defensa judicial idóneos y eficaces disponibles "
    "para el afectado."
)
S_ANTERIOR = (
    "Los jueces de instancia deben motivar con suficiencia las providencias mediante las cuales niegan o conceden el "
    "amparo solicitado."
)
S_FINAL_CORTA = "Esa carga argumentativa no admite excepciones en sede de revisión."
CUERPO_CERCANO = (
    f"<p>{S_INMINENTE} {S_GRAVE} {S_URGENTE}</p><p>{TEXTO_BASE}</p>"
    f"<p>{S_CORTA} {S_SIGUE}</p><p>{S_ANTERIOR} {S_FINAL_CORTA}</p>"
)
NEAR_79 = S_INMINENTE.replace("en un corto lapso.", "en breve tiempo.")
NEAR_77 = S_GRAVE.replace("No basta cualquier perjuicio, se requiere que este sea grave", "El perjuicio ha de ser grave")
INVENTADA_40 = " ".join(f"fantasia{i}" for i in range(40))


def _verificar_cercana(cfg: Config, texto: str, cuerpo: str = CUERPO_CERCANO) -> CitaVerificada:
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", cuerpo))
    return _verificar(cfg, _p("T-200/22", texto))[0]


def _ida_y_vuelta(cfg: Config, cv: CitaVerificada) -> CitaVerificada:
    assert cv.pasaje_cercano
    return _verificar(cfg, _p("T-200/22", cv.pasaje_cercano, "c9"))[0]


def test_pasaje_cercano_por_defecto_es_none_y_ok_no_lo_lleva(cfg):
    assert CitaVerificada(id="c1", sentencia_original="T-200/22", texto_citado="x").pasaje_cercano is None
    cv = _verificar_cercana(cfg, S_GRAVE)
    assert cv.estado == "ok" and cv.pasaje_cercano is None


def test_near_miss_al_79_devuelve_la_oracion_literal_y_pasa_al_volver(cfg):
    cv = _verificar_cercana(cfg, NEAR_79)
    assert cv.estado == "alerta" and cv.cobertura == 0.79
    assert cv.pasaje_cercano == S_INMINENTE
    assert _ida_y_vuelta(cfg, cv).estado == "ok"


def test_near_miss_al_77_devuelve_la_oracion_literal_y_pasa_al_volver(cfg):
    cv = _verificar_cercana(cfg, NEAR_77)
    assert cv.estado == "alerta" and 0.7 < cv.cobertura < cfg.cobertura_ok
    assert cv.pasaje_cercano == S_GRAVE
    vuelta = _ida_y_vuelta(cfg, cv)
    assert vuelta.estado == "ok" and vuelta.motivos == [] and vuelta.pasaje_cercano is None


def test_alerta_con_pasaje_lo_lleva_como_ultimo_motivo_con_la_instruccion(cfg):
    cv = _verificar_cercana(cfg, NEAR_79)
    ultimo = cv.motivos[-1]
    assert ultimo.startswith("El pasaje más cercano en la sentencia T-200/22 dice textualmente: «" + S_INMINENTE + "».")
    assert "cópielo sin ningún cambio" in ultimo and "al menos 25 palabras" in ultimo
    assert sum("pasaje más cercano" in m for m in cv.motivos) == 1


def test_rechazada_con_pasaje_lo_pone_justo_antes_de_la_regla(cfg):
    cv = _verificar_cercana(cfg, "Esa carga argumentativa no admite excepciones en sede de revisión constitucional.")
    assert cv.estado == "rechazada"
    assert "ratio decidendi" in cv.motivos[-1] and "pasaje más cercano" in cv.motivos[-2]


def test_cita_inventada_no_recibe_pasaje(cfg):
    cv = _verificar_cercana(cfg, INVENTADA_40)
    assert cv.estado == "rechazada" and cv.pasaje_cercano is None
    assert len(cv.motivos) == 2 and not any("pasaje más cercano" in m for m in cv.motivos)


def test_texto_juridico_plausible_pero_ausente_no_recibe_pasaje(cfg):
    inventada = (
        "La inmediatez de la acción de tutela exige que el afectado la interponga dentro de un término razonable "
        "desde el hecho que originó la vulneración, de modo que el juez pueda evaluar la urgencia de la protección."
    )
    assert _verificar_cercana(cfg, inventada).pasaje_cercano is None


def test_cita_corta_literal_recibe_el_pasaje_extendido_hasta_el_minimo(cfg):
    cv = _verificar_cercana(cfg, "La tutela es un mecanismo residual y subsidiario de protección constitucional.")
    assert cv.estado == "rechazada"
    assert cv.pasaje_cercano == f"{S_CORTA} {S_SIGUE}"
    assert citas.contar_palabras(cv.pasaje_cercano) >= cfg.min_palabras_cita
    assert _ida_y_vuelta(cfg, cv).estado == "ok"


def test_pasaje_corto_al_final_del_parrafo_se_extiende_hacia_la_oracion_anterior(cfg):
    cv = _verificar_cercana(cfg, "Esa carga argumentativa no admite excepciones en sede de revisión constitucional.")
    assert cv.pasaje_cercano == f"{S_ANTERIOR} {S_FINAL_CORTA}"
    assert _ida_y_vuelta(cfg, cv).estado == "ok"


@pytest.mark.parametrize("minimo", [0, 10, 25, 40])
def test_pasaje_cercano_respeta_el_minimo_de_palabras_configurado(cfg, minimo):
    cfg.min_palabras_cita = minimo
    cv = _verificar_cercana(cfg, "La tutela es un mecanismo residual y subsidiario de protección constitucional.")
    pasaje = cv.pasaje_cercano
    assert pasaje is not None and "\n" not in pasaje and citas.contar_palabras(pasaje) >= minimo
    assert (pasaje == S_CORTA) == (minimo <= 10)
    motivo = next(m for m in cv.motivos if "pasaje más cercano" in m)
    assert (f"al menos {minimo} palabras" in motivo) == (minimo > 0)
    assert _ida_y_vuelta(cfg, cv).estado == "ok"


S_NEGATIVA = (
    "La Corte ha explicado que el perjuicio irremediable no se configura por la sola afirmación del accionante, sino "
    "que debe acreditarse con pruebas suficientes sobre su gravedad e inminencia en el caso concreto bajo examen."
)


def test_inversion_de_polaridad_con_cobertura_cero_recibe_el_pasaje(cfg):
    invertida = S_NEGATIVA.replace("irremediable no se configura", "irremediable se configura", 1)
    cv = _verificar_cercana(cfg, invertida, f"<p>{S_NEGATIVA}</p>")
    assert cv.estado == "rechazada" and cv.cobertura == 0.0
    assert cv.pasaje_cercano == S_NEGATIVA
    assert _ida_y_vuelta(cfg, cv).estado == "ok"


def test_cita_literal_alertada_solo_por_una_nota_o_rechazada_por_seccion_no_recibe_pasaje(cfg):
    con_nota = f"{TEXTO_BASE[:60]} (Sentencia T-999 de 2015) {TEXTO_BASE[60:]}"
    cv = _verificar_cercana(cfg, con_nota, f"<p>{TEXTO_BASE}</p>")
    assert cv.estado == "alerta" and cv.pasaje_cercano is None
    assert not any("pasaje más cercano" in m for m in cv.motivos)
    salvamento = _verificar_fixture(cfg, "C-543-92", SALVAMENTO_C543)
    assert salvamento.seccion == "salvamento" and salvamento.pasaje_cercano is None


def test_no_ofrece_un_pasaje_que_seria_texto_normativo(cfg):
    texto = _norma("Decreto 2591 de 1991", "10")
    cercana = texto.replace("cualquiera persona", "cualquier persona", 1).replace("Los poderes", "Los apoderados", 1)
    cv = _verificar_cercana(cfg, cercana, f"<p>{texto}</p>")
    assert cv.estado == "rechazada" and cv.pasaje_cercano is None
    assert not any("pasaje más cercano" in m for m in cv.motivos)


def test_pasaje_cercano_sale_solo_de_la_mayoria(cfg):
    cuerpo = _pagina_con_votos("T-200-22", f"{S_INMINENTE} {S_GRAVE} {S_URGENTE}", VOTO_SINTETICO)
    _poner_pagina(cfg, "T-200-22.htm", cuerpo)
    del_voto = VOTO_SINTETICO.replace("sostiene", "afirma").replace("aunque se hayan agotado", "aun cuando se agotaron")
    de_la_mayoria, voto = _verificar(cfg, _p("T-200/22", NEAR_77), _p("T-200/22", del_voto, "c2"))
    assert de_la_mayoria.pasaje_cercano == S_GRAVE
    assert voto.pasaje_cercano is None


def test_sin_pagina_o_sin_sentencia_no_hay_pasaje(cfg):
    no_existe, sin_pagina = _verificar(cfg, _p("T-999 de 2022", NEAR_77), _p("SU-082/95", NEAR_77, "c2"))
    assert no_existe.pasaje_cercano is None and sin_pagina.pasaje_cercano is None


def test_pasaje_cercano_reutiliza_la_pagina_ya_indexada(cfg):
    _poner_pagina(cfg, "T-200-22.htm", _pagina("T-200-22", CUERPO_CERCANO))
    citas._fuente_cercana.cache_clear()
    _verificar(cfg, _p("T-200/22", NEAR_77), _p("T-200/22", NEAR_79, "c2"))
    info = citas._fuente_cercana.cache_info()
    assert info.misses == 1 and info.hits >= 1


def test_pasaje_cercano_c774_real_es_la_oracion_de_la_mayoria(cfg):
    cercana = MAYORIA_C774.replace("institución jurídico procesal que tiene", "figura jurídica que tiene")
    cv = _verificar_fixture(cfg, "C-774-01", cercana)
    assert cv.estado != "ok" and cv.pasaje_cercano == MAYORIA_C774
    ida = _verificar_fixture(cfg, "C-774-01", cv.pasaje_cercano, "c2")
    assert ida.estado == "ok" and ida.seccion == "mayoria"


def test_pasaje_cercano_t1215_real_no_arrastra_la_oracion_siguiente(cfg):
    cercana = PARAFRASIS_T1215.replace("actitudes deshonestas y contradictorias", "conductas deshonestas y contradictorias")
    cv = _verificar_fixture(cfg, "T-1215-03", cercana)
    assert cv.estado != "ok" and cv.pasaje_cercano == PARAFRASIS_T1215
    assert _verificar_fixture(cfg, "T-1215-03", cv.pasaje_cercano, "c2").estado == "ok"


def test_pasaje_mas_cercano_de_cita_vacia_o_sin_fuente_es_none():
    assert citas.pasaje_mas_cercano("", TEXTO_BASE, 25) is None
    assert citas.pasaje_mas_cercano("dos palabras", TEXTO_BASE, 25) is None
    assert citas.pasaje_mas_cercano(TEXTO_BASE, "", 25) is None


def _oracion(k: int, n: int, desde: int = 0) -> str:
    palabras = [f"voz{k}x{i}" for i in range(desde, desde + n)]
    palabras[0] = palabras[0].capitalize()
    return " ".join(palabras) + "."


def _fuente_con(*lineas: str) -> str:
    return "\n".join([_oracion(90, 25), *lineas, _oracion(91, 25)])


def _cercano(cita: str, *lineas: str, minimo: int = 0) -> str | None:
    return citas.pasaje_mas_cercano(cita, _fuente_con(*lineas), minimo)


@pytest.mark.parametrize(
    "largos,conservadas",
    [((40, 60, 60), (1, 2)), ((60, 60, 40), (0, 1)), ((50, 60, 50), (0, 1)), ((60, 60, 60), (0, 1)), ((70, 61, 61), (0, 1))],
)
def test_pasaje_mas_cercano_recorta_a_150_palabras_quitando_el_extremo_con_menos_texto_cubierto(largos, conservadas):
    oraciones = [_oracion(k, n) for k, n in enumerate(largos)]
    assert sum(largos) > citas.MAX_PALABRAS_PASAJE
    esperado = " ".join(oraciones[i] for i in range(conservadas[0], conservadas[1] + 1))
    assert _cercano(" ".join(oraciones), " ".join(oraciones)) == esperado


@pytest.mark.parametrize(
    "largos,esperado",
    [((75, 75), (0, 1)), ((75, 76), (1, 1)), ((76, 75), (0, 0)), ((150,), (0, 0)), ((100, 50), (0, 1))],
)
def test_pasaje_mas_cercano_el_borde_de_150_palabras_no_se_recorta(largos, esperado):
    oraciones = [_oracion(k, n) for k, n in enumerate(largos)]
    resultado = _cercano(" ".join(oraciones), " ".join(oraciones))
    assert resultado == " ".join(oraciones[esperado[0] : esperado[1] + 1])


@pytest.mark.parametrize("palabras,devuelve", [(299, True), (300, True), (301, False), (400, False)])
def test_pasaje_mas_cercano_descarta_una_oracion_unica_de_mas_de_300_palabras(palabras, devuelve):
    larga = _oracion(1, palabras)
    assert (_cercano(larga, larga) == larga) == devuelve
    assert devuelve or _cercano(larga, larga) is None


@pytest.mark.parametrize("cubiertas,se_conserva", [(3, False), (4, False), (5, True), (6, True), (12, True)])
def test_pasaje_mas_cercano_descarta_el_borde_con_menos_de_5_tokens_cubiertos(cubiertas, se_conserva):
    previa, objetivo = _oracion(1, 30), _oracion(2, 30)
    cola_previa = " ".join(previa.split()[-cubiertas:])
    esperado = f"{previa} {objetivo}" if se_conserva else objetivo
    assert _cercano(f"{cola_previa} {objetivo}", f"{previa} {objetivo}") == esperado


@pytest.mark.parametrize("cubiertas,se_conserva", [(4, False), (5, True), (12, True)])
def test_pasaje_mas_cercano_descarta_la_oracion_final_con_menos_de_5_tokens_cubiertos(cubiertas, se_conserva):
    objetivo, siguiente = _oracion(1, 30), _oracion(2, 30)
    cabeza = " ".join(siguiente.split()[:cubiertas])
    esperado = f"{objetivo} {siguiente}" if se_conserva else objetivo
    assert _cercano(f"{objetivo} {cabeza}", f"{objetivo} {siguiente}") == esperado


A_, B_, C_, D_ = (_oracion(k, 20) for k in (11, 12, 13, 14))


@pytest.mark.parametrize(
    "lineas,esperado",
    [
        ((f"{A_} {B_} {C_}",), f"{B_} {C_}"),
        ((f"{A_} {B_}", C_), f"{A_} {B_}"),
        ((A_, f"{B_} {C_}"), f"{B_} {C_}"),
        ((A_, B_, C_), f"{B_} {C_}"),
        ((f"{A_} {B_}", C_, D_), f"{A_} {B_}"),
    ],
)
def test_pasaje_mas_cercano_extiende_primero_hacia_la_oracion_siguiente_de_la_misma_linea(lineas, esperado):
    assert _cercano(B_, *lineas, minimo=30) == esperado


def test_pasaje_mas_cercano_extiende_hacia_la_anterior_si_la_siguiente_esta_en_otra_linea_y_la_anterior_en_la_misma():
    assert _cercano(B_, f"{A_} {B_}", C_, minimo=30) == f"{A_} {B_}"


def test_pasaje_mas_cercano_sin_siguiente_toma_la_anterior_y_sin_ninguna_devuelve_none():
    fuente = f"{A_}\n{B_}"
    assert citas.pasaje_mas_cercano(B_, fuente, 30) == f"{A_} {B_}"
    assert citas.pasaje_mas_cercano(B_, B_, 30) is None
    assert citas.pasaje_mas_cercano(B_, f"{B_}\n{C_}", 30) == f"{B_} {C_}"


@pytest.mark.parametrize(
    "palabra,siguiente,termina",
    [
        ("fin.", "Siguiente", True),
        ("fin.", "siguiente", False),
        ("fin.", "2020 fue", True),
        ("fin.", "«Nueva", True),
        ("fin.", "“Nueva", True),
        ("fin.", "¿Nueva", True),
        ("fin.", "", False),
        ("fin?", "Nueva", True),
        ("fin!", "Nueva", True),
        ("fin,", "Nueva", False),
        ("fin", "Nueva", False),
        ("fin.”", "Nueva", True),
        ("fin.»", "Nueva", True),
        ("fin.)", "Nueva", True),
        ("art.", "Nuevo", False),
        ("Art.", "Nuevo", False),
        ("No.", "Nuevo", False),
        ("Sr.", "Pérez", False),
        ("Sent.", "Nueva", False),
        ("S.A.", "Nueva", False),
        ("D.C.", "Bogotá", False),
        ("a.", "Nueva", False),
        ("1.", "Hechos", False),
        ("12.", "Hechos", False),
        ("123.", "Nueva", True),
        ("1991.", "Nueva", True),
        ("1.500.", "Nueva", True),
        ("...", "Nueva", False),
    ],
)
def test_termina_oracion(palabra, siguiente, termina):
    assert citas._termina_oracion(palabra, siguiente) is termina
