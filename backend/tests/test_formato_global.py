from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import get_origin
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from tutela2 import config as cfgmod
from tutela2 import expediente, formato_global, render, salidas, server
from tutela2.config import Config, Despacho
from tutela2.documentos import correos
from tutela2.formato_global import CATALOGO, DOCUMENTOS
from tutela2.models import Ingesta, Metadatos
from tutela2.rutas_formato import MAX_LINEA, MAX_LINEAS, MAX_TEXTO, DespachoEntrada

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
IDS_DOCUMENTOS = {d.id for d in DOCUMENTOS}
PATRONES = {
    "fallo": "02SegundaInstancia/C01Principal/*FalloSegunda*.docx",
    "auto": "02SegundaInstancia/C01Principal/*AutoAsume*.docx",
    "formato": "02SegundaInstancia/C01Principal/*FormatoCalificacion*.docx",
    "oficio": "por_radicar/OficioRemite*.docx",
    "correos": "borradores_correo/*.docx",
    "informe": "trabajo/informe_verificacion.docx",
    "declaracion_ia": "trabajo/declaracion_ia.docx",
    "requerimiento": "trabajo/requerimiento.docx",
}


def parrafos_docx(ruta: Path) -> list[str]:
    salida: list[str] = []
    with zipfile.ZipFile(ruta) as z:
        for nombre in sorted(z.namelist()):
            if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", nombre):
                raiz = ET.fromstring(z.read(nombre))
                salida += ["".join(t.text or "" for t in p.iter(W + "t")) for p in raiz.iter(W + "p")]
    return salida


def centinela(clave: str, tipo: str) -> list[str]:
    base = f"ZZ_{clave.upper()}"
    return [f"{base}_1_ZZ", f"{base}_2_ZZ"] if tipo == "lista" else [f"{base}_ZZ"]


