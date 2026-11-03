from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from tutela2 import radicado
from tutela2.letras import fecha_corta, fecha_larga, numero_a_letras, numero_titulo
from tutela2.models import Compulsa, Decision, Metadatos, Orden, Plazo

SUBTITULO_COMPETENCIA = "Competencia"
COMPETENCIA_1 = (
    "Este despacho es competente para conocer y resolver el recurso de impugnación interpuesto "
    "contra la sentencia de tutela de primera instancia, de conformidad con lo dispuesto en el "
    "artículo 32 del Decreto 2591 de 1991 y las normas concordantes de reparto de la acción de "
    "amparo. En su condición de superior funcional, le corresponde adelantar un examen integral "
    "de la providencia recurrida a la luz de los postulados de la Carta Política y de la doctrina "
    "fijada por la Corte Constitucional."
)
SUBTITULO_PROCEDIBILIDAD = "Presupuestos Generales de Procedibilidad de la Acción de Tutela"
PROCEDIBILIDAD_P1 = (
    'La acción de tutela, consagrada en el artículo 86 de la Constitución Política y reglamentada por el Decreto 2591 de 1991, se erige como un mecanismo preferente y sumario concebido para la protección inmediata y efectiva de los derechos constitucionales fundamentales cuando estos resulten vulnerados o amenazados por la acción u omisión de las autoridades públicas o de los particulares. Dada su finalidad tuitiva y extraordinaria, el juicio de procedibilidad de la acción exige la verificación rigurosa y concurrente de los presupuestos procesales obligatorios: la legitimación en la causa (activa y pasiva), la inmediatez y la subsidiariedad.'
)
PROCEDIBILIDAD_P2 = (
    'En relación con la legitimación en la causa por activa, el ordenamiento constitucional faculta a toda persona para solicitar el amparo de sus garantías fundamentales, actuando por sí misma, por medio de apoderado judicial, a través de representante legal o mediante agente oficioso cuando el titular no se encuentre en condiciones de promover su propia defensa. Por su parte, la legitimación en la causa por pasiva exige que la solicitud se dirija contra la autoridad o el particular a quien se le atribuya la conducta omisiva o lesiva. Tratándose de organizaciones privadas, la acción procede de forma excepcional en los supuestos contemplados en el artículo 42 del Decreto 2591 de 1991.'
)
TRANSICION = (
    "Definido el marco jurídico aplicable y los criterios constitucionales relevantes, procede "
    "este Despacho a continuación a examinar la situación fáctica y jurídica específica puesta en "
    "conocimiento en este trámite constitucional."
)
MERITO_ANTES = "En mérito de lo expuesto, el "
MERITO_DESPUES = ", administrando justicia en nombre de la República y por autoridad de la Ley,"

_MOTIVO = "por las razones expuestas en este proveído."
_ORDINALES = ("PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO", "SEXTO", "SÉPTIMO", "OCTAVO", "NOVENO")
_DECENAS_ORDINALES = ("", "DÉCIMO", "VIGÉSIMO", "TRIGÉSIMO")
_PLAZOS = {
    "horas_habiles": ("f", "hora hábil", "horas hábiles"),
    "dias_habiles": ("m", "día hábil", "días hábiles"),
    "horas": ("f", "hora", "horas"),
    "dias": ("m", "día", "días"),
}
_RESULTADO_ENCABEZADO = {"CONFIRMAR": "CONFIRMA", "REVOCAR": "REVOCA", "MODIFICAR": "MODIFICA"}
_SUSTITUTIVA_ENCABEZADO = {
    "AMPARAR": "",
    "NEGAR": "NIEGA",
    "IMPROCEDENTE": "DECLARA IMPROCEDENTE",
    "CARENCIA_HECHO_SUPERADO": "DECLARA HECHO SUPERADO",
    "CARENCIA_DANO_CONSUMADO": "DECLARA DAÑO CONSUMADO",
    "CARENCIA_SOBREVINIENTE": "DECLARA SITUACIÓN SOBREVINIENTE",
}
_CARENCIA = {
    "CARENCIA_HECHO_SUPERADO": "HECHO SUPERADO",
    "CARENCIA_DANO_CONSUMADO": "DAÑO CONSUMADO",
    "CARENCIA_SOBREVINIENTE": "SITUACIÓN SOBREVINIENTE",
}
_FEMENINOS = frozenset(
    "vida salud dignidad igualdad educacion vivienda libertad intimidad honra peticion integridad "
    "informacion seguridad estabilidad unidad familia defensa proteccion personalidad imagen "
    "propiedad alimentacion identidad nacionalidad libre".split()
)
_ARTICULO_INICIAL = re.compile(r"^(el|la|los|las)\s+", re.IGNORECASE)


def _falta(nombre: str) -> str:
    return f"⟦FALTA: {nombre}⟧"


