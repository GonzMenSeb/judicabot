from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from itertools import chain, combinations
from typing import Iterable

from tutela2.letras import letras_a_numero, numero_a_letras
from tutela2.citas import PREFIJO_REGLA, RE_SENTENCIA, cobertura, normalizar_texto, sentencias_en_texto
from tutela2.models import (
    AperturaLLM,
    CasoConcretoLLM,
    CitaVerificada,
    ConsideracionesLLM,
    Decision,
    Ingesta,
    Metadatos,
    Plazo,
    Reparo,
)

BLOQUEA = "BLOQUEA: "
ALERTA = "ALERTA: "
NGRAMA_ANCLA = 6
COBERTURA_ANCLA = 0.8
MIN_PALABRAS_DUPLICADO = 8
MAX_PALABRAS_RESIDUO = 40
MAX_LINEAS_CITADAS = 5
NGRAMA_CONTENCION = 3
MIN_NGRAMAS_CONTENCION = 10
MAX_CHARS_CITA_EN_MINIMO = 1800
MIN_CHARS_MOTIVOS_EN_MINIMO = 300
_ESTADO_EN_MINIMO = {"rechazada": "rechazada", "alerta": "para revisar"}
UMBRAL_CONTENCION = 0.6
MIN_PALABRAS_PASAJE = NGRAMA_ANCLA
COBERTURA_PASAJE_CITA = 0.5

_VINETA = re.compile(r"^\s*(?:[-–—•·▪◦*]|\d+[.)])\s+\S")
_ENCABEZADO = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_ROTULO = re.compile(
    r"^\s*((?i:argumento del despacho|hechos|pretensiones|nota|borrador|problema jur[ií]dico|conclusi[oó]n|tesis)|TODO)\s*:"
)
_MARCADOR = re.compile(r"\[\[CITA:\s*([^\]\s]+)\s*\]\]")
_MARCADOR_LAXO = re.compile(r"\[\[\s*cita\b[^\]\n]{0,80}\]{0,2}|\[\s*cita\s*:[^\]\n]{0,80}\]{0,2}", re.IGNORECASE)
_MARCADOR_CUALQUIERA = re.compile(r"\[\[[^\]]*\]\]")
_SIN_ANIO = re.compile(r"\b(SU|T|C)[-‑–](\d{3,4})(?![\dA-Za-z/])")
_SUFIJOS_SOCIETARIOS = {"sas", "sa", "ltda", "esp"}
_INFINITIVO = re.compile(r"^([A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:ar|er|ir))\b")
_NO_INFINITIVOS = {
    "primer", "tercer", "cualquier", "mujer", "lugar", "hogar", "taller", "ayer", "poder", "deber", "pesar",
}

_CUI = re.compile(r"(?<!\d)\d(?:[ \- ]?\d){22}(?!\d)")
_NUMERO = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?!\d)|(?<![\d.,])\d{6,}(?!\d)")
_FECHA_NUM = re.compile(r"(?<![\d/.\-])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)")
_FECHA_ISO = re.compile(r"(?<![\d\-/])(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)")
_MESES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3, "abril": 4, "abr": 4,
    "mayo": 5, "may": 5, "junio": 6, "jun": 6, "julio": 7, "jul": 7, "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}
_MES = "(" + "|".join(sorted(_MESES, key=len, reverse=True)) + ")"
_FECHA_LETRAS = re.compile(
    rf"(?<!\d)(\d{{1,2}})[º°ª]?\)?\s+(?:de\s+)?{_MES}\b\.?\s+"
    r"(?:(?:de|del)\s+)?(?:[a-záéíóúñ ]{3,80}?\(\s*)?(\d{4})(?!\d)",
    re.IGNORECASE,
)
_FECHA_MES_PRIMERO = re.compile(rf"\b{_MES}\b\.?\s+(\d{{1,2}})[º°ª]?\s+(?:de|del)\s+(\d{{4}})(?!\d)", re.IGNORECASE)

_RESULTADO = {
    "CONFIRMAR": ["confirm"],
    "REVOCAR": ["revoc"],
    "MODIFICAR": ["modific"],
}
_RAIZ_CONCEDER = r"conced\w*\s+(?:la\s+)?(?:tutela|proteccion)"
_RAIZ_NEGAR = r"neg(?:ar(?:a|an|ia|ian|se|l[aeo]s?)?|o|aron|ando)\b"
# El tipo de carencia (#89), con sus variantes de número y escritura («hechos superados», «daño ya consumado», «dano», «situación
# sobrevenida»): nombrar el tipo decidido con otra grafía no es nombrar otro tipo.
_TIPO_DE_CARENCIA = {
    "CARENCIA_HECHO_SUPERADO": r"hechos?\s+(?:ya\s+)?superados?\b",
    "CARENCIA_DANO_CONSUMADO": r"da[ñn]os?\s+(?:ya\s+)?consumados?\b",
    "CARENCIA_SOBREVINIENTE": r"(?:sobrevinient|sobrevenid)",
}
# Lo que el mensaje muestra por cada raíz que no sea el prefijo literal.
_ETIQUETA_RAIZ = {
    _RAIZ_CONCEDER: ["conceder la tutela/protección…"],
    _RAIZ_NEGAR: ["negar", "negará", "negarán", "negaría", "negarían", "negó", "negaron", "negando"],
    _TIPO_DE_CARENCIA["CARENCIA_HECHO_SUPERADO"]: ["declarar la carencia actual de objeto por hecho superado"],
    _TIPO_DE_CARENCIA["CARENCIA_DANO_CONSUMADO"]: ["declarar la carencia actual de objeto por daño consumado"],
    _TIPO_DE_CARENCIA["CARENCIA_SOBREVINIENTE"]: ["declarar la carencia actual de objeto por situación sobreviniente"],
}
_SUSTITUTIVA = {
    "AMPARAR": ["ampar", r"tutel(?!as?\b)", _RAIZ_CONCEDER],
    "NEGAR": [_RAIZ_NEGAR, "nieg", "deneg"],
    "IMPROCEDENTE": ["improceden"],
    # La carencia sin el tipo decidido no basta (decisión del dueño: bloquea, con reintento del modelo).
    **{tipo: [patron] for tipo, patron in _TIPO_DE_CARENCIA.items()},
}


def contar_palabras(texto: str) -> int:
    return len(texto.split())


def _resumir(lineas: list[int]) -> str:
    vistas = ", ".join(str(n) for n in lineas[:MAX_LINEAS_CITADAS])
    return vistas + ("…" if len(lineas) > MAX_LINEAS_CITADAS else "")


def lint_prosa(texto: str, campo: str, permitir_listas: bool = False) -> list[str]:
    encabezados: list[int] = []
    vinetas: list[int] = []
    rotulos: list[tuple[int, str]] = []
    for n, linea in enumerate(texto.splitlines(), 1):
        if _ENCABEZADO.match(linea):
            encabezados.append(n)
        elif m := _ROTULO.match(linea):
            rotulos.append((n, m.group(1)))
        elif _VINETA.match(linea):
            vinetas.append(n)
    msgs: list[str] = []
    if encabezados:
        msgs.append(f"{BLOQUEA}{campo}: contiene encabezados markdown (líneas {_resumir(encabezados)}); debe ser prosa corrida.")
    if "**" in texto:
        msgs.append(f"{BLOQUEA}{campo}: contiene marcas de negrita markdown (**); debe ser prosa corrida.")
    for n, rotulo in rotulos[:MAX_LINEAS_CITADAS]:
        msgs.append(f"{BLOQUEA}{campo}: la línea {n} empieza con el rótulo «{rotulo}:»; debe ser prosa corrida.")
    if vinetas and not permitir_listas:
        msgs.append(f"{ALERTA}{campo}: contiene viñetas o numerales (líneas {_resumir(vinetas)}); se espera prosa corrida.")
    return msgs


def anclas_literales(apertura: AperturaLLM, ing: Ingesta) -> list[str]:
    docs = {d.doc_id: d for d in ing.documentos}
    textos: dict[str, str] = {}
    msgs: list[str] = []

    def revisar(etiqueta: str, doc_id: str, cita: str) -> None:
        doc = docs.get(doc_id)
        if doc is None:
            msgs.append(f"{BLOQUEA}{etiqueta}: el documento «{doc_id}» no existe en el expediente.")
            return
        if doc_id not in textos:
            textos[doc_id] = doc.texto()
        cob = cobertura(cita, textos[doc_id], NGRAMA_ANCLA)
        if cob is None:
            msgs.append(f"{BLOQUEA}{etiqueta}: la cita literal está vacía.")
        elif cob < COBERTURA_ANCLA:
            msgs.append(
                f"{BLOQUEA}{etiqueta}: la cita literal «{cita[:70]}» no aparece en el documento {doc_id} "
                f"(cobertura {cob:.0%}; se exige al menos {COBERTURA_ANCLA:.0%})."
            )

    for i, ev in enumerate(apertura.cronologia, 1):
        revisar(f"Cronología, evento {i}", ev.doc_id, ev.cita_literal)
    for r in apertura.reparos:
        revisar(f"Reparo {r.id}", r.doc_id, r.cita_literal)
    return msgs


def _fechas(texto: str) -> set[tuple[int, int, int]]:
    fechas = {(int(a), int(m), int(d)) for a, m, d in _FECHA_ISO.findall(texto)}
    fechas |= {(int(a), int(m), int(d)) for d, m, a in _FECHA_NUM.findall(texto)}
    fechas |= {(int(a), _MESES[m.lower()], int(d)) for d, m, a in _FECHA_LETRAS.findall(texto)}
    fechas |= {(int(a), _MESES[m.lower()], int(d)) for m, d, a in _FECHA_MES_PRIMERO.findall(texto)}
    return fechas


_PALABRA = r"[a-záéíóúñ]+"
_FECHA_EN_LETRAS = re.compile(
    rf"(?<![a-záéíóúñ])({_PALABRA}(?:\s+y\s+{_PALABRA})?)\s+de\s+{_MES}\s+del?\s+((?:{_PALABRA}\s*){{1,7}})",
    re.IGNORECASE,
)

def _a_entero(palabras: str) -> int | None:
    t = " ".join(palabras.lower().split())
    total = 0
    for patron, factor, solo_singular in ((r"millón|millon|millones", 10**6, True), (r"mil", 1000, False)):
        m = re.match(rf"^(?:(.+?)\s+)?({patron})\b\s*(.*)$", t)
        if m:
            if m.group(1):
                n = letras_a_numero(m.group(1))
            else:
                n = None if solo_singular and m.group(2) == "millones" else 1
            if n is None:
                return None
            total += n * factor
            t = m.group(3)
    if t:
        n = letras_a_numero(t)
        if n is None:
            return None
        total += n
    return total or None


