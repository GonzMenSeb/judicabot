from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tutela2 import api, resumen_caso, server, termino
from tutela2.esquemas import Termino
from tutela2.festivos import habiles_entre, sumar_habiles

# Calendario de noviembre de 2026: el lunes 16 es festivo (Todos los Santos trasladado) y hoy es el martes 17.
VIE_13, SAB_14, DOM_15, LUN_16, MAR_17, MIE_18 = (date(2026, 11, d) for d in (13, 14, 15, 16, 17, 18))


def _termino(inicio: str, dias: int, unidad: str = "habiles") -> dict:
    return {"inicio": inicio, "dias": dias, "unidad": unidad}


def _plazo(inicio: str, dias: int, unidad: str, hoy: date, estado: str = "revision"):
    return termino.plazo(_termino(inicio, dias, unidad), estado, hoy)


# --- festivos.sumar_habiles y festivos.habiles_entre ---


def test_sumar_habiles_salta_fines_de_semana_y_festivos():
    assert sumar_habiles(VIE_13, 1) == MAR_17
    assert sumar_habiles(VIE_13, 2) == MIE_18
    assert sumar_habiles(date(2026, 11, 10), 5) == MIE_18
    assert sumar_habiles(date(2026, 11, 10), 20) == date(2026, 12, 10)
    assert sumar_habiles(date(2026, 12, 4), 1) == date(2026, 12, 7)
    assert sumar_habiles(date(2026, 12, 7), 1) == date(2026, 12, 9)


def test_sumar_habiles_cero_devuelve_el_dia_y_negativo_es_error():
    assert sumar_habiles(SAB_14, 0) == SAB_14
    with pytest.raises(ValueError):
        sumar_habiles(VIE_13, -1)


def test_sumar_habiles_desde_un_dia_no_habil_cuenta_desde_el_siguiente():
    assert sumar_habiles(SAB_14, 1) == MAR_17
    assert sumar_habiles(LUN_16, 1) == MAR_17


def test_habiles_entre_excluye_el_inicio_e_incluye_el_final():
    assert habiles_entre(VIE_13, MAR_17) == 1
    assert habiles_entre(VIE_13, MIE_18) == 2
    assert habiles_entre(date(2026, 11, 9), VIE_13) == 4
    assert habiles_entre(MAR_17, MAR_17) == 0
    assert habiles_entre(VIE_13, DOM_15) == 0


def test_habiles_entre_es_negativo_si_el_final_es_anterior():
    assert habiles_entre(MAR_17, VIE_13) == -1
    assert habiles_entre(MIE_18, VIE_13) == -2
    assert habiles_entre(DOM_15, VIE_13) == 0


@pytest.mark.parametrize("a, b", [(VIE_13, MIE_18), (date(2026, 1, 1), date(2026, 12, 31)), (date(2026, 12, 20), date(2027, 1, 15))])
def test_habiles_entre_y_sumar_habiles_son_inversas(a, b):
    n = habiles_entre(a, b)
    assert habiles_entre(b, a) == -n
    destino = sumar_habiles(a, n)
    assert habiles_entre(a, destino) == n and destino <= b


# --- vencimiento ---


def test_un_termino_habil_que_cruza_el_festivo_del_16_de_noviembre():
    plazo = _plazo("2026-11-10", 5, "habiles", VIE_13)
    assert plazo == {"vence": "2026-11-18", "dias_restantes": 2}
    assert _plazo("2026-11-13", 1, "habiles", VIE_13) == {"vence": "2026-11-17", "dias_restantes": 1}


def test_un_termino_habil_no_cuenta_fines_de_semana():
    assert _plazo("2026-11-02", 5, "habiles", date(2026, 11, 2))["vence"] == "2026-11-09"  # 3, 4, 5, 6 y 9
    assert _plazo("2026-11-03", 5, "habiles", date(2026, 11, 3))["vence"] == "2026-11-10"
    assert _plazo("2026-11-06", 1, "habiles", date(2026, 11, 6))["vence"] == "2026-11-09"
    assert _plazo("2026-11-06", 3, "habiles", date(2026, 11, 6))["vence"] == "2026-11-11"


