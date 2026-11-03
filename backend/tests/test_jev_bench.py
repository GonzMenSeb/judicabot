from __future__ import annotations

import json
from pathlib import Path

import pytest

from tutela2 import cli, jev_bench
from tutela2.clasificar import EVIDENCIA_SIN_ROL
from tutela2.config import Config, JevConfig
from tutela2.jev import ErrorJev, FakeJev
from tutela2.jev_bench import UMBRALES, comparar, correr, informe_markdown
from tutela2.jev_roles import ROLES_JEV, OpinionRol
from tutela2.models import Doc, Ingesta, Pagina

PREFIJO = "01PrimeraInstancia/C01Principal/"
CFG = Config(ocr=False, jev=JevConfig(modo="sombra", concurrencia=2))

ESCRITO = (
    "Medellín, 9 de febrero de 2027\nSeñor JUEZ CONSTITUCIONAL (REPARTO)\nACCIÓN DE TUTELA\n"
    "Accionante: MARIA PRUEBA\nHECHOS\n1. Algo ocurrió.\nPRETENSIONES\nSolicito amparo.\n"
)
NOTA = "Nota interna breve, sin ninguna característica propia de un documento del trámite."


def doc_de(n: int, nombre: str, rol: str, evidencia: str | None = None, con_texto: bool = True) -> Doc:
    if evidencia is None:
        evidencia = EVIDENCIA_SIN_ROL if rol == "otro" else "Rasgos del rol."
    return Doc(
        doc_id=f"1a-{n:03d}",
        ruta=f"C01Principal/{nombre}",
        nombre=nombre,
        instancia="1a",
        rol=rol,
        sha256=f"sha{n}",
        paginas=[Pagina(n=1, texto="Texto de prueba.")] if con_texto else [],
        evidencia=evidencia,
    )


def ingesta_con(docs: list[tuple]) -> Ingesta:
    return Ingesta(documentos=[doc_de(i, *d) for i, d in enumerate(docs, 1)])


def verdad_de(caso: str, *docs: tuple[str, str]) -> dict:
    return {
        "case": caso,
        "docs": [{"file": PREFIJO + n, "role": r, "confidence": "high", "evidence": "x"} for n, r in docs],
    }


def op(n: int, rol: str, confianza: float) -> OpinionRol:
    return OpinionRol(f"1a-{n:03d}", rol, confianza, {}, {})


def test_comparar_cuenta_rescates_y_falsos_rellenos():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "memorial"))]
    ing = {"C": ingesta_con([("a.pdf", "otro"), ("b.pdf", "otro")])}
    ops = {"C": [op(1, "escrito_tutela", 0.97), op(2, "contestacion", 0.95)]}
    r = comparar(verdad, ing, ops)
    assert len(r["rescates"]) == 1 and len(r["falsos_rellenos"]) == 1
    assert r["rescates"][0] == {
        "caso": "C",
        "archivo": PREFIJO + "a.pdf",
        "verdad": "escrito_tutela",
        "codigo": "otro",
        "jev": "escrito_tutela",
        "confianza": 0.97,
        "confianza_verdad": "high",
    }
    assert r["falsos_rellenos"][0]["archivo"] == PREFIJO + "b.pdf"
    assert r["falsos_rellenos"][0]["jev"] == "contestacion" and r["falsos_rellenos"][0]["verdad"] == "memorial"


def test_solo_cuenta_el_relleno_que_aplicar_haria():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "escrito_tutela"), ("c.pdf", "otro"), ("d.pdf", "escrito_tutela"))]
    ing = {
        "C": ingesta_con(
            [
                ("a.pdf", "otro", "Sentencia de otro radicado (05001)."),
                ("b.pdf", "otro"),
                ("c.pdf", "otro"),
                ("d.pdf", "fallo_a_quo"),
            ]
        )
    }
    ops = {"C": [op(1, "escrito_tutela", 0.99), op(2, "otro", 0.99), op(3, "otro", 0.99), op(4, "impugnacion", 0.99)]}
    r = comparar(verdad, ing, ops)
    assert r["rescates"] == [] and r["falsos_rellenos"] == [] and r["fuera_de_catalogo"] == []
    assert {d["archivo"] for d in r["discrepancias"]} == {PREFIJO + "a.pdf", PREFIJO + "d.pdf"}


