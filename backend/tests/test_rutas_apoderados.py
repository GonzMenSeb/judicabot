from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import logging
import re
import time
import types
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from test_graph import DECISION, Verificador, _doc, ingesta_sintetica

from tutela2 import (
    api,
    estado_apoderados,
    ingest,
    registro_apoderados,
    rutas_apoderados,
    rutas_expediente,
    server,
    vigencia,
)
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.esquemas_apoderados import (
    ApoderadosRespuesta,
    ApoderadoVista,
    PaginaExpediente,
)
from tutela2.estado_apoderados import evaluar
from tutela2.models import (
    Apoderado,
    EvidenciaDoc,
    Identificacion,
    Ingesta,
    ParteSinApoderado,
    Poder,
)

CASO = "caso-uno"
CEDULA_ROJO = "16000040"
PODER = (
    "Por medio del presente escrito otorgo poder especial al doctor CARLOS EDUARDO PINEDA RUIZ, con T.P. 97551, "
    "para que represente a la Entidad Prestadora Uno en la acción de tutela de la referencia."
)
MENSAJE = "Hay apoderados no verificados sin revisar: Carlos Eduardo Pineda Ruiz. Márquelos como revisados en el borrador."


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None, galletas=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)
    monkeypatch.setattr(vigencia, "_abrir", _falla)
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())
    monkeypatch.delenv("TUTELA2_PROVEEDOR", raising=False)


@pytest.fixture(autouse=True)
def sin_jobs():
    server.JOBS.clear()
    yield
    server.JOBS.clear()


def _ingesta() -> Ingesta:
    ing = ingesta_sintetica()
    poder = _doc("1a", 8, "anexo", "014PoderEspecial.pdf", ["PODER ESPECIAL", "Página de ruido.", PODER])
    poder.paginas[1].ruido = True
    poder.paginas[2].ocr = True
    ing.documentos += [
        poder,
        _doc("1a", 9, "anexo", "015Certificado.txt", ["CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL"]),
        _doc("1a", 10, "memorial", "016Memorial.docx", ["Memorial del apoderado."]),
    ]
    return ing


def _escribir_caso(caso_dir: Path, ing: Ingesta) -> None:
    for d in ing.documentos:
        archivo = caso_dir / "insumos" / d.ruta
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b"%PDF-1.4 " + d.nombre.encode() if d.ruta.endswith(".pdf") else d.texto().encode())
    (caso_dir / "caso.json").write_text(ing.model_dump_json(), encoding="utf-8")


@pytest.fixture
def caso_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    d = tmp_path / "casos" / CASO
    d.mkdir(parents=True)
    _escribir_caso(d, _ingesta())
    return d


@pytest.fixture
def cliente(caso_dir) -> TestClient:
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def estado(monkeypatch) -> dict:
    actual: dict = {"estado": "esperando_decision", "valores": {}}
    monkeypatch.setattr(rutas_apoderados, "_estado_del_caso", lambda caso_dir: (actual["estado"], actual["valores"]))
    return actual


def _ev(doc_id: str, pagina: int, cita: str, ocr: bool = False) -> EvidenciaDoc:
    return EvidenciaDoc(doc_id=doc_id, pagina=pagina, cita=cita, cobertura=1.0, ocr=ocr, inicio=10, fin=60)


def _rojo() -> Apoderado:
    return Apoderado(
        id="ap-7f3a9c2e10",
        nombre="Carlos Eduardo Pineda Ruiz",
        parte="Instituto Departamental de Salud",
        rol_parte="vinculada",
        tipo_persona="juridica",
        cedula=CEDULA_ROJO,
        tarjeta="97551",
        cedula_fuente=_ev("1a-008", 3, PODER),
        menciones=[_ev("1a-010", 1, "Memorial del apoderado.")],
        ajenos=[Poder(tipo="poder", evidencia=_ev("1a-008", 3, PODER, ocr=True), parte="Entidad Prestadora Uno")],
    )


def _ambar() -> Apoderado:
    return Apoderado(
        id="ap-0b51d2aa77",
        nombre="Julián David Mesa Londoño",
        parte="Clínica Santa Aurora S.A.S.",
        rol_parte="vinculada",
        tipo_persona="juridica",
        menciones=[_ev("1a-003", 1, "actuando como apoderado de la CLÍNICA SANTA AURORA S.A.S.")],
    )


def _ident() -> Identificacion:
    return Identificacion(
        ingesta_sha="abc",
        apoderados=[_rojo(), _ambar()],
        sin_apoderado=[ParteSinApoderado(nombre="Secretaría Seccional de Salud", rol_parte="vinculada", nota="Actúa por su representante legal.")],
        alertas=["ALERTA: hay una T.P. en el escrito de la Secretaría que ningún apoderado cubre."],
        documentos_revisados=10,
    )


def _url(ap_id: str = "") -> str:
    return f"/api/casos/{CASO}/apoderados" + (f"/{ap_id}/revision" if ap_id else "")


ROJO = "ap-7f3a9c2e10"
HUELLA_CUALQUIERA = "0123456789abcdef"


def _huella(cliente: TestClient, ap_id: str = ROJO) -> str:
    """La huella que muestra el GET, como la que envía el borrador al marcar."""
    return next(a["huella"] for a in cliente.get(_url()).json()["apoderados"] if a["id"] == ap_id)


def _marcar(cliente: TestClient, ap_id: str = ROJO, **cuerpo):
    return cliente.put(_url(ap_id), json={"revisado": True, "huella": _huella(cliente, ap_id), **cuerpo})


# --- GET /apoderados ---


def test_get_sin_identificacion_no_bloquea(cliente, caso_dir, estado):
    r = cliente.get(_url())
    assert r.status_code == 200
    assert r.json() == {
        "identificacion": "no_disponible",
        "apoderados": [],
        "sin_apoderado": [],
        "alertas": [],
        "consulta": {"activa": False, "extension": "no_conectada", "modo": "apagada", "pausa_hasta": None},
        "bloquea_decision": False,
        "editable": True,
    }
    assert not (caso_dir / "apoderados").exists()


def test_get_caso_inexistente(cliente, estado):
    assert cliente.get("/api/casos/no-existe/apoderados").status_code == 404
    assert cliente.get("/api/casos/..%2Fx/apoderados").status_code == 404


def test_get_forma_completa(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, _ident())
    r = cliente.get(_url())
    assert r.status_code == 200
    cuerpo = r.json()
    ApoderadosRespuesta.model_validate(cuerpo)
    assert cuerpo["identificacion"] == "lista" and cuerpo["bloquea_decision"] is True and cuerpo["editable"] is True
    assert cuerpo["sin_apoderado"] == [
        {"nombre": "Secretaría Seccional de Salud", "rol_parte": "vinculada", "nota": "Actúa por su representante legal."}
    ]
    assert cuerpo["alertas"] == _ident().alertas
    rojo, ambar = cuerpo["apoderados"]
    assert set(rojo) == set(ApoderadoVista.model_fields)
    assert (rojo["estado"], rojo["bloquea"], rojo["revisado"], rojo["revision_vencida"]) == ("no_verificado", True, False, False)
    assert rojo["cedula"] == CEDULA_ROJO and rojo["tarjeta"] == "97551" and len(rojo["huella"]) == 16
    assert rojo["motivos"][0] == "Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial."
    assert "El poder hallado es para Entidad Prestadora Uno, no para Instituto Departamental de Salud." in rojo["motivos"]
    assert rojo["vigencia"] == {
        "estado": "sin_consultar",
        "fase": "necesita_ayuda",
        "cedula": CEDULA_ROJO,
        "tarjeta_registro": None,
        "consultado_en": None,
        "origen": None,
        "certificado_url": None,
        "numero_certificado": None,
        "codigo_verificacion": None,
        "detalle": "",
        # Sin verificar por el poder de otra parte, no por la vigencia.
        "grave": False,
    }
    poder = rojo["poder"]
    assert (poder["estado"], poder["tipo"], poder["parte"], poder["documentos_revisados"]) == (
        "ajeno", "poder", "Entidad Prestadora Uno", 10
    )
    assert poder["evidencia"] == {
        "doc_id": "1a-008",
        "documento": "014PoderEspecial.pdf",
        "rol": "anexo",
        "pagina": 3,
        "total_paginas": 3,
        "cita": PODER,
        "ocr": True,
        "inicio": 10,
        "fin": 60,
    }
    assert poder["cadena"]["estado"] == "no_aplica"
    assert poder["mencion"]["documento"] == "016Memorial.docx" and poder["mencion"]["rol"] == "memorial"
    assert [c["ok"] for c in rojo["cotejos"]] == [True, None, False]

    assert (ambar["estado"], ambar["fase"], ambar["bloquea"], ambar["cedula"]) == ("revisar", "necesita_ayuda", False, None)
    assert ambar["vigencia"]["estado"] == "sin_cedula" and ambar["poder"]["estado"] == "sin_poder"
    assert ambar["poder"]["evidencia"] is None and ambar["poder"]["mencion"]["doc_id"] == "1a-003"


def test_get_con_consulta_y_certificado(cliente, caso_dir, estado):
    from tutela2.registro_apoderados import ConsultaVigencia
    from tutela2.vigencia import CertificadoVigencia

    registro_apoderados.espejar(caso_dir, _ident())
    consulta = ConsultaVigencia(
        estado="no_vigente",
        origen="manual",
        consultado_en="2026-11-17T10:43:00+00:00",
        certificado="certificados/0123456789abcdef.pdf",
        sha256="0123456789abcdef" * 4,
        datos=CertificadoVigencia(
            numero="7654321", nombre="CARLOS EDUARDO PINEDA RUIZ", documento=CEDULA_ROJO, tpa_numero="97551",
            tpa_estado="SUSPENDIDO", codigo_verificacion="f" * 64,
        ),
    )
    registro_apoderados.actualizar(caso_dir, lambda r: r.consultas.update({CEDULA_ROJO: consulta}))
    rojo = cliente.get(_url()).json()["apoderados"][0]
    assert rojo["vigencia"]["estado"] == "no_vigente" and rojo["vigencia"]["fase"] == "listo" and rojo["vigencia"]["grave"] is True
    assert rojo["vigencia"]["certificado_url"] == f"/api/casos/{CASO}/apoderados/ap-7f3a9c2e10/certificado"
    assert (rojo["vigencia"]["numero_certificado"], rojo["vigencia"]["tarjeta_registro"]) == ("7654321", "97551")
    assert rojo["motivos"][0] == "La tarjeta profesional 97551 figura como «SUSPENDIDO» en el certificado N.° 7654321."
    assert rojo["cotejos"][1] == {"ok": True, "texto": "T.P. 97551 coincide con el certificado de vigencia"}