def test_el_dia_de_inicio_no_cuenta_aunque_no_sea_habil():
    assert _plazo("2026-11-14", 1, "habiles", SAB_14)["vence"] == "2026-11-17"
    assert _plazo("2026-11-16", 1, "habiles", LUN_16)["vence"] == "2026-11-17"


def test_el_termino_por_defecto_de_20_dias_habiles():
    assert _plazo("2026-11-10", 20, "habiles", date(2026, 11, 10)) == {"vence": "2026-12-10", "dias_restantes": 20}


@pytest.mark.parametrize(
    "dias, vence",
    [
        (1, "2026-11-17"),  # sábado 14 -> siguiente hábil
        (2, "2026-11-17"),  # domingo 15 -> siguiente hábil
        (3, "2026-11-17"),  # lunes 16 festivo -> siguiente hábil
        (4, "2026-11-17"),  # martes 17 ya es hábil: no se mueve
        (5, "2026-11-18"),
        (7, "2026-11-20"),
        (8, "2026-11-23"),  # sábado 21 -> lunes 23
    ],
)
def test_calendario_pasa_al_siguiente_habil_solo_si_cae_en_dia_no_habil(dias, vence):
    assert _plazo("2026-11-13", dias, "calendario", VIE_13)["vence"] == vence


def test_calendario_y_habiles_dan_distinto_vencimiento_con_el_mismo_numero():
    assert _plazo("2026-11-13", 3, "calendario", VIE_13)["vence"] == "2026-11-17"
    assert _plazo("2026-11-13", 3, "habiles", VIE_13)["vence"] == "2026-11-19"


# --- días restantes ---


@pytest.mark.parametrize(
    "hoy, restantes",
    [
        (date(2026, 11, 10), 5),
        (date(2026, 11, 13), 2),
        (date(2026, 11, 14), 2),  # sábado: faltan los mismos 2 hábiles que el viernes
        (date(2026, 11, 16), 2),  # festivo
        (MAR_17, 1),
        (MIE_18, 0),
        (date(2026, 11, 19), -1),
        (date(2026, 11, 20), -2),
        (date(2026, 11, 21), -2),  # fin de semana: no suma atraso hábil
        (date(2026, 11, 23), -3),
    ],
)
def test_dias_restantes_habiles_cambian_de_signo_al_pasar_el_vencimiento(hoy, restantes):
    assert _plazo("2026-11-10", 5, "habiles", hoy) == {"vence": "2026-11-18", "dias_restantes": restantes}


def test_dias_restantes_es_cero_solo_el_dia_del_vencimiento():
    assert _plazo("2026-11-10", 5, "habiles", MIE_18)["dias_restantes"] == 0
    assert _plazo("2026-11-13", 4, "calendario", MAR_17)["dias_restantes"] == 0


def test_un_vencido_el_fin_de_semana_sigue_siendo_negativo():
    # vence el viernes 13; el sábado 14 hay 0 días hábiles de atraso pero el plazo ya pasó
    assert _plazo("2026-11-12", 1, "habiles", VIE_13)["dias_restantes"] == 0
    assert _plazo("2026-11-12", 1, "habiles", SAB_14) == {"vence": "2026-11-13", "dias_restantes": -1}
    assert _plazo("2026-11-12", 1, "habiles", DOM_15)["dias_restantes"] == -1
    assert _plazo("2026-11-12", 1, "habiles", LUN_16)["dias_restantes"] == -1
    assert _plazo("2026-11-12", 1, "habiles", MAR_17)["dias_restantes"] == -1
    assert _plazo("2026-11-12", 1, "habiles", MIE_18)["dias_restantes"] == -2