def test_documento_sin_texto_del_codigo_tambien_es_rellenable():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"))]
    ing = {"C": ingesta_con([("a.pdf", "otro", "Sin texto legible.")])}
    r = comparar(verdad, ing, {"C": [op(1, "escrito_tutela", 0.96)]})
    assert len(r["rescates"]) == 1


def test_rol_de_la_verdad_fuera_del_catalogo_cuenta_como_falso_relleno_y_se_lista_aparte():
    verdad = [verdad_de("C", ("a.pdf", "nuevo:poder"))]
    ing = {"C": ingesta_con([("a.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(1, "anexo", 0.95)]})
    assert r["rescates"] == []
    assert [(f["verdad"], f["jev"]) for f in r["falsos_rellenos"]] == [("nuevo:poder", "anexo")]
    assert [(f["verdad"], f["jev"]) for f in r["fuera_de_catalogo"]] == [("nuevo:poder", "anexo")]
    assert r["n_fuera_catalogo"] == 1
    assert r["por_umbral"][0.9]["rescates"] == 0 and r["por_umbral"][0.9]["falsos_rellenos"] == 1
    assert r["por_umbral"][0.99]["falsos_rellenos"] == 0
    assert r["umbral_relleno"] is None


def test_nuevo_anexo_equivale_a_anexo_y_un_acierto_es_un_rescate():
    verdad = [verdad_de("C", ("a.pdf", "nuevo:anexo"))]
    ing = {"C": ingesta_con([("a.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(1, "anexo", 0.95)]})
    assert len(r["rescates"]) == 1 and r["falsos_rellenos"] == [] and r["fuera_de_catalogo"] == []
    assert r["rescates"][0]["verdad"] == "nuevo:anexo"
    assert r["n_fuera_catalogo"] == 0 and r["exactitud_jev"] == 1.0 and r["exactitud_codigo"] == 0.0
    assert r["por_umbral"][0.9]["rescates"] == 1


def test_nuevo_anexo_con_otro_rol_propuesto_por_jev_es_falso_relleno():
    verdad = [verdad_de("C", ("a.pdf", "nuevo:anexo"), ("b.pdf", "nuevo:anexo"))]
    ing = {"C": ingesta_con([("a.pdf", "otro"), ("b.pdf", "anexo")])}
    r = comparar(verdad, ing, {"C": [op(1, "memorial", 0.95), op(2, "anexo", 0.95)]})
    assert [f["jev"] for f in r["falsos_rellenos"]] == ["memorial"] and r["fuera_de_catalogo"] == []
    assert r["por_umbral"][0.9]["falsos_rellenos"] == 1 and r["umbral_relleno"] is None
    assert r["exactitud_codigo"] == 0.5 and r["exactitud_jev"] == 0.5


def test_un_rol_nuevo_que_no_esta_en_el_catalogo_no_se_normaliza():
    verdad = [verdad_de("C", ("a.pdf", "nuevo:poder"))]
    ing = {"C": ingesta_con([("a.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(1, "poder", 0.95)]})
    assert r["rescates"] == [] and r["n_fuera_catalogo"] == 1


def test_no_cuenta_como_relleno_un_rol_unico_que_ya_tiene_otro_documento():
    verdad = [verdad_de("C", ("a.pdf", "fallo_a_quo"), ("b.pdf", "memorial"))]
    ing = {"C": ingesta_con([("a.pdf", "fallo_a_quo"), ("b.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(1, "fallo_a_quo", 0.99), op(2, "fallo_a_quo", 0.99)]})
    assert r["rescates"] == [] and r["falsos_rellenos"] == [] and r["umbral_relleno"] is None
    assert [d["archivo"] for d in r["discrepancias"]] == [PREFIJO + "b.pdf"]


def test_archivos_de_la_verdad_que_la_ingesta_no_lee_se_listan_aparte():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("indice.xlsm", "indice"), ("video.MP4", "anexo"), ("falta.pdf", "anexo"))]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela")])}
    r = comparar(verdad, ing, {"C": []})
    assert r["no_legibles"] == [PREFIJO + "indice.xlsm", PREFIJO + "video.MP4"]
    assert r["sin_pareja"] == [PREFIJO + "falta.pdf"] and r["n_verdad_sin_pareja"] == 1


def test_exactitudes_y_cobertura_de_opiniones():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "fallo_a_quo"), ("c.pdf", "impugnacion"), ("d.pdf", "anexo"))]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela"), ("b.pdf", "fallo_a_quo"), ("c.pdf", "otro"), ("d.pdf", "otro")])}
    ops = {"C": [op(1, "escrito_tutela", 0.99), op(2, "otro", 0.6), op(3, "impugnacion", 0.9)]}
    r = comparar(verdad, ing, ops)
    assert r["n_docs"] == 4 and r["n_con_jev"] == 3
    assert r["exactitud_codigo"] == pytest.approx(0.5)
    assert r["exactitud_codigo_en_jev"] == pytest.approx(2 / 3)
    assert r["exactitud_jev"] == pytest.approx(2 / 3)


def test_sin_opinion_separa_documentos_sin_texto_de_los_que_no_respondieron():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "escrito_tutela"), ("c.pdf", "escrito_tutela"))]
    ing = {"C": ingesta_con([("a.pdf", "otro", None, False), ("b.pdf", "otro"), ("c.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(3, "escrito_tutela", 0.95)]})
    assert r["sin_opinion"] == {"C": {"sin_texto": 1, "sin_respuesta": 1}}


def test_discrepancias_son_las_opiniones_distintas_al_codigo():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "fallo_a_quo"))]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela"), ("b.pdf", "fallo_a_quo")])}
    r = comparar(verdad, ing, {"C": [op(1, "escrito_tutela", 0.99), op(2, "impugnacion", 0.97)]})
    assert r["discrepancias"] == [
        {
            "caso": "C",
            "archivo": PREFIJO + "b.pdf",
            "verdad": "fallo_a_quo",
            "codigo": "fallo_a_quo",
            "jev": "impugnacion",
            "confianza": 0.97,
            "confianza_verdad": "high",
        }
    ]
    assert r["falsos_rellenos"] == []


def test_documentos_sin_pareja_se_listan_no_se_descartan():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("archivo_de_mas.pdf", "anexo"))]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela"), ("sobrante.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": []})
    assert PREFIJO + "archivo_de_mas.pdf" in r["sin_pareja"]
    assert "C01Principal/sobrante.pdf" in r["sin_pareja"]
    assert r["n_docs"] == 1


def test_caso_sin_ingesta_deja_todos_sus_archivos_sin_pareja():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "anexo"))]
    r = comparar(verdad, {}, {})
    assert r["n_docs"] == 0 and sorted(r["sin_pareja"]) == [PREFIJO + "a.pdf", PREFIJO + "b.pdf"]
    assert r["exactitud_codigo"] is None and r["exactitud_jev"] is None


def test_pareja_por_ruta_exacta_sufijo_o_nombre():
    verdad = [
        {
            "case": "C",
            "docs": [
                {"file": "C01Principal/a.pdf", "role": "escrito_tutela"},
                {"file": "01PrimeraInstancia/C01Principal/b.pdf", "role": "anexo"},
                {"file": "otra/carpeta/c.pdf", "role": "anexo"},
            ],
        }
    ]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela"), ("b.pdf", "anexo"), ("c.pdf", "anexo")])}
    r = comparar(verdad, ing, {"C": []})
    assert r["n_docs"] == 3 and r["sin_pareja"] == []


def test_dos_documentos_con_el_mismo_nombre_no_se_emparejan_a_ciegas():
    verdad = [{"case": "C", "docs": [{"file": "x/a.pdf", "role": "anexo"}]}]
    d1, d2 = doc_de(1, "a.pdf", "anexo"), doc_de(2, "a.pdf", "anexo")
    d1.ruta, d2.ruta = "p/a.pdf", "q/a.pdf"
    r = comparar(verdad, {"C": Ingesta(documentos=[d1, d2])}, {})
    assert r["n_docs"] == 0 and len(r["sin_pareja"]) == 3


def test_por_umbral_baja_la_cobertura_al_subir_el_umbral():
    nombres = [f"{i}.pdf" for i in range(6)]
    verdad = [verdad_de("C", *[(n, "anexo") for n in nombres])]
    ing = {"C": ingesta_con([(n, "anexo") for n in nombres])}
    confianzas = [0.55, 0.75, 0.85, 0.92, 0.96, 0.995]
    r = comparar(verdad, ing, {"C": [op(i, "anexo", c) for i, c in enumerate(confianzas, 1)]})
    u = r["por_umbral"]
    assert set(u) == set(UMBRALES)
    assert u[0.99]["cobertura"] <= u[0.9]["cobertura"] <= u[0.5]["cobertura"]
    assert [u[x]["cobertura"] for x in UMBRALES] == pytest.approx([6 / 6, 5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6])
    assert all(u[x]["exactitud"] == 1.0 for x in UMBRALES)


def test_por_umbral_cuenta_rescates_y_falsos_rellenos_y_elige_el_umbral_minimo():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"), ("b.pdf", "memorial"))]
    ing = {"C": ingesta_con([("a.pdf", "otro"), ("b.pdf", "otro")])}
    r = comparar(verdad, ing, {"C": [op(1, "escrito_tutela", 0.92), op(2, "contestacion", 0.6)]})
    u = r["por_umbral"]
    assert (u[0.5]["rescates"], u[0.5]["falsos_rellenos"]) == (1, 1)
    assert (u[0.7]["rescates"], u[0.7]["falsos_rellenos"]) == (1, 0)
    assert (u[0.95]["rescates"], u[0.95]["falsos_rellenos"]) == (0, 0)
    assert r["umbral_relleno"] == 0.7


def test_sin_rescates_no_hay_umbral_para_relleno():
    verdad = [verdad_de("C", ("a.pdf", "escrito_tutela"))]
    ing = {"C": ingesta_con([("a.pdf", "escrito_tutela")])}
    r = comparar(verdad, ing, {"C": [op(1, "escrito_tutela", 0.99)]})
    assert r["umbral_relleno"] is None


def sintetica(tmp_path: Path, con_ausente: bool = True) -> Path:
    ref = tmp_path / "referencia"
    primera = ref / "casos" / "CASO1" / "01PrimeraInstancia" / "C01Principal"
    primera.mkdir(parents=True)
    (primera / "001Escrito.txt").write_text(ESCRITO, encoding="utf-8")
    (primera / "002Nota.txt").write_text(NOTA, encoding="utf-8")
    (ref / "analisis").mkdir()
    verdad = [
        verdad_de("CASO1", ("001Escrito.txt", "escrito_tutela"), ("002Nota.txt", "contestacion")),
    ]
    if con_ausente:
        verdad.append(verdad_de("CASO2", ("003.pdf", "anexo")))
    (ref / "analisis" / "ground_truth_1a.json").write_text(json.dumps(verdad), encoding="utf-8")
    return ref


def agregar(ref: Path, nombre: str, texto: str, rol: str) -> None:
    (ref / "casos" / "CASO1" / "01PrimeraInstancia" / "C01Principal" / nombre).write_text(texto, encoding="utf-8")
    ruta = ref / "analisis" / "ground_truth_1a.json"
    verdad = json.loads(ruta.read_text(encoding="utf-8"))
    verdad[0]["docs"].append({"file": PREFIJO + nombre, "role": rol, "confidence": "high", "evidence": "x"})
    ruta.write_text(json.dumps(verdad), encoding="utf-8")


def agregar_verdad(ref: Path, nombre: str, rol: str) -> None:
    ruta = ref / "analisis" / "ground_truth_1a.json"
    verdad = json.loads(ruta.read_text(encoding="utf-8"))
    verdad[0]["docs"].append({"file": PREFIJO + nombre, "role": rol, "confidence": "high", "evidence": "x"})
    ruta.write_text(json.dumps(verdad), encoding="utf-8")


def respuesta(rol: str, confianza: float = 0.97) -> dict:
    return {"rol": {"type": "choice", "choice": rol, "confidence": confianza, "probabilities": {rol: confianza}}}


def por_nombre(rol_por_nombre: dict[str, str], confianza: float = 0.97):
    def f(estado, preguntas):
        nombre = estado.split("\n", 1)[0].removeprefix("Nombre del archivo: ")
        return respuesta(rol_por_nombre[nombre], confianza)

    return f


def listado(base: Path) -> list[str]:
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*"))


def test_correr_ingiere_en_forma_a_y_compara_contra_la_verdad(tmp_path):
    ref = sintetica(tmp_path, con_ausente=False)
    antes = listado(ref)
    fake = FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"}))
    r = correr(ref, fake, CFG)
    assert r["n_docs"] == 2 and r["sin_pareja"] == [] and r["casos_ausentes"] == []
    assert r["exactitud_codigo"] == pytest.approx(0.5) and r["exactitud_jev"] == 1.0
    assert [x["archivo"] for x in r["rescates"]] == [PREFIJO + "002Nota.txt"]
    assert r["falsos_rellenos"] == [] and r["completo"] is True and r["umbral_relleno"] == 0.5
    assert len(fake.llamadas) == 2
    assert listado(ref) == antes
    json.dumps(r)


def test_caso_sin_carpeta_se_informa_y_la_corrida_queda_incompleta(tmp_path):
    ref = sintetica(tmp_path)
    r = correr(ref, FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"})), CFG)
    assert r["casos_ausentes"] == ["CASO2"] and r["sin_pareja"] == [PREFIJO + "003.pdf"]
    assert r["n_verdad_sin_pareja"] == 1
    assert r["completo"] is False and r["umbral_relleno"] is None
    assert "no se puede certificar" in informe_markdown(r)


def test_un_fallo_de_jev_a_mitad_de_caso_no_certifica_el_umbral(tmp_path):
    ref = sintetica(tmp_path, con_ausente=False)
    agregar(ref, "003Otra.txt", NOTA + " Otra.", "anexo")
    respuestas = por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"})

    def falla_en_la_tercera(estado, preguntas):
        if "003Otra.txt" in estado:
            raise ErrorJev("429")
        return respuestas(estado, preguntas)

    cfg = Config(ocr=False, jev=JevConfig(modo="sombra", concurrencia=1))
    r = correr(ref, FakeJev(falla_en_la_tercera), cfg)
    assert r["por_umbral"][0.5]["rescates"] == 1 and r["por_umbral"][0.5]["falsos_rellenos"] == 0
    assert r["sin_opinion"]["CASO1"]["sin_respuesta"] == 1
    assert r["completo"] is False and r["umbral_relleno"] is None
    texto = informe_markdown(r)
    assert "no se puede certificar" in texto and "Umbral más bajo" not in texto


def test_archivos_que_la_ingesta_no_lee_no_impiden_certificar_el_umbral(tmp_path):
    ref = sintetica(tmp_path, con_ausente=False)
    agregar_verdad(ref, "000IndiceElectronico.xlsm", "indice")
    agregar_verdad(ref, "010Video.mp4", "nuevo:anexo")
    fake = FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"}))
    r = correr(ref, fake, CFG)
    assert r["no_legibles"] == [PREFIJO + "000IndiceElectronico.xlsm", PREFIJO + "010Video.mp4"]
    assert r["sin_pareja"] == [] and r["n_verdad_sin_pareja"] == 0
    assert r["completo"] is True and r["umbral_relleno"] == 0.5
    texto = informe_markdown(r)
    assert "000IndiceElectronico.xlsm" in texto and "no se puede certificar" not in texto


def test_un_pdf_de_la_verdad_sin_pareja_sigue_invalidando_la_corrida(tmp_path):
    ref = sintetica(tmp_path, con_ausente=False)
    agregar_verdad(ref, "000IndiceElectronico.xlsm", "indice")
    agregar_verdad(ref, "099Falta.PDF", "anexo")
    r = correr(ref, FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"})), CFG)
    assert r["sin_pareja"] == [PREFIJO + "099Falta.PDF"] and r["completo"] is False and r["umbral_relleno"] is None


def test_la_ingesta_del_benchmark_va_con_jev_apagado(tmp_path, monkeypatch):
    ref = sintetica(tmp_path)
    vistos = []
    real = jev_bench.ingerir

    def espia(caso_dir, cfg, *args, **kwargs):
        vistos.append(cfg.jev.modo)
        return real(caso_dir, cfg, *args, **kwargs)

    monkeypatch.setattr(jev_bench, "ingerir", espia)
    cfg = Config(ocr=False, jev=JevConfig(modo="relleno"))
    correr(ref, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})), cfg)
    assert vistos == ["apagado"] and cfg.jev.modo == "relleno"


def test_correr_mide_latencia_y_tokens(tmp_path):
    ref = sintetica(tmp_path)
    r = correr(ref, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})), CFG)
    assert r["latencia_s"]["n"] == 2
    assert 0 <= r["latencia_s"]["p50"] <= r["latencia_s"]["p95"]
    assert r["tokens"]["entrada"] > 0 and r["tokens"]["salida"] > 0
    assert r["modelos"] == ["jev-fake"]