def _o(valor: str | None, nombre: str) -> str:
    return valor.strip() if valor and valor.strip() else _falta(nombre)


_CEDULA = re.compile(
    r"(\b(?:C\.\s?C\.?|CC\.?|c[ée]dula(?:\s+de\s+ciudadan[ií]a)?)"
    r"(?:\s*(?:No\.?|N[°º.]|Nro\.?|n\.°|n[úu]mero))?\s*)(\d{6,10})\b(?![.,]\d|-\d)",
    re.IGNORECASE,
)


def _puntos(digitos: str) -> str:
    return re.sub(r"(?<=\d)(?=(?:\d{3})+$)", ".", digitos)


def formatear_cedulas(texto: str) -> str:
    return _CEDULA.sub(lambda m: m.group(1) + _puntos(m.group(2)), texto)


def _lista_y(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))


def _sin_punto(texto: str) -> str:
    return texto.strip().rstrip(".").strip()


def juzgado(md: Metadatos, forma: str) -> str:
    if md.juzgado_a_quo_numero is None or md.juzgado_a_quo_funcion is None:
        return _falta("juzgado a quo")
    j = radicado.Juzgado(
        numero=md.juzgado_a_quo_numero,
        funcion=md.juzgado_a_quo_funcion,
        letras=md.juzgado_a_quo_letras or numero_titulo(md.juzgado_a_quo_numero),
        plural=md.juzgado_a_quo_plural,
    )
    return radicado.nombre_juzgado(j, forma)


def competencia_2(md: Metadatos) -> str:
    plural = len(md.impugnantes) > 1
    impugnacion = "las impugnaciones presentadas" if plural else "la impugnación presentada"
    return (
        f"Este Despacho es competente para resolver {impugnacion} contra la sentencia de "
        f"tutela proferida el {fecha_corta(md.fechas.fallo_a_quo)} por el {juzgado(md, 'cuerpo')}, "
        "de conformidad con el artículo 32 del Decreto 2591 de 1991."
    )


def asunto(md: Metadatos) -> str:
    impugnantes = md.impugnantes or ([md.impugnante] if md.impugnante else [])
    quien = formatear_cedulas(_lista_y(impugnantes)) if impugnantes else _falta("impugnante")
    impugnacion = "las impugnaciones presentadas" if len(impugnantes) > 1 else "la impugnación presentada"
    fuente = md.resultado_a_quo_se or md.resultado_a_quo
    resultado = _sin_punto(fuente) if fuente else _falta("resultado del fallo de primera instancia")
    return (
        f"Procede el Despacho a resolver {impugnacion} por {quien} contra el fallo de tutela emitido el "
        f"{fecha_larga(md.fechas.fallo_a_quo)} por el {juzgado(md, 'cuerpo')}, por medio del cual se {resultado}."
    )


def etiqueta_parte(tipo: Literal["Accionad", "Vinculad"], genero: str | None, n: int) -> str:
    return tipo + ("o" if genero == "m" else "a") + ("s" if n > 1 else "")


def encabezado_decision(decision: Decision | None) -> str:
    if decision is None:
        return _falta("decisión")
    if decision.etiqueta_encabezado.strip():
        return decision.etiqueta_encabezado.strip()
    if not decision.resultado:
        return _falta("decisión")
    base = _RESULTADO_ENCABEZADO[decision.resultado]
    if decision.resultado == "CONFIRMAR" or not decision.sustitutiva:
        return base
    extra = _SUSTITUTIVA_ENCABEZADO[decision.sustitutiva]
    return f"{base} Y {extra}" if extra else base


def filas_encabezado(md: Metadatos, decision: Decision | None) -> list[tuple[str, str, str]]:
    cui = md.cui_2a or md.cui_1a
    filas = [
        ("radicado", "Radicado", radicado.espaciado(cui) if cui else _falta("radicado")),
        ("accionante", "Accionante", _o(md.accionante, "accionante").upper()),
        (
            "accionada",
            etiqueta_parte("Accionad", md.genero_accionadas, len(md.accionadas)),
            ", ".join(md.accionadas).upper() if md.accionadas else _falta("accionada"),
        ),
    ]
    if md.vinculadas:
        filas.append(
            ("vinculada", etiqueta_parte("Vinculad", md.genero_vinculadas, len(md.vinculadas)), ", ".join(md.vinculadas).upper())
        )
    filas.append(("procedencia", "Procedencia", juzgado(md, "encabezado")))
    if md.derechos_invocados:
        filas.append(("derechos", "Derechos", ", ".join(md.derechos_invocados).upper()))
    if decision is not None:
        filas.append(("decision", "Decisión", encabezado_decision(decision)))
    return filas


