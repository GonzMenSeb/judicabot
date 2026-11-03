from tutela2.config import Config
from tutela2.models import Decision, Doc, Ingesta, Metadatos, MetadatosLLM, Orden, DatosAuto


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
