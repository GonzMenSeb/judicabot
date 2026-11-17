import json

import pytest
from anthropic.lib._parse._transform import to_json_output_format
from pydantic import ValidationError

from tutela2.config import Config
from tutela2.llm import esquema_gemini
from tutela2.models import (
    AbogadoLLM,
    Apoderado,
    ApoderadosLLM,
    Cadena,
    DatosAuto,
    Decision,
    Doc,
    Estado,
    EvidenciaDoc,
    Identificacion,
    Ingesta,
    MencionLLM,
    Metadatos,
    MetadatosLLM,
    Orden,
    ParteLLM,
    ParteSinApoderado,
    Poder,
    PoderLLM,
)


def _decision(**kw):
    return Decision(accion="decidir", resultado="REVOCAR", sustitutiva="NEGAR", eje="x", **kw)


def test_orden_numerales_invalido():
    assert any("zzz" in e for e in _decision(orden_numerales=["zzz"]).errores())


def test_orden_numerales_valido():
    d = _decision(
        orden_numerales=["resultado", "notificar", "orden:0"],
        ordenes=[Orden(destinatario="X", conducta="y")],
    )
    assert d.errores() == []


def test_orden_numerales_indice_fuera_de_rango():
    assert any("orden:3" in e for e in _decision(orden_numerales=["orden:3"]).errores())
    assert any("libre:1" in e for e in _decision(numerales_libres=["a"], orden_numerales=["libre:1"]).errores())


def test_fechas_iso():
    assert any("2026-13-01" in e for e in _decision(fecha_fallo="2026-13-01").errores())
    assert any("fecha_oficio" in e for e in _decision(fecha_oficio="xx").errores())
    assert _decision(fecha_fallo="2026-10-21", fecha_oficio="2026-10-22").errores() == []


def test_numeral_libre_vacio():
    assert _decision(numerales_libres=["  "]).errores()
    assert _decision(numerales_libres=["texto"]).errores() == []


def test_config_despacho():
    d = Config().despacho
    assert d.pie_fallo[1] == "Palacio de Justicia Carrera 52 número 42 – 73. Piso 19"
    assert d.juez == "SANTIAGO ALEJANDRO CADAVID DUQUE"
    assert d.correo == "pcto03med@cendoj.ramajudicial.gov.co"
    assert d.cierre_fallo == "NOTIFÍQUESE Y CÚMPLASE"
    assert len(d.pie_auto) == 2


def test_esquema_anterior_se_carga():
    ing = Ingesta.model_validate({
        "documentos": [{
            "doc_id": "d1", "ruta": "a", "nombre": "a", "instancia": "1a",
            "rol": "otro", "sha256": "x", "paginas": [],
        }],
    })
    assert ing.esperados_faltantes == [] and ing.alertas_lectura == [] and ing.ignorados == []
    assert ing.documentos[0].evidencia == "" and ing.documentos[0].rol_origen == "contenido"
    d = Decision.model_validate({"accion": "decidir", "resultado": "CONFIRMAR", "sustitutiva": "NEGAR", "eje": "x"})
    assert d.numerales_libres == [] and d.generar_formato is False and d.fecha_fallo is None
    assert d.etiqueta_encabezado == ""


def test_rol_anexo():
    Doc(doc_id="d", ruta="r", nombre="n", instancia="1a", rol="anexo", sha256="x", paginas=[])


def test_metadatos_nuevos():
    m = Metadatos()
    assert m.impugnantes == [] and m.resultado_a_quo is None and m.resultado_a_quo_se is None
    assert m.genero_accionadas is None and m.genero_vinculadas is None
    m = MetadatosLLM()
    assert m.impugnantes == [] and m.resultado_a_quo == "" and m.resultado_a_quo_se == ""
    assert m.genero_accionadas == "" and m.genero_vinculadas == ""
    m = Metadatos()
    assert m.juzgado_a_quo_plural is False and m.juzgado_a_quo_derivado is False
    assert not hasattr(MetadatosLLM(), "juzgado_a_quo_numero")
    assert Orden(destinatario="X", conducta="y").mismo_termino is False
    assert DatosAuto().fecha is None


def test_confirmar_no_exige_sustitutiva():
    d = Decision.model_validate({"accion": "decidir", "resultado": "CONFIRMAR", "eje": "x"})
    assert d.errores() == []
    d = Decision.model_validate({"accion": "decidir", "resultado": "REVOCAR", "eje": "x"})
    assert any("sustitutiva" in e for e in d.errores())


