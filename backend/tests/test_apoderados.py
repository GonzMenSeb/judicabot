from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.request

import pytest

from tutela2 import apoderados, ingest
from tutela2.models import (
    AbogadoLLM,
    ApoderadosLLM,
    Doc,
    Identificacion,
    Ingesta,
    MencionLLM,
    Metadatos,
    Pagina,
    ParteLLM,
    PoderLLM,
)

ACCIONANTE = "MARTA INÉS QUINTERO BEDOYA"
EPS = "EPS HORIZONTE SALUD S.A.S."
SECRETARIA = "SECRETARÍA SECCIONAL DE SALUD DE ANTIOQUIA"
ABOGADA = "ANDREA PAOLA GIRALDO MONTOYA"
CC_ABOGADA = "1.017.234.567"
CC_ABOGADA_PLANA = "1017234567"
TP_ABOGADA = "287.415"
REPRESENTANTE = "JORGE ENRIQUE PALACIO VARGAS"
CC_REPRESENTANTE = "70.555.123"
SUSTITUYENTE = "ANA MARÍA LÓPEZ RUIZ"

CONTESTACION = (
    f"Referencia: Contestación de la acción de tutela\nAccionante: {ACCIONANTE}\nAccionada: {EPS}\n"
    f"La suscrita abogada {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA} y portadora de la "
    f"tarjeta profesional No. {TP_ABOGADA} del Consejo Superior de la Judicatura, obrando como apoderada judicial de "
    f"la {EPS}, me permito dar contestación a la acción de tutela en los siguientes términos.\n"
    "Es cierto que la accionante está afiliada a la entidad, pero no es cierto que se le haya negado el servicio."
)
PODER = (
    f"Referencia: Poder especial\n{REPRESENTANTE}, mayor de edad, identificado con la cédula de ciudadanía No. "
    f"{CC_REPRESENTANTE}, obrando como representante legal de la {EPS}, por medio del presente escrito confiero poder "
    f"especial, amplio y suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA} "
    f"y portadora de la tarjeta profesional No. {TP_ABOGADA}, para que conteste la acción de tutela promovida por "
    f"{ACCIONANTE}.\nAtentamente,\n{REPRESENTANTE}\nC.C. {CC_REPRESENTANTE}\nAcepto,\n{ABOGADA}\n"
    f"C.C. {CC_ABOGADA}\nT.P. {TP_ABOGADA}"
)
CITA_PODER = f"confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía"
CITA_MENCION = f"La suscrita abogada {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA}"
RELLENO = " ".join(["El objeto social comprende la prestación de servicios de salud a sus afiliados."] * 6)


def certificado(nombrado: str = REPRESENTANTE, sociedad: str = EPS, cargo: str = "REPRESENTANTE LEGAL") -> str:
    return (
        "CÁMARA DE COMERCIO DE MEDELLÍN PARA ANTIOQUIA\nCERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL\n"
        f"Código de verificación: ABC123\nRAZÓN SOCIAL: {sociedad}\nNIT: 800.000.412-0\n{RELLENO}\n"
        f"NOMBRAMIENTOS\nCARGO: {cargo}\nNOMBRE: {nombrado}\nIDENTIFICACIÓN: C.C. {CC_REPRESENTANTE}"
    )


def doc(doc_id: str, rol: str, paginas: list[str | Pagina], nombre: str | None = None) -> Doc:
    hojas = [
        p if isinstance(p, Pagina) else Pagina(n=i, texto=p, ruido=ingest._es_certificado(p))
        for i, p in enumerate(paginas, 1)
    ]
    d = Doc(
        doc_id=doc_id,
        ruta=f"{doc_id}.pdf",
        nombre=nombre or f"{doc_id}.pdf",
        instancia="1a",
        rol=rol,
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        paginas=hojas,
    )
    if hojas and all(p.ruido for p in hojas):
        d.ruido, d.motivo_ruido = True, "Certificado de existencia y representación legal"
    return d


def expediente(*docs: Doc, accionadas=(EPS,), vinculadas=(), ajenos=(), revisar=()) -> Ingesta:
    return Ingesta(
        documentos=list(docs),
        docs_ajenos=list(ajenos),
        docs_revisar=list(revisar),
        metadatos=Metadatos(accionante=ACCIONANTE, accionadas=list(accionadas), vinculadas=list(vinculadas)),
    )


def base(*extra: Doc, cert: str | None = None, **kw) -> Ingesta:
    docs = [doc("1a-001", "contestacion", [CONTESTACION, PODER])]
    if cert is not None:
        docs.append(doc("1a-002", "anexo", [cert]))
    return expediente(*docs, *extra, **kw)


def poder(**kw) -> PoderLLM:
    datos = dict(
        tipo="poder", doc_id="1a-001", pagina=2, cita=CITA_PODER, otorgante=REPRESENTANTE, cargo_otorgante="representante legal"
    )
    return PoderLLM(**{**datos, **kw})


def abogado(**kw) -> AbogadoLLM:
    datos = dict(
        nombre=ABOGADA,
        parte=EPS,
        cedula_texto=CC_ABOGADA,
        tarjeta_texto=TP_ABOGADA,
        menciones=[MencionLLM(doc_id="1a-001", pagina=1, cita=CITA_MENCION)],
        poderes=[poder()],
    )
    return AbogadoLLM(**{**datos, **kw})


def verificar(ing: Ingesta, *abogados: AbogadoLLM, partes: list[ParteLLM] | None = None) -> Identificacion:
    return apoderados.verificar(ApoderadosLLM(partes=partes or [], abogados=list(abogados)), ing, ing.metadatos)


def unico(ident: Identificacion):
    assert len(ident.apoderados) == 1, ident.model_dump_json(indent=1)
    return ident.apoderados[0]


def sin_cedulas(ident: Identificacion) -> None:
    textos = json.dumps([ident.alertas, [a.motivos for a in ident.apoderados]], ensure_ascii=False)
    for cedula in (CC_ABOGADA, CC_ABOGADA_PLANA, CC_REPRESENTANTE, "70555123"):
        assert cedula not in textos


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)


