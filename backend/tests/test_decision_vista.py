from __future__ import annotations

import importlib.util
import itertools
import json
import os
import random
import shutil
import sqlite3
import time
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from test_graph import DECISION, Verificador, ingesta_sintetica

from tutela2 import api, decision_vista, formulas, ingest, salidas, server
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.models import Decision, DisposicionReparo, Metadatos, Orden, colapsar_texto, normalizar_decision

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
HOY = date(2026, 11, 4)
CLAVES_VISTA = {"numerales", "faltantes", "errores", "advertencias", "encabezado", "fecha_fallo", "fecha_por_defecto"}
BASE = {
    "accion": "decidir",
    "resultado": "REVOCAR",
    "sustitutiva": "AMPARAR",
    "eje": "x",
    "ordenes": [{"destinatario": "la EPS", "conducta": "autorice"}],
    "decidido_por": "Oficial Mayor",
}
VISTA_ERROR = {
    "numerales": [],
    "faltantes": [],
    "errores": [decision_vista.ERROR_INTERNO],
    "advertencias": [],
    "encabezado": "",
    "fecha_fallo": "",
    "fecha_por_defecto": False,
}


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
    assert r.json() == VISTA_ERROR


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
    assert set(componentes["DecisionVistaRespuesta"]["properties"]) == CLAVES_VISTA
    assert set(componentes["DecisionVistaRespuesta"]["required"]) == CLAVES_VISTA
    assert set(componentes["NumeralVista"]["properties"]) == {"clave", "texto", "negritas"}
    assert set(componentes["FaltanteDecision"]["properties"]) == {"campo", "mensaje"}


NUMERALES_MINIMOS = {"notificar", "remitir"}


def test_decision_vacia_reporta_lo_que_falta_y_aun_arma_numerales(rapido):
    md = _md_del_estado(rapido / "caso-api")
    salida = decision_vista.decision_vista({}, md)
    assert {f["campo"] for f in salida["faltantes"]} == {"resultado", "sustitutiva", "eje"}
    assert NUMERALES_MINIMOS <= {n["clave"] for n in salida["numerales"]}
    assert salida["errores"] == list(dict.fromkeys(f["mensaje"] for f in salida["faltantes"]))
    assert decision_vista.decision_vista([], md) == {**VISTA_ERROR, "errores": ["La decisión debe ser un objeto."]}


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


def _vista(**cambios) -> dict:
    return decision_vista.decision_vista({**BASE, **cambios}, Metadatos(), HOY)


def _texto_de(salida: dict, clave: str) -> str:
    return next(n["texto"] for n in salida["numerales"] if n["clave"] == clave)


def test_la_vista_expone_encabezado_y_si_la_fecha_es_por_defecto():
    salida = _vista()
    assert salida["encabezado"] == "REVOCA"
    assert salida["fecha_fallo"] == "2026-11-04" and salida["fecha_por_defecto"] is True
    for sin_fecha in ({"fecha_fallo": None}, {"fecha_fallo": ""}, {"fecha_fallo": "   "}):
        assert _vista(**sin_fecha)["fecha_por_defecto"] is True
    propia = _vista(fecha_fallo="2026-10-20")
    assert propia["fecha_fallo"] == "2026-10-20" and propia["fecha_por_defecto"] is False
    assert _vista(resultado="REVOCAR", sustitutiva="NEGAR", ordenes=[])["encabezado"] == "REVOCA Y NIEGA"
    assert _vista(etiqueta_encabezado="CONFIRMA CON MODIFICACIONES")["encabezado"] == "CONFIRMA CON MODIFICACIONES"
    assert _vista(resultado=None)["encabezado"] == "⟦FALTA: decisión⟧"


def test_la_fecha_por_defecto_sigue_a_date_today(monkeypatch):
    class Falsa(date):
        @classmethod
        def today(cls):
            return cls(2031, 1, 2)

    monkeypatch.setattr(decision_vista, "date", Falsa)
    salida = decision_vista.decision_vista(BASE, Metadatos())
    assert salida["fecha_fallo"] == "2031-01-02" and salida["fecha_por_defecto"] is True


