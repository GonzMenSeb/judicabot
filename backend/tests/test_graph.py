from __future__ import annotations

import hashlib
import json
import sqlite3
import types

import anthropic
import pytest

try:
    import httpx2 as httpx
except ImportError:
    import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from test_llm import sse
from tutela2 import api, cli, graph, ingest, llm, prompts
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.llm import AnthropicClient, ErrorLLM, FakeClient
from tutela2.models import (
    AperturaLLM,
    Contestacion,
    CasoConcretoLLM,
    CitaVerificada,
    ConsideracionesLLM,
    Doc,
    Fechas,
    Ingesta,
    Metadatos,
    MetadatosLLM,
    Pagina,
)

ESCRITO = (
    "La accionante Marta Ejemplo presentó acción de tutela contra la Entidad Prestadora Uno por considerar vulnerados sus derechos "
    "fundamentales a la salud y a la vida digna. Afirma que la entidad no autorizó el procedimiento ordenado por su médico tratante "
    "desde hace varios meses y que su estado de salud empeora cada día. Solicita que se ordene la autorización inmediata del "
    "procedimiento y el suministro de los insumos requeridos para su recuperación."
)
ADMISORIO = (
    "El Juzgado Primero Municipal admitió la acción de tutela, ordenó notificar a la entidad accionada y vinculó a la Secretaría de "
    "Salud para que se pronunciara sobre los hechos y aportara las pruebas que tuviera en su poder dentro del término concedido."
)
CONTESTACION = (
    "La Entidad Prestadora Uno respondió que el procedimiento fue programado y que no existe vulneración alguna de los derechos de la "
    "accionante, por lo cual solicitó que se declare la improcedencia de la acción de tutela por carencia actual de objeto."
)
FALLO = (
    "El Juzgado Primero Municipal negó el amparo solicitado por considerar que la accionante dispone de otros mecanismos de defensa y "
    "que no se acreditó un perjuicio irremediable que habilitara la intervención del juez constitucional en este asunto."
)
IMPUGNACION_P1 = (
    "La accionante impugna el fallo porque el juez de primera instancia desconoció que el procedimiento ordenado por el médico tratante "
    "no ha sido autorizado y que cada día de espera agrava su condición de salud, de manera que existe un riesgo cierto para su vida."
)
IMPUGNACION_P2 = (
    "Además sostiene que el juez no valoró los conceptos médicos aportados con la tutela, en los cuales consta la urgencia del "
    "procedimiento, y pide que se revoque la decisión y se conceda el amparo de sus derechos fundamentales de manera inmediata."
)
CONCEDE = (
    "El Juzgado Primero Municipal concedió la impugnación presentada por la accionante y ordenó remitir el expediente al superior "
    "jerárquico para que se surta la segunda instancia conforme a lo dispuesto en el decreto reglamentario de la acción de tutela."
)
ACTA = (
    "Acta de reparto de la impugnación de tutela asignada al Juzgado Tercero Penal del Circuito. Accionante Marta Ejemplo. "
    "Accionado Entidad Prestadora Uno. Procedencia Juzgado Primero Municipal."
)


def _doc(instancia: str, i: int, rol: str, nombre: str, paginas: list[str]) -> Doc:
    return Doc(
        doc_id=f"{instancia}-{i:03d}",
        ruta=f"{instancia}/{nombre}",
        nombre=nombre,
        instancia=instancia,
        rol=rol,
        sha256=hashlib.sha256(nombre.encode()).hexdigest(),
        paginas=[Pagina(n=n, texto=t) for n, t in enumerate(paginas, 1)],
    )


def ingesta_sintetica(faltantes: list[str] | None = None) -> Ingesta:
    docs = [
        _doc("1a", 1, "escrito_tutela", "003EscritoTutela.pdf", [ESCRITO]),
        _doc("1a", 2, "auto_admisorio", "004AutoAdmision.pdf", [ADMISORIO]),
        _doc("1a", 3, "contestacion", "005RespuestaEntidadUno.pdf", [CONTESTACION]),
        _doc("1a", 4, "fallo_a_quo", "006FalloTutela.pdf", [FALLO]),
        _doc("1a", 5, "impugnacion", "008ImpugnacionTutela.pdf", [IMPUGNACION_P1, IMPUGNACION_P2]),
        _doc("1a", 6, "auto_concede_impugnacion", "009AutoConcedeImpugnacion.pdf", [CONCEDE]),
        _doc("2a", 7, "acta_reparto_2a", "001ActaRepartoSegunda.pdf", [ACTA]),
    ]
    return Ingesta(
        documentos=docs,
        faltantes=faltantes or [],
        metadatos=Metadatos(
            cui_1a="05001400900120260000100",
            cui_2a="05001400900120260000101",
            juzgado_a_quo="Juzgado Primero Municipal",
            accionante="Marta Ejemplo",
            accionadas=["Entidad Prestadora Uno"],
            fechas=Fechas(fallo_a_quo="2026-09-21", reparto_2a="2026-10-05"),
        ),
    )


PRINCIPAL = "02SegundaInstancia/C01Principal"
AUTO = f"{PRINCIPAL}/001AutoAsumeSegunda202600001.docx"
FALLO_DOCX = f"{PRINCIPAL}/002FalloSegunda202600001.docx"

DECISION = {
    "accion": "decidir",
    "resultado": "REVOCAR",
    "sustitutiva": "AMPARAR",
    "eje": "La entidad no acreditó la autorización del procedimiento y la demora compromete la salud de la accionante.",
    "por_reparo": [{"reparo_id": "R1", "disposicion": "ACOGE"}],
    "ordenes": [
        {
            "destinatario": "Entidad Prestadora Uno",
            "conducta": "autorice el procedimiento ordenado por el médico tratante",
        }
    ],
    "decidido_por": "Oficial Mayor",
}