# --- Caso completo y datos de identidad ---


def test_poder_de_sociedad_con_cadena_confirmada():
    ident = verificar(base(cert=certificado()), abogado())
    ap = unico(ident)
    assert (ap.nombre, ap.parte, ap.rol_parte, ap.tipo_persona) == (ABOGADA, EPS, "accionada", "juridica")
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta == "287415"
    assert ap.cedula_fuente is not None and ap.cedula_fuente.doc_id == "1a-001"
    assert [(m.doc_id, m.pagina) for m in ap.menciones] == [("1a-001", 1)]
    [p] = ap.poderes
    assert (p.tipo, p.evidencia.doc_id, p.evidencia.pagina, p.otorgante, p.parte) == ("poder", "1a-001", 2, REPRESENTANTE, EPS)
    assert p.evidencia.cobertura >= 0.8 and p.evidencia.ocr is False
    assert p.cadena.estado == "confirmada" and p.cadena.otorgante == REPRESENTANTE
    assert p.cadena.cargo == "representante legal"
    assert (p.cadena.evidencia.doc_id, p.cadena.evidencia.pagina) == ("1a-002", 1)
    assert REPRESENTANTE in p.cadena.evidencia.cita
    assert ap.ajenos == [] and ap.motivos == []
    assert ident.alertas == [] and ident.documentos_revisados == 2
    assert ident.ingesta_sha == apoderados.huella_ingesta(base(cert=certificado()))


def test_las_posiciones_de_la_evidencia_senalan_la_cita_en_la_pagina():
    ap = unico(verificar(base(cert=certificado()), abogado()))
    textos = {(1, "1a-001"): CONTESTACION, (2, "1a-001"): PODER}
    for ev in [*ap.menciones, ap.poderes[0].evidencia]:
        tramo = textos[(ev.pagina, ev.doc_id)][ev.inicio : ev.fin]
        assert apoderados.clave(tramo) == apoderados.clave(ev.cita)
    fuente = ap.cedula_fuente
    assert PODER[fuente.inicio : fuente.fin].startswith(ABOGADA) and PODER[fuente.inicio : fuente.fin].endswith(CC_ABOGADA)
    cadena = ap.poderes[0].cadena.evidencia
    assert apoderados.clave(certificado()[cadena.inicio : cadena.fin]) == apoderados.clave(cadena.cita)


def test_tildes_descompuestas_no_desplazan_las_posiciones():
    nfd = unicodedata.normalize("NFD", PODER)
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, nfd]), doc("1a-002", "anexo", [certificado()]))
    ap = unico(verificar(ing, abogado()))
    ev = ap.poderes[0].evidencia
    assert unicodedata.normalize("NFC", nfd[ev.inicio : ev.fin]).startswith("confiero poder especial")
    assert ap.cedula == CC_ABOGADA_PLANA


def test_cedula_y_tarjeta_inventadas_se_descartan_y_se_toman_las_que_constan():
    ap = unico(verificar(base(cert=certificado()), abogado(cedula_texto="43.111.222", tarjeta_texto="99.999")))
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta == "287415"
    assert any("cédula que señaló el modelo no consta" in m for m in ap.motivos)
    assert any("La tarjeta profesional que señaló el modelo no consta" in m and "se tomó la 287415" in m for m in ap.motivos)
    assert not any("99999" in m for m in ap.motivos)


def test_sin_numeros_junto_al_nombre_no_hay_cedula_ni_tarjeta():
    contestacion = f"Referencia: Contestación\nAccionada: {EPS}\nLa suscrita abogada {ABOGADA}, obrando como apoderada judicial de la {EPS}, contesta la acción de tutela en los siguientes términos de defensa."
    poder_sin = PODER.replace(f" No. {CC_ABOGADA}", "").replace(f"C.C. {CC_ABOGADA}", "").replace(f" No. {TP_ABOGADA}", "").replace(
        f"T.P. {TP_ABOGADA}", ""
    )
    cita = f"La suscrita abogada {ABOGADA}, obrando como apoderada judicial de la {EPS}"
    ing = expediente(doc("1a-001", "contestacion", [contestacion, poder_sin]), doc("1a-002", "anexo", [certificado()]))
    ap = unico(
        verificar(ing, abogado(menciones=[MencionLLM(doc_id="1a-001", pagina=1, cita=cita)], poderes=[poder(cita=CITA_PODER)]))
    )
    assert ap.cedula is None and ap.tarjeta is None and ap.cedula_fuente is None
    assert any("no se puede consultar automáticamente" in m for m in ap.motivos)
    assert any("tarjeta profesional" in m for m in ap.motivos)


def test_la_cedula_del_poderdante_no_se_toma_por_la_del_abogado():
    ident = verificar(base(cert=certificado()), abogado(cedula_texto=CC_REPRESENTANTE))
    ap = unico(ident)
    assert ap.cedula == CC_ABOGADA_PLANA
    sin_cedulas(ident)


def test_la_tarjeta_de_otro_abogado_en_la_misma_pagina_no_se_toma():
    sustitucion = (
        f"Yo, {SUSTITUYENTE}, abogada con T.P. 123.456, apoderada de la {EPS}, sustituyo el poder que me fue conferido "
        f"a la doctora {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA}, con T.P. {TP_ABOGADA}.\n"
        f"Acepto,\n{ABOGADA}\n\n{SUSTITUYENTE}\nT.P. 123.456"
    )
    cita = f"sustituyo el poder que me fue conferido a la doctora {ABOGADA}"
    ing = expediente(doc("1a-001", "memorial", [sustitucion]))
    ab = abogado(
        tarjeta_texto="123.456",
        menciones=[],
        poderes=[poder(tipo="sustitucion", pagina=1, cita=cita, otorgante=SUSTITUYENTE, cargo_otorgante="apoderada")],
    )
    ap = unico(verificar(ing, ab))
    assert ap.tarjeta == "287415"
    [p] = ap.poderes
    assert p.tipo == "sustitucion" and p.cadena.estado == "no_aplica" and p.otorgante == SUSTITUYENTE


