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


def _pagina(ident: str, cuerpo: str = PARRAFO_HTML, encoding: str = "cp1252") -> bytes:
    relleno = "".join(f"<p>Fundamento {i} alfa{i} beta{i} gamma{i} delta{i} epsilon{i}</p>\r\n" for i in range(500))
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
    assert larga.estado == "ok" and larga.cobertura == 1.0
    assert corta.estado == "ok" and corta.cobertura == 1.0
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
