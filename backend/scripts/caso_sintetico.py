from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.shared import Cm, Pt

RADICADO = "05001408800920260041200"
RADICADO_2A = RADICADO[:21] + "01"
RAD_ESPACIADO = "05001 40 88 009 2026 00412 00"
RAD_CORTO = "2026-00412"

ACCIONANTE = "MARTA INÉS QUINTERO BEDOYA"
CEDULA = "43.999.101"
CEDULA_PLANA = "43999101"
ACCIONADA = "EPS HORIZONTE SALUD S.A.S."
NIT = "800.000.412-0"
NIT_PLANO = "800000412"
REPRESENTANTE = "JORGE ENRIQUE PALACIO VARGAS"
EMPLEADOR = "DISTRIBUCIONES EL FARO S.A.S."
JUEZ_1A = "RICARDO ALBERTO SALAZAR NIETO"
JUEZ_2A = "PATRICIA ELENA RESTREPO ZULUAGA"
OFICIAL = "LAURA CAMILA OSPINA RÍOS"

CORREO_JUZGADO = "j09pmcgmed@ejemplo.test"
CORREO_ACCIONANTE = "marta.quintero@ejemplo.test"
CORREO_ACCIONADA = "notificaciones@horizontesalud.ejemplo.test"

JUZGADO_MAYUS = "JUZGADO NOVENO PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS"

DECISION_POR_DEFECTO = {
    "accion": "decidir",
    "instruccion": "",
    "resultado": "REVOCAR",
    "sustitutiva": "AMPARAR",
    "eje": (
        "Se revoca la sentencia que negó el amparo porque la falta de pago de las incapacidades "
        "compromete el mínimo vital de la accionante y de su hijo menor, y la vía ante la Superintendencia "
        "no resulta eficaz en este caso."
    ),
    "por_reparo": [],
    "derechos": [
        {"derecho": "mínimo vital", "disposicion": "AMPARA"},
        {"derecho": "salud", "disposicion": "AMPARA"},
    ],
    "ordenes": [
        {
            "verbo": "ORDENAR",
            "destinatario": "la EPS HORIZONTE SALUD S.A.S.",
            "via_representante": True,
            "conducta": "resuelva de fondo y pague a la accionante las incapacidades médicas pendientes que cumplan los requisitos legales",
            "plazo": {"n": 48, "unidad": "horas_habiles"},
            "condicion": "",
            "literales": [],
            "mismo_termino": False,
        }
    ],
    "desvincular": [],
    "prevenir": [],
    "compulsa": None,
    "numerales": {"notificar": True, "remitir_corte": True},
    "decidido_por": "caso_sintetico",
    "previo_sha256": "",
    "numerales_libres": [],
    "orden_numerales": [],
    "generar_formato": True,
    "fecha_fallo": None,
    "fecha_oficio": None,
    "etiqueta_encabezado": "",
}


def _acta(radicado: str, clase: str, numero: str, despacho: str, fecha: str, secuencia: str, juez: str, partes: list[list[str]]):
    bloques: list[tuple] = [
        ("centro", "REPÚBLICA DE COLOMBIA"),
        ("centro", "RAMA JUDICIAL"),
        ("centro", f"ACTA INDIVIDUAL DE REPARTO          Fecha: {fecha}"),
        ("izq", "NÚMERO RADICACIÓN:"),
        ("izq", radicado),
        ("izq", f"CLASE PROCESO:\t{clase}"),
        ("izq", f"NÚMERO DESPACHO:\t{numero}\tSECUENCIA:\t{secuencia}"),
        ("izq", f"TIPO REPARTO:\tEN LÍNEA\tFECHA REPARTO:\t{fecha}"),
        ("izq", f"REPARTIDO AL DESPACHO:\t{despacho}"),
        ("izq", f"JUEZ / MAGISTRADO:\t{juez}"),
        (
            "tabla",
            [["TIPO ID", "IDENTIFICACIÓN", "NOMBRE", "APELLIDO", "PARTE"]] + partes,
        ),
        ("centro", "GENERADO AUTOMÁTICAMENTE"),
        ("centro", "SERVIDOR JUDICIAL"),
    ]
    return bloques


def _partes_acta() -> list[list[str]]:
    return [
        ["CÉDULA DE CIUDADANIA", CEDULA_PLANA, "MARTA INÉS", "QUINTERO BEDOYA", "DEMANDANTE/ACCIONANTE"],
        ["NIT", NIT_PLANO, "EPS HORIZONTE", "SALUD S.A.S.", "DEMANDADO/INDICIADO/CAUSANTE"],
    ]


