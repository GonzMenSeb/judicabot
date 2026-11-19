from __future__ import annotations

import json
from collections import deque
from typing import Callable

import docx
import pytest
from fastapi.testclient import TestClient

from test_graph import DECISION, FALLO_DOCX, Verificador, ingesta_sintetica
from tutela2 import api, ingest, llm, salidas, server
from tutela2 import citas as citas_real
from tutela2 import config as cfgmod
from tutela2 import ediciones as ed
from tutela2.config import Config, LLMConfig
from tutela2.llm import FakeClient

ANTECEDENTES = "apertura.antecedentes_hechos"
IMPUGNACION = "apertura.impugnacion"
BLOQUE = "consideraciones.bloques.0.texto"
PRIMERO = (
    "La carencia actual de objeto por hecho superado se configura cuando desaparece la afectación que dio origen a la "
    "acción de tutela y la pretensión queda satisfecha. En la [[CITA:c1]], la Corte Constitucional explicó los "
    "presupuestos de esta figura y su alcance frente a la pretensión de la acción."
)
SEGUNDO = "El Despacho aplica ese criterio al caso concreto a partir de los hechos acreditados en el expediente"
INVALIDA = {"accion": "decidir", "resultado": "REVOCAR"}


class ClienteVariable(FakeClient):
    def __init__(self, siempre: dict[str, Callable] | None = None, cambios: dict[tuple[str, int], Callable] | None = None):
        super().__init__()
        self.siempre, self.cambios = siempre or {}, cambios or {}

    def estructurado(self, nodo, system, user, schema, cfg):
        salida, meta = super().estructurado(nodo, system, user, schema, cfg)
        n = sum(1 for x, _ in self.llamadas if x == nodo)
        if nodo in self.siempre:
            self.siempre[nodo](salida, n)
        if (nodo, n) in self.cambios:
            self.cambios[(nodo, n)](salida)
        return salida, meta

    def nodos(self) -> list[str]:
        return [n for n, _ in self.llamadas]


def dos_parrafos(salida, n: int, primero: str | None = None) -> None:
    salida.bloques[0].texto = f"{primero or PRIMERO}\n\n{SEGUNDO} (redacción {'inicial' if n == 1 else 'nueva'})."


def cliente_de_dos_parrafos(cambios: dict[tuple[str, int], Callable] | None = None) -> ClienteVariable:
    return ClienteVariable(siempre={"consideraciones": dos_parrafos}, cambios=cambios)


def montar_caso(tmp_path, monkeypatch, cliente: FakeClient | None = None):
    cliente = cliente or FakeClient()
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    carpeta = tmp_path / "casos" / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: cliente)
    assert api.nuevo(carpeta)["estado"] == "revision"
    r = api.iniciar(carpeta)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    return carpeta, cliente


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


def simular_job(caso_id: str) -> None:
    server.JOBS["simulado"] = {
        "id": "simulado",
        "caso": caso_id,
        "cmd": "iniciar",
        "estado": "corriendo",
        "log": deque(),
        "resultado": None,
        "error": None,
    }


def valores(caso) -> dict:
    with api._grafo(caso, cfgmod.cargar(caso)) as (g, hilo):
        return dict(g.get_state(hilo).values)


def parrafos_de(caso, pieza: str) -> list[str]:
    return api.ediciones(caso)["piezas"][pieza]["parrafos"]


def editar(caso, pieza: str, cambio: Callable[[str], str], parrafo: int = 0) -> dict:
    original = parrafos_de(caso, pieza)[parrafo]
    return api.editar_pieza(caso, pieza, parrafo, original, cambio(original))


def texto_de_vista(ruta, pieza: str | None = None) -> str:
    vista = json.loads(ruta.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(s["texto"] for s in b["segmentos"])
        for p in vista["paginas"]
        for b in p["bloques"]
        if pieza is None or (b.get("fuente") or {}).get("pieza") == pieza
    )


def vista_previo(caso, pieza: str | None = None) -> str:
    return texto_de_vista(salidas.trabajo(caso) / "previo.vista.json", pieza)


