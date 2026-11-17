from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from tutela2 import estado_apoderados, registro_apoderados
from tutela2.estado_apoderados import (
    Bloqueo,
    bloqueos,
    evaluar,
    evaluar_todos,
    fallida,
    mensaje_bloqueo,
)
from tutela2.models import (
    Apoderado,
    Cadena,
    EvidenciaDoc,
    Identificacion,
    ParteSinApoderado,
    Poder,
)
from tutela2.registro_apoderados import Ajuste, ConsultaVigencia, Registro, Revision
from tutela2.vigencia import CertificadoVigencia

CEDULA = "43000021"
TARJETA = "214883"
PARTE = "Salud Vital EPS S.A."


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def _falla(req, timeout=None):
        raise urllib.error.URLError("sin red en los tests")

    monkeypatch.setattr(urllib.request, "urlopen", _falla)


def _ev(doc_id: str = "1a-014", pagina: int = 3, ocr: bool = False) -> EvidenciaDoc:
    return EvidenciaDoc(
        doc_id=doc_id,
        pagina=pagina,
        cita="confiero poder especial, amplio y suficiente a la doctora MARCELA ORTIZ PEÑA",
        cobertura=1.0,
        ocr=ocr,
    )


def _poder(parte: str = PARTE, cadena: str = "confirmada", ocr: bool = False, doc_id: str = "1a-014") -> Poder:
    return Poder(
        tipo="poder",
        evidencia=_ev(doc_id, 3, ocr),
        otorgante="Pedro Alvarado Lema",
        parte=parte,
        cadena=Cadena(
            estado=cadena,
            otorgante="Pedro Alvarado Lema",
            cargo="representante legal",
            evidencia=_ev("1a-009", 2) if cadena == "confirmada" else None,
        ),
    )


def _apoderado(**cambios) -> Apoderado:
    datos = dict(
        id="ap-0000000001",
        nombre="Marcela Ortiz Peña",
        parte=PARTE,
        rol_parte="accionada",
        tipo_persona="juridica",
        cedula=CEDULA,
        tarjeta=TARJETA,
        cedula_fuente=_ev(),
        menciones=[_ev("1b-006", 1)],
        poderes=[_poder()],
    )
    datos.update(cambios)
    return Apoderado(**datos)


def _consulta(
    estado: str = "vigente",
    tpa_numero: str | None = TARJETA,
    tpa_estado: str | None = "VIGENTE",
    sha: str = "a" * 64,
    **datos,
) -> ConsultaVigencia:
    certificado = dict(
        numero="1234567",
        nombre="MARCELA ORTIZ PEÑA",
        documento=CEDULA,
        rna_estado="VIGENTE",
        tpa_numero=tpa_numero,
        tpa_fecha="01/02/2010",
        tpa_estado=tpa_estado,
        tpa_observaciones="NO REGISTRA",
        rna_observaciones="NO REGISTRA",
    )
    certificado.update(datos)
    return ConsultaVigencia(
        estado=estado,
        origen="manual",
        consultado_en="2026-11-17T10:42:00+00:00",
        certificado="certificados/aaaaaaaaaaaaaaaa.pdf",
        sha256=sha,
        datos=CertificadoVigencia(**certificado),
    )


def _registro(
    ap: Apoderado | None = None,
    consulta: ConsultaVigencia | None = None,
    ajuste: Ajuste | None = None,
    revision: Revision | None = None,
) -> Registro:
    ap = ap or _apoderado()
    return Registro(
        identificacion=Identificacion(ingesta_sha="x", apoderados=[ap], documentos_revisados=14),
        consultas={CEDULA: consulta} if consulta is not None else {},
        ajustes={ap.id: ajuste} if ajuste is not None else {},
        revisiones={ap.id: revision} if revision is not None else {},
    )


def _evaluar(ap=None, consulta=None, ajuste=None, revision=None, **kw):
    ap = ap or _apoderado()
    return evaluar(ap, _registro(ap, consulta, ajuste, revision), **kw)


VIGENTE = _consulta()
SIN_TARJETA = dict(tarjeta=None)
AJENO = dict(poderes=[], ajenos=[_poder(parte="Instituto Departamental de Salud")])
NATURAL = dict(tipo_persona="natural", poderes=[_poder(cadena="no_aplica")])

