from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi.testclient import TestClient

from test_render import HOY, construir_decision, construir_estado
from tutela2 import apoderados, ediciones, formulas, registro_apoderados, render, salidas, vista
from tutela2.config import Config
from tutela2.models import Apoderado, CitaVerificada, Identificacion

PRINCIPAL = "/".join(salidas.PRINCIPAL)


def estado_para(compulsa: bool = True, resultado: str = "REVOCAR") -> dict:
    e = construir_estado(compulsa)
    extra = {} if resultado == "REVOCAR" else {"sustitutiva": None}
    e["decisiones"] = [construir_decision(compulsa, resultado=resultado, **extra).model_dump(mode="json")]
    return e


def generar(tmp_path: Path, tipo: str, gen: str, e: dict) -> tuple[Path, dict]:
    cfg = Config(plantilla_gen=gen)
    if tipo == "borrador":
        docx = render.render_previo(e, cfg, tmp_path / "previo.docx")
    else:
        docx = render.render_fallo(e, cfg, tmp_path / "fallo.docx", hoy=HOY)
    return docx, json.loads((tmp_path / vista.ARCHIVOS[tipo]).read_text(encoding="utf-8"))


def lineas_docx(ruta: Path) -> list:
    doc = Document(ruta)
    salida: list = []
    for hijo in doc.element.body.iterchildren():
        if hijo.tag == qn("w:p"):
            texto = Paragraph(hijo, doc).text
            if texto:
                salida.append(texto)
        elif hijo.tag == qn("w:tbl"):
            for fila in Table(hijo, doc).rows:
                celdas = [c.text for c in fila.cells]
                if any(celdas):
                    salida.append(celdas)
    return salida


def pie_docx(ruta: Path) -> list[str]:
    doc = Document(ruta)
    return [
        p.text
        for p in doc.sections[0].footer.paragraphs
        if p.text.strip() and not p._p.xpath(".//w:fldSimple | .//w:instrText")
    ]


def bloques(v: dict, pie: bool = False) -> list[dict]:
    return [b for p in v["paginas"] for b in p["bloques"] if (b["tipo"] == "pie") == pie]


def texto(b: dict) -> str:
    return "".join(s["texto"] for s in b["segmentos"])


def lineas_vista(v: dict) -> list:
    return [[s["texto"] for s in b["segmentos"]] if b["tipo"] == "tabla" else texto(b) for b in bloques(v)]


def bloque_con(v: dict, fragmento: str) -> dict:
    encontrados = [b for b in bloques(v) if fragmento in texto(b)]
    assert len(encontrados) == 1, fragmento
    return encontrados[0]


CASOS = [
    pytest.param(tipo, gen, compulsa, resultado, id=f"{tipo}-{gen}-{'compulsa' if compulsa else 'sin'}-{resultado}")
    for tipo in ("borrador", "fallo")
    for gen in ("A", "B")
    for compulsa in (True, False)
    for resultado in ("REVOCAR", "CONFIRMAR")
]


@pytest.mark.parametrize("tipo,gen,compulsa,resultado", CASOS)
def test_equivalencia_parrafo_a_parrafo_con_el_docx(tmp_path, tipo, gen, compulsa, resultado):
    docx, v = generar(tmp_path, tipo, gen, estado_para(compulsa, resultado))
    assert lineas_vista(v) == lineas_docx(docx)
    esperado_pie = pie_docx(docx)
    assert esperado_pie
    for pagina in v["paginas"]:
        assert [texto(b) for b in pagina["bloques"] if b["tipo"] == "pie"] == esperado_pie
    assert v["tipo"] == tipo
    assert v["sha256"] == hashlib.sha256(docx.read_bytes()).hexdigest()
    vista.Vista.model_validate(v)


@pytest.mark.parametrize("gen", ["A", "B"])
def test_equivalencia_sin_apertura_ni_consideraciones(tmp_path, gen):
    e = estado_para()
    for clave in ("apertura", "consideraciones", "caso"):
        e.pop(clave)
    for tipo in ("borrador", "fallo"):
        docx, v = generar(tmp_path / tipo, tipo, gen, e)
        assert lineas_vista(v) == lineas_docx(docx)
        assert all(b["origen"] == "plantilla" for b in bloques(v))


def test_fallo_confirmar_y_revocar_cambian_el_resuelve(tmp_path):
    _, revoca = generar(tmp_path / "r", "fallo", "B", estado_para(resultado="REVOCAR"))
    _, confirma = generar(tmp_path / "c", "fallo", "B", estado_para(resultado="CONFIRMAR"))
    primero = lambda v: next(texto(b) for b in bloques(v) if b["tipo"] == "resuelve_numeral")
    assert primero(revoca).startswith("PRIMERO: REVOCAR")
    assert primero(confirma).startswith("PRIMERO: CONFIRMAR")


@pytest.mark.parametrize("tipo", ["borrador", "fallo"])
@pytest.mark.parametrize("gen", ["A", "B"])
def test_ids_estables_unicos_y_tamano(tmp_path, tipo, gen):
    _, uno = generar(tmp_path / "1", tipo, gen, estado_para())
    _, dos = generar(tmp_path / "2", tipo, gen, estado_para())
    uno.pop("sha256"), dos.pop("sha256")
    assert uno == dos
    ids = [b["id"] for p in uno["paginas"] for b in p["bloques"]]
    assert len(ids) == len(set(ids))
    assert (tmp_path / "1" / vista.ARCHIVOS[tipo]).stat().st_size < 60_000