def test_get_escribe_el_espejo_desde_el_grafo_una_vez(cliente, caso_dir, estado):
    estado["valores"] = {"apoderados": _ident().model_dump(mode="json")}
    r = cliente.get(_url())
    assert r.json()["identificacion"] == "lista" and len(r.json()["apoderados"]) == 2
    assert registro_apoderados.leer(caso_dir).identificacion == _ident()
    estado["valores"] = {"apoderados": None}
    assert len(cliente.get(_url()).json()["apoderados"]) == 2


def test_get_lee_el_grafo_bajo_el_candado_y_no_resucita_el_caso_anterior(cliente, caso_dir, monkeypatch):
    """``nuevo`` borra el hilo y el registro entre la lectura del estado del GET y la escritura del espejo."""
    bajo_candado: list[bool] = []

    def estado_del_caso(d):
        bajo_candado.append(registro_apoderados._candado(d).locked())
        if len(bajo_candado) == 1:
            return "esperando_decision", {"apoderados": _ident().model_dump(mode="json")}
        return "sin_iniciar", {}

    monkeypatch.setattr(rutas_apoderados, "_estado_del_caso", estado_del_caso)
    assert cliente.get(_url()).json()["identificacion"] == "no_disponible"
    assert not (caso_dir / "apoderados").exists()
    assert bajo_candado == [False, True]


def test_get_sin_apoderados_en_el_grafo_no_crea_carpeta(cliente, caso_dir, estado):
    estado["valores"] = {"apoderados": None}
    assert cliente.get(_url()).json()["identificacion"] == "no_disponible"
    assert not (caso_dir / "apoderados").exists()


def test_get_identificacion_fallida(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, Identificacion(ingesta_sha="abc"))
    cuerpo = cliente.get(_url()).json()
    assert cuerpo["identificacion"] == "fallida" and cuerpo["bloquea_decision"] is False


def test_get_no_editable_fuera_de_la_decision_o_con_job(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, _ident())
    estado["estado"] = "terminado"
    assert cliente.get(_url()).json()["editable"] is False
    estado["estado"] = "esperando_decision"
    server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
    assert cliente.get(_url()).json()["editable"] is False


def test_get_modo_de_consulta_desde_la_configuracion(cliente, caso_dir, estado, monkeypatch):
    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    assert cliente.get(_url()).json()["consulta"]["modo"] == "fake"


# --- PUT /apoderados/{ap}/revision ---


def test_revision_marca_y_desbloquea(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, _ident())
    r = _marcar(cliente, nota="  Revisado contra el original.  ")
    assert r.status_code == 200, r.text
    vista = r.json()
    assert vista["id"] == ROJO and vista["revisado"] is True and vista["bloquea"] is False
    assert vista["estado"] == "no_verificado"
    revision = registro_apoderados.leer(caso_dir).revisiones[ROJO]
    assert revision.revisado and revision.huella == vista["huella"] and revision.nota == "Revisado contra el original."
    assert revision.en.endswith("+00:00")
    assert cliente.get(_url()).json()["bloquea_decision"] is False

    r = cliente.put(_url(ROJO), json={"revisado": False})
    assert r.json()["revisado"] is False and r.json()["bloquea"] is True
    assert cliente.get(_url()).json()["bloquea_decision"] is True


def test_revision_usa_el_espejo_del_grafo_si_falta(cliente, caso_dir, estado):
    estado["valores"] = {"apoderados": _ident().model_dump(mode="json")}
    huella = estado_apoderados.evaluar(_rojo(), registro_apoderados.Registro(identificacion=_ident())).huella
    r = cliente.put(_url(ROJO), json={"revisado": True, "huella": huella})
    assert r.status_code == 200 and r.json()["revisado"] is True


def test_revision_con_la_huella_de_un_estado_que_ya_cambio_es_409(cliente, caso_dir, estado):
    """Quien revisa vio el apoderado en ámbar o rojo; entretanto cambió la evidencia (otra consulta, otro certificado)."""
    from tutela2.registro_apoderados import ConsultaVigencia

    registro_apoderados.espejar(caso_dir, _ident())
    vista = _huella(cliente)
    consulta = ConsultaVigencia(estado="no_vigente", origen="manual", consultado_en="2026-11-17T10:43:00+00:00", sha256="ab" * 32)
    registro_apoderados.actualizar(caso_dir, lambda r: r.consultas.update({CEDULA_ROJO: consulta}))

    r = cliente.put(_url(ROJO), json={"revisado": True, "huella": vista})
    assert r.status_code == 409 and r.json()["detail"] == rutas_apoderados.CAMBIO
    assert registro_apoderados.leer(caso_dir).revisiones == {}
    assert cliente.get(_url()).json()["bloquea_decision"] is True

    assert _marcar(cliente).status_code == 200
    assert cliente.get(_url()).json()["bloquea_decision"] is False
    # Desmarcar nunca abre la compuerta: no necesita huella ni que coincida.
    assert cliente.put(_url(ROJO), json={"revisado": False, "huella": vista}).status_code == 200
    assert cliente.get(_url()).json()["bloquea_decision"] is True


@pytest.mark.parametrize("caso_estado", ["terminado", "error", "revision", "sin_iniciar"])
def test_revision_409_fuera_de_la_decision(cliente, caso_dir, estado, caso_estado):
    registro_apoderados.espejar(caso_dir, _ident())
    estado["estado"] = caso_estado
    r = _marcar(cliente)
    assert r.status_code == 409 and r.json()["detail"] == rutas_apoderados.NO_EDITABLE
    assert registro_apoderados.leer(caso_dir).revisiones == {}


def test_revision_409_con_job_en_curso(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, _ident())
    server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
    assert _marcar(cliente).status_code == 409


def test_revision_404(cliente, caso_dir, estado):
    cuerpo = {"revisado": True, "huella": HUELLA_CUALQUIERA}
    assert cliente.put(_url(ROJO), json=cuerpo).status_code == 404
    registro_apoderados.espejar(caso_dir, _ident())
    r = cliente.put(_url("ap-desconocido"), json=cuerpo)
    assert r.status_code == 404 and r.json()["detail"] == "Apoderado no encontrado."
    assert registro_apoderados.leer(caso_dir).revisiones == {}
    assert cliente.put(f"/api/casos/otro/apoderados/{ROJO}/revision", json=cuerpo).status_code == 404


def test_revision_valida_el_cuerpo(cliente, caso_dir, estado):
    registro_apoderados.espejar(caso_dir, _ident())
    assert cliente.put(_url(ROJO), json={"nota": "x"}).status_code == 422
    assert cliente.put(_url(ROJO), json={"revisado": True, "huella": HUELLA_CUALQUIERA, "nota": "x" * 2001}).status_code == 422
    # Marcar exige la huella del estado que se revisó; desmarcar no.
    assert cliente.put(_url(ROJO), json={"revisado": True}).status_code == 422
    assert cliente.put(_url(ROJO), json={"revisado": True, "huella": ""}).status_code == 422
    assert cliente.put(_url(ROJO), json={"revisado": False}).status_code == 200
    assert registro_apoderados.leer(caso_dir).revisiones[ROJO].revisado is False


# --- compuerta en /run ---


def _esperar(cliente: TestClient, job_id: str) -> dict:
    limite = time.time() + 5
    while time.time() < limite:
        job = cliente.get(f"/api/jobs/{job_id}").json()
        if job["estado"] != "corriendo":
            return job
        time.sleep(0.02)
    raise AssertionError("el job no terminó")


@pytest.fixture
def comandos(monkeypatch) -> list:
    llamadas: list = []

    def falso(cmd, caso_dir, decision, forzar=False, descartar=False):
        llamadas.append((cmd, decision))
        return {"ok": True, "estado": "terminado", "payload": None, "salidas": [], "resumen": {}, "error": None}

    monkeypatch.setattr(server, "_comando", falso)
    return llamadas


def test_run_decidir_409_con_apoderado_rojo_sin_revisar(cliente, caso_dir, estado, comandos):
    registro_apoderados.espejar(caso_dir, _ident())
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 409 and r.json()["detail"] == MENSAJE
    assert server.JOBS == {} and comandos == []

    assert _marcar(cliente).status_code == 200
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 200, r.text
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert comandos == [("decidir", DECISION)]


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"cmd": "decidir", "decision": {"accion": "rehacer_apertura", "instruccion": "Más breve."}},
        {"cmd": "decidir", "decision": {"accion": "rehacer_consideraciones", "instruccion": "Más breve."}},
        {"cmd": "continuar"},
        {"cmd": "iniciar"},
    ],
)
def test_run_sin_compuerta_para_rehacer_y_otros_comandos(cliente, caso_dir, estado, comandos, cuerpo):
    registro_apoderados.espejar(caso_dir, _ident())
    r = cliente.post(f"/api/casos/{CASO}/run", json=cuerpo)
    assert r.status_code == 200, r.text
    _esperar(cliente, r.json()["job_id"])
    assert len(comandos) == 1


def test_run_decidir_sin_identificacion_no_se_bloquea(cliente, caso_dir, comandos):
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 200
    _esperar(cliente, r.json()["job_id"])