def test_la_causal_alimenta_el_segundo_y_la_etiqueta():
    base = {"resultado": "REVOCAR", "sustitutiva": "IMPROCEDENTE", "ordenes": []}
    con = _vista(**base, causal="COSA_JUZGADA")
    assert con["faltantes"] == [] and con["errores"] == []
    assert con["encabezado"] == "REVOCA Y DECLARA IMPROCEDENTE POR COSA JUZGADA"
    assert "cosa juzgada constitucional" in _texto_de(con, "sustitutiva")
    sin = _vista(**base)
    assert sin["encabezado"] == "REVOCA Y DECLARA IMPROCEDENTE"
    assert _texto_de(sin, "sustitutiva").endswith("por las razones expuestas en este proveído.")
    assert _vista(**base, causal="")["encabezado"] == sin["encabezado"]


def test_causal_invalida_se_reporta_y_no_cambia_el_texto():
    salida = _vista(resultado="REVOCAR", sustitutiva="IMPROCEDENTE", ordenes=[], causal="INVENTADA")
    assert [f["campo"] for f in salida["faltantes"]] == ["causal"]
    assert "COSA_JUZGADA" in salida["faltantes"][0]["mensaje"] and "SUBSIDIARIEDAD" in salida["faltantes"][0]["mensaje"]
    assert salida["encabezado"] == "REVOCA Y DECLARA IMPROCEDENTE"


def test_causal_sin_improcedente_se_ignora_sin_error():
    salida = _vista(resultado="REVOCAR", sustitutiva="NEGAR", ordenes=[], causal="COSA_JUZGADA")
    assert salida["faltantes"] == [] and salida["errores"] == []
    assert salida["encabezado"] == "REVOCA Y NIEGA"
    assert "cosa juzgada" not in _texto_de(salida, "sustitutiva")


@pytest.mark.parametrize(
    "sustitutiva,causal", [("NEGAR", None), ("IMPROCEDENTE", None), ("IMPROCEDENTE", "COSA_JUZGADA"), ("CARENCIA_HECHO_SUPERADO", None)]
)
def test_advertir_y_prevenir_sin_amparar_no_se_rechazan(sustitutiva, causal):
    ordenes = [
        {"verbo": "ADVERTIR", "destinatario": "la señora Ana", "conducta": "deberá acudir ante el juzgado de conocimiento"},
        {"verbo": "PREVENIR", "destinatario": "el Banco X", "conducta": "responda oportunamente"},
    ]
    extra = {"causal": causal} if causal else {}
    salida = _vista(resultado="REVOCAR", sustitutiva=sustitutiva, ordenes=ordenes, **extra)
    assert salida["faltantes"] == [] and salida["errores"] == []
    assert [n["clave"] for n in salida["numerales"]] == ["resultado", "sustitutiva", "orden:0", "orden:1", "notificar", "remitir"]
    assert _texto_de(salida, "orden:0") == "ADVERTIR a la señora Ana que deberá acudir ante el juzgado de conocimiento."
    assert _texto_de(salida, "orden:1") == "PREVENIR al Banco X para que responda oportunamente."


MSG_VACIO = "Decidido por está vacío: en la declaración de uso de IA constará «no consta»."
MSG_PLACEHOLDER = "Decidido por parece un valor de prueba: confirme que sea el nombre de quien decide."


@pytest.mark.parametrize(
    "nombre,mensaje",
    [
        ("", MSG_VACIO),
        ("   ", MSG_VACIO),
        (None, MSG_VACIO),
        ("John Doe", MSG_PLACEHOLDER),
        ("JOHN DOE", MSG_PLACEHOLDER),
        ("  john   doe ", MSG_PLACEHOLDER),
        ("prueba", MSG_PLACEHOLDER),
        ("Prueba", MSG_PLACEHOLDER),
        ("caso_sintetico", MSG_PLACEHOLDER),
        ("CASO-SINTETICO", MSG_PLACEHOLDER),
        ("caso sintético", MSG_PLACEHOLDER),
    ],
)
def test_decidido_por_vacio_o_de_prueba_advierte_sin_bloquear(nombre, mensaje):
    salida = _vista(decidido_por=nombre)
    assert salida["advertencias"] == [{"campo": "decidido_por", "mensaje": mensaje}]
    assert salida["faltantes"] == [] and salida["errores"] == []
    assert Decision.model_validate(decision_vista._limpiar({**BASE, "decidido_por": nombre}, [])).errores() == []