def test_el_signo_siempre_sigue_la_comparacion_con_vence():
    for unidad in ("habiles", "calendario"):
        vence = date.fromisoformat(_plazo("2026-11-02", 7, unidad, date(2026, 11, 2))["vence"])
        for desplazo in range(-30, 31):
            dia = vence + timedelta(days=desplazo)
            restantes = _plazo("2026-11-02", 7, unidad, dia)["dias_restantes"]
            assert (restantes > 0) == (dia < vence) and (restantes == 0) == (dia == vence) and (restantes < 0) == (dia > vence), (unidad, dia)


@pytest.mark.parametrize(
    "hoy, restantes",
    [(date(2026, 11, 13), 4), (date(2026, 11, 16), 1), (MAR_17, 0), (date(2026, 11, 18), -1), (date(2026, 11, 24), -7)],
)
def test_dias_restantes_calendario_cuenta_dias_corridos(hoy, restantes):
    assert _plazo("2026-11-13", 3, "calendario", hoy) == {"vence": "2026-11-17", "dias_restantes": restantes}


def test_cambiar_hoy_cambia_los_dias_restantes_sin_cambiar_vence(monkeypatch):
    t = _termino("2026-11-10", 5)
    restantes = []
    for dia in (VIE_13, MAR_17, MIE_18, date(2026, 11, 19)):
        monkeypatch.setattr(termino, "hoy", lambda dia=dia: dia)
        plazo = termino.plazo(t, "revision", termino.hoy())
        assert plazo["vence"] == "2026-11-18"
        restantes.append(plazo["dias_restantes"])
    assert restantes == [2, 1, 0, -1]


# --- plazo: casos sin plazo y entradas dañadas ---


def test_no_hay_plazo_si_el_caso_termino_o_no_hay_termino():
    assert termino.plazo(_termino("2026-11-10", 5), "terminado", VIE_13) is None
    assert termino.plazo(None, "revision", VIE_13) is None
    assert termino.plazo({}, "revision", VIE_13) is None
    for estado in ("sin_iniciar", "revision", "incompleto", "esperando_decision", "error", "corriendo", None):
        assert termino.plazo(_termino("2026-11-10", 5), estado, VIE_13) is not None


@pytest.mark.parametrize(
    "dañado",
    [
        {"inicio": "2026-11-10", "dias": 5},
        {"inicio": "no es fecha", "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 0, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 366, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 10**9, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": True, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": "5", "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": [5], "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 5, "unidad": "semanas"},
        {"inicio": None, "dias": 5, "unidad": "habiles"},
        {"inicio": "9999-12-31", "dias": 365, "unidad": "habiles"},
        {"inicio": "9999-12-31", "dias": 365, "unidad": "calendario"},
    ],
)
def test_un_termino_danado_no_lanza_y_no_tiene_plazo(dañado):
    assert termino.plazo(dañado, "revision", VIE_13) is None


def test_el_calculo_se_guarda_en_cache_y_cada_llamada_recibe_un_dict_propio():
    termino._calcular.cache_clear()
    primero = _plazo("2026-11-10", 5, "habiles", VIE_13)
    primero["vence"] = "alterado"
    segundo = _plazo("2026-11-10", 5, "habiles", VIE_13)
    assert segundo == {"vence": "2026-11-18", "dias_restantes": 2}
    info = termino._calcular.cache_info()
    assert (info.misses, info.hits) == (1, 1)
    _plazo("2026-11-10", 5, "habiles", MAR_17)
    assert termino._calcular.cache_info().misses == 2
    assert termino._calcular.cache_info().maxsize >= 2048


# --- hora de Colombia ---


def test_hoy_usa_la_hora_de_colombia_aunque_el_contenedor_corra_en_utc(monkeypatch):
    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(termino, "datetime", Reloj)
    assert termino.ZONA.utcoffset(None) == timedelta(hours=-5)
    assert termino.hoy() == MAR_17  # 21:00 del 17 en Colombia, aunque en UTC ya sea el 18
    assert termino.ahora().utcoffset() == timedelta(hours=-5)


# --- .datos_caso.json ---


@pytest.fixture
def caso(tmp_path) -> Path:
    carpeta = tmp_path / "caso"
    carpeta.mkdir()
    return carpeta


DEFECTO = {"proceso": "segunda", "creado": None, "termino": None}