def _anio_en_letras(palabras: str) -> int | None:
    tokens = palabras.split()
    for k in range(len(tokens), 0, -1):
        n = _a_entero(" ".join(tokens[:k]))
        if n is not None and 1900 <= n <= 2100:
            return n
    return None


def _fechas_en_letras(texto: str) -> set[tuple[int, int, int]]:
    plano = " ".join(texto.split())
    fechas = set()
    for dia, mes, anio in _FECHA_EN_LETRAS.findall(plano):
        d, a = letras_a_numero(dia), _anio_en_letras(anio)
        if d is not None and a is not None and 1 <= d <= 31:
            fechas.add((a, _MESES[mes.lower()], d))
    return fechas


_MONTO_EN_LETRAS = re.compile(rf"((?:{_PALABRA}\s+){{1,9}}?)(?:de\s+)?pesos\b", re.IGNORECASE)


def _montos_en_letras(texto: str) -> set[str]:
    plano = " ".join(texto.split())
    montos = set()
    for m in _MONTO_EN_LETRAS.finditer(plano):
        palabras = m.group(1).split()
        for k in range(len(palabras)):
            n = _a_entero(" ".join(palabras[k:]))
            if n is not None:
                if n >= 100_000:
                    montos.add(str(n))
                break
    return montos


def _identificadores(texto: str) -> tuple[set[str], set[str], set[tuple[int, int, int]]]:
    cuis = {re.sub(r"\D", "", m) for m in _CUI.findall(texto)}
    resto = _CUI.sub(" ", texto)
    numeros = {re.sub(r"\D", "", m) for m in _NUMERO.findall(resto)}
    numeros = {n for n in numeros if len(n) >= 6} | _montos_en_letras(resto)
    return cuis, numeros, _fechas(resto) | _fechas_en_letras(resto)


def _fecha_valida(f: tuple[int, int, int]) -> bool:
    try:
        date(*f)
    except ValueError:
        return False
    return True


def datos_ajenos(texto: str, ing: Ingesta) -> list[str]:
    cuis_doc, nums_doc, fechas_doc = _identificadores("\n\n".join(ing.textos_visibles()))
    meta = ing.metadatos
    cuis_doc |= {re.sub(r"\D", "", c) for c in (meta.cui_1a, meta.cui_2a) if c}
    fechas_doc |= {
        tuple(int(x) for x in v[:10].split("-"))
        for v in meta.fechas.model_dump().values()
        if v and re.match(r"\d{4}-\d{2}-\d{2}", v)
    }

    cuis, nums, fechas = _identificadores(texto)
    msgs = [
        f"{BLOQUEA}El radicado {c} que aparece en el texto no figura en ningún documento del caso."
        for c in sorted(cuis - cuis_doc)
    ]
    msgs += [
        f"{BLOQUEA}El número {n} (cédula, NIT u otro identificador de 6 o más dígitos) que aparece en el texto "
        "no figura en ningún documento del caso."
        for n in sorted(nums - nums_doc)
    ]
    for a, m, d in sorted(fechas - fechas_doc):
        if _fecha_valida((a, m, d)):
            msgs.append(f"{BLOQUEA}La fecha {d:02d}/{m:02d}/{a} que aparece en el texto no figura en ningún documento del caso.")
        else:
            msgs.append(f"{BLOQUEA}La fecha {d:02d}/{m:02d}/{a} que aparece en el texto no es una fecha válida.")
    return msgs


def _nombre_comparable(nombre: str) -> str:
    palabras = normalizar_texto(nombre).split()
    return " ".join(p for p in palabras if len(p) > 1 and p not in _SUFIJOS_SOCIETARIOS)


def guardia_p3(consideraciones: ConsideracionesLLM, metadatos: Metadatos) -> list[str]:
    bloques = consideraciones.bloques
    texto = "\n".join(
        [consideraciones.procedibilidad, *(b.titulo for b in bloques), *(b.texto for b in bloques)]
    )
    norm = f" {normalizar_texto(texto, False)} "
    partes = [("el accionante", metadatos.accionante)]
    partes += [("una accionada", n) for n in metadatos.accionadas]
    partes += [("una vinculada", n) for n in metadatos.vinculadas]
    msgs: list[str] = []
    for rol, nombre in partes:
        n = _nombre_comparable(nombre or "")
        if len(n.split()) >= 2 and f" {n} " in norm:
            msgs.append(
                f"{BLOQUEA}Las consideraciones mencionan a {rol} «{nombre}»; el análisis doctrinal no puede contener datos del caso."
            )
    cuis_caso = {re.sub(r"\D", "", c) for c in (metadatos.cui_1a, metadatos.cui_2a) if c}
    for c in sorted({re.sub(r"\D", "", m) for m in _CUI.findall(texto)} & cuis_caso):
        msgs.append(f"{BLOQUEA}Las consideraciones contienen el radicado del caso ({c}); no puede aparecer en el análisis doctrinal.")
    return msgs


def _marcadores_mal_formados(texto: str) -> list[str]:
    return [
        f"{BLOQUEA}Marcador de cita mal formado «{m}»; use exactamente [[CITA:id]]."
        for m in _MARCADOR_LAXO.findall(texto)
        if not _MARCADOR.fullmatch(m)
    ]


def _menciones_sueltas(texto: str) -> tuple[set[str], set[tuple[str, int]]]:
    fuera = _MARCADOR_CUALQUIERA.sub(" ", texto)
    completas = sentencias_en_texto(fuera)
    sin_anio = {(t, int(n)) for t, n in _SIN_ANIO.findall(RE_SENTENCIA.sub(" ", fuera))}
    return completas, sin_anio


def _texto_caso(caso: CasoConcretoLLM) -> str:
    return "\n\n".join([caso.problema_juridico, *(p.texto for p in caso.parrafos), caso.conclusion])


def subconjunto_citas(caso: CasoConcretoLLM, citas: list[CitaVerificada]) -> list[str]:
    texto = _texto_caso(caso)
    por_id = {c.id: c for c in citas}
    validas = [c for c in citas if c.estado in ("ok", "alerta")]
    claves = {c.sentencia_norm for c in validas if c.sentencia_norm}
    numeros = {(c.tipo, c.numero) for c in validas}
    msgs = _marcadores_mal_formados(texto)
    for id_ in dict.fromkeys(_MARCADOR.findall(texto)):
        cita = por_id.get(id_)
        if cita is None:
            msgs.append(f"{BLOQUEA}El marcador [[CITA:{id_}]] no corresponde a ninguna cita verificada.")
        elif cita.estado == "rechazada":
            msgs.append(f"{BLOQUEA}El marcador [[CITA:{id_}]] usa una cita rechazada ({cita.sentencia_original}).")
    completas, sin_anio = _menciones_sueltas(texto)
    for clave in sorted(completas - claves):
        msgs.append(
            f"{BLOQUEA}La sentencia {clave} se menciona fuera de un marcador y no está entre las citas verificadas."
        )
    for tipo, numero in sorted(sin_anio - numeros):
        msgs.append(
            f"{BLOQUEA}La sentencia {tipo}-{numero:03d} se menciona sin año y no está entre las citas verificadas."
        )
    return msgs


def cita_verificada_en_caso(caso: CasoConcretoLLM, citas: list[CitaVerificada], permitir_alerta: bool) -> list[str]:
    utilizables = [c for c in citas if c.estado == "ok" or (permitir_alerta and c.estado == "alerta")]
    if not utilizables:
        return [
            f"{ALERTA}No hay ninguna cita verificada utilizable para el caso concreto; esta sección queda sin "
            "jurisprudencia citada. Revise las citas de las consideraciones."
        ]
    ids = {c.id for c in utilizables}
    if ids & set(_MARCADOR.findall("\n".join(p.texto for p in caso.parrafos))):
        return []
    disponibles = ", ".join(f"[[CITA:{c.id}]] ({c.sentencia_original})" for c in utilizables)
    return [
        f"{BLOQUEA}Ningún párrafo del caso concreto contiene un marcador de una cita verificada. Regla: al menos un "
        "argumento de fondo debe cerrar con la regla jurisprudencial que lo respalda, citada solo con su marcador "
        "[[CITA:id]]; el sistema inserta el fragmento verificado, de modo que no lo transcriba ni lo ponga entre "
        f"comillas. Citas utilizables: {disponibles}."
    ]


_COMILLAS = re.compile(r"«([^»\n]+)»|“([^”\n]+)”|\"([^\"\n]+)\"")


def pasajes_entre_comillas(caso: CasoConcretoLLM, ing: Ingesta, citas: list[CitaVerificada]) -> list[str]:
    campos = {"problema jurídico": caso.problema_juridico}
    campos.update({f"párrafo {i}": p.texto for i, p in enumerate(caso.parrafos, 1)})
    campos["conclusión"] = caso.conclusion
    corpus: str | None = None
    msgs: list[str] = []
    for campo, texto in campos.items():
        for m in _COMILLAS.finditer(texto):
            pasaje = next(g for g in m.groups() if g is not None).strip()
            if contar_palabras(pasaje) < MIN_PALABRAS_PASAJE:
                continue
            if corpus is None:
                corpus = "\n\n".join(ing.textos_visibles())
            cob = cobertura(pasaje, corpus, NGRAMA_ANCLA)
            if cob is None or cob >= COBERTURA_ANCLA:
                continue
            inicio = " ".join(pasaje.split())[:70]
            origen = next(
                (c for c in citas if (cobertura(pasaje, c.texto_citado, NGRAMA_ANCLA) or 0) >= COBERTURA_PASAJE_CITA),
                None,
            )
            if origen is not None:
                msgs.append(
                    f"{BLOQUEA}Caso concreto, {campo}: el pasaje entre comillas «{inicio}» reproduce el texto de la cita "
                    f"{origen.id} ({origen.sentencia_original}). Regla: la jurisprudencia se cita solo con su marcador "
                    f"[[CITA:{origen.id}]]; el sistema inserta el fragmento verificado, así que no transcriba sentencias."
                )
            else:
                msgs.append(
                    f"{BLOQUEA}Caso concreto, {campo}: el pasaje entre comillas «{inicio}» no consta en el expediente ni "
                    "en la decisión. Regla: lo que va entre comillas debe copiarse literalmente de los documentos del "
                    "caso; la jurisprudencia se cita solo con [[CITA:id]], las normas por su número y año y lo demás se "
                    "formula sin comillas."
                )
    return msgs[:MAX_LINEAS_CITADAS]


_UNIDAD_PLAZO = {
    "horas_habiles": ("f", "hora", "hora hábil", "horas hábiles"),
    "horas": ("f", "hora", "hora", "horas"),
    "dias_habiles": ("m", "dia", "día hábil", "días hábiles"),
    "dias": ("m", "dia", "día", "días"),
}