@pytest.mark.parametrize("gen", ["A", "B"])
def test_origen_modelo_y_plantilla(tmp_path, gen):
    _, v = generar(tmp_path, "fallo", gen, estado_para())
    for fragmento in (
        "ANTECEDENTES_HECHOS primer",
        "CONTESTACION_BANCO",
        "SENTENCIA_IMPUGNADA_TEXTO",
        "IMPUGNACION_TEXTO",
        "PROCEDIBILIDAD_P1",
        "Hábeas data",
        "BLOQUE_TEXTO",
        "PROBLEMA_JURIDICO_TEXTO",
        "CASO_P1",
        "INSERTAR IMAGEN",
        "CONCLUSION_TEXTO",
    ):
        assert bloque_con(v, fragmento)["origen"] == "modelo", fragmento
    citados = [b for b in bloques(v) if "QUOTE_C1" in texto(b)]
    assert citados and all(b["origen"] == "modelo" for b in citados)
    for fragmento in (
        formulas.TRANSICION[:60],
        "Procede el Despacho a resolver",
        "HECHOS_REF_COMPULSA",
        "NOTIFÍQUESE",
    ):
        assert bloque_con(v, fragmento)["origen"] == "plantilla", fragmento
    assert all(b["origen"] == "plantilla" for b in bloques(v) if b["tipo"] in ("titulo", "tabla", "resuelve_numeral", "firma"))


@pytest.mark.parametrize("gen", ["A", "B"])
def test_tipos_y_secciones(tmp_path, gen):
    _, v = generar(tmp_path, "fallo", gen, estado_para())
    titulos = [b for b in bloques(v) if b["tipo"] == "titulo"]
    assert [x["id"] for x in titulos] == [e["id"] for e in v["indice"]]
    assert v["indice"][0] == {"id": "asunto", "titulo": "I. ASUNTO"}
    assert all("\t" not in e["titulo"] for e in v["indice"])
    assert all(b["seccion"] is None for b in bloques(v)[:3])
    assert bloques(v)[0]["tipo"] == "encabezado"
    assert bloque_con(v, "Hábeas data")["tipo"] == "encabezado"
    assert bloque_con(v, "QUOTE_C2")["tipo"] == "cita_bloque"
    assert bloque_con(v, "NOTIFÍQUESE")["tipo"] == "firma"
    assert bloque_con(v, "La causa concreta de la restricción.")["tipo"] == "resuelve_numeral"
    assert bloque_con(v, "PRIMERO: ")["tipo"] == "resuelve_numeral"
    assert bloque_con(v, "CASO_P1")["seccion"] == "caso-concreto"
    tabla = [b for b in bloques(v) if b["tipo"] == "tabla"]
    assert tabla and all(len(b["segmentos"]) == 2 and b["segmentos"][0].get("negrita") for b in tabla)


def test_borrador_lista_y_tabla_de_citas(tmp_path):
    _, v = generar(tmp_path, "borrador", "B", estado_para())
    assert bloque_con(v, "ALERTA: alerta de apertura")["tipo"] == "lista"
    cabecera = bloque_con(v, "M.P. (dataset)")
    assert cabecera["tipo"] == "tabla" and [s["texto"] for s in cabecera["segmentos"]][:3] == ["Sentencia", "Estado", "Cobertura"]
    assert all(s.get("negrita") for s in cabecera["segmentos"])
    assert [e["id"] for e in v["indice"]][-2:] == ["informe-de-citas", "alertas-por-nodo"]


@pytest.mark.parametrize("gen", ["A", "B"])
def test_citas_con_estado_y_segmentos(tmp_path, gen):
    e = estado_para()
    e["consideraciones"]["procedibilidad"] += " Otra en [[CITA:zz]]."
    _, v = generar(tmp_path, "borrador", gen, e)
    citas = {c["id"]: c for c in v["citas"]}
    assert citas["c1"] == {
        "id": "c1",
        "texto": "QUOTE_C1 fragmento literal uno.",
        "fuente": "Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas",
        "cobertura": 1.0,
        "estado": "verificada",
        "detalle": None,
        "url": "https://example.test/T-200-22.htm",
    }
    assert (citas["c2"]["estado"], citas["c2"]["cobertura"], citas["c2"]["detalle"]) == ("revisar", 0.6, "Cobertura parcial")
    assert (citas["c3"]["estado"], citas["c3"]["fuente"]) == ("rechazada", "T-999 de 2020")
    assert citas["zz"]["estado"] == "rechazada"

    p1 = bloque_con(v, "PROCEDIBILIDAD_P1")
    referencias = [s for s in p1["segmentos"] if s.get("cita_id")]
    assert [s["cita_id"] for s in referencias] == ["c1", "c1"]
    assert all(s["texto"] == citas["c1"]["fuente"] for s in referencias)
    assert [s for s in p1["segmentos"] if not s.get("cita_id")][1]["texto"] == " y reiterado en "
    desconocida = [s for s in bloque_con(v, "PROCEDIBILIDAD_P2")["segmentos"] if s.get("cita_id")]
    assert desconocida == [{"texto": "⟦CITA NO VERIFICADA: zz⟧", "cita_id": "zz"}]
    rechazada = next(s for s in bloque_con(v, "BLOQUE_TEXTO")["segmentos"] if s.get("cita_id") == "c3")
    assert rechazada["texto"] == "⟦CITA NO VERIFICADA: T-999 de 2020⟧"
    citas_bloque = [b for b in bloques(v) if b["tipo"] == "cita_bloque"]
    assert [b["segmentos"][0]["cita_id"] for b in citas_bloque] == ["c1", "c2"]
    assert all(s.get("cursiva") for b in citas_bloque for s in b["segmentos"])