FILAS = [
    # 1. La tarjeta no está vigente: gana a cualquier otra cosa.
    ("no_vigente", {}, _consulta("no_vigente", tpa_estado="SUSPENDIDO"), None, "no_verificado", "no_vigente"),
    ("no_vigente_y_tp_difiere", {}, _consulta("no_vigente", tpa_numero="999999", tpa_estado="SUSPENDIDO"), None, "no_verificado", "no_vigente"),
    ("no_vigente_y_ajeno", AJENO, _consulta("no_vigente", tpa_estado="EXCLUIDO"), None, "no_verificado", "no_vigente"),
    ("no_vigente_solo_rna", {}, _consulta("no_vigente", tpa_numero=None, tpa_estado=None, rna_estado="NO VIGENTE"), None, "no_verificado", "no_vigente"),
    # 2. T.P. distinta del certificado, leída de páginas sin OCR.
    ("tp_difiere", {}, _consulta(tpa_numero="214884"), None, "no_verificado", "difiere"),
    ("tp_difiere_con_observaciones", {}, _consulta("vigente_obs", tpa_numero="214884"), None, "no_verificado", "difiere"),
    ("tp_difiere_sin_poder", dict(poderes=[]), _consulta(tpa_numero="214884"), None, "no_verificado", "difiere"),
    # 3. Poder solo para otra parte del trámite.
    ("ajeno", AJENO, VIGENTE, None, "no_verificado", "ajeno"),
    ("ajeno_sin_consultar", AJENO, None, None, "no_verificado", "ajeno"),
    ("ajeno_sin_cedula", dict(AJENO, cedula=None), None, None, "no_verificado", "ajeno"),
    # 4. Verificado.
    ("verificado", {}, VIGENTE, None, "verificado", None),
    ("verificado_natural", NATURAL, VIGENTE, None, "verificado", None),
    ("verificado_sin_tp_en_expediente", SIN_TARJETA, VIGENTE, None, "verificado", None),
    ("verificado_tp_con_cero_inicial", dict(tarjeta="0214883"), VIGENTE, None, "verificado", None),
    ("verificado_sin_certificado_de_existencia", dict(poderes=[_poder(cadena="sin_certificado")]), VIGENTE, None, "verificado", None),
    ("verificado_un_poder_contradicho_y_otro_no", dict(poderes=[_poder(cadena="contradicha"), _poder()]), VIGENTE, None, "verificado", None),
    ("verificado_poder_manual", dict(poderes=[]), VIGENTE, Ajuste(poder_manual=_ev("1a-020", 1)), "verificado", None),
    ("poder_manual_gana_a_ajeno", AJENO, VIGENTE, Ajuste(poder_manual=_ev("1a-020", 1)), "verificado", None),
    ("verificado_con_cedula_ajustada", dict(cedula=None), VIGENTE, Ajuste(cedula="43.000.021"), "verificado", None),
    # 5. Por revisar.
    ("vigente_con_observaciones", {}, _consulta("vigente_obs"), None, "revisar", "vigente_obs"),
    ("otra_persona", {}, _consulta("otra_persona"), None, "revisar", "otra_persona"),
    ("vigente_a_otro_nombre", {}, _consulta(nombre="PEDRO JOSE FICTICIO MORA"), None, "revisar", "otra_persona"),
    ("vigente_sin_nombre", {}, _consulta(nombre=None), None, "revisar", "otra_persona"),
    ("no_vigente_a_otro_nombre", {}, _consulta("no_vigente", tpa_estado="SUSPENDIDO", nombre="PEDRO JOSE FICTICIO MORA"), None, "revisar", "otra_persona"),
    ("cedula_ajustada_sin_tp_en_expediente", dict(cedula=None, tarjeta=None), VIGENTE, Ajuste(cedula=CEDULA), "revisar", "vigente"),
    ("cedula_ajustada_sin_tp_en_certificado", dict(cedula=None), _consulta(tpa_numero=None), Ajuste(cedula=CEDULA), "revisar", "sin_dato"),
    ("otra_persona_y_tp_distinta", {}, _consulta("otra_persona", tpa_numero="111111"), None, "revisar", "otra_persona"),
    ("ilegible", {}, _consulta("ilegible", tpa_numero="111111"), None, "revisar", "ilegible"),
    ("inaccesible", {}, ConsultaVigencia(estado="inaccesible", origen="extension", consultado_en="2026-11-17T10:42:00+00:00"), None, "revisar", "inaccesible"),
    ("sin_cedula", dict(cedula=None), None, None, "revisar", "sin_cedula"),
    ("sin_consultar", {}, None, None, "revisar", "sin_consultar"),
    ("tp_difiere_con_ocr", dict(menciones=[_ev("1b-006", 1, ocr=True)]), _consulta(tpa_numero="214884"), None, "revisar", "difiere_ocr"),
    ("tp_difiere_poder_escaneado", dict(poderes=[_poder(ocr=True)]), _consulta(tpa_numero="214884"), None, "revisar", "difiere_ocr"),
    ("tp_difiere_sin_paginas_fuente", dict(cedula_fuente=None, menciones=[], poderes=[]), _consulta(tpa_numero="214884"), None, "revisar", "difiere_ocr"),
    ("cadena_contradicha", dict(poderes=[_poder(cadena="contradicha")]), VIGENTE, None, "revisar", "hallado_reserva"),
    ("sin_poder", dict(poderes=[]), VIGENTE, None, "revisar", "sin_poder"),
    ("poder_descartado", {}, VIGENTE, Ajuste(poder_descartado=True), "revisar", "descartado"),
    ("descartado_y_ajeno", AJENO, VIGENTE, Ajuste(poder_descartado=True), "revisar", "descartado"),
]


