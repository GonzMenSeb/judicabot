from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from test_ediciones_api import (
    ANTECEDENTES,
    BLOQUE,
    IMPUGNACION,
    ClienteVariable,
    acciones_log,
    montar_caso,
    provocar_conflicto,
    simular_job,
    vista_previo,
)
from test_graph import DECISION
from tutela2 import api, server
from tutela2 import ediciones as ed
from tutela2.esquemas import EdicionesRespuesta

TITULO = "consideraciones.bloques.0.titulo"
CONTESTACION = "apertura.contestaciones.0.texto"
SENTENCIA = "apertura.sentencia_impugnada"
JOB = "Hay una redacción en curso para este caso."


@pytest.fixture
def montaje(tmp_path, monkeypatch):
    return lambda cliente=None: montar_caso(tmp_path, monkeypatch, cliente)


@pytest.fixture
def caso(montaje):
    return montaje()[0]


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    server.JOBS.clear()
    yield TestClient(server.app, base_url="http://127.0.0.1")
    server.JOBS.clear()


def url(caso, pieza: str = "", sufijo: str = "") -> str:
    return f"/api/casos/{caso.name}/ediciones" + (f"/{pieza}" if pieza else "") + sufijo


def parrafos(http, caso, pieza: str) -> list[str]:
    return http.get(url(caso)).json()["piezas"][pieza]["parrafos"]


def poner(http, caso, pieza: str, cambio, parrafo: int = 0):
    original = parrafos(http, caso, pieza)[parrafo]
    return http.put(url(caso, pieza), json={"parrafo": parrafo, "original": original, "texto": cambio(original)})


def test_get_lista_las_piezas_en_el_orden_del_documento(http, caso):
    r = http.get(url(caso))
    assert r.status_code == 200
    cuerpo = EdicionesRespuesta.model_validate(r.json())
    assert cuerpo.editable is True and cuerpo.motivo is None and cuerpo.conflictos == []
    assert list(cuerpo.piezas) == [
        ANTECEDENTES,
        CONTESTACION,
        SENTENCIA,
        IMPUGNACION,
        "consideraciones.procedibilidad",
        TITULO,
        BLOQUE,
        "consideraciones.bloques.1.titulo",
        "consideraciones.bloques.1.texto",
    ]
    assert len(cuerpo.piezas[IMPUGNACION].parrafos) == 4 and cuerpo.piezas[IMPUGNACION].editados == []
    assert "⟦cita c1 · T-200 de 2022⟧" in cuerpo.piezas[BLOQUE].parrafos[0]


def test_put_y_delete_editan_y_restauran(http, caso):
    r = poner(http, caso, CONTESTACION, lambda t: t.replace("La entidad dio respuesta", "La entidad contestó"))
    assert r.status_code == 200
    assert r.json()["piezas"][CONTESTACION]["editados"] == [0]
    assert "La entidad contestó" in r.json()["piezas"][CONTESTACION]["parrafos"][0]
    assert "La entidad contestó" in vista_previo(caso, CONTESTACION)
    assert http.get(url(caso)).json()["piezas"][CONTESTACION]["editados"] == [0]

    r = http.delete(url(caso, CONTESTACION))
    assert r.status_code == 200
    assert r.json()["piezas"][CONTESTACION]["editados"] == []
    assert "La entidad contestó" not in vista_previo(caso)
    assert not ed.leer(caso)["piezas"]


def test_put_acepta_varios_parrafos_y_borrar_uno(http, caso):
    r = poner(http, caso, IMPUGNACION, lambda t: t + "\n\nUn párrafo nuevo del despacho.", 3)
    assert r.status_code == 200
    assert r.json()["piezas"][IMPUGNACION]["parrafos"][4] == "Un párrafo nuevo del despacho."
    assert r.json()["piezas"][IMPUGNACION]["editados"] == [4]
    r = poner(http, caso, IMPUGNACION, lambda t: "", 4)
    assert r.status_code == 200 and len(r.json()["piezas"][IMPUGNACION]["parrafos"]) == 4


def test_quitar_un_parrafo_deja_modificada_la_pieza_y_delete_la_restaura(http, caso):
    antes = http.get(url(caso)).json()["piezas"][IMPUGNACION]
    assert antes["modificada"] is False
    r = poner(http, caso, IMPUGNACION, lambda t: "", 3)
    assert r.status_code == 200
    pieza = r.json()["piezas"][IMPUGNACION]
    assert len(pieza["parrafos"]) == len(antes["parrafos"]) - 1
    assert pieza["editados"] == [] and pieza["modificada"] is True
    assert http.get(url(caso)).json()["piezas"][IMPUGNACION]["modificada"] is True
    r = http.delete(url(caso, IMPUGNACION))
    assert r.status_code == 200
    assert r.json()["piezas"][IMPUGNACION] == antes