ACEPTA = f"Acepto,\n{ABOGADA}\nT.P. {TP_ABOGADA}\n"
FIRMA_OTORGANTE = f"{REPRESENTANTE}\nC.C. {CC_REPRESENTANTE}"
PODER_SIN_NUMEROS = (
    f"Referencia: Poder especial\n{REPRESENTANTE}, obrando como representante legal de la {EPS}, por medio del presente "
    f"escrito confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, para que conteste la acción de tutela "
    f"promovida por {ACCIONANTE}.\n"
)
CITA_SIN_NUMEROS = f"confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, para que conteste la acción de tutela"


@pytest.mark.parametrize(
    "firmas",
    [
        ACEPTA + "Otorga,\n" + FIRMA_OTORGANTE,
        ACEPTA + "\n" + FIRMA_OTORGANTE,
        ACEPTA + "Atentamente,\n" + FIRMA_OTORGANTE,
        # Un nombre corto en la misma línea del rótulo no parece un nombre; el rótulo basta.
        ACEPTA + f"Otorga: Jorge Palacio, C.C. {CC_REPRESENTANTE}",
    ],
    ids=["rotulo_otorga", "solo_el_nombre", "atentamente", "rotulo_en_linea"],
)
@pytest.mark.parametrize("cedula_texto", ["", CC_REPRESENTANTE])
def test_la_cedula_que_sigue_a_la_firma_de_otro_no_es_del_abogado(firmas, cedula_texto):
    """El abogado firma sin cédula y debajo firma el poderdante, que el modelo no señaló como otorgante."""
    ing = expediente(doc("1a-001", "contestacion", [PODER_SIN_NUMEROS + firmas]), doc("1a-002", "anexo", [certificado()]))
    ab = abogado(cedula_texto=cedula_texto, menciones=[], poderes=[poder(pagina=1, cita=CITA_SIN_NUMEROS, otorgante="")])
    ident = verificar(ing, ab)
    ap = unico(ident)
    assert ap.cedula is None and ap.cedula_fuente is None
    assert ap.tarjeta == "287415"
    sin_cedulas(ident)


@pytest.mark.parametrize("otro", [REPRESENTANTE, "JORGE PALACIO"])
@pytest.mark.parametrize("nombre_modelo", [ABOGADA, "ANDREA PAOLA GIRALDO"])
def test_firmas_lado_a_lado_no_dan_la_cedula_del_otro_firmante(nombre_modelo, otro):
    # pdftotext -layout pone los dos bloques de firma en columnas: el nombre del poderdante queda en la misma
    # línea que el del abogado y su cédula, en la línea siguiente.
    firmas = (
        f"Acepto,                                   Otorgo,\n"
        f"{ABOGADA}              {otro}\n"
        f"T.P. {TP_ABOGADA}                              C.C. {CC_REPRESENTANTE}"
    )
    ing = expediente(doc("1a-001", "contestacion", [PODER_SIN_NUMEROS + firmas]), doc("1a-002", "anexo", [certificado()]))
    ab = abogado(nombre=nombre_modelo, cedula_texto="", menciones=[], poderes=[poder(pagina=1, cita=CITA_SIN_NUMEROS, otorgante="")])
    ident = verificar(ing, ab)
    assert unico(ident).cedula is None
    sin_cedulas(ident)


def test_la_tarjeta_del_sustituyente_que_firma_debajo_no_es_del_abogado():
    sustitucion = (
        f"Yo, {SUSTITUYENTE}, apoderada de la {EPS}, sustituyo el poder que me fue conferido a la doctora {ABOGADA}, "
        f"para que continúe con la representación.\nAcepto,\n{ABOGADA}\nC.C. {CC_ABOGADA}\nSustituye,\n{SUSTITUYENTE}\n"
        "T.P. 123.456"
    )
    cita = f"sustituyo el poder que me fue conferido a la doctora {ABOGADA}"
    ing = expediente(doc("1a-001", "memorial", [sustitucion]))
    ab = abogado(tarjeta_texto="", menciones=[], poderes=[poder(tipo="sustitucion", pagina=1, cita=cita, otorgante="")])
    ap = unico(verificar(ing, ab))
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta is None
    assert [p.tipo for p in ap.poderes] == ["sustitucion"]


def test_los_apellidos_pegados_al_nombre_que_dio_el_modelo_son_del_abogado():
    # El modelo dio el nombre sin los apellidos finales: lo que sigue pegado al nombre es suyo, no de otra persona.
    firma = f"Acepto,\n{ABOGADA} ARANGO\nC.C. {CC_ABOGADA}\nT.P. {TP_ABOGADA}"
    ing = expediente(doc("1a-001", "contestacion", [PODER_SIN_NUMEROS + firma]), doc("1a-002", "anexo", [certificado()]))
    ab = abogado(nombre="ANDREA PAOLA GIRALDO", menciones=[], poderes=[poder(pagina=1, cita=CITA_SIN_NUMEROS)])
    ap = unico(verificar(ing, ab))
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta == "287415"


def test_en_un_escrito_en_mayusculas_los_numeros_del_abogado_se_toman():
    poder_mayusculas = PODER.upper()
    cita = CITA_PODER.upper()
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, poder_mayusculas]), doc("1a-002", "anexo", [certificado()]))
    ap = unico(verificar(ing, abogado(menciones=[], poderes=[poder(cita=cita)])))
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta == "287415"


def test_cedula_con_formato_distinto_es_la_misma():
    ap = unico(verificar(base(cert=certificado()), abogado(cedula_texto=CC_ABOGADA_PLANA, tarjeta_texto="287415")))
    assert ap.cedula == CC_ABOGADA_PLANA and ap.tarjeta == "287415"
    assert not [m for m in ap.motivos if "cédula" in m or "tarjeta" in m]


