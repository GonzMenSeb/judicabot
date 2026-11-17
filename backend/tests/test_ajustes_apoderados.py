from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_apoderados import ABOGADA, CC_ABOGADA, CC_ABOGADA_PLANA, EPS, PODER
from test_graph import DECISION, ClienteCaido, Verificador, _doc, ingesta_con_abogada, ingesta_sintetica
from test_render import lineas, seccion_informe

from tutela2 import (
    api,
    apoderados,
    estado_apoderados,
    ingest,
    llm,
    registro_apoderados,
    rutas_apoderados,
    salidas,
    server,
    vigencia,
    vista,
)
from tutela2 import citas as citas_real
from tutela2 import config as cfgmod
from tutela2 import rutas_ajustes_apoderados as rutas
from tutela2.config import ApoderadosConfig, Config, LLMConfig
from tutela2.models import Apoderado, EvidenciaDoc, Identificacion, Pagina, Poder
from tutela2.registro_apoderados import ConsultaVigencia
from tutela2.vigencia import CertificadoVigencia

CASO = "caso-ajustes"
AMBAR = "ap-ajuste0001"
"""La abogada de la EPS: sin poder hallado y sin cédula en el expediente."""
VERDE = "ap-ajuste0002"
"""Poder hallado, cédula del expediente y tarjeta vigente."""
ROJO = "ap-ajuste0003"
"""Tarjeta no vigente."""
CEDULA_VERDE = "43000021"
CEDULA_ROJO = "16000040"
CEDULA_AJENA = "1017234560"


class ColaFalsa:
    """La cola de consultas de vigencia sin hilo ni red: anota lo que se le pide."""

    def __init__(self) -> None:
        self.encoladas: list[tuple[Path, list[str], bool]] = []
        self.retiradas: list[tuple[Path, list[str] | None]] = []

    def encolar(self, caso_dir, cedulas, forzar: bool = False) -> int:
        self.encoladas.append((Path(caso_dir).resolve(), list(cedulas), forzar))
        return len(self.encoladas[-1][1])

    def retirar(self, caso_dir, cedulas=None) -> int:
        self.retiradas.append((Path(caso_dir).resolve(), None if cedulas is None else list(cedulas)))
        return 0

    def fase(self, cedula, caso_dir=None):
        return None

    def activa(self, caso_dir) -> bool:
        return False

    def pausa_hasta(self):
        return None

    def iniciar(self) -> None:
        pass

    def detener(self) -> None:
        pass


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None, galletas=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)
    monkeypatch.setattr(vigencia, "_abrir", _falla)
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)
    monkeypatch.delenv(cfgmod.VARIABLE_CONSULTA_VIGENCIA, raising=False)


@pytest.fixture(autouse=True)
def cola(monkeypatch) -> ColaFalsa:
    falsa = ColaFalsa()
    monkeypatch.setattr(vigencia, "COLA", falsa, raising=False)
    return falsa


@pytest.fixture(autouse=True)
def sin_jobs():
    server.JOBS.clear()
    yield
    server.JOBS.clear()


def _ev(doc_id: str, pagina: int, cita: str) -> EvidenciaDoc:
    return EvidenciaDoc(doc_id=doc_id, pagina=pagina, cita=cita, cobertura=1.0)


