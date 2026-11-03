from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest
from test_graph import DECISION, Verificador, ingesta_sintetica

from tutela2 import api, expediente, ingest, salidas
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig
from tutela2.models import Doc, Pagina

PRINCIPAL = "02SegundaInstancia/C01Principal"
ACTA = b"%PDF-1.4 acta de ejemplo"
COMPULSA = {"organo": "Comisión Seccional de Disciplina Judicial de Antioquia", "respecto_de": "la funcionaria encargada"}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


def _caso(tmp_path, monkeypatch, con_acta: bool):
    carpeta = tmp_path / "caso-x"
    (carpeta / "insumos" / "2a").mkdir(parents=True)
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    ing = ingesta_sintetica()
    if con_acta:
        (carpeta / "insumos" / "2a" / "001ActaRepartoSegunda.pdf").write_bytes(ACTA)
    else:
        ing.documentos = [d for d in ing.documentos if d.rol != "acta_reparto_2a"]
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ing, raising=False)
    return carpeta


def test_numerados():
    assert expediente.numerados(["ActaRepartoSegunda.pdf", "AutoAsumeSegunda202600530.docx"]) == [
        "001ActaRepartoSegunda.pdf",
        "002AutoAsumeSegunda202600530.docx",
    ]


def test_previos_sin_acta_empiezan_en_001(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=False)
    r = api.nuevo(carpeta)
    assert r["estado"] == "revision"
    assert r["salidas"] == [f"{PRINCIPAL}/001AutoAsumeSegunda202600001.docx"]


def test_arbol_completo_con_formato_y_compulsa(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    assert api.nuevo(carpeta)["salidas"] == [
        f"{PRINCIPAL}/001ActaRepartoSegunda.pdf",
        f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx",
    ]
    assert (carpeta / "salidas" / PRINCIPAL / "001ActaRepartoSegunda.pdf").read_bytes() == ACTA
    assert api.iniciar(carpeta)["estado"] == "esperando_decision"
    decision = {**DECISION, "generar_formato": True, "compulsa": COMPULSA, "fecha_fallo": "2026-10-20", "fecha_oficio": "2026-10-21"}
    r = api.decidir(carpeta, decision)
    assert r["estado"] == "terminado", r["error"]
    assert r["salidas"] == sorted(
        [
            f"{PRINCIPAL}/001ActaRepartoSegunda.pdf",
            f"{PRINCIPAL}/002AutoAsumeSegunda202600001.docx",
            f"{PRINCIPAL}/003FalloSegunda202600001.docx",
            f"{PRINCIPAL}/004FormatoCalificacion202600001.docx",
            "por_radicar/OficioRemiteCorteConstitucional.docx",
            "borradores_correo/NotificacionFalloPartes.docx",
            "borradores_correo/EnvioFormatoCalidad.docx",
            "borradores_correo/RemisionCompulsaCopias.docx",
            "trabajo/previo.docx",
            "trabajo/informe_verificacion.docx",
            "trabajo/declaracion_ia.docx",
        ]
    )
    hashes = r["resumen"]["salidas"]
    assert hashes
    for rel, sha in hashes.items():
        assert hashlib.sha256((carpeta / "salidas" / rel).read_bytes()).hexdigest() == sha


def test_sin_formato_no_hay_004_ni_envio(tmp_path, monkeypatch):
    carpeta = _caso(tmp_path, monkeypatch, con_acta=True)
    api.nuevo(carpeta)
    api.iniciar(carpeta)
    r = api.decidir(carpeta, DECISION)
    assert r["estado"] == "terminado", r["error"]
    assert not any(s.startswith(f"{PRINCIPAL}/004") for s in r["salidas"])
    assert "borradores_correo/EnvioFormatoCalidad.docx" not in r["salidas"]
    assert "borradores_correo/RemisionCompulsaCopias.docx" not in r["salidas"]


def test_resolver_rechaza_rutas_fuera(tmp_path):
    (tmp_path / "salidas" / "trabajo").mkdir(parents=True)
    (tmp_path / "salidas" / "trabajo" / "a.docx").write_bytes(b"x")
    assert salidas.resolver(tmp_path, "trabajo/a.docx").read_bytes() == b"x"
    for malo in ("../x", "/etc/passwd", "trabajo/../../x", "..\\x", ""):
        with pytest.raises(ValueError):
            salidas.resolver(tmp_path, malo)
    with pytest.raises(FileNotFoundError):
        salidas.resolver(tmp_path, "trabajo/no.docx")


def test_resolver_rechaza_enlace_que_escapa(tmp_path):
    (tmp_path / "salidas").mkdir()
    (tmp_path / "secreto.txt").write_text("s")
    (tmp_path / "salidas" / "enlace.txt").symlink_to(tmp_path / "secreto.txt")
    with pytest.raises(ValueError):
        salidas.resolver(tmp_path, "enlace.txt")


def test_zip_y_listar(tmp_path):
    (tmp_path / "salidas" / "a" / "b").mkdir(parents=True)
    (tmp_path / "salidas" / "a" / "b" / "c.txt").write_text("c")
    (tmp_path / "salidas" / "d.txt").write_text("d")
    assert salidas.listar(tmp_path) == ["a/b/c.txt", "d.txt"]
    assert salidas.listar(tmp_path / "nada") == []
    with zipfile.ZipFile(BytesIO(salidas.zip_bytes(tmp_path))) as z:
        assert sorted(z.namelist()) == ["a/b/c.txt", "d.txt"]


def test_buzon_del_juzgado_desde_la_ultima_notificacion():
    ing = ingesta_sintetica()
    texto = "Asunto: notificación\nDe: Juzgado Origen <juzgado.origen@cendoj.ramajudicial.gov.co>\nPara: otra@ejemplo.com\n"
    ing.documentos.append(
        Doc(doc_id="1a-090", ruta="n.txt", nombre="n.txt", instancia="1a", rol="notificacion", sha256="0", paginas=[Pagina(n=1, texto=texto)])
    )
    assert expediente._buzon_juzgado(ing) == "juzgado.origen@cendoj.ramajudicial.gov.co"
    assert expediente._buzon_juzgado(ingesta_sintetica()) is None