def test_cedula_de_largo_imposible_se_descarta():
    ap = unico(verificar(base(cert=certificado()), abogado(cedula_texto="1234")))
    assert ap.cedula == CC_ABOGADA_PLANA


def test_ocr_de_la_pagina_queda_en_la_evidencia():
    paginas = [Pagina(n=1, texto=CONTESTACION), Pagina(n=2, texto=PODER, ocr=True)]
    ing = expediente(doc("1a-001", "contestacion", paginas), doc("1a-002", "anexo", [certificado()]))
    ap = unico(verificar(ing, abogado()))
    assert ap.poderes[0].evidencia.ocr is True and ap.menciones[0].ocr is False


# --- Citas y páginas ---


def test_cita_en_otra_pagina_del_documento_se_corrige():
    ap = unico(verificar(base(cert=certificado()), abogado(poderes=[poder(pagina=1)])))
    assert ap.poderes[0].evidencia.pagina == 2
    assert any("estaba en 1a-001, p. 2, y no en la p. 1" in m for m in ap.motivos)


def test_cita_inexistente_se_descarta_y_la_busqueda_halla_el_poder():
    ab = abogado(poderes=[poder(cita="otorgo poder general a quien corresponda para todos los fines legales pertinentes")])
    ap = unico(verificar(base(cert=certificado()), ab))
    assert any("no consta en 1a-001; se descartó" in m for m in ap.motivos)
    assert any("se halló uno en 1a-001, p. 2" in m for m in ap.motivos)
    [p] = ap.poderes
    assert (p.evidencia.doc_id, p.evidencia.pagina, p.tipo) == ("1a-001", 2, "poder")
    assert p.evidencia.cita.startswith("confiero poder") and ABOGADA in p.evidencia.cita
    assert p.otorgante == REPRESENTANTE and p.cadena.estado == "confirmada"


def test_cita_corta_o_de_documento_inexistente_se_descarta():
    ab = abogado(
        menciones=[MencionLLM(doc_id="1a-999", pagina=1, cita=CITA_MENCION), MencionLLM(doc_id="1a-001", pagina=1, cita=ABOGADA)]
    )
    ap = unico(verificar(base(cert=certificado()), ab))
    assert ap.menciones == []
    assert any("«1a-999»" in m for m in ap.motivos) and any("demasiado corta" in m for m in ap.motivos)


def test_cita_en_una_pagina_que_no_nombra_al_abogado_se_descarta():
    otro = PODER.replace(ABOGADA, "CARLOS ALBERTO RÍOS MESA")
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION]), doc("1a-003", "anexo", [otro]))
    cita = "confiero poder especial, amplio y suficiente a la doctora CARLOS ALBERTO RÍOS MESA"
    ap = unico(verificar(ing, abogado(poderes=[poder(doc_id="1a-003", pagina=1, cita=cita)])))
    assert ap.poderes == []
    assert any("no nombra al abogado" in m for m in ap.motivos)
    assert any(m.startswith("No se halló poder para EPS HORIZONTE SALUD S.A.S. en los 2 documentos") for m in ap.motivos)


def test_documentos_ajenos_no_se_pueden_citar():
    ing = base(cert=certificado(), ajenos=["1a-001"])
    ident = verificar(ing, abogado())
    assert ident.apoderados == []
    assert any("no consta en el expediente" in a for a in ident.alertas)


def test_poder_en_documento_de_otro_radicado_no_cuenta():
    ap = unico(verificar(base(cert=certificado(), revisar=["1a-001"]), abogado()))
    assert ap.poderes == [] and ap.menciones
    assert any("parece de otro radicado" in m for m in ap.motivos)


# --- Partes y poderes ajenos ---


def test_poder_otorgado_por_otra_parte_va_a_ajenos():
    poder_marta = (
        f"{ACCIONANTE}, mayor de edad, identificada con la cédula de ciudadanía No. 43.999.101, por medio del presente "
        f"confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía "
        f"No. {CC_ABOGADA} y portadora de la tarjeta profesional No. {TP_ABOGADA}, para que promueva acción de tutela "
        f"contra la {EPS}."
    )
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION]), doc("1a-002", "anexo", [poder_marta]))
    ap = unico(verificar(ing, abogado(poderes=[poder(doc_id="1a-002", pagina=1, otorgante=ACCIONANTE)])))
    assert ap.poderes == []
    [ajeno] = ap.ajenos
    assert (ajeno.parte, ajeno.otorgante, ajeno.evidencia.doc_id) == (ACCIONANTE, ACCIONANTE, "1a-002")
    assert any(f"lo otorga {ACCIONANTE} (accionante), no {EPS}" in m for m in ap.motivos)
    assert any(m.startswith(f"No se halló poder para {EPS}") for m in ap.motivos)


def test_poder_de_la_sociedad_reclamado_para_la_accionante_va_a_ajenos():
    ap = unico(verificar(base(cert=certificado()), abogado(parte=ACCIONANTE)))
    assert ap.parte == ACCIONANTE and ap.rol_parte == "accionante" and ap.tipo_persona == "natural"
    assert ap.poderes == [] and [a.parte for a in ap.ajenos] == [EPS]


CITA_PROMOVIDA = f"confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía"