def test_run_decidir_si_falla_la_compuerta_deja_que_api_decida(cliente, caso_dir, comandos, monkeypatch):
    from tutela2 import estado_apoderados

    def rota(caso_dir):
        raise RuntimeError("registro roto")

    monkeypatch.setattr(estado_apoderados, "bloqueos", rota)
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 200
    _esperar(cliente, r.json()["job_id"])


# --- compuerta en api.decidir (cubre la CLI) ---


@pytest.fixture
def caso_real(tmp_path, monkeypatch) -> Path:
    carpeta = tmp_path / "casos" / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    assert api.nuevo(carpeta)["ok"]
    r = api.iniciar(carpeta)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    return carpeta


def test_api_decidir_rechaza_con_apoderado_rojo_y_permite_rehacer(caso_real):
    registro_apoderados.espejar(caso_real, _ident())
    r = api.decidir(caso_real, DECISION)
    assert r["ok"] is False and r["estado"] == "esperando_decision" and r["error"] == MENSAJE
    assert not (caso_real / "decision.json").exists()
    assert api.estado(caso_real)["estado"] == "esperando_decision"

    r = api.decidir(caso_real, {"accion": "rehacer_consideraciones", "instruccion": "Más breve."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]

    reg = registro_apoderados.leer(caso_real)
    huella = evaluar(reg.identificacion.apoderados[0], reg).huella
    registro_apoderados.actualizar(
        caso_real,
        lambda x: x.revisiones.update(
            {"ap-7f3a9c2e10": registro_apoderados.Revision(revisado=True, en=registro_apoderados.ahora(), huella=huella)}
        ),
    )
    r = api.decidir(caso_real, DECISION)
    assert r["ok"] and r["estado"] == "terminado", r["error"]


def _registro_danado(caso_dir: Path) -> bytes:
    """Un registro con una consulta ``no_vigente`` que deja de validar (otra consulta trae un estado de una
    versión más nueva)."""
    registro_apoderados.espejar(caso_dir, _ident())
    datos = json.loads(registro_apoderados.ruta(caso_dir).read_text(encoding="utf-8"))
    datos["consultas"] = {
        CEDULA_ROJO: {"estado": "no_vigente", "origen": "manual", "consultado_en": "2026-11-17T10:43:00+00:00"},
        "16000041": {"estado": "vencida", "origen": "extension", "consultado_en": "2026-11-17T10:44:00+00:00"},
    }
    registro_apoderados.ruta(caso_dir).write_text(json.dumps(datos), encoding="utf-8")
    return registro_apoderados.ruta(caso_dir).read_bytes()


def test_registro_danado_falla_cerrado_y_no_se_reescribe(cliente, caso_dir, estado, comandos, caplog):
    original = _registro_danado(caso_dir)
    estado["valores"] = {"apoderados": _ident().model_dump(mode="json")}

    r = cliente.get(_url())
    assert r.status_code == 500 and "está dañado" in r.json()["detail"]
    assert cliente.put(_url(ROJO), json={"revisado": False}).status_code == 500
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 409 and "está dañado" in r.json()["detail"]
    assert server.JOBS == {} and comandos == []
    with pytest.raises(registro_apoderados.RegistroInvalido):
        estado_apoderados.bloqueos(caso_dir)

    assert registro_apoderados.ruta(caso_dir).read_bytes() == original
    assert CEDULA_ROJO not in caplog.text and "16000041" not in caplog.text
    assert CEDULA_ROJO not in r.text


def test_api_decidir_con_registro_danado_no_decide(caso_real):
    original = _registro_danado(caso_real)
    r = api.decidir(caso_real, DECISION)
    assert r["ok"] is False and r["estado"] == "esperando_decision" and "está dañado" in r["error"]
    assert not (caso_real / "decision.json").exists()
    assert registro_apoderados.ruta(caso_real).read_bytes() == original
    r = api.decidir(caso_real, {"accion": "rehacer_consideraciones", "instruccion": "Más breve."})
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]


def test_estado_del_caso_y_get_sobre_un_grafo_real(caso_real):
    estado_caso, valores = rutas_apoderados._estado_del_caso(caso_real)
    assert estado_caso == "esperando_decision" and "apoderados" in valores
    cliente = TestClient(server.app, base_url="http://127.0.0.1")
    cuerpo = cliente.get("/api/casos/caso-api/apoderados").json()
    assert cuerpo["editable"] is True and cuerpo["identificacion"] in ("lista", "no_disponible", "fallida")


def test_estado_del_caso_sin_hilo_no_lo_crea(caso_dir):
    assert rutas_apoderados._estado_del_caso(caso_dir) == ("sin_iniciar", {})
    assert not (caso_dir / "hilo.sqlite").exists()