def _menciona_plazo(norm: str, plazo: Plazo) -> bool:
    genero, raiz, *_ = _UNIDAD_PLAZO[plazo.unidad]
    formas = {str(plazo.n)}
    if 0 <= plazo.n < 1_000_000:
        formas.add(normalizar_texto(numero_a_letras(plazo.n, genero), False))
    if plazo.n == 1:
        formas |= {"un", "una", "uno"}
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(f)}(?:\s+\S+){{0,2}}?\s+{raiz}s?\b", norm) for f in formas
    )


def plazos_en_caso(caso: CasoConcretoLLM, decision: Decision) -> list[str]:
    norm = normalizar_texto("\n".join(p.texto for p in caso.parrafos), False)
    sin_mencion: dict[tuple[int, str], list[int]] = {}
    for i, o in enumerate(decision.ordenes, 1):
        if o.verbo == "ORDENAR" and not o.mismo_termino and not _menciona_plazo(norm, o.plazo):
            sin_mencion.setdefault((o.plazo.n, o.plazo.unidad), []).append(i)
    msgs = []
    for (n, unidad), numeros in sin_mencion.items():
        etiqueta = _UNIDAD_PLAZO[unidad][2] if n == 1 else _UNIDAD_PLAZO[unidad][3]
        orden = f"la orden {numeros[0]}" if len(numeros) == 1 else f"las órdenes {', '.join(map(str, numeros[:-1]))} y {numeros[-1]}"
        msgs.append(
            f"{ALERTA}El caso concreto no menciona el plazo de {n} {etiqueta} que la decisión fija en {orden}; la "
            "motivación debe reflejar el alcance y el plazo de las órdenes."
        )
    return msgs


def marcadores_consideraciones(cons: ConsideracionesLLM) -> list[str]:
    texto = "\n".join([cons.procedibilidad, *(f"{b.titulo}\n{b.texto}" for b in cons.bloques)])
    ids = [c.id for c in cons.citas]
    msgs = _marcadores_mal_formados(texto)
    for id_ in sorted({i for i in ids if ids.count(i) > 1}):
        msgs.append(f"{BLOQUEA}El id de cita «{id_}» está repetido.")
    usados = list(dict.fromkeys(_MARCADOR.findall(texto)))
    for id_ in usados:
        if id_ not in ids:
            msgs.append(f"{BLOQUEA}El marcador [[CITA:{id_}]] no corresponde a ninguna cita propuesta.")
    for c in cons.citas:
        if c.id not in usados:
            msgs.append(f"{BLOQUEA}La cita {c.id} ({c.sentencia}) no se usa en ningún marcador del texto.")
    completas, sin_anio = _menciones_sueltas(texto)
    for clave in sorted(completas):
        msgs.append(f"{BLOQUEA}La sentencia {clave} se menciona fuera de un marcador; use [[CITA:id]].")
    for tipo, numero in sorted(sin_anio):
        msgs.append(f"{BLOQUEA}La sentencia {tipo}-{numero:03d} se menciona fuera de un marcador; use [[CITA:id]].")
    return msgs


def _detalle_cita(c: CitaVerificada) -> str:
    motivos = [m for m in c.motivos if not m.startswith(PREFIJO_REGLA)]
    pasaje = [m for m in motivos if c.pasaje_cercano and c.pasaje_cercano in m]
    otros = " ".join(m for m in motivos if m not in pasaje)
    cupo = max(MIN_CHARS_MOTIVOS_EN_MINIMO, MAX_CHARS_CITA_EN_MINIMO - sum(map(len, pasaje)))
    if len(otros) > cupo:
        otros = otros[:cupo].rstrip() + "…"
    return " ".join(x for x in (otros, *pasaje) if x) or "sin detalle."


def _ids_repetidas(citas: list[CitaVerificada]) -> list[str]:
    textos = [f" {normalizar_texto(c.texto_citado)} " for c in citas]
    contadas: list[str] = []
    repetidas: set[int] = set()
    for k in sorted(range(len(citas)), key=lambda k: -len(textos[k])):
        if any(textos[k] in otra for otra in contadas):
            repetidas.add(k)
        else:
            contadas.append(textos[k])
    return [c.id for k, c in enumerate(citas) if k in repetidas]


def minimo_citas_ok(citas: Iterable[CitaVerificada], minimo: int, min_palabras: int) -> list[str]:
    citas = list(citas)
    verificadas = [c for c in citas if c.estado == "ok"]
    repetidas = _ids_repetidas(verificadas)
    ok = len(verificadas) - len(repetidas)
    if ok >= max(minimo, 1):
        return []
    if ok >= minimo:
        return [f"{ALERTA}Las consideraciones no tienen ninguna cita verificada; revise la jurisprudencia que las respalda."]
    sin_acceso = sum(1 for c in citas if c.relatoria == "inaccesible" and c.estado == "alerta")
    if ok + sin_acceso >= minimo:
        return [
            f"{ALERTA}Las consideraciones tienen {ok} {'cita verificada' if ok == 1 else 'citas verificadas'} y se exigen "
            f"al menos {minimo}, pero {sin_acceso} no se pudieron verificar porque la relatoría de la Corte no respondió "
            "desde el servidor (no están rechazadas); verifíquelas en la relatoría antes de firmar."
        ]
    rechazadas = sum(1 for c in citas if c.estado == "rechazada")
    para_revisar = sum(1 for c in citas if c.estado == "alerta")
    detalle = "".join(
        f"\n- Cita {c.id} ({c.sentencia_original}, {_ESTADO_EN_MINIMO[c.estado]}): {_detalle_cita(c)}"
        for c in citas
        if c.estado != "ok"
    )
    distintas = (" distinta" if ok == 1 else " distintas") if repetidas else ""
    contenidas = f"; repetidas o contenidas en otra cita verificada: {', '.join(repetidas)}" if repetidas else ""
    return [
        f"{BLOQUEA}Las consideraciones tienen {ok} {'cita verificada' if ok == 1 else 'citas verificadas'}{distintas}; "
        f"se exigen al menos {minimo} (propuestas: {len(citas)}; rechazadas: {rechazadas}; para revisar: {para_revisar}"
        f"{contenidas}, que no cuentan)."
        + (f" Citas que no cuentan:{detalle}\n" if detalle else " ")
        + "Regla: cada cita es un fragmento literal de la ratio decidendi de la sentencia, de una a tres "
        f"frases completas y de al menos {min_palabras} palabras, tomado de la parte de la mayoría (no de un salvamento "
        "ni de una aclaración de voto) y que no sea texto de la Constitución, de un decreto ni de una ley. "
        "Sustituya las citas rechazadas o insuficientes por otras que cumplan la regla y no acorte el fragmento "
        "para que pase."
    ]


_JURISPRUDENCIA_HA = re.compile(
    r"\bla\s+jurisprudencia\b"
    r"(?:\s+(?:constitucional|pac[ií]fica|reiterada|uniforme|de\s+(?:la|esta)\s+corte(?:\s+constitucional)?|de\s+esta\s+corporaci[oó]n))*"
    r"[\s,]*(?:(?:de\s+(?:manera|forma|modo)\s+\w+|\w+mente)[\s,]*)*\bhan?\b",
    re.IGNORECASE,
)
_FIN_ORACION = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡«\"“])|\n+")


def jurisprudencia_sin_cita(texto: str, campo: str) -> list[str]:
    msgs: list[str] = []
    for oracion in _FIN_ORACION.split(texto):
        if _JURISPRUDENCIA_HA.search(oracion) and not _MARCADOR.search(oracion):
            inicio = " ".join(oracion.split())[:80]
            msgs.append(
                f"{ALERTA}{campo}: la oración «{inicio}» atribuye una regla a «la jurisprudencia» sin un marcador "
                "[[CITA:id]] en la misma oración; respáldela con una cita verificada o formúlela sin atribuirla."
            )
    return msgs[:MAX_LINEAS_CITADAS]


def _contiene_raiz(norm: str, patron: str) -> bool:
    return re.search(rf"(?<![a-zñ0-9]){patron}", norm) is not None


_NO_PRECEDE = r"(?<![a-zñáéíóú0-9])"
_NEGADOR_PREVIO = re.compile(
    r"\b(?:no|tampoco|ni|nunca|jam[aá]s|en\s+modo\s+alguno)(?:\s+(?:se|le|les|lo|la))*\s*$"
)
_CONDICIONAL_PREVIO = re.compile(
    r"(?:^|[,;:(«\"“—–-]\s*|[.!?]\s+|\b(?:y|e|o|pero|pues|porque|que|aun|aún|incluso|máxime|como"
    r"|es\s+decir)\s+)(?:solo\s+|sólo\s+)?si\b(?!\s+bien)[^.;]{0,80}$"
)