def test_correr_con_jev_caido_informa_sin_excepcion_y_sin_respuesta(tmp_path):
    ref = sintetica(tmp_path)

    def cae(estado, preguntas):
        raise ErrorJev("429")

    r = correr(ref, FakeJev(cae), Config(ocr=False, jev=JevConfig(modo="sombra", concurrencia=1)))
    assert r["n_con_jev"] == 0 and r["exactitud_jev"] is None
    assert r["sin_opinion"]["CASO1"]["sin_respuesta"] == 2
    assert any("CASO1" in a and "Jev" in a for a in r["alertas"])


def test_invertir_mide_cuantas_etiquetas_cambian(tmp_path):
    ref = sintetica(tmp_path)

    def primera_opcion(estado, preguntas):
        return respuesta(next(iter(preguntas["rol"]["criteria"])), 0.9)

    fake = FakeJev(primera_opcion)
    r = correr(ref, fake, CFG, invertir=True)
    assert len(fake.llamadas) == 4
    assert r["inversion"]["comparables"] == 2 and r["inversion"]["cambian"] == 2
    assert {c["directo"] for c in r["inversion"]["cambios"]} == {ROLES_JEV[0]}
    assert {c["invertido"] for c in r["inversion"]["cambios"]} == {ROLES_JEV[-1]}
    assert r["inversion"]["exactitud_jev"] == 0.0
    assert r["latencia_s"]["n"] == 4