def test_api_decidir_usa_el_estado_del_grafo_si_falta_el_espejo(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-falso"
    carpeta.mkdir()
    (carpeta / "hilo.sqlite").write_bytes(b"")
    (carpeta / "config.json").write_text(Config(llm=LLMConfig(proveedor="fake")).model_dump_json(), encoding="utf-8")
    snap = types.SimpleNamespace(
        tasks=[types.SimpleNamespace(interrupts=[types.SimpleNamespace(value={"reparos": []})], error=None)],
        next=("decision",),
        values={"apoderados": _ident().model_dump(mode="json")},
    )
    invocado = []
    grafo = types.SimpleNamespace(get_state=lambda hilo: snap, invoke=lambda *a, **k: invocado.append(a))

    @contextmanager
    def falso(caso_dir, cfg, cliente=None):
        yield grafo, {}

    monkeypatch.setattr(api, "_grafo", falso)
    r = api.decidir(carpeta, DECISION)
    assert r["ok"] is False and r["error"] == MENSAJE and invocado == []
    assert registro_apoderados.leer(carpeta).identificacion == _ident()


def test_nuevo_borra_la_carpeta_de_apoderados(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-nuevo"
    (carpeta / "insumos").mkdir(parents=True)
    (carpeta / "config.json").write_text(Config(llm=LLMConfig(proveedor="fake")).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    registro_apoderados.espejar(carpeta, _ident())
    (carpeta / "apoderados" / "certificados").mkdir()
    (carpeta / "apoderados" / "certificados" / "0123456789abcdef.pdf").write_bytes(b"%PDF-")
    assert api.nuevo(carpeta)["ok"]
    assert not (carpeta / "apoderados").exists()
    assert "apoderados" not in json.dumps(api.estado(carpeta)["salidas"])


# --- expediente ---


def _pagina(cliente: TestClient, doc_id: str, n: int):
    return cliente.get(f"/api/casos/{CASO}/expediente/{doc_id}/paginas/{n}")


def test_pagina_del_expediente(cliente):
    r = _pagina(cliente, "1a-008", 3)
    assert r.status_code == 200
    assert r.json() == PaginaExpediente(
        doc_id="1a-008", documento="014PoderEspecial.pdf", rol="anexo", pagina=3, total=3, texto=PODER, ocr=True, es_pdf=True
    ).model_dump()
    ruido = _pagina(cliente, "1a-008", 2).json()
    assert ruido["texto"] == "Página de ruido." and ruido["ocr"] is False
    assert _pagina(cliente, "1a-009", 1).json()["es_pdf"] is False


@pytest.mark.parametrize("doc_id, n, codigo", [
    ("1a-008", 4, 404),
    ("1a-008", 0, 422),
    ("1a-008", -1, 422),
    ("1a-999", 1, 404),
    ("3a-001", 1, 422),
    ("1A-008", 1, 422),
    ("1a-08", 1, 422),
    ("caso.json", 1, 422),
    ("..%2F..%2Fcaso.json", 1, 404),
    ("%2E%2E", 1, None),
])
def test_pagina_invalida(cliente, doc_id, n, codigo):
    r = _pagina(cliente, doc_id, n)
    if codigo is None:
        assert r.status_code in (404, 422)
    else:
        assert r.status_code == codigo
    assert "texto" not in r.text


def test_pagina_de_caso_inexistente_o_sin_ingesta(cliente, caso_dir):
    assert cliente.get("/api/casos/otro/expediente/1a-001/paginas/1").status_code == 404
    (caso_dir / "caso.json").unlink()
    assert _pagina(cliente, "1a-001", 1).status_code == 404


def test_la_ingesta_se_recarga_si_cambia_caso_json(cliente, caso_dir):
    assert _pagina(cliente, "1a-001", 1).status_code == 200
    ing = _ingesta()
    ing.documentos[0].paginas[0].texto = "Texto corregido."
    (caso_dir / "caso.json").write_text(ing.model_dump_json(indent=1), encoding="utf-8")
    assert _pagina(cliente, "1a-001", 1).json()["texto"] == "Texto corregido."


def test_archivo_pdf_en_linea(cliente):
    r = cliente.get(f"/api/casos/{CASO}/expediente/1a-008/archivo")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 014PoderEspecial.pdf"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_archivo_texto_en_linea_y_docx_como_descarga(cliente):
    txt = cliente.get(f"/api/casos/{CASO}/expediente/1a-009/archivo")
    assert txt.headers["content-type"].startswith("text/plain") and txt.headers["content-disposition"].startswith("inline")
    docx = cliente.get(f"/api/casos/{CASO}/expediente/1a-010/archivo")
    assert docx.status_code == 200 and docx.headers["content-disposition"].startswith("attachment")
    assert docx.headers["content-type"] == rutas_expediente.DOCX


def _con_ruta(caso_dir: Path, ruta: str) -> None:
    ing = _ingesta()
    ing.documentos[7].ruta = ruta
    (caso_dir / "caso.json").write_text(ing.model_dump_json(indent=2), encoding="utf-8")


@pytest.mark.parametrize("ruta", ["../fuera.pdf", "1a/../../fuera.pdf", "/etc/hostname", "1a/no-existe.pdf", "1a"])
def test_archivo_no_sale_de_insumos(cliente, caso_dir, ruta):
    (caso_dir / "fuera.pdf").write_bytes(b"%PDF-secreto")
    _con_ruta(caso_dir, ruta)
    r = cliente.get(f"/api/casos/{CASO}/expediente/1a-008/archivo")
    assert r.status_code == 404 and b"secreto" not in r.content


def test_archivo_enlace_simbolico_fuera_de_insumos(cliente, caso_dir, tmp_path):
    secreto = tmp_path / "secreto.pdf"
    secreto.write_bytes(b"%PDF-secreto")
    (caso_dir / "insumos" / "1a" / "enlace.pdf").symlink_to(secreto)
    _con_ruta(caso_dir, "1a/enlace.pdf")
    r = cliente.get(f"/api/casos/{CASO}/expediente/1a-008/archivo")
    assert r.status_code == 404 and b"secreto" not in r.content


def test_archivo_doc_id_invalido(cliente):
    assert cliente.get(f"/api/casos/{CASO}/expediente/x/archivo").status_code == 422
    assert cliente.get(f"/api/casos/{CASO}/expediente/1a-999/archivo").status_code == 404


# --- certificado de vigencia: PUT y GET /apoderados/{ap}/certificado ---

FIXTURES_VIGENCIA = Path(__file__).parent / "fixtures" / "vigencia"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
VERDE = "ap-5c1d2e3f40"
NOMBRE_VERDE = "María Fernanda Prueba López"
CEDULA_VERDE = "1000000001"  # la del certificado de vigente.txt y de sintetico.pdf
OTRA_CEDULA = "1000000099"  # la de otra_cedula.txt
PARTE_VERDE = "Entidad Prestadora Uno"
TITULAR_VERDE = {"nombre": "MARIA FERNANDA PRUEBA LOPEZ", "cedula": CEDULA_VERDE, "tarjeta": "123456"}
PODER_VERDE = (
    "Por medio del presente escrito otorgo poder especial a la doctora MARÍA FERNANDA PRUEBA LÓPEZ, con T.P. 123456, "
    "para que represente a la Entidad Prestadora Uno en la acción de tutela de la referencia."
)
MENSAJE_VERDE = f"Hay apoderados no verificados sin revisar: {NOMBRE_VERDE}. Márquelos como revisados en el borrador."
NOMBRE_ARCHIVO = re.compile(r"ap-[0-9a-f]{10}-[0-9a-f]{16}\.pdf")


@pytest.fixture(scope="module")
def fixture_vigencia():
    spec = importlib.util.spec_from_file_location("fixture_vigencia", SCRIPTS / "fixture_vigencia.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sintetico() -> bytes:
    return (FIXTURES_VIGENCIA / "sintetico.pdf").read_bytes()


def _pdf_de(fv, texto: str) -> bytes:
    """El texto dibujado y cifrado como el certificado real; bytes distintos en cada llamada."""
    salida = io.BytesIO()
    fv.construir(texto).write(salida)
    return salida.getvalue()


def _certificado(fv, estado: str = "vigente", **titular) -> bytes:
    return _pdf_de(fv, fv.personalizar(fv.PLANTILLAS[estado].read_text(encoding="utf-8"), **titular))


def _otra_cedula(fv) -> bytes:
    return _pdf_de(fv, (FIXTURES_VIGENCIA / "otra_cedula.txt").read_text(encoding="utf-8"))


def _verde(**cambios) -> Apoderado:
    """Abogada con poder hallado para la parte que dice representar: verde en cuanto la tarjeta esté vigente."""
    datos = {
        "id": VERDE,
        "nombre": NOMBRE_VERDE,
        "parte": PARTE_VERDE,
        "rol_parte": "accionada",
        "tipo_persona": "natural",
        "cedula": CEDULA_VERDE,
        "tarjeta": "123456",
        "cedula_fuente": _ev("1a-008", 3, PODER_VERDE),
        "poderes": [Poder(tipo="poder", evidencia=_ev("1a-008", 3, PODER_VERDE), parte=PARTE_VERDE)],
    }
    return Apoderado(**{**datos, **cambios})


def _con(caso_dir: Path, *apoderados: Apoderado) -> None:
    registro_apoderados.espejar(
        caso_dir, Identificacion(ingesta_sha="abc", apoderados=list(apoderados), documentos_revisados=10)
    )


def _url_cert(ap_id: str = VERDE, caso: str = CASO) -> str:
    return f"/api/casos/{caso}/apoderados/{ap_id}/certificado"


def _subir(cliente: TestClient, datos: bytes, ap_id: str = VERDE, nombre: str = f"CV_RNA-TPA_{CEDULA_VERDE}.pdf"):
    """Como el navegador: el nombre del archivo descargado de la Rama Judicial lleva la cédula."""
    return cliente.put(_url_cert(ap_id), files={"archivo": (nombre, datos, "application/pdf")})


def _archivos(caso_dir: Path) -> list[str]:
    carpeta = caso_dir / "apoderados" / "certificados"
    return sorted(p.name for p in carpeta.iterdir()) if carpeta.is_dir() else []


def _poner_consulta(caso_dir: Path, certificado: str) -> None:
    consulta = registro_apoderados.ConsultaVigencia(
        estado="vigente", origen="manual", consultado_en="2026-11-17T10:43:00+00:00", certificado=certificado, sha256="ab" * 32
    )
    registro_apoderados.actualizar(caso_dir, lambda r: r.consultas.update({CEDULA_VERDE: consulta}))


@pytest.mark.parametrize("tarjeta", ["123456", None], ids=["tarjeta_coincide", "tarjeta_no_consta"])
def test_subir_certificado_vigente_lo_deja_en_verde(cliente, caso_dir, estado, tarjeta):
    _con(caso_dir, _verde(tarjeta=tarjeta))
    pdf = _sintetico()
    r = _subir(cliente, pdf)
    assert r.status_code == 200, r.text
    vista = ApoderadoVista.model_validate(r.json())
    assert (vista.estado, vista.fase, vista.bloquea, vista.motivos) == ("verificado", "listo", False, [])
    assert [c.ok for c in vista.cotejos] == [True, True if tarjeta else None, True]
    v = vista.vigencia
    assert (v.estado, v.fase, v.origen, v.cedula, v.tarjeta_registro) == ("vigente", "listo", "manual", CEDULA_VERDE, "123456")
    assert v.certificado_url == f"/api/casos/{CASO}/apoderados/{VERDE}/certificado"
    assert (v.numero_certificado, v.codigo_verificacion) == ("1234567", "0123456789abcdef" * 4)
    assert v.consultado_en and v.detalle == rutas_apoderados.DETALLE_MANUAL

    sha = hashlib.sha256(pdf).hexdigest()
    reg = registro_apoderados.leer(caso_dir)
    consulta = reg.consultas[CEDULA_VERDE]
    assert (consulta.estado, consulta.origen, consulta.sha256) == ("vigente", "manual", sha)
    assert consulta.certificado == f"certificados/{VERDE}-{sha[:16]}.pdf"
    assert consulta.datos == vigencia.leer_certificado(pdf)
    assert reg.ajustes == {}
    assert (caso_dir / "apoderados" / consulta.certificado).read_bytes() == pdf
    cuerpo = cliente.get(_url()).json()
    assert cuerpo["apoderados"] == [r.json()] and cuerpo["bloquea_decision"] is False


def test_certificado_no_vigente_pone_rojo_y_bloquea_la_decision(cliente, caso_dir, estado, comandos, fixture_vigencia):
    _con(caso_dir, _verde())
    r = _subir(cliente, _certificado(fixture_vigencia, "no_vigente", **TITULAR_VERDE))
    assert r.status_code == 200, r.text
    vista = r.json()
    assert (vista["estado"], vista["fase"], vista["bloquea"], vista["revisado"]) == ("no_verificado", "listo", True, False)
    assert vista["vigencia"]["estado"] == "no_vigente" and vista["vigencia"]["numero_certificado"] == "1234568"
    assert vista["motivos"][0] == "La tarjeta profesional 123456 figura como «SUSPENDIDO» en el certificado N.° 1234568."
    assert cliente.get(_url()).json()["bloquea_decision"] is True
    assert [b.id for b in estado_apoderados.bloqueos(caso_dir)] == [VERDE]

    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 409 and r.json()["detail"] == MENSAJE_VERDE
    assert server.JOBS == {} and comandos == []

    assert _marcar(cliente, VERDE).json()["bloquea"] is False
    r = cliente.post(f"/api/casos/{CASO}/run", json={"cmd": "decidir", "decision": DECISION})
    assert r.status_code == 200, r.text
    assert _esperar(cliente, r.json()["job_id"])["estado"] == "terminado"
    assert comandos == [("decidir", DECISION)]


def test_resubir_reemplaza_el_certificado_y_vence_la_revision(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde())
    primero = _certificado(fixture_vigencia, "no_vigente", **TITULAR_VERDE)
    segundo = _certificado(fixture_vigencia, "no_vigente", **TITULAR_VERDE)
    assert primero != segundo
    assert _subir(cliente, primero).status_code == 200
    assert _marcar(cliente, VERDE).json()["revisado"] is True
    assert cliente.get(_url()).json()["bloquea_decision"] is False

    # El mismo PDF otra vez es la misma evidencia: la revisión sigue valiendo.
    vista = _subir(cliente, primero).json()
    assert (vista["revisado"], vista["revision_vencida"], vista["bloquea"]) == (True, False, False)

    # Otro certificado cambia la huella: la revisión vence y la compuerta vuelve a cerrarse.
    vista = _subir(cliente, segundo).json()
    assert (vista["estado"], vista["revisado"], vista["revision_vencida"], vista["bloquea"]) == (
        "no_verificado", False, True, True
    )
    assert cliente.get(_url()).json()["bloquea_decision"] is True
    assert _archivos(caso_dir) == [f"{VERDE}-{hashlib.sha256(segundo).hexdigest()[:16]}.pdf"]
    assert list(registro_apoderados.leer(caso_dir).consultas) == [CEDULA_VERDE]

    vista = _subir(cliente, _sintetico()).json()
    assert (vista["estado"], vista["bloquea"]) == ("verificado", False)
    assert len(_archivos(caso_dir)) == 1
    assert cliente.get(_url_cert()).content == _sintetico()


MOTIVO_SIN_CEDULA_M1 = (
    "No consta la cédula del abogado junto a su nombre en las páginas comprobadas; "
    "la vigencia de su tarjeta profesional no se puede consultar automáticamente."
)
COTEJO_CEDULA_DEL_CERTIFICADO = "La cédula se tomó del certificado subido; no consta en el expediente"


def test_sin_cedula_verificada_se_toma_la_del_certificado(cliente, caso_dir, estado):
    _con(caso_dir, _verde(cedula=None, cedula_fuente=None, motivos=[MOTIVO_SIN_CEDULA_M1]))
    vista = _subir(cliente, _sintetico()).json()
    assert (vista["estado"], vista["cedula"], vista["vigencia"]["estado"]) == ("verificado", CEDULA_VERDE, "vigente")
    assert registro_apoderados.leer(caso_dir).ajustes[VERDE].cedula == CEDULA_VERDE
    # La T.P. del expediente coincide con la del certificado: eso lo ata al abogado. Se dice de dónde
    # salió la cédula y el motivo de la identificación que pedía consultarla deja de mostrarse.
    assert vista["motivos"] == [
        "La cédula del abogado no consta en el expediente: se tomó del certificado de vigencia subido."
    ]
    assert {"ok": None, "texto": COTEJO_CEDULA_DEL_CERTIFICADO} in vista["cotejos"]
    assert [c["ok"] for c in vista["cotejos"]] == [True, True, None, True]


def test_sin_cedula_ni_tarjeta_en_el_expediente_el_certificado_subido_queda_en_ambar(cliente, caso_dir, estado, fixture_vigencia):
    """Solo el nombre ata el certificado al abogado: «Juan Pérez» aceptaría el de «JUAN PEREZ GOMEZ»."""
    _con(caso_dir, _verde(cedula=None, tarjeta=None, cedula_fuente=None, motivos=[MOTIVO_SIN_CEDULA_M1]))
    vista = _subir(cliente, _certificado(fixture_vigencia, "vigente", nombre="MARIA FERNANDA PRUEBA LOPEZ GIRALDO")).json()
    assert (vista["estado"], vista["fase"], vista["bloquea"]) == ("revisar", "listo", False)
    assert vista["vigencia"]["estado"] == "vigente" and vista["cedula"] == CEDULA_VERDE
    assert vista["motivos"] == [
        "La cédula del abogado no consta en el expediente: se tomó del certificado de vigencia subido, y sin la tarjeta "
        "profesional del expediente solo el nombre lo ata al abogado: confirme que es suyo."
    ]
    assert {"ok": None, "texto": COTEJO_CEDULA_DEL_CERTIFICADO} in vista["cotejos"]


def test_sin_cedula_verificada_un_certificado_a_otro_nombre_es_422_y_no_guarda_nada(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde(cedula=None, cedula_fuente=None))
    r = _subir(cliente, _otra_cedula(fixture_vigencia), nombre=f"CV_RNA-TPA_{OTRA_CEDULA}.pdf")
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.OTRA_PERSONA}
    reg = registro_apoderados.leer(caso_dir)
    assert reg.consultas == {} and reg.ajustes == {} and _archivos(caso_dir) == []

    vista = _subir(cliente, _sintetico()).json()
    assert (vista["estado"], vista["cedula"]) == ("verificado", CEDULA_VERDE)


def test_sin_cedula_verificada_otro_certificado_a_su_nombre_reemplaza_al_anterior(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde(cedula=None, cedula_fuente=None))
    homonimo = _certificado(fixture_vigencia, "vigente", nombre="MARIA FERNANDA PRUEBA LOPEZ", cedula=OTRA_CEDULA, tarjeta="654321")
    vista = _subir(cliente, homonimo).json()
    assert (vista["estado"], vista["cedula"]) == ("no_verificado", OTRA_CEDULA)  # su T.P. no es la del expediente
    reg = registro_apoderados.leer(caso_dir)
    assert reg.ajustes[VERDE].cedula == OTRA_CEDULA and list(reg.consultas) == [OTRA_CEDULA]
    anterior = _archivos(caso_dir)

    # El certificado correcto reemplaza al del homónimo, que no se conserva.
    vista = _subir(cliente, _sintetico()).json()
    assert (vista["estado"], vista["cedula"]) == ("verificado", CEDULA_VERDE)
    reg = registro_apoderados.leer(caso_dir)
    assert reg.ajustes[VERDE].cedula == CEDULA_VERDE and list(reg.consultas) == [CEDULA_VERDE]
    assert len(_archivos(caso_dir)) == 1 and _archivos(caso_dir) != anterior


@pytest.mark.parametrize("estado_cert", ["no_vigente", "vigente"])
def test_el_certificado_de_un_abogado_subido_a_otro_sin_cedula_no_toca_al_primero(cliente, caso_dir, estado, fixture_vigencia, estado_cert):
    """La consulta es de la cédula: subirla por error en la ayuda de otro abogado no la cambia ni abre la compuerta."""
    otro = "ap-0123456789"
    _con(caso_dir, _verde(), _verde(id=otro, nombre="Pedro José Ficticio Mora", cedula=None, cedula_fuente=None))
    pdf = _certificado(fixture_vigencia, estado_cert, **TITULAR_VERDE)
    primero = _subir(cliente, pdf).json()
    antes = cliente.get(_url()).json()
    archivos = _archivos(caso_dir)

    r = _subir(cliente, pdf, ap_id=otro)
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.OTRA_PERSONA}
    despues = cliente.get(_url()).json()
    assert despues == antes and despues["apoderados"][0] == primero
    assert despues["bloquea_decision"] is (estado_cert == "no_vigente")
    assert _archivos(caso_dir) == archivos and registro_apoderados.leer(caso_dir).ajustes == {}


def test_dos_apoderados_con_la_misma_cedula_y_otro_nombre_cada_uno_coteja_el_suyo(cliente, caso_dir, estado, fixture_vigencia):
    """Si la identificación emparejó la misma cédula con dos nombres, el certificado solo vale para el que nombra."""
    otro = "ap-0123456789"
    _con(caso_dir, _verde(), _verde(id=otro, nombre="Pedro José Ficticio Mora"))
    r = _subir(cliente, _sintetico(), ap_id=otro)
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["vigencia"]["estado"]) == ("revisar", "otra_persona")
    verde, ambar = cliente.get(_url()).json()["apoderados"]
    assert (verde["estado"], verde["vigencia"]["estado"]) == ("verificado", "vigente")
    assert ambar == r.json()
    assert registro_apoderados.leer(caso_dir).consultas[CEDULA_VERDE].estado == "vigente"


def test_la_cedula_verificada_manda_sobre_una_tomada_de_otro_certificado(cliente, caso_dir, estado):
    _con(caso_dir, _verde())
    registro_apoderados.actualizar(caso_dir, lambda r: r.ajustes.update({VERDE: registro_apoderados.Ajuste(cedula=OTRA_CEDULA)}))
    vista = _subir(cliente, _sintetico()).json()
    assert (vista["estado"], vista["cedula"]) == ("verificado", CEDULA_VERDE)
    assert registro_apoderados.leer(caso_dir).ajustes == {}


def test_misma_cedula_con_otro_nombre_queda_en_ambar(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde())
    vista = _subir(cliente, _certificado(fixture_vigencia, "vigente", nombre="PEDRO JOSE FICTICIO MORA")).json()
    assert (vista["estado"], vista["vigencia"]["estado"], vista["bloquea"]) == ("revisar", "otra_persona", False)


def test_certificado_de_otra_cedula_es_422_y_no_guarda_nada(cliente, caso_dir, estado, fixture_vigencia, caplog):
    caplog.set_level(logging.DEBUG)
    _con(caso_dir, _verde())
    r = _subir(cliente, _otra_cedula(fixture_vigencia), nombre=f"CV_RNA-TPA_{OTRA_CEDULA}.pdf")
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.OTRA_PERSONA}
    reg = registro_apoderados.leer(caso_dir)
    assert reg.consultas == {} and reg.ajustes == {} and _archivos(caso_dir) == []
    assert OTRA_CEDULA not in caplog.text and CEDULA_VERDE not in caplog.text


