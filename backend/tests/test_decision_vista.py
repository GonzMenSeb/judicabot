from __future__ import annotations

import importlib.util
import itertools
import json
import os
import random
import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from test_graph import DECISION, Verificador, ingesta_sintetica

from tutela2 import api, decision_vista, formulas, ingest, salidas, server
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.models import Decision, Metadatos

SEMILLA = 20261103
VALIDAS_RESULTADO = ("CONFIRMAR", "REVOCAR", "MODIFICAR")
VALIDAS_SUSTITUTIVA = (
    "AMPARAR",
    "NEGAR",
    "IMPROCEDENTE",
    "CARENCIA_HECHO_SUPERADO",
    "CARENCIA_DANO_CONSUMADO",
    "CARENCIA_SOBREVINIENTE",
)
URL = "/api/casos/{}/decision/vista"


def _plano(numerales: list[formulas.Numeral]) -> list[dict]:
    return [{"clave": n.clave, "texto": n.texto, "negritas": n.negritas} for n in numerales]


@pytest.fixture(autouse=True)
def _cache_limpia():
    decision_vista._CACHE.clear()


@pytest.fixture(scope="module")
def rapido(tmp_path_factory) -> Path:
    raiz = tmp_path_factory.mktemp("casos_rapido")
    carpeta = raiz / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(citas_real, "cargar_dataset", lambda cfg: {})
        mp.setattr(citas_real, "verificar_citas", Verificador())
        mp.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
        assert api.nuevo(carpeta)["estado"] == "revision"
        assert api.iniciar(carpeta)["estado"] == "esperando_decision"
    return raiz


def _generador():
    ruta = Path(__file__).resolve().parents[1] / "scripts" / "caso_sintetico.py"
    spec = importlib.util.spec_from_file_location("caso_sintetico", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def sintetico(tmp_path_factory) -> tuple[Path, dict]:
    if not (shutil.which("soffice") and shutil.which("pdftotext")):
        pytest.skip("requiere soffice y pdftotext")
    modulo = _generador()
    raiz = tmp_path_factory.mktemp("casos_sintetico")
    carpeta = raiz / "sintetico"
    modulo.generar(carpeta)
    modulo.preparar(carpeta, "fake")
    resultados = modulo.ejecutar(carpeta, modulo.DECISION_POR_DEFECTO)
    assert resultados["decidir"]["estado"] == "terminado", resultados["decidir"]["error"]
    return raiz, modulo.DECISION_POR_DEFECTO


def _cliente(monkeypatch, raiz: Path) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(raiz))
    return TestClient(server.app, base_url="http://127.0.0.1")


@pytest.fixture
def cliente(monkeypatch, rapido) -> TestClient:
    return _cliente(monkeypatch, rapido)


def _md_del_estado(carpeta: Path) -> Metadatos:
    return Metadatos.model_validate(api.estado(carpeta)["resumen"]["metadatos"])


COMPLETAS = {
    "revocar_amparar": DECISION,
    "confirmar": {"accion": "decidir", "resultado": "CONFIRMAR", "eje": "Se comparte la tesis del a quo."},
    "negar_con_derechos": {
        "accion": "decidir",
        "resultado": "REVOCAR",
        "sustitutiva": "NEGAR",
        "eje": "No hay vulneración.",
        "derechos": [{"derecho": "salud", "disposicion": "NIEGA"}, {"derecho": "vida", "disposicion": "NIEGA"}],
    },
    "improcedente": {"accion": "decidir", "resultado": "MODIFICAR", "sustitutiva": "IMPROCEDENTE", "eje": "Subsidiariedad."},
    "carencia": {"accion": "decidir", "resultado": "REVOCAR", "sustitutiva": "CARENCIA_HECHO_SUPERADO", "eje": "Se entregó."},
    "todo": {
        **DECISION,
        "derechos": [{"derecho": "la salud", "disposicion": "AMPARA"}],
        "ordenes": [
            {
                "verbo": "ORDENAR",
                "destinatario": "la EPS Horizonte",
                "conducta": "entregue el medicamento",
                "plazo": {"n": 1, "unidad": "dias_habiles"},
                "condicion": "si aún no lo ha hecho",
                "literales": ["Informe al despacho", "Allegue constancia"],
            },
            {"verbo": "PREVENIR", "destinatario": "el Hospital", "conducta": "no repita la demora"},
            {"verbo": "ADVERTIR", "destinatario": "la clínica", "conducta": "debe atender", "mismo_termino": True},
        ],
        "prevenir": ["la EPS Horizonte", "el Hospital"],
        "desvincular": ["la Secretaría de Salud"],
        "compulsa": {"respecto_de": "el funcionario de turno", "hechos_ref": "los de la demora"},
        "numerales_libres": ["ENVIAR copia de este fallo al archivo.", "Comuníquese."],
        "orden_numerales": ["libre:0", "orden:0", "resultado", "sustitutiva"],
        "numerales": {"notificar": True, "remitir_corte": False},
        "fecha_fallo": "2026-11-03",
        "generar_formato": True,
        "clave_desconocida": {"x": [1, 2]},
    },
}


