from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request

import pytest

from tutela2 import registro_apoderados, vista
from tutela2.models import Apoderado, Identificacion
from tutela2.registro_apoderados import ConsultaVigencia, Registro, Revision

CEDULA = "43000021"


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)


@pytest.fixture
def caso(tmp_path):
    d = tmp_path / "caso"
    d.mkdir()
    return d


def _ident(n: int = 1) -> Identificacion:
    return Identificacion(
        ingesta_sha="abc",
        apoderados=[Apoderado(id=f"ap-{i:010d}", nombre=f"Abogado {i}", parte="Entidad", cedula=CEDULA) for i in range(n)],
        documentos_revisados=3,
    )


def _consulta(estado: str = "vigente") -> ConsultaVigencia:
    return ConsultaVigencia(estado=estado, origen="fake", consultado_en=registro_apoderados.ahora())


def test_sin_archivo_el_registro_esta_vacio(caso):
    reg = registro_apoderados.leer(caso)
    assert reg == Registro() and reg.identificacion is None and reg.version == 1
    assert not (caso / "apoderados").exists()


def test_la_ruta_queda_fuera_de_insumos_y_salidas(caso):
    ruta = registro_apoderados.ruta(caso)
    assert ruta == caso / "apoderados" / "registro.json"
    assert not ruta.is_relative_to(caso / "insumos") and not ruta.is_relative_to(caso / "salidas")


def test_espejar_crea_la_carpeta_y_conserva_lo_demas(caso):
    registro_apoderados.espejar(caso, _ident())
    assert registro_apoderados.ruta(caso).is_file()
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta()}))
    registro_apoderados.actualizar(
        caso, lambda r: r.revisiones.update({"ap-0000000000": Revision(revisado=True, en="x", huella="h")})
    )
    registro_apoderados.espejar(caso, _ident(2))
    reg = registro_apoderados.leer(caso)
    assert len(reg.identificacion.apoderados) == 2
    assert reg.consultas[CEDULA].estado == "vigente" and reg.revisiones["ap-0000000000"].huella == "h"
    assert Registro.model_validate_json(registro_apoderados.ruta(caso).read_text(encoding="utf-8")) == reg


def test_actualizar_sin_carpeta_no_hace_nada(caso):
    llamadas = []
    assert registro_apoderados.actualizar(caso, llamadas.append) is None
    assert llamadas == [] and not (caso / "apoderados").exists()


def test_actualizar_puede_devolver_un_registro_nuevo(caso):
    registro_apoderados.espejar(caso, _ident())
    nuevo = registro_apoderados.actualizar(caso, lambda r: Registro(identificacion=_ident(3)))
    assert len(nuevo.identificacion.apoderados) == 3
    assert registro_apoderados.leer(caso) == nuevo


def test_sin_cambios_no_reescribe(caso):
    registro_apoderados.espejar(caso, _ident())
    os.utime(registro_apoderados.ruta(caso), ns=(1, 1))
    registro_apoderados.actualizar(caso, lambda r: None)
    registro_apoderados.espejar(caso, _ident())
    assert registro_apoderados.ruta(caso).stat().st_mtime_ns == 1
    registro_apoderados.espejar(caso, _ident(2))
    assert registro_apoderados.ruta(caso).stat().st_mtime_ns != 1


def test_escritura_atomica_sin_temporales_y_sin_romper_el_original(caso, monkeypatch):
    registro_apoderados.espejar(caso, _ident())
    original = registro_apoderados.ruta(caso).read_bytes()

    def falla(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(vista.os, "replace", falla)
    with pytest.raises(OSError):
        registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta()}))
    assert registro_apoderados.ruta(caso).read_bytes() == original
    assert sorted(p.name for p in (caso / "apoderados").iterdir()) == ["registro.json"]


