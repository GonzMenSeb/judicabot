from __future__ import annotations

import shutil
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_server import _entorno_intacto, _subir, api, caso, cliente  # noqa: F401

from tutela2 import config as cfgmod
from tutela2 import formato_global, papelera, resumen_caso, rutas_casos, server, termino
from tutela2.esquemas import Termino

AHORA = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)


def _raiz(tmp_path: Path) -> Path:
    return tmp_path / "casos"


def _ids(cliente) -> list[str]:
    return [c["id"] for c in cliente.get("/api/casos").json()]


def test_eliminar_mueve_la_carpeta_a_la_papelera(cliente, caso, tmp_path):
    raiz = _raiz(tmp_path)
    r = cliente.delete(f"/api/casos/{caso}")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id"] == caso and set(cuerpo) == {"id", "papelera"}
    assert papelera.interpretar(cuerpo["papelera"])[0] == caso
    entrada = raiz / ".papelera" / cuerpo["papelera"]
    assert (entrada / "insumos" / "01PrimeraInstancia" / "a.pdf").read_bytes() == b"%PDF-a"
    assert not (raiz / caso).exists()
    assert caso not in _ids(cliente)
    assert cliente.get(f"/api/casos/{caso}/resumen").status_code == 404


def test_eliminar_retira_al_caso_de_la_cola_de_vigencia(cliente, caso, tmp_path, monkeypatch):
    from tutela2 import vigencia

    retirados = []
    monkeypatch.setattr(vigencia.COLA, "retirar", lambda caso_dir, cedulas=None: retirados.append((Path(caso_dir), cedulas)) or 0)
    assert cliente.delete(f"/api/casos/{caso}").status_code == 200
    assert retirados == [((_raiz(tmp_path) / caso).resolve(), None)]


@pytest.mark.parametrize("malo", ["nada", ".papelera", "%2e%2e", ".preferencias.json"])
def test_eliminar_con_id_invalido_es_404(cliente, caso, tmp_path, malo):
    cliente.delete(f"/api/casos/{caso}")
    r = cliente.delete(f"/api/casos/{malo}")
    assert r.status_code == 404 and r.json()["detail"] == "Caso no encontrado."
    assert (_raiz(tmp_path) / ".papelera").is_dir()


def test_eliminar_dos_veces_es_404(cliente, caso):
    assert cliente.delete(f"/api/casos/{caso}").status_code == 200
    assert cliente.delete(f"/api/casos/{caso}").status_code == 404


def test_eliminar_con_un_job_corriendo_es_409(cliente, caso, api, tmp_path):
    api.soltar.clear()
    cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    try:
        r = cliente.delete(f"/api/casos/{caso}")
        assert r.status_code == 409
        assert r.json()["detail"] == "Hay una ejecución en curso para este caso. Espere a que termine para eliminarlo."
        assert (_raiz(tmp_path) / caso).is_dir()
    finally:
        api.soltar.set()


def test_restaurar_devuelve_el_caso(cliente, caso, tmp_path):
    entrada = cliente.delete(f"/api/casos/{caso}").json()["papelera"]
    r = cliente.post(f"/api/papelera/{entrada}/restaurar")
    assert r.status_code == 200 and r.json() == {"id": caso}
    assert (_raiz(tmp_path) / caso / "insumos" / "01PrimeraInstancia" / "a.pdf").is_file()
    assert not (_raiz(tmp_path) / ".papelera" / entrada).exists()
    assert _ids(cliente) == [caso]
    assert cliente.post(f"/api/papelera/{entrada}/restaurar").status_code == 404


def test_restaurar_con_el_id_ocupado_es_409(cliente, caso, tmp_path):
    entrada = cliente.delete(f"/api/casos/{caso}").json()["papelera"]
    (_raiz(tmp_path) / caso).mkdir()
    r = cliente.post(f"/api/papelera/{entrada}/restaurar")
    assert r.status_code == 409 and r.json()["detail"] == "Ya hay otro caso con ese identificador."
    assert (_raiz(tmp_path) / ".papelera" / entrada).is_dir()


@pytest.mark.parametrize(
    "entrada",
    [
        "caso-uno",
        "caso-uno@ayer",
        "caso-uno@20261117T150000000000",
        "@20261117T150000000000Z",
        ".papelera",
        "%2e%2e",
        ".oculto@20261117T150000000000Z",
        "caso-uno@20261317T150000000000Z",
        "otro@20261117T150000000000Z",
    ],
)
def test_restaurar_entradas_invalidas_es_404(cliente, caso, tmp_path, entrada):
    cliente.delete(f"/api/casos/{caso}")
    (_raiz(tmp_path) / ".papelera" / ".oculto@20261117T150000000000Z").mkdir()
    r = cliente.post(f"/api/papelera/{entrada}/restaurar")
    assert r.status_code == 404 and r.json()["detail"] == "No se encontró el caso en la papelera."