def test_sin_archivo_se_leen_los_valores_por_defecto(caso):
    assert termino.leer(caso) == DEFECTO
    assert termino.leer(caso / "no-existe") == DEFECTO


@pytest.mark.parametrize(
    "contenido",
    ["", "no es json", "[]", "null", '"x"', "{", '{"termino": 5}', '{"termino": {"dias": 0}}', '{"creado": 7, "termino": []}'],
)
def test_un_archivo_corrupto_se_lee_como_por_defecto(caso, contenido):
    (caso / ".datos_caso.json").write_text(contenido, encoding="utf-8")
    assert termino.leer(caso) == DEFECTO


def test_campos_invalidos_se_descartan_uno_por_uno(caso):
    (caso / ".datos_caso.json").write_text(
        json.dumps({"proceso": "otro", "creado": "ayer", "termino": _termino("2026-11-10", 5)}), encoding="utf-8"
    )
    assert termino.leer(caso) == {"proceso": "segunda", "creado": None, "termino": _termino("2026-11-10", 5)}
    (caso / ".datos_caso.json").write_text(
        json.dumps({"creado": "2026-11-17T10:00:00-05:00", "termino": {"inicio": "2026-02-30", "dias": 5, "unidad": "habiles"}}),
        encoding="utf-8",
    )
    assert termino.leer(caso) == {"proceso": "segunda", "creado": "2026-11-17T10:00:00-05:00", "termino": None}


def test_crear_escribe_proceso_creado_con_desfase_y_termino_nulo(caso):
    termino.crear(caso)
    bruto = json.loads((caso / ".datos_caso.json").read_text(encoding="utf-8"))
    assert set(bruto) == {"proceso", "creado", "termino"}
    assert bruto["proceso"] == "segunda" and bruto["termino"] is None
    assert datetime.fromisoformat(bruto["creado"]).utcoffset() == timedelta(hours=-5)
    assert termino.leer(caso)["creado"] == bruto["creado"]


def test_guardar_termino_conserva_proceso_y_creado(caso):
    termino.crear(caso)
    creado = termino.leer(caso)["creado"]
    termino.guardar_termino(caso, Termino(inicio="2026-11-10", dias=5, unidad="habiles"))
    assert termino.leer(caso) == {"proceso": "segunda", "creado": creado, "termino": _termino("2026-11-10", 5)}
    termino.guardar_termino(caso, Termino(inicio="2026-11-11", dias=8, unidad="calendario"))
    assert termino.leer(caso)["termino"] == _termino("2026-11-11", 8, "calendario") and termino.leer(caso)["creado"] == creado


def test_guardar_termino_en_un_caso_sin_archivo_lo_crea_con_creado_nulo(caso):
    termino.guardar_termino(caso, Termino(inicio="2026-11-10", dias=5, unidad="habiles"))
    assert termino.leer(caso) == {"proceso": "segunda", "creado": None, "termino": _termino("2026-11-10", 5)}