def _ident() -> Identificacion:
    ambar = Apoderado(
        id=AMBAR,
        nombre=ABOGADA,
        parte=EPS,
        rol_parte="accionada",
        tipo_persona="juridica",
        tarjeta="287415",
        menciones=[_ev("1a-003", 1, "Respuesta de la entidad")],
        motivos=[f"No consta la cédula del abogado junto a su nombre; {apoderados.SIN_CONSULTA_AUTOMATICA}."],
    )
    verde = Apoderado(
        id=VERDE,
        nombre="Marcela Ortiz Peña",
        parte="Marta Ejemplo",
        rol_parte="accionante",
        tipo_persona="natural",
        cedula=CEDULA_VERDE,
        tarjeta="214883",
        cedula_fuente=_ev("1a-001", 1, "Marcela Ortiz Peña, C.C."),
        poderes=[Poder(tipo="poder", evidencia=_ev("1a-001", 1, "confiero poder a la doctora"), parte="Marta Ejemplo")],
    )
    rojo = Apoderado(
        id=ROJO,
        nombre="Carlos Eduardo Pineda Ruiz",
        parte="Entidad Prestadora Uno",
        rol_parte="accionada",
        tipo_persona="juridica",
        cedula=CEDULA_ROJO,
        tarjeta="97551",
        cedula_fuente=_ev("1a-003", 1, "Carlos Eduardo Pineda Ruiz, C.C."),
        poderes=[Poder(tipo="poder", evidencia=_ev("1a-003", 1, "otorgo poder al doctor"), parte="Entidad Prestadora Uno")],
    )
    return Identificacion(ingesta_sha="abc", apoderados=[ambar, verde, rojo], documentos_revisados=9)


def _consulta(cedula: str, nombre: str, tarjeta: str, estado: str = "vigente", tpa_estado: str = "VIGENTE", **extra) -> ConsultaVigencia:
    return ConsultaVigencia(
        estado=estado,
        origen="extension",
        consultado_en="2026-11-17T15:42:00+00:00",
        sha256=cedula[-1] * 64,
        datos=CertificadoVigencia(
            numero="1234567",
            nombre=nombre,
            documento=cedula,
            rna_estado="VIGENTE",
            tpa_numero=tarjeta,
            tpa_fecha="01/02/2010",
            tpa_estado=tpa_estado,
            tpa_observaciones="NO REGISTRA",
            rna_observaciones="NO REGISTRA",
            codigo_verificacion="ab" * 32,
        ),
        **extra,
    )


def _ingesta():
    ing = ingesta_sintetica()
    ing.documentos += [
        _doc("1a", 8, "anexo", "014PoderEspecial.pdf", [PODER, "Página que no nombra a nadie del caso.", ""]),
        _doc("1a", 9, "anexo", "015OtroRadicado.pdf", [PODER]),
    ]
    ing.docs_ajenos = ["1a-009"]
    return ing


def _modo(caso_dir: Path, modo: str) -> None:
    cfgmod.guardar(caso_dir, Config(apoderados=ApoderadosConfig(consulta=modo)))


@pytest.fixture
def caso_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    d = tmp_path / "casos" / CASO
    d.mkdir(parents=True)
    (d / "caso.json").write_text(_ingesta().model_dump_json(), encoding="utf-8")
    _modo(d, "extension")
    registro_apoderados.espejar(d, _ident())
    consultas = {
        CEDULA_VERDE: _consulta(CEDULA_VERDE, "MARCELA ORTIZ PEÑA", "214883"),
        CEDULA_ROJO: _consulta(CEDULA_ROJO, "CARLOS EDUARDO PINEDA RUIZ", "97551", "no_vigente", "SUSPENDIDO"),
    }
    registro_apoderados.actualizar(d, lambda r: r.consultas.update(consultas))
    return d


@pytest.fixture
def cliente(caso_dir) -> TestClient:
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def estado(monkeypatch) -> dict:
    actual: dict = {"estado": "esperando_decision", "valores": {}}
    monkeypatch.setattr(rutas_apoderados, "_estado_del_caso", lambda caso_dir: (actual["estado"], actual["valores"]))
    return actual


def _url(ap_id: str) -> str:
    return f"/api/casos/{CASO}/apoderados/{ap_id}/ajustes"


def _leer(cliente: TestClient, ap_id: str) -> dict:
    return next(a for a in cliente.get(f"/api/casos/{CASO}/apoderados").json()["apoderados"] if a["id"] == ap_id)


def _ajustes(caso_dir: Path) -> dict:
    return registro_apoderados.leer(caso_dir).ajustes


# --- poder señalado a mano ---