def vista_fallo(caso, pieza: str | None = None) -> str:
    return texto_de_vista(salidas.principal(caso) / "fallo.vista.json", pieza)


def texto_docx(ruta) -> str:
    d = docx.Document(str(ruta))
    celdas = [c.text for t in d.tables for f in t.rows for c in f.cells]
    return "\n".join([p.text for p in d.paragraphs] + celdas)


def lineas_log(caso) -> list[dict]:
    ruta = caso / ed.LOG
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []


def acciones_log(caso) -> list[str]:
    return [x["accion"] for x in lineas_log(caso)]


def seccion_del_prompt(cliente: FakeClient, nodo: str, nombre: str, indice: int = -1) -> str:
    user = [u for n, u in cliente.llamadas if n == nodo][indice]
    return llm.leer_secciones(user)[nombre]


def provocar_conflicto(montaje):
    cliente = cliente_de_dos_parrafos(
        {("consideraciones", 2): lambda s: dos_parrafos(s, 2, PRIMERO.replace("explicó", "precisó"))}
    )
    caso, cliente = montaje(cliente)
    nuevo = editar(caso, BLOQUE, lambda t: t.replace("presupuestos", "lineamientos"))["piezas"][BLOQUE]["parrafos"][0]
    r = api.decidir(caso, {"accion": "rehacer_consideraciones", "instruccion": "Ajusta el tono."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    return caso, cliente, nuevo


def test_editar_no_toca_el_grafo_ni_la_clasificacion(caso, montaje):
    antes = valores(caso)
    llamadas = len(api.estado(caso)["resumen"]["bitacora"])
    r = editar(caso, ANTECEDENTES, lambda t: t.replace("dispuso la notificación", "dispuso con urgencia la notificación"), 1)
    assert r["editable"] and r["piezas"][ANTECEDENTES]["editados"] == [1]
    assert "con urgencia" in r["piezas"][ANTECEDENTES]["parrafos"][1]
    assert r["piezas"][ANTECEDENTES]["parrafos"][0] == antes["apertura"]["antecedentes_hechos"].split("\n\n")[0]

    estado = api.estado(caso)
    assert estado["estado"] == "esperando_decision" and len(estado["resumen"]["bitacora"]) == llamadas
    despues = valores(caso)
    for campo in ("apertura", "consideraciones", "bitacora", "alertas", "errores", "intentos", "decisiones", "citas"):
        assert despues.get(campo) == antes.get(campo), campo
    assert "ediciones_humanas" not in despues

    assert "con urgencia" in vista_previo(caso, ANTECEDENTES)
    assert "con urgencia" not in vista_previo(caso, "apertura.impugnacion")
    capa = ed.leer(caso)
    assert set(capa["piezas"]) == {ANTECEDENTES} and capa["conflictos"] == {}
    assert acciones_log(caso) == ["editar"]


def test_el_previo_se_regenera_con_las_ediciones(caso):
    antes = (salidas.trabajo(caso) / "previo.docx").read_bytes()
    editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)
    despues = (salidas.trabajo(caso) / "previo.docx").read_bytes()
    assert despues != antes
    assert "pide al superior" in texto_docx(salidas.trabajo(caso) / "previo.docx")
    assert "pide al superior" in vista_previo(caso, IMPUGNACION)
    api.restaurar_pieza(caso, IMPUGNACION)
    assert "pide al superior" not in vista_previo(caso)
    assert acciones_log(caso) == ["editar", "restaurar"]


def test_decidir_lleva_las_ediciones_al_caso_concreto_y_al_fallo(montaje):
    caso, cliente = montaje()
    editar(caso, ANTECEDENTES, lambda t: t.replace("dispuso la notificación", "dispuso con urgencia la notificación"), 1)
    editar(caso, BLOQUE, lambda t: t.replace("presupuestos", "lineamientos"))
    antes = len(cliente.llamadas)
    assert [n for n, _ in cliente.llamadas] == ["apertura", "apoderados", "consideraciones"]

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert [n for n, _ in cliente.llamadas] == ["apertura", "apoderados", "consideraciones", "caso_concreto"]
    assert len(cliente.llamadas) == antes + 1
    assert [b["nodo"] for b in r["resumen"]["bitacora"]] == ["apertura", "apoderados", "consideraciones", "caso_concreto"]

    antecedentes = seccion_del_prompt(cliente, "caso_concreto", "ANTECEDENTES")
    consideraciones = seccion_del_prompt(cliente, "caso_concreto", "CONSIDERACIONES")
    assert "dispuso con urgencia la notificación" in antecedentes
    assert "los lineamientos de esta figura" in consideraciones and "los presupuestos de esta figura" not in consideraciones
    assert "[[CITA:c1]]" in consideraciones and "⟦" not in consideraciones

    estado = valores(caso)
    assert estado["ediciones_humanas"] == ["antecedentes", "consideraciones"]
    assert "con urgencia" in estado["apertura"]["antecedentes_hechos"]
    assert "[[CITA:c1]]" in estado["consideraciones"]["bloques"][0]["texto"]

    fallo = salidas.raiz(caso) / FALLO_DOCX
    assert "dispuso con urgencia la notificación" in texto_docx(fallo)
    assert "los lineamientos de esta figura" in texto_docx(fallo)
    assert "con urgencia" in vista_fallo(caso, ANTECEDENTES)
    assert "los lineamientos de esta figura" in vista_fallo(caso, BLOQUE)
    assert "los presupuestos de esta figura" not in vista_fallo(caso)

    declaracion = texto_docx(salidas.trabajo(caso) / "declaracion_ia.docx")
    assert "IA + edición humana" in declaracion and "Corregido por el despacho en el borrador." in declaracion

    assert acciones_log(caso) == ["editar", "editar", "consolidar", "consolidar"]
    consolidadas = {x["pieza"]: x for x in lineas_log(caso) if x["accion"] == "consolidar"}
    assert set(consolidadas) == {ANTECEDENTES, BLOQUE}
    assert "con urgencia" in consolidadas[ANTECEDENTES]["texto"] and "con urgencia" not in consolidadas[ANTECEDENTES]["ia"]

    editable = api.ediciones(caso)
    assert editable["editable"] is False and editable["piezas"] == {} and editable["conflictos"] == []
    assert editable["motivo"]


def test_sin_ediciones_el_comando_no_lleva_update(caso, monkeypatch):
    comandos: list[dict] = []
    real = api.Command
    monkeypatch.setattr(api, "Command", lambda **kw: comandos.append(kw) or real(**kw))
    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    assert [set(c) for c in comandos] == [{"resume"}]
    assert not (caso / ed.ARCHIVO).exists() and not (caso / ed.LOG).exists()
    assert "ediciones_humanas" not in valores(caso)
    assert "IA + edición humana" not in texto_docx(salidas.trabajo(caso) / "declaracion_ia.docx")


def test_con_ediciones_el_update_solo_toca_las_piezas(caso, monkeypatch):
    editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)
    comandos: list[dict] = []
    real = api.Command
    monkeypatch.setattr(api, "Command", lambda **kw: comandos.append(kw) or real(**kw))
    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    assert len(comandos) == 1 and set(comandos[0]) == {"update", "resume"}
    assert set(comandos[0]["update"]) == {"apertura", "consideraciones", "ediciones_humanas"}
    assert comandos[0]["update"]["ediciones_humanas"] == ["impugnacion"]