@pytest.mark.parametrize(
    ("estado", "esperada"),
    [("ok", "https://example.test/T-1-20.htm"), ("alerta", None), ("rechazada", None)],
)
def test_cita_vista_solo_entrega_la_url_de_las_verificadas(estado, esperada):
    cv = CitaVerificada(
        id="c", sentencia_original="T-1 de 2020", texto_citado="q", estado=estado, url="https://example.test/T-1-20.htm"
    )
    assert vista.cita_vista(cv, "T-1 de 2020")["url"] == esperada
    assert vista.cita_vista(cv.model_copy(update={"url": None}), "T-1 de 2020")["url"] is None


@pytest.mark.parametrize("gen", ["A", "B"])
def test_paginacion_determinista(tmp_path, gen):
    _, v = generar(tmp_path, "fallo", gen, estado_para())
    assert len(v["paginas"]) > 1
    for pagina in v["paginas"]:
        cuerpo = [b for b in pagina["bloques"] if b["tipo"] != "pie"]
        assert cuerpo and cuerpo[-1]["tipo"] not in ("titulo", "encabezado")
    assert vista.paginar(bloques(v), gen) == [[b for b in p["bloques"] if b["tipo"] != "pie"] for p in v["paginas"]]


@pytest.mark.parametrize("gen", ["A", "B"])
def test_paginacion_no_deja_titulos_solos_con_parrafos_largos(tmp_path, gen):
    e = estado_para()
    e["consideraciones"]["bloques"][0]["texto"] = "Palabra larga de relleno. " * 120
    e["caso"]["problema_juridico"] = "Otra palabra de relleno. " * 150
    _, v = generar(tmp_path, "fallo", gen, e)
    for pagina in v["paginas"]:
        cuerpo = [b for b in pagina["bloques"] if b["tipo"] != "pie"]
        assert cuerpo and cuerpo[-1]["tipo"] not in ("titulo", "encabezado")


@pytest.mark.parametrize("gen", ["A", "B"])
@pytest.mark.parametrize("tipo", ["borrador", "fallo"])
def test_equivalencia_con_saltos_y_tabulaciones_sin_normalizar(tmp_path, gen, tipo):
    e = estado_para()
    e["consideraciones"]["bloques"][0]["titulo"] = "Título\tcon\r\nsaltos\ny\rretornos"
    decision = e["decisiones"][0]
    decision["ordenes"][0]["literales"] = ["Literal\tuno\r\ncon salto.", "Literal\rdos."]
    e["metadatos"]["accionante"] = "ANA\tEJEMPLO\r\nPRUEBA"
    docx, v = generar(tmp_path, tipo, gen, e)
    assert lineas_vista(v) == lineas_docx(docx)


TIPOS_Y_GEN = [pytest.param(tipo, gen, id=f"{tipo}-{gen}") for tipo in ("borrador", "fallo") for gen in ("A", "B")]


def fuente_de(b: dict) -> tuple[str, int] | None:
    return None if b["fuente"] is None else (b["fuente"]["pieza"], b["fuente"]["parrafo"])


def con_fuente(v: dict) -> list[dict]:
    return [b for b in bloques(v) if b["fuente"] is not None]


def estado_con_prosa_irregular() -> dict:
    e = estado_para()
    ap, cons = e["apertura"], e["consideraciones"]
    ap["antecedentes_hechos"] = (
        "\n\n  Primero en dos\nlíneas.\n\n\n  \n\nSegundo   con   espacios.\r\n\r\n"
        "Tercero [[IMAGEN 1 p. 2 primera captura]] medio [[IMAGEN 2 p. 3 segunda]] cierre.\n \n"
    )
    ap["contestaciones"].append(
        {"entidad": "CLÍNICA MODELO S.A.S.", "texto": "Contestó\nen dos líneas.\n\n\n\nY calló el resto."}
    )
    ap["sentencia_impugnada"] = "Uno\ny dos.\n\nTres."
    ap["impugnacion"] = "Reparo uno.\n\n\n\nReparo dos.\n"
    cons["procedibilidad"] = "Abre con [[CITA:c1]] y sigue.\nMisma línea lógica.\n\n\nCierra sin cita."
    cons["bloques"][0]["texto"] = "Alfa [[CITA:c2]] beta.\n\n[[IMAGEN 5 p. 1 solo imagen]]\n\nOmega."
    cons["bloques"].append({"titulo": "Debido proceso", "reparo_ids": ["R1"], "texto": "Un único\npárrafo largo."})
    return e