class Verificador:
    def __init__(self, rechazar_c1_primeras: int = 0):
        self.rechazar = rechazar_c1_primeras
        self.llamadas = 0

    def __call__(self, propuestas, cfg, dataset):
        self.llamadas += 1
        salida = []
        for c in propuestas:
            tipo, numero, anio = citas_real.normalizar_sentencia(c.sentencia)
            rechazada = c.id == "c1" and self.llamadas <= self.rechazar
            salida.append(
                CitaVerificada(
                    id=c.id,
                    sentencia_original=c.sentencia,
                    sentencia_norm=citas_real.clave_dataset(tipo, numero, anio),
                    tipo=tipo,
                    numero=numero,
                    anio=anio,
                    texto_citado=c.texto_citado,
                    reparo_ids=c.reparo_ids,
                    en_dataset=True,
                    mp_dataset="José Fernando Reyes Cuartas",
                    url="https://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm",
                    pagina_ok=not rechazada,
                    cobertura=0.1 if rechazada else 1.0,
                    estado="rechazada" if rechazada else "ok",
                    motivos=["El pasaje no se localizó en la sentencia."] if rechazada else [],
                )
            )
        return salida


class ClienteCorrupto:
    def __init__(self, base: FakeClient, veces: int = 1):
        self.base, self.veces, self.n = base, veces, 0

    @property
    def llamadas(self):
        return self.base.llamadas

    def estructurado(self, nodo, system, user, schema, cfg):
        salida, meta = self.base.estructurado(nodo, system, user, schema, cfg)
        if nodo == "apertura" and self.n < self.veces:
            self.n += 1
            salida.cronologia[0].cita_literal = "frase que no figura en ningún documento del expediente de ejemplo"
        return salida, meta


class ClienteConEje:
    def __init__(self, base: FakeClient, eje: str):
        self.base, self.eje = base, eje

    def estructurado(self, nodo, system, user, schema, cfg):
        salida, meta = self.base.estructurado(nodo, system, user, schema, cfg)
        if nodo == "caso_concreto":
            salida.parrafos[0].texto += " " + self.eje
        return salida, meta


class ClienteSinReparos:
    def __init__(self, base: FakeClient):
        self.base = base

    @property
    def llamadas(self):
        return self.base.llamadas

    def estructurado(self, nodo, system, user, schema, cfg):
        salida, meta = self.base.estructurado(nodo, system, user, schema, cfg)
        if nodo == "apertura":
            salida.reparos = []
        return salida, meta


class ClienteCaido:
    def __init__(self, base: FakeClient, nodo: str):
        self.base, self.nodo, self.activo = base, nodo, True

    def estructurado(self, nodo, system, user, schema, cfg):
        if self.activo and nodo == self.nodo:
            raise ErrorLLM("El modelo rechazó la solicitud (stop_reason=refusal).")
        return self.base.estructurado(nodo, system, user, schema, cfg)


@pytest.fixture
def cfg() -> Config:
    return Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)


@pytest.fixture(autouse=True)
def verificador(monkeypatch):
    v = Verificador()
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", v)
    return v


def hilo(nombre: str = "caso-1") -> dict:
    return {"configurable": {"thread_id": nombre}}


def pendientes(g, h) -> list:
    return [i.value for t in g.get_state(h).tasks for i in t.interrupts]


def arrancar(cfg, tmp_path, cliente=None, saver=None):
    cliente = cliente or FakeClient()
    g = graph.construir(cfg, cliente, saver or InMemorySaver())
    h = hilo()
    entrada = graph.estado_inicial(tmp_path / "caso-1", cfg, ingesta_sintetica())
    g.invoke(entrada, h, durability="sync")
    return g, h, cliente


def test_topologia_exacta(cfg, tmp_path):
    g = graph.construir(cfg, FakeClient(), InMemorySaver())
    aristas = {(e.source, e.target) for e in g.get_graph().edges}
    assert aristas == {
        ("__start__", "apertura"),
        ("apertura", "validar_apertura"),
        ("validar_apertura", "apertura"),
        ("validar_apertura", "consideraciones"),
        ("consideraciones", "verificar_consideraciones"),
        ("verificar_consideraciones", "consideraciones"),
        ("verificar_consideraciones", "decision"),
        ("decision", "apertura"),
        ("decision", "consideraciones"),
        ("decision", "caso_concreto"),
        ("caso_concreto", "validar_caso"),
        ("validar_caso", "caso_concreto"),
        ("validar_caso", "ensamblar"),
        ("ensamblar", "__end__"),
    }