def _escrito_tutela() -> list[tuple]:
    hechos = [
        f"Soy trabajadora dependiente de la empresa {EMPLEADOR}, donde me desempeño como auxiliar administrativa con un salario mensual de $1.800.000, y estoy afiliada como cotizante a la {ACCIONADA}.",
        "Soy madre cabeza de familia y tengo a mi cargo a mi hijo de nueve años, quien depende económicamente de mí. No cuento con otras fuentes de ingresos ni con rentas o bienes que me permitan sostener los gastos del hogar.",
        "El 15 de junio de 2026 mi médico tratante ordenó una incapacidad por una lesión de columna lumbar que requirió manejo quirúrgico, la cual fue prorrogada en tres ocasiones hasta el 12 de septiembre de 2026, para un total de noventa días.",
        "Mi empleador pagó los dos primeros días de incapacidad y radicó ante la EPS las transcripciones de las incapacidades restantes dentro de los términos señalados por la normativa.",
        "A la fecha de presentación de esta tutela la EPS no ha pagado las incapacidades correspondientes a los períodos posteriores al tercer día, y en el portal de consulta aparecen como «en validación documental» sin que se me haya indicado qué documento falta.",
        "Presenté tres solicitudes escritas (radicados internos 2026-1187, 2026-1302 y 2026-1415) pidiendo el pago o, en su defecto, que se me informara con precisión la razón de la demora. Solo recibí respuestas genéricas que remiten a un trámite que continúa abierto.",
        "Durante estos meses he debido pagar el canon de arrendamiento, los servicios públicos, el transporte a las citas médicas y la alimentación de mi hijo con préstamos de familiares, y estoy en mora con el arrendador, quien me ha advertido que pedirá la entrega del inmueble.",
        "La suma que se me adeuda por concepto de incapacidades asciende aproximadamente a $3.600.000, valor que constituye la única fuente de recursos con la que contaba durante mi recuperación.",
    ]
    pretensiones = [
        "Se amparen mis derechos fundamentales al mínimo vital y a la salud.",
        f"Se ordene a la {ACCIONADA} que, en el término de cuarenta y ocho (48) horas, reconozca y pague las incapacidades médicas pendientes a mi favor.",
        "Se prevenga a la entidad accionada para que en lo sucesivo tramite y pague las incapacidades dentro de los términos legales.",
    ]
    b: list[tuple] = [
        ("izq", "Medellín, 14 de septiembre de 2026"),
        ("izq", "Señor\nJUEZ DE TUTELAS (REPARTO)\nMedellín\nE. S. D."),
        ("izq", f"Referencia: ACCIÓN DE TUTELA de {ACCIONANTE} contra {ACCIONADA}"),
        (
            "p",
            f"{ACCIONANTE}, mayor de edad, vecina de Medellín, identificada con cédula de ciudadanía No. {CEDULA}, actuando en nombre propio, acudo ante usted para promover ACCIÓN DE TUTELA, de conformidad con el artículo 86 de la Constitución Política y el Decreto 2591 de 1991, en contra de la {ACCIONADA}, por la vulneración de mis derechos fundamentales al mínimo vital y a la salud, con base en los siguientes",
        ),
        ("centro", "HECHOS"),
    ]
    ordinales = ["PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO", "SEXTO", "SÉPTIMO", "OCTAVO"]
    b += [("p", f"{o}: {t}") for o, t in zip(ordinales, hechos)]
    b += [("centro", "PRETENSIONES")]
    b += [("p", f"{o}: {t}") for o, t in zip(["PRIMERA", "SEGUNDA", "TERCERA"], pretensiones)]
    b += [
        ("centro", "FUNDAMENTOS DE DERECHO"),
        (
            "p",
            "Invoco los artículos 1, 11, 48, 49, 53 y 86 de la Constitución Política, el artículo 206 de la Ley 100 de 1993 y el Decreto 2591 de 1991. La incapacidad médica sustituye el salario del trabajador mientras no puede laborar, y su falta de pago afecta de manera directa el mínimo vital cuando, como en mi caso, es el único ingreso del hogar.",
        ),
        ("centro", "PRUEBAS"),
        (
            "p",
            "Aporto copia de mi cédula de ciudadanía, de las incapacidades expedidas por mi médico tratante, de las tres solicitudes presentadas a la EPS y de la constancia de consulta del portal. Juro bajo la gravedad del juramento que no he presentado otra acción de tutela por los mismos hechos.",
        ),
        ("centro", "NOTIFICACIONES"),
        ("izq", f"Recibo notificaciones en el correo electrónico {CORREO_ACCIONANTE}. La accionada recibe notificaciones en {CORREO_ACCIONADA}."),
        ("izq", f"Atentamente,\n\n{ACCIONANTE}\nC.C. {CEDULA}"),
    ]
    return b