@pytest.mark.parametrize(
    "encabezado",
    [
        # El accionante se nombra justo después del poderdante, pero el poder es de la sociedad.
        f"{REPRESENTANTE}, mayor de edad, identificado con la cédula de ciudadanía No. {CC_REPRESENTANTE}, dentro de la "
        f"acción de tutela promovida por {ACCIONANTE} en contra de la {EPS}, obrando en mi condición de representante "
        "legal de esta última,",
        f"La {EPS}, sociedad comercial con domicilio en Medellín, representada legalmente por {REPRESENTANTE}, dentro "
        f"de la acción de tutela promovida por {ACCIONANTE},",
    ],
    ids=["promovida_por", "representada_por"],
)
def test_poder_de_la_parte_reclamada_aunque_nombre_antes_a_otra(encabezado):
    texto = (
        f"Referencia: Poder especial\n{encabezado} por medio del presente escrito confiero poder especial, amplio y "
        f"suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA} y portadora de la "
        f"tarjeta profesional No. {TP_ABOGADA}, para que conteste la acción de tutela."
    )
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, texto]), doc("1a-002", "anexo", [certificado()]))
    ap = unico(verificar(ing, abogado(poderes=[poder(cita=CITA_PROMOVIDA)])))
    assert ap.ajenos == []
    [p] = ap.poderes
    assert (p.parte, p.otorgante, p.cadena.estado) == (EPS, REPRESENTANTE, "confirmada")
    assert not any("lo otorga" in m for m in ap.motivos)


def test_representada_por_otra_parte_va_a_ajenos_aunque_la_pagina_nombre_a_la_reclamada():
    texto = (
        f"La {EPS}, representada legalmente por {REPRESENTANTE}, por medio del presente escrito confiero poder especial, "
        f"amplio y suficiente a la doctora {ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA}, para "
        f"que conteste la acción de tutela promovida por {ACCIONANTE}."
    )
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, texto]))
    ap = unico(verificar(ing, abogado(parte=ACCIONANTE, poderes=[poder(cita=CITA_PROMOVIDA)])))
    assert ap.poderes == [] and [(a.parte, a.otorgante) for a in ap.ajenos] == [(EPS, REPRESENTANTE)]


JUAN = "JUAN CARLOS PÉREZ GÓMEZ"
CARLOS = "CARLOS PÉREZ"
LUIS = "LUIS FERNANDO MEJÍA ROJAS"
PODER_CARLOS = (
    f"{CARLOS}, mayor de edad, identificado con la cédula de ciudadanía No. 71.222.333, por medio del presente confiero "
    f"poder especial, amplio y suficiente al doctor {LUIS}, identificado con la cédula de ciudadanía No. 98.765.432 y "
    "portador de la tarjeta profesional No. 111.222, para que me represente como vinculado en la acción de tutela."
)
CITA_CARLOS = f"confiero poder especial, amplio y suficiente al doctor {LUIS}, identificado con la cédula de ciudadanía"


def _luis(parte: str, otorgante: str = CARLOS, **metadatos) -> Identificacion:
    ing = Ingesta(
        documentos=[doc("1a-001", "anexo", [PODER_CARLOS])],
        metadatos=Metadatos(**{"accionante": JUAN, "accionadas": [EPS], "vinculadas": [CARLOS], **metadatos}),
    )
    ab = AbogadoLLM(
        nombre=LUIS,
        parte=parte,
        cedula_texto="98.765.432",
        tarjeta_texto="111.222",
        menciones=[],
        poderes=[PoderLLM(tipo="poder", doc_id="1a-001", pagina=1, cita=CITA_CARLOS, otorgante=otorgante, cargo_otorgante="")],
    )
    return verificar(ing, ab)


def test_el_otorgante_se_atribuye_a_la_parte_que_mejor_coincide():
    # "CARLOS PÉREZ" cabe en "JUAN CARLOS PÉREZ GÓMEZ", pero es el nombre exacto del vinculado.
    ap = unico(_luis(CARLOS))
    assert [p.parte for p in ap.poderes] == [CARLOS] and ap.ajenos == []
    ap = unico(_luis(EPS))
    assert ap.poderes == [] and [a.parte for a in ap.ajenos] == [CARLOS]


def test_otorgante_que_coincide_mejor_con_otra_parte_no_cuenta_ni_es_ajeno():
    ap = unico(_luis(JUAN))
    assert ap.poderes == [] and ap.ajenos == []
    assert any("coincide con más de una parte" in m for m in ap.motivos)


def test_otorgante_que_coincide_igual_con_dos_partes_no_es_ajeno():
    ap = unico(_luis(EPS, accionante="CARLOS PÉREZ RUIZ", vinculadas=["CARLOS PÉREZ LÓPEZ"], accionadas=[EPS]))
    assert ap.poderes == [] and ap.ajenos == []
    assert any("coincide con más de una parte" in m for m in ap.motivos)


def test_parte_que_no_esta_en_los_metadatos_no_genera_ajenos():
    ap = unico(verificar(base(cert=certificado()), abogado(parte="CLÍNICA SANTA AURORA S.A.S.")))
    assert ap.parte == "CLÍNICA SANTA AURORA S.A.S." and ap.rol_parte == "otro"
    assert ap.poderes == [] and ap.ajenos == []
    assert any("no figura en los metadatos" in m for m in ap.motivos)


def test_poder_que_no_nombra_a_la_parte_no_cuenta_ni_es_ajeno():
    generico = (
        f"Por medio del presente escrito confiero poder especial, amplio y suficiente a la doctora {ABOGADA}, "
        f"identificada con la cédula de ciudadanía No. {CC_ABOGADA}, para que represente a la entidad."
    )
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION]), doc("1a-002", "anexo", [generico]))
    ap = unico(verificar(ing, abogado(poderes=[poder(doc_id="1a-002", pagina=1, otorgante="")])))
    assert ap.poderes == [] and ap.ajenos == []
    assert any("no nombra a EPS HORIZONTE SALUD S.A.S." in m for m in ap.motivos)


def test_la_parte_se_reconoce_aunque_el_modelo_la_escriba_distinto():
    ap = unico(verificar(base(cert=certificado()), abogado(parte="Horizonte Salud EPS")))
    assert ap.parte == EPS and ap.rol_parte == "accionada" and ap.poderes