def test_rehacer_consideraciones_recibe_el_texto_humano_y_rebasa_limpio(montaje):
    cliente = cliente_de_dos_parrafos()
    caso, cliente = montaje(cliente)
    editar(caso, BLOQUE, lambda t: t.replace("presupuestos", "lineamientos"))
    r = api.decidir(caso, {"accion": "rehacer_consideraciones", "instruccion": "Ajusta el tono."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert cliente.nodos() == ["apertura", "apoderados", "consideraciones", "consideraciones"]

    anterior = json.loads(seccion_del_prompt(cliente, "consideraciones", "SALIDA ANTERIOR"))
    assert "lineamientos de esta figura" in anterior["bloques"][0]["texto"]
    assert "presupuestos de esta figura" not in anterior["bloques"][0]["texto"]
    assert "[[CITA:c1]]" in anterior["bloques"][0]["texto"]

    resp = api.ediciones(caso)
    assert resp["conflictos"] == []
    parrafos = resp["piezas"][BLOQUE]["parrafos"]
    assert "lineamientos de esta figura" in parrafos[0] and "(redacción nueva)" in parrafos[1]
    assert resp["piezas"][BLOQUE]["editados"] == [0]
    capa = ed.leer(caso)
    assert capa["piezas"][BLOQUE]["ia"].endswith("(redacción nueva).")
    assert "presupuestos de esta figura" in capa["piezas"][BLOQUE]["ia"]
    texto = vista_previo(caso, BLOQUE)
    assert "lineamientos de esta figura" in texto and "(redacción nueva)" in texto and "(redacción inicial)" not in texto
    assert acciones_log(caso) == ["editar", "consolidar", "rebase"]

    r = api.decidir(caso, DECISION)
    assert r["estado"] == "terminado"
    consideraciones = seccion_del_prompt(cliente, "caso_concreto", "CONSIDERACIONES")
    assert "lineamientos de esta figura" in consideraciones and "(redacción nueva)" in consideraciones


def test_rehacer_apertura_con_ediciones_rebasa_la_apertura(montaje):
    def cambiar_ultimo(salida):
        salida.impugnacion = "\n\n".join(salida.impugnacion.split("\n\n")[:-1] + ["Cierre de la nueva redacción de la impugnación."])

    caso, cliente = montaje(ClienteVariable(cambios={("apertura", 2): cambiar_ultimo}))
    editar(caso, IMPUGNACION, lambda t: t.replace("el impugnante señala", "la parte señala"), 0)
    r = api.decidir(caso, {"accion": "rehacer_apertura", "instruccion": "Incluye la contestación."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    anterior = json.loads(seccion_del_prompt(cliente, "apertura", "SALIDA ANTERIOR"))
    assert "la parte señala" in anterior["impugnacion"]

    resp = api.ediciones(caso)
    assert resp["conflictos"] == []
    parrafos = resp["piezas"][IMPUGNACION]["parrafos"]
    assert "la parte señala" in parrafos[0] and parrafos[-1] == "Cierre de la nueva redacción de la impugnación."
    assert resp["piezas"][IMPUGNACION]["editados"] == [0]
    assert "la parte señala" in vista_previo(caso, IMPUGNACION)


def test_rehacer_apertura_que_reordena_los_bloques_lleva_la_edicion_con_su_bloque(montaje):
    def invertir(salida):
        salida.bloques = list(reversed(salida.bloques))

    caso, cliente = montaje(cliente_de_dos_parrafos({("consideraciones", 2): invertir}))
    titulo = valores(caso)["consideraciones"]["bloques"][0]["titulo"]
    humano = "Párrafo del despacho: conclusión sobre la carencia actual de objeto."
    editar(caso, BLOQUE, lambda t: f"{t}\n\n{humano}", 1)
    r = api.decidir(caso, {"accion": "rehacer_apertura", "instruccion": "Ajusta la apertura."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]

    titulos = [b["titulo"] for b in valores(caso)["consideraciones"]["bloques"]]
    j = titulos.index(titulo)
    assert j != 0
    destino = f"consideraciones.bloques.{j}.texto"
    resp = api.ediciones(caso)
    assert resp["conflictos"] == []
    assert resp["piezas"][destino]["parrafos"][-1] == humano
    assert humano not in resp["piezas"][BLOQUE]["parrafos"]
    assert humano in vista_previo(caso, destino) and humano not in vista_previo(caso, BLOQUE)

    r = api.decidir(caso, DECISION)
    assert r["estado"] == "terminado", r["error"]
    consideraciones = seccion_del_prompt(cliente, "caso_concreto", "CONSIDERACIONES")
    assert consideraciones.index(titulos[0]) < consideraciones.index(titulo) < consideraciones.index(humano)
    assert humano in vista_fallo(caso, destino) and humano not in vista_fallo(caso, BLOQUE)


def test_conflicto_bloquea_decidir_sin_escribir_decision(montaje, http):
    caso, cliente, mia = provocar_conflicto(montaje)
    resp = api.ediciones(caso)
    assert [c["pieza"] for c in resp["conflictos"]] == [BLOQUE] and not resp["conflictos"][0]["huerfana"]
    trozos = resp["conflictos"][0]["trozos"]
    assert [t["tipo"] for t in trozos] == ["conflicto", "ok"] and trozos[0]["mio_permitido"] is True
    assert "lineamientos" in trozos[0]["mio"][0] and "precisó" in trozos[0]["nuevo"][0]
    assert "precisó" in resp["piezas"][BLOQUE]["parrafos"][0] and "lineamientos" not in resp["piezas"][BLOQUE]["parrafos"][0]
    assert "precisó" in vista_previo(caso, BLOQUE) and "lineamientos" not in vista_previo(caso)
    assert ed.hay_conflictos(caso)

    decision_antes = (caso / "decision.json").read_bytes()
    llamadas = len(cliente.llamadas)
    r = api.decidir(caso, DECISION)
    assert r["ok"] is False and r["estado"] == "esperando_decision"
    assert r["error"] == "Hay conflictos de edición sin resolver en el borrador: resuélvalos antes de continuar."
    assert (caso / "decision.json").read_bytes() == decision_antes
    assert len(cliente.llamadas) == llamadas and api.estado(caso)["estado"] == "esperando_decision"

    rechazo = http.post(f"/api/casos/{caso.name}/run", json={"cmd": "decidir", "decision": DECISION})
    assert rechazo.status_code == 409
    assert rechazo.json()["detail"] == "Hay conflictos de edición sin resolver en el borrador: resuélvalos antes de decidir."
    assert server.JOBS == {}
    assert len(cliente.llamadas) == llamadas
    assert acciones_log(caso) == ["editar", "consolidar", "conflicto"]


def test_resolver_con_mi_version_desbloquea_y_llega_al_fallo(montaje, http):
    caso, cliente, _ = provocar_conflicto(montaje)
    resp = api.resolver_pieza(caso, BLOQUE, ["mio"])
    assert resp["conflictos"] == [] and not ed.hay_conflictos(caso)
    assert "lineamientos" in resp["piezas"][BLOQUE]["parrafos"][0] and resp["piezas"][BLOQUE]["editados"] == [0]
    assert "lineamientos" in vista_previo(caso, BLOQUE)
    assert "resolver" in acciones_log(caso)

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert "lineamientos de esta figura" in seccion_del_prompt(cliente, "caso_concreto", "CONSIDERACIONES")
    assert "lineamientos de esta figura" in texto_docx(salidas.raiz(caso) / FALLO_DOCX)
    assert valores(caso)["ediciones_humanas"] == ["consideraciones"]


def test_resolver_con_la_version_nueva_descarta_mi_edicion(montaje, http):
    caso, cliente, _ = provocar_conflicto(montaje)
    resp = api.resolver_pieza(caso, BLOQUE, ["nuevo"])
    assert resp["conflictos"] == [] and resp["piezas"][BLOQUE]["editados"] == []
    assert "precisó" in resp["piezas"][BLOQUE]["parrafos"][0]
    assert BLOQUE not in ed.leer(caso)["piezas"]

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    consideraciones = seccion_del_prompt(cliente, "caso_concreto", "CONSIDERACIONES")
    assert "precisó los presupuestos" in consideraciones and "lineamientos" not in consideraciones
    assert valores(caso)["ediciones_humanas"] == ["consideraciones"]


def test_restaurar_tras_consolidar_devuelve_el_texto_de_la_ia(montaje):
    caso, cliente = montaje()
    original = parrafos_de(caso, IMPUGNACION)[3]
    editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)

    r = api.decidir(caso, {"accion": "rehacer_consideraciones", "instruccion": "Ajusta el tono."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert "pide al superior" in valores(caso)["apertura"]["impugnacion"]
    assert len(cliente.llamadas) == 4

    resp = api.ediciones(caso)
    assert resp["conflictos"] == [] and resp["piezas"][IMPUGNACION]["editados"] == [3]
    assert "pide al superior" in vista_previo(caso, IMPUGNACION)

    resp = api.restaurar_pieza(caso, IMPUGNACION)
    assert resp["piezas"][IMPUGNACION]["parrafos"][3] == original and resp["piezas"][IMPUGNACION]["editados"] == []
    assert IMPUGNACION in ed.leer(caso)["piezas"]
    assert "pide al superior" not in vista_previo(caso, IMPUGNACION)

    for _ in range(2):
        resp = api.ediciones(caso)
        assert resp["conflictos"] == [] and resp["piezas"][IMPUGNACION]["parrafos"][3] == original
        assert "pide al superior" not in vista_previo(caso, IMPUGNACION)
    assert IMPUGNACION in ed.leer(caso)["piezas"]

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert "pide al superior" not in seccion_del_prompt(cliente, "caso_concreto", "IMPUGNACION")
    assert "solicita al superior" in seccion_del_prompt(cliente, "caso_concreto", "IMPUGNACION")
    assert "pide al superior" not in texto_docx(salidas.raiz(caso) / FALLO_DOCX)
    assert acciones_log(caso) == ["editar", "consolidar", "restaurar", "consolidar"]


def test_volver_a_editar_tras_consolidar_no_crea_conflicto(montaje):
    caso, cliente = montaje()
    editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)
    rehacer = {"accion": "rehacer_consideraciones", "instruccion": "Ajusta el tono."}
    assert api.decidir(caso, rehacer)["estado"] == "esperando_decision"
    resp = editar(caso, IMPUGNACION, lambda t: t.replace("pide al superior", "ruega al superior"), 3)
    assert resp["conflictos"] == [] and "ruega al superior" in resp["piezas"][IMPUGNACION]["parrafos"][3]
    assert "ruega al superior" in vista_previo(caso, IMPUGNACION)
    assert api.ediciones(caso)["conflictos"] == []

    assert api.decidir(caso, rehacer)["estado"] == "esperando_decision"
    assert "ruega al superior" in valores(caso)["apertura"]["impugnacion"]
    assert api.ediciones(caso)["conflictos"] == []
    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert "ruega al superior" in seccion_del_prompt(cliente, "caso_concreto", "IMPUGNACION")


def test_decision_invalida_con_ediciones_sigue_esperando_la_decision(montaje):
    caso, cliente = montaje()
    editar(caso, ANTECEDENTES, lambda t: t.replace("dispuso la notificación", "dispuso con urgencia la notificación"), 1)
    antes = valores(caso)
    llamadas = list(cliente.llamadas)
    for _ in range(2):
        r = api.decidir(caso, INVALIDA)
        assert r["ok"] and r["estado"] == "esperando_decision" and r["payload"]["errores"]
        assert api.decidir(caso, {"accion": "inventada"})["estado"] == "esperando_decision"
    assert cliente.llamadas == llamadas
    assert api.estado(caso)["estado"] == "esperando_decision"
    despues = valores(caso)
    assert despues["apertura"] == antes["apertura"] and "ediciones_humanas" not in despues
    resp = api.ediciones(caso)
    assert resp["editable"] and resp["conflictos"] == []
    assert resp["piezas"][ANTECEDENTES]["editados"] == [1]
    assert "con urgencia" in vista_previo(caso, ANTECEDENTES)
    assert acciones_log(caso) == ["editar"]

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert "dispuso con urgencia la notificación" in seccion_del_prompt(cliente, "caso_concreto", "ANTECEDENTES")
    assert "dispuso con urgencia la notificación" in texto_docx(salidas.raiz(caso) / FALLO_DOCX)
    assert acciones_log(caso) == ["editar", "consolidar"]


def test_ediciones_no_editable_sin_hilo_ni_en_otro_estado(tmp_path, caso):
    resp = api.ediciones(caso)
    assert resp["editable"] is True and resp["motivo"] is None
    assert api.decidir(caso, DECISION)["estado"] == "terminado"
    terminado = api.ediciones(caso)
    assert terminado == {"editable": False, "motivo": terminado["motivo"], "piezas": {}, "conflictos": []} and terminado["motivo"]
    for llamar in (
        lambda: api.editar_pieza(caso, ANTECEDENTES, 0, "x", "y"),
        lambda: api.restaurar_pieza(caso, ANTECEDENTES),
        lambda: api.resolver_pieza(caso, ANTECEDENTES, ["mio"]),
    ):
        with pytest.raises(ed.ErrorEdicion) as e:
            llamar()
        assert e.value.estado == 409

    vacio = tmp_path / "casos" / "caso-vacio"
    (vacio / "insumos").mkdir(parents=True)
    sin_hilo = api.ediciones(vacio)
    assert sin_hilo["editable"] is False and sin_hilo["motivo"] and sin_hilo["piezas"] == {} and sin_hilo["conflictos"] == []
    assert not (vacio / "hilo.sqlite").exists()


def test_nuevo_borra_la_capa_y_su_bitacora(caso):
    editar(caso, ANTECEDENTES, lambda t: t.replace("dispuso la notificación", "dispuso con urgencia la notificación"), 1)
    assert (caso / ed.ARCHIVO).exists() and (caso / ed.LOG).exists()
    assert api.nuevo(caso, descartar=True)["estado"] == "revision"
    assert not (caso / ed.ARCHIVO).exists() and not (caso / ed.LOG).exists() and not (caso / "hilo.sqlite").exists()


def test_borrar_hilo_quita_los_archivos_de_ediciones(tmp_path):
    for nombre in ("hilo.sqlite", ed.ARCHIVO, ed.LOG, "decision.json"):
        (tmp_path / nombre).write_text("x", encoding="utf-8")
    api._borrar_hilo(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_un_estado_nuevo_con_la_capa_corrupta_no_rompe(caso):
    (caso / ed.ARCHIVO).write_text("{no es json", encoding="utf-8")
    resp = api.ediciones(caso)
    assert resp["editable"] and resp["conflictos"] == []
    editar(caso, ANTECEDENTES, lambda t: t.replace("dispuso la notificación", "dispuso con urgencia la notificación"), 1)
    assert json.loads((caso / ed.ARCHIVO).read_text(encoding="utf-8"))["piezas"][ANTECEDENTES]["texto"]


def capa_en_disco(caso) -> bytes | None:
    ruta = caso / ed.ARCHIVO
    return ruta.read_bytes() if ruta.exists() else None


@pytest.mark.parametrize("caracter", ["\x00", "\x07", "\x1b"])
def test_un_caracter_de_control_se_rechaza_con_422_y_no_deja_rastro(caso, http, caracter):
    original = parrafos_de(caso, ANTECEDENTES)[1]
    previo = (salidas.trabajo(caso) / "previo.docx").read_bytes()
    r = http.put(
        f"/api/casos/{caso.name}/ediciones/{ANTECEDENTES}",
        json={"parrafo": 1, "original": original, "texto": f"{original} pegado{caracter} fin"},
    )
    assert r.status_code == 422 and "control" in r.json()["detail"]
    assert capa_en_disco(caso) is None and acciones_log(caso) == []
    assert (salidas.trabajo(caso) / "previo.docx").read_bytes() == previo
    ok = editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)
    assert ok["editable"] and set(ed.leer(caso)["piezas"]) == {IMPUGNACION}
    assert api.estado(caso)["estado"] == "esperando_decision"
    assert api.decidir(caso, DECISION)["estado"] == "terminado"


def falla_una_vez(monkeypatch) -> list[int]:
    llamadas: list[int] = []
    real = api.render.render_previo

    def fragil(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise OSError("disco lleno")
        return real(*args, **kwargs)

    monkeypatch.setattr(api.render, "render_previo", fragil)
    return llamadas


def test_si_el_previo_no_se_puede_regenerar_la_edicion_no_se_guarda(caso, monkeypatch):
    previo = (salidas.trabajo(caso) / "previo.docx").read_bytes()
    original = parrafos_de(caso, IMPUGNACION)[3]
    cambio = original.replace("solicita al superior", "pide al superior")
    llamadas = falla_una_vez(monkeypatch)
    with pytest.raises(OSError):
        api.editar_pieza(caso, IMPUGNACION, 3, original, cambio)
    assert capa_en_disco(caso) is None and acciones_log(caso) == []
    assert (salidas.trabajo(caso) / "previo.docx").read_bytes() == previo
    assert api.ediciones(caso)["piezas"][IMPUGNACION]["editados"] == []

    r = api.editar_pieza(caso, IMPUGNACION, 3, original, cambio)
    assert r["piezas"][IMPUGNACION]["editados"] == [3] and len(llamadas) == 2
    assert "pide al superior" in vista_previo(caso, IMPUGNACION)
    assert acciones_log(caso) == ["editar"]
    assert api.decidir(caso, DECISION)["estado"] == "terminado"


def test_si_el_previo_no_se_puede_regenerar_el_rebase_no_se_guarda(caso, monkeypatch):
    editar(caso, IMPUGNACION, lambda t: t.replace("solicita al superior", "pide al superior"), 3)
    capa = ed.leer(caso)
    e = capa["piezas"][IMPUGNACION]
    ia = e["ia"].split("\n\n")
    viejo = ["Primer párrafo anterior de la IA.", *ia[1:]]
    e.update(ia="\n\n".join(viejo), consolidado="\n\n".join(viejo), texto="\n\n".join([*viejo[:3], e["texto"].split("\n\n")[3], *viejo[4:]]))
    ed.guardar(caso, capa)
    atrasada = capa_en_disco(caso)
    llamadas = falla_una_vez(monkeypatch)
    with pytest.raises(OSError):
        api.ediciones(caso)
    assert capa_en_disco(caso) == atrasada and acciones_log(caso) == ["editar"]

    resp = api.ediciones(caso)
    assert len(llamadas) == 2 and capa_en_disco(caso) != atrasada
    assert "pide al superior" in resp["piezas"][IMPUGNACION]["parrafos"][3]
    assert "pide al superior" in vista_previo(caso, IMPUGNACION)
    assert acciones_log(caso)[0] == "editar" and "rebase" in acciones_log(caso)


def test_si_no_se_puede_guardar_la_capa_el_previo_vuelve_a_reflejar_la_capa_anterior(caso, monkeypatch):
    original = parrafos_de(caso, IMPUGNACION)[3]
    cambio = original.replace("solicita al superior", "pide al superior")

    def sin_disco(*args, **kwargs):
        raise OSError("sin espacio")

    monkeypatch.setattr(api.ed, "guardar", sin_disco)
    with pytest.raises(OSError):
        api.editar_pieza(caso, IMPUGNACION, 3, original, cambio)
    assert capa_en_disco(caso) is None and acciones_log(caso) == []
    assert "pide al superior" not in texto_docx(salidas.trabajo(caso) / "previo.docx")
    assert "pide al superior" not in vista_previo(caso)
    assert "solicita al superior" in vista_previo(caso, IMPUGNACION)


def test_si_falla_solo_la_linea_de_auditoria_la_capa_y_el_previo_quedan_con_la_edicion(caso, monkeypatch):
    original = parrafos_de(caso, IMPUGNACION)[3]
    cambio = original.replace("solicita al superior", "pide al superior")

    def sin_log(*args, **kwargs):
        raise OSError("no se pudo escribir la bitácora")

    monkeypatch.setattr(api.ed, "registrar", sin_log)
    with pytest.raises(OSError):
        api.editar_pieza(caso, IMPUGNACION, 3, original, cambio)
    assert "pide al superior" in ed.leer(caso)["piezas"][IMPUGNACION]["texto"]
    assert "pide al superior" in vista_previo(caso, IMPUGNACION)
    assert "pide al superior" in texto_docx(salidas.trabajo(caso) / "previo.docx")