def test_poder_a_mano_se_comprueba_y_la_cita_sale_de_la_pagina(cliente, caso_dir, estado):
    assert _leer(cliente, AMBAR)["poder"]["estado"] == "sin_poder"
    r = cliente.put(_url(AMBAR), json={"poder_manual": {"doc_id": "1a-008", "pagina": 1}, "nota": "  Está en el anexo.  "})
    assert r.status_code == 200, r.text
    vista_ap = r.json()
    ev = vista_ap["poder"]["evidencia"]
    assert vista_ap["poder"]["estado"] == "manual" and vista_ap["estado"] == "revisar"
    assert (ev["doc_id"], ev["pagina"], ev["documento"]) == ("1a-008", 1, "014PoderEspecial.pdf")
    assert ev["cita"].startswith("confiero poder especial, amplio y suficiente a la doctora " + ABOGADA)
    assert 8 <= len(ev["cita"].split()) <= 60
    assert " ".join(PODER[ev["inicio"] : ev["fin"]].split()) == ev["cita"]
    assert vista_ap["cotejos"][0] == {"ok": True, "texto": "El nombre coincide con quien actúa en el expediente"}
    ajuste = _ajustes(caso_dir)[AMBAR]
    assert ajuste.poder_manual.cita == ev["cita"] and ajuste.nota == "Está en el anexo." and ajuste.en.endswith("+00:00")


@pytest.mark.parametrize(
    "pedido, detalle",
    [
        ({"doc_id": "1a-008", "pagina": 2}, rutas.SIN_NOMBRE),
        ({"doc_id": "1a-008", "pagina": 3}, rutas.SIN_NOMBRE),
        ({"doc_id": "1a-008", "pagina": 4}, rutas.SIN_PAGINA),
        ({"doc_id": "1a-099", "pagina": 1}, rutas.SIN_PAGINA),
        ({"doc_id": "1a-009", "pagina": 1}, rutas.DOC_AJENO),
        ({"doc_id": "../caso.json", "pagina": 1}, None),
        ({"doc_id": "1a-008", "pagina": 0}, None),
    ],
)
def test_poder_a_mano_que_no_se_puede_comprobar_es_422(cliente, caso_dir, estado, pedido, detalle):
    r = cliente.put(_url(AMBAR), json={"poder_manual": pedido})
    assert r.status_code == 422
    if detalle is not None:
        assert r.json()["detail"] == detalle
    assert _ajustes(caso_dir) == {}


def test_evidencia_de_un_poder_a_mano_sin_palabra_de_otorgamiento():
    texto = f"Memorial.\nObra en el expediente la intervención de la doctora {ABOGADA.title()} en nombre de la entidad accionada."
    doc = _doc("1a", 8, "memorial", "016Memorial.pdf", [texto])
    ev = apoderados.evidencia_poder_manual(doc, doc.paginas[0], ABOGADA)
    # Ocho palabras antes del nombre y hasta doce después.
    assert ev is not None and ev.cita == (
        "en el expediente la intervención de la doctora Andrea Paola Giraldo Montoya en nombre de la entidad accionada."
    )
    assert texto[ev.inicio : ev.fin] == ev.cita and ev.fin == len(texto)
    # El segundo apellido puede faltar, como en la identificación; un nombre ajeno, no.
    assert apoderados.evidencia_poder_manual(doc, doc.paginas[0], "Andrea Paola Giraldo Restrepo") is not None
    assert apoderados.evidencia_poder_manual(doc, doc.paginas[0], "Carlos Eduardo Pineda Ruiz") is None
    vacia = Pagina(n=2, texto="", sin_texto=True)
    assert apoderados.evidencia_poder_manual(doc, vacia, ABOGADA) is None


# --- «No es correcto…» ---


def test_descartar_el_poder_y_deshacerlo(cliente, caso_dir, estado):
    assert _leer(cliente, VERDE)["estado"] == "verificado"
    r = cliente.put(_url(VERDE), json={"poder_descartado": True, "nota": "Es de otro proceso."})
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["poder"]["estado"]) == ("revisar", "descartado")
    assert "El poder hallado se marcó como incorrecto en la revisión." in r.json()["motivos"]
    assert _ajustes(caso_dir)[VERDE].poder_descartado is True

    r = cliente.put(_url(VERDE), json={"poder_descartado": None})
    assert r.status_code == 200 and r.json()["estado"] == "verificado"
    assert VERDE not in _ajustes(caso_dir)