def test_otorgante_que_no_consta_en_el_poder_se_tiene_por_no_indicado():
    ap = unico(verificar(base(cert=certificado()), abogado(poderes=[poder(otorgante="PEDRO PABLO PÉREZ GÓMEZ")])))
    [p] = ap.poderes
    assert p.otorgante == "" and p.cadena.estado == "contradicha"
    assert any("PEDRO PABLO PÉREZ GÓMEZ" in m and "no consta" in m for m in ap.motivos)


# --- Cadena con el certificado de existencia (páginas ruido) ---


def test_certificado_que_no_nombra_al_otorgante_contradice_la_cadena():
    ap = unico(verificar(base(cert=certificado(nombrado="LUISA FERNANDA OSORIO DÍAZ")), abogado()))
    [p] = ap.poderes
    assert p.cadena.estado == "contradicha" and p.cadena.otorgante == REPRESENTANTE
    assert p.cadena.evidencia is not None and p.cadena.evidencia.doc_id == "1a-002"
    assert any(f"no nombra a {REPRESENTANTE}" in m for m in ap.motivos)


def test_certificado_que_nombra_al_otorgante_en_otro_cargo_contradice_la_cadena():
    pagina1 = certificado(nombrado="LUISA FERNANDA OSORIO DÍAZ")
    pagina2 = f"{RELLENO}\n{RELLENO}\nREVISORÍA FISCAL\nREVISOR FISCAL PRINCIPAL: {REPRESENTANTE}"
    ing = base(doc("1a-002", "anexo", [pagina1, Pagina(n=2, texto=pagina2, ruido=True)]))
    ap = unico(verificar(ing, abogado()))
    [p] = ap.poderes
    assert p.cadena.estado == "contradicha" and p.cadena.evidencia.pagina == 2
    assert any("pero no como representante legal" in m for m in ap.motivos)


def test_representante_en_pagina_siguiente_del_certificado_confirma_la_cadena():
    pagina1 = certificado(nombrado="LUISA FERNANDA OSORIO DÍAZ", cargo="GERENTE")
    pagina2 = f"REPRESENTANTE LEGAL SUPLENTE\nNOMBRE: {REPRESENTANTE}"
    ing = base(doc("1a-002", "anexo", [pagina1, Pagina(n=2, texto=pagina2, ruido=True)]))
    [p] = unico(verificar(ing, abogado())).poderes
    assert p.cadena.estado == "confirmada" and p.cadena.evidencia.pagina == 2
    assert p.cadena.cargo in ("representante legal", "suplente")


def test_certificado_dentro_del_mismo_documento_del_poder():
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, PODER, certificado()]))
    assert ing.documentos[0].paginas[2].ruido and "CÁMARA" not in ingest.texto_para_llm(ing)
    [p] = unico(verificar(ing, abogado())).poderes
    assert p.cadena.estado == "confirmada" and (p.cadena.evidencia.doc_id, p.cadena.evidencia.pagina) == ("1a-001", 3)


def test_certificado_de_otra_sociedad_no_cuenta():
    ap = unico(verificar(base(cert=certificado(sociedad="DISTRIBUCIONES EL FARO S.A.S.")), abogado()))
    [p] = ap.poderes
    assert p.cadena.estado == "sin_certificado"
    assert any("No obra certificado de existencia" in m for m in ap.motivos)


def test_sin_otorgante_no_se_puede_cotejar_la_cadena():
    [p] = unico(verificar(base(cert=certificado()), abogado(poderes=[poder(otorgante="")]))).poderes
    assert p.otorgante == "" and p.cadena.estado == "contradicha" and p.cadena.evidencia.doc_id == "1a-002"


def test_entidad_publica_sin_certificado_no_aplica():
    poder_sec = PODER.replace(EPS, SECRETARIA).replace("representante legal", "secretario de despacho")
    contestacion = CONTESTACION.replace(EPS, SECRETARIA)
    ing = expediente(doc("1a-001", "contestacion", [contestacion, poder_sec]), accionadas=(EPS,), vinculadas=(SECRETARIA,))
    ap = unico(verificar(ing, abogado(parte=SECRETARIA)))
    assert ap.tipo_persona == "juridica" and ap.rol_parte == "vinculada"
    [p] = ap.poderes
    assert p.cadena.estado == "no_aplica"


def test_persona_natural_no_necesita_cadena():
    poder_marta = (
        f"{ACCIONANTE}, mayor de edad, por medio del presente confiero poder especial, amplio y suficiente a la doctora "
        f"{ABOGADA}, identificada con la cédula de ciudadanía No. {CC_ABOGADA} y portadora de la tarjeta profesional "
        f"No. {TP_ABOGADA}, para que promueva acción de tutela contra la {EPS}."
    )
    ing = expediente(doc("1a-001", "escrito_tutela", [poder_marta]), doc("1a-002", "anexo", [certificado()]))
    ab = abogado(parte=ACCIONANTE, menciones=[], poderes=[poder(pagina=1, otorgante=ACCIONANTE)])
    ap = unico(verificar(ing, ab))
    assert ap.tipo_persona == "natural" and ap.rol_parte == "accionante"
    [p] = ap.poderes
    assert p.parte == ACCIONANTE and p.cadena.estado == "no_aplica"


def test_certificado_que_inscribe_al_abogado_como_apoderado_es_poder():
    inscrito = certificado() + f"\nAPODERADOS JUDICIALES\nNOMBRE: {ABOGADA}\nCARGO: APODERADA JUDICIAL"
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION]), doc("1a-002", "anexo", [inscrito]))
    cita = f"IDENTIFICACIÓN: C.C. {CC_REPRESENTANTE} APODERADOS JUDICIALES NOMBRE: {ABOGADA}"
    propuesto = poder(tipo="certificado_existencia", doc_id="1a-002", pagina=1, cita=cita, otorgante="")
    [p] = unico(verificar(ing, abogado(poderes=[propuesto]))).poderes
    assert p.tipo == "certificado_existencia" and p.parte == EPS and p.cadena.estado == "no_aplica"

    [hallado] = unico(verificar(ing, abogado(poderes=[]))).poderes
    assert hallado.tipo == "certificado_existencia" and hallado.evidencia.doc_id == "1a-002"


