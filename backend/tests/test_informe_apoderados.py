from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import get_args

import pytest
from test_ajustes_apoderados import AMBAR, CEDULA_ROJO, CEDULA_VERDE, ROJO, _consulta, _ident
from test_apoderados import ABOGADA, CC_ABOGADA_PLANA
from test_render import construir_estado, lineas, resaltadas_por_fila, seccion_informe

from tutela2 import apoderados, registro_apoderados, render
from tutela2.config import Config
from tutela2.esquemas_apoderados import EstadoVigencia
from tutela2.estado_apoderados import MOTIVO_NO_INSCRITO, evaluar
from tutela2.models import EvidenciaDoc, Identificacion, ParteSinApoderado
from tutela2.registro_apoderados import Ajuste, Revision
from tutela2.vigencia import CertificadoVigencia

TITULO = "III. APODERADOS"
CABECERA = "Apoderado | Parte | Tarjeta profesional | Consulta | Código de verificación | Facultad | Estado final | Revisión"
CODIGO = "ab" * 32


def _caso(tmp_path: Path) -> Path:
    """Un caso con los tres apoderados de ``test_ajustes_apoderados``: el verde consultado desde la extensión,
    el rojo con certificado subido y revisado, y la abogada de la EPS con correcciones a mano."""
    caso = tmp_path / "caso"
    caso.mkdir()
    ident = _ident().model_copy(
        update={"sin_apoderado": [ParteSinApoderado(nombre="Secretaría de Salud", rol_parte="vinculada", nota="x")]}
    )
    registro_apoderados.espejar(caso, ident)
    manual = EvidenciaDoc(doc_id="1a-008", pagina=1, cita=f"confiero poder especial a la doctora {ABOGADA}", cobertura=1.0)

    def llenar(reg):
        reg.consultas[CEDULA_VERDE] = _consulta(CEDULA_VERDE, "MARCELA ORTIZ PEÑA", "214883")
        reg.consultas[CEDULA_ROJO] = _consulta(
            CEDULA_ROJO, "CARLOS EDUARDO PINEDA RUIZ", "97551", "no_vigente", "SUSPENDIDO"
        ).model_copy(update={"origen": "manual"})
        reg.ajustes[AMBAR] = Ajuste(
            cedula=CC_ABOGADA_PLANA, poder_manual=manual, nota="  Lo indicó\nla abogada.  ", en="2026-11-17T15:50:00+00:00"
        )
        rojo = next(a for a in reg.identificacion.apoderados if a.id == ROJO)
        reg.revisiones[ROJO] = Revision(
            revisado=True, en="2026-11-17T16:05:00+00:00", huella=evaluar(rojo, reg).huella, nota="Revisado contra el certificado."
        )

    registro_apoderados.actualizar(caso, llenar)
    return caso


def _informe(tmp_path: Path, **estado) -> tuple[Path, list[str]]:
    ruta = render.render_informe({**construir_estado(), **estado}, Config(), tmp_path / "informe_verificacion.docx")
    return ruta, lineas(ruta)


def test_informe_tabla_de_apoderados(tmp_path):
    caso = _caso(tmp_path)
    ruta, texto = _informe(tmp_path, caso_dir=str(caso), apoderados=None)
    for titulo in ("II. CITAS NORMATIVAS (NO VERIFICADAS AUTOMÁTICAMENTE)", TITULO, "IV. ALERTAS POR NODO",
                   "V. ERRORES BLOQUEANTES VIGENTES", "VI. PENDIENTES Y VALORES POR DEFECTO", "VII. BITÁCORA DE LLAMADAS A LA IA"):
        assert titulo in texto
    seccion = seccion_informe(texto, TITULO)
    assert seccion[0] == (
        "3 apoderados: 1 verificado, 1 por revisar, 1 no verificado. Las cédulas van enmascaradas y las horas son de Colombia."
    )
    assert seccion[1] == CABECERA
    ambar, verde, rojo = seccion[2:5]
    assert verde == (
        "Marcela Ortiz Peña\nC.C. 43.•••.•21\nT.P. 214.883 | Marta Ejemplo\n(accionante) | "
        "Vigente\nConsulta automática desde el navegador | 17/11/2026 10:42 | "
        f"N.° 1234567\n{CODIGO} | Poder · Doc. 1a-001, p. 1 | Verificado | —"
    )
    assert rojo == (
        "Carlos Eduardo Pineda Ruiz\nC.C. 16.•••.•40\nT.P. 97.551 | Entidad Prestadora Uno\n(accionada) | "
        "No vigente\nCertificado subido por el despacho | 17/11/2026 10:42 | "
        f"N.° 1234567\n{CODIGO} | Poder · Doc. 1a-003, p. 1 | No verificado | Revisado el 17/11/2026 11:05"
    )
    assert ambar == (
        f"{ABOGADA}\nC.C. 1.017.•••.•67\nT.P. 287.415 | EPS HORIZONTE SALUD S.A.S.\n(accionada) | "
        "Sin consultar | — | — | Señalado a mano · Doc. 1a-008, p. 1 | Por revisar | —"
    )
    assert seccion[5:] == [
        "",
        "Por qué no quedaron verificados:",
        f"{ABOGADA}: Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial.",
        "Carlos Eduardo Pineda Ruiz: La tarjeta profesional 97551 figura como «SUSPENDIDO» en el certificado N.° 1234567.",
        "Correcciones a mano y notas de la revisión:",
        f"{ABOGADA}: poder señalado a mano en Doc. 1a-008, p. 1; cédula indicada a mano (17/11/2026 10:50). "
        "Nota: «Lo indicó la abogada.».",
        "Carlos Eduardo Pineda Ruiz, nota de la revisión: «Revisado contra el certificado.».",
        "Partes sin apoderado: Secretaría de Salud (vinculada).",
    ]
    # Lo que no quedó verificado va resaltado, como las citas por revisar.
    resaltadas = {nombre.split("\n")[0]: celdas for nombre, celdas in resaltadas_por_fila(ruta).items()}
    assert resaltadas["Marcela Ortiz Peña"] == []
    assert resaltadas[ABOGADA] == ["Por revisar"] and resaltadas["Carlos Eduardo Pineda Ruiz"] == ["No verificado"]
    # Ninguna cédula completa en el documento.
    with zipfile.ZipFile(ruta) as z:
        xml = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    for cedula in (CEDULA_VERDE, CEDULA_ROJO, CC_ABOGADA_PLANA):
        assert cedula not in xml and cedula not in "\n".join(texto)
    assert "sin alertas" not in "\n".join(seccion).lower()