def test_no_es_correcto_sobre_un_poder_senalado_a_mano_lo_quita(cliente, caso_dir, estado):
    assert cliente.put(_url(AMBAR), json={"poder_manual": {"doc_id": "1a-008", "pagina": 1}}).status_code == 200
    r = cliente.put(_url(AMBAR), json={"poder_descartado": True})
    assert r.status_code == 200 and r.json()["poder"]["estado"] == "descartado"
    ajuste = _ajustes(caso_dir)[AMBAR]
    assert ajuste.poder_manual is None and ajuste.poder_descartado is True


def test_sin_poder_no_hay_nada_que_descartar(cliente, caso_dir, estado):
    r = cliente.put(_url(AMBAR), json={"poder_descartado": True})
    assert r.status_code == 409 and r.json()["detail"] == rutas.SIN_PODER
    assert _ajustes(caso_dir) == {}


def test_un_ajuste_vence_la_revision_y_la_compuerta_vuelve_a_cerrar(cliente, caso_dir, estado):
    huella = _leer(cliente, ROJO)["huella"]
    r = cliente.put(f"/api/casos/{CASO}/apoderados/{ROJO}/revision", json={"revisado": True, "huella": huella})
    assert r.json()["bloquea"] is False and estado_apoderados.bloqueos(caso_dir) == []

    r = cliente.put(_url(ROJO), json={"poder_descartado": True, "nota": "El poder es de otro proceso."})
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["estado"], v["revisado"], v["revision_vencida"], v["bloquea"]) == ("no_verificado", False, True, True)
    assert v["huella"] != huella
    assert [b.id for b in estado_apoderados.bloqueos(caso_dir)] == [ROJO]
    assert cliente.get(f"/api/casos/{CASO}/apoderados").json()["bloquea_decision"] is True

    # Repetir la misma corrección con otra nota no cambia la huella: la nueva revisión sigue valiendo.
    cliente.put(f"/api/casos/{CASO}/apoderados/{ROJO}/revision", json={"revisado": True, "huella": v["huella"]})
    r = cliente.put(_url(ROJO), json={"poder_descartado": True, "nota": "Confirmado con el despacho."})
    assert (r.json()["huella"], r.json()["revisado"]) == (v["huella"], True)
    assert _ajustes(caso_dir)[ROJO].nota == "Confirmado con el despacho."


# --- cédula a mano ---


@pytest.mark.parametrize("mala", ["123", "12345678901", "12a45678", "1017-234-568", "1" * 40])
def test_cedula_a_mano_no_valida_es_422_y_no_se_repite(cliente, caso_dir, estado, cola, mala):
    r = cliente.put(_url(AMBAR), json={"cedula": mala})
    assert r.status_code == 422 and r.json()["detail"] == rutas.CEDULA_INVALIDA
    assert mala not in r.text
    assert _ajustes(caso_dir) == {} and cola.encoladas == []


def test_cedula_a_mano_se_guarda_y_va_a_la_cola(cliente, caso_dir, estado, cola, caplog):
    with caplog.at_level("INFO"):
        r = cliente.put(_url(AMBAR), json={"cedula": f" {CC_ABOGADA} ", "nota": "La dio la abogada."})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["cedula"] == CC_ABOGADA_PLANA and v["vigencia"]["estado"] == "sin_consultar"
    assert v["motivos"][:2] == [
        "Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial.",
        "La cédula del abogado no consta en el expediente: la indicó a mano quien revisa.",
    ]
    assert not any(apoderados.SIN_CONSULTA_AUTOMATICA in m for m in v["motivos"])
    assert any(c["texto"] == "La cédula la indicó a mano quien revisa; no consta en el expediente" for c in v["cotejos"])
    assert _ajustes(caso_dir)[AMBAR].cedula == CC_ABOGADA_PLANA
    assert cola.encoladas == [(caso_dir.resolve(), [CC_ABOGADA_PLANA], False)]
    assert CC_ABOGADA_PLANA not in caplog.text and CC_ABOGADA not in caplog.text

    # La misma cédula otra vez no vuelve a la cola.
    assert cliente.put(_url(AMBAR), json={"cedula": CC_ABOGADA_PLANA}).status_code == 200
    assert len(cola.encoladas) == 1


