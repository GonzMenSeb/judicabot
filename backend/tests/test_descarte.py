from __future__ import annotations

import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_graph import DECISION, FALLO_DOCX, Verificador, ingesta_sintetica

from tutela2 import api, descarte, ingest, papelera, server
from tutela2 import citas as citas_real
from tutela2.config import Config, LLMConfig

BORRADOR, DECIDIDO, FALLO = "el borrador", "la decisión del juez", "el fallo con sus documentos"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(citas_real, "cargar_dataset", lambda cfg: {})
    monkeypatch.setattr(citas_real, "verificar_citas", Verificador())


@pytest.fixture
def caso(tmp_path, monkeypatch):
    carpeta = tmp_path / "caso-api"
    (carpeta / "insumos").mkdir(parents=True)
    (carpeta / "insumos" / "escrito.pdf").write_bytes(b"%PDF-escrito")
    cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False)
    (carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(ingest, "ingerir", lambda d, c: ingesta_sintetica(), raising=False)
    return carpeta


def _hilo_con_fila(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(ruta) as con:
        con.execute("CREATE TABLE checkpoints (thread_id TEXT)")
        con.execute("INSERT INTO checkpoints VALUES ('x')")
    con.close()


def _entradas(raiz: Path) -> list[str]:
    carpeta = papelera.carpeta(raiz)
    return sorted(p.name for p in carpeta.iterdir()) if carpeta.is_dir() else []


def _terminado(caso: Path) -> None:
    assert api.nuevo(caso)["ok"]
    assert api.iniciar(caso)["estado"] == "esperando_decision"
    assert api.decidir(caso, DECISION)["estado"] == "terminado"


def test_caso_recien_procesado_no_tiene_trabajo_previo(caso):
    assert api.nuevo(caso)["estado"] == "revision"
    assert descarte.trabajo_previo(caso) == []
    assert descarte.trabajo_huerfano(caso) == []


def test_trabajo_previo_por_etapas(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    assert descarte.trabajo_previo(caso) == [BORRADOR]
    api.decidir(caso, DECISION)
    assert descarte.trabajo_previo(caso) == [BORRADOR, DECIDIDO, FALLO]


def test_hilo_vacio_o_sin_tablas_no_cuenta(caso):
    (caso / "hilo.sqlite").write_bytes(b"")
    assert descarte.hilo_con_datos(caso) is False
    (caso / "hilo.sqlite").unlink()
    with sqlite3.connect(caso / "hilo.sqlite") as con:
        con.execute("CREATE TABLE x(a)")
    con.close()
    assert descarte.hilo_con_datos(caso) is False
    assert descarte.trabajo_previo(caso) == []


def test_hilo_ilegible_cuenta_como_trabajo(caso):
    (caso / "hilo.sqlite").write_bytes(b"basura" * 100)
    assert descarte.hilo_con_datos(caso) is True
    assert descarte.trabajo_previo(caso) == ["el avance de la redacción"]


def test_hilo_con_datos_en_una_ruta_con_caracteres_especiales(tmp_path):
    carpeta = tmp_path / "ca#so?x%20"
    _hilo_con_fila(carpeta / "hilo.sqlite")
    assert descarte.hilo_con_datos(carpeta) is True


def test_trabajo_huerfano_ignora_un_hilo_sano(caso):
    api.nuevo(caso)
    api.iniciar(caso)
    assert descarte.trabajo_previo(caso) == [BORRADOR]
    assert descarte.trabajo_huerfano(caso) == []
    for sufijo in ("", "-wal", "-shm"):
        (caso / f"hilo.sqlite{sufijo}").unlink(missing_ok=True)
    assert descarte.trabajo_huerfano(caso) == [BORRADOR]


def test_mensaje_enumera():
    trabajo = [BORRADOR, DECIDIDO]
    assert descarte.enumerar(["a"]) == "a"
    assert descarte.enumerar(["a", "b"]) == "a y b"
    assert descarte.enumerar(["a", "b", "c"]) == "a, b y c"
    assert descarte.mensaje(trabajo, "nuevo") == (
        "Este caso ya tiene el borrador y la decisión del juez. Volver a procesar los documentos los descarta; "
        "antes se guarda una copia del caso en la papelera, donde se puede recuperar durante 30 días."
    )
    assert "cuyo historial se perdió. Iniciar la redacción los descarta; antes se guarda una copia" in descarte.mensaje(trabajo, "iniciar")
    assert "hay que volver a procesar los documentos, lo que los descarta" in descarte.mensaje(trabajo, "revisar")
    assert descarte.detalle(trabajo, "nuevo") == {
        "codigo": "trabajo_previo",
        "mensaje": descarte.mensaje(trabajo, "nuevo"),
        "trabajo": trabajo,
    }


# Copia en la papelera (decisión del dueño, P1 opción B): se guarda antes de descartar y se puede restaurar.


def test_respaldar_copia_el_caso_completo_a_la_papelera(caso):
    _terminado(caso)
    antes = sorted(str(p.relative_to(caso)) for p in caso.rglob("*"))
    entrada = descarte.respaldar(caso)
    datos = papelera.interpretar(entrada)
    assert datos is not None and datos[0] == caso.name
    copia = papelera.carpeta(caso.parent) / entrada
    assert sorted(str(p.relative_to(copia)) for p in copia.rglob("*")) == antes
    assert (copia / "decision.json").read_bytes() == (caso / "decision.json").read_bytes()
    assert (copia / "salidas" / FALLO_DOCX).read_bytes() == (caso / "salidas" / FALLO_DOCX).read_bytes()
    assert (copia / "insumos" / "escrito.pdf").read_bytes() == b"%PDF-escrito"
    assert sorted(str(p.relative_to(caso)) for p in caso.rglob("*")) == antes


def test_respaldar_no_deja_una_copia_a_medias_si_falla(caso, monkeypatch):
    _terminado(caso)

    def a_medias(origen, destino, **kw):
        (Path(destino) / "insumos").mkdir(parents=True)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copytree", a_medias)
    with pytest.raises(descarte.ErrorRespaldo, match="No se pudo guardar la copia"):
        descarte.respaldar(caso)
    assert _entradas(caso.parent) == []


def test_respaldar_no_deja_pasar_un_caso_que_no_existe(tmp_path):
    with pytest.raises(descarte.ErrorRespaldo):
        descarte.respaldar(tmp_path / "no-existe")
    assert _entradas(tmp_path) == []


def test_nuevo_con_descartar_guarda_la_copia_antes_de_borrar(caso):
    _terminado(caso)
    r = api.nuevo(caso, descartar=True)
    assert r["ok"] and r["estado"] == "revision"
    (entrada,) = _entradas(caso.parent)
    assert r["papelera"] == entrada
    copia = papelera.carpeta(caso.parent) / entrada
    assert (copia / "hilo.sqlite").is_file() and (copia / "decision.json").is_file()
    assert (copia / "salidas" / FALLO_DOCX).is_file()
    assert not (caso / "decision.json").exists() and not (caso / "hilo.sqlite").exists()
    assert not (caso / "salidas" / FALLO_DOCX).exists()


def test_nuevo_sin_trabajo_previo_no_guarda_copia(caso):
    api.nuevo(caso)
    r = api.nuevo(caso, descartar=True)
    assert r["ok"] and "papelera" not in r
    assert _entradas(caso.parent) == []


def test_nuevo_sin_descartar_no_guarda_copia_ni_borra_nada(caso):
    _terminado(caso)
    r = api.nuevo(caso)
    assert r["ok"] is False and "papelera" not in r
    assert _entradas(caso.parent) == []
    assert (caso / "decision.json").exists() and (caso / "salidas" / FALLO_DOCX).exists()


def test_si_la_copia_falla_no_se_descarta_nada(caso, monkeypatch):
    _terminado(caso)

    def sin_espacio(origen, destino, **kw):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as parche:
        parche.setattr(shutil, "copytree", sin_espacio)
        r = api.nuevo(caso, descartar=True)
    assert r["ok"] is False and "No se pudo guardar la copia" in r["error"] and "no se descartó nada" in r["error"]
    assert (caso / "hilo.sqlite").exists() and (caso / "decision.json").exists()
    assert (caso / "salidas" / FALLO_DOCX).exists()
    assert _entradas(caso.parent) == []
    assert api.estado(caso)["estado"] == "terminado"


def test_iniciar_sin_historial_con_descartar_guarda_la_copia(caso):
    _terminado(caso)
    for sufijo in ("", "-wal", "-shm"):
        (caso / f"hilo.sqlite{sufijo}").unlink(missing_ok=True)
    r = api.iniciar(caso, descartar=True)
    assert r["ok"] and r["estado"] == "esperando_decision", r["error"]
    (entrada,) = _entradas(caso.parent)
    assert r["papelera"] == entrada
    copia = papelera.carpeta(caso.parent) / entrada
    assert (copia / "decision.json").is_file() and (copia / "salidas" / FALLO_DOCX).is_file()
    assert not (caso / "decision.json").exists() and not (caso / "salidas" / "por_radicar").exists()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path))
    monkeypatch.delenv("JUDICABOT_PASSWORD", raising=False)
    server.JOBS.clear()
    return TestClient(server.app, base_url="http://127.0.0.1")


def test_la_copia_se_restaura_como_un_caso_eliminado(caso, cliente):
    _terminado(caso)
    decision = (caso / "decision.json").read_bytes()
    fallo = (caso / "salidas" / FALLO_DOCX).read_bytes()
    entrada = api.nuevo(caso, descartar=True)["papelera"]
    assert api.estado(caso)["estado"] == "revision"

    # Mientras exista el caso con ese id no se puede restaurar encima: es la regla de siempre de la papelera.
    r = cliente.post(f"/api/papelera/{entrada}/restaurar")
    assert r.status_code == 409 and (caso / "insumos").is_dir()

    # Se elimina el caso actual (también va a la papelera) y se restaura la copia.
    assert cliente.delete(f"/api/casos/{caso.name}").status_code == 200
    assert not caso.exists()
    r = cliente.post(f"/api/papelera/{entrada}/restaurar")
    assert r.status_code == 200 and r.json() == {"id": caso.name}
    assert (caso / "decision.json").read_bytes() == decision
    assert (caso / "salidas" / FALLO_DOCX).read_bytes() == fallo
    restaurado = api.estado(caso)
    assert restaurado["ok"] and restaurado["estado"] == "terminado" and FALLO_DOCX in restaurado["salidas"]
    assert "historial_perdido" not in restaurado


def test_la_copia_se_purga_a_los_30_dias_como_cualquier_entrada(caso):
    _terminado(caso)
    entrada = api.nuevo(caso, descartar=True)["papelera"]
    sello = papelera.interpretar(entrada)[1]
    assert papelera.purgar(caso.parent, sello) == []
    assert papelera.purgar(caso.parent, sello + timedelta(days=papelera.DIAS_PAPELERA + 1)) == [entrada]
    assert _entradas(caso.parent) == []