def piezas_de(e: dict) -> dict[str, str]:
    ap, cons = e["apertura"], e["consideraciones"]
    piezas = {"apertura.antecedentes_hechos": ap["antecedentes_hechos"]}
    piezas |= {f"apertura.contestaciones.{i}.texto": c["texto"] for i, c in enumerate(ap["contestaciones"])}
    piezas["apertura.sentencia_impugnada"] = ap["sentencia_impugnada"]
    piezas["apertura.impugnacion"] = ap["impugnacion"]
    piezas["consideraciones.procedibilidad"] = cons["procedibilidad"]
    for i, b in enumerate(cons["bloques"]):
        piezas[f"consideraciones.bloques.{i}.titulo"] = b["titulo"]
        piezas[f"consideraciones.bloques.{i}.texto"] = b["texto"]
    return piezas


@pytest.mark.parametrize("tipo,gen", TIPOS_Y_GEN)
def test_fuente_en_la_prosa_del_modelo_de_i_a_v_y_nula_en_el_resto(tmp_path, tipo, gen):
    _, v = generar(tmp_path, tipo, gen, estado_para())
    esperado = [
        (("apertura.antecedentes_hechos", 0), "ANTECEDENTES_HECHOS primer"),
        (("apertura.antecedentes_hechos", 1), "ANTECEDENTES_HECHOS segundo"),
        (("apertura.contestaciones.0.texto", 0), "CONTESTACION_BANCO"),
        (("apertura.sentencia_impugnada", 0), "SENTENCIA_IMPUGNADA_TEXTO"),
        (("apertura.impugnacion", 0), "IMPUGNACION_TEXTO"),
        (("consideraciones.procedibilidad", 0), "PROCEDIBILIDAD_P1"),
        (("consideraciones.procedibilidad", 1), "PROCEDIBILIDAD_P2"),
        (("consideraciones.bloques.0.titulo", 0), "Hábeas data"),
        (("consideraciones.bloques.0.texto", 0), "BLOQUE_TEXTO"),
    ]
    propios = con_fuente(v)
    assert [fuente_de(b) for b in propios] == [f for f, _ in esperado]
    for b, (_, inicio) in zip(propios, esperado):
        assert texto(b).startswith(inicio) and b["origen"] == "modelo"
    assert all("fuente" in b for p in v["paginas"] for b in p["bloques"])
    sin_fuente = [b for b in bloques(v) if b["fuente"] is None]
    assert bloques(v)[0]["tipo"] == "encabezado" and bloques(v)[0]["fuente"] is None
    assert all(b["fuente"] is None for b in bloques(v) if b["origen"] == "plantilla")
    assert all(b["fuente"] is None for b in sin_fuente if b["tipo"] in ("titulo", "tabla", "cita_bloque", "lista", "firma"))
    assert bloque_con(v, "Procede el Despacho a resolver")["fuente"] is None
    citados = [b for b in bloques(v) if b["tipo"] == "cita_bloque"]
    assert len(citados) == (2 if tipo == "borrador" else 3) and all(b["fuente"] is None for b in citados)
    pies = bloques(v, pie=True)
    assert pies and all(b["fuente"] is None for b in pies)
    if tipo == "fallo":
        caso = [b for b in bloques(v) if b["seccion"] == "caso-concreto"]
        assert any("INSERTAR IMAGEN" in texto(b) for b in caso)
        assert all(b["fuente"] is None for b in caso)
        assert all(b["fuente"] is None for b in bloques(v) if b["tipo"] in ("resuelve_numeral", "firma"))
        assert bloque_con(v, "HECHOS_REF_COMPULSA")["fuente"] is None
    vista.Vista.model_validate(v)


@pytest.mark.parametrize("gen", ["A", "B"])
def test_sin_apertura_ni_consideraciones_no_hay_fuente(tmp_path, gen):
    e = estado_para()
    for clave in ("apertura", "consideraciones", "caso"):
        e.pop(clave)
    for tipo in ("borrador", "fallo"):
        _, v = generar(tmp_path / tipo, tipo, gen, e)
        assert all(b["fuente"] is None for p in v["paginas"] for b in p["bloques"])