@pytest.mark.parametrize("ocr", [False, True], ids=["cedula_sin_ocr", "cedula_con_ocr"])
def test_certificado_de_cedula_no_inscrita_con_cedula_verificada(cliente, caso_dir, estado, fixture_vigencia, ocr, caplog):
    caplog.set_level(logging.DEBUG)
    _con(caso_dir, _verde(cedula_fuente=_ev("1a-008", 3, PODER_VERDE, ocr=ocr)))
    pdf = _certificado(fixture_vigencia, "no_inscrito", cedula=CEDULA_VERDE)
    r = _subir(cliente, pdf)
    assert r.status_code == 200, r.text
    vista = r.json()
    rojo = not ocr
    assert (vista["estado"], vista["bloquea"]) == (("no_verificado", True) if rojo else ("revisar", False))
    assert (vista["vigencia"]["estado"], vista["vigencia"]["numero_certificado"], vista["cedula"]) == ("no_inscrito", "7654321", CEDULA_VERDE)
    assert vista["vigencia"]["grave"] is rojo
    assert vista["motivos"][0] == estado_apoderados.MOTIVO_NO_INSCRITO
    assert cliente.get(_url()).json()["bloquea_decision"] is rojo
    consulta = registro_apoderados.leer(caso_dir).consultas[CEDULA_VERDE]
    assert (consulta.estado, consulta.origen, consulta.datos.inscrito, consulta.datos.nombre) == ("no_inscrito", "manual", False, None)
    assert registro_apoderados.leer(caso_dir).ajustes == {}
    assert CEDULA_VERDE not in caplog.text