def test_veinte_escritores_concurrentes_no_pierden_cambios(caso):
    registro_apoderados.espejar(caso, _ident())
    lecturas_rotas: list[Exception] = []
    parar = threading.Event()

    def lector():
        while not parar.is_set():
            try:
                texto = registro_apoderados.ruta(caso).read_text(encoding="utf-8")
                json.loads(texto)
            except FileNotFoundError:
                continue
            except Exception as e:
                lecturas_rotas.append(e)

    def escritor(i: int):
        registro_apoderados.actualizar(
            caso, lambda r: r.revisiones.update({f"ap-{i:010d}": Revision(revisado=True, en="x", huella=str(i))})
        )

    hilo_lector = threading.Thread(target=lector)
    hilo_lector.start()
    hilos = [threading.Thread(target=escritor, args=(i,)) for i in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    parar.set()
    hilo_lector.join()

    reg = registro_apoderados.leer(caso)
    assert sorted(reg.revisiones) == sorted(f"ap-{i:010d}" for i in range(20))
    assert lecturas_rotas == []
    assert sorted(p.name for p in (caso / "apoderados").iterdir()) == ["registro.json"]


def test_una_escritura_despues_de_borrar_no_resucita_el_registro(caso):
    registro_apoderados.espejar(caso, _ident())
    registro_apoderados.borrar(caso)
    assert not (caso / "apoderados").exists()
    assert registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta()})) is None
    assert not (caso / "apoderados").exists()
    registro_apoderados.borrar(caso)


def test_borrar_espera_a_la_escritura_en_curso(caso):
    registro_apoderados.espejar(caso, _ident())
    dentro, soltar = threading.Event(), threading.Event()

    def lento(r: Registro) -> None:
        dentro.set()
        soltar.wait(5)
        r.consultas[CEDULA] = _consulta()

    escritor = threading.Thread(target=registro_apoderados.actualizar, args=(caso, lento))
    escritor.start()
    assert dentro.wait(5)
    borrador = threading.Thread(target=registro_apoderados.borrar, args=(caso,))
    borrador.start()
    borrador.join(0.2)
    assert borrador.is_alive()
    soltar.set()
    escritor.join(5)
    borrador.join(5)
    assert not (caso / "apoderados").exists()


def test_espejar_si_falta_lee_el_grafo_solo_si_hace_falta(caso):
    llamadas = []

    def leer_estado():
        llamadas.append(1)
        return _ident().model_dump(mode="json")

    reg = registro_apoderados.espejar_si_falta(caso, leer_estado)
    assert reg.identificacion == _ident() and llamadas == [1]
    assert registro_apoderados.leer(caso).identificacion == _ident()
    registro_apoderados.espejar_si_falta(caso, leer_estado)
    assert llamadas == [1]


def test_espejar_si_falta_sin_identificacion_no_crea_nada(caso):
    reg = registro_apoderados.espejar_si_falta(caso, lambda: None)
    assert reg.identificacion is None and not (caso / "apoderados").exists()


def test_espejar_si_falta_ignora_un_estado_invalido_y_conserva_lo_guardado(caso, caplog):
    (caso / "apoderados").mkdir()
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta()}))
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        reg = registro_apoderados.espejar_si_falta(caso, lambda: {"apoderados": "no es una lista"})
    assert reg.identificacion is None and CEDULA in reg.consultas
    assert registro_apoderados.leer(caso).identificacion is None


@pytest.mark.parametrize(
    "contenido",
    [
        ('{"consultas": {"' + CEDULA + '": 3}}').encode(),
        ('{"consultas": {"' + CEDULA + '": {"estado": "vencida", "origen": "fake", "consultado_en": "x"}}}').encode(),
        b"{no es json",
        b"\xff\xfe\x00 binario",
    ],
    ids=["tipo", "estado_de_otra_version", "json_roto", "binario"],
)
def test_registro_corrupto_falla_cerrado_sin_reescribirse_y_sin_cedulas(caso, caplog, contenido):
    (caso / "apoderados").mkdir()
    registro_apoderados.ruta(caso).write_bytes(contenido)
    with caplog.at_level(logging.WARNING, logger="tutela2"):
        with pytest.raises(registro_apoderados.RegistroInvalido) as error:
            registro_apoderados.leer(caso)
        with pytest.raises(registro_apoderados.RegistroInvalido):
            registro_apoderados.actualizar(caso, lambda r: r.revisiones.clear())
        with pytest.raises(registro_apoderados.RegistroInvalido):
            registro_apoderados.espejar(caso, _ident())
        with pytest.raises(registro_apoderados.RegistroInvalido):
            registro_apoderados.espejar_si_falta(caso, lambda: _ident().model_dump(mode="json"))
    assert registro_apoderados.ruta(caso).read_bytes() == contenido
    assert sorted(p.name for p in (caso / "apoderados").iterdir()) == ["registro.json"]
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert CEDULA not in str(error.value)
    assert caplog.records and all(CEDULA not in r.getMessage() for r in caplog.records)


def test_candado_por_caso(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert registro_apoderados._candado(a) is registro_apoderados._candado(tmp_path / "x" / ".." / "a")
    assert registro_apoderados._candado(a) is not registro_apoderados._candado(b)