def test_la_escritura_es_atomica_y_no_deja_temporales(caso, monkeypatch):
    termino.crear(caso)
    anterior = (caso / ".datos_caso.json").read_bytes()

    def falla(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(termino.os, "replace", falla)
    with pytest.raises(OSError):
        termino.guardar_termino(caso, Termino(inicio="2026-11-10", dias=5, unidad="habiles"))
    assert (caso / ".datos_caso.json").read_bytes() == anterior
    assert [p.name for p in caso.iterdir()] == [".datos_caso.json"]


# --- término efectivo ---


def _estado(reparto: str | None, estado: str = "revision") -> dict:
    fechas = {} if reparto is None else {"reparto_2a": reparto}
    return {"ok": True, "estado": estado, "resumen": {"metadatos": {"fechas": fechas}}}


def _auto(caso: Path, **campos) -> None:
    (caso / "auto.json").write_text(json.dumps(campos), encoding="utf-8")


def test_el_termino_por_defecto_sale_del_acta_de_reparto(caso):
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-10", 20), True)
    assert termino.efectivo(caso, _estado("2026-11-10T09:30:00"))[0]["inicio"] == "2026-11-10"
    assert termino.fecha_reparto(caso, _estado("2026-11-10")) == date(2026, 11, 10)


def test_el_override_de_auto_json_gana_al_acta(caso):
    _auto(caso, fecha_reparto="2026-11-12")
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-12", 20), True)
    assert termino.fecha_reparto(caso, _estado("2026-11-10")) == date(2026, 11, 12)


@pytest.mark.parametrize("override", [None, "", "no es fecha", 7, "2026-13-45", "1926-11-03", "2101-01-01"])
def test_un_override_inutil_se_ignora_y_vale_el_acta(caso, override):
    _auto(caso, fecha_reparto=override, fecha="2026-11-20")
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-10", 20), True)


def test_una_fecha_de_reparto_fuera_de_rango_cae_a_la_del_acta_y_deja_termino(caso):
    _auto(caso, fecha_reparto="1926-11-03")
    assert termino.fecha_reparto(caso, _estado("2026-11-10")) == date(2026, 11, 10)
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-10", 20), True)
    # sin acta no hay fecha: no se reporta una fecha de reparto que no pueda dar término
    assert termino.fecha_reparto(caso, None) is None
    assert termino.describir(caso, None)["fecha_reparto"] is None


@pytest.mark.parametrize("contenido", ["", "no es json", "[]", "null", "5"])
def test_un_auto_json_corrupto_se_ignora(caso, contenido):
    (caso / "auto.json").write_text(contenido, encoding="utf-8")
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-10", 20), True)


def test_el_override_basta_aunque_no_se_pueda_leer_el_estado(caso):
    _auto(caso, fecha_reparto="2026-11-12")
    assert termino.efectivo(caso, None) == (_termino("2026-11-12", 20), True)


@pytest.mark.parametrize(
    "respuesta",
    [None, "x", 5, {}, {"estado": "error"}, {"resumen": None}, {"resumen": {}}, {"resumen": {"metadatos": None}},
     {"resumen": {"metadatos": {"fechas": None}}}, {"resumen": {"metadatos": {"fechas": "x"}}}, _estado(None), _estado("sin fecha")],
)
def test_sin_fecha_de_reparto_no_hay_termino(caso, respuesta):
    assert termino.efectivo(caso, respuesta) == (None, False)
    assert termino.fecha_reparto(caso, respuesta) is None


def test_una_fecha_de_reparto_fuera_de_rango_no_da_termino(caso):
    assert termino.efectivo(caso, _estado("9999-12-31")) == (None, False)
    assert termino.efectivo(caso, _estado("0001-01-01")) == (None, False)


def test_el_termino_guardado_gana_a_todo_y_no_es_por_defecto(caso):
    _auto(caso, fecha_reparto="2026-11-12")
    termino.guardar_termino(caso, Termino(inicio="2026-11-03", dias=10, unidad="calendario"))
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-03", 10, "calendario"), False)
    assert termino.efectivo(caso, None) == (_termino("2026-11-03", 10, "calendario"), False)


def test_un_termino_guardado_invalido_vuelve_al_por_defecto(caso):
    (caso / ".datos_caso.json").write_text(json.dumps({"termino": {"inicio": "x", "dias": 5, "unidad": "habiles"}}), encoding="utf-8")
    assert termino.efectivo(caso, _estado("2026-11-10")) == (_termino("2026-11-10", 20), True)


def test_describir_arma_la_respuesta_con_el_plazo_de_hoy(caso, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    assert termino.describir(caso, _estado("2026-11-10")) == {
        "termino": _termino("2026-11-10", 20),
        "por_defecto": True,
        "fecha_reparto": "2026-11-10",
        "vence": "2026-12-10",
        "dias_restantes": 17,
    }
    assert termino.describir(caso, _estado("2026-11-10", "terminado")) == {
        "termino": _termino("2026-11-10", 20),
        "por_defecto": True,
        "fecha_reparto": "2026-11-10",
        "vence": None,
        "dias_restantes": None,
    }
    assert termino.describir(caso, None) == {"termino": None, "por_defecto": False, "fecha_reparto": None, "vence": None, "dias_restantes": None}


# --- esquemas.Termino ---


def test_termino_acepta_el_formato_canonico():
    t = Termino(inicio="2026-11-10", dias=20, unidad="habiles")
    assert t.model_dump() == _termino("2026-11-10", 20)
    assert Termino(inicio="2026-11-10", dias=1, unidad="calendario").dias == 1 and Termino(inicio="2026-11-10", dias=365, unidad="habiles").dias == 365


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio": "2026-02-30", "dias": 5, "unidad": "habiles"},
        {"inicio": "20261110", "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-W46-2", "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-1-5", "dias": 5, "unidad": "habiles"},
        {"inicio": " 2026-11-10", "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-11-10T00:00:00", "dias": 5, "unidad": "habiles"},
        {"inicio": "1999-12-31", "dias": 5, "unidad": "habiles"},
        {"inicio": "2101-01-01", "dias": 5, "unidad": "habiles"},
        {"inicio": None, "dias": 5, "unidad": "habiles"},
        {"inicio": 20261110, "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 0, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": -3, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 366, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 2.5, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 5.0, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": "5", "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": True, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": None, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 5, "unidad": "semanas"},
        {"inicio": "2026-11-10", "dias": 5, "unidad": "HABILES"},
        {"inicio": "2026-11-10", "dias": 5, "unidad": None},
        {"inicio": "2026-11-10", "dias": 5},
        {"dias": 5, "unidad": "habiles"},
        {},
    ],
)
def test_termino_rechaza_entradas_invalidas(cuerpo):
    with pytest.raises(ValidationError):
        Termino.model_validate(cuerpo)