def test_certificado_de_cedula_no_inscrita_de_otra_cedula_es_422(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde())
    r = _subir(cliente, _certificado(fixture_vigencia, "no_inscrito", cedula=OTRA_CEDULA))
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.OTRA_PERSONA}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_certificado_sin_nombre_para_un_abogado_sin_cedula_es_422_y_no_guarda_nada(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde(cedula=None, cedula_fuente=None))
    pdf = _certificado(fixture_vigencia, "no_inscrito", cedula=CEDULA_VERDE)
    r = _subir(cliente, pdf)
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.SIN_NOMBRE}
    assert rutas_apoderados.SIN_NOMBRE == "El certificado no trae nombre: escriba primero la cédula del abogado."
    reg = registro_apoderados.leer(caso_dir)
    assert reg.consultas == {} and reg.ajustes == {} and _archivos(caso_dir) == []

    # Con la cédula escrita a mano, el mismo certificado se acepta si es de ella; queda en ámbar.
    registro_apoderados.actualizar(caso_dir, lambda r: r.ajustes.update({VERDE: registro_apoderados.Ajuste(cedula=OTRA_CEDULA)}))
    r = _subir(cliente, pdf)
    assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.OTRA_PERSONA}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []
    registro_apoderados.actualizar(caso_dir, lambda r: r.ajustes.update({VERDE: registro_apoderados.Ajuste(cedula=CEDULA_VERDE)}))
    r = _subir(cliente, pdf)
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["vigencia"]["estado"], r.json()["bloquea"]) == ("revisar", "no_inscrito", False)
    assert r.json()["vigencia"]["grave"] is False
    # El certificado no trae nombre: la cédula la indicó quien revisa, no se tomó de él.
    assert "La cédula del abogado no consta en el expediente: la indicó a mano quien revisa." in r.json()["motivos"]
    assert registro_apoderados.leer(caso_dir).ajustes[VERDE].cedula == CEDULA_VERDE


def test_un_certificado_sirve_a_otro_apoderado_con_la_misma_cedula(cliente, caso_dir, estado):
    otro = _verde(id="ap-1111111111", parte="Otra Entidad", poderes=[], ajenos=[])
    _con(caso_dir, _verde(), otro)
    assert _subir(cliente, _sintetico()).status_code == 200
    _, segundo = cliente.get(_url()).json()["apoderados"]
    assert segundo["vigencia"]["estado"] == "vigente" and segundo["estado"] == "revisar"
    assert cliente.get(segundo["vigencia"]["certificado_url"]).content == _sintetico()


@pytest.mark.parametrize(
    "datos, detalle",
    [
        (b"", rutas_apoderados.NO_ES_PDF),
        (b"<html><body>Request blocked</body></html>", rutas_apoderados.NO_ES_PDF),
        (b"PK\x03\x04 un docx", rutas_apoderados.NO_ES_PDF),
        (b" %PDF-1.7 con un espacio antes", rutas_apoderados.NO_ES_PDF),
        (b"%PDF-1.7\nesto no es un pdf", rutas_apoderados.ILEGIBLE),
    ],
)
def test_subir_lo_que_no_es_un_certificado_es_422(cliente, caso_dir, estado, datos, detalle):
    _con(caso_dir, _verde())
    r = _subir(cliente, datos)
    assert r.status_code == 422 and r.json() == {"detail": detalle}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_pdf_sin_certificado_o_cortado_es_422(cliente, caso_dir, estado, fixture_vigencia):
    _con(caso_dir, _verde())
    carta = _pdf_de(fixture_vigencia, "Una carta cualquiera\nsin certificado de vigencia")
    for datos in (carta, _sintetico()[:300]):
        r = _subir(cliente, datos)
        assert r.status_code == 422 and r.json() == {"detail": rutas_apoderados.ILEGIBLE}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_subir_sin_archivo_es_422(cliente, caso_dir, estado):
    _con(caso_dir, _verde())
    assert cliente.put(_url_cert(), files={"otro": ("x.pdf", _sintetico(), "application/pdf")}).status_code == 422


def test_subir_mas_de_2_mib_es_413(cliente, caso_dir, estado):
    _con(caso_dir, _verde())
    maximo = rutas_apoderados.MAX_BYTES_CERTIFICADO
    assert maximo == 2 * 1024 * 1024
    justo = b"%PDF-1.7\n" + b"0" * (maximo - 9)
    assert len(justo) == maximo
    assert _subir(cliente, justo).json() == {"detail": rutas_apoderados.ILEGIBLE}
    r = _subir(cliente, justo + b"0")
    assert r.status_code == 413 and r.json() == {"detail": rutas_apoderados.MUY_GRANDE}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


@pytest.mark.parametrize("caso_estado", ["terminado", "error", "revision", "sin_iniciar"])
def test_subir_certificado_409_fuera_de_la_decision(cliente, caso_dir, estado, caso_estado):
    _con(caso_dir, _verde())
    estado["estado"] = caso_estado
    r = _subir(cliente, _sintetico())
    assert r.status_code == 409 and r.json() == {"detail": rutas_apoderados.NO_EDITABLE}
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_subir_certificado_409_con_job_en_curso(cliente, caso_dir, estado):
    _con(caso_dir, _verde())
    server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
    assert _subir(cliente, _sintetico()).status_code == 409
    assert registro_apoderados.leer(caso_dir).consultas == {}


def test_job_que_empieza_mientras_se_lee_el_pdf_deja_la_subida_en_409(cliente, caso_dir, estado, monkeypatch):
    _con(caso_dir, _verde())
    leer = vigencia.leer_certificado

    def con_job(pdf: bytes):
        server.JOBS["j1"] = {"id": "j1", "caso": CASO, "cmd": "decidir", "estado": "corriendo"}
        return leer(pdf)

    monkeypatch.setattr(vigencia, "leer_certificado", con_job)
    assert _subir(cliente, _sintetico()).status_code == 409
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_subir_certificado_404(cliente, caso_dir, estado):
    assert _subir(cliente, _sintetico()).status_code == 404
    assert not (caso_dir / "apoderados").exists()
    _con(caso_dir, _verde())
    r = _subir(cliente, _sintetico(), ap_id="ap-desconocido")
    assert r.status_code == 404 and r.json() == {"detail": rutas_apoderados.NO_ENCONTRADO}
    r = cliente.put(_url_cert(caso="otro"), files={"archivo": ("c.pdf", _sintetico(), "application/pdf")})
    assert r.status_code == 404
    assert registro_apoderados.leer(caso_dir).consultas == {} and _archivos(caso_dir) == []


def test_si_nuevo_borra_el_registro_mientras_se_lee_el_pdf_no_lo_resucita(cliente, caso_dir, estado, monkeypatch):
    _con(caso_dir, _verde())
    leer = vigencia.leer_certificado

    def con_nuevo(pdf: bytes):
        registro_apoderados.borrar(caso_dir)
        return leer(pdf)

    monkeypatch.setattr(vigencia, "leer_certificado", con_nuevo)
    assert _subir(cliente, _sintetico()).status_code == 404
    assert not (caso_dir / "apoderados").exists()


def test_descargar_certificado_en_linea(cliente, caso_dir, estado):
    _con(caso_dir, _verde())
    r = cliente.get(_url_cert())
    assert r.status_code == 404 and r.json() == {"detail": rutas_apoderados.SIN_CERTIFICADO}
    assert _subir(cliente, _sintetico()).status_code == 200
    r = cliente.get(_url_cert())
    assert r.status_code == 200 and r.content == _sintetico()
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert f"certificado-vigencia-{VERDE}.pdf" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert CEDULA_VERDE not in json.dumps(dict(r.headers))
    assert cliente.get(_url_cert("ap-desconocido")).status_code == 404
    assert cliente.get(_url_cert(caso="otro")).status_code == 404
    assert cliente.get(f"/api/casos/{CASO}/apoderados/..%2F..%2Fcaso.json/certificado").status_code == 404


@pytest.mark.parametrize(
    "certificado",
    [
        "../caso.json",
        "certificados/../../caso.json",
        "certificados/../registro.json",
        "registro.json",
        "/etc/hostname",
        "certificados/no-existe.pdf",
        "certificados",
    ],
)
def test_descargar_certificado_no_sale_de_la_carpeta(cliente, caso_dir, estado, certificado):
    _con(caso_dir, _verde())
    (caso_dir / "apoderados" / "certificados").mkdir()
    _poner_consulta(caso_dir, certificado)
    r = cliente.get(_url_cert())
    assert r.status_code == 404 and r.json() == {"detail": rutas_apoderados.SIN_CERTIFICADO}


def test_descargar_certificado_enlace_simbolico_fuera(cliente, caso_dir, estado, tmp_path):
    _con(caso_dir, _verde())
    secreto = tmp_path / "secreto.pdf"
    secreto.write_bytes(b"%PDF-secreto")
    (caso_dir / "apoderados" / "certificados").mkdir()
    (caso_dir / "apoderados" / "certificados" / "enlace.pdf").symlink_to(secreto)
    _poner_consulta(caso_dir, "certificados/enlace.pdf")
    r = cliente.get(_url_cert())
    assert r.status_code == 404 and b"secreto" not in r.content


def test_carpeta_de_certificados_enlazada_fuera_no_se_lee_ni_se_escribe(caso_dir, estado, tmp_path):
    _con(caso_dir, _verde())
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "x.pdf").write_bytes(b"%PDF-secreto")
    (caso_dir / "apoderados" / "certificados").symlink_to(fuera, target_is_directory=True)
    _poner_consulta(caso_dir, "certificados/x.pdf")
    cliente = TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    r = cliente.get(_url_cert())
    assert r.status_code == 404 and b"secreto" not in r.content
    assert _subir(cliente, _sintetico()).status_code == 500
    assert sorted(p.name for p in fuera.iterdir()) == ["x.pdf"]
    assert registro_apoderados.leer(caso_dir).consultas[CEDULA_VERDE].certificado == "certificados/x.pdf"