def _auto_admisorio() -> list[tuple]:
    return [
        (
            "izq",
            f"Constancia: Le informo señor Juez que, en la fecha, se recibió por reparto la acción de tutela promovida por {ACCIONANTE} identificada con la cédula de ciudadanía No. {CEDULA}, en contra de la {ACCIONADA}. Se radicó con el No. {RAD_CORTO}. A Despacho.",
        ),
        ("izq", "Medellín, 15 de septiembre de 2026."),
        ("izq", f"{OFICIAL}\nOficial Mayor"),
        ("centro", "JUZGADO NOVENO PENAL MUNICIPAL\nCON FUNCIÓN DE CONTROL DE GARANTÍAS"),
        ("centro_n", "Medellín, quince (15) de septiembre de dos mil veintiséis (2026)"),
        (
            "p",
            f"Cumplidos los requisitos exigidos en el Decreto 2591 de 1991, SE ADMITE la presente acción de tutela promovida por {ACCIONANTE} identificada con la cédula de ciudadanía No. {CEDULA}, quien actúa en nombre propio, en contra de la {ACCIONADA}.",
        ),
        (
            "p",
            "Practíquense las pruebas que se consideren pertinentes y notifíquese de conformidad con lo que indica el artículo 16 del Decreto antes citado, advirtiéndole a la accionada que debe contestar la demanda en el término perentorio de DOS (2) DÍAS.",
        ),
        ("centro", "NOTIFÍQUESE Y CÚMPLASE"),
        ("centro", f"{JUEZ_1A}\nJuez"),
    ]


def _contestacion() -> list[tuple]:
    return [
        ("izq", "Medellín, 17 de septiembre de 2026"),
        ("izq", "Señor\nJUEZ NOVENO PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS\nMedellín\nE. S. D."),
        ("izq", f"Referencia: Contestación de la acción de tutela\nRadicado: {RAD_ESPACIADO}\nAccionante: {ACCIONANTE}\nAccionada: {ACCIONADA}"),
        (
            "p",
            f"{REPRESENTANTE}, obrando como representante legal para asuntos judiciales de la {ACCIONADA}, identificada con NIT {NIT}, me permito dar contestación a la acción de tutela de la referencia en los siguientes términos.",
        ),
        ("centro", "FRENTE A LOS HECHOS"),
        (
            "p",
            "Es cierto que la accionante se encuentra afiliada a esta entidad en calidad de cotizante dependiente y que su empleador radicó las transcripciones de las incapacidades causadas entre el 15 de junio y el 12 de septiembre de 2026. No es cierto que la entidad se haya negado a pagarlas: las incapacidades se encuentran en revisión porque el certificado de la segunda prórroga no registra el diagnóstico ni la firma del médico tratante, y el 20 de agosto de 2026 se solicitó al empleador subsanar el documento sin que a la fecha lo haya hecho.",
        ),
        (
            "p",
            "Las solicitudes de la accionante fueron respondidas dentro de los términos, informándole el estado del trámite. La entidad no ha desconocido su derecho; el pago procederá una vez se complete la documentación exigida por la normativa vigente.",
        ),
        ("centro", "FRENTE A LAS PRETENSIONES"),
        (
            "p",
            "Me opongo a las pretensiones. La controversia sobre el reconocimiento de prestaciones económicas del sistema de salud tiene un mecanismo especial ante la Superintendencia Nacional de Salud, que ejerce funciones jurisdiccionales, y la accionante no ha demostrado un perjuicio irremediable ni la afectación concreta de su mínimo vital. La atención en salud de la accionante no ha sido suspendida en ningún momento.",
        ),
        ("centro", "SOLICITUD"),
        (
            "p",
            "Solicito declarar improcedente la acción de tutela o, en subsidio, negar el amparo por inexistencia de vulneración atribuible a la entidad.",
        ),
        ("izq", f"Atentamente,\n\n{REPRESENTANTE}\nRepresentante legal para asuntos judiciales\n{ACCIONADA}\n{CORREO_ACCIONADA}"),
    ]