@pytest.mark.parametrize("nombre", ["Oficial Mayor", "SANTIAGO ALEJANDRO CADAVID DUQUE", "Juan Prueba Pérez", "John Doe Jr."])
def test_decidido_por_real_no_advierte(nombre):
    assert _vista(decidido_por=nombre)["advertencias"] == []


def test_advertencias_solo_al_decidir_y_el_valor_existe_en_el_modelo():
    assert _vista(accion="rehacer_apertura", instruccion="x", decidido_por="")["advertencias"] == []
    assert Decision(accion="decidir", decidido_por="prueba").advertencias() == [MSG_PLACEHOLDER]
    assert Decision(accion="decidir").advertencias() == [MSG_VACIO]
    assert Decision(accion="rehacer_apertura", instruccion="x").advertencias() == []


def test_mensajes_de_advertencia_llevan_prefijo_que_los_asigna_a_su_campo():
    d = Decision(accion="decidir")
    for mensaje in (MSG_VACIO, MSG_PLACEHOLDER):
        assert decision_vista._campos_del_error(mensaje, d) == ["decidido_por"]


def test_colapsar_texto():
    assert colapsar_texto("▎ Línea uno\n▎ Línea dos") == "Línea uno Línea dos"
    assert colapsar_texto("  a   b \t\n c ") == "a b c"
    assert colapsar_texto("a\u00a0b\u2028c") == "a b c"
    assert colapsar_texto("a\x0bb") == "ab"
    assert colapsar_texto("▎") == "" and colapsar_texto("▎\n  ▎ ") == ""
    assert colapsar_texto(colapsar_texto("▎ x\n y")) == "x y"
    assert colapsar_texto(5) == 5 and colapsar_texto(None) is None


CRUDA = {
    "accion": "decidir",
    "eje": "▎ La entidad no\n▎ acreditó la autorización.",
    "instruccion": "  corrija\n la cita ",
    "por_reparo": [{"reparo_id": "R1", "disposicion": "ACOGE", "nota": "▎ nota\n\n dos"}, None, 3],
    "numerales_libres": ["▎ CONFIRMAR   en lo demás.\n", 5],
    "ordenes": [{"destinatario": "la  EPS\n", "conducta": "▎ entregue\n▎ el medicamento", "literales": ["a\n b"]}, "x"],
    "decidido_por": "  Oficial\n Mayor ",
}


def test_normalizar_decision_cruda_toca_solo_los_campos_de_texto_libre():
    original = deepcopy(CRUDA)
    salida = normalizar_decision(CRUDA)
    assert CRUDA == original
    assert salida["eje"] == "La entidad no acreditó la autorización."
    assert salida["instruccion"] == "corrija la cita"
    assert salida["por_reparo"][0] == {"reparo_id": "R1", "disposicion": "ACOGE", "nota": "nota dos"}
    assert salida["por_reparo"][1:] == [None, 3]
    assert salida["numerales_libres"] == ["CONFIRMAR en lo demás.", 5]
    assert salida["ordenes"][0] == {"destinatario": "la  EPS\n", "conducta": "entregue el medicamento", "literales": ["a\n b"]}
    assert salida["ordenes"][1] == "x"
    assert salida["decidido_por"] == CRUDA["decidido_por"]
    assert normalizar_decision(salida) == salida


@pytest.mark.parametrize(
    "basura",
    [
        [1, 2],
        "x",
        None,
        {"eje": 5, "instruccion": None, "por_reparo": "x", "numerales_libres": None, "ordenes": {"a": 1}},
        {"por_reparo": [{"nota": 5}], "ordenes": [{"conducta": None}, {}]},
    ],
)
def test_normalizar_decision_cruda_tolera_cualquier_forma(basura):
    assert normalizar_decision(basura) == basura