def test_metadatos_llm_normaliza_enums_y_nulos():
    m = MetadatosLLM.model_validate(
        {"impugnante_rol": " Accionante ", "genero_accionadas": "F", "genero_vinculadas": "M", "accionante": None, "accionadas": None}
    )
    assert (m.impugnante_rol, m.genero_accionadas, m.genero_vinculadas) == ("accionante", "f", "m")
    assert m.accionante == "" and m.accionadas == []


def test_metadatos_vacios_del_modelo_pasan_a_none_en_los_del_codigo():
    m = Metadatos.model_validate(MetadatosLLM().model_dump())
    assert m.impugnante_rol is None and m.genero_accionadas is None and m.accionante is None


def _evidencia(**kw) -> EvidenciaDoc:
    return EvidenciaDoc(**{"doc_id": "1a-004", "pagina": 2, "cita": "confiero poder especial al doctor Pedro Ficticio", **kw})


def test_identificacion_ida_y_vuelta_por_json():
    poder = Poder(
        tipo="poder",
        evidencia=_evidencia(cobertura=0.92, inicio=10, fin=58),
        otorgante="Ana Gerente",
        parte="Sociedad Ficticia S.A.S.",
        cadena=Cadena(estado="confirmada", otorgante="Ana Gerente", cargo="representante legal", evidencia=_evidencia(doc_id="1a-005", pagina=1, ocr=True)),
    )
    ident = Identificacion(
        ingesta_sha="abc",
        apoderados=[
            Apoderado(
                id="ap-0123456789",
                nombre="Pedro Ficticio",
                parte="Sociedad Ficticia S.A.S.",
                rol_parte="accionada",
                tipo_persona="juridica",
                cedula="43000021",
                tarjeta="97551",
                cedula_fuente=_evidencia(),
                menciones=[_evidencia(pagina=1)],
                poderes=[poder],
                ajenos=[poder.model_copy(update={"parte": "Otra Parte"})],
                motivos=["No se halló poder para Otra Parte."],
            )
        ],
        sin_apoderado=[ParteSinApoderado(nombre="Juana Pérez", rol_parte="accionante", nota="actúa en nombre propio")],
        alertas=["ALERTA: x"],
        documentos_revisados=7,
    )
    datos = json.loads(ident.model_dump_json())
    assert Identificacion.model_validate(datos) == ident
    assert datos["version"] == 1 and datos["apoderados"][0]["poderes"][0]["cadena"]["evidencia"]["ocr"] is True


def test_modelos_de_apoderados_por_defecto():
    ident = Identificacion()
    assert (ident.version, ident.ingesta_sha, ident.apoderados, ident.sin_apoderado, ident.alertas, ident.documentos_revisados) == (1, "", [], [], [], 0)
    ev = _evidencia()
    assert (ev.cobertura, ev.ocr, ev.inicio, ev.fin) == (0.0, False, None, None)
    p = Poder(tipo="sustitucion", evidencia=ev)
    assert p.cadena == Cadena() and p.cadena.estado == "no_aplica" and p.cadena.evidencia is None
    assert Poder(tipo="poder", evidencia=ev).cadena is not p.cadena
    a = Apoderado(id="ap-x", nombre="N", parte="P")
    assert (a.rol_parte, a.tipo_persona, a.cedula, a.tarjeta, a.cedula_fuente) == ("otro", "natural", None, None, None)
    assert a.menciones == a.poderes == a.ajenos == a.motivos == []


@pytest.mark.parametrize(
    "modelo, datos",
    [
        (Cadena, {"estado": "inventada"}),
        (Poder, {"tipo": "mandato", "evidencia": {"doc_id": "d", "pagina": 1, "cita": "c"}}),
        (Apoderado, {"id": "ap-x", "nombre": "N", "parte": "P", "tipo_persona": "otra"}),
        (ParteSinApoderado, {"nombre": "N", "rol_parte": "impugnante"}),
    ],
)
def test_modelos_de_apoderados_rechazan_valores_fuera_del_dominio(modelo, datos):
    with pytest.raises(ValidationError):
        modelo.model_validate(datos)


def test_estado_declara_apoderados():
    assert "apoderados" in Estado.__annotations__


def _modelos_llm() -> list[type]:
    return [ApoderadosLLM, ParteLLM, AbogadoLLM, MencionLLM, PoderLLM]