@pytest.mark.parametrize("escrita", ["１０１７２３４５６７", "١٠١٧٢٣٤٥٦٧", "1.017.２３４.567"])
def test_cedula_con_digitos_de_otra_escritura_se_guarda_y_va_a_la_cola_con_0_9(cliente, caso_dir, estado, cola, escrita):
    """La lista blanca de la extensión solo admite 0-9: nunca se guarda ni se pone en cola otra cosa."""
    r = cliente.put(_url(AMBAR), json={"cedula": escrita})
    assert r.status_code == 200, r.text
    assert r.json()["cedula"] == CC_ABOGADA_PLANA and _ajustes(caso_dir)[AMBAR].cedula == CC_ABOGADA_PLANA
    assert cola.encoladas == [(caso_dir.resolve(), [CC_ABOGADA_PLANA], False)]
    assert vigencia.cedula_valida(cola.encoladas[0][1][0])


def test_con_la_consulta_apagada_la_cedula_no_va_a_la_cola(cliente, caso_dir, estado, cola):
    _modo(caso_dir, "apagada")
    r = cliente.put(_url(AMBAR), json={"cedula": CC_ABOGADA})
    assert r.status_code == 200, r.text
    assert (r.json()["cedula"], r.json()["fase"]) == (CC_ABOGADA_PLANA, "necesita_ayuda")
    assert cola.encoladas == []


def test_una_falla_de_la_cola_no_deshace_la_cedula(cliente, caso_dir, estado, monkeypatch, caplog):
    def rota(caso_dir, cedulas, forzar=False):
        raise RuntimeError(f"cola rota {cedulas}")

    monkeypatch.setattr(vigencia.COLA, "encolar", rota)
    r = cliente.put(_url(AMBAR), json={"cedula": CC_ABOGADA})
    assert r.status_code == 200 and _ajustes(caso_dir)[AMBAR].cedula == CC_ABOGADA_PLANA
    assert "RuntimeError" in caplog.text and CC_ABOGADA_PLANA not in caplog.text


def test_la_cedula_del_expediente_manda(cliente, caso_dir, estado, cola):
    r = cliente.put(_url(VERDE), json={"cedula": "1234567"})
    assert r.status_code == 409 and r.json()["detail"] == rutas.CEDULA_DEL_EXPEDIENTE
    r = cliente.put(_url(VERDE), json={"cedula": "43.000.021"})
    assert r.status_code == 200 and r.json()["estado"] == "verificado"
    assert _ajustes(caso_dir) == {} and cola.encoladas == []


def test_cambiar_o_quitar_la_cedula_borra_la_consulta_que_ya_nadie_usa(cliente, caso_dir, estado, cola):
    assert cliente.put(_url(AMBAR), json={"cedula": CEDULA_AJENA}).status_code == 200
    assert cola.retiradas == []
    nombre_pdf = "ap-ajuste0001-0123456789abcdef.pdf"

    def trae_otra_persona(reg):
        ruta = registro_apoderados.guardar_certificado(caso_dir, nombre_pdf, b"%PDF-1.4 otra persona")
        reg.consultas[CEDULA_AJENA] = _consulta(CEDULA_AJENA, "PEDRO PÉREZ", "1111", certificado=ruta)

    registro_apoderados.actualizar(caso_dir, trae_otra_persona)
    pdf = registro_apoderados.carpeta(caso_dir) / registro_apoderados.CERTIFICADOS / nombre_pdf
    assert pdf.is_file() and _leer(cliente, AMBAR)["vigencia"]["estado"] == "otra_persona"

    r = cliente.put(_url(AMBAR), json={"cedula": CC_ABOGADA})
    assert r.status_code == 200
    reg = registro_apoderados.leer(caso_dir)
    assert CEDULA_AJENA not in reg.consultas and not pdf.exists()
    assert set(reg.consultas) == {CEDULA_VERDE, CEDULA_ROJO}
    # La cédula reemplazada (quizá de otra persona) sale de la cola: no se consulta.
    assert cola.retiradas == [(caso_dir.resolve(), [CEDULA_AJENA])]

    r = cliente.put(_url(AMBAR), json={"cedula": None})
    assert r.status_code == 200 and r.json()["vigencia"]["estado"] == "sin_cedula"
    assert AMBAR not in _ajustes(caso_dir)
    assert cola.retiradas[-1] == (caso_dir.resolve(), [CC_ABOGADA_PLANA])