@pytest.mark.parametrize("cambios, consulta, ajuste, estado, causa", [f[1:] for f in FILAS], ids=[f[0] for f in FILAS])
def test_tabla_de_estados(cambios, consulta, ajuste, estado, causa):
    ev = _evaluar(_apoderado(**cambios), consulta, ajuste)
    assert ev.estado == estado
    if causa is not None:
        assert causa in (ev.vigencia, ev.tarjeta, ev.poder)
    if estado == "verificado":
        assert ev.motivo is None and ev.fase == "listo"
    else:
        assert ev.motivo and ev.motivo in ev.motivos
    assert all(CEDULA not in m and "43.000.021" not in m for m in ev.motivos), ev.motivos
    assert ev.bloquea is (estado == "no_verificado")


def test_motivos_concretos_en_espanol():
    rojo = _evaluar(consulta=_consulta("no_vigente", tpa_numero="97551", tpa_estado="SUSPENDIDA"))
    assert rojo.motivo == "La tarjeta profesional 97551 figura como «SUSPENDIDA» en el certificado N.° 1234567."
    rna = _evaluar(consulta=_consulta("no_vigente", tpa_numero=None, tpa_estado=None, rna_estado="NO VIGENTE"))
    assert rna.motivo == (
        "La inscripción en el Registro Nacional de Abogados figura como «NO VIGENTE» en el certificado N.° 1234567."
    )
    difiere = _evaluar(consulta=_consulta(tpa_numero="214884"))
    assert difiere.motivo == (
        "La tarjeta profesional del expediente (214883) no coincide con la del certificado de vigencia (214884)."
    )
    ocr = _evaluar(_apoderado(menciones=[_ev(ocr=True)]), _consulta(tpa_numero="214884"))
    assert "OCR" in ocr.motivo
    ajeno = _evaluar(_apoderado(**AJENO), VIGENTE)
    assert ajeno.motivo == f"El poder hallado es para Instituto Departamental de Salud, no para {PARTE}."
    sin_poder = _evaluar(_apoderado(poderes=[]), VIGENTE)
    assert sin_poder.motivo == f"Se revisaron 14 documentos y ninguno le otorga poder para representar a {PARTE}."
    reserva = _evaluar(_apoderado(poderes=[_poder(cadena="contradicha")]), VIGENTE)
    assert "no acredita a Pedro Alvarado Lema" in reserva.motivo
    obs = _evaluar(consulta=_consulta("vigente_obs", tpa_observaciones="SANCIONADO HASTA 2027"))
    assert "«SANCIONADO HASTA 2027»" in obs.motivo