@pytest.mark.parametrize("tipo,gen", TIPOS_Y_GEN)
def test_fuente_coincide_con_ediciones_parrafos(tmp_path, tipo, gen):
    e = estado_con_prosa_irregular()
    _, v = generar(tmp_path, tipo, gen, e)
    todos = bloques(v)
    piezas = piezas_de(e)
    for pieza, crudo in piezas.items():
        esperados = ediciones.parrafos(crudo)
        assert esperados, pieza
        propios = [i for i, b in enumerate(todos) if b["fuente"] and b["fuente"]["pieza"] == pieza]
        assert {todos[i]["fuente"]["parrafo"] for i in propios} == set(range(len(esperados))), pieza
        for k, parrafo in enumerate(esperados):
            indices = [i for i in propios if todos[i]["fuente"]["parrafo"] == k]
            assert indices == list(range(indices[0], indices[0] + len(indices))), (pieza, k)
            grupo = [todos[i] for i in indices]
            if "[[IMAGEN" in parrafo and "[[CITA" not in parrafo:
                partes = render._IMAGEN.split(parrafo)
                assert [texto(b) for b in grupo] == [
                    f"⟦INSERTAR IMAGEN: {x.strip()}⟧" if i % 2 else x.strip()
                    for i, x in enumerate(partes)
                    if i % 2 or x.strip()
                ], (pieza, k)
            elif "[[CITA" in parrafo:
                assert len(grupo) == 1 and any(s.get("cita_id") for s in grupo[0]["segmentos"]), (pieza, k)
                assert texto(grupo[0]).startswith(parrafo.split("[[")[0])
                assert texto(grupo[0]).endswith(parrafo.rsplit("]]", 1)[1])
            else:
                assert [texto(b) for b in grupo] == [parrafo], (pieza, k)
    secuencia = []
    for b in con_fuente(v):
        if not secuencia or secuencia[-1] != fuente_de(b):
            secuencia.append(fuente_de(b))
    assert secuencia == [(pieza, k) for pieza, crudo in piezas.items() for k in range(len(ediciones.parrafos(crudo)))]


@pytest.mark.parametrize("gen", ["A", "B"])
def test_parrafos_editables_coinciden_con_la_fuente_aunque_la_ia_deje_una_marca_de_imagen_rota(tmp_path, gen):
    e = estado_para()
    pieza = "consideraciones.bloques.0.texto"
    e["consideraciones"]["bloques"][0]["texto"] = "Uno.\n\n[[IMAGEN captura 1\n\nde la historia clinica]]\n\nTres final."
    _, v = generar(tmp_path, "borrador", gen, e)
    en_vista = {b["fuente"]["parrafo"]: texto(b) for b in bloques(v) if b["fuente"] and b["fuente"]["pieza"] == pieza}
    editables = ediciones.respuesta(e, {"version": 1, "piezas": {}, "conflictos": {}})["piezas"][pieza]["parrafos"]
    assert editables == [en_vista[k] for k in sorted(en_vista)]
    assert editables == ["Uno.", "[[IMAGEN captura 1", "de la historia clinica]]", "Tres final."]


@pytest.mark.parametrize("gen", ["A", "B"])
def test_marcas_de_imagen_comparten_la_fuente_del_parrafo_que_parten(tmp_path, gen):
    e = estado_con_prosa_irregular()
    _, v = generar(tmp_path, "borrador", gen, e)
    todos = bloques(v)
    inicio = next(i for i, b in enumerate(todos) if texto(b) == "Tercero")
    grupo = todos[inicio : inicio + 5]
    assert [texto(b) for b in grupo] == [
        "Tercero",
        "⟦INSERTAR IMAGEN: 1 p. 2 primera captura⟧",
        "medio",
        "⟦INSERTAR IMAGEN: 2 p. 3 segunda⟧",
        "cierre.",
    ]
    assert {fuente_de(b) for b in grupo} == {("apertura.antecedentes_hechos", 2)}
    solo = next(b for b in todos if texto(b) == "⟦INSERTAR IMAGEN: 5 p. 1 solo imagen⟧")
    assert fuente_de(solo) == ("consideraciones.bloques.0.texto", 1)
    for id_ in ("c1", "c2"):
        i = next(i for i, b in enumerate(todos) if b["tipo"] == "cita_bloque" and b["segmentos"][0].get("cita_id") == id_)
        assert todos[i]["fuente"] is None
        assert todos[i - 1]["fuente"] is not None
        assert any(s.get("cita_id") == id_ for s in todos[i - 1]["segmentos"])


@pytest.mark.parametrize("gen", ["A", "B"])
def test_titulo_de_bloque_lleva_su_fuente(tmp_path, gen):
    _, v = generar(tmp_path, "borrador", gen, estado_con_prosa_irregular())
    for i, titulo in enumerate(("Hábeas data", "Debido proceso")):
        (b,) = [b for b in bloques(v) if texto(b) == titulo]
        assert b["tipo"] == "encabezado"
        assert b["fuente"] == {"pieza": f"consideraciones.bloques.{i}.titulo", "parrafo": 0}
    otros = [b for b in bloques(v) if b["tipo"] == "encabezado" and texto(b) not in ("Hábeas data", "Debido proceso")]
    assert otros and all(b["fuente"] is None for b in otros)


def test_registro_como_fuente_se_restablece_y_se_guarda_en_la_entrada():
    r = vista.Registro()
    assert r.fuente is None
    dentro = {"pieza": "apertura.impugnacion", "parrafo": 3}
    with r.como(fuente=dentro):
        r.segmento("a", "texto", False, False)
        with r.como(fuente=None):
            assert r.fuente is None
            r.segmento("b", "texto", False, False)
        assert r.fuente == dentro
    r.segmento("c", "texto", False, False)
    assert r.fuente is None
    assert [r.parrafos[k]["fuente"] for k in "abc"] == [dentro, None, None]


def test_openapi_declara_fuente(cliente):
    esquemas = cliente.get("/openapi.json").json()["components"]["schemas"]
    assert esquemas["Fuente"]["required"] == ["pieza", "parrafo"]
    assert esquemas["Fuente"]["properties"]["parrafo"]["type"] == "integer"
    assert "fuente" in esquemas["Bloque"]["properties"] and "fuente" not in esquemas["Bloque"]["required"]