_CONDICIONAL_EXCEPTO = re.compile(
    r"\b(?:salvo(?:\s+que|\s+si)?|excepto(?:\s+que|\s+si)?|siempre\s+y\s+cuando|a\s+menos\s+que|con\s+tal\s+de\s+que"
    r"|(?:[uú]nicamente|solamente|s[oó]lo|solo)\s+(?:si|cuando|en\s+caso)"
    r"|caso\s+en\s+el\s+cual|en\s+cuyo\s+caso|en\s+tal\s+caso|en\s+ese\s+caso)\b[^.;!?]{0,80}$"
)
_HIPOTETICO_PREVIO = re.compile(
    r"(?<!dicho )(?<!expresado )(?<!decirlo )"
    r"\b(?:de\s+lo\s+contrario|en\s+caso\s+contrario|de\s+otro\s+modo|so\s+pena)\b[^.!?;]{0,60}$"
)
_SI_POSTERIOR = re.compile(
    r"[^.;!?]{0,60}?\b(?:(?:solo|s[oó]lo|[uú]nicamente|solamente)\s+si|siempre\s+(?:que|y\s+cuando)"
    r"|a\s+condici[oó]n\s+de\s+que|en\s+caso\s+de\s+que)\b"
)
_MARCA_PARCIAL = re.compile(r"\b(?:dem[aá]s|restantes)\b")
_CONCESION = re.compile(
    r"\b(?:ampar|tutel)(?:ar[aá]n?|ar[ií]an?|ar|ando)\b|\bampar(?:an?)\b"
    r"|\bconceder(?:[aá]n?)?\s+(?:la\s+|el\s+)?(?:tutela|protecci[oó]n|amparo)\b"
)
# Qué se niega. Si es el amparo mismo, la negación contradice AMPARAR; si es una pretensión accesoria («el tratamiento
# integral», «la exoneración de copagos»), es una negación parcial legítima.
# Eso se decide por el núcleo («amparo», «tutela», «acción»…), no por las palabras que lo preceden: tras el determinante caben
# hasta tres palabras sueltas («el citado amparo», «la presente acción de tutela», «cualquier tutela», «ahora el amparo») y, si
# tras ellas viene el núcleo, lo que se niega es el amparo mismo. Solo si antes del núcleo hay una preposición o una conjunción
# («el tratamiento integral de la tutela», «el transporte pues la tutela…»), o más de tres palabras, el núcleo es de otra frase y
# lo negado es una pretensión accesoria. Decidirlo por una lista de determinantes dejaba pasar la negación del amparo mismo con
# cada palabra que la lista no traía, y la lista no se acababa nunca.
# Cada palabra se lee de una sola forma (determinante, palabra suelta o corte): «la totalidad de» no absorbe el artículo que sigue
# (lo toma la iteración siguiente) y las palabras sueltas excluyen a los determinantes. Con alternativas solapadas bajo un
# cuantificador, un texto que no casa costaría 2^n pasos.
_DET_PALABRA = (
    r"(?:[a-zñáéíóú]+mente|también|además|asimismo|entonces|el|la|los|las|su|sus|un|una|todas?|todos?|tales"
    r"|dich[oa]s?|estas?|estos?|este|esas?|esos?|ese|aquel(?:l[ao]s?)?)"
)
_DETERMINANTE = rf"(?:(?:{_DET_PALABRA}|la\s+totalidad\s+del?)\s+)*"
# Las preposiciones y conjunciones de las que nace una frase nueva. `_SIN_COMPLEMENTO` (lo que sigue a «negará») y
# `_CORTE` (lo que corta las palabras sueltas) parten de la misma lista para no desalinearse. `_CORTE` añade los relativos y
# subordinantes («cuando», «cuyo», «donde»…) y los pronombres «se», «le», «les», que también abren una frase nueva.
_NEXO = r"por|en|con|pues|porque|ya|dado|sin|para|ante|al|a|y|e|o|que|como|aunque|pero|si"
_CORTE = (
    rf"(?:{_NEXO}|de|del|u|ni|se|le|les|respecto|sobre|contra|desde|hasta|entre|seg[uú]n|cuando|mientras|mediante|durante"
    r"|tras|bajo|hacia|salvo|excepto|donde|cual(?:es)?|quienes?|cuy[oa]s?)"
)
# Una palabra suelta no es determinante ni corte: así cada palabra tiene una sola lectura y las palabras sueltas son un `{0,3}`
# aparte, no una alternativa más del `(?:…)*`. Los determinantes que siguen a una palabra suelta («solo el amparo») no gastan
# ninguna de las tres.
_RELLENO = rf"(?:(?!{_DET_PALABRA}\b|{_CORTE}\b)[a-zñáéíóú]+\s+{_DETERMINANTE}){{0,3}}"
_PRETENSION_GENERICA = r"(?:pretensi[oó]n(?:es)?|s[uú]plicas?|solicitud(?:es)?|petici[oó]n(?:es)?|pedimentos?|reclamaci[oó]n(?:es)?|demanda)"
# «las pretensiones accesorias» no es el amparo mismo: la pretensión que el adjetivo califica de accesoria es la que se niega.
_ADJETIVO_ACCESORIO = r"(?:accesori|adicional|subsidiari|complementari)"
# Lo que sigue a «pretensiones de / solicitud de / petición de…» se lee con la misma regla que lo que sigue a «negará»: determinantes
# y hasta tres palabras sueltas («de la presente acción», «de esta acción», «del citado amparo») y, tras ellas, el núcleo
# («acción», «tutela», «amparo», «protección», o la parte: «accionante», «actor», «demandante», «peticionario», en plural también).
_AMPARO_COMO_OBJETO = (
    rf"{_DETERMINANTE}{_RELLENO}(?:amparos?|tutelas?|acci(?:[oó]n|ones)|protecci(?:[oó]n|ones)|accionantes?|actor(?:es|as?)?"
    r"|demandantes?|peticionari\w+)"
)
_ES_EL_AMPARO = re.compile(
    rf"\s*{_DETERMINANTE}{_RELLENO}(?:(?:amparos?|tutelas?|protecci(?:[oó]n|ones)|acci(?:[oó]n|ones)|derechos?)\b"
    rf"|{_PRETENSION_GENERICA}\b(?!\s+(?:de|del)\s+(?!{_AMPARO_COMO_OBJETO}\b))(?!\s+{_ADJETIVO_ACCESORIO})"
    r"|lo\s+(?:solicitado|pedido|pretendido|impetrado|reclamado|demandado))"
)
_SIN_COMPLEMENTO = re.compile(rf"\s*(?:$|[,.;:!?)»\"]|(?:{_NEXO}|toda\s+vez)\b)")
_PALABRA_SUSTANTIVA = re.compile(rf"\s*{_DETERMINANTE}(?:lo\s+)?[a-zñáéíóú]{{3,}}")


def _niega_pretension_accesoria(texto: str, m: re.Match[str]) -> bool:
    if _SIN_COMPLEMENTO.match(texto, m.end()) or _ES_EL_AMPARO.match(texto, m.end()):
        return False
    return _PALABRA_SUSTANTIVA.match(texto, m.end()) is not None


@lru_cache(maxsize=8)
def _hay_concesion(texto: str) -> bool:
    """¿La conclusión anuncia una concesión del amparo que no niega ni condiciona? Se calcula una vez por texto y no una vez
    por cada «negará», que la recorrería entera tantas veces como negaciones tenga."""
    return any(not _excusada(texto, g.start()) and not _SI_POSTERIOR.match(texto, g.end()) for g in _CONCESION.finditer(texto))


def _negacion_parcial(texto: str, m: re.Match[str], decision: Decision) -> bool:
    # Confirmar un amparo ya es conceder: no hace falta que la conclusión lo vuelva a anunciar.
    if decision.resultado != "CONFIRMAR" and not _hay_concesion(texto):
        return False
    if _niega_pretension_accesoria(texto, m):
        return True
    ini = max(texto.rfind(c, 0, m.start()) for c in ".;!?") + 1
    fins = [k for k in (texto.find(c, m.end()) for c in ".;!?") if k != -1]
    fin = min(fins) if fins else len(texto)
    return bool(_MARCA_PARCIAL.search(texto[max(ini, m.start() - 80) : min(fin, m.end() + 80)]))


# Cada excusa empieza como mucho ~100 caracteres antes de lo que excusa (su palabra clave y «[^.;]{0,80}$», sobre texto con
# los espacios ya normalizados): se busca solo en esa ventana y no desde el principio por cada coincidencia. Buscar con
# `pos`/`endpos` no es recortar: «^» sigue siendo el inicio real y «\b» y las búsquedas hacia atrás ven lo anterior.
_VENTANA_EXCUSA = 200


def _excusada(texto: str, inicio: int) -> bool:
    desde = max(0, inicio - _VENTANA_EXCUSA)
    return bool(
        _NEGADOR_PREVIO.search(texto[max(0, inicio - 40) : inicio])
        or _HIPOTETICO_PREVIO.search(texto, desde, inicio)
        or _CONDICIONAL_PREVIO.search(texto, desde, inicio)
        or _CONDICIONAL_EXCEPTO.search(texto, desde, inicio)
    )


# --- #89: tipo de carencia --------------------------------------------------------------------------------------------
# Entre «la carencia» y el tipo solo caben palabras de una lista cerrada («actual de objeto por», «al configurarse un») y comas:
# así, el tipo que se declara es, sin ambigüedad, el que sigue a esa fórmula. «…por situación sobreviniente, distinta del hecho
# superado» o «…por daño consumado, y no por hecho superado» no declaran el hecho superado: antes de él hay otro tipo, una
# negación o una palabra que no es de la fórmula. Cada palabra se lee de una sola forma («de» y «del», «a» y «al» se separan
# por el `\b`), así que el `{0,10}` no retrocede más que diez pasos.
_PALABRA_DE_LA_CARENCIA = (
    r"(?:actual|objeto|de|del|por|ante|tras|al|a|la|el|un|una|en|debido|raz[oó]n|situaci[oó]n|configurarse|configurad[oa]"
    r"|configuraci[oó]n|haberse|existir|existencia|presentarse|presentad[oa]|operad[oa]|acaecid[oa]|ocurrid[oa]|derivad[oa]"
    r"|originad[oa])"
)
_HUECO_CARENCIA = rf"(?:\s*,|\s+{_PALABRA_DE_LA_CARENCIA}\b){{0,10}}\s+"
_CARENCIA = r"declarar(?:á|án|ía|ían)\s+la\s+carencia" + _HUECO_CARENCIA
_CARENCIA_INF = r"declarar\s+la\s+carencia" + _HUECO_CARENCIA
_CLITICO = r"(?:l[aeo]s?)?"
_FUTURO_RESULTADO = {
    "CONFIRMAR": r"confirmar(?:á|án|ía|ían)\b",
    "REVOCAR": r"revocar(?:á|án|ía|ían)\b",
}
_FUTURO_SUSTITUTIVA = {
    "AMPARAR": r"(?:(?:ampar|tutel)ar(?:á|án|ía|ían)\b|conceder(?:á|án)\s+(?:la\s+|el\s+)?(?:tutela|protecci[oó]n|amparo))",
    "NEGAR": r"(?:neg|deneg)ar(?:á|án|ía|ían)\b",
    "IMPROCEDENTE": r"declarar(?:á|án|ía|ían)\s+(?:la\s+)?(?:acci[oó]n\s+(?:de\s+tutela\s+)?)?improcedente",
    **{tipo: _CARENCIA + patron for tipo, patron in _TIPO_DE_CARENCIA.items()},
}
# La misma familia en infinitivo, que es la forma que ordena el prompt («corresponde revocar y negar el amparo»). Se prueba solo
# donde empieza un infinitivo que anuncia el Despacho (`_infinitivos_anunciados`), nunca en cualquier punto del texto.
_INFINITIVO_RESULTADO = {
    "CONFIRMAR": re.compile(rf"confirmar{_CLITICO}\b"),
    "REVOCAR": re.compile(rf"revocar{_CLITICO}\b"),
}
_INFINITIVO_SUSTITUTIVA = {
    "AMPARAR": re.compile(rf"(?:(?:ampar|tutel)ar{_CLITICO}\b|conceder\s+(?:la\s+|el\s+)?(?:tutela|protecci[oó]n|amparo))"),
    "NEGAR": re.compile(rf"(?:neg|deneg)ar{_CLITICO}\b"),
    "IMPROCEDENTE": re.compile(r"declarar\s+(?:la\s+)?(?:acci[oó]n\s+(?:de\s+tutela\s+)?)?improcedente"),
    **{tipo: re.compile(_CARENCIA_INF + patron) for tipo, patron in _TIPO_DE_CARENCIA.items()},
}