@pytest.mark.parametrize("modelo", _modelos_llm(), ids=lambda m: m.__name__)
def test_esquema_de_apoderados_es_estricto_y_describe_cada_campo(modelo):
    esquema = modelo.model_json_schema()
    defs = esquema.get("$defs", {})
    for nodo in [esquema, *defs.values()]:
        assert nodo["required"] == list(nodo["properties"])
        assert all(p.get("description") for p in nodo["properties"].values())
    assert "anyOf" not in json.dumps(esquema)


def test_esquema_de_apoderados_para_anthropic_y_gemini():
    formato = to_json_output_format(ApoderadosLLM)
    assert formato["type"] == "json_schema"
    defs = formato["schema"]["$defs"]
    assert set(defs) == {"ParteLLM", "AbogadoLLM", "MencionLLM", "PoderLLM"}
    for nombre, nodo in [("raíz", formato["schema"]), *defs.items()]:
        assert nodo["required"] == list(nodo["properties"]), nombre
        assert nodo.get("additionalProperties") is False, nombre
    assert defs["PoderLLM"]["properties"]["tipo"]["enum"] == ["poder", "sustitucion", "certificado_existencia"]
    assert defs["ParteLLM"]["properties"]["rol_parte"]["enum"] == ["accionante", "accionada", "vinculada", "otro"]
    convertido = esquema_gemini(ApoderadosLLM)
    poder = convertido["properties"]["abogados"]["items"]["properties"]["poderes"]["items"]
    assert poder["required"] == list(PoderLLM.model_fields) and poder["properties"]["certificado_pagina"]["type"] == "integer"
    assert "$ref" not in json.dumps(convertido)


def test_apoderados_llm_normaliza_nulos_y_enums():
    salida = ApoderadosLLM.model_validate(
        {
            "partes": [
                {"nombre": "Sociedad Ficticia S.A.S.", "rol_parte": " Accionadas ", "con_abogado": True},
                {"nombre": None, "rol_parte": "Vinculada", "con_abogado": None},
                {"nombre": "X", "rol_parte": None, "con_abogado": False},
            ],
            "abogados": [
                {
                    "nombre": "Pedro Ficticio",
                    "parte": "Sociedad Ficticia S.A.S.",
                    "cedula_texto": None,
                    "tarjeta_texto": "97.551",
                    "menciones": None,
                    "poderes": [
                        {"tipo": "Sustitución", "doc_id": "1a-004", "pagina": "3", "cita": "c", "otorgante": None,
                         "cargo_otorgante": None, "certificado_doc_id": None, "certificado_pagina": None},
                        {"tipo": "certificado de existencia", "doc_id": "1a-005", "pagina": 1, "cita": "c", "otorgante": "",
                         "cargo_otorgante": "", "certificado_doc_id": "", "certificado_pagina": 0},
                        {"tipo": None, "doc_id": "1a-006", "pagina": 2, "cita": "c", "otorgante": "Ana",
                         "cargo_otorgante": "representante legal", "certificado_doc_id": "1a-005", "certificado_pagina": 1},
                    ],
                }
            ],
        }
    )
    assert [(p.rol_parte, p.con_abogado, p.nombre) for p in salida.partes] == [
        ("accionada", True, "Sociedad Ficticia S.A.S."),
        ("vinculada", False, ""),
        ("otro", False, "X"),
    ]
    abogado = salida.abogados[0]
    assert abogado.cedula_texto == "" and abogado.tarjeta_texto == "97.551" and abogado.menciones == []
    assert [p.tipo for p in abogado.poderes] == ["sustitucion", "certificado_existencia", "poder"]
    assert abogado.poderes[0].pagina == 3 and abogado.poderes[0].otorgante == "" and abogado.poderes[0].certificado_pagina == 0
    assert ApoderadosLLM.model_validate({"partes": None, "abogados": None}) == ApoderadosLLM()
    assert ApoderadosLLM.model_validate_json(salida.model_dump_json()) == salida
    with pytest.raises(ValidationError):
        PoderLLM.model_validate({"tipo": "mandato"})
    with pytest.raises(ValidationError):
        ParteLLM.model_validate({"rol_parte": "juez"})


def test_las_listas_por_defecto_del_modelo_no_se_comparten():
    a, b = ApoderadosLLM.model_validate({"partes": None}), ApoderadosLLM()
    a.partes.append(ParteLLM(nombre="X"))
    assert b.partes == [] and ApoderadosLLM().partes == []