def test_decision_normaliza_al_validar_desde_dict_y_desde_instancias():
    limpia = {**CRUDA, "por_reparo": CRUDA["por_reparo"][:1], "numerales_libres": CRUDA["numerales_libres"][:1]}
    d = Decision.model_validate({**limpia, "ordenes": CRUDA["ordenes"][:1]})
    assert d.eje == "La entidad no acreditó la autorización." and d.instruccion == "corrija la cita"
    assert d.por_reparo[0].nota == "nota dos" and d.numerales_libres == ["CONFIRMAR en lo demás."]
    assert d.ordenes[0].conducta == "entregue el medicamento"
    pasada = Orden(destinatario="x", conducta="▎ a\n▎ b")
    nota = DisposicionReparo(reparo_id="R1", nota="n\n▎ m")
    d = Decision(accion="decidir", eje="▎ u\nv", numerales_libres=["▎ w\n z"], ordenes=[pasada], por_reparo=[nota])
    assert (d.eje, d.numerales_libres, d.ordenes[0].conducta, d.por_reparo[0].nota) == ("u v", ["w z"], "a b", "n m")
    assert pasada.conducta == "▎ a\n▎ b" and nota.nota == "n\n▎ m"
    assert d.model_fields_set == {"accion", "eje", "numerales_libres", "ordenes", "por_reparo"}


def test_la_vista_colapsa_los_textos_y_marca_lo_que_queda_vacio():
    salida = _vista(
        eje="▎ Porque\n▎ sí.",
        ordenes=[{"destinatario": "la EPS", "conducta": "▎ entregue\n▎ el medicamento"}],
        numerales_libres=["▎ NOTIFICAR   algo\n"],
        por_reparo=[{"reparo_id": "R1", "disposicion": "ACOGE", "nota": "▎ a\n b"}],
    )
    assert salida["faltantes"] == []
    assert _texto_de(salida, "orden:0").endswith("entregue el medicamento.")
    assert _texto_de(salida, "libre:0") == "NOTIFICAR algo"
    assert "▎" not in json.dumps(salida, ensure_ascii=False)
    vacia = _vista(eje="▎\n  ▎ ", ordenes=[{"destinatario": "la EPS", "conducta": "▎"}])
    assert {f["campo"] for f in vacia["faltantes"]} == {"eje", "ordenes.0.conducta"}


def test_el_limite_de_largo_se_mide_despues_de_colapsar():
    largo = "palabra " * (decision_vista.MAX_TEXTO // 8 - 1)
    espaciado = "▎ " + largo.replace(" ", "   ")
    assert len(espaciado) > decision_vista.MAX_TEXTO
    assert _vista(eje=espaciado)["faltantes"] == []


def _t(valor, *campos):
    return valor, set(campos)


RESULTADOS = [_t(None), _t("CONFIRMAR"), _t("REVOCAR"), _t("MODIFICAR"), _t("revocar", "resultado"), _t(7, "resultado"), _t([], "resultado"), _t("")]
SUSTITUTIVAS = [_t(None), _t(""), *[_t(s) for s in VALIDAS_SUSTITUTIVA], _t("INVENTADA", "sustitutiva"), _t({}, "sustitutiva")]
EJES = [
    _t(None),
    _t(""),
    _t("   "),
    _t("Porque sí."),
    _t(5, "eje"),
    _t("x" * (decision_vista.MAX_TEXTO + 1), "eje"),
    _t("\x00\x01"),
    _t("▎ Porque sí.\n▎ Y además."),
    _t("▎\n  ▎ "),
]
CAUSALES = [_t(None), _t(""), _t("COSA_JUZGADA"), _t("SUBSIDIARIEDAD"), _t("INVENTADA", "causal"), _t(5, "causal"), _t([], "causal")]
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
    for clave in ("resultado", "sustitutiva", "eje", "accion", "numerales", "compulsa", "fecha_fallo", "causal"):
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
    if not (isinstance(eje, str) and colapsar_texto(eje) and len(eje) <= decision_vista.MAX_TEXTO):
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
            ("causal", CAUSALES),
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
        assert set(salida) == CLAVES_VISTA
        assert salida["numerales"], d
        assert {a["campo"] for a in salida["advertencias"]} <= {"decidido_por"}
        assert not {a["mensaje"] for a in salida["advertencias"]} & set(salida["errores"])
        assert isinstance(salida["encabezado"], str) and salida["encabezado"]
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