# --- rutas ---


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    server.JOBS.clear()
    yield TestClient(server.app, base_url="http://127.0.0.1")
    server.JOBS.clear()


def _subir(cliente: TestClient, nombre: str = "Raiz") -> str:
    r = cliente.post("/api/casos", data={"nombre": nombre}, files=[("files", ("a.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _archivo(caso_id: str) -> Path:
    return server.casos_dir() / caso_id / ".datos_caso.json"


@pytest.fixture
def con_acta(monkeypatch):
    """api.estado devuelve un caso en revisión con acta de reparto de segunda del 10 de nov. de 2026."""
    respuesta = {"ok": True, "estado": "revision", "resumen": {"metadatos": _estado("2026-11-10")["resumen"]["metadatos"]}}
    monkeypatch.setattr(api, "estado", lambda caso_dir: dict(respuesta))
    return respuesta


def test_post_escribe_datos_caso_con_proceso_creado_y_termino_nulo(cliente):
    caso_id = _subir(cliente)
    bruto = json.loads(_archivo(caso_id).read_text(encoding="utf-8"))
    assert bruto["proceso"] == "segunda" and bruto["termino"] is None and set(bruto) == {"proceso", "creado", "termino"}
    creado = datetime.fromisoformat(bruto["creado"])
    assert creado.utcoffset() == timedelta(hours=-5)
    assert abs(creado - datetime.now(timezone.utc)) < timedelta(minutes=1)
    assert [p.name for p in _archivo(caso_id).parent.iterdir() if p.name.endswith(".tmp")] == []
    [fila] = cliente.get("/api/casos").json()
    assert fila["creado"] == bruto["creado"] and fila["termino"] is None and fila["vence"] is None and fila["dias_restantes"] is None


def test_post_si_falla_datos_caso_no_deja_el_caso(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))

    def falla(caso_dir):
        raise OSError("disco lleno")

    monkeypatch.setattr(termino, "crear", falla)
    cliente = TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    r = cliente.post("/api/casos", data={"nombre": "x"}, files=[("files", ("a.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 500
    assert list((tmp_path / "casos").iterdir()) == []


def test_un_caso_sin_datos_caso_se_lee_con_los_valores_por_defecto(cliente):
    caso_id = _subir(cliente)
    _archivo(caso_id).unlink()
    r = cliente.get(f"/api/casos/{caso_id}/resumen").json()
    assert r["proceso"] == "segunda" and r["creado"] is None and r["termino"] is None


@pytest.mark.parametrize("ruta", ["no-existe", ".oculto", "%2e%2e"])
def test_termino_de_un_caso_inexistente_es_404(cliente, ruta):
    _subir(cliente)
    valido = {"inicio": "2026-11-10", "dias": 5, "unidad": "habiles"}
    assert cliente.get(f"/api/casos/{ruta}/termino").status_code == 404
    assert cliente.put(f"/api/casos/{ruta}/termino", json=valido).status_code == 404
    assert cliente.put(f"/api/casos/{ruta}/termino", json={"dias": 0}).status_code == 404


def test_get_termino_sin_fecha_de_reparto_no_trae_termino(cliente):
    caso_id = _subir(cliente)
    assert cliente.get(f"/api/casos/{caso_id}/termino").json() == {
        "termino": None, "por_defecto": False, "fecha_reparto": None, "vence": None, "dias_restantes": None,
    }


def test_get_termino_propone_el_de_20_dias_habiles_desde_el_acta(cliente, con_acta, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    caso_id = _subir(cliente)
    r = cliente.get(f"/api/casos/{caso_id}/termino")
    assert r.status_code == 200
    assert r.json() == {
        "termino": _termino("2026-11-10", 20), "por_defecto": True, "fecha_reparto": "2026-11-10",
        "vence": "2026-12-10", "dias_restantes": 17,
    }
    assert not any(p.name == "auto.json" for p in (server.casos_dir() / caso_id).iterdir())


def test_get_termino_usa_el_override_de_auto_json(cliente, con_acta, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    caso_id = _subir(cliente)
    _auto(server.casos_dir() / caso_id, fecha_reparto="2026-11-12")
    r = cliente.get(f"/api/casos/{caso_id}/termino").json()
    assert r["fecha_reparto"] == "2026-11-12" and r["termino"] == _termino("2026-11-12", 20) and r["por_defecto"] is True
    assert r["vence"] == "2026-12-14"


def test_put_termino_guarda_y_devuelve_lo_mismo_que_get(cliente, con_acta, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    caso_id = _subir(cliente)
    antes = json.loads(_archivo(caso_id).read_text(encoding="utf-8"))
    cuerpo = _termino("2026-11-10", 5)
    r = cliente.put(f"/api/casos/{caso_id}/termino", json=cuerpo)
    assert r.status_code == 200
    esperado = {"termino": cuerpo, "por_defecto": False, "fecha_reparto": "2026-11-10", "vence": "2026-11-18", "dias_restantes": 2}
    assert r.json() == esperado
    assert cliente.get(f"/api/casos/{caso_id}/termino").json() == esperado

    despues = json.loads(_archivo(caso_id).read_text(encoding="utf-8"))
    assert despues == {**antes, "termino": cuerpo}

    # la lista y el resumen del caso ven el término nuevo sin esperar a nada más
    [fila] = cliente.get("/api/casos").json()
    assert (fila["termino"], fila["vence"], fila["dias_restantes"]) == (cuerpo, "2026-11-18", 2)
    assert cliente.get(f"/api/casos/{caso_id}/resumen").json() == fila

    # volver a guardar reemplaza el término
    otro = _termino("2026-11-13", 4, "calendario")
    r = cliente.put(f"/api/casos/{caso_id}/termino", json=otro)
    assert r.json()["termino"] == otro and (r.json()["vence"], r.json()["dias_restantes"]) == ("2026-11-17", 4)
    assert json.loads(_archivo(caso_id).read_text(encoding="utf-8"))["creado"] == antes["creado"]


def test_put_termino_en_un_caso_sin_datos_caso_los_crea(cliente, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    caso_id = _subir(cliente)
    _archivo(caso_id).unlink()
    cuerpo = _termino("2026-11-10", 5)
    assert cliente.put(f"/api/casos/{caso_id}/termino", json=cuerpo).status_code == 200
    assert json.loads(_archivo(caso_id).read_text(encoding="utf-8")) == {"proceso": "segunda", "creado": None, "termino": cuerpo}


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio": "2026-02-30", "dias": 5, "unidad": "habiles"},
        {"inicio": "20261110", "dias": 5, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 0, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 366, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": "5", "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 2.5, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": True, "unidad": "habiles"},
        {"inicio": "2026-11-10", "dias": 5, "unidad": "semanas"},
        {"inicio": "2026-11-10", "dias": 5},
        {},
        [],
        None,
    ],
)
def test_put_termino_invalido_es_422_y_no_toca_el_archivo(cliente, cuerpo):
    caso_id = _subir(cliente)
    antes = _archivo(caso_id).read_bytes()
    r = cliente.put(f"/api/casos/{caso_id}/termino", json=cuerpo)
    assert r.status_code == 422
    assert _archivo(caso_id).read_bytes() == antes


def test_put_termino_con_cuerpo_que_no_es_json_es_422(cliente):
    caso_id = _subir(cliente)
    assert cliente.put(f"/api/casos/{caso_id}/termino", content=b"no es json", headers={"content-type": "application/json"}).status_code == 422


def test_put_termino_de_un_caso_terminado_no_tiene_plazo(cliente, monkeypatch):
    monkeypatch.setattr(termino, "hoy", lambda: VIE_13)
    monkeypatch.setattr(api, "estado", lambda caso_dir: _estado("2026-11-10", "terminado"))
    caso_id = _subir(cliente)
    cuerpo = _termino("2026-11-10", 5)
    r = cliente.put(f"/api/casos/{caso_id}/termino", json=cuerpo).json()
    assert r["termino"] == cuerpo and r["vence"] is None and r["dias_restantes"] is None
    [fila] = cliente.get("/api/casos").json()
    assert fila["estado"] == "terminado" and fila["termino"] == cuerpo and fila["vence"] is None and fila["dias_restantes"] is None


def test_put_termino_no_falla_si_no_se_puede_actualizar_el_resumen(cliente, monkeypatch):
    caso_id = _subir(cliente)

    def falla(caso_dir):
        raise RuntimeError("resumen roto")

    monkeypatch.setattr(resumen_caso, "actualizar", falla)
    assert cliente.put(f"/api/casos/{caso_id}/termino", json=_termino("2026-11-10", 5)).status_code == 200
    assert termino.leer(server.casos_dir() / caso_id)["termino"] == _termino("2026-11-10", 5)


def test_put_termino_si_no_se_puede_escribir_es_500(tmp_path, monkeypatch):
    monkeypatch.setenv("CASOS_DIR", str(tmp_path / "casos"))
    cliente = TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    caso_id = _subir(cliente)

    def falla(caso_dir, nuevo):
        raise OSError("sin espacio")

    monkeypatch.setattr(termino, "guardar_termino", falla)
    r = cliente.put(f"/api/casos/{caso_id}/termino", json=_termino("2026-11-10", 5))
    assert r.status_code == 500 and "No se pudo guardar el término" in r.json()["detail"]


def test_la_lista_trae_el_plazo_del_dia_aunque_el_resumen_este_cacheado(cliente, con_acta, monkeypatch):
    caso_id = _subir(cliente)
    caso_dir = server.casos_dir() / caso_id
    termino.guardar_termino(caso_dir, Termino(inicio="2026-11-10", dias=5, unidad="habiles"))
    vistos = []
    for dia in (VIE_13, MAR_17, MIE_18, date(2026, 11, 19)):
        monkeypatch.setattr(termino, "hoy", lambda dia=dia: dia)
        [fila] = cliente.get("/api/casos").json()
        vistos.append((fila["vence"], fila["dias_restantes"]))
    assert vistos == [("2026-11-18", 2), ("2026-11-18", 1), ("2026-11-18", 0), ("2026-11-18", -1)]
    assert "dias_restantes" not in (caso_dir / ".resumen.json").read_text(encoding="utf-8")