def despacho_centinela() -> Despacho:
    return Despacho(**{c.clave: (lineas if c.tipo == "lista" else lineas[0]) for c in CATALOGO for lineas in [centinela(c.clave, c.tipo)]})


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture(scope="module")
def sintetico(tmp_path_factory):
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        pytest.skip("requiere soffice y pdftotext")
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "caso_sintetico.py"
    spec = importlib.util.spec_from_file_location("caso_sintetico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    carpeta = tmp_path_factory.mktemp("formato_sintetico")
    modulo.generar(carpeta)
    modulo.preparar(carpeta, "fake")
    decision = {
        **modulo.DECISION_POR_DEFECTO,
        "compulsa": {"organo": "Comisión Seccional de Disciplina Judicial de Antioquia", "respecto_de": "el funcionario X"},
        "fecha_fallo": "2026-11-03",
        "fecha_oficio": "2026-11-03",
    }
    resultados = modulo.ejecutar(carpeta, decision)
    assert resultados["decidir"]["estado"] == "terminado", resultados["decidir"]["error"]

    from tutela2 import api

    cfg = cfgmod.cargar(carpeta, entorno=False)
    with api._grafo(carpeta, cfg) as (g, hilo):
        estado = dict(g.get_state(hilo).values)
    return carpeta, estado


def generar(sintetico, despacho: Despacho, plantilla: str) -> dict[str, str]:
    carpeta, estado = sintetico
    cfg = Config(despacho=despacho, plantilla_gen=plantilla)
    expediente.generar_final(carpeta, estado, cfg)
    raiz = salidas.raiz(carpeta)
    render.render_requerimiento(Ingesta.model_validate(estado["ingesta"]), cfg, salidas.trabajo(carpeta) / "requerimiento.docx")
    textos = {}
    for doc, patron in PATRONES.items():
        archivos = sorted(raiz.glob(patron))
        assert archivos, f"no se generó {doc}"
        textos[doc] = "\n".join("\n".join(parrafos_docx(f)) for f in archivos)
    assert len(sorted(raiz.glob(PATRONES["correos"]))) == 3
    return textos


def test_catalogo_cubre_exactamente_los_campos_del_despacho() -> None:
    claves = [c.clave for c in CATALOGO]
    assert len(claves) == len(set(claves))
    assert set(claves) == set(Despacho.model_fields)
    for c in CATALOGO:
        assert c.etiqueta.strip() and c.ayuda.strip() and c.grupo.strip()
        assert c.documentos and set(c.documentos) <= IDS_DOCUMENTOS
        assert (c.tipo == "lista") == (Despacho.model_fields[c.clave].annotation == list[str])


def test_centinelas_aparecen_solo_en_los_documentos_que_declara_el_catalogo(sintetico) -> None:
    despacho = despacho_centinela()
    encontrados: dict[str, dict[str, set[str]]] = {}
    for plantilla in ("A", "B"):
        textos = generar(sintetico, despacho, plantilla)
        por_campo: dict[str, set[str]] = {}
        for c in CATALOGO:
            lineas = centinela(c.clave, c.tipo)
            donde = set()
            for doc, texto in textos.items():
                presentes = [s in texto for s in lineas]
                assert all(presentes) or not any(presentes), f"{c.clave} aparece incompleto en {doc} ({plantilla})"
                if all(presentes):
                    donde.add(doc)
            por_campo[c.clave] = donde
        encontrados[plantilla] = por_campo

    for c in CATALOGO:
        union = encontrados["A"][c.clave] | encontrados["B"][c.clave]
        assert union == set(c.documentos), f"{c.clave}: el catálogo dice {sorted(c.documentos)}, los documentos {sorted(union)}"
    internos = {"informe", "declaracion_ia", "requerimiento"}
    assert encontrados["A"]["pie"] == {"fallo"} | internos and encontrados["B"]["pie"] == internos
    assert encontrados["B"]["pie_fallo"] == {"fallo"} and encontrados["A"]["pie_fallo"] == set()


def test_textos_por_defecto_identicos_a_los_anteriores(sintetico) -> None:
    carpeta, _ = sintetico
    d = Despacho()
    assert d.nombre_corto == d.nombre.replace(" DE MEDELLÍN", "")
    generar(sintetico, d, "B")
    raiz = salidas.raiz(carpeta)

    for patron in (PATRONES["auto"], PATRONES["oficio"]):
        (archivo,) = raiz.glob(patron)
        assert d.nombre.replace(" DE MEDELLÍN", "") in parrafos_docx(archivo)

    firma = [d.escribiente, d.cargo_escribiente, "Juzgado 3 Penal del Circuito con Funciones", "de Conocimiento de Medellín", d.correo, d.telefono_correo]
    for archivo in raiz.glob(PATRONES["correos"]):
        parrafos = parrafos_docx(archivo)
        i = parrafos.index(firma[0])
        assert parrafos[i : i + len(firma)] == firma


def test_despacho_hereda_nombre_corto_de_configuraciones_anteriores() -> None:
    assert Despacho.model_validate({"nombre": "JUZGADO X DE MEDELLÍN"}).nombre_corto == "JUZGADO X"
    assert Despacho.model_validate({"nombre": "JUZGADO X DE BOGOTÁ"}).nombre_corto == "JUZGADO X DE BOGOTÁ"
    assert Despacho.model_validate({"nombre": "JUZGADO X DE MEDELLÍN", "nombre_corto": "OTRO"}).nombre_corto == "OTRO"
    assert Despacho.model_validate({}).nombre_corto == Despacho().nombre_corto
    antiguo = json.loads(Config().model_dump_json())
    for clave in ("nombre_corto", "firma_correo"):
        del antiguo["despacho"][clave]
    assert Config.model_validate(antiguo).despacho == Despacho()


def test_get_sin_archivo_devuelve_valores_por_defecto(cliente) -> None:
    r = cliente.get("/api/formato")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["valores"] == Despacho().model_dump()
    assert cuerpo["plantilla_gen"] == Config().plantilla_gen
    assert [c["clave"] for c in cuerpo["campos"]] == [c.clave for c in CATALOGO]
    assert {"clave", "etiqueta", "ayuda", "tipo", "grupo", "documentos"} == set(cuerpo["campos"][0])
    assert [d["id"] for d in cuerpo["documentos"]] == [
        "fallo", "auto", "oficio", "correos", "formato", "informe", "declaracion_ia", "requerimiento",
    ]


def test_put_guarda_y_get_devuelve_lo_guardado(cliente, tmp_path) -> None:
    valores = despacho_centinela().model_dump()
    r = cliente.put("/api/formato", json={"valores": valores, "plantilla_gen": "A"})
    assert r.status_code == 200
    assert r.json()["valores"] == valores and r.json()["plantilla_gen"] == "A"
    assert cliente.get("/api/formato").json() == r.json()
    guardado = json.loads((tmp_path / "casos" / ".formato.json").read_text(encoding="utf-8"))
    assert guardado == {"valores": valores, "plantilla_gen": "A"}


def test_put_invalido_devuelve_422_con_errores_por_campo_y_no_escribe(cliente, tmp_path) -> None:
    archivo = tmp_path / "casos" / ".formato.json"
    valores = Despacho().model_dump()
    r = cliente.put("/api/formato", json={"valores": {**valores, "juez": 5, "pie_fallo": "una sola línea"}, "plantilla_gen": "C"})
    assert r.status_code == 422
    errores = {e["campo"]: e["mensaje"] for e in r.json()["detail"]["errores"]}
    assert set(errores) == {"juez", "pie_fallo", "plantilla_gen"}
    assert all(isinstance(m, str) and m for m in errores.values())
    assert not archivo.exists()

    r = cliente.put("/api/formato", json={"plantilla_gen": "A"})
    assert r.status_code == 422
    assert [e["campo"] for e in r.json()["detail"]["errores"]] == ["valores"]
    assert not archivo.exists()

    r = cliente.put("/api/formato", content=b"{x", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"] == [{"campo": "", "mensaje": "no es un JSON válido."}]
    assert not archivo.exists()


def test_put_invalido_conserva_el_formato_anterior(cliente) -> None:
    valores = Despacho(juez="PRIMERO").model_dump()
    assert cliente.put("/api/formato", json={"valores": valores, "plantilla_gen": "A"}).status_code == 200
    assert cliente.put("/api/formato", json={"valores": {**valores, "ciudad": None}, "plantilla_gen": "B"}).status_code == 422
    r = cliente.get("/api/formato").json()
    assert r["valores"]["juez"] == "PRIMERO" and r["plantilla_gen"] == "A"


def test_escritura_atomica_nunca_deja_el_archivo_a_medias(cliente, tmp_path, monkeypatch) -> None:
    casos = tmp_path / "casos"
    archivo = casos / ".formato.json"
    anterior = Despacho(juez="ANTERIOR")
    formato_global.guardar_formato(anterior, "B")
    contenido_anterior = archivo.read_text(encoding="utf-8")

    vistos = {}
    real = os.replace

    def espiar(origen, destino):
        vistos["temporal"] = json.loads(Path(origen).read_text(encoding="utf-8"))
        vistos["destino_antes"] = Path(destino).read_text(encoding="utf-8")
        real(origen, destino)

    monkeypatch.setattr(os, "replace", espiar)
    formato_global.guardar_formato(Despacho(juez="NUEVO"), "A")
    assert vistos["temporal"]["valores"]["juez"] == "NUEVO" and vistos["temporal"]["plantilla_gen"] == "A"
    assert vistos["destino_antes"] == contenido_anterior
    assert json.loads(archivo.read_text(encoding="utf-8"))["valores"]["juez"] == "NUEVO"

    contenido_nuevo = archivo.read_text(encoding="utf-8")

    def fallar(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", fallar)
    with pytest.raises(OSError):
        formato_global.guardar_formato(Despacho(juez="PERDIDO"), "B")
    assert archivo.read_text(encoding="utf-8") == contenido_nuevo
    assert sorted(p.name for p in casos.iterdir()) == [".formato.json"]


def test_archivo_corrupto_se_ignora_y_no_rompe_get_ni_la_copia(cliente, tmp_path) -> None:
    casos = tmp_path / "casos"
    casos.mkdir()
    (casos / ".formato.json").write_text("{no es json", encoding="utf-8")
    assert cliente.get("/api/formato").json()["valores"] == Despacho().model_dump()
    caso = casos / "uno"
    caso.mkdir()
    formato_global.copiar_a_caso(caso)
    assert not (caso / "config.json").exists()

    (casos / ".formato.json").write_text(json.dumps({"valores": {"juez": 7}, "plantilla_gen": "B"}), encoding="utf-8")
    assert formato_global.leer_formato() is None
    (casos / ".formato.json").write_text(json.dumps({"valores": {}, "plantilla_gen": "Z"}), encoding="utf-8")
    assert formato_global.leer_formato() is None


def test_copiar_a_caso_sin_formato_no_hace_nada(cliente, tmp_path) -> None:
    caso = tmp_path / "casos" / "uno"
    caso.mkdir(parents=True)
    formato_global.copiar_a_caso(caso)
    assert list(caso.iterdir()) == []


def test_copiar_a_caso_escribe_despacho_y_plantilla_y_conserva_el_resto(cliente, tmp_path) -> None:
    caso = tmp_path / "casos" / "uno"
    caso.mkdir(parents=True)
    previa = Config(max_intentos=7)
    previa.llm.modelo = "claude-haiku-5-5"
    cfgmod.guardar(caso, previa)
    despacho = despacho_centinela()
    formato_global.guardar_formato(despacho, "A")

    formato_global.copiar_a_caso(caso)

    cfg = cfgmod.cargar(caso, entorno=False)
    assert cfg.despacho == despacho and cfg.plantilla_gen == "A"
    assert cfg.max_intentos == 7 and cfg.llm.modelo == "claude-haiku-5-5"


def test_el_formato_solo_se_aplica_a_casos_nuevos(cliente, tmp_path) -> None:
    casos = tmp_path / "casos"
    primero = Despacho(juez="PRIMER JUEZ")
    assert cliente.put("/api/formato", json={"valores": primero.model_dump(), "plantilla_gen": "A"}).status_code == 200

    existente = casos / "existente"
    existente.mkdir()
    formato_global.copiar_a_caso(existente)
    antes = (existente / "config.json").read_bytes()

    segundo = Despacho(juez="SEGUNDO JUEZ")
    assert cliente.put("/api/formato", json={"valores": segundo.model_dump(), "plantilla_gen": "B"}).status_code == 200

    assert (existente / "config.json").read_bytes() == antes
    r = cliente.get("/api/casos/existente/config").json()
    assert r["despacho"]["juez"] == "PRIMER JUEZ" and r["plantilla_gen"] == "A"

    nuevo = casos / "nuevo"
    nuevo.mkdir()
    formato_global.copiar_a_caso(nuevo)
    cfg = cfgmod.cargar(nuevo, entorno=False)
    assert cfg.despacho.juez == "SEGUNDO JUEZ" and cfg.plantilla_gen == "B"


def test_documentos_de_trabajo_usan_solo_los_campos_conocidos(sintetico) -> None:
    carpeta, estado = sintetico
    despacho = despacho_centinela()
    cfg = Config(despacho=despacho, plantilla_gen="B")
    trabajo = salidas.trabajo(carpeta)
    render.render_previo(estado, cfg, trabajo / "previo.docx")
    render.render_informe(estado, cfg, trabajo / "informe_verificacion.docx")
    render.render_declaracion_ia(estado, cfg, trabajo / "declaracion_ia.docx")
    render.render_requerimiento(Ingesta.model_validate(estado["ingesta"]), cfg, trabajo / "requerimiento.docx")

    def usados(nombre: str) -> set[str]:
        texto = "\n".join(parrafos_docx(trabajo / nombre))
        return {c.clave for c in CATALOGO if all(s in texto for s in centinela(c.clave, c.tipo))}

    def declarados(documento: str) -> set[str]:
        return {c.clave for c in CATALOGO if documento in c.documentos}

    assert usados("previo.docx") <= declarados("fallo")
    assert usados("informe_verificacion.docx") == declarados("informe") == {"nombre", "pie"}
    assert usados("declaracion_ia.docx") == declarados("declaracion_ia") == {"ciudad", "juez", "nombre", "pie"}
    assert usados("requerimiento.docx") == declarados("requerimiento") == {"ciudad", "correo", "nombre_cuerpo", "pie"}


def test_openapi_declara_las_rutas_de_formato(cliente) -> None:
    esquema = cliente.get("/openapi.json").json()
    ruta = esquema["paths"]["/api/formato"]
    assert set(ruta) == {"get", "put"}
    assert ruta["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/FormatoRespuesta")
    assert ruta["put"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/FormatoCuerpo")
    assert ruta["put"]["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/FormatoErrores")
    assert {"nombre_corto", "firma_correo"} <= set(esquema["components"]["schemas"]["Despacho"]["properties"])


def test_catalogo_avisa_de_los_textos_fijos_de_los_documentos() -> None:
    ayuda = {c.clave: c.ayuda for c in CATALOGO}
    assert "«MEDELLÍN»" in ayuda["ciudad"] and "fijo" in ayuda["ciudad"]
    assert correos.PARA_REPARTO in ayuda["correo"] and "fijo" in ayuda["correo"]


CON_CONTROL = {
    "nombre": "JUZGADO\x01 X\x0b",
    "juez": "\x00JUEZ\x1f",
    "ciudad": "Medel\x0clín",
    "correo": "a\x08@b.co",
    "pie": "Pie\x01",
    "pie_fallo": ["L\x01ínea", "Otra\x0b"],
    "firma_correo": ["\x1fFirma"],
}


def test_despacho_descarta_caracteres_de_control_y_conserva_el_resto() -> None:
    d = Despacho.model_validate({**CON_CONTROL, "nombre_cuerpo": "Tab\ty\nsalto\rok", "pie_auto": ["a￾b", "c\ud800d", "e￿"]})
    assert d.nombre == "JUZGADO X" and d.juez == "JUEZ" and d.ciudad == "Medellín" and d.correo == "a@b.co"
    assert d.pie == "Pie" and d.pie_fallo == ["Línea", "Otra"] and d.firma_correo == ["Firma"]
    assert d.nombre_cuerpo == "Tab\ty\nsalto\rok" and d.pie_auto == ["ab", "cd", "e"]
    assert d.nombre_corto == "JUZGADO X"
    assert Despacho.model_validate(Despacho().model_dump()) == Despacho()


def test_put_con_caracteres_de_control_los_limpia_y_el_render_no_falla(cliente, tmp_path) -> None:
    valores = {**Despacho().model_dump(), **CON_CONTROL}
    r = cliente.put("/api/formato", json={"valores": valores, "plantilla_gen": "B"})
    assert r.status_code == 200
    guardado = r.json()["valores"]
    assert guardado["nombre"] == "JUZGADO X" and guardado["pie_fallo"] == ["Línea", "Otra"]
    assert cliente.get("/api/formato").json()["valores"] == guardado

    despacho, plantilla = formato_global.vigente()
    ing = Ingesta(documentos=[], metadatos=Metadatos(), faltantes=[])
    ruta = render.render_requerimiento(ing, Config(despacho=despacho, plantilla_gen=plantilla), tmp_path / "r.docx")
    texto = "\n".join(parrafos_docx(ruta))
    assert "Medellín" in texto and "a@b.co" in texto and "Pie" in texto
    assert not re.search("[\x00-\x08\x0b\x0c\x0e-\x1f]", texto)


def test_put_exige_todos_los_campos_del_despacho(cliente, tmp_path) -> None:
    archivo = tmp_path / "casos" / ".formato.json"
    completo = Despacho().model_dump()
    parcial = {k: v for k, v in completo.items() if k not in ("juez", "pie_auto")}
    r = cliente.put("/api/formato", json={"valores": parcial, "plantilla_gen": "A"})
    assert r.status_code == 422
    assert {e["campo"]: e["mensaje"] for e in r.json()["detail"]["errores"]} == {"juez": "es obligatorio.", "pie_auto": "es obligatorio."}
    r = cliente.put("/api/formato", json={"valores": {"juez": "SOLO"}, "plantilla_gen": "A"})
    assert r.status_code == 422 and len(r.json()["detail"]["errores"]) == len(completo) - 1
    assert not archivo.exists()


def test_put_rechaza_claves_extra_en_el_cuerpo_y_en_los_valores(cliente, tmp_path) -> None:
    archivo = tmp_path / "casos" / ".formato.json"
    completo = Despacho().model_dump()
    r = cliente.put("/api/formato", json={"valores": {**completo, "juzgado": "x"}, "plantilla_gen": "A", "otro": 1})
    assert r.status_code == 422
    assert {e["campo"]: e["mensaje"] for e in r.json()["detail"]["errores"]} == {
        "juzgado": "no es un campo reconocido.",
        "otro": "no es un campo reconocido.",
    }
    assert not archivo.exists()


@pytest.mark.parametrize(
    "campo, valor, campo_error, mensaje",
    [
        ("juez", "x" * (MAX_TEXTO + 1), "juez", f"debe tener como máximo {MAX_TEXTO} caracteres."),
        ("pie_fallo", ["x"] * (MAX_LINEAS + 1), "pie_fallo", f"debe tener como máximo {MAX_LINEAS} elementos."),
        ("pie_auto", ["ok", "x" * (MAX_LINEA + 1)], "pie_auto.1", f"debe tener como máximo {MAX_LINEA} caracteres."),
    ],
)
def test_put_limita_el_largo_de_textos_y_listas(cliente, tmp_path, campo, valor, campo_error, mensaje) -> None:
    r = cliente.put("/api/formato", json={"valores": {**Despacho().model_dump(), campo: valor}, "plantilla_gen": "A"})
    assert r.status_code == 422
    assert r.json()["detail"]["errores"] == [{"campo": campo_error, "mensaje": mensaje}]
    assert not (tmp_path / "casos" / ".formato.json").exists()


def test_put_acepta_los_limites_exactos_y_mide_despues_de_limpiar_control(cliente) -> None:
    valores = {
        **Despacho().model_dump(),
        "juez": "x" * MAX_TEXTO + "\x01",
        "pie_fallo": ["y" * MAX_LINEA] * MAX_LINEAS,
    }
    r = cliente.put("/api/formato", json={"valores": valores, "plantilla_gen": "B"})
    assert r.status_code == 200
    assert r.json()["valores"]["juez"] == "x" * MAX_TEXTO and len(r.json()["valores"]["pie_fallo"]) == MAX_LINEAS


def test_get_y_put_hacen_round_trip_con_los_valores_por_defecto_y_los_guardados(cliente) -> None:
    for _ in range(2):
        leido = cliente.get("/api/formato").json()
        r = cliente.put("/api/formato", json={"valores": leido["valores"], "plantilla_gen": leido["plantilla_gen"]})
        assert r.status_code == 200 and r.json() == leido
    valores = despacho_centinela().model_dump()
    assert cliente.put("/api/formato", json={"valores": valores, "plantilla_gen": "A"}).status_code == 200
    leido = cliente.get("/api/formato").json()
    assert cliente.put("/api/formato", json={"valores": leido["valores"], "plantilla_gen": leido["plantilla_gen"]}).json() == leido


def test_despacho_de_entrada_declara_los_mismos_campos_que_despacho() -> None:
    assert list(DespachoEntrada.model_fields) == list(Despacho.model_fields)
    assert all(f.is_required() for f in DespachoEntrada.model_fields.values())
    def tipos(modelo) -> dict:
        return {k: get_origin(f.annotation) or f.annotation for k, f in modelo.model_fields.items()}

    assert tipos(DespachoEntrada) == tipos(Despacho)
    assert DespachoEntrada.model_validate(Despacho().model_dump()).model_dump() == Despacho().model_dump()


def test_openapi_declara_el_cuerpo_estricto_de_formato(cliente) -> None:
    esquemas = cliente.get("/openapi.json").json()["components"]["schemas"]
    entrada = esquemas["DespachoEntrada"]
    assert set(entrada["required"]) == set(Despacho.model_fields) and entrada["additionalProperties"] is False
    assert entrada["properties"]["juez"]["maxLength"] == MAX_TEXTO
    assert entrada["properties"]["pie_fallo"]["maxItems"] == MAX_LINEAS
    assert entrada["properties"]["pie_fallo"]["items"]["maxLength"] == MAX_LINEA
    cuerpo = esquemas["FormatoCuerpo"]
    assert cuerpo["additionalProperties"] is False and set(cuerpo["required"]) == {"valores", "plantilla_gen"}
    assert cuerpo["properties"]["valores"]["$ref"].endswith("/DespachoEntrada")