def test_poder_propuesto_como_certificado_en_pagina_comun_se_descarta():
    ap = unico(verificar(base(cert=certificado()), abogado(poderes=[poder(tipo="certificado_existencia")])))
    assert any("no es un certificado de existencia" in m for m in ap.motivos)
    assert [p.tipo for p in ap.poderes] == ["poder"]


# --- Búsqueda de respaldo, descartes y fusiones ---


def test_sin_poder_propuesto_se_busca_la_pagina_de_otorgamiento():
    ap = unico(verificar(base(cert=certificado()), abogado(poderes=[])))
    [p] = ap.poderes
    assert (p.evidencia.doc_id, p.evidencia.pagina) == ("1a-001", 2) and p.cadena.estado == "contradicha"
    assert any("se halló uno en 1a-001, p. 2" in m for m in ap.motivos)


def test_la_busqueda_exige_los_numeros_conocidos_del_abogado():
    sin_numeros = PODER.replace(CC_ABOGADA, "").replace(TP_ABOGADA, "")
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION, sin_numeros]))
    ap = unico(verificar(ing, abogado(poderes=[])))
    assert ap.poderes == []
    assert any(m.startswith(f"No se halló poder para {EPS} en los 1 documentos") for m in ap.motivos)


def test_abogado_sin_citas_validas_se_conserva_si_su_nombre_consta():
    ab = abogado(menciones=[MencionLLM(doc_id="1a-001", pagina=1, cita="frase que no aparece en ninguna parte del expediente")], poderes=[])
    ap = unico(verificar(expediente(doc("1a-001", "contestacion", [CONTESTACION])), ab))
    assert [(m.doc_id, m.pagina) for m in ap.menciones] == [("1a-001", 1)]
    assert any("su nombre consta en 1a-001, p. 1" in m for m in ap.motivos)


def test_abogado_inventado_se_descarta_con_alerta():
    ident = verificar(base(cert=certificado()), abogado(nombre="ROBERTO CARLOS INVENTADO PÉREZ", menciones=[], poderes=[]))
    assert ident.apoderados == []
    assert ident.alertas[0] == (
        f"ALERTA: El modelo propuso como abogado a ROBERTO CARLOS INVENTADO PÉREZ ({EPS}), pero su nombre no consta en "
        "el expediente; se descartó."
    )
    assert len(ident.alertas) == 2 and "tarjeta profesional 287415" in ident.alertas[1]


def test_ids_estables_y_duplicados_fusionados():
    a = abogado(poderes=[])
    b = abogado(nombre="Andrea Paola Giraldo Montoya", parte="EPS Horizonte Salud S.A.S.", menciones=[], poderes=[poder()])
    ident = verificar(base(cert=certificado()), a, b)
    ap = unico(ident)
    assert ap.id == apoderados.id_apoderado(ABOGADA, EPS) == apoderados.id_apoderado("andrea  paola giraldo montoya", EPS)
    assert re.fullmatch(r"ap-[0-9a-f]{10}", ap.id)
    assert ap.menciones and ap.poderes and ap.nombre == ABOGADA
    assert unico(verificar(base(cert=certificado()), abogado())).id == ap.id
    otra = verificar(base(cert=certificado()), abogado(), abogado(parte=ACCIONANTE))
    assert len({x.id for x in otra.apoderados}) == 2


def test_dos_cedulas_distintas_para_el_mismo_abogado_se_descartan():
    otra = CONTESTACION.replace(CC_ABOGADA, "1.017.234.561")
    ing = expediente(doc("1a-001", "contestacion", [CONTESTACION]), doc("1a-002", "memorial", [otra]))
    a = abogado(poderes=[])
    b = abogado(cedula_texto="1.017.234.561", menciones=[MencionLLM(doc_id="1a-002", pagina=1, cita=CITA_MENCION.replace(CC_ABOGADA, "1.017.234.561"))], poderes=[])
    ap = unico(verificar(ing, a, b))
    assert ap.cedula is None and ap.cedula_fuente is None and ap.tarjeta == "287415"
    assert any("dos cédulas distintas" in m for m in ap.motivos)


def test_huella_de_la_ingesta_no_depende_del_orden():
    a = doc("1a-001", "contestacion", [CONTESTACION])
    b = doc("1a-002", "anexo", [certificado()])
    assert apoderados.huella_ingesta(expediente(a, b)) == apoderados.huella_ingesta(expediente(b, a))
    assert apoderados.huella_ingesta(expediente(a)) != apoderados.huella_ingesta(expediente(a, b))


# --- Partes sin abogado y alertas ---


def test_partes_sin_abogado_y_parte_con_abogado_no_identificado():
    partes = [
        ParteLLM(nombre=ACCIONANTE, rol_parte="accionante", con_abogado=False),
        ParteLLM(nombre=EPS, rol_parte="accionada", con_abogado=True),
        ParteLLM(nombre=SECRETARIA, rol_parte="vinculada", con_abogado=False),
        ParteLLM(nombre="FONDO DE PENSIONES PROTECCIÓN S.A.", rol_parte="vinculada", con_abogado=True),
    ]
    ident = verificar(base(cert=certificado(), vinculadas=(SECRETARIA,)), abogado(), partes=partes)
    assert [(p.nombre, p.rol_parte, p.nota) for p in ident.sin_apoderado] == [
        (ACCIONANTE, "accionante", "Actúa en nombre propio."),
        (SECRETARIA, "vinculada", "Actúa por su representante legal o por un funcionario."),
    ]
    assert ident.alertas == [
        "ALERTA: Según el modelo, FONDO DE PENSIONES PROTECCIÓN S.A. actúa por medio de abogado, pero no se pudo "
        "comprobar en el expediente quién la representa; revíselo."
    ]