def test_get_con_un_job_corriendo_no_sincroniza(http, caso):
    assert poner(http, caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3).status_code == 200
    capa = json.loads((caso / ed.ARCHIVO).read_text(encoding="utf-8"))
    capa["piezas"][IMPUGNACION].update(ia="Un texto previo de la IA.", consolidado="Un texto previo de la IA.")
    ruta = caso / ed.ARCHIVO
    ruta.write_text(json.dumps(capa, ensure_ascii=False, indent=2), encoding="utf-8")
    contenido = ruta.read_bytes()
    log = (caso / ed.LOG).read_bytes()
    previo = (caso / "salidas" / "trabajo" / "previo.docx").read_bytes()

    simular_job(caso.name)
    r = http.get(url(caso))
    assert r.status_code == 200
    assert r.json() == {"editable": False, "motivo": JOB, "piezas": {}, "conflictos": []}
    assert ruta.read_bytes() == contenido and (caso / ed.LOG).read_bytes() == log
    assert (caso / "salidas" / "trabajo" / "previo.docx").read_bytes() == previo

    server.JOBS.clear()
    r = http.get(url(caso))
    assert r.status_code == 200 and r.json()["editable"] is True
    assert ruta.read_bytes() != contenido
    assert [c["pieza"] for c in r.json()["conflictos"]] == [IMPUGNACION]
    assert ed.leer(caso)["conflictos"][IMPUGNACION]["huerfana"] is False


def test_get_con_un_job_terminado_no_estorba(http, caso):
    simular_job(caso.name)
    server.JOBS["simulado"]["estado"] = "terminado"
    assert http.get(url(caso)).json()["editable"] is True


def test_los_jobs_de_otro_caso_no_bloquean(http, caso):
    simular_job("otro-caso")
    assert http.get(url(caso)).json()["editable"] is True
    assert poner(http, caso, SENTENCIA, lambda t: t.replace("resolvió", "decidió")).status_code == 200


def test_get_terminado_no_es_editable(http, caso):
    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    r = http.get(url(caso))
    assert r.status_code == 200
    assert r.json()["editable"] is False and r.json()["motivo"]
    assert r.json()["piezas"] == {} and r.json()["conflictos"] == []
    assert not (caso / ed.ARCHIVO).exists()


def test_get_sin_hilo_no_es_editable_ni_crea_el_hilo(http, tmp_path):
    carpeta = tmp_path / "casos" / "caso-vacio"
    (carpeta / "insumos").mkdir(parents=True)
    r = http.get(f"/api/casos/{carpeta.name}/ediciones")
    assert r.status_code == 200 and r.json()["editable"] is False and r.json()["motivo"]
    assert not (carpeta / "hilo.sqlite").exists()


def test_caso_inexistente_responde_404(http, caso):
    assert http.get("/api/casos/no-existe/ediciones").status_code == 404
    assert http.put("/api/casos/no-existe/ediciones/" + ANTECEDENTES, json={"parrafo": 0, "original": "a", "texto": "b"}).status_code == 404
    assert http.delete("/api/casos/no-existe/ediciones/" + ANTECEDENTES).status_code == 404


@pytest.mark.parametrize(
    "metodo, sufijo, cuerpo",
    [
        ("put", "", {"parrafo": 0, "original": "x", "texto": "y"}),
        ("delete", "", None),
        ("post", "/resolver", {"elecciones": ["mio"]}),
    ],
)
def test_mutaciones_con_un_job_corriendo_responden_409(http, caso, metodo, sufijo, cuerpo):
    simular_job(caso.name)
    r = getattr(http, metodo)(url(caso, ANTECEDENTES, sufijo), **({"json": cuerpo} if cuerpo else {}))
    assert r.status_code == 409 and r.json()["detail"] == JOB
    assert not (caso / ed.ARCHIVO).exists() and not (caso / ed.LOG).exists()


def test_put_con_original_desfasado_responde_409(http, caso):
    r = http.put(url(caso, ANTECEDENTES), json={"parrafo": 1, "original": "Texto que ya no está.", "texto": "Nuevo."})
    assert r.status_code == 409 and "recargue" in r.json()["detail"]
    r = http.put(url(caso, ANTECEDENTES), json={"parrafo": 7, "original": "x", "texto": "Nuevo."})
    assert r.status_code == 409 and "recargue" in r.json()["detail"]
    assert not (caso / ed.ARCHIVO).exists()