def test_restaurar_un_archivo_de_la_papelera_es_404(cliente, caso, tmp_path):
    cliente.delete(f"/api/casos/{caso}")
    (_raiz(tmp_path) / ".papelera" / "x@20261117T150000000000Z").write_text("no", encoding="utf-8")
    assert cliente.post("/api/papelera/x@20261117T150000000000Z/restaurar").status_code == 404


def test_un_caso_nuevo_no_reutiliza_un_id_en_la_papelera(cliente, caso):
    entrada = cliente.delete(f"/api/casos/{caso}").json()["papelera"]
    nuevo = _subir(cliente, "Caso Uno", {"a.pdf": b"%PDF-b"}).json()["id"]
    assert nuevo == f"{caso}-2"
    assert cliente.post(f"/api/papelera/{entrada}/restaurar").json() == {"id": caso}
    assert sorted(_ids(cliente)) == [caso, nuevo]


def test_crear_dir_caso_salta_ids_en_la_papelera(cliente, tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / ".papelera" / "tutela@20261117T150000000000Z").mkdir(parents=True)
    (raiz / ".papelera" / "tutela-2@manual").mkdir()
    (raiz / "tutela-3").mkdir()
    (raiz / ".papelera" / "tutela-4").mkdir()
    (raiz / ".papelera" / ".tutela-5@20261117T150000000000Z").mkdir()
    assert server._crear_dir_caso("Tutela")[0] == "tutela-4"
    assert server._crear_dir_caso("Tutela")[0] == "tutela-5"
    assert papelera.ids(raiz) == {"tutela", "tutela-2"}


def test_eliminar_purga_lo_vencido(cliente, caso, tmp_path):
    vieja = _raiz(tmp_path) / ".papelera" / papelera.nombre_entrada("viejo", datetime.now(timezone.utc) - timedelta(days=31))
    vieja.mkdir(parents=True)
    assert cliente.delete(f"/api/casos/{caso}").status_code == 200
    assert not vieja.exists()


def test_un_error_al_purgar_no_cambia_la_respuesta(cliente, caso, monkeypatch):
    monkeypatch.setattr(papelera, "purgar", lambda raiz: (_ for _ in ()).throw(OSError("disco")))
    r = cliente.delete(f"/api/casos/{caso}")
    assert r.status_code == 200 and r.json()["id"] == caso


def test_purgar_borra_solo_lo_vencido_y_respeta_lo_que_no_entiende(tmp_path):
    carpeta = papelera.carpeta(tmp_path)
    carpeta.mkdir()
    vencida = papelera.nombre_entrada("a", AHORA - timedelta(days=30, seconds=1))
    vigente = papelera.nombre_entrada("b", AHORA - timedelta(days=29, hours=23))
    archivo_vencido = papelera.nombre_entrada("c", AHORA - timedelta(days=40))
    raras = ["sin-sello", "d@20200101", ".e@20200101T000000000000Z", "f@20201301T000000000000Z"]
    for nombre in [vencida, vigente, *raras]:
        (carpeta / nombre / "insumos").mkdir(parents=True)
    (carpeta / archivo_vencido).write_text("x", encoding="utf-8")
    assert sorted(papelera.purgar(tmp_path, AHORA)) == sorted([vencida, archivo_vencido])
    assert sorted(p.name for p in carpeta.iterdir()) == sorted([vigente, *raras])


def test_purgar_sin_papelera_no_hace_nada(tmp_path):
    assert papelera.purgar(tmp_path / "no-existe") == []


def test_el_calentamiento_purga_la_papelera(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path))
    vieja = tmp_path / ".papelera" / papelera.nombre_entrada("a", datetime.now(timezone.utc) - timedelta(days=45))
    vieja.mkdir(parents=True)
    llamadas = []
    monkeypatch.setattr(resumen_caso, "calentar", llamadas.append)
    server._calentar_resumenes()
    assert not vieja.exists() and llamadas == [tmp_path]


def test_el_calentamiento_sigue_si_falla_la_purga(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path))
    monkeypatch.setattr(papelera, "purgar", lambda raiz: (_ for _ in ()).throw(OSError("disco")))
    llamadas = []
    monkeypatch.setattr(resumen_caso, "calentar", llamadas.append)
    server._calentar_resumenes()
    assert llamadas == [tmp_path]