def _parrafos_fallo() -> list[tuple]:
    b: list[tuple] = [
        ("centro", "REPÚBLICA DE COLOMBIA\nRAMA JUDICIAL DEL PODER PÚBLICO"),
        ("centro", JUZGADO_MAYUS),
        ("centro_n", "Medellín, veintiocho (28) de septiembre de dos mil veintiséis (2026)"),
        (
            "izq",
            f"Radicado:\t{RAD_ESPACIADO}\nAccionante:\t{ACCIONANTE}\nAccionada:\t{ACCIONADA}\nDecisión:\tNIEGA\nFallo:\t412/2026",
        ),
        (
            "p",
            f"Procede el Despacho a emitir el fallo de tutela correspondiente a la acción que, amparada en el artículo 86 de la Carta Política y sus decretos reglamentarios, promovió {ACCIONANTE}, identificada con la cédula de ciudadanía No. {CEDULA}, quien actúa en nombre propio, en contra de la {ACCIONADA}, en procura de la protección de sus derechos fundamentales al mínimo vital y a la salud.",
        ),
        ("centro", "ANTECEDENTES"),
        ("centro", "Hechos y petición"),
        (
            "p",
            f"Manifestó la accionante que es trabajadora dependiente de {EMPLEADOR}, con un salario mensual de $1.800.000, y que se encuentra afiliada como cotizante a la entidad accionada. Refirió que es madre cabeza de familia, que tiene a su cargo a un hijo de nueve años y que no cuenta con otras fuentes de ingresos.",
        ),
        (
            "p",
            "Señaló que el 15 de junio de 2026 su médico tratante ordenó una incapacidad por una lesión de columna lumbar que requirió manejo quirúrgico, prorrogada en tres ocasiones hasta el 12 de septiembre de 2026, para un total de noventa días. Aseguró que su empleador radicó ante la EPS las transcripciones de las incapacidades posteriores al tercer día y que la entidad no las ha pagado, pues en el portal figuran «en validación documental» sin que se le haya informado qué documento falta.",
        ),
        (
            "p",
            "Añadió que presentó tres solicitudes escritas y solo recibió respuestas genéricas; que ha sostenido los gastos del hogar con préstamos de familiares; que se encuentra en mora con el pago del arriendo y que la suma adeudada asciende aproximadamente a $3.600.000.",
        ),
        (
            "p",
            "Petición: Por lo anterior, solicitó la tutela de los derechos fundamentales invocados, con miras a que se ordene a la entidad accionada reconocer y pagar, en el término de cuarenta y ocho horas, las incapacidades médicas pendientes, y que se la prevenga para que en lo sucesivo las tramite dentro de los términos legales.",
        ),
        ("centro", "Actuación del Despacho"),
        (
            "p",
            "La solicitud fue asignada a este Despacho para su trámite, por lo que, al constatar que se reunían los requisitos del Decreto 2591 de 1991, se avocó el conocimiento mediante auto del 15 de septiembre de 2026 y se corrió traslado del libelo a la entidad accionada, a fin de que ejerciera su derecho de defensa y aportara las pruebas que pretendiera hacer valer.",
        ),
        ("centro", f"Respuesta de la {ACCIONADA}"),
        (
            "p",
            f"La entidad, por intermedio de {REPRESENTANTE}, allegó respuesta oportuna en la que aceptó la afiliación de la accionante y la radicación de las transcripciones de las incapacidades causadas entre el 15 de junio y el 12 de septiembre de 2026. Indicó que no se ha negado a pagarlas, pues se encuentran en revisión debido a que el certificado de la segunda prórroga no registra el diagnóstico ni la firma del médico tratante, circunstancia que fue puesta en conocimiento del empleador el 20 de agosto de 2026 sin que hubiera sido subsanada.",
        ),
        (
            "p",
            "Sostuvo, además, que la controversia sobre el reconocimiento de prestaciones económicas tiene un mecanismo especial ante la Superintendencia Nacional de Salud, que la accionante no acreditó un perjuicio irremediable ni la afectación concreta de su mínimo vital y que la atención en salud nunca ha sido suspendida. Solicitó declarar improcedente el amparo o negarlo por inexistencia de vulneración.",
        ),
        ("centro", "CONSIDERACIONES DEL JUZGADO"),
        ("centro", "Competencia"),
        (
            "p",
            "Este Despacho es competente para conocer y fallar la presente acción de tutela, de conformidad con lo previsto en el artículo 86 de la Constitución Política, el artículo 37 del Decreto 2591 de 1991 y el Decreto 333 de 2021, en tanto la presunta vulneración se produce en el lugar donde tiene su domicilio la accionante y la entidad accionada es una persona jurídica de derecho privado que presta el servicio público de salud.",
        ),
        ("centro", "Problema jurídico"),
        (
            "p",
            "Corresponde al Despacho determinar si la entidad accionada vulneró los derechos fundamentales al mínimo vital y a la salud de la accionante al no pagar las incapacidades médicas causadas entre el 15 de junio y el 12 de septiembre de 2026, y si la acción de tutela es el mecanismo procedente para obtener ese pago.",
        ),
        ("centro", "Marco normativo"),
        (
            "p",
            "El artículo 86 de la Constitución Política consagra la acción de tutela como un mecanismo preferente y sumario para la protección inmediata de los derechos fundamentales, de carácter subsidiario, de manera que solo procede cuando el afectado no dispone de otro medio de defensa judicial idóneo y eficaz, o cuando, existiendo, se utiliza de manera transitoria para evitar un perjuicio irremediable. El Decreto 2591 de 1991 desarrolla este presupuesto en su artículo 6.",
        ),
        (
            "p",
            "La incapacidad por enfermedad general es una prestación económica del Sistema General de Seguridad Social en Salud que, conforme al artículo 206 de la Ley 100 de 1993, busca sustituir el ingreso del trabajador mientras permanece imposibilitado para laborar. La jurisprudencia constitucional ha reconocido que, por su vínculo con la subsistencia del trabajador y de su familia, su falta de pago puede comprometer el mínimo vital, pero ha exigido que esa afectación se acredite de manera concreta y no se presuma.",
        ),
        (
            "p",
            "Por su parte, el artículo 41 de la Ley 1122 de 2007, modificado por la Ley 1949 de 2019, atribuyó a la Superintendencia Nacional de Salud funciones jurisdiccionales para conocer, a prevención, de los conflictos relacionados con el reconocimiento económico de prestaciones por parte de las entidades promotoras de salud. Ese procedimiento es preferente, sumario y de decisión en plazos breves, por lo que, en principio, constituye el medio ordinario de defensa frente a la controversia que plantea la accionante.",
        ),
        (
            "p",
            "Cuando el accionante invoca la afectación del mínimo vital, el juez de tutela debe verificar, con base en las pruebas allegadas, que la falta del ingreso reclamado es la causa de una privación real de lo indispensable para vivir en condiciones dignas, que no existen otros ingresos con los cuales sufragar los gastos básicos y que el mecanismo ordinario, en las circunstancias particulares, carece de la eficacia necesaria para evitar un daño inminente y grave.",
        ),
        ("centro", "Legitimación y pruebas"),
        (
            "p",
            "La acción fue promovida por la titular de los derechos presuntamente vulnerados, quien actúa en nombre propio, por lo que se encuentra legitimada por activa. La entidad accionada es una empresa promotora de salud, particular que presta un servicio público y frente a la cual procede la tutela según el numeral 2 del artículo 42 del Decreto 2591 de 1991, de modo que está legitimada por pasiva.",
        ),
        (
            "p",
            "Obran en el expediente el escrito de tutela con sus anexos, el auto que avocó el conocimiento, su notificación a las partes y la respuesta de la entidad accionada. El Despacho no decretó pruebas adicionales por considerar suficientes las existentes para resolver, en atención al carácter preferente y sumario del trámite y a que la accionante tuvo la oportunidad de aportar los soportes de su situación económica al momento de presentar la solicitud.",
        ),
        ("centro", "Inmediatez y subsidiariedad"),
        (
            "p",
            "La acción se presentó el 14 de septiembre de 2026, dos días después de vencida la última incapacidad, por lo que cumple el requisito de inmediatez. En cuanto a la subsidiariedad, el análisis debe hacerse con flexibilidad cuando el accionante es una persona en condición de vulnerabilidad, pero tal flexibilidad no equivale a prescindir de la carga probatoria mínima que permita al juez advertir que el medio ordinario no es idóneo ni eficaz para el caso concreto.",
        ),
        ("centro", "Caso concreto"),
        (
            "p",
            "En el asunto examinado, la accionante acreditó su afiliación a la entidad accionada, la existencia de las incapacidades expedidas por su médico tratante y la presentación de tres solicitudes ante la EPS. La entidad, por su parte, reconoció que las transcripciones fueron radicadas y que el pago se encuentra detenido por una inconsistencia documental en la segunda prórroga, que atribuyó al empleador.",
        ),
        (
            "p",
            "Frente al derecho a la salud, el Despacho no encuentra vulneración alguna. De las pruebas allegadas se desprende que la accionante recibió el manejo quirúrgico y los controles médicos ordenados, y que la entidad no ha suspendido la prestación de servicios. La controversia gira exclusivamente en torno a una prestación económica, que no hace parte de la atención en salud propiamente dicha.",
        ),
        (
            "p",
            "En cuanto al mínimo vital, la accionante afirma que la suma adeudada constituye la única fuente de recursos del hogar. Sin embargo, no allegó prueba alguna que respalde esa afirmación: no aportó certificación de ingresos y egresos, extractos bancarios, contrato de arrendamiento, constancias de las deudas contraídas ni declaración que permita establecer la composición de su núcleo familiar. Tampoco explicó si durante el período de incapacidad recibió de su empleador algún pago o auxilio, ni si su vínculo laboral continúa vigente, circunstancia relevante porque el salario es la fuente ordinaria de su sustento.",
        ),
        (
            "p",
            "Aunque la condición de madre cabeza de familia exige una especial consideración, la jurisprudencia ha sido clara en que dicha calidad no releva al accionante de la carga de demostrar, así sea de manera sumaria, la afectación concreta de sus derechos. En este caso, el Despacho no cuenta con elementos de juicio que permitan concluir que existe un perjuicio irremediable que haga necesaria la intervención transitoria del juez de tutela.",
        ),
        (
            "p",
            "Adicionalmente, la accionante cuenta con un mecanismo idóneo, la acción jurisdiccional ante la Superintendencia Nacional de Salud, cuyo trámite sumario fue diseñado precisamente para resolver controversias como la que aquí se plantea, y no demostró que ese mecanismo carezca de eficacia en su situación particular. La inconsistencia señalada por la entidad en el certificado de la segunda prórroga debe, además, ser resuelta mediante la subsanación del documento por quien corresponda, asunto que escapa a la órbita del juez constitucional en ausencia de una vulneración acreditada.",
        ),
        (
            "p",
            "Por las razones expuestas, el Despacho negará el amparo solicitado, sin perjuicio de que la accionante acuda a la vía jurisdiccional ante la Superintendencia Nacional de Salud o de que, si llegare a acreditar con pruebas suficientes una afectación grave de su mínimo vital, promueva una nueva solicitud de protección.",
        ),
        ("centro", "DECISIÓN"),
        (
            "p",
            "En mérito de lo expuesto, el JUZGADO NOVENO PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS DE MEDELLÍN, administrando justicia en nombre de la República de Colombia y por autoridad de la ley,",
        ),
        ("centro", "RESUELVE"),
        (
            "p",
            f"PRIMERO: NEGAR el amparo a los derechos fundamentales al mínimo vital y a la salud invocados por {ACCIONANTE} en contra de la {ACCIONADA}, de acuerdo con lo expuesto en la parte motiva.",
        ),
        (
            "p",
            "SEGUNDO: NOTIFÍQUESE la presente decisión a las partes de conformidad con lo dispuesto en el artículo 5° del Decreto 306 de 1992, en armonía con el artículo 30 del Decreto 2591 de 1991.",
        ),
        (
            "p",
            "TERCERO: Si no fuere impugnada esta decisión dentro de los tres días siguientes a su notificación, envíese el expediente a la Honorable Corte Constitucional para su eventual revisión.",
        ),
        ("centro", "NOTIFÍQUESE Y CÚMPLASE"),
        ("centro", f"{JUEZ_1A}\nJUEZ"),
    ]
    return b