def test_original_desfasado_tras_otra_edicion(http, caso):
    original = parrafos(http, caso, SENTENCIA)[0]
    assert poner(http, caso, SENTENCIA, lambda t: t.replace("resolvió", "decidió")).status_code == 200
    r = http.put(url(caso, SENTENCIA), json={"parrafo": 0, "original": original, "texto": "Otra versión."})
    assert r.status_code == 409


@pytest.mark.parametrize("pieza", ["apertura.nada", "consideraciones.bloques.x.texto", "apertura.contestaciones.01.texto", "caso.parrafos"])
def test_pieza_desconocida_responde_404(http, caso, pieza):
    assert http.put(url(caso, pieza), json={"parrafo": 0, "original": "a", "texto": "b"}).status_code == 404
    assert http.delete(url(caso, pieza)).status_code == 404
    assert http.post(url(caso, pieza, "/resolver"), json={"elecciones": []}).status_code == 404
    assert not (caso / ed.ARCHIVO).exists()


def test_pieza_que_no_existe_en_el_estado_responde_404(http, caso):
    pieza = "consideraciones.bloques.9.texto"
    assert ed.es_pieza(pieza)
    assert http.put(url(caso, pieza), json={"parrafo": 0, "original": "a", "texto": "b"}).status_code == 404
    assert http.delete(url(caso, pieza)).status_code == 200


def test_las_validaciones_responden_422_en_espanol(http, caso):
    casos = [
        (SENTENCIA, lambda t: "", "no puede quedar vacía"),
        (SENTENCIA, lambda t: t + " Véase [[CITA:c1]].", "No escriba [["),
        (BLOQUE, lambda t: t.replace("⟦cita c1 · T-200 de 2022⟧", "la sentencia"), "no se pueden agregar, quitar ni cambiar"),
        (BLOQUE, lambda t: t + " ⟦cita c2 · SU-082 de 1995⟧", "sobran"),
        (BLOQUE, lambda t: t + " Así lo dijo la sentencia T-999 de 2020.", "jurisprudencia nueva"),
        (TITULO, lambda t: t + "\nOtra línea", "una sola línea"),
        (SENTENCIA, lambda t: t + " ⟦ suelta", "suelto"),
    ]
    for pieza, cambio, fragmento in casos:
        r = poner(http, caso, pieza, cambio)
        assert r.status_code == 422, (pieza, fragmento, r.text)
        assert isinstance(r.json()["detail"], str) and fragmento in r.json()["detail"], (fragmento, r.json())
    assert not (caso / ed.ARCHIVO).exists()
    assert http.get(url(caso)).json()["piezas"][SENTENCIA]["editados"] == []


def test_validaciones_multiples_se_unen_con_un_espacio(http, caso):
    r = poner(http, caso, BLOQUE, lambda t: t.replace("⟦cita c1 · T-200 de 2022⟧", "[[CITA:c1]]"))
    assert r.status_code == 422
    assert "No escriba [[" in r.json()["detail"] and "faltan" in r.json()["detail"] and "\n" not in r.json()["detail"]


def test_cuerpo_invalido_responde_422(http, caso):
    assert http.put(url(caso, SENTENCIA), json={"parrafo": -1, "original": "a", "texto": "b"}).status_code == 422
    assert http.put(url(caso, SENTENCIA), json={"original": "a", "texto": "b"}).status_code == 422
    assert http.post(url(caso, SENTENCIA, "/resolver"), json={"elecciones": ["otro"]}).status_code == 422
    assert http.post(url(caso, SENTENCIA, "/resolver"), json={}).status_code == 422


def test_resolver_sin_conflicto_responde_409(http, caso):
    r = http.post(url(caso, SENTENCIA, "/resolver"), json={"elecciones": ["mio"]})
    assert r.status_code == 409 and "no tiene un conflicto" in r.json()["detail"]