# --- guardas ---


def test_ajustes_guardas(cliente, caso_dir, estado):
    assert cliente.put(_url("ap-noexiste01"), json={"poder_descartado": True}).status_code == 404
    assert cliente.put(f"/api/casos/no-existe/apoderados/{AMBAR}/ajustes", json={"poder_descartado": True}).status_code == 404
    for cuerpo in ({}, {"nota": "Solo una nota."}):
        r = cliente.put(_url(AMBAR), json=cuerpo)
        assert r.status_code == 422 and r.json()["detail"] == rutas.NADA_QUE_AJUSTAR
    estado["estado"] = "terminado"
    r = cliente.put(_url(VERDE), json={"poder_descartado": True})
    assert r.status_code == 409 and r.json()["detail"] == rutas_apoderados.NO_EDITABLE
    estado["estado"] = "esperando_decision"
    server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
    assert cliente.put(_url(VERDE), json={"poder_descartado": True}).status_code == 409
    assert _ajustes(caso_dir) == {}


def test_ajustes_con_registro_danado_es_500_y_no_se_reescribe(cliente, caso_dir, estado):
    ruta = registro_apoderados.ruta(caso_dir)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["consultas"][CEDULA_VERDE]["estado"] = "vencida"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    original = ruta.read_bytes()
    r = cliente.put(_url(VERDE), json={"poder_descartado": True})
    assert r.status_code == 500 and "está dañado" in r.json()["detail"]
    assert ruta.read_bytes() == original


# --- identificación de casos anteriores ---


def _esperar(cliente: TestClient, ubicacion: str) -> dict:
    limite = time.time() + 10
    while time.time() < limite:
        job = cliente.get(ubicacion).json()
        if job["estado"] != "corriendo":
            return job
        time.sleep(0.02)
    raise AssertionError("el job no terminó")


def _marcas(ruta: Path) -> list[tuple[str, str]]:
    v = json.loads(ruta.read_text(encoding="utf-8"))
    return [
        (s["texto"], s["apoderado_id"])
        for p in v["paginas"]
        for b in p["bloques"]
        for s in b["segmentos"]
        if "apoderado_id" in s
    ]


def _estado_grafo(carpeta: Path):
    with api._grafo(carpeta, cfgmod.cargar(carpeta)) as (g, hilo):
        return g.get_state(hilo)


@pytest.fixture
def caso_viejo(tmp_path, monkeypatch) -> Path:
    """Un caso que llegó a la decisión sin identificación de apoderados (como los anteriores al nodo)."""
    carpeta = tmp_path / "casos" / "caso-viejo"
    (carpeta / "insumos").mkdir(parents=True)
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    base = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    cfgmod.guardar(carpeta, base.model_copy(update={"apoderados": ApoderadosConfig(activo=False)}))
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_con_abogada(), raising=False)
    assert api.nuevo(carpeta)["ok"]
    r = api.iniciar(carpeta)
    assert r["estado"] == "esperando_decision", r["error"]
    cfgmod.guardar(carpeta, base.model_copy(update={"apoderados": ApoderadosConfig(consulta="fake")}))
    return carpeta


def test_reiniciar_el_caso_saca_de_la_cola_lo_que_esperaba(tmp_path, monkeypatch, cola):
    carpeta = tmp_path / "casos" / "otro"
    (carpeta / "insumos").mkdir(parents=True)
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_con_abogada(), raising=False)
    assert api.nuevo(carpeta)["ok"]
    assert cola.retiradas == [(carpeta.resolve(), None)]