# --- #89: cuándo un infinitivo es el resultado que anuncia el Despacho ----------------------------------------------------
# Un infinitivo puede ser lo que anuncia el Despacho («corresponde revocar y negar el amparo»), pero también lo que pide la EPS,
# lo que hizo el a quo o lo que debe hacer un tercero. Buscar a ese otro no converge: la lengua tiene infinitas formas de
# nombrarlo (cada ronda de revisión de esta regla encontró una nueva). Por eso se hace al revés: el infinitivo solo cuenta si la
# oración entera deja sin ambigüedad que lo anuncia el Despacho, y eso se comprueba con listas cerradas:
#   1. La apertura —todo lo que va del comienzo de la oración al disparador— es, entera, una de las formas de `_APERTURA`:
#      conectivos de una lista cerrada y, después, un impersonal («corresponde», «procede», «hay que»…), el dativo del Despacho
#      («a este Despacho le corresponde»), el Despacho como sujeto («el Despacho decide|debe», «el Despacho considera que
#      procede…»), una oración impersonal con «que» («es claro que procede…») o «deber» con el sujeto implícito tras un
#      conectivo («Por lo expuesto, debe…»). Cualquier otra palabra antes del disparador (un tercero, un dativo, una atribución,
#      un «que» de otro, una subordinada, una negación) deja la oración sin examinar.
#   2. El infinitivo sigue al disparador o va coordinado con otros infinitivos de decisión que lo siguen: entre ellos solo hay
#      sus complementos, sin puntuación ni palabras que abran otra cláusula (`_CORTA_LA_CADENA`), y los enlaces de `_ENLACE`.
#   3. El resto de la oración no atribuye nada a nadie (`_ATRIBUCION`: «…, según la EPS», «…, como lo pide la accionada»).
#   4. «Confirmar» y «revocar» recaen sobre una decisión judicial o no llevan objeto, y no son «confirmar que…»; el objeto
#      se reconoce con una forma cerrada (`_OBJETO_JUDICIAL`).
#   5. «Negar», «declarar improcedente» y «declarar la carencia» son enteros: el amparo mismo y, tras él, solo el fin de la oración
#      o una cola cerrada y los enlaces de `_cola_entera`. No se buscan las palabras que acotan una parte: no se acaban.
# Todo lo demás no se examina: es un falso negativo aceptado, porque un falso BLOQUEA detiene el borrador del juez.
#
# Las expresiones de abajo son alternativas de frases fijas. Ninguna frase de una lista es otra frase de la misma lista
# seguida de un separador (por eso no está «así pues», que ya es «así» + «pues»), de modo que cada texto se lee de una sola
# forma y los `(…)*` no retroceden de forma catastrófica.

