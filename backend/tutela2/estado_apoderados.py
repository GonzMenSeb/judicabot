"""Estado de cada apoderado y compuerta de la decisión.

``evaluar`` cruza la identificación (lo que el código comprobó en el expediente) con el registro
del caso (consultas de vigencia, ajustes y revisiones) y aplica la tabla de estados; gana la
primera fila que se cumple:

1. El certificado dice que la tarjeta no está vigente → ``no_verificado``. El certificado de una
   cédula que no está inscrita como abogado(a) (``no_inscrito``) cuenta igual si la cédula consta en
   una página del expediente leída sin OCR; si se leyó con OCR o la indicó a mano quien revisa, puede
   estar mal escrita y no basta para el rojo (``Evaluacion.vigencia_grave``) → ``revisar``, salvo
   que otra fila lo deje en ``no_verificado``.
2. La T.P. del expediente difiere de la del certificado y ninguna página de donde se leyó es OCR
   → ``no_verificado``.
3. Solo hay poder para otra parte del trámite, ninguno para la que dice representar y ninguno
   señalado a mano → ``no_verificado``.
4. Tarjeta ``vigente`` sin observaciones, T.P. que coincide o que no consta, y poder hallado (con
   la cadena del certificado de existencia no contradicha) o señalado a mano → ``verificado``.
   Si la cédula no consta en el expediente (se tomó del certificado subido o la indicó a mano
   quien revisa), la T.P. del expediente debe coincidir con la del certificado: sin ella, solo el
   nombre ataría el certificado al abogado.
5. Todo lo demás (consulta pendiente o fallida, sin cédula, certificado ilegible o de otra
   persona, cédula no inscrita que puede estar mal escrita, observaciones, T.P. distinta leída con OCR, cadena contradicha, sin poder, poder
   descartado) → ``revisar``.

Nada de esto se guarda: se calcula en cada lectura, así que una consulta, un ajuste o una
revisión cambian el estado sin volver a correr el grafo ni tocar el previo. Cada revisión queda
atada a la ``huella`` del estado y de la evidencia; si algo de eso cambia, la revisión vence.

Una consulta es de una cédula y la comparten todos los apoderados que la usan; su ``estado`` no
depende del nombre. El nombre del certificado se coteja aquí con el de cada apoderado: si no es el
suyo, para ese apoderado el certificado es de ``otra_persona``. El certificado ``no_inscrito`` no trae
nombre y no se coteja: solo lo ata la cédula.

``bloqueos`` es la compuerta de la decisión: los apoderados ``no_verificado`` sin una revisión
vigente impiden decidir (``server.ejecutar`` y ``api.decidir``). Rehacer nunca se bloquea y un
caso sin identificación nunca bloquea.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, NamedTuple

from tutela2 import registro_apoderados
from tutela2.apoderados import SIN_CONSULTA_AUTOMATICA
from tutela2.esquemas_apoderados import (
    Cotejo,
    EstadoApoderado,
    EstadoPoder,
    EstadoVigencia,
    Fase,
)
from tutela2.models import Apoderado, EvidenciaDoc, Identificacion, Poder
from tutela2.registro_apoderados import Ajuste, ConsultaVigencia, Registro
from tutela2.vigencia import ESTADO_VIGENTE, SIN_OBSERVACIONES, a_nombre_de, solo_digitos

EstadoTarjeta = Literal["coincide", "difiere", "difiere_ocr", "sin_dato"]
FaseCola = Literal["en_cola", "consultando"]

RESULTADOS_PROPIOS = ("vigente", "vigente_obs", "no_vigente")
"""Resultados en los que el certificado es de la persona consultada (cédula y nombre coinciden)."""
NECESITAN_AYUDA = ("inaccesible", "ilegible", "otra_persona", "sin_cedula")
MOTIVO_NO_INSCRITO = (
    "El Registro Nacional de Abogados certifica que la cédula del abogado no está inscrita como abogado(a). "
    "Verifique el número; si actúa con licencia temporal, esta consulta no la cubre."
)
MAX_OBSERVACION = 200

_ROL_PARTE = {"accionante": "la parte accionante", "accionada": "la parte accionada", "vinculada": "vinculada al trámite"}


def sin_cola(cedula: str) -> FaseCola | None:
    """Fase en la cola de consultas automáticas: no hay cola, ninguna cédula está en ella."""
    return None


@dataclass(frozen=True)
class Evaluacion:
    apoderado: Apoderado
    estado: EstadoApoderado
    fase: Fase
    vigencia: EstadoVigencia
    vigencia_grave: bool
    """La vigencia por sí sola deja al abogado sin verificar (fila 1 de la tabla): tarjeta no vigente, o cédula
    no inscrita que consta en una página del expediente leída sin OCR."""
    tarjeta: EstadoTarjeta
    poder: EstadoPoder
    cedula: str | None
    consulta: ConsultaVigencia | None
    poder_mostrado: Poder | None
    motivo: str | None
    """La razón del estado: la de la fila que decidió (rojo) o la primera pendiente (ámbar)."""
    motivos: list[str] = field(default_factory=list)
    cotejos: list[Cotejo] = field(default_factory=list)
    huella: str = ""
    revisado: bool = False
    revision_vencida: bool = False

    @property
    def bloquea(self) -> bool:
        return self.estado == "no_verificado" and not self.revisado


class Bloqueo(NamedTuple):
    id: str
    nombre: str
    parte: str
    motivo: str


def _digitos(texto: str | None) -> str:
    return solo_digitos(texto)


def _sin_ceros(texto: str | None) -> str:
    return _digitos(texto).lstrip("0")


def _fuente_sin_ocr(ap: Apoderado) -> bool:
    """Hay páginas de donde salió la identificación del abogado y ninguna se leyó con OCR.

    Sin saber en qué página exacta consta la T.P., se miran todas: basta una escaneada para que
    una diferencia de T.P. quede en ámbar y no en rojo."""
    paginas = [e for e in (ap.cedula_fuente, *ap.menciones, *(p.evidencia for p in [*ap.poderes, *ap.ajenos])) if e]
    return bool(paginas) and not any(e.ocr for e in paginas)


def _cedula_sin_ocr(ap: Apoderado, cedula_fuera: bool) -> bool:
    """La cédula con que se consultó consta en una página verificada del expediente leída sin OCR."""
    return not cedula_fuera and bool(_digitos(ap.cedula)) and ap.cedula_fuente is not None and not ap.cedula_fuente.ocr


def _cita_corta(texto: str) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_OBSERVACION else texto[: MAX_OBSERVACION - 1].rstrip() + "…"


def _sin_observaciones(obs: str | None) -> bool:
    return obs is not None and " ".join(obs.split()).upper() == SIN_OBSERVACIONES


def _vigencia(ap: Apoderado, cedula: str | None, consulta: ConsultaVigencia | None) -> EstadoVigencia:
    if not cedula:
        return "sin_cedula"
    if consulta is None:
        return "sin_consultar"
    # La consulta es de la cédula y la comparten los apoderados que la usan: el nombre se coteja con cada uno.
    if consulta.estado in RESULTADOS_PROPIOS and consulta.datos is not None and not a_nombre_de(consulta.datos, ap.nombre):
        return "otra_persona"
    return consulta.estado


def _tarjeta(ap: Apoderado, vigencia: EstadoVigencia, consulta: ConsultaVigencia | None) -> EstadoTarjeta:
    if vigencia not in RESULTADOS_PROPIOS or consulta is None or consulta.datos is None:
        return "sin_dato"
    del_expediente, del_certificado = _sin_ceros(ap.tarjeta), _sin_ceros(consulta.datos.tpa_numero)
    if not del_expediente or not del_certificado:
        return "sin_dato"
    if del_expediente == del_certificado:
        return "coincide"
    return "difiere" if _fuente_sin_ocr(ap) else "difiere_ocr"


def _poder(ap: Apoderado, ajuste: Ajuste | None) -> tuple[EstadoPoder, Poder | None]:
    if ajuste is not None and ajuste.poder_manual is not None:
        return "manual", Poder(tipo="poder", evidencia=ajuste.poder_manual, parte=ap.parte)
    if ajuste is not None and ajuste.poder_descartado:
        return "descartado", None
    validos = [p for p in ap.poderes if p.cadena.estado != "contradicha"]
    if validos:
        return "hallado", validos[0]
    if ap.poderes:
        return "hallado_reserva", ap.poderes[0]
    if ap.ajenos:
        return "ajeno", ap.ajenos[0]
    return "sin_poder", None


def _numero_certificado(consulta: ConsultaVigencia | None) -> str:
    numero = consulta.datos.numero if consulta is not None and consulta.datos is not None else None
    return f" N.° {numero}" if numero else ""


def _motivo_vigencia(ap: Apoderado, vigencia: EstadoVigencia, consulta: ConsultaVigencia | None) -> str | None:
    datos = consulta.datos if consulta is not None else None
    if vigencia == "vigente":
        return None
    if vigencia == "sin_cedula":
        return "No consta en el expediente la cédula del abogado: no se puede consultar la vigencia de su tarjeta profesional."
    if vigencia == "sin_consultar":
        return "Aún no se ha consultado la vigencia de la tarjeta profesional en la Rama Judicial."
    if vigencia == "inaccesible":
        return "La consulta del certificado de vigencia en la Rama Judicial no obtuvo respuesta."
    if vigencia == "ilegible":
        return "No se pudo leer el certificado de vigencia: ábralo y revíselo."
    if vigencia == "no_inscrito":
        return MOTIVO_NO_INSCRITO
    if vigencia == "otra_persona":
        if datos is not None and datos.nombre:
            return f"El certificado de vigencia está a nombre de {datos.nombre}, no de {ap.nombre}."
        return f"El certificado de vigencia no está a nombre de {ap.nombre}."
    numero = _numero_certificado(consulta)
    if vigencia == "no_vigente":
        if datos is not None and datos.tpa_estado:
            tarjeta = f" {datos.tpa_numero}" if datos.tpa_numero else ""
            return f"La tarjeta profesional{tarjeta} figura como «{datos.tpa_estado}» en el certificado{numero}."
        if datos is not None and datos.rna_estado:
            return (
                f"La inscripción en el Registro Nacional de Abogados figura como «{datos.rna_estado}» "
                f"en el certificado{numero}."
            )
        return f"El certificado{numero} no reporta la tarjeta profesional como vigente."
    if datos is not None and datos.tpa_observaciones and not _sin_observaciones(datos.tpa_observaciones):
        return f"El certificado{numero} registra observaciones sobre la tarjeta: «{_cita_corta(datos.tpa_observaciones)}»."
    if datos is not None and datos.rna_observaciones and not _sin_observaciones(datos.rna_observaciones):
        return (
            f"El certificado{numero} registra observaciones sobre la inscripción en el Registro Nacional de Abogados: "
            f"«{_cita_corta(datos.rna_observaciones)}»."
        )
    if datos is not None and datos.rna_estado != ESTADO_VIGENTE:
        return f"El certificado{numero} no confirma que la inscripción en el Registro Nacional de Abogados esté vigente."
    return f"El certificado{numero} registra observaciones."


def _motivo_tarjeta(ap: Apoderado, tarjeta: EstadoTarjeta, consulta: ConsultaVigencia | None) -> str | None:
    if tarjeta not in ("difiere", "difiere_ocr") or consulta is None or consulta.datos is None:
        return None
    base = (
        f"La tarjeta profesional del expediente ({ap.tarjeta}) no coincide con la del certificado de vigencia "
        f"({consulta.datos.tpa_numero})"
    )
    if tarjeta == "difiere":
        return base + "."
    return base + ", pero se leyó de una página escaneada (OCR): compruébela en el documento."


def _motivo_cedula(fuera: bool, subida: bool, vigencia: EstadoVigencia, tarjeta: EstadoTarjeta) -> str | None:
    if not fuera:
        return None
    origen = "se tomó del certificado de vigencia subido" if subida else "la indicó a mano quien revisa"
    base = f"La cédula del abogado no consta en el expediente: {origen}"
    if vigencia in RESULTADOS_PROPIOS and tarjeta == "sin_dato":
        return base + ", y sin la tarjeta profesional del expediente solo el nombre lo ata al abogado: confirme que es suyo."
    return base + "."


def _motivo_poder(ap: Apoderado, poder: EstadoPoder, mostrado: Poder | None, documentos: int) -> str | None:
    if poder == "sin_poder":
        if documentos:
            return f"Se revisaron {documentos} documentos y ninguno le otorga poder para representar a {ap.parte}."
        return f"No se halló en el expediente un poder ni un certificado que lo faculte para representar a {ap.parte}."
    if poder == "ajeno":
        otra = (mostrado.parte or mostrado.otorgante) if mostrado is not None else ""
        return f"El poder hallado es para {otra or 'otra parte'}, no para {ap.parte}."
    if poder == "hallado_reserva":
        otorgante = (mostrado.cadena.otorgante or mostrado.otorgante) if mostrado is not None else ""
        return (
            f"El certificado de existencia y representación de {ap.parte} no acredita a "
            f"{otorgante or 'quien otorgó el poder'} como su representante."
        )
    if poder == "descartado":
        return "El poder hallado se marcó como incorrecto en la revisión."
    return None


def _ref(e: EvidenciaDoc | None) -> str:
    return f" (Doc. {e.doc_id}, p. {e.pagina})" if e is not None else ""


def _cotejos(
    ap: Apoderado,
    vigencia: EstadoVigencia,
    tarjeta: EstadoTarjeta,
    poder: EstadoPoder,
    mostrado: Poder | None,
    consulta: ConsultaVigencia | None,
    cedula_fuera: bool,
    cedula_subida: bool,
) -> list[Cotejo]:
    salida: list[Cotejo] = []
    if mostrado is not None:
        salida.append(Cotejo(ok=True, texto="El nombre coincide con quien actúa en el expediente"))
    elif poder == "descartado":
        salida.append(Cotejo(ok=False, texto="El poder hallado se descartó en la revisión"))
    else:
        salida.append(Cotejo(ok=None, texto="No hay poder con el cual cotejar el nombre"))

    datos = consulta.datos if consulta is not None else None
    if tarjeta == "coincide":
        salida.append(Cotejo(ok=True, texto=f"T.P. {ap.tarjeta} coincide con el certificado de vigencia"))
    elif tarjeta in ("difiere", "difiere_ocr"):
        registro = datos.tpa_numero if datos is not None else ""
        salida.append(
            Cotejo(ok=False, texto=f"La T.P. {ap.tarjeta} del expediente no coincide con la del certificado ({registro})")
        )
    elif vigencia == "otra_persona":
        salida.append(Cotejo(ok=False, texto="El certificado de vigencia está a nombre de otra persona"))
    elif vigencia == "no_inscrito":
        salida.append(Cotejo(ok=False, texto="La cédula no figura inscrita como abogado(a) en el Registro Nacional de Abogados"))
    elif vigencia in RESULTADOS_PROPIOS and not ap.tarjeta:
        salida.append(Cotejo(ok=None, texto="No consta la T.P. en el expediente: no se pudo cotejar con el certificado"))
    else:
        salida.append(Cotejo(ok=None, texto="La T.P. aún no se ha cotejado con el certificado de vigencia"))

    if cedula_fuera:
        origen = "La cédula se tomó del certificado subido" if cedula_subida else "La cédula la indicó a mano quien revisa"
        salida.append(Cotejo(ok=None, texto=f"{origen}; no consta en el expediente"))

    rol = _ROL_PARTE.get(ap.rol_parte)
    if poder in ("hallado", "hallado_reserva", "manual"):
        salida.append(Cotejo(ok=True, texto=f"Representa a {ap.parte}" + (f", {rol}" if rol else "")))
    elif poder == "ajeno":
        otra = (mostrado.parte or mostrado.otorgante) if mostrado is not None else ""
        salida.append(Cotejo(ok=False, texto=f"El poder es para {otra or 'otra parte'}, no para {ap.parte}"))
    elif poder == "descartado":
        salida.append(Cotejo(ok=False, texto=f"No queda poder que lo faculte para representar a {ap.parte}"))
    else:
        salida.append(Cotejo(ok=None, texto=f"No se halló poder para representar a {ap.parte}"))

    if ap.tipo_persona == "juridica" and mostrado is not None and poder != "ajeno":
        cadena = mostrado.cadena
        otorgante = cadena.otorgante or mostrado.otorgante or "quien otorga el poder"
        if cadena.estado == "confirmada":
            cargo = f", {cadena.cargo}," if cadena.cargo else ""
            salida.append(
                Cotejo(
                    ok=True,
                    texto=f"Lo otorga {otorgante}{cargo} acreditado en el certificado de existencia{_ref(cadena.evidencia)}",
                )
            )
        elif cadena.estado == "contradicha":
            salida.append(
                Cotejo(ok=False, texto=f"El certificado de existencia no acredita a {otorgante} como representante de {ap.parte}")
            )
        elif cadena.estado == "sin_certificado":
            salida.append(
                Cotejo(ok=None, texto=f"No hay certificado de existencia y representación de {ap.parte} en el expediente")
            )
    return salida


def _huella(
    estado: EstadoApoderado,
    vigencia: EstadoVigencia,
    tarjeta: EstadoTarjeta,
    poder: EstadoPoder,
    motivos: list[str],
    ap: Apoderado,
    ajuste: Ajuste | None,
    consulta: ConsultaVigencia | None,
) -> str:
    evidencias = [e for p in [*ap.poderes, *ap.ajenos] for e in (p.evidencia, p.cadena.evidencia) if e is not None]
    if ajuste is not None and ajuste.poder_manual is not None:
        evidencias.append(ajuste.poder_manual)
    datos = [
        estado,
        vigencia,
        tarjeta,
        poder,
        sorted(motivos),
        sorted({(e.doc_id, e.pagina) for e in evidencias}),
        consulta.sha256 if consulta is not None else None,
    ]
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _fase(cedula: str | None, vigencia: EstadoVigencia, fase_cola: Callable[[str], FaseCola | None], automatica: bool) -> Fase:
    en_cola = fase_cola(cedula) if cedula else None
    if en_cola is not None:
        return en_cola
    if vigencia in NECESITAN_AYUDA:
        return "necesita_ayuda"
    if vigencia == "sin_consultar":
        return "en_cola" if automatica else "necesita_ayuda"
    return "listo"


def evaluar(
    ap: Apoderado,
    registro: Registro,
    *,
    fase_cola: Callable[[str], FaseCola | None] = sin_cola,
    consulta_automatica: bool = False,
) -> Evaluacion:
    """Estado de un apoderado según la tabla del módulo (gana la primera fila que se cumple).

    ``fase_cola`` dice si la cédula está en la cola de consultas automáticas y
    ``consulta_automatica`` si una consulta automática todavía puede resolver una cédula sin
    consultar (con cola, se asume que la pondrá en ella); sin eso, la cédula pendiente necesita
    ayuda (subir el certificado a mano). Ninguno de los dos cambia el estado ni la huella, solo la
    fase."""
    ajuste = registro.ajustes.get(ap.id)
    cedula_ajuste = ajuste.cedula if ajuste is not None else None
    cedula = _digitos(cedula_ajuste or ap.cedula) or None
    # La cédula del ajuste la pone la subida del certificado o quien revisa, solo si el expediente no la trae.
    cedula_fuera = bool(cedula_ajuste) and cedula is not None and cedula != (_digitos(ap.cedula) or None)
    consulta = registro.consultas.get(cedula) if cedula else None
    # Si hay un certificado subido de esa cédula, de él se tomó; si no, la indicó quien revisa. El certificado de
    # una cédula no inscrita no trae nombre: solo se acepta si quien revisa ya había escrito la cédula.
    cedula_subida = (
        cedula_fuera
        and consulta is not None
        and consulta.origen == "manual"
        and (consulta.datos is None or consulta.datos.inscrito)
    )
    vigencia = _vigencia(ap, cedula, consulta)
    vigencia_grave = vigencia == "no_vigente" or (vigencia == "no_inscrito" and _cedula_sin_ocr(ap, cedula_fuera))
    tarjeta = _tarjeta(ap, vigencia, consulta)
    poder, mostrado = _poder(ap, ajuste)
    documentos = registro.identificacion.documentos_revisados if registro.identificacion is not None else 0

    m_vigencia = _motivo_vigencia(ap, vigencia, consulta)
    m_tarjeta = _motivo_tarjeta(ap, tarjeta, consulta)
    m_cedula = _motivo_cedula(cedula_fuera, cedula_subida, vigencia, tarjeta)
    m_poder = _motivo_poder(ap, poder, mostrado, documentos)
    # Con una cédula que no consta en el expediente, la T.P. del expediente es lo único que lo ata al abogado.
    tarjetas_validas = ("coincide",) if cedula_fuera else ("coincide", "sin_dato")

    if vigencia_grave:
        estado: EstadoApoderado = "no_verificado"
        motivo = m_vigencia
    elif tarjeta == "difiere":
        estado, motivo = "no_verificado", m_tarjeta
    elif poder == "ajeno":
        estado, motivo = "no_verificado", m_poder
    elif vigencia == "vigente" and tarjeta in tarjetas_validas and poder in ("hallado", "manual"):
        estado, motivo = "verificado", None
    else:
        estado = "revisar"
        motivo = next((m for m in (m_vigencia, m_tarjeta, m_cedula, m_poder) if m), None)

    motivos = [m for m in (m_vigencia, m_tarjeta, m_cedula, m_poder) if m]
    # Los motivos de la identificación sobre la cédula que faltaba ya no valen si hay otra fuera del expediente.
    propios = [m for m in dict.fromkeys(ap.motivos) if not (cedula_fuera and SIN_CONSULTA_AUTOMATICA in m)]
    motivos += [m for m in propios if m not in motivos]
    if estado == "revisar" and motivo is None:
        motivo = motivos[0] if motivos else "Falta confirmar la tarjeta profesional o el poder."
    huella = _huella(estado, vigencia, tarjeta, poder, motivos, ap, ajuste, consulta)
    revision = registro.revisiones.get(ap.id)
    marcada = revision is not None and revision.revisado
    return Evaluacion(
        apoderado=ap,
        estado=estado,
        fase=_fase(cedula, vigencia, fase_cola, consulta_automatica),
        vigencia=vigencia,
        vigencia_grave=vigencia_grave,
        tarjeta=tarjeta,
        poder=poder,
        cedula=cedula,
        consulta=consulta,
        poder_mostrado=mostrado,
        motivo=motivo,
        motivos=motivos,
        cotejos=_cotejos(ap, vigencia, tarjeta, poder, mostrado, consulta, cedula_fuera, cedula_subida),
        huella=huella,
        revisado=marcada and revision.huella == huella,
        revision_vencida=marcada and revision.huella != huella,
    )


def evaluar_todos(
    registro: Registro,
    *,
    fase_cola: Callable[[str], FaseCola | None] = sin_cola,
    consulta_automatica: bool = False,
) -> list[Evaluacion]:
    if registro.identificacion is None:
        return []
    return [
        evaluar(ap, registro, fase_cola=fase_cola, consulta_automatica=consulta_automatica)
        for ap in registro.identificacion.apoderados
    ]


def fallida(identificacion: Identificacion) -> bool:
    """La identificación quedó vacía porque falló (no se revisó ningún documento)."""
    return not identificacion.apoderados and not identificacion.sin_apoderado and identificacion.documentos_revisados == 0


def bloqueos(caso_dir: Path) -> list[Bloqueo]:
    """Los apoderados ``no_verificado`` que no tienen una revisión con la huella actual.

    Falla cerrado: si el registro del caso no es válido lanza ``registro_apoderados.RegistroInvalido``
    en vez de evaluar un registro vacío."""
    return [
        Bloqueo(ev.apoderado.id, ev.apoderado.nombre, ev.apoderado.parte, ev.motivo or "")
        for ev in evaluar_todos(registro_apoderados.leer(caso_dir))
        if ev.bloquea
    ]


def mensaje_bloqueo(pendientes: list[Bloqueo]) -> str:
    nombres = ", ".join(dict.fromkeys(b.nombre for b in pendientes))
    return f"Hay apoderados no verificados sin revisar: {nombres}. Márquelos como revisados en el borrador."