def test_los_motivos_de_la_identificacion_se_suman_sin_repetir():
    ap = _apoderado(motivos=["La cita del poder se corrigió a la página 3.", "La cita del poder se corrigió a la página 3."])
    ev = _evaluar(ap, VIGENTE)
    assert ev.estado == "verificado"
    assert ev.motivos == ["La cita del poder se corrigió a la página 3."]
    ambar = _evaluar(ap, None)
    assert ambar.motivos[0].startswith("Aún no se ha consultado") and ambar.motivos[-1] == ap.motivos[0]


def test_cotejos_de_un_verificado_juridico_y_natural():
    juridico = _evaluar(consulta=VIGENTE)
    assert [c.ok for c in juridico.cotejos] == [True, True, True, True]
    assert juridico.cotejos[1].texto == "T.P. 214883 coincide con el certificado de vigencia"
    assert juridico.cotejos[2].texto == f"Representa a {PARTE}, la parte accionada"
    assert juridico.cotejos[3].texto == (
        "Lo otorga Pedro Alvarado Lema, representante legal, acreditado en el certificado de existencia (Doc. 1a-009, p. 2)"
    )
    natural = _evaluar(_apoderado(**NATURAL), VIGENTE)
    assert [c.ok for c in natural.cotejos] == [True, True, True]


@pytest.mark.parametrize(
    "cambios, consulta, esperado",
    [
        (dict(poderes=[]), VIGENTE, [None, True, None]),
        (AJENO, VIGENTE, [True, True, False]),
        ({}, _consulta(tpa_numero="214884"), [True, False, True, True]),
        ({}, _consulta("otra_persona"), [True, False, True, True]),
        ({}, None, [True, None, True, True]),
        (dict(poderes=[_poder(cadena="contradicha")]), VIGENTE, [True, True, True, False]),
        (dict(poderes=[_poder(cadena="sin_certificado")]), VIGENTE, [True, True, True, None]),
    ],
)
def test_cotejos_sin_fila_de_alcance(cambios, consulta, esperado):
    ev = _evaluar(_apoderado(**cambios), consulta)
    assert [c.ok for c in ev.cotejos] == esperado
    assert not any("lcance" in c.texto for c in ev.cotejos)


@pytest.mark.parametrize(
    "cambios, consulta, cola, automatica, fase",
    [
        ({}, VIGENTE, None, False, "listo"),
        ({}, _consulta("no_vigente", tpa_estado="SUSPENDIDO"), None, False, "listo"),
        ({}, _consulta("vigente_obs"), None, False, "listo"),
        ({}, None, None, False, "necesita_ayuda"),
        ({}, None, None, True, "en_cola"),
        ({}, None, "en_cola", False, "en_cola"),
        ({}, None, "consultando", True, "consultando"),
        ({}, ConsultaVigencia(estado="inaccesible", origen="extension", consultado_en="x"), None, True, "necesita_ayuda"),
        ({}, ConsultaVigencia(estado="inaccesible", origen="extension", consultado_en="x"), "consultando", True, "consultando"),
        ({}, _consulta("ilegible"), None, True, "necesita_ayuda"),
        ({}, _consulta("otra_persona"), None, True, "necesita_ayuda"),
        (dict(cedula=None), None, "en_cola", True, "necesita_ayuda"),
    ],
)
def test_fase(cambios, consulta, cola, automatica, fase):
    ev = _evaluar(_apoderado(**cambios), consulta, fase_cola=lambda c: cola, consulta_automatica=automatica)
    assert ev.fase == fase


def test_la_fase_de_la_cola_no_cambia_estado_ni_huella():
    quieta = _evaluar(consulta=None)
    en_curso = _evaluar(consulta=None, fase_cola=lambda c: "consultando", consulta_automatica=True)
    assert (quieta.estado, quieta.huella) == (en_curso.estado, en_curso.huella)
    assert quieta.fase != en_curso.fase


def test_la_huella_es_estable_y_corta():
    a, b = _evaluar(consulta=VIGENTE), _evaluar(consulta=VIGENTE)
    assert a.huella == b.huella and len(a.huella) == 16 and int(a.huella, 16) >= 0