# Fin de oración: «.», «;», «!» o «?». El punto de una sigla o abreviatura («S.A.», «E.P.S.», «Dr.») no la cierra. Los dos
# puntos tampoco: lo que sigue suele ser lo que dice otro («La EPS concluye: procede confirmar el fallo»).
_ABREVIATURAS = ("dr", "dra", "sr", "sra", "ltda", "cía", "inc")
_FIN_DE_ORACION = re.compile(r"[;!?]|(?<!\b[a-zñ])" + "".join(rf"(?<!\b{a})" for a in _ABREVIATURAS) + r"\.")
_SEP = r"(?:\s*,\s*|\s+)"
# Conectivos y locuciones con que el Despacho abre su conclusión. Solo palabras que no pueden nombrar a otro: nada de «su», de
# pronombres ni de partes; las provisionales («en principio», «a primera vista») tampoco, porque anuncian algo que se descarta.
_CONECTIVO = "(?:" + "|".join((
    r"por\s+(?:todo\s+)?lo\s+(?:expuesto|anterior|dicho|analizado|considerado|explicado|precedente|tanto)",
    r"por\s+(?:tanto|consiguiente|ende|ello|eso|esto)",
    r"por\s+(?:esta|esa)\s+raz[oó]n",
    r"por\s+(?:las\s+(?:anteriores\s+)?|estas\s+|esas\s+)razones(?:\s+(?:expuestas|anteriores|anotadas))?",
    r"en\s+(?:consecuencia|conclusi[oó]n|suma|s[ií]ntesis|definitiva|resumen|efecto)",
    r"en\s+(?:el\s+presente|este|el)\s+(?:caso|asunto)(?:\s+(?:concreto|bajo\s+(?:examen|estudio|an[aá]lisis)))?",
    r"en\s+(?:esta|la\s+presente)\s+(?:instancia|oportunidad)",
    r"en\s+todo\s+caso",
    r"as[ií]\s+las\s+cosas",
    r"as[ií]",
    r"siendo\s+as[ií]",
    r"de\s+(?:este|ese|tal)\s+modo",
    r"de\s+(?:esta|esa|tal)\s+(?:manera|forma|suerte)",
    r"en\s+(?:este|ese)\s+orden(?:\s+de\s+ideas)?",
    r"bajo\s+(?:este|ese)\s+(?:panorama|contexto|entendido)",
    r"bajo\s+(?:las|estas|esas)\s+circunstancias(?:\s+(?:descritas|expuestas|anotadas|anteriores|se[nñ]aladas))?",
    r"(?:conforme|de\s+acuerdo)\s+(?:a|con)\s+lo\s+(?:expuesto|anterior|dicho|analizado|probado|explicado)",
    r"(?:a\s+la\s+luz|en\s+(?:m[eé]rito|virtud|raz[oó]n))\s+de\s+lo\s+(?:expuesto|anterior|analizado|dicho|probado)",
    r"a\s+la\s+luz\s+de(?:l\s+(?:expediente|material\s+probatorio|acervo\s+probatorio)|\s+las\s+pruebas)",
    r"con\s+(?:base|fundamento)\s+en\s+(?:lo\s+(?:expuesto|anterior|analizado|dicho|probado)|el\s+(?:material|acervo)\s+probatorio"
    r"|las\s+pruebas)",
    r"(?:dado|visto)\s+lo\s+(?:anterior|expuesto)",
    r"de\s+lo\s+(?:anterior|expuesto|dicho)",
    r"(?:seg[uú]n|por)\s+lo\s+que\s+(?:consta|obra)\s+en\s+el\s+expediente",
    r"en\s+lo\s+que\s+(?:a\s+este\s+(?:caso|asunto)|al\s+caso\s+concreto)\s+(?:respecta|ata[nñ]e|concierne)",
    r"como\s+(?:ya\s+)?se\s+(?:dijo|expuso|explic[oó]|indic[oó]|anot[oó]|vio|advirti[oó]|se[nñ]al[oó]|analiz[oó]|precis[oó])"
    r"(?:\s+(?:antes|anteriormente|atr[aá]s|arriba|previamente|en\s+precedencia))?",
    r"a\s+esta\s+altura",
    r"entonces|pues|luego|ahora\s+bien|con\s+todo|sin\s+embargo|no\s+obstante|adem[aá]s|asimismo|igualmente|tambi[eé]n",
    r"finalmente|por\s+(?:[uú]ltimo|otra\s+parte)|de\s+otra\s+parte",
    # la opinión del propio Despacho
    r"(?:a\s+(?:juicio|criterio)|en\s+(?:criterio|concepto|opini[oó]n|(?:el\s+)?sentir))\s+(?:del\s+despacho"
    r"|de\s+(?:este\s+(?:despacho|juzgado)|esta\s+(?:sala|judicatura|instancia)|la\s+sala))",
    r"para\s+(?:(?:el|este)\s+despacho|este\s+juzgado|(?:la|esta)\s+sala|esta\s+judicatura)",
)) + ")"
# Tras el Despacho como sujeto («el Despacho considera que, a su juicio, …»), «su» solo puede ser el Despacho.
_CONECTIVO_DEL_DESPACHO = rf"(?:{_CONECTIVO}|(?:a|en)\s+su\s+(?:juicio|criterio|sentir|concepto|parecer|entender))"
_CONECTIVOS = rf"(?:(?:y\s+)?{_CONECTIVO}{_SEP})*"
_CONECTIVOS_DEL_DESPACHO = rf"(?:(?:y\s+)?{_CONECTIVO_DEL_DESPACHO}{_SEP})*"
# «Juzgado» a secas puede ser el a quo y «tribunal» el superior; solo «este Juzgado» es el Despacho.
_DESPACHO_SUJETO = (
    r"(?:(?:el|este)\s+despacho|este\s+juzgado|(?:la|esta)\s+sala|esta\s+(?:judicatura|instancia|agencia\s+judicial|sede)"
    r"|(?:el|la)\s+suscrit[oa])"
)
_DATIVO_DEL_DESPACHO = r"(?:a\s+(?:este\s+(?:despacho|juzgado)|esta\s+(?:sala|judicatura|instancia)|la\s+sala)|al\s+despacho)(?:\s+les?)?"
_IMPERSONAL = (
    r"(?:corresponde|procede(?!\s+a\b)|se\s+impone|hay\s+que|se\s+deben?"
    r"|es\s+(?:necesario|preciso|procedente|menester|imperativo|forzoso)|resulta\s+(?:necesario|preciso|procedente|imperativo|forzoso)"
    r"|lo\s+(?:procedente|que\s+procede|que\s+corresponde|pertinente)\s+es)"
)
_MODAL = r"(?:deber[aá]n?|deben?|(?:habr[aá]n?|han?)\s+de|proceder[aá]n?\s+a|procede\s+a)"
_DECIDE = r"(?:decide|decidir[aá]|resuelve|resolver[aá]|dispone|dispondr[aá])"
_OPINA = r"(?:considera|estima|concluye|entiende|encuentra|advierte|observa|colige|infiere|aprecia|constata|verifica|halla|juzga)"
_QUE_IMPERSONAL = (
    r"(?:se\s+(?:concluye|advierte|colige|observa|sigue|tiene|infiere|desprende|evidencia|constata|aprecia|verifica)"
    r"|(?:es|resulta|queda)\s+(?:claro|evidente|patente|manifiesto|notorio|indudable|innegable|incuestionable|cierto)"
    r"|no\s+cabe\s+duda\s+de)\s+que"
)
_APERTURA = re.compile(
    rf"\s*(?P<conectivos>{_CONECTIVOS})(?:"
    rf"{_IMPERSONAL}"
    rf"|(?P<despacho>{_DATIVO_DEL_DESPACHO}\s+{_IMPERSONAL}"
    rf"|{_DESPACHO_SUJETO}(?:\s*,\s*(?:{_CONECTIVO}\s*,\s*)+|\s+)(?:{_DECIDE}|{_MODAL}"
    rf"|{_OPINA}\s+que{_SEP}{_CONECTIVOS_DEL_DESPACHO}(?:{_IMPERSONAL}|{_MODAL})))"
    rf"|{_QUE_IMPERSONAL}{_SEP}{_CONECTIVOS}{_IMPERSONAL}"
    rf"|(?P<modal_implicito>{_MODAL})"
    r")\b"
)
# Entre el disparador y el primer infinitivo: un conectivo («corresponde, en consecuencia, revocar») o el dativo del Despacho
# («corresponde al Despacho revocar»). «Corresponde a la EPS…» o «debe la entidad…» no llegan a ningún infinitivo.
_RELLENO_TRAS_DISPARADOR = re.compile(
    rf"\s*,\s*(?:(?:y\s+)?{_CONECTIVO}\s*,\s*)+"
    rf"|\s+(?:(?:al\s+despacho|a\s+(?:este\s+(?:despacho|juzgado)|esta\s+(?:sala|judicatura)|la\s+sala))\s+)?(?:{_CONECTIVO}\s+)*"
)
_INFINITIVO_DE_DECISION = re.compile(
    r"(?:confirmar|revocar|modificar|amparar|tutelar|conceder|negar|denegar|declarar|desestimar|reponer|adicionar|aclarar"
    r"|anular|rechazar|acceder|dejar\s+sin\s+efectos?)(?:l[aeo]s?)?\b"
)
# Enlace entre dos infinitivos de decisión: «, », «y », «, y », «y, en su lugar, », «, además, »…
_CONECTIVO_DE_ENLACE = (
    r"(?:en\s+su\s+lugar|adem[aá]s|tambi[eé]n|asimismo|igualmente|por\s+(?:tanto|consiguiente|ende|otra\s+parte)"
    r"|en\s+consecuencia|consecuentemente|finalmente|a\s+su\s+vez|de\s+otra\s+parte)"
)
_ENLACE = re.compile(
    rf"(?:\s*,\s*(?:(?:y|e)(?:\s*,\s*|\s+))?|\s+(?:y|e)(?:\s*,\s*|\s+))(?:{_CONECTIVO_DE_ENLACE}(?:\s*,\s*|\s+))*"
)
# «Confirmar o revocar», «negar o declarar improcedente»: una disyunción no anuncia ninguno de los dos y deja la cadena sin examinar.
_DISYUNCION = re.compile(r"(?:\s*,\s*|\s+)(?:o|u)(?:\s*,\s*|\s+)(?:bien(?:\s*,\s*|\s+))?")
_PALABRA_DEL_COMPLEMENTO = re.compile(r"\s+([a-zñáéíóúü0-9]+)")
# Palabras que, dentro del complemento, abren otra cláusula o traen a otro actor: relativos y subordinantes, negaciones, otros
# verbos (infinitivo, gerundio, futuro, condicional, pretérito, un modal o una cópula conjugados) y pronombres átonos.
_CORTA_LA_CADENA = re.compile(
    r"(?:que|cual(?:es)?|quien(?:es)?|cuy[oa]s?|donde|cuando|mientras|porque|pues|aunque|si|sino|dado|puesto|toda|como"
    r"|seg[uú]n|conforme|salvo|excepto|no|ni|tampoco|se|le|les"
    r"|[a-zñáéíóúü]{2,}(?:ando|iendo|yendo)"
    r"|[a-zñáéíóúü]{3,}(?:ar|er|ir)(?:se|l[aeo]s?|les?)?|dar|ser|ver|ir"
    r"|[a-zñáéíóúü]+(?:ar|er|ir)(?:á|án|ía|ían)"
    r"|[a-zñáéíóúü]{2,}(?:ó|aron|ieron|ió)"
    r"|deb(?:e|en|[ií]a|[ií]an)|pued(?:e|en)|tiene|tienen|ha|han|hay|corresponde|compete|incumbe|obliga|queda|quedan"
    r"|es|son|est[aá]n?|fue|fueron|sea|sean|[oó]rdenes|orden|ordena)"
)
# Sustantivos y adjetivos corrientes que acaban en -ar, -er o -ir y no son verbos: no cortan la cadena.
_NO_ES_INFINITIVO = frozenset(
    "lugar lugares titular particular familiar similar regular popular militar singular vulgar hogar azar ejemplar estándar "
    "mujer primer tercer cualquier carácter alquiler auxiliar peculiar escolar".split()
)
_MAX_CADENA = 600  # caracteres desde el disparador: una cadena más larga ya no es un anuncio de una línea
# Lo que, en el resto de la oración, atribuye lo dicho a otro: «…, según la EPS», «…, a juicio de la accionada», «…, como lo
# pide la EPS», «…, sostiene la entidad», «…, para la EPS.». Es amplio a propósito: si aparece, la oración no se examina.
_VERBO_DE_DECIR = (
    r"(?:afirm|aleg|plante|se[nñ]al|indic|manifest|solicit|reclam|consider|estim|argument|reiter|asegur|opin|observ|explic"
    r"|precis|agreg|invoc|deprec|impetr|cuestion|reproch|replic|contest|insin[uú])(?:a|an|[oó]|aron)"
    r"|concept[uú](?:a|an|[oó]|aron)"
    r"|sostienen?|sostuvo|sostuvieron|aducen?|adujo|adujeron|insisten?|insisti[oó]|insistieron|sugieren?|sugiri[oó]|sugirieron"
    r"|exponen?|expuso|expusieron|proponen?|propuso|propusieron|dicen?|dijo|dijeron|creen?|crey[oó]|creyeron|entienden?"
    r"|entendi[oó]|entendieron|advierten?|advirti[oó]|advirtieron|concluyen?|concluy[oó]|concluyeron|arguyen?|arguy[oó]"
    r"|arguyeron|defienden?|defendi[oó]|defendieron|piden?|pidi[oó]|pidieron|pretenden?|pretendi[oó]|pretendieron|refieren?"
    r"|refiri[oó]|refirieron|a[nñ]aden?|a[nñ]adi[oó]|a[nñ]adieron"
)
_ATRIBUCION = re.compile(
    r"\b(?:seg[uú]n|juicio|criterio|opini[oó]n|sentir|parecer|entender|concepto|decir|palabras|voces|perspectiva|[oó]ptica"
    r"|punto\s+de\s+vista|tesis|postura|posici[oó]n|planteamiento|versi[oó]n|alegatos?|argumentos?|razonamiento"
    r"|como\s+(?:lo|la|los|las)|tal\s+(?:y\s+)?como"
    rf"|{_VERBO_DE_DECIR})\b"
    r"|\bpara\s+(?:el|la|los|las|este|esta|su|sus)\s+(?!(?:cual|que)\b)[a-zñáéíóúü]+(?:\s+[a-zñáéíóúü.]+){0,2}\s*(?:[,;!?)]|\.|$)"
)
# Lo que, en el resto de la oración, vuelve el anuncio condicional o hipotético («corresponde negar el amparo si la EPS…»).
_CONDICION = re.compile(
    r"\b(?:si|salvo|excepto|a\s+menos\s+que|siempre\s+(?:que|y\s+cuando)|en\s+caso\s+(?:de|contrario)|en\s+(?:el\s+)?evento"
    r"|cuando|de\s+lo\s+contrario|de\s+no\s+ser\s+as[ií]|so\s+pena)\b"
)
# Lo que puede seguir a un anuncio de negar, de declarar improcedente o de declarar la carencia para que cuente como entero. Estas
# decisiones pueden ser una parte de otra (se ampara un derecho y se niega otro; es improcedente frente a una entidad y se
# ampara frente a otra) y las palabras que acotan la parte no tienen fin («respecto de», «en el suministro de», «del reembolso»,
# «con el medicamento», «como mecanismo transitorio»…): una lista de ellas dejaba pasar la que no traía. Por eso se hace al
# revés, con una forma cerrada: tras el anuncio solo puede venir el fin de la oración o una cola de la lista cerrada de abajo (que
# no acota nada) seguida del fin, y, tras el fin o la cola, un enlace con otro infinitivo («y ordenar a la EPS…»), un gerundio de
# orden («, ordenando a la EPS…») o la razón («, toda vez que…»), que ya no son parte del anuncio. Cualquier otra cosa (un
# complemento, un adjetivo, un relativo, un «y» con un sustantivo) deja el anuncio sin examinar.
_PARTE_ACTORA = r"(?:la|el)\s+(?:accionante|actor|actora|demandante|peticionari[oa]|parte\s+(?:accionante|actora|demandante))"
_COLA_QUE_NO_ACOTA = (
    r"(?:(?:solicitad|pedid|invocad|impetrad|reclamad|formulad)[ao]s?(?:\s+por\s+" + _PARTE_ACTORA + r")?"
    r"|por\s+" + _PARTE_ACTORA +
    r"|por\s+(?:las?\s+)?(?:razones|motivos)\s+(?:ya\s+)?(?:expuest|anotad|indicad|se[nñ]alad)[ao]s"
    r"(?:\s+en\s+(?:la\s+parte\s+(?:motiva|considerativa)|esta\s+(?:providencia|sentencia)|este\s+proveído|las\s+consideraciones))?"
    r"|(?:por|conforme\s+(?:a|con)|de\s+acuerdo\s+(?:a|con))\s+lo\s+(?:expuesto|anterior)"
    r"|en\s+(?:el\s+presente|este)\s+(?:caso|asunto)|en\s+esta\s+(?:instancia|oportunidad)"
    # los motivos de improcedencia de la acción entera
    r"|por\s+(?:(?:la\s+)?(?:falta|ausencia)\s+de\s+)?(?:subsidiariedad|inmediatez|temeridad|cosa\s+juzgada"
    r"|legitimaci[oó]n(?:\s+en\s+la\s+causa)?(?:\s+por\s+(?:activa|pasiva))?)"
    r"|por\s+no\s+(?:cumplir|superar|satisfacer)\s+el\s+requisito\s+de\s+(?:subsidiariedad|inmediatez))"
)
# `[a-z]*`: lo que falta de la palabra si el anuncio acaba en una raíz («sobrevinient|e»). «de tutela» cierra «la acción».
_COLA_PREVIA = re.compile(rf"[a-zñáéíóúü]*(?:\s+de\s+tutela)?(?:(?:\s*,)?\s+{_COLA_QUE_NO_ACOTA})?")
_PALABRA_COMO_INFINITIVO = re.compile(r"[a-zñáéíóúü]+(?:ar|er|ir)(?:l[aeo]s?|les?|se)?\b")
# «…, ordenando a la EPS…» (el prompt permite aludir a las órdenes) y «…, toda vez que no se acreditó…»: el anuncio acaba donde
# empieza lo que ordena o lo que lo motiva. Los demás nexos («por cuanto», «por lo que», «en tanto», «en cuanto a») pueden acotar
# («por cuanto respecta a…», «por lo que hace a…», «en tanto pretende el reembolso») y no están.
_CIERRE_DEL_ANUNCIO = re.compile(
    r"\s*,?\s+(?:ordenando|disponiendo|exhortando|requiriendo|instando|advirtiendo|previniendo|notificando|comunicando"
    r"|porque|pues|puesto\s+que|ya\s+que|toda\s+vez\s+que|dado\s+que)\b"
)