def _impugnacion() -> list[tuple]:
    return [
        ("izq", "Medellín, 1 de octubre de 2026"),
        ("izq", "Señor\nJUEZ NOVENO PENAL MUNICIPAL CON FUNCIÓN DE CONTROL DE GARANTÍAS\nMedellín\nE. S. D."),
        (
            "izq",
            f"Referencia: Impugnación del fallo de tutela\nRadicado: {RAD_ESPACIADO}\nAccionante: {ACCIONANTE}\nAccionada: {ACCIONADA}",
        ),
        (
            "p",
            f"Yo, {ACCIONANTE}, identificada con cédula de ciudadanía No. {CEDULA}, actuando en nombre propio y dentro del término legal, presento IMPUGNACIÓN contra el fallo del 28 de septiembre de 2026 mediante el cual se negó el amparo, para que el superior funcional lo revoque y proteja mis derechos fundamentales al mínimo vital y a la salud, con fundamento en los siguientes reparos.",
        ),
        ("centro", "PRIMER REPARO: LA FALTA DE PRUEBA DEL MÍNIMO VITAL SE ATRIBUYÓ A MÍ SIN VALORAR LO ACREDITADO"),
        (
            "p",
            "El fallo sostiene que no probé la afectación de mi mínimo vital, pero desconoce que afirmé bajo juramento que soy madre cabeza de familia, que mi hijo de nueve años depende de mí y que el único ingreso con el que contaba en mi recuperación eran las incapacidades. La entidad accionada no desvirtuó ninguna de esas afirmaciones. Tratándose de una persona en situación de debilidad manifiesta por enfermedad, el juez debió presumir la veracidad de mis afirmaciones o decretar de oficio las pruebas que echó de menos, en lugar de negar la protección por falta de documentos.",
        ),
        ("centro", "SEGUNDO REPARO: EL MECANISMO ANTE LA SUPERINTENDENCIA NO ES IDÓNEO NI EFICAZ EN MI CASO"),
        (
            "p",
            "El fallo remite a la vía jurisdiccional ante la Superintendencia Nacional de Salud sin analizar si, dadas mis circunstancias, esa vía permite evitar el daño que enfrento. Estoy en mora con el arriendo y el arrendador me ha advertido que pedirá la entrega del inmueble; esperar el trámite de un proceso adicional prolonga una afectación actual y grave sobre mi hijo y sobre mí. La entidad, además, tardó más de tres meses en responderme de fondo, lo que demuestra que sin una orden judicial el pago no se hará efectivo oportunamente.",
        ),
        ("centro", "PETICIÓN"),
        (
            "p",
            "Solicito al juez de segunda instancia revocar el fallo impugnado, amparar mis derechos fundamentales al mínimo vital y a la salud y ordenar a la entidad accionada el pago de las incapacidades pendientes.",
        ),
        ("izq", f"Atentamente,\n\n{ACCIONANTE}\nC.C. {CEDULA}\n{CORREO_ACCIONANTE}"),
    ]