def con_articulo(derecho: str) -> str:
    texto = derecho.strip()
    bajo = texto.lower()
    if bajo.startswith(("al ", "a la ", "a los ", "a las ")):
        return texto
    if bajo.startswith("el "):
        return contraer("a", texto)
    if bajo.startswith(("la ", "los ", "las ")):
        return f"a {texto}"
    primera = _sin_tildes(texto.split()[0]) if texto else ""
    return f"a la {texto}" if primera in _FEMENINOS else f"al {texto}"


def contraer(prep: Literal["a", "de"], texto: str) -> str:
    texto = texto.strip()
    if texto.lower().startswith("el "):
        return f"{'al' if prep == 'a' else 'del'} {texto[3:].lstrip()}"
    return f"{prep} {texto}"


def ordinal(i: int) -> str:
    if i < 10:
        return _ORDINALES[i - 1]
    if i >= 40:
        return f"NUMERAL {i}"
    decena = _DECENAS_ORDINALES[i // 10]
    return decena if i % 10 == 0 else f"{decena} {_ORDINALES[i % 10 - 1]}"


@dataclass
class Numeral:
    clave: str
    texto: str
    negritas: list[str] = field(default_factory=list)
    literales: list[str] = field(default_factory=list)


def _plazo(p: Plazo) -> tuple[str, str]:
    genero, singular, plural = _PLAZOS[p.unidad]
    if p.n == 1:
        return f"{numero_a_letras(1, genero)} (1) {singular}", "siguiente"
    articulo = "las" if genero == "f" else "los"
    return f"{articulo} {numero_a_letras(p.n, genero)} ({p.n}) {plural}", "siguientes"


def _sin_articulo(texto: str) -> str:
    return _ARTICULO_INICIAL.sub("", texto.strip())


def _derechos(d: Decision, md: Metadatos, disposicion: str) -> list[str]:
    elegidos = [x.derecho for x in d.derechos if x.disposicion == disposicion]
    if elegidos or (disposicion == "AMPARA" and d.derechos):
        return elegidos
    return list(md.derechos_invocados)


def _persona(md: Metadatos) -> tuple[str, str, str]:
    nombre = _o(md.accionante, "accionante").upper()
    trat = f"{md.accionante_tratamiento.strip()} " if md.accionante_tratamiento and md.accionante_tratamiento.strip() else ""
    ident = f", {formatear_cedulas(md.accionante_identificacion.strip())}" if md.accionante_identificacion and md.accionante_identificacion.strip() else ""
    return trat, nombre, ident


def _resultado(d: Decision, md: Metadatos) -> Numeral:
    verbo = d.resultado or _falta("resultado")
    a_quo = _sin_punto(md.resultado_a_quo) if md.resultado_a_quo else _falta("resultado del fallo de primera instancia")
    texto = (
        f"{verbo} la sentencia proferida el {fecha_corta(md.fechas.fallo_a_quo)} por el "
        f"{juzgado(md, 'cuerpo_numero')}, que {a_quo}, de conformidad con lo expuesto en la parte motiva de este proveído."
    )
    return Numeral("resultado", texto, [verbo])


def _sustitutiva(d: Decision, md: Metadatos) -> Numeral:
    trat, nombre, ident = _persona(md)
    s = d.sustitutiva
    if s == "AMPARAR":
        derechos = _derechos(d, md, "AMPARA")
        objeto = "el derecho fundamental" if len(derechos) == 1 else "los derechos fundamentales"
        lista = _lista_y([con_articulo(x) for x in derechos]) if derechos else _falta("derechos")
        texto = f"AMPARAR {objeto} {lista} {contraer('de', trat + nombre)}{ident}"
        texto = texto if texto.endswith(".") else texto + "."
        return Numeral("sustitutiva", texto, ["AMPARAR", nombre])
    if s == "NEGAR":
        derechos = _derechos(d, md, "NIEGA")
        objeto = "del derecho fundamental" if len(derechos) == 1 else "de los derechos fundamentales"
        lista = _lista_y([con_articulo(x) for x in derechos]) if derechos else _falta("derechos")
        texto = f"NEGAR el amparo solicitado por {trat}{nombre} respecto {objeto} {lista}, {_MOTIVO}"
        return Numeral("sustitutiva", texto, ["NEGAR"])
    if s == "IMPROCEDENTE":
        texto = f"DECLARAR IMPROCEDENTE la acción de tutela promovida por {trat}{nombre}, {_MOTIVO}"
        return Numeral("sustitutiva", texto, ["DECLARAR IMPROCEDENTE"])
    if s in _CARENCIA:
        cabeza = f"DECLARAR LA CARENCIA ACTUAL DE OBJETO POR {_CARENCIA[s]}"
        texto = f"{cabeza} en la acción de tutela promovida por {trat}{nombre}, {_MOTIVO}"
        return Numeral("sustitutiva", texto, [cabeza])
    return Numeral("sustitutiva", _falta("decisión sustitutiva"))


def _orden(i: int, o: Orden) -> Numeral:
    dest = o.destinatario.strip()
    conducta = o.conducta.strip().rstrip(" .:;,")
    if o.condicion.strip():
        conducta += f", {_sin_punto(o.condicion)}"
    negritas = [o.verbo, _sin_articulo(dest)]
    clave = f"orden:{i}"
    if o.verbo == "PREVENIR":
        union = "" if conducta.startswith(",") else " "
        return Numeral(clave, f"PREVENIR {contraer('a', dest)} para que{union}{conducta}.", negritas)
    if o.verbo == "ADVERTIR":
        return Numeral(clave, f"ADVERTIR {contraer('a', dest)} que {conducta}.", negritas)
    via = " a través de su representante legal y/o quien haga sus veces," if o.via_representante else ""
    if o.mismo_termino:
        termino = "dentro del mismo término"
    else:
        plazo, siguiente = _plazo(o.plazo)
        termino = f"dentro de {plazo} {siguiente} a la notificación de esta providencia"
    texto = f"ORDENAR {contraer('a', dest)}{via} que, {termino}, {conducta}"
    if not o.literales:
        return Numeral(clave, texto + ".", negritas)
    literales = [f"{chr(97 + k)}. {x.strip()}" for k, x in enumerate(o.literales)]
    return Numeral(clave, texto + ":", negritas, literales)


def _libre(i: int, texto: str) -> Numeral:
    texto = texto.strip()
    primera = texto.split()[0].rstrip(",.;:") if texto.split() else ""
    return Numeral(f"libre:{i}", texto, [primera] if primera.isupper() else [])


def _estandar(d: Decision, md: Metadatos) -> dict[str, Numeral]:
    por_clave: dict[str, Numeral] = {"resultado": _resultado(d, md)}
    if d.resultado != "CONFIRMAR":
        por_clave["sustitutiva"] = _sustitutiva(d, md)
    for i, o in enumerate(d.ordenes):
        por_clave[f"orden:{i}"] = _orden(i, o)
    if d.prevenir:
        vuelva = "vuelva" if len(d.prevenir) == 1 else "vuelvan"
        texto = (
            f"PREVENIR {_lista_y([contraer('a', x) for x in d.prevenir])} para que, en lo sucesivo, no {vuelva} a incurrir "
            "en las acciones u omisiones que dieron lugar a la presente acción de tutela."
        )
        por_clave["prevenir"] = Numeral("prevenir", texto, ["PREVENIR"])
    if d.desvincular:
        texto = (
            f"DESVINCULAR de la presente acción de tutela {_lista_y([contraer('a', x) for x in d.desvincular])}, por las "
            "razones expuestas en la parte motiva de esta providencia."
        )
        por_clave["desvincular"] = Numeral("desvincular", texto, ["DESVINCULAR"])
    if d.compulsa:
        texto = (
            f"COMPULSAR COPIAS ante la {d.compulsa.organo} para que, de estimarlo pertinente, adelante las "
            f"actuaciones a que haya lugar respecto {contraer('de', d.compulsa.respecto_de)}, conforme a lo "
            "indicado en el acápite de otras determinaciones de este proveído."
        )
        por_clave["compulsa"] = Numeral("compulsa", texto, ["COMPULSAR COPIAS"])
    for i, t in enumerate(d.numerales_libres):
        por_clave[f"libre:{i}"] = _libre(i, t)
    if d.numerales.notificar:
        texto = (
            "NOTIFICAR esta providencia a las partes por el medio más expedito, de conformidad con lo "
            "dispuesto en el artículo 30 del Decreto 2591 de 1991."
        )
        por_clave["notificar"] = Numeral("notificar", texto, ["NOTIFICAR"])
    if d.numerales.remitir_corte:
        texto = "REMITIR el expediente a la Honorable Corte Constitucional para su eventual revisión."
        por_clave["remitir"] = Numeral("remitir", texto, ["REMITIR"])
    return por_clave


def numerales(decision: Decision, md: Metadatos) -> list[Numeral]:
    por_clave = _estandar(decision, md)
    claves: list[str] = []
    for k in [*decision.orden_numerales, *por_clave]:
        if k in por_clave and k not in claves:
            claves.append(k)
    return [por_clave[k] for k in claves]


def cierre_otras_determinaciones(c: Compulsa) -> str:
    return (
        "Por lo anterior, en cumplimiento del deber legal que le asiste a este funcionario, se dispondrá a "
        f"compulsar copias de lo actuado ante la {c.organo} para que, dentro del marco de sus competencias, "
        f"evalúe las situaciones descritas respecto {contraer('de', c.respecto_de)}."
    )