def test_interpretar_entradas():
    assert papelera.interpretar("caso-1@20261117T150000123456Z") == ("caso-1", datetime(2026, 11, 17, 15, 0, 0, 123456, tzinfo=timezone.utc))
    assert papelera.interpretar("a@b@20261117T150000000000Z")[0] == "a@b"
    assert papelera.nombre_entrada("x", AHORA) == "x@20261117T150000000000Z"
    for malo in ["", "x", "x@", "@20261117T150000000000Z", "a/b@20261117T150000000000Z", "..@20261117T150000000000Z"]:
        assert papelera.interpretar(malo) is None


def _eliminar_al_resolver(monkeypatch, tmp_path):
    original = server._dir_caso

    def resolver(caso_id):
        d = original(caso_id)
        papelera.mover(_raiz(tmp_path).resolve(), caso_id)
        return d

    monkeypatch.setattr(server, "_dir_caso", resolver)


def test_run_da_404_si_la_carpeta_desaparecio(cliente, caso, api, tmp_path, monkeypatch):
    _eliminar_al_resolver(monkeypatch, tmp_path)
    r = cliente.post(f"/api/casos/{caso}/run", json={"cmd": "nuevo"})
    assert r.status_code == 404 and r.json()["detail"] == "Caso no encontrado."
    assert api.llamadas == [] and server.JOBS == {}
    assert not (_raiz(tmp_path) / caso).exists()


def test_revision_da_404_si_la_carpeta_desaparecio(cliente, caso, api, tmp_path, monkeypatch):
    _eliminar_al_resolver(monkeypatch, tmp_path)
    r = cliente.put(f"/api/casos/{caso}/revision", json={"roles": {}})
    assert r.status_code == 404 and r.json()["detail"] == "Caso no encontrado."
    assert api.llamadas == []
    assert not (_raiz(tmp_path) / caso).exists()


@pytest.mark.parametrize("metodo", ["put", "delete"])
def test_editar_el_borrador_da_404_si_la_carpeta_desaparecio(cliente, caso, tmp_path, monkeypatch, metodo):
    _eliminar_al_resolver(monkeypatch, tmp_path)
    ruta = f"/api/casos/{caso}/ediciones/apertura.antecedentes_hechos"
    r = cliente.put(ruta, json={"parrafo": 0, "original": "a", "texto": "b"}) if metodo == "put" else cliente.delete(ruta)
    assert r.status_code == 404 and r.json()["detail"] == "Caso no encontrado."
    assert not (_raiz(tmp_path) / caso).exists()


@pytest.mark.parametrize("archivos", [{"R/a.pdf": b"%PDF-a", "R/sub/b.pdf": b"%PDF-b"}, {"a.pdf": b"%PDF-a"}], ids=["antes-del-ultimo", "tras-el-ultimo"])
def test_eliminar_durante_la_subida_no_recrea_la_carpeta(cliente, tmp_path, monkeypatch, archivos):
    raiz = _raiz(tmp_path)

    def copiar(origen, destino):
        shutil.copyfileobj(origen, destino)
        papelera.mover(raiz, "subida")

    monkeypatch.setattr(rutas_casos, "shutil", types.SimpleNamespace(copyfileobj=copiar, rmtree=shutil.rmtree))
    r = _subir(cliente, "Subida", archivos)
    assert r.status_code == 404 and r.json()["detail"] == "Caso no encontrado."
    assert not (raiz / "subida").exists()


def test_otro_archivo_que_falta_en_la_subida_no_se_toma_por_un_caso_eliminado(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(formato_global, "copiar_a_caso", lambda caso_dir: (_ for _ in ()).throw(FileNotFoundError("plantilla")))
    with pytest.raises(FileNotFoundError):
        _subir(cliente, "Subida", {"a.pdf": b"%PDF-a"})
    assert not (_raiz(tmp_path) / "subida").exists()


def test_escrituras_tardias_no_recrean_la_carpeta(cliente, caso, tmp_path):
    caso_dir = (_raiz(tmp_path) / caso).resolve()
    cliente.delete(f"/api/casos/{caso}")
    assert resumen_caso.actualizar(caso_dir)["id"] == caso
    resumen_caso.tras_transicion(lambda d: None)(caso_dir)
    with pytest.raises(OSError):
        termino.guardar_termino(caso_dir, Termino(inicio="2026-11-17", dias=20, unidad="habiles"))
    with pytest.raises(OSError):
        cfgmod.guardar(caso_dir, cfgmod.Config())
    assert not caso_dir.exists()