def test_identificar_un_caso_anterior_actualiza_el_estado_sin_correr_el_grafo(caso_viejo, cola, monkeypatch):
    antes = _estado_grafo(caso_viejo).values
    previo = salidas.trabajo(caso_viejo) / vista.ARCHIVOS["borrador"]
    assert antes["apoderados"] is None and not registro_apoderados.carpeta(caso_viejo).exists()
    assert _marcas(previo) == []
    sha_vista = json.loads(previo.read_text(encoding="utf-8"))["sha256"]
    falso = llm.FakeClient()
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: falso)
    cliente = TestClient(server.app, base_url="http://127.0.0.1")

    r = cliente.post("/api/casos/caso-viejo/apoderados/identificar")
    assert r.status_code == 202, r.text
    assert r.headers["location"].startswith("/api/jobs/")
    assert r.json()["identificacion"] in ("no_disponible", "lista")
    job = _esperar(cliente, r.headers["location"])
    assert (job["cmd"], job["estado"]) == ("identificar", "terminado"), job["error"]

    # Solo se llamó al modelo para identificar: ni la apertura ni las consideraciones se rehicieron.
    assert [n for n, _ in falso.llamadas] == ["apoderados"]
    snap = _estado_grafo(caso_viejo)
    valores = snap.values
    assert api._clasificar(snap)[0] == "esperando_decision" and snap.next == ("decision",)
    pendiente = [i.value for t in snap.tasks for i in t.interrupts][0]
    ident = Identificacion.model_validate(valores["apoderados"])
    [ap] = ident.apoderados
    assert (ap.nombre, ap.parte, ap.cedula) == (ABOGADA, EPS, CC_ABOGADA_PLANA)
    assert [b["nodo"] for b in valores["bitacora"]] == [*(b["nodo"] for b in antes["bitacora"]), "apoderados"]
    assert valores["alertas"]["apoderados"] == ident.alertas == pendiente["alertas"]["apoderados"]
    assert pendiente["errores"] == []
    for clave in ("apertura", "consideraciones", "citas", "metadatos", "decisiones"):
        assert valores[clave] == antes[clave]

    # El espejo, el borrador previo con el nombre marcado y la cola.
    assert registro_apoderados.leer(caso_viejo).identificacion == ident
    assert [i for _, i in _marcas(previo)] == [ap.id]
    # Las marcas no cambian el .docx: las citas que el usuario ya revisó siguen valiendo.
    assert json.loads(previo.read_text(encoding="utf-8"))["sha256"] == sha_vista
    assert cola.encoladas == [(caso_viejo.resolve(), [CC_ABOGADA_PLANA], False)]
    cuerpo = cliente.get("/api/casos/caso-viejo/apoderados").json()
    assert cuerpo["identificacion"] == "lista" and cuerpo["editable"] is True
    assert [a["nombre"] for a in cuerpo["apoderados"]] == [ABOGADA]

    # La segunda vez no hay nada que hacer.
    r = cliente.post("/api/casos/caso-viejo/apoderados/identificar")
    assert r.status_code == 200 and r.json()["identificacion"] == "lista"
    assert [n for n, _ in falso.llamadas] == ["apoderados"] and len(server.JOBS) == 1

    # El caso sigue su curso: la decisión se toma sobre el estado actualizado y el informe lista a la abogada.
    decision = {**DECISION, "ordenes": [{**DECISION["ordenes"][0], "destinatario": EPS}]}
    r = api.decidir(caso_viejo, decision)
    assert r["ok"] and r["estado"] == "terminado", r["error"]
    assert _estado_grafo(caso_viejo).values["apoderados"] == valores["apoderados"]
    informe = lineas(salidas.trabajo(caso_viejo) / "informe_verificacion.docx")
    filas = seccion_informe(informe, "III. APODERADOS")
    assert filas[0].startswith("1 apoderado: 0 verificados, 1 por revisar, 0 no verificados.")
    assert filas[2].startswith(f"{ABOGADA}\nC.C. 1.017.•••.•67\nT.P. 287.415 | {EPS}\n(accionada) | Sin consultar |")
    assert CC_ABOGADA_PLANA not in "\n".join(informe)