@pytest.mark.parametrize("nombre", sorted(COMPLETAS))
def test_numerales_equivalen_a_formulas_para_decisiones_completas(cliente, rapido, nombre):
    decision = COMPLETAS[nombre]
    md = _md_del_estado(rapido / "caso-api")
    esperado = _plano(formulas.numerales(Decision.model_validate(decision), md))
    r = cliente.post(URL.format("caso-api"), json=decision)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["numerales"] == esperado
    assert cuerpo["faltantes"] == [] and cuerpo["errores"] == []
    assert all(set(n) == {"clave", "texto", "negritas"} for n in cuerpo["numerales"])


def test_el_orden_libre_de_numerales_se_respeta(cliente):
    cuerpo = cliente.post(URL.format("caso-api"), json=COMPLETAS["todo"]).json()
    claves = [n["clave"] for n in cuerpo["numerales"]]
    assert claves[:4] == ["libre:0", "orden:0", "resultado", "sustitutiva"]
    assert "remitir" not in claves and "notificar" in claves


def test_los_metadatos_salen_del_checkpoint_y_no_solo_de_caso_json(cliente, rapido):
    carpeta = rapido / "caso-api"
    en_json = json.loads((carpeta / "caso.json").read_text(encoding="utf-8"))["metadatos"]
    assert not en_json.get("accionante_tratamiento")
    texto = {n["clave"]: n["texto"] for n in cliente.post(URL.format("caso-api"), json=DECISION).json()["numerales"]}
    assert "del señor MARTA EJEMPLO" in texto["sustitutiva"]
    assert "a la salud" in texto["sustitutiva"]


def test_sin_hilo_basta_caso_json_y_no_se_abre_sqlite(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-b"
    carpeta.mkdir()
    (carpeta / "caso.json").write_text(ingesta_sintetica().model_dump_json(), encoding="utf-8")
    abierto = []
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: abierto.append(a) or pytest.fail("no debía abrir sqlite"))
    cliente = _cliente(monkeypatch, tmp_path)
    r = cliente.post(URL.format("caso-b"), json=DECISION)
    assert r.status_code == 200 and not abierto
    texto = {n["clave"]: n["texto"] for n in r.json()["numerales"]}
    assert "MARTA EJEMPLO" in texto["sustitutiva"]
    assert not (carpeta / "hilo.sqlite").exists()


def test_sin_ingesta_los_metadatos_degradan_a_marcadores(tmp_path, monkeypatch):
    (tmp_path / "caso-c").mkdir()
    cliente = _cliente(monkeypatch, tmp_path)
    r = cliente.post(URL.format("caso-c"), json=DECISION)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["faltantes"] == [] and cuerpo["numerales"]
    assert "⟦FALTA: ACCIONANTE⟧" in {n["clave"]: n["texto"] for n in cuerpo["numerales"]}["sustitutiva"]
    assert not (tmp_path / "caso-c" / "hilo.sqlite").exists()