def test_red_de_seguridad_alerta_tarjetas_sin_abogado():
    escrito = "Medellín\nSeñor Juez\nCARLOS ALBERTO RÍOS MESA, abogado con T.P. No. 99.887 del C. S. de la J., actúa en nombre de la accionante."
    ing = base(doc("1a-003", "escrito_tutela", [escrito]), cert=certificado())
    ident = verificar(ing, abogado())
    assert ident.alertas == [
        "ALERTA: En 1a-003 (1a-003.pdf), p. 1, consta la tarjeta profesional 99887, que no corresponde a ningún "
        "apoderado identificado; revise si actúa un abogado que no se identificó."
    ]
    assert not verificar(base(cert=certificado()), abogado()).alertas
    sin_abogados = verificar(base(cert=certificado()))
    assert len(sin_abogados.alertas) == 1 and "287415" in sin_abogados.alertas[0]


def test_ningun_motivo_ni_alerta_lleva_una_cedula():
    casos = [
        verificar(base(cert=certificado()), abogado(cedula_texto="43.111.222")),
        verificar(base(cert=certificado()), abogado(cedula_texto=CC_REPRESENTANTE, poderes=[])),
        verificar(base(cert=certificado(nombrado="LUISA FERNANDA OSORIO DÍAZ")), abogado(cedula_texto="12")),
        verificar(base(cert=certificado()), abogado(tarjeta_texto=CC_ABOGADA)),
        verificar(base(cert=certificado()), abogado(tarjeta_texto=CC_REPRESENTANTE)),
        verificar(base(cert=certificado()), abogado(tarjeta_texto="1.234.567")),
    ]
    assert "1234567" not in json.dumps([a.motivos for a in casos[-1].apoderados])
    for ident in casos:
        sin_cedulas(ident)


def test_propuesta_vacia_da_identificacion_vacia():
    ident = verificar(expediente(doc("1a-001", "contestacion", [CONTESTACION.replace(TP_ABOGADA, "")])))
    assert ident.apoderados == [] and ident.sin_apoderado == [] and ident.alertas == []
    assert ident.documentos_revisados == 1 and ident.ingesta_sha


# --- Páginas que recibe el modelo ---


def _paginas_largas() -> Ingesta:
    escrito = doc(
        "1a-001",
        "escrito_tutela",
        ["Primera página del escrito de tutela.", "Página intermedia sin nada pertinente.", "Página intermedia con el apoderado judicial.", "Firma de la accionante."],
    )
    fallo = doc("1a-002", "fallo_a_quo", ["Encabezado del fallo.", "Considera el juzgado que la tutela procede."])
    certificado_doc = doc("1a-003", "anexo", [certificado()])
    ajeno = doc("1a-004", "anexo", ["Poder especial de otro proceso al abogado."])
    producto = doc("1a-005", "producto_despacho", ["Poder especial del despacho."])
    duplicado = doc("1a-006", "contestacion", [CONTESTACION])
    duplicado.ruido, duplicado.motivo_ruido = True, "Duplicado exacto de 1a-007"
    revisar = doc("1a-007", "memorial", ["Memorial con poder especial para el abogado."])
    return Ingesta(
        documentos=[escrito, fallo, certificado_doc, ajeno, producto, duplicado, revisar],
        docs_ajenos=["1a-004"],
        docs_revisar=["1a-007"],
    )


def test_paginas_para_apoderados_elige_las_pertinentes():
    texto, alertas = ingest.paginas_para_apoderados(_paginas_largas(), 150_000)
    assert alertas == []
    assert "### DOC 1a-001 | escrito_tutela | 1a-001.pdf\n[p. 1]\nPrimera página" in texto
    assert "[p. 3]\nPágina intermedia con el apoderado" in texto and "[p. 4]\nFirma" in texto
    assert "Página intermedia sin nada" not in texto
    assert "1a-002" not in texto
    assert f"### DOC 1a-003 | anexo | 1a-003.pdf\n[p. 1] {ingest.ETIQUETA_CERTIFICADO}\nCÁMARA DE COMERCIO" in texto
    assert "1a-004" not in texto and "1a-005" not in texto and "1a-006" not in texto
    assert f"### DOC 1a-007 | memorial | 1a-007.pdf\n{ingest.AVISO_REVISAR}\n[p. 1]" in texto
    assert texto.index("1a-001") < texto.index("1a-003") < texto.index("1a-007")


def test_texto_para_llm_no_cambia_y_sigue_sin_certificados():
    ing = _paginas_largas()
    texto = ingest.texto_para_llm(ing)
    assert "CÁMARA DE COMERCIO" not in texto and "Página intermedia sin nada" in texto


def test_paginas_para_apoderados_respeta_el_tope_con_alerta():
    ing = _paginas_largas()
    ing.documentos[2].paginas[0].texto = certificado() + "\n" + "x " * 2000
    texto, alertas = ingest.paginas_para_apoderados(ing, 1200)
    assert len(texto) <= 1200
    assert "CÁMARA DE COMERCIO" in texto and "[... TRUNCADO ...]" in texto
    assert len(alertas) == 1 and alertas[0].startswith("ALERTA: Identificación de apoderados") and "1200" in alertas[0]
    texto, alertas = ingest.paginas_para_apoderados(ing, 300)
    assert len(texto) <= 300 and alertas


def test_paginas_para_apoderados_de_un_expediente_vacio():
    assert ingest.paginas_para_apoderados(Ingesta(documentos=[]), 1000) == ("", [])


def test_la_busqueda_revisa_la_pagina_que_el_modelo_dio_como_mencion():
    ab = abogado(menciones=[MencionLLM(doc_id="1a-001", pagina=2, cita=CITA_PODER)], poderes=[])
    ap = unico(verificar(base(cert=certificado()), ab))
    assert [(m.doc_id, m.pagina) for m in ap.menciones] == [("1a-001", 2)]
    assert [(p.evidencia.doc_id, p.evidencia.pagina) for p in ap.poderes] == [("1a-001", 2)]