def test_sin_invertir_no_hay_seccion_de_inversion(tmp_path):
    ref = sintetica(tmp_path)
    r = correr(ref, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})), CFG)
    assert r["inversion"] is None


def test_informe_markdown_resume_la_decision(tmp_path):
    ref = sintetica(tmp_path)
    fake = FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"}))
    texto = informe_markdown(correr(ref, fake, CFG, invertir=True))
    for esperado in ("# Benchmark de roles de Jev", "## Por umbral", "## Rescates", "## Falsos rellenos", "## Orden invertido"):
        assert esperado in texto
    assert "002Nota.txt" in texto and "umbral" in texto.lower()


def test_informe_markdown_sin_umbral_recomienda_sombra(tmp_path):
    ref = sintetica(tmp_path)
    fake = FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "otro"}))
    assert "`sombra`" in informe_markdown(correr(ref, fake, CFG))


def fijar_cliente(monkeypatch, fake: FakeJev) -> None:
    monkeypatch.setenv("JEV_API_KEY", "x")
    monkeypatch.setattr(cli, "HttpJev", lambda clave, timeout_s: fake)


def test_cli_escribe_el_informe_en_salida(tmp_path, monkeypatch, capsys):
    ref = sintetica(tmp_path)
    fijar_cliente(monkeypatch, FakeJev(por_nombre({"001Escrito.txt": "escrito_tutela", "002Nota.txt": "contestacion"})))
    salida = tmp_path / "fuera" / "informe.md"
    assert cli.main(["jev-bench", "--referencia", str(ref), "--salida", str(salida)]) == 0
    assert salida.read_text(encoding="utf-8").startswith("# Benchmark de roles de Jev")
    assert "002Nota.txt" not in capsys.readouterr().out