def test_flujo_de_conflicto_por_http(montaje, http):
    caso, cliente, _ = provocar_conflicto(montaje)
    r = http.get(url(caso))
    assert r.status_code == 200
    cuerpo = EdicionesRespuesta.model_validate(r.json())
    assert [c.pieza for c in cuerpo.conflictos] == [BLOQUE]
    assert cuerpo.conflictos[0].etiqueta == "Consideraciones: bloque 1 (La carencia actual de objeto por hecho superado)"
    assert [t.tipo for t in cuerpo.conflictos[0].trozos] == ["conflicto", "ok"]

    r = http.put(url(caso, BLOQUE), json={"parrafo": 0, "original": cuerpo.piezas[BLOQUE].parrafos[0], "texto": "Otro."})
    assert r.status_code == 409 and "conflicto" in r.json()["detail"]

    r = http.post(url(caso, BLOQUE, "/resolver"), json={"elecciones": []})
    assert r.status_code == 422 and "Debe elegir" in r.json()["detail"]
    r = http.post(url(caso, BLOQUE, "/resolver"), json={"elecciones": ["mio", "nuevo"]})
    assert r.status_code == 422

    simular_job(caso.name)
    assert http.post(url(caso, BLOQUE, "/resolver"), json={"elecciones": ["mio"]}).status_code == 409
    server.JOBS.clear()

    r = http.post(url(caso, BLOQUE, "/resolver"), json={"elecciones": ["mio"]})
    assert r.status_code == 200 and r.json()["conflictos"] == []
    assert r.json()["piezas"][BLOQUE]["editados"] == [0]
    assert "lineamientos" in vista_previo(caso, BLOQUE)
    assert http.post(url(caso, BLOQUE, "/resolver"), json={"elecciones": ["mio"]}).status_code == 409


def test_descartar_una_pieza_huerfana_por_http(montaje, http):
    def sin_segundo_bloque(salida, n):
        if n >= 2:
            salida.bloques.pop()
            salida.citas = [c for c in salida.citas if c.id != "c2"]

    caso, cliente = montaje(ClienteVariable(siempre={"consideraciones": sin_segundo_bloque}))
    huerfana = "consideraciones.bloques.1.texto"
    assert poner(http, caso, huerfana, lambda t: t.replace("precisó", "fijó")).status_code == 200
    rehacer = {"accion": "rehacer_consideraciones", "instruccion": "Sé más breve."}
    assert api.decidir(caso, rehacer)["estado"] == "esperando_decision"

    r = http.get(url(caso))
    assert [(c["pieza"], c["huerfana"]) for c in r.json()["conflictos"]] == [(huerfana, True)]
    [trozo] = r.json()["conflictos"][0]["trozos"]
    assert trozo["tipo"] == "ok" and any("fijó" in p for p in trozo["parrafos"])
    assert huerfana not in r.json()["piezas"]
    assert http.post(url(caso, huerfana, "/resolver"), json={"elecciones": []}).status_code == 422
    llamadas = len(cliente.llamadas)
    assert http.post(f"/api/casos/{caso.name}/run", json={"cmd": "decidir", "decision": DECISION}).status_code == 409

    r = http.delete(url(caso, huerfana))
    assert r.status_code == 200 and r.json()["conflictos"] == []
    assert not ed.hay_conflictos(caso) and ed.leer(caso)["piezas"] == {}
    assert acciones_log(caso) == ["editar", "consolidar", "conflicto", "descartar"]
    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    assert len(cliente.llamadas) == llamadas + 1


def test_errores_inesperados_responden_500_en_espanol(http, caso, monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("se rompió")

    for nombre in ("ediciones", "editar_pieza", "restaurar_pieza", "resolver_pieza"):
        monkeypatch.setattr(api, nombre, falla)
    r = http.get(url(caso))
    assert r.status_code == 500 and r.json()["detail"].startswith("No se pudieron leer las ediciones")
    r = http.put(url(caso, SENTENCIA), json={"parrafo": 0, "original": "a", "texto": "b"})
    assert r.status_code == 500 and r.json()["detail"].startswith("No se pudo guardar la edición")
    assert http.delete(url(caso, SENTENCIA)).status_code == 500
    assert http.post(url(caso, SENTENCIA, "/resolver"), json={"elecciones": []}).status_code == 500
    assert not server._LOCK.locked()


def test_el_contrato_documenta_las_rutas():
    esquema = server.app.openapi()
    base = "/api/casos/{caso_id}/ediciones"
    assert set(esquema["paths"][base]) == {"get"}
    assert set(esquema["paths"][base + "/{pieza}"]) == {"put", "delete"}
    assert set(esquema["paths"][base + "/{pieza}/resolver"]) == {"post"}
    for metodo in ("put", "delete"):
        assert {"200", "404", "409", "422"} <= set(esquema["paths"][base + "/{pieza}"][metodo]["responses"])
    trozos = esquema["components"]["schemas"]["ConflictoEdicion"]["properties"]["trozos"]["items"]
    assert trozos["discriminator"]["propertyName"] == "tipo"