def _cola_entera(texto: str, pos: int, fin: int) -> bool:
    """¿Lo que va de `pos` al fin de la oración es el fin, o un enlace con otro infinitivo, tras una cola que no acota nada?"""
    previa = _COLA_PREVIA.match(texto, pos, fin)
    if previa is None:
        return False
    if not texto[previa.end() : fin].strip() or _CIERRE_DEL_ANUNCIO.match(texto, previa.end(), fin):
        return True
    enlace = _ENLACE.match(texto, previa.end(), fin)
    verbo = _PALABRA_COMO_INFINITIVO.match(texto, enlace.end(), fin) if enlace else None
    return verbo is not None and verbo.group() not in _NO_ES_INFINITIVO


_FORMULA = {
    "CONFIRMAR": "confirmar",
    "REVOCAR": "revocar",
    "MODIFICAR": "modificar",
    "AMPARAR": "amparar",
    "NEGAR": "negar",
    "IMPROCEDENTE": "declarar improcedente",
    "CARENCIA_HECHO_SUPERADO": "declarar la carencia actual de objeto por hecho superado",
    "CARENCIA_DANO_CONSUMADO": "declarar la carencia actual de objeto por daño consumado",
    "CARENCIA_SOBREVINIENTE": "declarar la carencia actual de objeto por situación sobreviniente",
}
_PISTA_NEGACION_PARCIAL = (
    " Si solo niega una pretensión accesoria, nómbrela (por ejemplo, «negar el tratamiento integral») o diga «las demás pretensiones»."
)


def _oraciones(texto: str) -> list[tuple[int, int, bool]]:
    """(inicio, fin, abre) de cada tramo entre fines de oración; `abre` es falso si el tramo sigue a un «;» (es otra cláusula
    de la misma oración)."""
    tramos, inicio, abre = [], 0, True
    for f in _FIN_DE_ORACION.finditer(texto):
        tramos.append((inicio, f.start(), abre))
        inicio, abre = f.end(), f.group() != ";"
    tramos.append((inicio, len(texto), abre))
    return tramos


def _cadena_de_decision(texto: str, inicio: int, fin: int) -> list[int]:
    """Dónde empieza cada infinitivo de decisión de la cadena que arranca en `inicio`: el primero va justo ahí y cada uno de
    los siguientes va tras un enlace; entre ellos, solo palabras del complemento que no abren otra cláusula."""
    posiciones: list[int] = []
    verbo = _INFINITIVO_DE_DECISION.match(texto, inicio, fin)
    while verbo:
        posiciones.append(verbo.start())
        pos, verbo = verbo.end(), None
        while pos < fin:
            o = _DISYUNCION.match(texto, pos, fin)
            if o and _INFINITIVO_DE_DECISION.match(texto, o.end(), fin):
                return []
            enlace = _ENLACE.match(texto, pos, fin)
            if enlace and (verbo := _INFINITIVO_DE_DECISION.match(texto, enlace.end(), fin)):
                break
            palabra = _PALABRA_DEL_COMPLEMENTO.match(texto, pos, fin)
            if palabra is None:
                break
            p = palabra.group(1)
            # Un infinitivo de decisión sin enlace delante («la decisión de negar») es complemento de otra cosa.
            if _INFINITIVO_DE_DECISION.fullmatch(p) or (
                _CORTA_LA_CADENA.fullmatch(p) and p not in _NO_ES_INFINITIVO and not p.endswith("ular")
            ):
                break
            pos = palabra.end()
    return posiciones


def _infinitivos_anunciados(texto: str) -> list[tuple[int, int]]:
    """(inicio, fin de su oración) de cada infinitivo de decisión que anuncia el Despacho (ver el comentario de
    `_APERTURA`). Cada tramo se mira una vez y la cadena tiene un tope, así que el coste es lineal en el largo del texto."""
    anunciados: list[tuple[int, int]] = []
    # `limpia`: todo lo anterior de la oración (las cláusulas antes de un «;») es del Despacho y no atribuye nada a nadie.
    # `ajena_antes`: alguna oración anterior atribuye algo a otro («La EPS sostiene que no hay vulneración.»).
    limpia, ajena_antes, previa = True, False, (0, 0)
    for inicio, fin, abre in _oraciones(texto):
        if abre:
            ajena_antes = ajena_antes or bool(_ATRIBUCION.search(texto, *previa))
            limpia, previa = True, (inicio, fin)
        else:
            previa = (previa[0], fin)
        apertura = _APERTURA.match(texto, inicio, fin) if limpia else None
        if (
            apertura is None
            or "?" in texto[fin : fin + 1]
            or "¿" in texto[inicio:fin]
            or _ATRIBUCION.search(texto, apertura.end(), fin)
            or _CONDICION.search(texto, apertura.end(), fin)
        ):
            limpia = False
            continue
        # Después de atribuir algo a otro, un impersonal o un «deber» sin sujeto podrían seguir siendo lo que dice ese otro («La
        # EPS sostiene que no hay vulneración. Además, el servicio es estético. Por tanto, procede confirmar el fallo.»): solo
        # cuenta el anuncio que nombra al Despacho.
        if ajena_antes and not apertura.group("despacho"):
            continue
        # «Deber» sin sujeto: el sujeto implícito es el Despacho solo al empezar la conclusión o tras un conectivo de conclusión
        # («Por lo expuesto, debe…»); tras otra oración («La EPS incumplió. Debe…») podría ser el de esa oración.
        if apertura.group("modal_implicito") and not apertura.group("conectivos") and texto[:inicio].strip():
            continue
        relleno = _RELLENO_TRAS_DISPARADOR.match(texto, apertura.end(), fin)
        if relleno is not None:
            cadena = _cadena_de_decision(texto, relleno.end(), min(fin, apertura.end() + _MAX_CADENA))
            anunciados += [(p, fin) for p in cadena]
    return anunciados


# «Confirmar» y «revocar» solo son el resultado si recaen sobre una decisión judicial o no llevan objeto («corresponde
# revocar y amparar…»). «Confirmar la cita» o «revocar la glosa» son actos de otro; si el objeto no se reconoce, o es un
# clítico sin antecedente a la vista («corresponde confirmarla»), no se examina.
# Reconocer el objeto es también una forma cerrada: el sustantivo («fallo», «sentencia», «decisión»…) y, justo después, el fin de
# la oración, una coma o un «y», o uno de los complementos de la lista que lo hacen del a quo o del Despacho («de primera
# instancia», «del a quo», «proferida por el Juzgado…», «impugnada», «en su integridad»). Cualquier otra cosa tras el sustantivo
# («la decisión médica de operar», «la decisión anterior de la EPS», «la decisión que ordenó la cirugía») deja la oración sin
# examinar: «decisión» o «auto» pueden ser de otro, y la lista de lo que no es del Despacho no se acababa.
_INSTANCIA_JUDICIAL = (
    r"(?:(?:primera|segunda|[uú]nica|instancia|a\s+quo|sala|juzgado|despacho|corte|tribunal|juez|jueza|tutela|amparo"
    r"|(?:este|esta|dicho|dicha)\s+(?:despacho|juzgado|sala|corte|tribunal|instancia|judicatura))\b)"
)
_ORDINAL = (
    r"(?:primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[eé]ptim[oa]|octav[oa]|noven[oa]|d[eé]cim[oa]|[uú]nic[oa]|\d+)"
)
_COMPLEMENTO_JUDICIAL = (
    rf"(?:{_ORDINAL}|(?:de|del)\s+(?:(?:la|el)\s+)?{_INSTANCIA_JUDICIAL}"
    rf"|(?:adoptad|emitid|expedid|tomad|dictad|proferid)[ao]s?\s+por\s+(?:(?:la|el)\s+)?{_INSTANCIA_JUDICIAL}"
    r"|impugnad[ao]s?|apelad[ao]s?|recurrid[ao]s?|parcialmente|totalmente|[ií]ntegramente|integralmente"
    r"|en\s+(?:su\s+)?(?:integridad|totalidad)|en\s+lo\s+(?:dem[aá]s|restante)|por\s+(?:las?\s+)?(?:razones|motivos))\b"
)
_OBJETO_JUDICIAL = re.compile(
    r"\s*(?:$|[,.;:!?)»\"]|(?:y|e|parcialmente|totalmente|[ií]ntegramente|integralmente|solo|s[oó]lo|[uú]nicamente)\b"
    r"|en\s+(?:su\s+)?(?:integridad|totalidad)\b|en\s+lo\s+(?:dem[aá]s|restante)\b|por\s+(?:las?\s+)?(?:razones|motivos)\b"
    r"|(?:(?:el|la|los|las|lo|su|sus|dich[ao]s?|est[ae]|es[ae]|tal)\s+)*"
    r"(?:fallo|sentencia|decisi[oó]n|providencia|auto|determinaci[oó]n|proveído|pronunciamiento|numeral|numerales"
    r"|ordinal|ordinales|par[aá]grafo|literal|decidido|resuelto|dispuesto|impugnad[ao]s?|apelad[ao]s?|recurrid[ao]s?"
    r"|primera|segunda|instancia|a\s+quo|tutela|amparo|mism[ao]|restantes|dem[aá]s)\b"
    rf"(?=\s*(?:$|[,.;:!?)»\"]|(?:y|e)\b)|\s+{_COMPLEMENTO_JUDICIAL}))"
)
# En infinitivo, negar o declarar improcedente solo cuentan si lo que sigue, directamente, es el amparo mismo: su núcleo
# («el amparo», «la tutela», «la acción», «la protección», con hasta tres palabras sueltas antes), «las pretensiones de la acción»
# o «lo solicitado». No basta con que no sea una pretensión accesoria reconocible, como en futuro: «negar, en cambio, el
# tratamiento integral», «negar las pretensiones adicionales» o «negar la solicitud o la pretensión relativa al transporte» son
# negaciones parciales que pueden convivir con el amparo. Lo que sigue al objeto lo decide `_cola_entera`.
_EL_AMPARO_MISMO = re.compile(
    rf"\s+{_DETERMINANTE}{_RELLENO}(?:(?:amparos?|tutelas?|protecci(?:[oó]n|ones)|acci(?:[oó]n|ones))\b"
    rf"|{_PRETENSION_GENERICA}\s+(?:de|del)\s+{_AMPARO_COMO_OBJETO}\b"
    r"|lo\s+(?:solicitado|pedido|pretendido|impetrado|reclamado|demandado)\b)"
)
_CLITICO_FINAL = re.compile(r"ar(?:l[aeo]s?)$")
_VERBO_DE_COMPROBACION = re.compile(r"\s*,?\s*(?:adem[aá]s\s*,?\s*)?que\b")


