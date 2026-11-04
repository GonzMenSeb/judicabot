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
from tutela2 import formulas, render, salidas, vista
from tutela2.config import Config

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
        "QUOTE_C1",
        "PROBLEMA_JURIDICO_TEXTO",
        "CASO_P1",
        "INSERTAR IMAGEN",
        "CONCLUSION_TEXTO",
    ):
        assert bloque_con(v, fragmento)["origen"] == "modelo", fragmento
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