def test_cli_sin_salida_imprime_el_informe(tmp_path, monkeypatch, capsys):
    ref = sintetica(tmp_path)
    fijar_cliente(monkeypatch, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})))
    assert cli.main(["jev-bench", "--referencia", str(ref), "--invertir"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Benchmark de roles de Jev") and "## Orden invertido" in out


def test_cli_rechaza_una_salida_dentro_del_repositorio(tmp_path, monkeypatch):
    ref = sintetica(tmp_path)
    fijar_cliente(monkeypatch, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(cli, "RAIZ_REPO", repo)
    salida = repo / "informes" / "jev.md"
    with pytest.raises(SystemExit) as e:
        cli.main(["jev-bench", "--referencia", str(ref), "--salida", str(salida)])
    assert e.value.code == 2 and not salida.exists() and not salida.parent.exists()


def test_cli_acepta_una_salida_fuera_del_repositorio(tmp_path, monkeypatch):
    ref = sintetica(tmp_path)
    fijar_cliente(monkeypatch, FakeJev(por_nombre({"001Escrito.txt": "otro", "002Nota.txt": "otro"})))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(cli, "RAIZ_REPO", repo)
    salida = tmp_path / "fuera" / "jev.md"
    assert cli.main(["jev-bench", "--referencia", str(ref), "--salida", str(salida)]) == 0
    assert salida.is_file()


def test_cli_exige_referencia_y_clave(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["jev-bench"])
    assert e.value.code == 2
    ref = sintetica(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(["jev-bench", "--referencia", str(ref)])
    assert e.value.code == 2


def test_cli_referencia_sin_verdad_falla_con_mensaje(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "x")
    with pytest.raises(SystemExit) as e:
        cli.main(["jev-bench", "--referencia", str(tmp_path)])
    assert e.value.code == 2