def test_ni_los_archivos_ni_los_registros_llevan_la_cedula(cliente, caso_dir, estado, fixture_vigencia, caplog):
    caplog.set_level(logging.DEBUG)
    sin_cedula = _verde(id="ap-2222222222", nombre="Pedro José Ficticio Mora", cedula=None, cedula_fuente=None, parte="Otra")
    _con(caso_dir, _verde(), sin_cedula)
    subidas = [
        (VERDE, _certificado(fixture_vigencia, "no_vigente", **TITULAR_VERDE), 200),
        (VERDE, _sintetico(), 200),
        (VERDE, _otra_cedula(fixture_vigencia), 422),
        (VERDE, b"%PDF-1.7\nroto", 422),
        ("ap-2222222222", _otra_cedula(fixture_vigencia), 200),
    ]
    for ap_id, datos, codigo in subidas:
        r = _subir(cliente, datos, ap_id=ap_id)
        assert r.status_code == codigo, r.text
    assert "Certificado de vigencia subido para el apoderado" in caplog.text

    for cedula in (CEDULA_VERDE, OTRA_CEDULA):
        assert cedula not in caplog.text
        assert not [p for p in caso_dir.rglob("*") if cedula in str(p.relative_to(caso_dir))]
    assert len(_archivos(caso_dir)) == 2 and all(NOMBRE_ARCHIVO.fullmatch(n) for n in _archivos(caso_dir))


# --- fixtures de punta a punta y script que los hace ---


def test_los_certificados_e2e_son_de_la_abogada_del_caso_sintetico(fixture_vigencia):
    abogada = fixture_vigencia.abogada_e2e()
    assert set(fixture_vigencia.SALIDAS_E2E) == {"vigente", "no_vigente"}
    for estado_esperado, archivo in fixture_vigencia.SALIDAS_E2E.items():
        assert PdfReader(archivo).is_encrypted
        cert = vigencia.leer_certificado(archivo.read_bytes())
        assert cert is not None
        assert (cert.nombre, cert.documento, cert.tpa_numero) == (abogada["nombre"], abogada["cedula"], abogada["tarjeta"]), (
            f"{archivo.name} no es de la abogada de scripts/caso_sintetico.py: "
            "ejecute `uv run python scripts/fixture_vigencia.py --e2e`"
        )
        assert vigencia.clasificar(cert, abogada["cedula"], abogada["nombre"].title()) == estado_esperado


def test_el_script_rehace_los_certificados_e2e(fixture_vigencia, tmp_path, monkeypatch):
    salidas = {"vigente": tmp_path / "v.pdf", "no_vigente": tmp_path / "nv.pdf"}
    monkeypatch.setattr(fixture_vigencia, "SALIDAS_E2E", salidas)
    assert fixture_vigencia.main(["--e2e"]) == 0
    for estado_esperado, archivo in salidas.items():
        cert = vigencia.leer_certificado(archivo.read_bytes())
        assert cert.documento == fixture_vigencia.abogada_e2e()["cedula"]
        assert vigencia.clasificar(cert, cert.documento, cert.nombre) == estado_esperado


def test_el_script_hace_un_certificado_para_otro_titular(fixture_vigencia, tmp_path):
    salida = tmp_path / "otro.pdf"
    argumentos = ["--estado", "no_vigente", "--nombre", "Ana  Lucía Ejemplo Ruiz", "--cedula", "1.000.000.005"]
    assert fixture_vigencia.main([*argumentos, "--tarjeta", "98765", "-s", str(salida)]) == 0
    cert = vigencia.leer_certificado(salida.read_bytes())
    assert (cert.nombre, cert.documento, cert.tpa_numero, cert.tpa_fecha, cert.tpa_estado) == (
        "ANA LUCÍA EJEMPLO RUIZ", "1000000005", "98765", "04/12/2006", "SUSPENDIDO"
    )
    assert vigencia.clasificar(cert, "1000000005", "Ana Lucía Ejemplo Ruiz") == "no_vigente"


def test_personalizar_conserva_las_columnas_de_la_fila_de_la_tarjeta(fixture_vigencia):
    plantilla = fixture_vigencia.PLANTILLAS["vigente"].read_text(encoding="utf-8")
    fila = next(linea for linea in plantilla.splitlines() if "CON TPA" in linea)
    for tarjeta in ("987", "1234567"):
        nueva = next(
            linea for linea in fixture_vigencia.personalizar(plantilla, tarjeta=tarjeta).splitlines() if "CON TPA" in linea
        )
        assert nueva.index("04/12/2006") == fila.index("04/12/2006") and f" {tarjeta} " in nueva
    assert fixture_vigencia.personalizar(plantilla) == plantilla


def test_el_script_sin_argumentos_sigue_haciendo_el_sintetico(fixture_vigencia, tmp_path, monkeypatch):
    monkeypatch.setattr(fixture_vigencia, "SALIDA_DEFECTO", tmp_path / "sintetico.pdf")
    assert fixture_vigencia.main([]) == 0
    assert vigencia.leer_certificado((tmp_path / "sintetico.pdf").read_bytes()) == vigencia.leer_certificado(_sintetico())


@pytest.mark.parametrize(
    "argumentos",
    [
        ["--nombre", "Ana Ejemplo"],
        ["--estado", "no_vigente"],
        ["--cedula", "12", "-s", "x.pdf"],
        ["--cedula", "12345678901", "-s", "x.pdf"],
        ["--tarjeta", "12", "-s", "x.pdf"],
        ["--nombre", "Ana", "-s", "x.pdf"],
        ["--nombre", "Ana 3jemplo", "-s", "x.pdf"],
        ["--e2e", "-s", "x.pdf"],
        ["--e2e", "--cedula", "1000000005"],
        ["--e2e", "--estado", "vigente"],
        ["--estado", "vencido", "-s", "x.pdf"],
        ["-e", "sin_tpa.txt", "--tarjeta", "123", "-s", "x.pdf"],
    ],
)
def test_el_script_rechaza_argumentos_invalidos(fixture_vigencia, tmp_path, monkeypatch, argumentos):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fixture_vigencia, "SALIDA_DEFECTO", tmp_path / "sintetico.pdf")
    monkeypatch.setattr(fixture_vigencia, "SALIDAS_E2E", {"vigente": tmp_path / "v.pdf", "no_vigente": tmp_path / "nv.pdf"})
    argumentos = [str(FIXTURES_VIGENCIA / a) if a.endswith(".txt") else a for a in argumentos]
    with pytest.raises(SystemExit) as e:
        fixture_vigencia.main(argumentos)
    assert e.value.code == 2
    assert list(tmp_path.iterdir()) == []


# --- archivos de certificados en el registro ---


def test_guardar_certificado_no_resucita_la_carpeta_ni_acepta_rutas(tmp_path):
    caso = tmp_path / "caso"
    caso.mkdir()
    with pytest.raises(FileNotFoundError):
        registro_apoderados.guardar_certificado(caso, "ap-0000000000-0123456789abcdef.pdf", b"%PDF-")
    assert not (caso / "apoderados").exists()

    (caso / "apoderados").mkdir()
    for nombre in ("", "../fuera.pdf", "certificados/x.pdf", ".oculto.pdf", "/tmp/x.pdf"):
        with pytest.raises(ValueError):
            registro_apoderados.guardar_certificado(caso, nombre, b"%PDF-")
    assert registro_apoderados.guardar_certificado(caso, "a.pdf", b"%PDF-1") == "certificados/a.pdf"
    assert registro_apoderados.guardar_certificado(caso, "a.pdf", b"%PDF-2") == "certificados/a.pdf"
    assert sorted(p.name for p in (caso / "apoderados" / "certificados").iterdir()) == ["a.pdf"]
    assert (caso / "apoderados" / "certificados" / "a.pdf").read_bytes() == b"%PDF-2"


def test_borrar_certificados_sin_uso_respeta_los_que_usa_una_consulta(tmp_path):
    caso = tmp_path / "caso"
    (caso / "apoderados").mkdir(parents=True)
    usado = registro_apoderados.guardar_certificado(caso, "usado.pdf", b"%PDF-u")
    suelto = registro_apoderados.guardar_certificado(caso, "suelto.pdf", b"%PDF-s")
    (caso / "caso.json").write_text("{}", encoding="utf-8")
    consulta = registro_apoderados.ConsultaVigencia(
        estado="vigente", origen="manual", consultado_en="2026-11-17T10:43:00+00:00", certificado=usado
    )
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA_VERDE: consulta}))
    registro_apoderados.borrar_certificados_sin_uso(caso, [usado, suelto, "../caso.json", "registro.json"])
    assert sorted(p.name for p in (caso / "apoderados" / "certificados").iterdir()) == ["usado.pdf"]
    assert (caso / "caso.json").exists() and registro_apoderados.ruta(caso).exists()


# --- POST /apoderados/consultar y la fase de la cola de consultas automáticas ---


@pytest.fixture
def cola(monkeypatch, tmp_path):
    """Una cola nueva, sin hilo, con reloj propio y la extensión conectada (se puede cambiar)."""
    from tutela2 import extension

    estado = types.SimpleNamespace(t=1_800_000_000.0, extension="conectada")
    monkeypatch.setattr(extension, "estado_conexion", lambda servicio="vigencia": estado.extension)

    def dormir(segundos: float) -> bool:
        estado.t += segundos
        return False

    estado.cola = vigencia.ColaVigencia(reloj=lambda: estado.t, dormir=dormir, carpeta_cache=tmp_path / "cache-vigencias")
    monkeypatch.setattr(vigencia, "COLA", estado.cola)
    return estado


@pytest.fixture
def con_consulta(monkeypatch):
    monkeypatch.setenv("TUTELA2_CONSULTA_VIGENCIA", "extension")