@pytest.mark.parametrize(
    "cambio",
    [
        dict(consulta=_consulta(sha="b" * 64)),
        dict(consulta=_consulta("no_vigente", tpa_estado="EXCLUIDO")),
        dict(ap=_apoderado(**dict(AJENO, motivos=["Otro motivo."]))),
        dict(ap=_apoderado(ajenos=[_poder(parte="Instituto Departamental de Salud", doc_id="1a-015")], poderes=[])),
        dict(ajuste=Ajuste(poder_manual=_ev("1a-020", 1))),
    ],
    ids=["otro_certificado", "otro_estado", "otro_motivo", "otra_pagina", "poder_manual"],
)
def test_la_revision_vence_si_cambia_la_evidencia(cambio):
    ap = _apoderado(**AJENO)
    rojo = _evaluar(ap, VIGENTE)
    assert rojo.estado == "no_verificado" and rojo.bloquea
    revision = Revision(revisado=True, en="2026-11-17T10:45:00+00:00", huella=rojo.huella)
    revisado = _evaluar(ap, VIGENTE, revision=revision)
    assert revisado.revisado and not revisado.revision_vencida and not revisado.bloquea

    args = {"ap": ap, "consulta": VIGENTE, **cambio}
    despues = _evaluar(args["ap"], args["consulta"], args.get("ajuste"), revision)
    assert despues.huella != rojo.huella
    assert not despues.revisado and despues.revision_vencida
    assert despues.bloquea is (despues.estado == "no_verificado")


def test_revision_desmarcada_no_cuenta_ni_vence():
    rojo = _evaluar(_apoderado(**AJENO), VIGENTE)
    revision = Revision(revisado=False, en="x", huella=rojo.huella, nota="lo miro luego")
    ev = _evaluar(_apoderado(**AJENO), VIGENTE, revision=revision)
    assert not ev.revisado and not ev.revision_vencida and ev.bloquea


def test_la_revision_de_un_ambar_no_cambia_el_estado():
    ambar = _evaluar(consulta=None)
    revisado = _evaluar(consulta=None, revision=Revision(revisado=True, en="x", huella=ambar.huella))
    assert revisado.estado == "revisar" and revisado.revisado and not revisado.bloquea


def test_evaluar_todos_y_fallida():
    assert evaluar_todos(Registro()) == []
    reg = _registro(_apoderado(**AJENO), VIGENTE)
    assert [ev.estado for ev in evaluar_todos(reg)] == ["no_verificado"]
    assert fallida(Identificacion())
    assert not fallida(Identificacion(documentos_revisados=3))
    assert not fallida(Identificacion(sin_apoderado=[ParteSinApoderado(nombre="Secretaría", rol_parte="vinculada")]))


def test_consultas_por_cedula_compartidas_entre_apoderados():
    uno = _apoderado()
    otro = _apoderado(id="ap-0000000002", parte="Instituto Departamental de Salud", rol_parte="vinculada")
    reg = Registro(
        identificacion=Identificacion(apoderados=[uno, otro], documentos_revisados=2),
        consultas={CEDULA: _consulta("no_vigente", tpa_estado="SUSPENDIDO")},
    )
    assert [ev.estado for ev in evaluar_todos(reg)] == ["no_verificado", "no_verificado"]


def test_el_nombre_del_certificado_se_coteja_con_cada_apoderado_que_comparte_la_cedula():
    marcela = _apoderado()
    otro = _apoderado(id="ap-0000000002", nombre="Pedro José Ficticio Mora")
    reg = Registro(
        identificacion=Identificacion(apoderados=[marcela, otro], documentos_revisados=2),
        consultas={CEDULA: _consulta("no_vigente", tpa_estado="SUSPENDIDO")},
    )
    rojo, ambar = evaluar_todos(reg)
    assert (rojo.estado, rojo.vigencia, rojo.bloquea) == ("no_verificado", "no_vigente", True)
    assert (ambar.estado, ambar.vigencia, ambar.bloquea) == ("revisar", "otra_persona", False)
    assert ambar.motivo == "El certificado de vigencia está a nombre de MARCELA ORTIZ PEÑA, no de Pedro José Ficticio Mora."


MOTIVO_SIN_CEDULA = (
    "No consta la cédula del abogado junto a su nombre en las páginas comprobadas; "
    "la vigencia de su tarjeta profesional no se puede consultar automáticamente."
)
DEL_CERTIFICADO = "La cédula del abogado no consta en el expediente: se tomó del certificado de vigencia subido"