def test_identificar_reintenta_una_identificacion_fallida(caso_viejo, monkeypatch):
    caido = ClienteCaido(llm.FakeClient(), "apoderados")
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: caido)
    cliente = TestClient(server.app, base_url="http://127.0.0.1")

    r = cliente.post("/api/casos/caso-viejo/apoderados/identificar")
    assert r.status_code == 202
    job = _esperar(cliente, r.headers["location"])
    assert (job["estado"], job["error"]) == ("error", apoderados.ALERTA_FALLA)
    cuerpo = cliente.get("/api/casos/caso-viejo/apoderados").json()
    assert cuerpo["identificacion"] == "fallida" and cuerpo["alertas"] == [apoderados.ALERTA_FALLA]
    # La falla no entra al estado del grafo: la decisión sigue pendiente y se puede reintentar.
    assert api.estado(caso_viejo)["estado"] == "esperando_decision"
    assert _estado_grafo(caso_viejo).values["apoderados"] is None

    caido.activo = False
    r = cliente.post("/api/casos/caso-viejo/apoderados/identificar")
    assert r.status_code == 202
    assert _esperar(cliente, r.headers["location"])["estado"] == "terminado"
    cuerpo = cliente.get("/api/casos/caso-viejo/apoderados").json()
    assert cuerpo["identificacion"] == "lista" and [a["nombre"] for a in cuerpo["apoderados"]] == [ABOGADA]


def test_identificar_dentro_del_trabajo_vuelve_a_mirar_el_estado(caso_viejo, monkeypatch):
    decision = {**DECISION, "ordenes": [{**DECISION["ordenes"][0], "destinatario": EPS}]}
    assert api.decidir(caso_viejo, decision)["estado"] == "terminado"
    monkeypatch.setattr(llm, "cliente_para", lambda cfg: pytest.fail("no debe llamar al modelo"))
    r = rutas.identificar(caso_viejo)
    assert r["ok"] is False and r["error"] == rutas.NO_ESPERANDO
    assert _estado_grafo(caso_viejo).values["apoderados"] is None


def test_identificar_guardas(cliente, caso_dir, estado, monkeypatch):
    llamados: list[Path] = []
    monkeypatch.setattr(rutas, "identificar", lambda caso_dir: llamados.append(caso_dir) or {"ok": True})
    url = f"/api/casos/{CASO}/apoderados/identificar"

    assert cliente.post("/api/casos/no-existe/apoderados/identificar").status_code == 404
    estado["estado"] = "terminado"
    r = cliente.post(url)
    assert r.status_code == 409 and r.json()["detail"] == rutas.NO_ESPERANDO
    estado["estado"] = "esperando_decision"

    server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
    r = cliente.post(url)
    assert r.status_code == 409 and r.json()["detail"] == rutas.EN_CURSO
    server.JOBS.clear()

    # Ya identificado en el grafo: 200 sin trabajo.
    estado["valores"] = {"apoderados": _ident().model_dump(mode="json")}
    r = cliente.post(url)
    assert r.status_code == 200 and server.JOBS == {} and llamados == []
    assert _ids(r.json()) == [AMBAR, VERDE, ROJO]

    # Sin identificación, con la identificación desactivada: 409.
    estado["valores"] = {"apoderados": None}
    cfgmod.guardar(caso_dir, Config(apoderados=ApoderadosConfig(activo=False)))
    r = cliente.post(url)
    assert r.status_code == 409 and r.json()["detail"] == rutas.DESACTIVADA
    assert server.JOBS == {} and llamados == []

    # Con una identificación fallida se vuelve a intentar en un trabajo del caso.
    _modo(caso_dir, "extension")
    estado["valores"] = {"apoderados": Identificacion(alertas=[apoderados.ALERTA_FALLA]).model_dump(mode="json")}
    r = cliente.post(url)
    assert r.status_code == 202
    job = _esperar(cliente, r.headers["location"])
    assert job["estado"] == "terminado" and llamados == [caso_dir.resolve()]


def _ids(cuerpo: dict) -> list[str]:
    return [a["id"] for a in cuerpo["apoderados"]]