def test_si_falla_la_vista_el_docx_se_genera_y_no_queda_vista_vieja(tmp_path, monkeypatch):
    docx, _ = generar(tmp_path, "fallo", "A", estado_para())
    antes = lineas_docx(docx)

    def roto(*_a, **_k):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(vista, "armar", roto)
    render.render_fallo(estado_para(), Config(plantilla_gen="A"), docx, hoy=HOY)
    assert lineas_docx(docx) == antes
    assert not (tmp_path / "fallo.vista.json").exists()


def test_otros_documentos_no_escriben_vista(tmp_path):
    e = estado_para()
    cfg = Config()
    render.render_informe(e, cfg, tmp_path / "informe.docx")
    render.render_declaracion_ia(e, cfg, tmp_path / "decl.docx", hoy=HOY)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["decl.docx", "informe.docx"]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from tutela2 import rutas_vista, server

    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    rutas_vista._cache.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def caso(tmp_path) -> Path:
    d = tmp_path / "casos" / "caso-1"
    d.mkdir(parents=True)
    return d


def test_ruta_vista_borrador_y_fallo(cliente, caso):
    e = estado_para()
    render.render_previo(e, Config(plantilla_gen="B"), salidas.trabajo(caso) / "previo.docx")
    render.render_fallo(e, Config(plantilla_gen="B"), salidas.principal(caso) / "003FalloSegunda202600999.docx", hoy=HOY)
    for tipo, rel in (("borrador", "trabajo/previo.vista.json"), ("fallo", f"{PRINCIPAL}/fallo.vista.json")):
        r = cliente.get(f"/api/casos/caso-1/vista/{tipo}")
        assert r.status_code == 200 and r.headers["content-type"] == "application/json"
        assert r.json() == json.loads((salidas.raiz(caso) / rel).read_text(encoding="utf-8"))
        assert r.json()["tipo"] == tipo


def test_ruta_vista_404_y_validacion(cliente, caso):
    r = cliente.get("/api/casos/caso-1/vista/borrador")
    assert r.status_code == 404 and r.json()["detail"] == "El borrador aún no existe."
    assert cliente.get("/api/casos/caso-1/vista/fallo").json()["detail"] == "El fallo aún no existe."
    assert cliente.get("/api/casos/caso-1/vista/otro").status_code == 422
    assert cliente.get("/api/casos/no-existe/vista/borrador").status_code == 404
    assert cliente.get("/api/casos/..%2F..%2Fetc/vista/borrador").status_code == 404

    salidas.trabajo(caso).mkdir(parents=True)
    (salidas.trabajo(caso) / "previo.docx").write_bytes(b"PK")
    salidas.principal(caso).mkdir(parents=True)
    (salidas.principal(caso) / "003FalloSegunda202600999.docx").write_bytes(b"PK")
    for tipo in ("borrador", "fallo"):
        r = cliente.get(f"/api/casos/caso-1/vista/{tipo}")
        assert r.status_code == 404 and "no tiene vista previa" in r.json()["detail"]


def test_ruta_vista_no_sigue_enlaces_fuera_de_salidas(cliente, caso, tmp_path):
    fuera = tmp_path / "secreto.json"
    fuera.write_text('{"secreto": true}', encoding="utf-8")
    salidas.trabajo(caso).mkdir(parents=True)
    (salidas.trabajo(caso) / "previo.vista.json").symlink_to(fuera)
    assert cliente.get("/api/casos/caso-1/vista/borrador").status_code == 404