def test_informe_cedula_tomada_del_certificado_subido_y_revision_vencida(tmp_path):
    caso = _caso(tmp_path)

    def cambiar(reg):
        reg.consultas[CC_ABOGADA_PLANA] = _consulta(CC_ABOGADA_PLANA, ABOGADA, "287415").model_copy(update={"origen": "manual"})
        reg.revisiones[ROJO] = reg.revisiones[ROJO].model_copy(update={"huella": "0" * 16})

    registro_apoderados.actualizar(caso, cambiar)
    _, texto = _informe(tmp_path, caso_dir=str(caso))
    seccion = seccion_informe(texto, TITULO)
    assert seccion[0].startswith("3 apoderados: 2 verificados, 0 por revisar, 1 no verificado.")
    assert seccion[2].endswith("| Verificado | —")
    assert seccion[4].endswith("| No verificado | Revisión vencida (del 17/11/2026 11:05)")
    assert any("cédula tomada del certificado subido" in linea for linea in seccion)


def test_informe_usa_la_identificacion_del_estado_si_falta_el_espejo(tmp_path):
    ident = _ident()
    _, texto = _informe(tmp_path, caso_dir=str(tmp_path), apoderados=ident.model_dump(mode="json"))
    seccion = seccion_informe(texto, TITULO)
    assert seccion[0] == (
        "3 apoderados: 0 verificados, 3 por revisar, 0 no verificados. Las cédulas van enmascaradas y las horas son de Colombia."
    )
    assert [fila.split(" | ")[2] for fila in seccion[2:5]] == ["Sin cédula para consultarla", "Sin consultar", "Sin consultar"]
    assert not registro_apoderados.carpeta(tmp_path).exists()


@pytest.mark.parametrize(
    "identificacion, esperado",
    [
        (None, "El caso no tiene identificación de apoderados: verifique a mano"),
        (Identificacion(alertas=[apoderados.ALERTA_FALLA]), "No se pudieron identificar los apoderados: verifique a mano"),
        (Identificacion(ingesta_sha="x", documentos_revisados=4), "No se identificaron apoderados en el expediente."),
    ],
)
def test_informe_sin_apoderados_que_mostrar(tmp_path, identificacion, esperado):
    valor = identificacion.model_dump(mode="json") if identificacion is not None else None
    _, texto = _informe(tmp_path, caso_dir=None, apoderados=valor)
    seccion = seccion_informe(texto, TITULO)
    assert len(seccion) == 1 and seccion[0].startswith(esperado)


def test_informe_con_registro_danado_lo_dice_sin_reescribirlo(tmp_path):
    caso = _caso(tmp_path)
    ruta = registro_apoderados.ruta(caso)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["consultas"][CEDULA_VERDE]["estado"] = "vencida"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    original = ruta.read_bytes()
    _, texto = _informe(tmp_path, caso_dir=str(caso), apoderados=_ident().model_dump(mode="json"))
    assert seccion_informe(texto, TITULO) == [
        "No se pudo leer el registro de apoderados del caso: verifique a mano la tarjeta profesional y el poder de cada abogado."
    ]
    assert ruta.read_bytes() == original


def test_informe_cedula_no_inscrita(tmp_path):
    caso = _caso(tmp_path)
    no_inscrito = registro_apoderados.ConsultaVigencia(
        estado="no_inscrito",
        origen="manual",
        consultado_en="2026-11-17T15:42:00+00:00",
        certificado="certificados/x.pdf",
        sha256="cd" * 32,
        datos=CertificadoVigencia(inscrito=False, documento=CC_ABOGADA_PLANA, numero="7654321", codigo_verificacion=CODIGO),
    )
    registro_apoderados.actualizar(caso, lambda reg: reg.consultas.update({CC_ABOGADA_PLANA: no_inscrito}))
    _, texto = _informe(tmp_path, caso_dir=str(caso))
    seccion = seccion_informe(texto, TITULO)
    ambar = seccion[2]
    assert ambar.startswith(f"{ABOGADA}\nC.C. 1.017.•••.•67\n")
    # La cédula la indicó a mano quien revisa: ámbar, no rojo.
    assert "| No inscrito en el Registro Nacional de Abogados\nCertificado subido por el despacho | 17/11/2026 10:42 | " in ambar
    assert ambar.endswith("| Por revisar | —")
    assert f"{ABOGADA}: {MOTIVO_NO_INSCRITO}" in seccion
    assert CC_ABOGADA_PLANA not in "\n".join(texto)


def test_cada_estado_de_vigencia_tiene_su_rotulo_en_el_informe():
    assert set(get_args(EstadoVigencia)) == set(render._TARJETA_APODERADO)