def _auto_concede() -> list[tuple]:
    return [
        (
            "izq",
            f"Constancia: El fallo emitido en la acción de tutela con radicado {RAD_CORTO} se encuentra debidamente notificado; en tiempo oportuno la señora {ACCIONANTE}, identificada con la cédula de ciudadanía No. {CEDULA}, parte actora, presentó escrito de impugnación. Paso a Despacho en la fecha.",
        ),
        ("izq", "Medellín, 6 de octubre de 2026.\n\n" + f"{OFICIAL}\nOficial Mayor"),
        ("centro", "JUZGADO NOVENO PENAL MUNICIPAL\nDE CONTROL DE GARANTÍAS"),
        ("centro_n", "Medellín, seis (6) de octubre de dos mil veintiséis (2026)"),
        (
            "p",
            "Visto el informe anterior y conforme a lo establecido en la Ley 2213 de 2022, se concede la impugnación en contra del fallo emitido en esta acción de tutela; remítase a través del sistema aleatorio de reparto para que sea repartida entre los Jueces Penales de Circuito de la ciudad.",
        ),
        ("centro", "NOTIFÍQUESE Y CÚMPLASE"),
        ("centro", f"{JUEZ_1A}\nJuez"),
    ]


def _correo() -> list[tuple]:
    return [
        ("izq", "6/10/26, 9:54\tElementos enviados: Juzgado 9 Penal Municipal Control Garantías - Antioquia - Medellín - Correo"),
        ("izq", "Correo"),
        ("n", f"NOTIFICACIÓN AUTO QUE CONCEDE IMPUGNACIÓN TUTELA {RAD_CORTO}"),
        ("izq", f"Asunto\tNOTIFICACIÓN AUTO QUE CONCEDE IMPUGNACIÓN TUTELA {RAD_CORTO}"),
        ("izq", f"Desde Juzgado 9 Penal Municipal Control Garantías - Antioquia - Medellín <{CORREO_JUZGADO}>"),
        ("izq", "Fecha Mar 06/10/2026 9:54 AM"),
        ("izq", f"Para {CORREO_ACCIONANTE} <{CORREO_ACCIONANTE}>; {CORREO_ACCIONADA} <{CORREO_ACCIONADA}>"),
        ("izq", "2 archivos adjuntos (191 KB)\n006.pdf; 007.pdf;"),
        ("centro", "JUZGADO NOVENO PENAL MUNICIPAL\nDE CONTROL DE GARANTÍAS"),
        ("centro_n", "Medellín, seis (6) de octubre de dos mil veintiséis (2026)"),
        ("izq", f"SEÑORA\n{ACCIONANTE}\nAccionante\nEmail: {CORREO_ACCIONANTE}\nCiudad"),
        ("izq", f"SEÑORES\n{ACCIONADA}\nEmail: {CORREO_ACCIONADA}\nCiudad"),
        (
            "p",
            f"Por medio del presente, notifico el escrito de impugnación y el auto por medio del cual se concede la impugnación en contra del fallo emitido en la acción de tutela bajo radicado {RAD_CORTO}, remítase a través del sistema aleatorio de reparto.",
        ),
        ("izq", f"Atentamente,\n\n{OFICIAL}\nOficial Mayor\nJuzgado 9 Penal Municipal de Medellín"),
    ]