def test_ruta_vista_cache_por_mtime_y_latencia(cliente, caso):
    ruta = salidas.trabajo(caso) / "previo.docx"
    render.render_previo(estado_para(), Config(), ruta)
    url = "/api/casos/caso-1/vista/borrador"
    primera = cliente.get(url).json()
    inicio = time.perf_counter()
    for _ in range(10):
        assert cliente.get(url).status_code == 200
    assert (time.perf_counter() - inicio) / 10 < 0.1

    json_vista = ruta.with_name("previo.vista.json")
    modificado = {**primera, "sha256": "x" * 64}
    json_vista.write_text(json.dumps(modificado), encoding="utf-8")
    st = json_vista.stat()
    os.utime(json_vista, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert cliente.get(url).json()["sha256"] == "x" * 64


def test_ruta_vista_fallo_latencia(cliente, caso):
    render.render_fallo(estado_para(), Config(), salidas.principal(caso) / "003FalloSegunda202600999.docx", hoy=HOY)
    url = "/api/casos/caso-1/vista/fallo"
    inicio = time.perf_counter()
    assert cliente.get(url).status_code == 200
    assert time.perf_counter() - inicio < 0.1


def test_openapi_declara_vista(cliente):
    esquema = cliente.get("/openapi.json").json()
    operacion = esquema["paths"]["/api/casos/{caso_id}/vista/{tipo}"]["get"]
    assert operacion["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Vista"}
    segmento = esquema["components"]["schemas"]["Segmento"]
    assert segmento["required"] == ["texto"]
    assert segmento["properties"]["negrita"] == {"title": "Negrita", "type": "boolean"}
    assert segmento["properties"]["apoderado_id"] == {"title": "Apoderado Id", "type": "string"}


# --- Nombres de apoderados en el borrador previo ---

ABOGADA = ("MARÍA JOSÉ PÉREZ GÓMEZ", "BANCO EJEMPLO S.A.")
ABOGADO = ("CARLOS EDUARDO PINEDA RUIZ", "CLÍNICA MODELO S.A.S.")
HOMONIMO = ("José Fernando Reyes Cuartas", "ANA EJEMPLO PRUEBA")
"""Homónimo del magistrado ponente de la cita c1: su nombre está también dentro de la referencia."""


def id_de(par: tuple[str, str]) -> str:
    return apoderados.id_apoderado(*par)


def identificacion(*pares: tuple[str, str]) -> dict:
    return Identificacion(
        ingesta_sha="i" * 64,
        apoderados=[Apoderado(id=id_de(p), nombre=p[0], parte=p[1]) for p in pares],
    ).model_dump(mode="json")


def estado_con_apoderados() -> dict:
    e = estado_para()
    e["apoderados"] = identificacion(ABOGADA, ABOGADO, HOMONIMO)
    ap = e["apertura"]
    ap["antecedentes_hechos"] += (
        "\n\nANTECEDENTES_APODERADA: el banco actuó por medio de la doctora Maria Jose\n   Perez Gomez, sin tildes."
    )
    ap["contestaciones"][0]["texto"] = (
        "CONTESTACION_BANCO: la entidad, mediante su apoderada judicial, la doctora María José Pérez Gómez, "
        "guardó absoluto silencio."
    )
    ap["sentencia_impugnada"] = (
        "SENTENCIA_IMPUGNADA_TEXTO. El juez oyó al doctor CARLOS EDUARDO PINEDA, apoderado de la vinculada, "
        "y no al señor Carlos Eduardo Pineda Restrepo ni a maría josé pérez gómez."
    )
    ap["impugnacion"] = "IMPUGNACION_TEXTO. El doctor José Fernando Reyes Cuartas sustentó el recurso."
    return e


def marcas(v: dict) -> list[tuple[str, str]]:
    return [(s["texto"], s["apoderado_id"]) for b in bloques(v) for s in b["segmentos"] if "apoderado_id" in s]


def partes_docx(ruta: Path) -> dict[str, bytes]:
    """El contenido de cada parte del docx; los bytes del zip llevan la hora de escritura de cada parte."""
    with zipfile.ZipFile(ruta) as z:
        return {n: z.read(n) for n in z.namelist()}


@pytest.mark.parametrize("gen", ["A", "B"])
def test_el_borrador_marca_los_nombres_de_los_apoderados(tmp_path, gen):
    docx, v = generar(tmp_path, "borrador", gen, estado_con_apoderados())
    assert marcas(v) == [
        ("Maria Jose Perez Gomez", id_de(ABOGADA)),
        ("María José Pérez Gómez", id_de(ABOGADA)),
        ("CARLOS EDUARDO PINEDA", id_de(ABOGADO)),
        ("José Fernando Reyes Cuartas", id_de(HOMONIMO)),
    ]
    assert bloque_con(v, "CONTESTACION_BANCO")["segmentos"] == [
        {"texto": "CONTESTACION_BANCO: la entidad, mediante su apoderada judicial, la doctora "},
        {"texto": "María José Pérez Gómez", "apoderado_id": id_de(ABOGADA)},
        {"texto": ", guardó absoluto silencio."},
    ]
    assert bloque_con(v, "CONTESTACION_BANCO")["origen"] == "modelo"
    assert lineas_vista(v) == lineas_docx(docx)
    assert v["sha256"] == hashlib.sha256(docx.read_bytes()).hexdigest()
    vista.Vista.model_validate(v)


@pytest.mark.parametrize("gen", ["A", "B"])
def test_un_nombre_dentro_de_una_cita_queda_en_la_cita(tmp_path, gen):
    _, v = generar(tmp_path, "borrador", gen, estado_con_apoderados())
    p1 = bloque_con(v, "PROCEDIBILIDAD_P1")
    assert [s["cita_id"] for s in p1["segmentos"] if "cita_id" in s] == ["c1", "c1"]
    assert all("José Fernando Reyes Cuartas" in s["texto"] for s in p1["segmentos"] if "cita_id" in s)
    assert not any("apoderado_id" in s for s in p1["segmentos"])
    assert all(not ("cita_id" in s and "apoderado_id" in s) for b in bloques(v) for s in b["segmentos"])


@pytest.mark.parametrize("gen", ["A", "B"])
def test_las_marcas_no_cambian_el_docx_el_texto_ni_las_citas(tmp_path, gen):
    e = estado_con_apoderados()
    docx_con, con = generar(tmp_path / "con", "borrador", gen, e)
    docx_sin, sin = generar(tmp_path / "sin", "borrador", gen, {**e, "apoderados": None})
    assert marcas(con) and not marcas(sin)
    assert partes_docx(docx_con) == partes_docx(docx_sin)
    assert lineas_vista(con) == lineas_vista(sin)
    assert con["citas"] == sin["citas"] and con["indice"] == sin["indice"]
    assert sorted(c["id"] for c in con["citas"]) == ["c1", "c2", "c3"]
    assert [[b["id"] for b in p["bloques"]] for p in con["paginas"]] == [[b["id"] for b in p["bloques"]] for p in sin["paginas"]]


@pytest.mark.parametrize("gen", ["A", "B"])
def test_el_fallo_no_marca_apoderados(tmp_path, gen):
    e = estado_con_apoderados()
    docx_con, con = generar(tmp_path / "con", "fallo", gen, e)
    docx_sin, sin = generar(tmp_path / "sin", "fallo", gen, {k: v for k, v in e.items() if k != "apoderados"})
    assert not marcas(con)
    assert partes_docx(docx_con) == partes_docx(docx_sin)
    con.pop("sha256"), sin.pop("sha256")
    assert con == sin


@pytest.mark.parametrize(
    "valor",
    [
        pytest.param(None, id="ninguna"),
        pytest.param({}, id="vacia"),
        pytest.param(Identificacion(alertas=["ALERTA: la identificación falló."]).model_dump(mode="json"), id="fallida"),
        pytest.param({"apoderados": [{"id": "ap-0000000000"}]}, id="invalida"),
    ],
)
def test_sin_identificacion_valida_el_borrador_sale_sin_marcas(tmp_path, valor):
    e = estado_con_apoderados()
    e["apoderados"] = valor
    docx, v = generar(tmp_path, "borrador", "B", e)
    assert not marcas(v)
    assert lineas_vista(v) == lineas_docx(docx)


def test_revisar_un_apoderado_no_toca_el_borrador_ni_su_vista(cliente, caso, monkeypatch):
    from tutela2 import rutas_apoderados

    e = estado_con_apoderados()
    ruta = salidas.trabajo(caso) / "previo.docx"
    render.render_previo(e, Config(plantilla_gen="B"), ruta)
    archivos = (ruta, ruta.with_name(vista.ARCHIVOS["borrador"]))
    antes = [p.read_bytes() for p in archivos]
    url_vista = "/api/casos/caso-1/vista/borrador"
    sha = cliente.get(url_vista).json()["sha256"]
    assert marcas(cliente.get(url_vista).json())

    monkeypatch.setattr(rutas_apoderados, "_estado_del_caso", lambda caso_dir: ("esperando_decision", {}))
    registro_apoderados.espejar(caso, Identificacion.model_validate(e["apoderados"]))
    consulta = registro_apoderados.ConsultaVigencia(estado="no_vigente", origen="manual", consultado_en=registro_apoderados.ahora())
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({"52000013": consulta}))
    url = "/api/casos/caso-1/apoderados"
    ap = next(a for a in cliente.get(url).json()["apoderados"] if a["id"] == id_de(ABOGADA))
    r = cliente.put(f"{url}/{ap['id']}/revision", json={"revisado": True, "huella": ap["huella"]})
    assert r.status_code == 200 and r.json()["revisado"] is True

    assert [p.read_bytes() for p in archivos] == antes
    assert cliente.get(url_vista).json()["sha256"] == sha


