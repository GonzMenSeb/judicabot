from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_ingest import CUI, FALLO, OTRO_CUI, P1, caso_sintetico, escribir, pdf_en_blanco, por_nombre

from tutela2 import api, graph, ingest
from tutela2.clasificar import EVIDENCIA_SIN_ROL, EVIDENCIA_SIN_TEXTO
from tutela2.config import Config, JevConfig, LLMConfig
from tutela2.jev import ErrorJev, FakeJev
from tutela2.jev_roles import EVIDENCIA_JEV, OpinionRol, aplicar, rellenable
from tutela2.models import Doc, Ingesta, Pagina

TEXTO_SIN_RASGOS = "Lorem ipsum dolor sit amet consectetur adipiscing elit."
APAGADO = Config()
SOMBRA = Config(jev=JevConfig(modo="sombra"))
RELLENO = Config(jev=JevConfig(modo="relleno"))


def choice(rol: str, confianza: float = 0.97) -> dict:
    return {"rol": {"type": "choice", "choice": rol, "confidence": confianza, "probabilities": {rol: confianza}}}


def lanza(error: Exception):
    def f(estado, preguntas):
        raise error

    return f


def carpeta_con(base: Path, *archivos: tuple[str, str]) -> Path:
    for nombre, texto in archivos:
        escribir(base, P1 + nombre, texto)
    return base


def doc_de(
    doc_id: str = "1a-001",
    rol: str = "otro",
    evidencia: str = EVIDENCIA_SIN_ROL,
    rol_origen: str = "contenido",
) -> Doc:
    return Doc(
        doc_id=doc_id,
        ruta=f"{doc_id}.txt",
        nombre=f"{doc_id}.txt",
        instancia="1a",
        rol=rol,
        sha256=doc_id,
        paginas=[Pagina(n=1, texto=TEXTO_SIN_RASGOS)],
        evidencia=evidencia,
        rol_origen=rol_origen,
    )


def opinion(doc: Doc, rol: str, confianza: float = 0.97) -> OpinionRol:
    return OpinionRol(doc.doc_id, rol, confianza, {rol: confianza}, {})


def test_los_textos_de_prueba_se_clasifican_como_se_espera(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", FALLO))
    ing = ingest.ingerir(caso, APAGADO)
    assert (por_nombre(ing, "doc01.txt").rol, por_nombre(ing, "doc01.txt").evidencia) == ("otro", EVIDENCIA_SIN_ROL)
    assert por_nombre(ing, "doc02.txt").rol == "fallo_a_quo"
    assert all(d.jev_rol is None and d.jev_confianza is None and d.jev_probabilidades == {} for d in ing.documentos)
    assert all(d.jev_umbral is None for d in ing.documentos)
    assert ing.llamadas_jev == []


def test_relleno_asigna_rol_solo_a_documentos_sin_rasgos(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", FALLO))
    fake = FakeJev(choice("escrito_tutela", 0.97))
    ing = ingest.ingerir(caso, RELLENO, jev=fake)
    vacio = por_nombre(ing, "doc01.txt")
    assert (vacio.rol, vacio.rol_origen) == ("escrito_tutela", "jev")
    assert vacio.evidencia == EVIDENCIA_JEV
    fallo = por_nombre(ing, "doc02.txt")
    assert (fallo.rol, fallo.rol_origen) == ("fallo_a_quo", "contenido")


def test_sombra_nunca_cambia_el_rol_y_alerta_la_discrepancia(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", FALLO))
    fake = FakeJev(choice("impugnacion", 0.98))
    ing = ingest.ingerir(caso, SOMBRA, jev=fake)
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen) == ("fallo_a_quo", "contenido")
    assert any("impugnacion" in a for a in ing.alertas_lectura)
    assert all(a in ing.alertas for a in ing.alertas_lectura)


def test_sombra_no_rellena_ni_siquiera_un_documento_sin_rasgos(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, SOMBRA, jev=FakeJev(choice("escrito_tutela", 0.99)))
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen, d.evidencia) == ("otro", "contenido", EVIDENCIA_SIN_ROL)
    assert (d.jev_rol, d.jev_confianza) == ("escrito_tutela", 0.99)
    assert any("escrito_tutela" in a for a in ing.alertas_lectura)


def test_relleno_no_pisa_un_rol_decidido_por_el_codigo(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", FALLO))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("escrito_tutela", 0.99)))
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen) == ("fallo_a_quo", "contenido")
    assert any("escrito_tutela" in a for a in ing.alertas_lectura)


def test_relleno_respeta_el_umbral(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("escrito_tutela", 0.5)))
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen, d.evidencia) == ("otro", "contenido", EVIDENCIA_SIN_ROL)
    assert (d.jev_rol, d.jev_confianza) == ("escrito_tutela", 0.5)
    assert ing.alertas_lectura == []