def _infinitivo_cuenta(texto: str, m: re.Match[str], fin: int, otro: str) -> bool:
    # «Confirmar que la EPS cumpla…» comprueba un hecho; no confirma ni revoca nada.
    if _VERBO_DE_COMPROBACION.match(texto, m.end()):
        return False
    if otro in ("CONFIRMAR", "REVOCAR"):
        return not _CLITICO_FINAL.search(m.group()) and _OBJETO_JUDICIAL.match(texto, m.end()) is not None
    if otro == "AMPARAR":
        return True
    # Negar, declarar improcedente o declarar la carencia pueden ser una parte de otra decisión (se ampara un derecho y se niega
    # otro; se niega frente a una entidad y es improcedente frente a otra). Solo cuentan si son enteros, y eso se reconoce por
    # una forma cerrada, no por las palabras que acotan (`_cola_entera`): el objeto es el amparo mismo (`_EL_AMPARO_MISMO`; no
    # «negar el tratamiento integral» ni «declarar improcedente la solicitud de reembolso») y, tras él (y tras el tipo de la
    # carencia), solo viene el fin de la oración, un enlace con otro infinitivo o una cola que no acota nada. Amparar, en
    # cambio, contradice cualquier otra sustitutiva aunque sea en parte.
    if otro in ("NEGAR", "IMPROCEDENTE"):
        if otro == "IMPROCEDENTE" and "acci" in m.group():  # «declarar la acción (de tutela) improcedente»: el objeto va antes
            return _cola_entera(texto, m.end(), fin)
        objeto = _EL_AMPARO_MISMO.match(texto, m.end())
        return objeto is not None and _cola_entera(texto, objeto.end(), fin)
    return _cola_entera(texto, m.end(), fin)


def _cuenta_como_contradiccion(texto: str, m: re.Match[str], otro: str, decidido: str, decision: Decision) -> bool:
    if _excusada(texto, m.start()):
        return False
    return not (otro == "NEGAR" and decidido == "AMPARAR" and _negacion_parcial(texto, m, decision))


def _contradicciones(conclusion: str, decision: Decision) -> list[str]:
    texto = " ".join(conclusion.lower().split())
    anunciados = _infinitivos_anunciados(texto)
    # Un derecho marcado «Niega» ya declara un amparo parcial: negar algo no contradice AMPARAR.
    niega_un_derecho = decision.sustitutiva == "AMPARAR" and any(d.disposicion == "NIEGA" for d in decision.derechos)
    msgs: list[str] = []
    familias = (
        ("el resultado", decision.resultado, _FUTURO_RESULTADO, _INFINITIVO_RESULTADO),
        ("la decisión sustitutiva", decision.sustitutiva, _FUTURO_SUSTITUTIVA, _INFINITIVO_SUSTITUTIVA),
    )
    for nombre, decidido, futuros, infinitivos in familias:
        # MODIFICAR confirma una parte y cambia otra: «en lo demás lo confirmará» o «revocará el numeral…» no contradicen.
        if not decidido or decidido == "MODIFICAR":
            continue
        for otro, futuro in futuros.items():
            if otro == decidido or (otro == "NEGAR" and niega_un_derecho):
                continue
            en_futuro = re.finditer(_NO_PRECEDE + futuro, texto)
            en_infinitivo = (
                m for p, fin in anunciados if (m := infinitivos[otro].match(texto, p)) and _infinitivo_cuenta(texto, m, fin, otro)
            )
            if any(_cuenta_como_contradiccion(texto, m, otro, decidido, decision) for m in chain(en_futuro, en_infinitivo)):
                pista = _PISTA_NEGACION_PARCIAL if (otro, decidido) == ("NEGAR", "AMPARAR") else ""
                msgs.append(
                    f"{BLOQUEA}La conclusión anuncia {otro} como {nombre}, pero el juez decidió {decidido}; "
                    f"anuncie solo lo decidido («{_FORMULA[decidido]}») y, si menciona lo que resolvió el a quo, "
                    f"escríbalo en pasado.{pista}"
                )
    return msgs


def coherencia_decision(caso: CasoConcretoLLM, decision: Decision) -> list[str]:
    if decision.accion != "decidir":
        return []
    norm = normalizar_texto(caso.conclusion, False)
    msgs: list[str] = _contradicciones(caso.conclusion, decision)
    if decision.resultado:
        raices = _RESULTADO[decision.resultado]
        if not any(_contiene_raiz(norm, r) for r in raices):
            msgs.append(
                f"{BLOQUEA}La conclusión no anuncia el resultado decidido ({decision.resultado}); "
                f"debe contener una expresión como «{raices[0]}…»."
            )
    if decision.sustitutiva:
        raices = _SUSTITUTIVA[decision.sustitutiva]
        if not any(_contiene_raiz(norm, r) for r in raices):
            esperadas = ", ".join(f"«{e}»" for r in raices for e in _ETIQUETA_RAIZ.get(r, [r.partition("(")[0] + "…"]))
            msgs.append(
                f"{BLOQUEA}La conclusión no anuncia la decisión sustitutiva ({decision.sustitutiva}); "
                f"debe contener alguna de estas expresiones: {esperadas}."
            )
    return msgs


def cobertura_reparos(
    parrafos_reparo_ids: Iterable[str | Iterable[str]],
    reparos: Iterable[Reparo | str],
    decision: Decision | None = None,
) -> list[str]:
    tratados: set[str] = set()
    for item in parrafos_reparo_ids:
        tratados.update([item] if isinstance(item, str) else item)
    absorbidos = {d.reparo_id for d in decision.por_reparo if d.disposicion == "ABSORBIDO"} if decision else set()
    msgs: list[str] = []
    for r in reparos:
        id_ = r if isinstance(r, str) else r.id
        if id_ not in tratados and id_ not in absorbidos:
            msgs.append(f"{ALERTA}El reparo {id_} no se trata en ningún párrafo ni bloque.")
    return msgs


def extension(texto: str, rango: list[int] | tuple[int, int], campo: str) -> list[str]:
    n = contar_palabras(texto)
    minimo, maximo = rango
    if n < minimo:
        return [f"{ALERTA}{campo}: tiene {n} palabras, por debajo del mínimo esperado ({minimo} a {maximo})."]
    if n > maximo:
        return [f"{ALERTA}{campo}: tiene {n} palabras, por encima del máximo esperado ({minimo} a {maximo})."]
    return []


def _ngramas(texto: str) -> set[tuple[str, ...]]:
    palabras = normalizar_texto(texto, False).split()
    return {tuple(palabras[k : k + NGRAMA_CONTENCION]) for k in range(len(palabras) - NGRAMA_CONTENCION + 1)}


def _pares_similares(
    textos: list[str], umbral: float, contencion: float | None
) -> list[tuple[int, int, float, float | None]]:
    palabras = [set(normalizar_texto(t, False).split()) for t in textos]
    ngramas = [_ngramas(t) for t in textos] if contencion is not None else []
    pares = []
    for i, j in combinations(range(len(textos)), 2):
        a, b = palabras[i], palabras[j]
        if len(a) < MIN_PALABRAS_DUPLICADO or len(b) < MIN_PALABRAS_DUPLICADO:
            continue
        jaccard = len(a & b) / len(a | b)
        cont = None
        if contencion is not None and min(len(ngramas[i]), len(ngramas[j])) >= MIN_NGRAMAS_CONTENCION:
            cont = len(ngramas[i] & ngramas[j]) / min(len(ngramas[i]), len(ngramas[j]))
        if jaccard >= umbral or (cont is not None and cont >= contencion):
            pares.append((i, j, jaccard, cont))
    return pares


def _similitud(jaccard: float, cont: float | None) -> str:
    return f"similitud {jaccard:.0%}" + ("" if cont is None else f", contención {cont:.0%}")


def duplicados(
    parrafos: list[str], umbral: float, contencion: float | None = None, etiquetas: list[str] | None = None
) -> list[str]:
    msgs: list[str] = []
    for i, j, jaccard, cont in _pares_similares(parrafos, umbral, contencion):
        similitud = _similitud(jaccard, cont)
        if etiquetas:
            msgs.append(f"{ALERTA}{etiquetas[i].capitalize()} y {etiquetas[j]} son casi idénticos ({similitud}).")
        else:
            msgs.append(f"{ALERTA}Los párrafos {i + 1} y {j + 1} son casi idénticos ({similitud}).")
    return msgs


def duplicados_caso(caso: CasoConcretoLLM, umbral: float, contencion: float = UMBRAL_CONTENCION) -> list[str]:
    etiquetas = ["el problema jurídico", *(f"el párrafo {i}" for i in range(1, len(caso.parrafos) + 1)), "la conclusión"]
    textos = [caso.problema_juridico, *(p.texto for p in caso.parrafos), caso.conclusion]
    ultimo, conclusion = len(textos) - 2, len(textos) - 1
    msgs: list[str] = []
    for i, j, jaccard, cont in _pares_similares(textos, umbral, contencion):
        similitud = _similitud(jaccard, cont)
        if j == conclusion and i == ultimo and caso.parrafos:
            msgs.append(
                f"{BLOQUEA}La conclusión repite el último párrafo (párrafo {i}; {similitud}). La conclusión va solo en el "
                f"campo conclusion: quite del párrafo {i} lo que ya dice la conclusión y no la reitere en ningún párrafo."
            )
        else:
            msgs.append(f"{ALERTA}En el caso concreto, {etiquetas[i]} y {etiquetas[j]} son casi idénticos ({similitud}).")
    return msgs


def residuos(texto: str) -> list[str]:
    msgs: list[str] = []
    n = 0
    for linea in texto.splitlines():
        p = _MARCADOR_CUALQUIERA.sub(" ", linea).strip()
        if not p:
            continue
        n += 1
        inicio = f"«{p[:60]}»"
        if p.startswith("[") or re.match(r"TODO\b|(?i:borrador)\b", p):
            msgs.append(f"{ALERTA}Posible residuo de borrador al inicio del párrafo {n}: {inicio}.")
            continue
        m = _INFINITIVO.match(p)
        if m and m.group(1).lower() not in _NO_INFINITIVOS and len(p.split()) < MAX_PALABRAS_RESIDUO:
            msgs.append(f"{ALERTA}El párrafo {n} es corto y empieza con un infinitivo, como una instrucción sin redactar: {inicio}.")
    return msgs