def _datos_vista() -> dict:
    return {"tipo": "borrador", "sha256": "0" * 64, "paginas": [], "citas": [], "indice": []}


def test_guardar_limpia_el_temporal_si_falla_el_reemplazo(tmp_path, monkeypatch):
    destino = tmp_path / "previo.vista.json"
    vista.guardar(_datos_vista(), destino)
    anterior = destino.read_bytes()

    def falla(origen, ruta):
        raise OSError("disco lleno")

    monkeypatch.setattr(vista.os, "replace", falla)
    with pytest.raises(OSError):
        vista.guardar({**_datos_vista(), "sha256": "1" * 64}, destino)
    assert destino.read_bytes() == anterior
    assert [p.name for p in tmp_path.iterdir()] == ["previo.vista.json"]


def test_guardar_limpia_el_temporal_si_falla_a_mitad_de_la_escritura(tmp_path, monkeypatch):
    destino = tmp_path / "previo.vista.json"

    def a_medias(self, texto, **kw):
        self.write_bytes(texto.encode("utf-8")[:5])
        raise OSError("se cortó")

    monkeypatch.setattr(Path, "write_text", a_medias)
    with pytest.raises(OSError):
        vista.guardar(_datos_vista(), destino)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "oculto",
    [
        "trabajo/previo.vista.json",
        "trabajo/.previo.vista.json.tmp",
        "02SegundaInstancia/C01Principal/fallo.vista.json",
        "02SegundaInstancia/C01Principal/.fallo.vista.json.tmp",
        "trabajo/previo.vista.json.bak",
    ],
)
def test_salidas_listar_oculta_las_vistas_y_sus_temporales(tmp_path, oculto):
    for rel in (oculto, "trabajo/previo.docx", "trabajo/datos.json", "trabajo/vista.json.txt"):
        destino = salidas.raiz(tmp_path) / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"x")
    assert salidas.listar(tmp_path) == ["trabajo/datos.json", "trabajo/previo.docx", "trabajo/vista.json.txt"]
    with zipfile.ZipFile(io.BytesIO(salidas.zip_bytes(tmp_path))) as z:
        assert sorted(z.namelist()) == ["trabajo/datos.json", "trabajo/previo.docx", "trabajo/vista.json.txt"]