def test_relleno_no_asigna_si_jev_tambien_dice_otro(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("otro", 0.99)))
    d = ing.documentos[0]
    assert (d.rol, d.rol_origen, d.jev_rol) == ("otro", "contenido", "otro")
    assert ing.alertas_lectura == []


def test_rol_fijado_por_el_usuario_no_se_toca_aunque_jev_discrepe():
    doc = doc_de(rol="otro", rol_origen="usuario", evidencia=EVIDENCIA_SIN_ROL)
    aplicar([doc], [opinion(doc, "escrito_tutela", 0.99)], RELLENO)
    assert (doc.rol, doc.rol_origen) == ("otro", "usuario")


@pytest.mark.parametrize("origen", ["usuario", "jev"])
def test_relleno_solo_toca_documentos_con_origen_contenido(origen):
    doc = doc_de(rol="otro", rol_origen=origen)
    aplicar([doc], [opinion(doc, "escrito_tutela", 0.99)], RELLENO)
    assert (doc.rol, doc.rol_origen, doc.evidencia) == ("otro", origen, EVIDENCIA_SIN_ROL)


def test_ingesta_termina_si_jev_falla(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", FALLO))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(lanza(ErrorJev("401"))))
    assert len(ing.documentos) == 2
    assert len([a for a in ing.alertas_lectura if "Jev" in a]) == 1
    assert all(d.jev_rol is None and d.jev_confianza is None and d.jev_probabilidades == {} for d in ing.documentos)
    assert por_nombre(ing, "doc01.txt").rol == "otro" and ing.llamadas_jev == []


def test_modo_apagado_no_hace_peticiones(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    fake = FakeJev(choice("otro", 0.99))
    ing = ingest.ingerir(caso, APAGADO, jev=fake)
    assert fake.llamadas == []
    assert ing.documentos[0].jev_rol is None and ing.llamadas_jev == []


def test_sin_cliente_inyectado_usa_cliente_jev_de_la_configuracion(tmp_path, monkeypatch):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    fake = FakeJev(choice("escrito_tutela", 0.97))
    pedidos: list[Config] = []

    def cliente(cfg):
        pedidos.append(cfg)
        return fake

    monkeypatch.setattr(ingest, "cliente_jev", cliente)
    ing = ingest.ingerir(caso, RELLENO)
    assert len(pedidos) == 1 and len(fake.llamadas) == 1
    assert ing.documentos[0].rol_origen == "jev"


def test_sin_clave_ni_cliente_la_ingesta_sigue_sin_alertas_de_jev(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO)
    assert ing.documentos[0].rol == "otro" and ing.llamadas_jev == []
    assert not any("Jev" in a for a in ing.alertas)


def test_documento_sin_texto_no_se_consulta(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    pdf_en_blanco(caso / "insumos" / P1 / "doc02.pdf")
    fake = FakeJev(choice("escrito_tutela", 0.97))
    ing = ingest.ingerir(caso, Config(ocr=False, jev=JevConfig(modo="relleno")), jev=fake)
    assert len(fake.llamadas) == 1
    blanco = por_nombre(ing, "doc02.pdf")
    assert blanco.evidencia == EVIDENCIA_SIN_TEXTO and blanco.jev_rol is None and blanco.rol_origen == "contenido"


def test_opinion_de_jev_queda_en_el_documento_aunque_el_rol_no_cambie(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", FALLO))
    for cfg in (SOMBRA, RELLENO):
        ing = ingest.ingerir(caso, cfg, jev=FakeJev(choice("fallo_a_quo", 0.93)))
        d = ing.documentos[0]
        assert (d.rol, d.rol_origen) == ("fallo_a_quo", "contenido")
        assert (d.jev_rol, d.jev_confianza, d.jev_probabilidades) == ("fallo_a_quo", 0.93, {"fallo_a_quo": 0.93})
        assert ing.alertas_lectura == []


def test_opinion_de_baja_confianza_tambien_se_guarda_sin_alerta():
    doc = doc_de(rol="fallo_a_quo", evidencia="RESUELVE")
    alertas = aplicar([doc], [opinion(doc, "impugnacion", 0.4)], SOMBRA)
    assert alertas == [] and (doc.jev_rol, doc.jev_confianza) == ("impugnacion", 0.4)


def test_relleno_asignado_conserva_la_opinion_y_la_confianza():
    doc = doc_de()
    op = OpinionRol(doc.doc_id, "escrito_tutela", 0.956, {"escrito_tutela": 0.956, "otro": 0.03}, {})
    assert aplicar([doc], [op], RELLENO) == []
    assert (doc.rol, doc.rol_origen, doc.evidencia) == ("escrito_tutela", "jev", EVIDENCIA_JEV)
    assert (doc.jev_rol, doc.jev_confianza) == ("escrito_tutela", 0.956)
    assert doc.jev_probabilidades == {"escrito_tutela": 0.956, "otro": 0.03}


def test_aplicar_guarda_el_umbral_con_que_se_aplico_la_opinion():
    sobre, bajo, sin_opinion = doc_de("1a-001"), doc_de("1a-002"), doc_de("1a-003")
    cfg = Config(jev=JevConfig(modo="relleno", umbral_confianza=0.8))
    aplicar([sobre, bajo, sin_opinion], [opinion(sobre, "escrito_tutela", 0.95), opinion(bajo, "anexo", 0.5)], cfg)
    assert (sobre.jev_umbral, bajo.jev_umbral, sin_opinion.jev_umbral) == (0.8, 0.8, None)
    aplicar([sobre], [opinion(sobre, "escrito_tutela", 0.95)], Config(jev=JevConfig(modo="sombra", umbral_confianza=0.99)))
    assert sobre.jev_umbral == 0.99


def test_el_umbral_aplicado_sobrevive_a_la_reingesta_aunque_cambie_la_configuracion(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, Config(jev=JevConfig(modo="relleno", umbral_confianza=0.9)), jev=FakeJev(choice("escrito_tutela", 0.92)))
    nuevo = ingest.reaplicar(ing, {})
    leida = Ingesta.model_validate_json(nuevo.model_dump_json())
    assert leida.documentos[0].jev_umbral == 0.9 and leida.documentos[0].rol_origen == "jev"


def test_aplicar_no_comparte_el_diccionario_de_probabilidades():
    doc = doc_de()
    op = opinion(doc, "escrito_tutela")
    aplicar([doc], [op], SOMBRA)
    doc.jev_probabilidades["otro"] = 1.0
    assert op.probabilidades == {"escrito_tutela": 0.97}


def test_aplicar_apagado_no_toca_nada():
    doc = doc_de()
    assert aplicar([doc], [opinion(doc, "escrito_tutela", 0.99)], APAGADO) == []
    assert (doc.rol, doc.rol_origen, doc.jev_rol, doc.jev_confianza) == ("otro", "contenido", None, None)


@pytest.mark.parametrize("evidencia", [EVIDENCIA_SIN_TEXTO, EVIDENCIA_SIN_ROL])
def test_relleno_acepta_las_dos_evidencias_de_falta_de_rasgos(evidencia):
    doc = doc_de(evidencia=evidencia)
    aplicar([doc], [opinion(doc, "contestacion", 0.95)], RELLENO)
    assert (doc.rol, doc.rol_origen) == ("contestacion", "jev")


def test_relleno_no_rellena_un_otro_con_otra_evidencia():
    doc = doc_de(evidencia="Sentencia de otro radicado (05001408803320270000100).")
    alertas = aplicar([doc], [opinion(doc, "fallo_a_quo", 0.99)], RELLENO)
    assert (doc.rol, doc.rol_origen) == ("otro", "contenido")
    assert len(alertas) == 1 and "fallo_a_quo" in alertas[0]


def test_umbral_es_inclusivo():
    justo, debajo = doc_de("1a-001"), doc_de("1a-002")
    cfg = Config(jev=JevConfig(modo="relleno", umbral_confianza=0.9))
    aplicar([justo, debajo], [opinion(justo, "escrito_tutela", 0.9), opinion(debajo, "escrito_tutela", 0.89)], cfg)
    assert justo.rol == "escrito_tutela" and debajo.rol == "otro"


def test_alerta_de_discrepancia_nombra_documento_etiqueta_y_confianza():
    doc = doc_de("1a-004", rol="fallo_a_quo", evidencia="RESUELVE")
    [alerta] = aplicar([doc], [opinion(doc, "impugnacion", 0.98)], SOMBRA)
    assert "1a-004" in alerta and "Jev" in alerta and "impugnacion" in alerta and "fallo_a_quo" in alerta and "0.98" in alerta


def test_relleno_alerta_las_discrepancias_que_no_resuelve():
    lleno, discrepante, igual = doc_de("1a-001"), doc_de("1a-002", rol="fallo_a_quo", evidencia="x"), doc_de("1a-003", rol="anexo", evidencia="x")
    alertas = aplicar(
        [lleno, discrepante, igual],
        [opinion(lleno, "escrito_tutela"), opinion(discrepante, "impugnacion"), opinion(igual, "anexo")],
        RELLENO,
    )
    assert lleno.rol == "escrito_tutela" and discrepante.rol == "fallo_a_quo"
    assert len(alertas) == 1 and "1a-002" in alertas[0]


def test_aplicar_ignora_opiniones_de_documentos_desconocidos():
    doc = doc_de()
    assert aplicar([doc], [OpinionRol("1a-999", "escrito_tutela", 0.99, {}, {})], RELLENO) == []
    assert doc.rol == "otro" and doc.jev_rol is None


def test_llamadas_de_jev_quedan_en_la_ingesta_sin_texto_del_expediente(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", FALLO))
    ing = ingest.ingerir(caso, SOMBRA, jev=FakeJev(choice("otro", 0.9)))
    assert len(ing.llamadas_jev) == 2
    assert all(c["proveedor"] == "jev" and c["nodo"] == "roles" for c in ing.llamadas_jev)
    volcado = json.dumps(ing.llamadas_jev)
    assert "Lorem" not in volcado and "TREINTA Y TRES" not in volcado


def test_relleno_no_toma_el_rol_unico_que_ya_tiene_otro_documento(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", FALLO), ("doc02.txt", TEXTO_SIN_RASGOS))

    def responde(estado, preguntas):
        return choice("fallo_a_quo" if "Lorem" in estado else "otro", 0.99)

    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(responde))
    real, nota = por_nombre(ing, "doc01.txt"), por_nombre(ing, "doc02.txt")
    assert (real.rol, real.rol_origen) == ("fallo_a_quo", "contenido")
    assert (nota.rol, nota.rol_origen, nota.evidencia) == ("otro", "contenido", EVIDENCIA_SIN_ROL)
    assert (nota.jev_rol, nota.jev_confianza) == ("fallo_a_quo", 0.99)
    assert any("doc02.txt" in a and "fallo_a_quo" in a for a in ing.alertas_lectura)


def extra(base: Path, nombre: str, texto: str) -> None:
    escribir(base, P1 + nombre, texto)


def por_nombre_jev(roles: dict[str, str], confianza: float = 0.97, resto: tuple[str, float] = ("otro", 0.1)):
    def f(estado, preguntas):
        nombre = estado.split("\n", 1)[0].removeprefix("Nombre del archivo: ")
        rol, c = (roles[nombre], confianza) if nombre in roles else resto
        return choice(rol, c)

    return f


def test_relleno_no_le_quita_el_acta_2a_al_acta_que_el_codigo_clasifico(tmp_path):
    caso_sintetico(tmp_path)
    extra(tmp_path, "020Nota.txt", TEXTO_SIN_RASGOS)
    base = ingest.ingerir(tmp_path, APAGADO)
    acta_base = por_nombre(base, "008Acta.txt")
    assert acta_base.rol == "acta_reparto_2a" and base.metadatos.fechas.reparto_2a is not None

    ing = ingest.ingerir(tmp_path, RELLENO, jev=FakeJev(por_nombre_jev({"020Nota.txt": "acta_reparto_2a"})))
    acta, nota = por_nombre(ing, "008Acta.txt"), por_nombre(ing, "020Nota.txt")
    assert (acta.rol, acta.rol_origen, acta.evidencia) == ("acta_reparto_2a", "contenido", acta_base.evidencia)
    assert (nota.rol, nota.rol_origen, nota.evidencia) == ("otro", "contenido", EVIDENCIA_SIN_ROL)
    assert (nota.jev_rol, nota.jev_confianza) == ("acta_reparto_2a", 0.97)
    assert ing.metadatos.fechas == base.metadatos.fechas
    assert ing.esperados_faltantes == base.esperados_faltantes
    assert any("020Nota.txt" in a and "acta_reparto_2a" in a for a in ing.alertas_lectura)


def test_relleno_no_le_quita_el_fallo_al_documento_que_el_codigo_clasifico(tmp_path):
    caso_sintetico(tmp_path)
    informe = f"JUZGADO TREINTA Y TRES PENAL MUNICIPAL\nRadicado {CUI}\n" + "\f".join(["informe interno sin rasgos"] * 10)
    extra(tmp_path, "020Informe.txt", informe)
    base = ingest.ingerir(tmp_path, APAGADO)
    assert (por_nombre(base, "020Informe.txt").rol, por_nombre(base, "004Fallo.txt").rol) == ("otro", "fallo_a_quo")

    ing = ingest.ingerir(tmp_path, RELLENO, jev=FakeJev(por_nombre_jev({"020Informe.txt": "fallo_a_quo"}, 0.95)))
    fallo, informe_doc = por_nombre(ing, "004Fallo.txt"), por_nombre(ing, "020Informe.txt")
    assert (fallo.rol, fallo.rol_origen, fallo.evidencia) == ("fallo_a_quo", "contenido", por_nombre(base, "004Fallo.txt").evidencia)
    assert (informe_doc.rol, informe_doc.rol_origen) == ("otro", "contenido")
    assert ing.faltantes == base.faltantes == []
    assert ing.metadatos == base.metadatos
    assert not any("más de un documento" in a for a in ing.alertas)


def test_correccion_del_usuario_sobre_un_relleno_no_deja_al_caso_sin_fallo(caso_jev):
    caso_sintetico(caso_jev.carpeta)
    informe = f"JUZGADO TREINTA Y TRES PENAL MUNICIPAL\nRadicado {CUI}\n" + "\f".join(["informe interno sin rasgos"] * 10)
    extra(caso_jev.carpeta, "020Informe.txt", informe)
    caso_jev.monkeypatch.setattr(ingest, "cliente_jev", lambda cfg: FakeJev(por_nombre_jev({"020Informe.txt": "fallo_a_quo"}, 0.95)))

    def docs():
        return {d.nombre: d for d in Ingesta.model_validate_json((caso_jev.carpeta / "caso.json").read_text(encoding="utf-8")).documentos}

    assert api.nuevo(caso_jev.carpeta)["ok"]
    assert docs()["004Fallo.txt"].rol == "fallo_a_quo" and docs()["020Informe.txt"].rol == "otro"
    r = api.revisar(caso_jev.carpeta, {docs()["020Informe.txt"].doc_id: "otro"}, None)
    assert r["ok"], r["error"]
    assert api.nuevo(caso_jev.carpeta)["ok"]
    ing = Ingesta.model_validate_json((caso_jev.carpeta / "caso.json").read_text(encoding="utf-8"))
    assert ing.faltantes == []
    assert docs()["004Fallo.txt"].rol == "fallo_a_quo"


def test_relleno_no_acepta_como_fallo_un_documento_de_otro_radicado(tmp_path):
    caso_sintetico(tmp_path)
    (tmp_path / "insumos" / P1 / "004Fallo.txt").unlink()
    base = ingest.ingerir(tmp_path, APAGADO)
    ajeno = por_nombre(base, "030Ajeno.txt")
    assert (ajeno.rol, ajeno.evidencia) == ("otro", EVIDENCIA_SIN_ROL) and "fallo_a_quo" in base.faltantes

    ing = ingest.ingerir(tmp_path, RELLENO, jev=FakeJev(por_nombre_jev({"030Ajeno.txt": "fallo_a_quo"})))
    ajeno = por_nombre(ing, "030Ajeno.txt")
    assert (ajeno.rol, ajeno.rol_origen) == ("otro", "contenido") and OTRO_CUI in ajeno.evidencia
    assert (ajeno.jev_rol, ajeno.jev_confianza) == ("fallo_a_quo", 0.97)
    assert "fallo_a_quo" in ing.faltantes


def test_relleno_asigna_un_rol_unico_si_nadie_lo_tiene(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("fallo_a_quo", 0.97)))
    assert (ing.documentos[0].rol, ing.documentos[0].rol_origen) == ("fallo_a_quo", "jev")


def test_dos_rellenos_del_mismo_rol_unico_solo_aplican_el_primero(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", TEXTO_SIN_RASGOS + " Otra."))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("acta_reparto_2a", 0.97)))
    primero, segundo = por_nombre(ing, "doc01.txt"), por_nombre(ing, "doc02.txt")
    assert (primero.rol, primero.rol_origen) == ("acta_reparto_2a", "jev")
    assert (segundo.rol, segundo.rol_origen) == ("otro", "contenido")
    assert any("doc02.txt" in a for a in ing.alertas_lectura)


def test_rellenable_rechaza_un_rol_unico_ocupado_pero_no_uno_repetible():
    ocupado, vacio = doc_de("1a-001", rol="fallo_a_quo", evidencia="RESUELVE"), doc_de("1a-002")
    assert not rellenable(vacio, opinion(vacio, "fallo_a_quo"), [ocupado, vacio])
    assert not rellenable(vacio, opinion(vacio, "acta_reparto_2a"), [doc_de("1a-003", rol="acta_reparto_2a", evidencia="x"), vacio])
    assert rellenable(vacio, opinion(vacio, "escrito_tutela"), [doc_de("1a-003", rol="escrito_tutela", evidencia="x"), vacio])
    assert rellenable(vacio, opinion(vacio, "fallo_a_quo"), [vacio])
    assert not rellenable(vacio, opinion(vacio, "otro"), [vacio])


def test_aplicar_conserva_el_rol_unico_del_codigo_y_alerta():
    fallo, nota = doc_de("1a-001", rol="fallo_a_quo", evidencia="RESUELVE"), doc_de("1a-002")
    alertas = aplicar([fallo, nota], [opinion(nota, "fallo_a_quo", 0.99)], RELLENO)
    assert (fallo.rol, nota.rol, nota.rol_origen) == ("fallo_a_quo", "otro", "contenido")
    assert len(alertas) == 1 and "1a-002" in alertas[0] and "fallo_a_quo" in alertas[0]


def copia_del_fallo(base: Path) -> None:
    caso_sintetico(base)
    extra(base, "012FalloCopia.txt", FALLO)


def test_alerta_de_sombra_se_calcula_contra_el_rol_final(tmp_path):
    copia_del_fallo(tmp_path)
    ing = ingest.ingerir(tmp_path, SOMBRA, jev=FakeJev(por_nombre_jev({"012FalloCopia.txt": "otro"}, 0.95)))
    copia = por_nombre(ing, "012FalloCopia.txt")
    assert (copia.rol, copia.jev_rol) == ("otro", "otro")
    assert not any("012FalloCopia.txt" in a and "Jev sugiere" in a for a in ing.alertas)


def test_alerta_de_sombra_aparece_si_jev_discrepa_del_rol_final(tmp_path):
    copia_del_fallo(tmp_path)
    ing = ingest.ingerir(tmp_path, SOMBRA, jev=FakeJev(por_nombre_jev({"012FalloCopia.txt": "fallo_a_quo"}, 0.95)))
    copia = por_nombre(ing, "012FalloCopia.txt")
    assert copia.rol == "otro" and copia.jev_rol == "fallo_a_quo"
    [alerta] = [a for a in ing.alertas_lectura if "012FalloCopia.txt" in a]
    assert "fallo_a_quo" in alerta and "quedó como otro" in alerta


def test_respuestas_descartadas_de_jev_quedan_en_la_bitacora(tmp_path):
    caso = carpeta_con(tmp_path, *[(f"doc0{i}.txt", TEXTO_SIN_RASGOS + f" {i}") for i in range(1, 5)])
    fake = FakeJev({"rol": {"type": "choice", "choice": "inventado", "confidence": 0.99}})
    ing = ingest.ingerir(caso, SOMBRA, jev=fake)
    assert len(fake.llamadas) == 4 and len(ing.llamadas_jev) == 4
    assert graph.estado_inicial(Path("."), SOMBRA, ing)["bitacora"] == ing.llamadas_jev
    assert all(c["proveedor"] == "jev" and c["error"] is None for c in ing.llamadas_jev)
    assert "Lorem" not in json.dumps(ing.llamadas_jev)


def test_peticion_fallida_tras_el_envio_queda_como_llamada_con_error(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    cfg = Config(jev=JevConfig(modo="sombra", concurrencia=1))
    ing = ingest.ingerir(caso, cfg, jev=FakeJev(lanza(ErrorJev("Jev respondió 500: boom", enviada=True))))
    assert len(ing.llamadas_jev) == 1
    assert ing.llamadas_jev[0]["error"] == "Jev respondió 500: boom" and ing.llamadas_jev[0]["proveedor"] == "jev"
    assert len([a for a in ing.alertas_lectura if "Jev" in a]) == 1


def test_probabilidades_no_finitas_no_dejan_el_caso_ilegible(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    respuesta = choice("otro", 0.5)
    respuesta["rol"]["probabilities"] = {"otro": float("nan"), "memorial": float("inf"), "anexo": 0.2}
    ing = ingest.ingerir(caso, SOMBRA, jev=FakeJev(respuesta))
    assert ing.documentos[0].jev_probabilidades == {"anexo": 0.2}
    assert Ingesta.model_validate_json(ing.model_dump_json()) == ing


@pytest.mark.parametrize("clave", ["SECRETO-JEV\nx", "clave\u2013con-raya"])
def test_clave_no_valida_no_aborta_la_ingesta_ni_se_filtra(caso_jev, monkeypatch, clave):
    caso_jev.configurar("sombra")
    monkeypatch.setenv("JEV_API_KEY", clave)
    r = api.nuevo(caso_jev.carpeta)
    assert r["ok"], r["error"]
    ing = Ingesta.model_validate_json((caso_jev.carpeta / "caso.json").read_text(encoding="utf-8"))
    assert len([a for a in ing.alertas_lectura if "Jev" in a]) == 1
    volcado = json.dumps(r, default=str)
    assert "SECRETO" not in volcado and "raya" not in volcado
    assert not any(b"SECRETO-JEV" in p.read_bytes() for p in caso_jev.carpeta.rglob("*") if p.is_file())


def test_estado_inicial_copia_las_llamadas_de_jev_a_la_bitacora(tmp_path):
    ing = Ingesta(documentos=[], llamadas_jev=[{"nodo": "roles", "proveedor": "jev"}])
    estado = graph.estado_inicial(Path("."), Config(), ing)
    assert estado["bitacora"] == [{"nodo": "roles", "proveedor": "jev"}]
    estado["bitacora"].append({"nodo": "otro"})
    assert ing.llamadas_jev == [{"nodo": "roles", "proveedor": "jev"}]


def test_estado_inicial_sin_llamadas_de_jev_arranca_con_bitacora_vacia():
    assert graph.estado_inicial(Path("."), Config(), Ingesta(documentos=[]))["bitacora"] == []


def test_la_ingesta_con_opiniones_de_jev_se_serializa_y_se_lee(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("escrito_tutela", 0.97)))
    leida = Ingesta.model_validate_json(ing.model_dump_json())
    assert leida == ing
    assert leida.documentos[0].rol_origen == "jev" and leida.llamadas_jev == ing.llamadas_jev


def test_caso_json_anterior_sin_campos_de_jev_se_sigue_leyendo():
    doc = doc_de().model_dump(mode="json")
    for campo in ("jev_rol", "jev_confianza", "jev_probabilidades", "jev_umbral"):
        del doc[campo]
    ing = Ingesta.model_validate({"documentos": [doc]})
    d = ing.documentos[0]
    assert d.jev_rol is None and d.jev_confianza is None and d.jev_probabilidades == {} and d.jev_umbral is None
    assert ing.llamadas_jev == []


def test_reaplicar_conserva_las_llamadas_y_las_opiniones_de_jev(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS), ("doc02.txt", FALLO))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("escrito_tutela", 0.97)))
    fallo = por_nombre(ing, "doc02.txt")
    nuevo = ingest.reaplicar(ing, {fallo.doc_id: "anexo"})
    assert nuevo.llamadas_jev == ing.llamadas_jev and len(nuevo.llamadas_jev) == 2
    cambiado = por_nombre(nuevo, "doc02.txt")
    assert (cambiado.rol, cambiado.rol_origen) == ("anexo", "usuario")
    assert (cambiado.jev_rol, cambiado.jev_confianza) == ("escrito_tutela", 0.97)
    assert por_nombre(nuevo, "doc01.txt").rol_origen == "jev"
    assert nuevo.alertas_lectura == ing.alertas_lectura


def test_confirmar_el_rol_sugerido_por_jev_lo_fija_como_del_usuario(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", TEXTO_SIN_RASGOS))
    ing = ingest.ingerir(caso, RELLENO, jev=FakeJev(choice("escrito_tutela", 0.97)))
    d = ing.documentos[0]
    assert d.rol_origen == "jev"
    nuevo = ingest.reaplicar(ing, {d.doc_id: "escrito_tutela"})
    assert (nuevo.documentos[0].rol, nuevo.documentos[0].rol_origen) == ("escrito_tutela", "usuario")
    assert nuevo.documentos[0].evidencia == "Rol fijado por el usuario."


def test_reaplicar_no_promueve_un_rol_de_contenido_al_confirmarlo(tmp_path):
    caso = carpeta_con(tmp_path, ("doc01.txt", FALLO))
    ing = ingest.ingerir(caso, APAGADO)
    d = ing.documentos[0]
    nuevo = ingest.reaplicar(ing, {d.doc_id: d.rol})
    assert nuevo.documentos[0].rol_origen == "contenido"


def doc_guardado(caso: Path) -> Doc:
    return Ingesta.model_validate_json((caso / "caso.json").read_text(encoding="utf-8")).documentos[0]


class CasoApi:
    def __init__(self, carpeta: Path, monkeypatch):
        self.carpeta = carpeta
        self.monkeypatch = monkeypatch

    def configurar(self, modo: str) -> None:
        cfg = Config(llm=LLMConfig(proveedor="fake"), verificar_relatoria=False, jev=JevConfig(modo=modo))
        (self.carpeta / "config.json").write_text(cfg.model_dump_json(), encoding="utf-8")

    def jev(self, respuestas: dict | None) -> None:
        fake = FakeJev(respuestas) if respuestas is not None else None
        self.monkeypatch.setattr(ingest, "cliente_jev", lambda cfg: fake)

    def doc(self) -> Doc:
        return doc_guardado(self.carpeta)


@pytest.fixture
def caso_jev(tmp_path, monkeypatch):
    c = CasoApi(carpeta_con(tmp_path / "caso", ("doc01.txt", TEXTO_SIN_RASGOS)), monkeypatch)
    c.configurar("relleno")
    return c


def test_reingesta_no_confunde_el_rol_de_jev_con_uno_fijado_por_el_usuario(caso_jev):
    caso_jev.jev(choice("escrito_tutela", 0.97))
    assert api.nuevo(caso_jev.carpeta)["ok"]
    d = caso_jev.doc()
    assert (d.rol, d.rol_origen) == ("escrito_tutela", "jev")

    caso_jev.jev(choice("otro", 0.99))
    r = api.nuevo(caso_jev.carpeta)
    assert r["ok"], r["error"]
    d = caso_jev.doc()
    assert (d.rol, d.rol_origen, d.jev_rol) == ("otro", "contenido", "otro")

    caso_jev.configurar("apagado")
    caso_jev.jev(None)
    assert api.nuevo(caso_jev.carpeta)["ok"]
    d = caso_jev.doc()
    assert (d.rol, d.rol_origen, d.jev_rol, d.jev_confianza) == ("otro", "contenido", None, None)


def test_reingesta_conserva_el_rol_del_usuario_frente_a_jev(caso_jev):
    caso_jev.jev(choice("escrito_tutela", 0.97))
    api.nuevo(caso_jev.carpeta)
    doc_id = caso_jev.doc().doc_id
    r = api.revisar(caso_jev.carpeta, {doc_id: "anexo"}, None)
    assert r["ok"], r["error"]
    assert (caso_jev.doc().rol, caso_jev.doc().rol_origen) == ("anexo", "usuario")

    caso_jev.jev(choice("contestacion", 0.99))
    r = api.nuevo(caso_jev.carpeta)
    assert r["ok"], r["error"]
    d = caso_jev.doc()
    assert (d.rol, d.rol_origen) == ("anexo", "usuario")
    assert (d.jev_rol, d.jev_confianza) == ("contestacion", 0.99)


def test_reingesta_conserva_el_rol_que_el_usuario_confirmo_aunque_jev_ya_no_opine(caso_jev):
    caso_jev.jev(choice("escrito_tutela", 0.97))
    api.nuevo(caso_jev.carpeta)
    doc_id = caso_jev.doc().doc_id
    assert api.revisar(caso_jev.carpeta, {doc_id: "escrito_tutela"}, None)["ok"]
    assert caso_jev.doc().rol_origen == "usuario"

    caso_jev.configurar("apagado")
    caso_jev.jev(None)
    assert api.nuevo(caso_jev.carpeta)["ok"]
    d = caso_jev.doc()
    assert (d.rol, d.rol_origen, d.jev_rol) == ("escrito_tutela", "usuario", None)


def test_reingesta_vuelve_a_registrar_las_llamadas_de_jev(caso_jev):
    caso_jev.jev(choice("escrito_tutela", 0.97))
    api.nuevo(caso_jev.carpeta)
    doc_id = caso_jev.doc().doc_id
    api.revisar(caso_jev.carpeta, {doc_id: "anexo"}, None)
    ing = Ingesta.model_validate_json((caso_jev.carpeta / "caso.json").read_text(encoding="utf-8"))
    assert len(ing.llamadas_jev) == 1
    api.nuevo(caso_jev.carpeta)
    ing = Ingesta.model_validate_json((caso_jev.carpeta / "caso.json").read_text(encoding="utf-8"))
    assert len(ing.llamadas_jev) == 1 and ing.llamadas_jev[0]["proveedor"] == "jev"