def test_cedula_tomada_del_certificado_lo_dice_y_quita_el_motivo_de_la_identificacion():
    otro_motivo = "La cita del poder se corrigió a la página 3."
    ap = _apoderado(cedula=None, cedula_fuente=None, motivos=[MOTIVO_SIN_CEDULA, otro_motivo])
    verde = _evaluar(ap, VIGENTE, Ajuste(cedula=CEDULA))
    assert verde.estado == "verificado" and verde.cedula == CEDULA
    assert verde.motivos == [DEL_CERTIFICADO + ".", otro_motivo]
    assert verde.cotejos[2].ok is None and verde.cotejos[2].texto.startswith("La cédula se tomó del certificado subido")
    assert [c.ok for c in verde.cotejos] == [True, True, None, True, True]

    ambar = _evaluar(ap.model_copy(update={"tarjeta": None}), VIGENTE, Ajuste(cedula=CEDULA))
    assert ambar.estado == "revisar" and ambar.fase == "listo"
    assert ambar.motivo == ambar.motivos[0] and ambar.motivo.startswith(DEL_CERTIFICADO + ", y sin la tarjeta profesional")

    # Sin ajuste el motivo de la identificación sigue valiendo, y una cédula del expediente no da el aviso.
    assert _evaluar(ap, None).motivos[-2:] == [MOTIVO_SIN_CEDULA, otro_motivo]
    con_cedula = _evaluar(_apoderado(motivos=[MOTIVO_SIN_CEDULA]), VIGENTE)
    assert not any(m.startswith(DEL_CERTIFICADO) for m in con_cedula.motivos)
    assert len(con_cedula.cotejos) == 4


def test_bloqueos_y_mensaje(tmp_path):
    caso = tmp_path / "caso"
    caso.mkdir()
    assert bloqueos(caso) == []

    rojo = _apoderado(id="ap-rojo000001", nombre="Carlos Eduardo Pineda Ruiz", **AJENO)
    ambar = _apoderado(id="ap-ambar00001", nombre="Julián David Mesa Londoño", poderes=[])
    verde = _apoderado(id="ap-verde00001")
    ident = Identificacion(apoderados=[rojo, ambar, verde], documentos_revisados=5)
    registro_apoderados.espejar(caso, ident)
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: VIGENTE}))

    pendientes = bloqueos(caso)
    assert pendientes == [Bloqueo(rojo.id, rojo.nombre, rojo.parte, f"El poder hallado es para Instituto Departamental de Salud, no para {PARTE}.")]
    assert mensaje_bloqueo(pendientes) == (
        "Hay apoderados no verificados sin revisar: Carlos Eduardo Pineda Ruiz. Márquelos como revisados en el borrador."
    )

    huella = evaluar(rojo, registro_apoderados.leer(caso)).huella
    registro_apoderados.actualizar(
        caso, lambda r: r.revisiones.update({rojo.id: Revision(revisado=True, en="x", huella=huella)})
    )
    assert bloqueos(caso) == []

    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta(sha="c" * 64)}))
    assert [b.id for b in bloqueos(caso)] == [rojo.id]


def test_mensaje_con_varios_nombres_sin_repetir():
    pendientes = [Bloqueo("a", "Ana Uno", "X", "m"), Bloqueo("b", "Beto Dos", "Y", "m"), Bloqueo("c", "Ana Uno", "Z", "m")]
    assert estado_apoderados.mensaje_bloqueo(pendientes) == (
        "Hay apoderados no verificados sin revisar: Ana Uno, Beto Dos. Márquelos como revisados en el borrador."
    )


def test_caso_sin_identificacion_nunca_bloquea(tmp_path):
    caso = tmp_path / "caso"
    (caso / "apoderados").mkdir(parents=True)
    registro_apoderados.actualizar(caso, lambda r: r.consultas.update({CEDULA: _consulta("no_vigente", tpa_estado="X")}))
    assert bloqueos(caso) == []


# ---------------------------------------------------------------- cédula no inscrita


def _no_inscrito(origen: str = "extension", sha: str = "c" * 64) -> ConsultaVigencia:
    return ConsultaVigencia(
        estado="no_inscrito",
        origen=origen,
        consultado_en="2026-11-17T10:42:00+00:00",
        certificado="certificados/cccccccccccccccc.pdf",
        sha256=sha,
        datos=CertificadoVigencia(
            inscrito=False, documento=CEDULA, numero="7654321", expedido="17/11/2026 10:42:00 AM", codigo_verificacion="0" * 64
        ),
    )