def test_pausa_antes_de_decidir(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    snap = g.get_state(h)
    assert snap.next == ("decision",)
    payload = pendientes(g, h)[0]
    assert [r["id"] for r in payload["reparos"]] == ["R1", "R2", "R3"]
    assert {c["id"] for c in payload["citas"]} == {"c1", "c2"}
    assert payload["errores"] == []
    assert payload["derechos_invocados"] == ["salud", "vida"]
    assert [n for n, _ in cliente.llamadas] == ["apertura", "consideraciones"]
    v = snap.values
    assert [b["nodo"] for b in v["bitacora"]] == ["apertura", "consideraciones"]
    assert v["bitacora"][0]["prompt_id"] == f"apertura@{prompts.version_default('apertura')}"
    assert (
        v["bitacora"][0]["sha256_instrucciones"]
        == hashlib.sha256(prompts.prompt_default("apertura").encode()).hexdigest()
    )
    assert v["metadatos"]["accionante"] == "Marta Ejemplo"
    assert v["metadatos"]["decision_a_quo"] == "negó el amparo solicitado"
    assert v["intentos"] == {"apertura": 1, "consideraciones": 1}
    assert v["decisiones"] == [] and v["caso"] is None


def test_consideraciones_no_recibe_documentos(cfg, tmp_path):
    _, _, cliente = arrancar(cfg, tmp_path)
    user = dict(cliente.llamadas)["consideraciones"]
    assert "### DOC" not in user
    assert "R1" in user and "Máximo de bloques temáticos: 3" in user


def test_flujo_completo(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    salida = g.invoke(Command(resume=DECISION), h, durability="sync")
    assert "__interrupt__" not in salida
    snap = g.get_state(h)
    assert snap.next == ()
    v = snap.values
    assert [d["accion"] for d in v["decisiones"]] == ["decidir"]
    assert v["decisiones"][0]["fecha"]
    assert [b["nodo"] for b in v["bitacora"]] == ["apertura", "consideraciones", "caso_concreto"]
    assert "revocar" in v["caso"]["conclusion"] and "amparar" in v["caso"]["conclusion"]
    assert "[[CITA:" in " ".join(p["texto"] for p in v["caso"]["parrafos"])
    assert set(v["salidas"]) == {
        f"{PRINCIPAL}/001AutoAsumeSegunda202600001.docx",
        f"{PRINCIPAL}/002FalloSegunda202600001.docx",
        "por_radicar/OficioRemiteCorteConstitucional.docx",
        "borradores_correo/NotificacionFalloPartes.docx",
        "trabajo/informe_verificacion.docx",
        "trabajo/declaracion_ia.docx",
    }
    for nombre, sha in v["salidas"].items():
        ruta = tmp_path / "caso-1" / "salidas" / nombre
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == sha
    user_caso = cliente.llamadas[-1][1]
    assert DECISION["eje"] in user_caso
    assert "Sentencia T-200 de 2022, con ponencia del Magistrado José Fernando Reyes Cuartas" in user_caso


def test_caso_concreto_solo_recibe_citas_aprobadas(cfg, tmp_path, verificador):
    verificador.rechazar = 99
    g, h, cliente = arrancar(cfg, tmp_path)
    assert pendientes(g, h)
    g.invoke(Command(resume=DECISION), h, durability="sync")
    user_caso = [u for n, u in cliente.llamadas if n == "caso_concreto"][0]
    citas_json = json.loads(user_caso.split("=== CITAS ===\n")[1].split("\n=== ")[0])
    assert [c["id"] for c in citas_json] == ["c2"]


def test_decision_invalida_reinterrumpe(cfg, tmp_path):
    g, h, _ = arrancar(cfg, tmp_path)
    incompleta = {"accion": "decidir", "resultado": "REVOCAR"}
    out = g.invoke(Command(resume=incompleta), h, durability="sync")
    errores = out["__interrupt__"][0].value["errores"]
    assert any("sustitutiva" in e for e in errores) and any("eje" in e for e in errores)
    assert g.get_state(h).values["decisiones"] == []

    out = g.invoke(Command(resume={"accion": "inventada"}), h, durability="sync")
    errores = out["__interrupt__"][0].value["errores"]
    assert errores and any("accion" in e for e in errores)
    assert g.get_state(h).next == ("decision",)
    assert g.get_state(h).values["decisiones"] == []

    out = g.invoke(
        Command(resume={"accion": "decidir", "resultado": "REVOCAR", "sustitutiva": "AMPARAR", "eje": "x"}),
        h,
        durability="sync",
    )
    assert any("orden" in e for e in out["__interrupt__"][0].value["errores"])

    out = g.invoke(Command(resume=DECISION), h, durability="sync")
    assert "__interrupt__" not in out
    assert len(g.get_state(h).values["decisiones"]) == 1


def test_rehacer_consideraciones(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    rehacer = {"accion": "rehacer_consideraciones", "instruccion": "Enfócate en la subsidiariedad."}
    out = g.invoke(Command(resume=rehacer), h, durability="sync")
    assert out["__interrupt__"]
    llamadas = cliente.llamadas
    assert [n for n, _ in llamadas] == ["apertura", "consideraciones", "consideraciones"]
    assert "=== INSTRUCCION ===\nEnfócate en la subsidiariedad." in llamadas[2][1]
    assert "INSTRUCCION" not in llamadas[1][1]
    v = g.get_state(h).values
    assert v["intentos"] == {"apertura": 1, "consideraciones": 1}
    assert [d["accion"] for d in v["decisiones"]] == ["rehacer_consideraciones"]

    g.invoke(Command(resume=DECISION), h, durability="sync")
    assert g.get_state(h).next == ()
    assert "INSTRUCCION" not in cliente.llamadas[-1][1]


def test_rehacer_apertura_reinicia_consideraciones(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    g.invoke(
        Command(resume={"accion": "rehacer_apertura", "instruccion": "Incluye la contestación."}), h, durability="sync"
    )
    assert [n for n, _ in cliente.llamadas] == ["apertura", "consideraciones", "apertura", "consideraciones"]
    assert "Incluye la contestación." in cliente.llamadas[2][1]
    assert "INSTRUCCION" not in cliente.llamadas[3][1]
    assert g.get_state(h).next == ("decision",)
    assert g.get_state(h).values["intentos"]["apertura"] == 1


def test_reintento_por_cita_literal_ajena(cfg, tmp_path):
    cliente = ClienteCorrupto(FakeClient(), veces=1)
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    apertura = [u for n, u in cliente.llamadas if n == "apertura"]
    assert len(apertura) == 2
    assert "=== ERRORES ===" not in apertura[0] and "=== ERRORES ===" in apertura[1]
    assert "SALIDA ANTERIOR" not in apertura[0]
    previa = json.loads(llm.leer_secciones(apertura[1])["SALIDA ANTERIOR"])
    assert previa["cronologia"][0]["cita_literal"].startswith("frase que no figura")
    assert apertura[1].index("=== SALIDA ANTERIOR ===") < apertura[1].index("=== ERRORES ===")
    v = g.get_state(h).values
    assert v["intentos"]["apertura"] == 2
    assert not [m for m in v["alertas"]["apertura"] if m.startswith("BLOQUEA:")]
    assert "Se agotaron" not in " ".join(v["alertas"]["apertura"])


def test_intentos_agotados_siguen_con_alertas(cfg, tmp_path):
    cliente = ClienteCorrupto(FakeClient(), veces=99)
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    assert len([n for n, _ in cliente.llamadas if n == "apertura"]) == cfg.max_intentos
    v = g.get_state(h).values
    assert g.get_state(h).next == ("decision",)
    assert any(m.startswith("BLOQUEA:") for m in v["alertas"]["apertura"])
    assert any("Se agotaron" in m for m in v["alertas"]["apertura"])
    consideraciones = [u for n, u in cliente.llamadas if n == "consideraciones"][0]
    assert "ERRORES" not in consideraciones


def test_cita_rechazada_vuelve_a_consideraciones(cfg, tmp_path, verificador):
    verificador.rechazar = 1
    g, h, cliente = arrancar(cfg, tmp_path)
    cons = [u for n, u in cliente.llamadas if n == "consideraciones"]
    assert len(cons) == 2
    assert "cambia la cita, nunca la tesis" in cons[1]
    assert "=== SALIDA ANTERIOR ===" not in cons[0]
    previa = llm.leer_secciones(cons[1])["SALIDA ANTERIOR"]
    assert json.loads(previa)["bloques"][0]["titulo"] == "La carencia actual de objeto por hecho superado"
    assert cons[1].index("=== SALIDA ANTERIOR ===") < cons[1].index("=== ERRORES ===")
    v = g.get_state(h).values
    assert v["intentos"]["consideraciones"] == 2
    assert {c["estado"] for c in v["citas"]} == {"ok"}
    assert v["errores"] == []


def test_reanudar_tras_error_del_modelo(cfg, tmp_path):
    ruta = tmp_path / "hilo.sqlite"

    def abrir(cliente):
        conexion = sqlite3.connect(ruta, check_same_thread=False)
        return conexion, graph.construir(cfg, cliente, SqliteSaver(conexion))

    caido = ClienteCaido(FakeClient(), "consideraciones")
    conexion, g = abrir(caido)
    entrada = graph.estado_inicial(tmp_path / "caso-1", cfg, ingesta_sintetica())
    with pytest.raises(ErrorLLM):
        g.invoke(entrada, hilo(), durability="sync")
    snap = g.get_state(hilo())
    assert snap.next == ("consideraciones",)
    assert "refusal" in str(snap.tasks[0].error)
    conexion.close()

    conexion, g = abrir(FakeClient())
    g.invoke(None, hilo(), durability="sync")
    assert g.get_state(hilo()).next == ("decision",)
    assert pendientes(g, hilo())
    conexion.close()

    conexion, g = abrir(FakeClient())
    g.invoke(Command(resume=DECISION), hilo(), durability="sync")
    assert g.get_state(hilo()).next == ()
    assert g.get_state(hilo()).values["salidas"]
    conexion.close()


def test_prompt_override_se_usa_y_queda_en_bitacora(tmp_path):
    cfg = Config(
        llm=LLMConfig(proveedor="fake"),
        verificar_relatoria=False,
        prompts_override={"apertura": "Instrucciones propias."},
    )
    g, h, _ = arrancar(cfg, tmp_path)
    primera = g.get_state(h).values["bitacora"][0]
    assert primera["prompt_id"] == "apertura@override"
    assert primera["sha256_instrucciones"] == hashlib.sha256(b"Instrucciones propias.").hexdigest()


@pytest.fixture
def caso(tmp_path, cfg, monkeypatch):
    carpeta = tmp_path / "casos" / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    return carpeta


def test_api_incompleto(caso, monkeypatch):
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(["impugnacion"]), raising=False)
    r = api.nuevo(caso)
    assert r["ok"] and r["estado"] == "incompleto"
    assert r["resumen"]["faltantes"] == ["impugnacion"]
    assert {"trabajo/requerimiento.docx"} <= set(r["salidas"])
    assert not (caso / "hilo.sqlite").exists()
    assert (caso / "caso.json").exists()
    assert api.estado(caso)["estado"] == "incompleto"


def test_api_ciclo_completo(caso):
    assert api.estado(caso)["estado"] == "sin_iniciar"
    r = api.nuevo(caso)
    assert r["ok"] and r["estado"] == "revision", r["error"]
    assert Ingesta.model_validate_json((caso / "caso.json").read_text(encoding="utf-8")).completo
    assert r["salidas"] == [AUTO]
    assert api.estado(caso)["estado"] == "revision"
    r = api.iniciar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    assert {AUTO, "trabajo/previo.docx"} <= set(r["salidas"])
    assert r["payload"]["accionadas"] == ["Entidad Prestadora Uno"] and r["payload"]["fecha_hoy"]
    assert [x["id"] for x in r["payload"]["reparos"]] == ["R1", "R2", "R3"]
    assert [b["nodo"] for b in r["resumen"]["bitacora"]] == ["apertura", "consideraciones"]
    assert r["resumen"]["apertura"]["reparos"] and r["resumen"]["citas"]
    assert json.dumps(r)

    e = api.estado(caso)
    assert e["estado"] == "esperando_decision" and e["payload"] == r["payload"]

    previo = hashlib.sha256((caso / "salidas" / "trabajo" / "previo.docx").read_bytes()).hexdigest()
    r = api.decidir(caso, {"accion": "decidir", "resultado": "REVOCAR"})
    assert r["ok"] and r["estado"] == "esperando_decision"
    assert r["payload"]["errores"]
    assert hashlib.sha256((caso / "salidas" / "trabajo" / "previo.docx").read_bytes()).hexdigest() == previo

    r = api.decidir(caso, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert {FALLO_DOCX, "trabajo/informe_verificacion.docx", "trabajo/declaracion_ia.docx", "trabajo/previo.docx", AUTO} <= set(
        r["salidas"]
    )
    guardada = json.loads((caso / "decision.json").read_text(encoding="utf-8"))
    assert guardada["resultado"] == "REVOCAR"
    registro = r["resumen"]["decision"]
    assert registro["previo_sha256"] == previo and registro["accion"] == "decidir"
    assert r["resumen"]["caso_concreto"]["conclusion"]

    assert api.estado(caso)["estado"] == "terminado"
    assert api.decidir(caso, DECISION)["ok"] is False
    assert api.continuar(caso)["estado"] == "terminado"


def test_api_rehacer_regenera_previo(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    previo = caso / "salidas" / "trabajo" / "previo.docx"
    previo.write_bytes(b"obsoleto")
    r = api.decidir(caso, {"accion": "rehacer_consideraciones", "instruccion": "Más breve."})
    assert r["estado"] == "esperando_decision"
    assert previo.read_bytes() != b"obsoleto"
    assert [b["nodo"] for b in r["resumen"]["bitacora"]] == ["apertura", "consideraciones", "consideraciones"]


def test_api_error_y_continuar(caso, monkeypatch):
    caido = ClienteCaido(FakeClient(), "consideraciones")
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: caido)
    api.nuevo(caso)
    r = api.iniciar(caso)
    assert not r["ok"] and r["estado"] == "error" and "refusal" in r["error"]
    e = api.estado(caso)
    assert e["estado"] == "error" and "consideraciones" in e["error"]

    caido.activo = False
    r = api.continuar(caso)
    assert r["ok"] and r["estado"] == "esperando_decision"
    assert "trabajo/previo.docx" in r["salidas"]


def test_api_nuevo_reinicia_el_hilo(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    api.decidir(caso, DECISION)
    assert (caso / "salidas" / FALLO_DOCX).exists() and (caso / "decision.json").exists()
    r = api.nuevo(caso)
    assert r["estado"] == "revision"
    assert r["salidas"] == [AUTO]
    assert not (caso / "decision.json").exists() and not (caso / "hilo.sqlite").exists()


def test_api_nuevo_incompleto_no_deja_salidas_viejas(caso, monkeypatch):
    api.nuevo(caso)
    api.iniciar(caso)
    api.decidir(caso, DECISION)
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(["impugnacion"]), raising=False)
    r = api.nuevo(caso)
    assert r["estado"] == "incompleto"
    assert set(r["salidas"]) == {AUTO, "trabajo/requerimiento.docx"}


def test_api_defaults():
    assert api.config_default() == Config().model_dump()
    assert set(api.prompts_default()) == {"apertura", "consideraciones", "caso_concreto"}
    assert all(api.prompts_default().values())


def test_cli(caso, capsys):
    assert cli.main(["config-default"]) == 0
    assert json.loads(capsys.readouterr().out)["max_intentos"] == 3
    assert cli.main(["nuevo", "--caso", str(caso)]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "revision"
    assert cli.main(["revisar", "--caso", str(caso)]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "revision"
    assert cli.main(["iniciar", "--caso", str(caso)]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "esperando_decision"
    archivo = caso / "d.json"
    archivo.write_text(json.dumps(DECISION), encoding="utf-8")
    assert cli.main(["decidir", "--caso", str(caso), "--decision", str(archivo)]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "terminado"
    assert cli.main(["estado", "--caso", str(caso)]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["nuevo"])


class SDKFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.messages = self
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream_beta))

    def _stream_beta(self, **kwargs):
        return self.stream(**kwargs, _beta=True)

    def with_options(self, **opciones):
        return self

    def stream(self, **kwargs):
        self.llamadas.append(kwargs)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return FlujoFalso(r)


class FlujoFalso:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.final


def respuesta_sdk(parsed, stop="end_turn"):
    uso = types.SimpleNamespace(input_tokens=10, output_tokens=5)
    contenido = [types.SimpleNamespace(type="text", text=parsed.model_dump_json())] if parsed else []
    return types.SimpleNamespace(content=contenido, stop_reason=stop, model="claude-efectivo", usage=uso)


def error_400(mensaje):
    return anthropic.BadRequestError(
        mensaje, response=types.SimpleNamespace(status_code=400, headers={}, request=None), body=None
    )


CASO = CasoConcretoLLM(problema_juridico="p", parrafos=[], conclusion="c")


def test_anthropic_envia_los_parametros_del_contrato():
    sdk = SDKFalso(respuesta_sdk(CASO))
    cfg = Config(
        llm=LLMConfig(
            modelo="claude-opus-5-5",
            effort="high",
            effort_por_nodo={"caso_concreto": "max"},
            modelo_por_nodo={"apertura": "claude-sonnet-5-5"},
        )
    )
    salida, meta = AnthropicClient(sdk).estructurado("caso_concreto", "sistema", "usuario", CasoConcretoLLM, cfg)
    assert salida == CASO
    assert meta == {
        "modelo_efectivo": "claude-efectivo",
        "tokens_entrada": 10,
        "tokens_salida": 5,
        "stop_reason": "end_turn",
    }
    args = sdk.llamadas[0]
    assert args["model"] == "claude-opus-5-5" and args["output_config"]["effort"] == "max"
    assert args["output_config"]["format"]["type"] == "json_schema" and args["system"] == "sistema"
    assert args["messages"] == [{"role": "user", "content": "usuario"}]
    assert args["max_tokens"] == cfg.llm.max_tokens and args["timeout"] == cfg.llm.timeout_s
    assert "temperature" not in args and "thinking" not in args
    assert args["betas"] == ["server-side-fallback-2026-07-01"] and args["fallbacks"] == "default"
    sdk2 = SDKFalso(respuesta_sdk(CASO))
    AnthropicClient(sdk2).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    assert sdk2.llamadas[0]["model"] == "claude-sonnet-5-5"


def test_anthropic_sin_fallbacks_no_usa_el_stream_beta():
    sdk = SDKFalso(respuesta_sdk(CASO))
    cfg = Config(llm=LLMConfig(fallbacks_default=False))
    AnthropicClient(sdk).estructurado("apertura", "s", "u", CasoConcretoLLM, cfg)
    args = sdk.llamadas[0]
    assert "_beta" not in args and "betas" not in args and "fallbacks" not in args


def test_anthropic_reintenta_sin_fallbacks_si_la_api_los_rechaza():
    sdk = SDKFalso(error_400("Unknown parameter: fallbacks"), respuesta_sdk(CASO))
    AnthropicClient(sdk).estructurado("apertura", "s", "u", CasoConcretoLLM, Config())
    assert len(sdk.llamadas) == 2
    assert "fallbacks" in sdk.llamadas[0] and "fallbacks" not in sdk.llamadas[1]
    assert "_beta" in sdk.llamadas[0] and "_beta" not in sdk.llamadas[1]


def test_anthropic_no_reintenta_otros_400():
    sdk = SDKFalso(error_400("prompt demasiado largo"))
    with pytest.raises(ErrorLLM, match="prompt demasiado largo"):
        AnthropicClient(sdk).estructurado("apertura", "s", "u", CasoConcretoLLM, Config())
    assert len(sdk.llamadas) == 1


@pytest.mark.parametrize(
    "respuesta, texto",
    [
        (respuesta_sdk(None, "refusal"), "rechazó"),
        (respuesta_sdk(None, "max_tokens"), "límite de tokens"),
        (respuesta_sdk(None, "end_turn"), "salida estructurada"),
    ],
)
def test_anthropic_errores_claros(respuesta, texto):
    with pytest.raises(ErrorLLM, match=texto):
        AnthropicClient(SDKFalso(respuesta)).estructurado("apertura", "s", "u", CasoConcretoLLM, Config())


class ClienteCaso:
    def __init__(self, base: FakeClient, **cambios):
        self.base, self.cambios = base, cambios

    @property
    def llamadas(self):
        return self.base.llamadas

    def estructurado(self, nodo, system, user, schema, cfg):
        salida, meta = self.base.estructurado(nodo, system, user, schema, cfg)
        if nodo == "apertura":
            for k, v in self.cambios.items():
                setattr(salida.metadatos, k, v)
        return salida, meta


def test_caso_concreto_reintenta_con_su_salida_anterior(cfg, tmp_path):
    class Contradictorio:
        def __init__(self):
            self.base, self.n = FakeClient(), 0

        @property
        def llamadas(self):
            return self.base.llamadas

        def estructurado(self, nodo, system, user, schema, c):
            salida, meta = self.base.estructurado(nodo, system, user, schema, c)
            if nodo == "caso_concreto" and self.n == 0:
                self.n += 1
                salida.conclusion = "El Despacho revocará el fallo, que amparó, y en su lugar se negará el amparo."
            return salida, meta

    cliente = Contradictorio()
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    g.invoke(Command(resume=DECISION), h, durability="sync")
    casos = [u for n, u in cliente.llamadas if n == "caso_concreto"]
    assert len(casos) == 2
    previa = json.loads(llm.leer_secciones(casos[1])["SALIDA ANTERIOR"])
    assert "se negará el amparo" in previa["conclusion"]
    assert "sustitutiva" in llm.leer_secciones(casos[1])["ERRORES"]
    assert g.get_state(h).values["intentos"]["caso_concreto"] == 2


def test_identificacion_nit_y_fecha_inventados_en_metadatos_bloquean(cfg, tmp_path):
    cliente = ClienteCaso(
        FakeClient(),
        accionante_identificacion="identificada con cédula de ciudadanía 98.765.432",
        impugnantes=["la sociedad Inventada S.A.S. con NIT 900.999.888-1"],
        resultado_a_quo="negó el amparo el 15/02/2026",
    )
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    v = g.get_state(h).values
    msgs = [m for m in v["alertas"]["apertura"] if m.startswith("BLOQUEA:")]
    assert any("98765432" in m and "accionante_identificacion" in m for m in msgs)
    assert any("900999888" in m and "impugnantes" in m for m in msgs)
    assert any("15/02/2026" in m and "resultado_a_quo" in m for m in msgs)
    assert v["intentos"]["apertura"] == cfg.max_intentos


def test_identificacion_presente_en_los_documentos_no_bloquea(cfg, tmp_path):
    ing = ingesta_sintetica()
    ing.documentos[0].paginas[0].texto += " La accionante se identifica con la cédula de ciudadanía 43.123.456."
    cliente = ClienteCaso(FakeClient(), accionante_identificacion="identificada con cédula de ciudadanía 43.123.456")
    g = graph.construir(cfg, cliente, InMemorySaver())
    g.invoke(graph.estado_inicial(tmp_path / "caso-1", cfg, ing), hilo(), durability="sync")
    assert not [m for m in g.get_state(hilo()).values["alertas"]["apertura"] if m.startswith("BLOQUEA:")]


def test_metadatos_del_modelo_se_muestran_al_juez_en_la_decision(cfg, tmp_path):
    cliente = ClienteCaso(FakeClient(), accionante_tratamiento="la señora", resultado_a_quo="negó el amparo")
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    payload = pendientes(g, h)[0]
    assert payload["accionante_tratamiento"] == "la señora" and payload["resultado_a_quo"] == "negó el amparo"
    assert payload["impugnantes"] and "accionante_identificacion" in payload


def test_diferencia_entre_ingesta_y_modelo_se_alerta(cfg, tmp_path):
    cliente = ClienteCaso(FakeClient(), accionante="MARTA EJEMPLÓ", accionadas=["Entidad Prestadora Uno"])
    g, h, _ = arrancar(cfg, tmp_path, cliente=cliente)
    v = g.get_state(h).values
    alertas = [m for m in v["alertas"]["apertura"] if "la ingesta extrajo" in m]
    assert len(alertas) == 1 and "accionante" in alertas[0] and "'Marta Ejemplo'" in alertas[0]
    assert alertas[0].startswith("ALERTA:") and v["metadatos"]["accionante"] == "Marta Ejemplo"


def test_metadatos_vacios_del_modelo_no_pisan_ni_rompen_la_fusion():
    from tutela2.models import Metadatos, MetadatosLLM

    fusion = graph._fusionar_metadatos(Metadatos(accionante="A"), MetadatosLLM(impugnante_rol="Accionante", genero_accionadas="F"))
    assert fusion.accionante == "A" and fusion.impugnante is None and fusion.genero_vinculadas is None
    assert fusion.impugnante_rol == "accionante" and fusion.genero_accionadas == "f"


def test_extension_de_antecedentes_se_mide_con_las_contestaciones(cfg, tmp_path):
    cfg = cfg.model_copy(update={"rango_palabras": {**cfg.rango_palabras, "antecedentes": [60, 400]}})
    ap = AperturaLLM(
        metadatos=MetadatosLLM(), cronologia=[], antecedentes_hechos=" ".join(["hecho"] * 30),
        contestaciones=[Contestacion(entidad="E", texto=" ".join(["respuesta"] * 40))],
        sentencia_impugnada="s", impugnacion="i", reparos=[],
    )
    estado = {"apertura": ap.model_dump(mode="json"), "ingesta": ingesta_sintetica().model_dump(mode="json"), "intentos": {}}
    alertas = graph.nodo_validar_apertura(estado, cfg)["alertas"]["apertura"]
    assert not [m for m in alertas if "antecedentes" in m and "palabras" in m]


def test_extension_enviada_al_modelo_explica_el_alcance(cfg, tmp_path):
    _, _, cliente = arrancar(cfg, tmp_path)
    ext = llm.leer_secciones(dict(cliente.llamadas)["apertura"])["EXTENSION"]
    assert "antecedentes (hechos y contestaciones sumados): entre 510 y 1140" in ext
    cons = llm.leer_secciones(dict(cliente.llamadas)["consideraciones"])["EXTENSION"]
    assert "entre 600 y 2050" in cons


def test_caso_concreto_recibe_la_cita_literal_de_cada_evento(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    g.invoke(Command(resume=DECISION), h, durability="sync")
    user = [u for n, u in cliente.llamadas if n == "caso_concreto"][0]
    evento = g.get_state(h).values["apertura"]["cronologia"][0]
    assert f"«{evento['cita_literal']}»" in llm.leer_secciones(user)["CRONOLOGIA"]


def test_bitacora_guarda_las_instrucciones_sin_documentos(cfg, tmp_path):
    g, h, _ = arrancar(cfg, tmp_path)
    b = g.get_state(h).values["bitacora"]
    assert "=== EXTENSION ===" in b[0]["instrucciones"] and "### DOC" not in b[0]["instrucciones"]
    assert "=== LIMITES ===" in b[1]["instrucciones"] and "REPAROS" not in b[1]["instrucciones"]


def test_datos_escritos_por_el_juez_no_son_ajenos(cfg, tmp_path):
    eje = "La accionante pagó $1.500.000 el 03/11/2026 según el comprobante que obra en la impugnación."
    g, h, _ = arrancar(cfg, tmp_path, cliente=ClienteConEje(FakeClient(), eje))
    g.invoke(Command(resume={**DECISION, "eje": eje}), h, durability="sync")
    v = g.get_state(h).values
    assert v["intentos"]["caso_concreto"] == 1
    assert not [m for m in v["alertas"]["caso_concreto"] if m.startswith("BLOQUEA:")]


def test_datos_inventados_en_el_caso_si_se_bloquean(cfg, tmp_path):
    g, h, _ = arrancar(cfg, tmp_path, cliente=ClienteConEje(FakeClient(), "Pagó $9.876.543 el 07/07/2026."))
    g.invoke(Command(resume=DECISION), h, durability="sync")
    v = g.get_state(h).values
    assert v["intentos"]["caso_concreto"] == cfg.max_intentos
    assert any("9876543" in m and m.startswith("BLOQUEA:") for m in v["alertas"]["caso_concreto"])


def test_sin_reparos_solo_alerta_y_no_reintenta(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path, cliente=ClienteSinReparos(FakeClient()))
    v = g.get_state(h).values
    assert v["intentos"]["apertura"] == 1 and v["errores"] == []
    assert any(m.startswith("ALERTA:") and "reparo" in m for m in v["alertas"]["apertura"])
    assert pendientes(g, h)[0]["reparos"] == []


@pytest.mark.parametrize(
    "schema, minimo",
    [
        (
            AperturaLLM,
            AperturaLLM(
                metadatos=MetadatosLLM(),
                cronologia=[],
                antecedentes_hechos="",
                contestaciones=[],
                sentencia_impugnada="",
                impugnacion="",
                reparos=[],
            ),
        ),
        (ConsideracionesLLM, ConsideracionesLLM(procedibilidad="", bloques=[], citas=[])),
        (CasoConcretoLLM, CASO),
    ],
)
def test_anthropic_sdk_real_con_transporte_simulado(schema, minimo):
    capturas = []

    def responder(request):
        capturas.append(request)
        return sse(minimo.model_dump_json())

    sdk = anthropic.Anthropic(
        api_key="clave", http_client=httpx.Client(transport=httpx.MockTransport(responder)), max_retries=0
    )
    salida, meta = AnthropicClient(sdk).estructurado("apertura", "sistema", "usuario", schema, Config())
    assert type(salida) is schema and meta["tokens_entrada"] == 3 and meta["modelo_efectivo"] == "claude-efectivo"
    peticion = capturas[0]
    cuerpo = json.loads(peticion.content)
    assert cuerpo["output_config"]["effort"] == "high" and "format" in cuerpo["output_config"]
    assert cuerpo["fallbacks"] == "default" and cuerpo["model"] == "claude-sonnet-5-5"
    assert peticion.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(cuerpo)


@pytest.mark.parametrize("nodo", ["apertura", "consideraciones", "caso_concreto"])
def test_prompts_del_contrato(nodo):
    texto = prompts.prompt_default(nodo)
    assert len(texto.split()) > 200
    assert "```" not in texto
    if nodo != "apertura":
        assert "[[CITA:" in texto
    assert prompts.prompt_para(nodo, Config()) == (texto, f"{nodo}@{prompts.version_default(nodo)}")


def _user_caso(cfg, tmp_path):
    g, h, cliente = arrancar(cfg, tmp_path)
    g.invoke(Command(resume=DECISION), h, durability="sync")
    return [u for n, u in cliente.llamadas if n == "caso_concreto"][0]


def test_caso_concreto_recibe_documentos_de_roles_con_prueba(cfg, tmp_path):
    docs = llm.leer_secciones(_user_caso(cfg, tmp_path))["DOCUMENTOS"]
    for rol in ("escrito_tutela", "contestacion", "fallo_a_quo", "impugnacion"):
        assert f"| {rol} |" in docs
    for rol in ("auto_admisorio", "auto_concede_impugnacion", "acta_reparto_2a"):
        assert f"| {rol} |" not in docs


def test_caso_concreto_respeta_el_tope_de_documentos(cfg, tmp_path):
    cfg = cfg.model_copy(update={"max_chars_documentos_caso": 200})
    docs = llm.leer_secciones(_user_caso(cfg, tmp_path))["DOCUMENTOS"]
    assert "[... TRUNCADO ...]" in docs
    assert len(docs) < 400


def _ing_documentos(extra):
    ing = ingesta_sintetica()
    ing.documentos = extra + ing.documentos
    return ing


def test_documentos_caso_prioriza_fallo_e_impugnacion_y_avisa(cfg):
    relleno = [_doc("1a", 20 + i, "contestacion", f"R{i}.pdf", ["x" * 500]) for i in range(5)]
    cfg = cfg.model_copy(update={"max_chars_documentos_caso": 1500})
    texto, alertas = graph._documentos_caso(_ing_documentos(relleno), cfg)
    assert "| fallo_a_quo |" in texto and "| impugnacion |" in texto
    assert texto.index("| fallo_a_quo |") < texto.index("| contestacion |")
    assert any("omitido" in a or "truncado" in a for a in alertas)


def test_documentos_caso_incluye_otro_y_correo_pero_no_roles_procesales(cfg):
    extra = [
        _doc("1a", 30, "otro", "Respuesta.pdf", ["respuesta sustantiva"]),
        _doc("1a", 31, "correo", "Correo.pdf", ["correo sustantivo"]),
    ]
    texto, alertas = graph._documentos_caso(_ing_documentos(extra), cfg)
    assert "| otro |" in texto and "| correo |" in texto
    assert "| auto_admisorio |" not in texto and alertas == []


def test_alerta_de_documentos_omitidos_llega_al_estado(cfg, tmp_path):
    cfg = cfg.model_copy(update={"max_chars_documentos_caso": 200})
    g, h, _ = arrancar(cfg, tmp_path)
    g.invoke(Command(resume=DECISION), h, durability="sync")
    assert g.get_state(h).values["alertas"]["documentos_caso"]


def test_prompt_caso_concreto_menciona_documentos():
    assert "DOCUMENTOS" in prompts.prompt_default("caso_concreto")