def _consultar(cliente: TestClient, **cuerpo):
    return cliente.post(f"/api/casos/{CASO}/apoderados/consultar", json=cuerpo)


def _por_id(cuerpo: dict) -> dict:
    return {a["id"]: a for a in cuerpo["apoderados"]}


def test_consultar_con_la_consulta_apagada_es_409_y_no_sale_nada(cliente, caso_dir, estado, cola):
    registro_apoderados.espejar(caso_dir, _ident())
    r = _consultar(cliente)
    assert r.status_code == 409 and r.json()["detail"] == rutas_apoderados.CONSULTA_APAGADA
    assert cola.cola._pedidos == {}
    cuerpo = cliente.get(_url()).json()
    assert cuerpo["consulta"] == {"activa": False, "extension": "conectada", "modo": "apagada", "pausa_hasta": None}
    assert _por_id(cuerpo)[ROJO]["fase"] == "necesita_ayuda"


@pytest.mark.parametrize("caso_estado", ["terminado", "error", "revision", "sin_iniciar"])
def test_consultar_409_fuera_de_la_decision(cliente, caso_dir, estado, cola, con_consulta, caso_estado):
    registro_apoderados.espejar(caso_dir, _ident())
    estado["estado"] = caso_estado
    r = _consultar(cliente)
    assert r.status_code == 409 and r.json()["detail"] == rutas_apoderados.NO_EDITABLE
    assert cola.cola._pedidos == {}


def test_consultar_pone_en_cola_y_el_get_muestra_la_fase(cliente, caso_dir, estado, cola, con_consulta):
    registro_apoderados.espejar(caso_dir, _ident())
    r = _consultar(cliente)
    assert r.status_code == 202
    cuerpo = r.json()
    ApoderadosRespuesta.model_validate(cuerpo)
    assert cuerpo["consulta"] == {"activa": True, "extension": "conectada", "modo": "extension", "pausa_hasta": None}
    rojo, ambar = _por_id(cuerpo)[ROJO], _por_id(cuerpo)["ap-0b51d2aa77"]
    assert (rojo["fase"], rojo["vigencia"]["fase"], rojo["vigencia"]["estado"]) == ("en_cola", "en_cola", "sin_consultar")
    assert ambar["fase"] == "necesita_ayuda"  # sin cédula no hay nada que consultar
    assert cliente.get(_url()).json() == cuerpo
    assert set(c for _, c in cola.cola._pedidos) == {CEDULA_ROJO}

    # Con la extensión desactualizada o sin conectar la consulta espera: el abogado necesita ayuda.
    for estado_extension in ("desactualizada", "no_conectada"):
        cola.extension = estado_extension
        cuerpo = cliente.get(_url()).json()
        assert cuerpo["consulta"]["activa"] is False and cuerpo["consulta"]["extension"] == estado_extension
        assert _por_id(cuerpo)[ROJO]["fase"] == "necesita_ayuda"


def test_consultar_solo_los_ids_pedidos(cliente, caso_dir, estado, cola, con_consulta):
    registro_apoderados.espejar(caso_dir, _ident())
    assert _consultar(cliente, ids=["ap-0b51d2aa77"]).status_code == 202
    assert cola.cola._pedidos == {}
    assert _consultar(cliente, ids=[ROJO, "ap-no-existe"]).status_code == 404
    assert cola.cola._pedidos == {}
    r = _consultar(cliente, ids=[ROJO, ROJO])
    assert r.status_code == 202 and _por_id(r.json())[ROJO]["fase"] == "en_cola"
    assert _consultar(cliente, ids=["x" * 65]).status_code == 422
    assert _consultar(cliente, forzar="sí").status_code == 422


def test_consultar_sin_forzar_salta_lo_resuelto_y_forzar_lo_consulta_de_nuevo(cliente, caso_dir, estado, cola, con_consulta):
    registro_apoderados.espejar(caso_dir, _ident())
    consulta = registro_apoderados.ConsultaVigencia(estado="no_vigente", origen="manual", consultado_en="2026-11-17T10:43:00+00:00")
    registro_apoderados.actualizar(caso_dir, lambda r: r.consultas.update({CEDULA_ROJO: consulta}))
    r = _consultar(cliente)
    assert r.status_code == 202 and _por_id(r.json())[ROJO]["fase"] == "listo" and cola.cola._pedidos == {}
    r = _consultar(cliente, ids=[ROJO], forzar=True)
    assert r.status_code == 202 and _por_id(r.json())[ROJO]["fase"] == "en_cola"
    assert r.json()["consulta"]["activa"] is True


def test_subir_el_certificado_saca_la_consulta_de_la_cola(cliente, caso_dir, estado, cola, con_consulta):
    """Con el certificado subido, la pestaña no sigue mostrando «En cola» ni la cédula sale después."""
    _con(caso_dir, _verde())
    assert _consultar(cliente).status_code == 202
    assert {c for _, c in cola.cola._pedidos} == {CEDULA_VERDE}
    r = _subir(cliente, _sintetico())
    assert r.status_code == 200, r.text
    assert (r.json()["fase"], r.json()["vigencia"]["origen"]) == ("listo", "manual")
    assert cola.cola._pedidos == {}
    cuerpo = cliente.get(_url()).json()
    assert cuerpo["consulta"]["activa"] is False and [a["fase"] for a in cuerpo["apoderados"]] == ["listo"]


def test_la_vista_dice_si_hay_un_poder_hallado_al_que_volver(cliente, caso_dir, estado):
    sin_poder = _verde(id="ap-0000000001", nombre="Pedro Pablo Ejemplo Ruiz", cedula="52345671", poderes=[])
    _con(caso_dir, _verde(), sin_poder)
    poderes = {a["id"]: a["poder"] for a in cliente.get(_url()).json()["apoderados"]}
    assert (poderes[VERDE]["estado"], poderes[VERDE]["hay_hallado"]) == ("hallado", True)
    assert (poderes[sin_poder.id]["estado"], poderes[sin_poder.id]["hay_hallado"]) == ("sin_poder", False)
    # Descartado, el hallado sigue ahí para «Deshacer el descarte».
    registro_apoderados.actualizar(caso_dir, lambda r: r.ajustes.update({VERDE: registro_apoderados.Ajuste(poder_descartado=True)}))
    poder = next(a["poder"] for a in cliente.get(_url()).json()["apoderados"] if a["id"] == VERDE)
    assert (poder["estado"], poder["hay_hallado"]) == ("descartado", True)


def test_el_get_muestra_la_pausa_de_la_cola_tras_quedar_sin_respuesta(cliente, caso_dir, estado, cola, con_consulta, monkeypatch):
    from tutela2 import extension

    def falla(*args, **kwargs):
        raise TimeoutError("la extensión no respondió a tiempo")

    monkeypatch.setattr(extension, "pedir", falla)
    registro_apoderados.espejar(caso_dir, _ident())
    _consultar(cliente)
    while (espera := cola.cola.paso()) == 0:
        pass
    cuerpo = cliente.get(_url()).json()
    hasta = cola.t + vigencia.ENFRIAMIENTO_S
    assert cuerpo["consulta"]["pausa_hasta"] == vigencia._iso(hasta) and espera == pytest.approx(vigencia.ENFRIAMIENTO_S)
    rojo = _por_id(cuerpo)[ROJO]
    assert (rojo["vigencia"]["estado"], rojo["fase"], cuerpo["consulta"]["activa"]) == ("inaccesible", "necesita_ayuda", False)
    assert rojo["vigencia"]["detalle"] == vigencia.SIN_RESPUESTA and rojo["vigencia"]["origen"] == "extension"

    # «Reintentar consulta automática» la deja en cola, pero espera a que pase la pausa.
    rojo = _por_id(_consultar(cliente, ids=[ROJO], forzar=True).json())[ROJO]
    assert rojo["fase"] == "en_cola" and cola.cola.paso() == pytest.approx(vigencia.ENFRIAMIENTO_S)
    monkeypatch.setenv("TUTELA2_CONSULTA_VIGENCIA", "apagada")
    assert cliente.get(_url()).json()["consulta"]["pausa_hasta"] is None


def test_con_el_proveedor_falso_la_abogada_queda_en_verde_sin_subir_nada(cliente, caso_dir, estado, cola, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from test_graph import ingesta_con_abogada

    from tutela2 import config as cfgmod
    from tutela2 import graph
    from tutela2.llm import FakeClient

    monkeypatch.setenv("TUTELA2_PROVEEDOR", "fake")
    cfg = cfgmod.cargar(caso_dir)
    assert cfg.apoderados.consulta == "fake"
    g = graph.construir(cfg, FakeClient(), InMemorySaver())
    g.invoke(graph.estado_inicial(caso_dir, cfg, ingesta_con_abogada()), {"configurable": {"thread_id": CASO}}, durability="sync")

    [ap] = registro_apoderados.leer(caso_dir).identificacion.apoderados
    antes = cliente.get(_url()).json()
    [vista] = antes["apoderados"]
    assert (vista["id"], vista["estado"], vista["fase"]) == (ap.id, "revisar", "en_cola")
    assert antes["consulta"]["activa"] is True and antes["consulta"]["modo"] == "fake"

    while cola.cola.paso() is not None:
        pass
    despues = cliente.get(_url()).json()
    [vista] = despues["apoderados"]
    assert (vista["estado"], vista["fase"], vista["bloquea"], despues["consulta"]["activa"]) == ("verificado", "listo", False, False)
    assert (vista["vigencia"]["estado"], vista["vigencia"]["origen"]) == ("vigente", "fake")
    assert vista["vigencia"]["tarjeta_registro"] == ap.tarjeta and vista["motivos"] == []
    pdf = cliente.get(vista["vigencia"]["certificado_url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert vigencia.AVISO_FICTICIO in "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert not (caso_dir.parent.parent / "cache-vigencias").exists()  # la consulta simulada no usa la caché