@pytest.mark.parametrize(
    "cambios, origen, ajuste, estado, grave",
    [
        # La cédula consta en una página del expediente leída sin OCR: como una tarjeta no vigente, rojo.
        ({}, "extension", None, "no_verificado", True),
        ({}, "manual", None, "no_verificado", True),
        (AJENO, "extension", None, "no_verificado", True),
        # Pudo leerse o escribirse mal: ámbar.
        (dict(cedula_fuente=_ev(ocr=True)), "extension", None, "revisar", False),
        (dict(cedula_fuente=None), "extension", None, "revisar", False),
        (dict(cedula=None), "extension", Ajuste(cedula=CEDULA), "revisar", False),
        (dict(cedula=None), "manual", Ajuste(cedula=CEDULA), "revisar", False),
        # El poder de otra parte lo deja sin verificar, pero la vigencia sigue sin ser grave: la cédula pudo leerse mal.
        (dict(cedula_fuente=_ev(ocr=True), **AJENO), "extension", None, "no_verificado", False),
        (dict(cedula=None, **AJENO), "manual", Ajuste(cedula=CEDULA), "no_verificado", False),
    ],
    ids=[
        "sin_ocr",
        "sin_ocr_subido",
        "sin_ocr_y_ajeno",
        "ocr",
        "sin_pagina_fuente",
        "cedula_a_mano",
        "cedula_del_certificado_subido",
        "ocr_y_ajeno",
        "cedula_a_mano_y_ajeno",
    ],
)
def test_cedula_no_inscrita(cambios, origen, ajuste, estado, grave):
    ev = _evaluar(_apoderado(**cambios), _no_inscrito(origen), ajuste)
    assert (ev.vigencia, ev.estado, ev.tarjeta, ev.fase) == ("no_inscrito", estado, "sin_dato", "listo")
    assert ev.vigencia_grave is grave
    assert ev.bloquea is (estado == "no_verificado")
    assert ev.motivos[0] == estado_apoderados.MOTIVO_NO_INSCRITO == (
        "El Registro Nacional de Abogados certifica que la cédula del abogado no está inscrita como abogado(a). "
        "Verifique el número; si actúa con licencia temporal, esta consulta no la cubre."
    )
    if estado == "revisar":
        assert ev.motivo == estado_apoderados.MOTIVO_NO_INSCRITO
    assert all(CEDULA not in m and "7654321" not in m for m in ev.motivos)
    assert any(c.ok is False and "no figura inscrita" in c.texto for c in ev.cotejos)
    if ajuste is not None:
        # El certificado de una cédula no inscrita no trae nombre: la cédula la escribió quien revisa, aunque se subiera.
        assert "La cédula del abogado no consta en el expediente: la indicó a mano quien revisa." in ev.motivos
        assert not any("certificado de vigencia subido" in m for m in ev.motivos)
        assert any(c.texto == "La cédula la indicó a mano quien revisa; no consta en el expediente" for c in ev.cotejos)


def test_cedula_no_inscrita_nunca_es_de_otra_persona_por_no_traer_nombre():
    for nombre in ("Marcela Ortiz Peña", "Pedro José Ficticio Mora", ""):
        ev = _evaluar(_apoderado(nombre=nombre or "X"), _no_inscrito())
        assert ev.vigencia == "no_inscrito"


def test_la_huella_cambia_con_la_cedula_no_inscrita():
    ap = _apoderado()
    rojo_no_vigente = _evaluar(ap, _consulta("no_vigente", tpa_estado="SUSPENDIDO"))
    rojo = _evaluar(ap, _no_inscrito())
    ambar = _evaluar(_apoderado(cedula_fuente=_ev(ocr=True)), _no_inscrito())
    assert len({rojo_no_vigente.huella, rojo.huella, ambar.huella}) == 3
    revision = Revision(revisado=True, en="2026-11-17T10:45:00+00:00", huella=rojo.huella)
    assert _evaluar(ap, _no_inscrito(), revision=revision).revisado
    assert _evaluar(ap, _no_inscrito(sha="d" * 64), revision=revision).revision_vencida