def documentos() -> list[tuple[str, list[tuple]]]:
    partes = _partes_acta()
    return [
        (
            "001",
            _acta(
                RADICADO,
                "TUTELA",
                "009",
                "JUZGADO MUNICIPAL - PENAL CONTROL DE GARANTIAS 009 MEDELLIN",
                "14/09/2026 4:48:30 p. m.",
                "6614001",
                JUEZ_1A,
                partes,
            ),
        ),
        ("002", _escrito_tutela()),
        ("003", _auto_admisorio()),
        ("004", _contestacion()),
        ("005", _parrafos_fallo()),
        ("006", _impugnacion()),
        ("007", _auto_concede()),
        ("008", _correo()),
        (
            "009",
            _acta(
                RADICADO_2A,
                "IMPUGNACIÓN TUTELA",
                "003",
                "JUZGADO DE CIRCUITO - PENAL FUNCIÓN DE CONOCIMIENTO 003 MEDELLIN",
                "07/10/2026 10:07:03 a. m.",
                "6691002",
                JUEZ_2A,
                partes,
            ),
        ),
    ]


def _construir_docx(bloques: list[tuple], ruta: Path) -> None:
    doc = Document()
    if any(b[0] == "tabla" for b in bloques):
        seccion = doc.sections[0]
        seccion.orientation = WD_ORIENT.LANDSCAPE
        seccion.page_width, seccion.page_height = seccion.page_height, seccion.page_width
    estilo = doc.styles["Normal"]
    estilo.font.name = "Liberation Serif"
    estilo.font.size = Pt(12)
    estilo.paragraph_format.space_after = Pt(8)
    for bloque in bloques:
        tipo = bloque[0]
        if tipo == "tabla":
            filas = bloque[1]
            tabla = doc.add_table(rows=len(filas), cols=len(filas[0]))
            tabla.style = "Table Grid"
            tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
            tabla.autofit = False
            anchos = (4.5, 3.5, 4.5, 4.5, 7.0)
            for i, fila in enumerate(filas):
                for j, celda in enumerate(fila):
                    tabla.cell(i, j).text = celda
                    tabla.cell(i, j).width = Cm(anchos[j])
                    for p in tabla.cell(i, j).paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(8)
                            r.bold = i == 0
            doc.add_paragraph()
            continue
        p = doc.add_paragraph()
        run = p.add_run(bloque[1])
        if tipo in ("centro", "centro_n"):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif tipo == "p":
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run.bold = tipo in ("centro", "n")
    doc.save(ruta)