def test_un_hilo_corrupto_degrada_a_caso_json(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-d"
    carpeta.mkdir()
    (carpeta / "caso.json").write_text(ingesta_sintetica().model_dump_json(), encoding="utf-8")
    (carpeta / "hilo.sqlite").write_bytes(b"esto no es sqlite" * 50)
    cliente = _cliente(monkeypatch, tmp_path)
    r = cliente.post(URL.format("caso-d"), json=DECISION)
    assert r.status_code == 200
    assert "MARTA EJEMPLO" in {n["clave"]: n["texto"] for n in r.json()["numerales"]}["sustitutiva"]


def test_caso_json_ilegible_degrada(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-e"
    carpeta.mkdir()
    (carpeta / "caso.json").write_text('{"metadatos": [1, 2]', encoding="utf-8")
    assert decision_vista.metadatos_del_caso(carpeta) == Metadatos()
    (carpeta / "caso.json").write_text('{"metadatos": {"fechas": 5}}', encoding="utf-8")
    assert decision_vista.metadatos_del_caso(carpeta) == Metadatos()


def test_la_lectura_del_hilo_se_cachea_y_se_invalida(rapido, monkeypatch):
    carpeta = rapido / "caso-api"
    llamadas = []
    real = decision_vista._desde_hilo
    monkeypatch.setattr(decision_vista, "_desde_hilo", lambda d: llamadas.append(d) or real(d))
    primero = decision_vista.metadatos_del_caso(carpeta)
    assert decision_vista.metadatos_del_caso(carpeta) is primero and len(llamadas) == 1
    original = (carpeta / "caso.json").stat()
    try:
        os.utime(carpeta / "caso.json", ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000_000))
        assert decision_vista.metadatos_del_caso(carpeta).accionante == primero.accionante
        assert len(llamadas) == 2
    finally:
        os.utime(carpeta / "caso.json", ns=(original.st_atime_ns, original.st_mtime_ns))


def test_un_hilo_bloqueado_no_se_cachea(rapido, monkeypatch):
    carpeta = rapido / "caso-api"

    def bloqueado(_):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(decision_vista, "_desde_hilo", bloqueado)
    md = decision_vista.metadatos_del_caso(carpeta)
    assert md.accionante == "Marta Ejemplo" and not md.accionante_tratamiento
    assert not decision_vista._CACHE


def test_la_cache_tiene_tope(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_vista, "CACHE_MAX", 3)
    for i in range(6):
        carpeta = tmp_path / f"c{i}"
        carpeta.mkdir()
        decision_vista.metadatos_del_caso(carpeta)
    assert len(decision_vista._CACHE) == 3


def test_caso_inexistente_es_404(cliente):
    for nombre in ("no-existe", ".preferencias", "..%2F..%2Fetc"):
        r = cliente.post(URL.format(nombre), json=DECISION)
        assert r.status_code == 404, nombre
    assert cliente.post(URL.format("no-existe"), content=b"[1]").status_code == 404


@pytest.mark.parametrize("cuerpo", [b"[]", b"[1, 2]", b'"texto"', b"12", b"null", b"true"])
def test_cuerpo_que_no_es_objeto_es_422(cliente, cuerpo):
    r = cliente.post(URL.format("caso-api"), content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("cuerpo", [b"", b"{", b"{'a': 1}", b"NaN", b'{"eje": NaN}', b'{"a": Infinity}', b"\xff\xfe"])
def test_json_invalido_es_422(cliente, cuerpo):
    r = cliente.post(URL.format("caso-api"), content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_cuerpo_demasiado_grande_es_413_con_y_sin_content_length(cliente):
    enorme = b'{"eje": "' + b"a" * (256 * 1024) + b'"}'
    assert cliente.post(URL.format("caso-api"), content=enorme).status_code == 413

    def trozos():
        for i in range(0, len(enorme), 8192):
            yield enorme[i : i + 8192]

    assert cliente.post(URL.format("caso-api"), content=trozos()).status_code == 413


def test_anidamiento_extremo_no_es_500(cliente):
    for cuerpo in (b"[" * 200_000, b'{"eje": ' + b"[" * 100_000 + b"]" * 100_000 + b"}", b"[" * 400 + b"]" * 400):
        assert cliente.post(URL.format("caso-api"), content=cuerpo).status_code < 500
    anidado = json.dumps({"eje": "x", "extra": [[[[[[1]]]]]] * 50, "ordenes": [{"destinatario": {"a": [[]]}, "conducta": [[1]]}]})
    r = cliente.post(URL.format("caso-api"), content=anidado.encode())
    assert r.status_code == 200


def test_cadenas_gigantes_se_recortan_y_se_reportan(cliente):
    gigante = "ñ" * 55_000
    r = cliente.post(URL.format("caso-api"), json={**DECISION, "eje": gigante, "ordenes": [{"destinatario": "EPS", "conducta": gigante}]})
    assert r.status_code == 200
    cuerpo = r.json()
    assert {f["campo"] for f in cuerpo["faltantes"]} == {"eje", "ordenes.0.conducta"}
    assert max(len(n["texto"]) for n in cuerpo["numerales"]) < 10_000
    assert len(r.content) < 20_000


def test_sustitutos_sueltos_y_control_no_rompen_la_respuesta(cliente):
    crudo = '{"accion": "decidir", "eje": "\\ud800\\udc00\\ud800", "resultado": "CONFIRMAR", "numerales_libres": ["a\\u0000b\\ud83d"]}'
    r = cliente.post(URL.format("caso-api"), content=crudo.encode())
    assert r.status_code == 200
    textos = [n["texto"] for n in r.json()["numerales"]]
    assert any(t.startswith("ab") for t in textos)
    assert "\x00" not in r.text


def test_la_red_de_seguridad_responde_200_con_errores(cliente, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(decision_vista, "decision_vista", falla)
    r = cliente.post(URL.format("caso-api"), json=DECISION)
    assert r.status_code == 200
    assert r.json() == {"numerales": [], "faltantes": [], "errores": [decision_vista.ERROR_INTERNO]}


def test_si_fallan_los_metadatos_se_degrada_y_se_responde(cliente, monkeypatch):
    def falla(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(decision_vista, "metadatos_del_caso", falla)
    r = cliente.post(URL.format("caso-api"), json=DECISION)
    assert r.status_code == 200 and r.json()["numerales"] and r.json()["errores"] == []


def test_openapi_documenta_la_ruta():
    esquema = server.app.openapi()
    operacion = esquema["paths"]["/api/casos/{caso_id}/decision/vista"]["post"]
    assert operacion["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/DecisionVistaRespuesta")
    assert operacion["requestBody"]["content"]["application/json"]["schema"]["type"] == "object"
    assert {"404", "413", "422"} <= set(operacion["responses"])
    componentes = esquema["components"]["schemas"]
    assert set(componentes["DecisionVistaRespuesta"]["properties"]) == {"numerales", "faltantes", "errores"}
    assert set(componentes["NumeralVista"]["properties"]) == {"clave", "texto", "negritas"}
    assert set(componentes["FaltanteDecision"]["properties"]) == {"campo", "mensaje"}


NUMERALES_MINIMOS = {"notificar", "remitir"}


def test_decision_vacia_reporta_lo_que_falta_y_aun_arma_numerales(rapido):
    md = _md_del_estado(rapido / "caso-api")
    salida = decision_vista.decision_vista({}, md)
    assert {f["campo"] for f in salida["faltantes"]} == {"resultado", "sustitutiva", "eje"}
    assert NUMERALES_MINIMOS <= {n["clave"] for n in salida["numerales"]}
    assert salida["errores"] == list(dict.fromkeys(f["mensaje"] for f in salida["faltantes"]))
    assert decision_vista.decision_vista([], md) == {
        "numerales": [],
        "faltantes": [],
        "errores": ["La decisión debe ser un objeto."],
    }


def test_mensajes_de_validacion_coinciden_con_los_de_la_interfaz():
    salida = decision_vista.decision_vista(
        {
            "resultado": "REVOCAR",
            "sustitutiva": "AMPARAR",
            "eje": "x",
            "ordenes": [{"destinatario": "", "conducta": "", "plazo": {"n": 0}}],
            "compulsa": {},
        },
        Metadatos(),
    )
    assert set(salida["errores"]) == {
        "Cada orden necesita destinatario y conducta.",
        "El plazo de cada orden debe ser mayor que cero.",
        "La compulsa de copias necesita indicar respecto de quién.",
    }
    texto = {n["clave"]: n["texto"] for n in salida["numerales"]}
    assert "⟦FALTA: destinatario⟧" in texto["orden:0"] and "cuarenta y ocho (48)" in texto["orden:0"]
    assert "⟦FALTA: respecto de quién⟧" in texto["compulsa"]


def _t(valor, *campos):
    return valor, set(campos)


RESULTADOS = [_t(None), _t("CONFIRMAR"), _t("REVOCAR"), _t("MODIFICAR"), _t("revocar", "resultado"), _t(7, "resultado"), _t([], "resultado"), _t("")]
SUSTITUTIVAS = [_t(None), _t(""), *[_t(s) for s in VALIDAS_SUSTITUTIVA], _t("INVENTADA", "sustitutiva"), _t({}, "sustitutiva")]
EJES = [_t(None), _t(""), _t("   "), _t("Porque sí."), _t(5, "eje"), _t("x" * (decision_vista.MAX_TEXTO + 1), "eje"), _t("\x00\x01")]
ORDENES = [
    (None, set(), 0),
    ([], set(), 0),
    ("texto", {"ordenes"}, 0),
    ({"a": 1}, {"ordenes"}, 0),
    ([{}], {"ordenes.0.destinatario", "ordenes.0.conducta"}, 1),
    ([{"destinatario": "EPS", "conducta": "autorice"}], set(), 1),
    ([{"destinatario": "EPS", "conducta": "c", "plazo": {"n": 0}}], {"ordenes.0.plazo.n"}, 1),
    ([{"destinatario": "EPS", "conducta": "c", "plazo": {"n": 10**9}}], {"ordenes.0.plazo.n"}, 1),
    ([{"destinatario": "EPS", "conducta": "c", "plazo": {"n": "abc", "unidad": "siglos"}}], {"ordenes.0.plazo.n", "ordenes.0.plazo.unidad"}, 1),
    ([{"destinatario": "EPS", "conducta": "c", "plazo": 5}], {"ordenes.0.plazo"}, 1),
    ([{"destinatario": "EPS", "conducta": "c", "verbo": "X"}], {"ordenes.0.verbo"}, 1),
    ([{"destinatario": "EPS", "conducta": "c", "literales": ["uno", "", None, 5]}], {"ordenes.0.literales.3"}, 1),
    ([None, 3, "x"], {"ordenes.0", "ordenes.1", "ordenes.2"}, 3),
    ([{"destinatario": "EPS", "conducta": "c", "via_representante": "si"}], {"ordenes.0.via_representante"}, 1),
]
DERECHOS = [
    _t(None),
    _t([]),
    _t([{"derecho": "salud"}]),
    _t([{"derecho": "", "disposicion": "NIEGA"}], "derechos.0.derecho"),
    _t([{"derecho": "x", "disposicion": "Z"}], "derechos.0.disposicion"),
    _t("salud", "derechos"),
    _t([1, None], "derechos.0", "derechos.1"),
]
LIBRES = [
    _t(None),
    _t([]),
    _t(["NOTIFICAR algo"]),
    _t(["", "x"], "numerales_libres.0"),
    _t([None, 5], "numerales_libres.0", "numerales_libres.1"),
    _t("x", "numerales_libres"),
    _t(["x"] * (decision_vista.MAX_LISTA + 1), "numerales_libres"),
]
ORDENES_NUMERALES = [
    _t(None),
    _t([]),
    _t(["sustitutiva", "resultado"]),
    _t(["orden:9", "foo"], "orden_numerales"),
    _t([1, None], "orden_numerales.0"),
    _t("x", "orden_numerales"),
]
COMPULSAS = [
    _t(None),
    _t(False),
    _t({}, "compulsa.respecto_de"),
    _t({"respecto_de": "Dr. X"}),
    _t({"organo": "Comisión", "respecto_de": "  "}, "compulsa.respecto_de"),
    _t("x", "compulsa"),
    _t([1], "compulsa"),
    _t(True, "compulsa"),
]
ESTANDAR = [_t(None), _t({"notificar": False}), _t({"notificar": "si"}, "numerales.notificar"), _t("x", "numerales"), _t({"remitir_corte": 0}, "numerales.remitir_corte")]
FECHAS = [_t(None), _t("2026-11-03"), _t("no es fecha", "fecha_fallo"), _t(""), _t(20261103, "fecha_fallo")]
ACCIONES = [_t(None), _t("decidir"), _t("rehacer_apertura"), _t("rehacer_consideraciones"), _t("inventada", "accion")]
INSTRUCCIONES = [_t(None), _t(""), _t("Corrija la cita.")]
EXTRAS = [{}, {"desconocida": 1}, {"__proto__": {"x": 1}, "otra": [1, [2]]}]


def _esperado(caso: dict) -> set[str]:
    campos: set[str] = set()
    for clave in ("resultado", "sustitutiva", "eje", "accion", "numerales", "compulsa", "fecha_fallo"):
        campos |= caso["hallazgos"][clave]
    for clave in ("ordenes", "derechos", "numerales_libres", "orden_numerales"):
        campos |= caso["hallazgos"][clave]
    d = caso["decision"]
    accion = d.get("accion")
    accion = accion if accion in ("decidir", "rehacer_apertura", "rehacer_consideraciones") else "decidir"
    if accion.startswith("rehacer"):
        if not (isinstance(d.get("instruccion"), str) and d["instruccion"].strip("\x00\x01")):
            campos.add("instruccion")
        return campos
    resultado = d.get("resultado") if d.get("resultado") in VALIDAS_RESULTADO else None
    sustitutiva = d.get("sustitutiva") if d.get("sustitutiva") in VALIDAS_SUSTITUTIVA else None
    if resultado is None:
        campos.add("resultado")
    if sustitutiva is None and resultado != "CONFIRMAR":
        campos.add("sustitutiva")
    eje = d.get("eje")
    if not (isinstance(eje, str) and eje.strip("\x00\x01 ") and len(eje) <= decision_vista.MAX_TEXTO):
        campos.add("eje")
    if sustitutiva == "AMPARAR" and caso["n_ordenes"] == 0:
        campos.add("ordenes")
    return campos


def _casos_aleatorios(n: int):
    rng = random.Random(SEMILLA)
    for _ in range(n):
        decision: dict = {}
        hallazgos: dict[str, set[str]] = {}
        for clave, tabla in (
            ("resultado", RESULTADOS),
            ("sustitutiva", SUSTITUTIVAS),
            ("eje", EJES),
            ("derechos", DERECHOS),
            ("numerales_libres", LIBRES),
            ("orden_numerales", ORDENES_NUMERALES),
            ("compulsa", COMPULSAS),
            ("numerales", ESTANDAR),
            ("fecha_fallo", FECHAS),
            ("accion", ACCIONES),
            ("instruccion", INSTRUCCIONES),
        ):
            valor, campos = rng.choice(tabla)
            if valor is not None:
                decision[clave] = valor
            hallazgos[clave] = campos
        ordenes, campos, n_ordenes = rng.choice(ORDENES)
        if ordenes is not None:
            decision["ordenes"] = ordenes
        hallazgos["ordenes"] = campos
        decision.update(rng.choice(EXTRAS))
        yield {"decision": decision, "hallazgos": hallazgos, "n_ordenes": n_ordenes}


def _sanear(decision: dict) -> Decision:
    return Decision.model_validate(decision_vista._limpiar(decision, []))


def test_fuzz_con_semilla_fija_nunca_falla_y_reporta_lo_que_falta(rapido):
    md = _md_del_estado(rapido / "caso-api")
    vistos = set()
    for caso in _casos_aleatorios(3000):
        d = caso["decision"]
        salida = decision_vista.decision_vista(d, md)
        assert decision_vista.ERROR_INTERNO not in salida["errores"]
        assert set(salida) == {"numerales", "faltantes", "errores"}
        assert salida["numerales"], d
        for n in salida["numerales"]:
            assert isinstance(n["clave"], str) and isinstance(n["texto"], str)
            assert all(isinstance(x, str) for x in n["negritas"])
        campos = {f["campo"] for f in salida["faltantes"]}
        assert campos == _esperado(caso), d
        assert all(f["campo"] and f["mensaje"] for f in salida["faltantes"])
        assert salida["errores"] == list(dict.fromkeys(f["mensaje"] for f in salida["faltantes"]))
        for mensaje in _sanear(d).errores():
            cubiertos = decision_vista._campos_del_error(mensaje, _sanear(d))
            assert mensaje in salida["errores"] or set(cubiertos) <= campos, (mensaje, d)
        json.dumps(salida, ensure_ascii=False).encode("utf-8")
        vistos |= campos
    assert {"resultado", "sustitutiva", "eje", "ordenes", "instruccion", "fecha_fallo", "orden_numerales"} <= vistos


def test_fuzz_combinatorio_de_los_campos_centrales(rapido):
    md = _md_del_estado(rapido / "caso-api")
    ordenes = [None, [], [{"destinatario": "la EPS", "conducta": "autorice"}]]
    total = 0
    for resultado, sustitutiva, orden, eje, compulsa in itertools.product(
        (None, *VALIDAS_RESULTADO), (None, *VALIDAS_SUSTITUTIVA), ordenes, (None, "Porque sí."), (None, {"respecto_de": "X"})
    ):
        d = {"accion": "decidir"}
        for clave, valor in (("resultado", resultado), ("sustitutiva", sustitutiva), ("ordenes", orden), ("eje", eje), ("compulsa", compulsa)):
            if valor is not None:
                d[clave] = valor
        salida = decision_vista.decision_vista(d, md)
        esperado = set()
        if resultado is None:
            esperado.add("resultado")
        if sustitutiva is None and resultado != "CONFIRMAR":
            esperado.add("sustitutiva")
        if eje is None:
            esperado.add("eje")
        if sustitutiva == "AMPARAR" and not orden:
            esperado.add("ordenes")
        assert {f["campo"] for f in salida["faltantes"]} == esperado, d
        assert bool(salida["errores"]) == bool(esperado)
        if not esperado:
            assert _plano(formulas.numerales(Decision.model_validate(d), md)) == salida["numerales"]
        total += 1
    assert total == 4 * 7 * 3 * 2 * 2


def test_fuzz_http_nunca_responde_500(cliente):
    rng = random.Random(SEMILLA)
    for caso in itertools.islice(_casos_aleatorios(300), 300):
        extra = {"ordenes": rng.choice([[], None, [{}], "x"])} if rng.random() < 0.2 else {}
        r = cliente.post(URL.format("caso-api"), json={**caso["decision"], **extra})
        assert r.status_code == 200, caso["decision"]
        assert decision_vista.ERROR_INTERNO not in r.json()["errores"]


def _paragrafos_resuelve(carpeta: Path) -> list[str]:
    fallos = [
        p for p in salidas.listar(carpeta) if p.endswith(".docx") and "Fallo" in Path(p).name and "02SegundaInstancia" in p
    ]
    assert len(fallos) == 1, fallos
    parrafos = [p.text for p in Document(salidas.raiz(carpeta) / fallos[0]).paragraphs]
    return parrafos


def test_numerales_son_los_del_resuelve_del_fallo_docx(sintetico, monkeypatch):
    raiz, decision = sintetico
    carpeta = raiz / "sintetico"
    cliente = _cliente(monkeypatch, raiz)
    cuerpo = cliente.post(URL.format("sintetico"), json=decision).json()
    assert cuerpo["faltantes"] == [] and cuerpo["errores"] == []
    esperados = [f"{formulas.ordinal(i)}: {n['texto']}" for i, n in enumerate(cuerpo["numerales"], 1)]
    parrafos = _paragrafos_resuelve(carpeta)
    posiciones = [parrafos.index(e) for e in esperados]
    assert posiciones == sorted(posiciones)
    assert len(esperados) >= 3


def test_latencia_p95_con_el_caso_sintetico(sintetico, monkeypatch):
    raiz, decision = sintetico
    cliente = _cliente(monkeypatch, raiz)
    assert cliente.post(URL.format("sintetico"), json=decision).status_code == 200
    tiempos = []
    for i in range(60):
        cuerpo = {**decision, "eje": f"{decision.get('eje', '')} {i}"}
        t = time.perf_counter()
        r = cliente.post(URL.format("sintetico"), json=cuerpo)
        tiempos.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    tiempos.sort()
    assert tiempos[int(len(tiempos) * 0.95) - 1] < 80, tiempos[-5:]
    assert not (raiz / "sintetico" / "hilo.sqlite-journal").exists()


def test_la_cache_evita_reabrir_el_hilo_en_llamadas_repetidas(sintetico, monkeypatch):
    raiz, decision = sintetico
    cliente = _cliente(monkeypatch, raiz)
    real = decision_vista._desde_hilo
    llamadas = []
    monkeypatch.setattr(decision_vista, "_desde_hilo", lambda d: llamadas.append(1) or real(d))
    for _ in range(5):
        cliente.post(URL.format("sintetico"), json=decision)
    assert len(llamadas) == 1