def generar(carpeta: Path) -> Path:
    destino = Path(carpeta) / "01PrimeraInstancia" / "C01Principal"
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    soffice = shutil.which("soffice")
    if not soffice:
        raise RuntimeError("Se necesita LibreOffice (soffice) para convertir los documentos a PDF.")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        docxs = []
        for nombre, bloques in documentos():
            ruta = tmp / f"{nombre}.docx"
            _construir_docx(bloques, ruta)
            docxs.append(ruta)
        r = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{tmp / 'perfil'}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(destino),
                *map(str, docxs),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    faltan = [n for n, _ in documentos() if not (destino / f"{n}.pdf").is_file()]
    if faltan:
        raise RuntimeError(f"soffice no generó {', '.join(faltan)}.pdf: {r.stderr.strip()}")
    return destino


def preparar(carpeta: Path, proveedor: str) -> None:
    from tutela2.config import Config, LLMConfig, guardar

    carpeta = Path(carpeta)
    origen = carpeta / "01PrimeraInstancia"
    if not origen.is_dir():
        raise FileNotFoundError(f"No existe {origen}; corra primero 'generar'.")
    insumos = carpeta / "insumos"
    if insumos.exists():
        shutil.rmtree(insumos)
    shutil.copytree(origen, insumos)
    cfg = Config(llm=LLMConfig(proveedor=proveedor), verificar_relatoria=proveedor != "fake")
    guardar(carpeta, cfg)


def ejecutar(carpeta: Path, decision: dict) -> dict[str, dict]:
    from tutela2 import api

    resultados = {"nuevo": api.nuevo(carpeta)}
    if resultados["nuevo"]["estado"] == "revision":
        resultados["iniciar"] = api.iniciar(carpeta)
        if resultados["iniciar"]["estado"] == "esperando_decision":
            resultados["decidir"] = api.decidir(carpeta, decision)
    return resultados


def _aviso_costo(carpeta: Path) -> str:
    from tutela2.config import cargar

    cfg = cargar(carpeta)
    texto = sum(
        len(p.read_bytes()) for p in (carpeta / "insumos").rglob("*.pdf")
    )
    return (
        f"Se llamará al modelo {cfg.llm.modelo} (effort {cfg.llm.effort}) en 3 pasos (apertura, consideraciones, "
        f"caso concreto), con hasta {cfg.max_intentos} intentos por paso si el validador rechaza la salida, "
        f"y un tope de {cfg.llm.max_tokens} tokens de salida por llamada (el razonamiento cuenta contra ese tope). "
        f"En el peor caso son {3 * cfg.max_intentos} llamadas. Los PDF ocupan unos {texto // 1024} KB. "
        f"El costo depende de la tarifa vigente del modelo; consúltela en la página de precios de Anthropic. "
        f"Los documentos son ficticios, pero se envían a la API."
    )


def _imprimir(resultados: dict[str, dict]) -> int:
    ultimo = list(resultados.values())[-1]
    print(f"Estado: {ultimo['estado']}")
    if ultimo.get("error"):
        print(f"Error: {ultimo['error']}")
    resumen = resultados["nuevo"].get("resumen", {})
    for clave, titulo in (("faltantes", "Faltantes"), ("esperados_faltantes", "Esperados faltantes")):
        print(f"{titulo}: {resumen.get(clave) or 'ninguno'}")
    alertas = list(resumen.get("alertas") or [])
    for r in resultados.values():
        res = r.get("resumen") or {}
        a = res.get("alertas")
        if isinstance(a, dict):
            for k, v in a.items():
                alertas += [f"{k}: {x}" for x in (v if isinstance(v, list) else [v])]
    print("Alertas:")
    for a in dict.fromkeys(alertas):
        print(f"  - {a}")
    if not alertas:
        print("  ninguna")
    print("Salidas:")
    for s in ultimo.get("salidas", []):
        print(f"  {s}")
    return 0 if ultimo.get("ok") and ultimo["estado"] == "terminado" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expediente de tutela de primera instancia 100 % ficticio.")
    sub = parser.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("generar", help="Crea <carpeta>/01PrimeraInstancia/C01Principal con 9 PDF ficticios")
    g.add_argument("carpeta", type=Path)
    c = sub.add_parser("correr", help="Corre el caso de punta a punta")
    c.add_argument("carpeta", type=Path)
    c.add_argument("--proveedor", choices=("fake", "anthropic"), required=True)
    c.add_argument("--decision", type=Path)
    c.add_argument("--si", action="store_true", help="No pedir confirmación antes de llamar al modelo")
    args = parser.parse_args(argv)

    if args.comando == "generar":
        destino = generar(args.carpeta)
        print(f"Caso sintético generado en {destino}")
        return 0

    decision = json.loads(args.decision.read_text(encoding="utf-8")) if args.decision else DECISION_POR_DEFECTO
    if args.proveedor == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Falta la variable de entorno ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2
    preparar(args.carpeta, args.proveedor)
    if args.proveedor == "anthropic":
        print(_aviso_costo(args.carpeta))
        if not args.si and input("¿Continuar? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            return 1
    return _imprimir(ejecutar(args.carpeta, decision))


if __name__ == "__main__":
    sys.exit(main())
