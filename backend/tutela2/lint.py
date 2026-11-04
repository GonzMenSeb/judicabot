from __future__ import annotations

import re
from datetime import date
from itertools import combinations
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
_ETIQUETA_RAIZ = {r"conced\w*\s+(?:la\s+)?(?:tutela|proteccion)": "conceder la tutela/protección"}
_SUSTITUTIVA = {
    "AMPARAR": ["ampar", r"tutel(?!as?\b)", r"conced\w*\s+(?:la\s+)?(?:tutela|proteccion)"],
    "NEGAR": [r"neg(?:ar|ara|aria|o|ando|aron)\b", "nieg", "deneg"],
    "IMPROCEDENTE": ["improceden"],
    "CARENCIA_HECHO_SUPERADO": ["carencia", "hecho superado"],
    "CARENCIA_DANO_CONSUMADO": ["carencia", "daño consumado"],
    "CARENCIA_SOBREVINIENTE": ["carencia", "sobrevinient"],
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
_CONCESION_FUTURA = re.compile(
    r"\b(?:ampar|tutel)(?:ar[aá]n?|ar[ií]an?)\b|\bconceder[aá]n?\s+(?:la\s+|el\s+)?(?:tutela|protecci[oó]n|amparo)\b"
)


def _negacion_parcial(texto: str, m: re.Match[str]) -> bool:
    if not any(
        not _excusada(texto, g.start()) and not _SI_POSTERIOR.match(texto, g.end())
        for g in _CONCESION_FUTURA.finditer(texto)
    ):
        return False
    ini = max(texto.rfind(c, 0, m.start()) for c in ".;!?") + 1
    fins = [k for k in (texto.find(c, m.end()) for c in ".;!?") if k != -1]
    fin = min(fins) if fins else len(texto)
    return bool(_MARCA_PARCIAL.search(texto[max(ini, m.start() - 80) : min(fin, m.end() + 80)]))


def _excusada(texto: str, inicio: int) -> bool:
    previo = texto[:inicio]
    return bool(
        _NEGADOR_PREVIO.search(previo[-40:])
        or _HIPOTETICO_PREVIO.search(previo)
        or _CONDICIONAL_PREVIO.search(previo)
        or _CONDICIONAL_EXCEPTO.search(previo)
    )


_CARENCIA = r"declarar(?:á|án|ía|ían)\s+la\s+carencia[^.;]{0,60}?"
_FUTURO_RESULTADO = {
    "CONFIRMAR": r"confirmar(?:á|án|ía|ían)\b",
    "REVOCAR": r"revocar(?:á|án|ía|ían)\b",
}
_FUTURO_SUSTITUTIVA = {
    "AMPARAR": r"(?:(?:ampar|tutel)ar(?:á|án|ía|ían)\b|conceder(?:á|án)\s+(?:la\s+|el\s+)?(?:tutela|protecci[oó]n|amparo))",
    "NEGAR": r"(?:neg|deneg)ar(?:á|án|ía|ían)\b",
    "IMPROCEDENTE": r"declarar(?:á|án|ía|ían)\s+(?:la\s+)?(?:acci[oó]n\s+(?:de\s+tutela\s+)?)?improcedente",
    "CARENCIA_HECHO_SUPERADO": _CARENCIA + r"hecho\s+superado",
    "CARENCIA_DANO_CONSUMADO": _CARENCIA + r"da[ñn]o\s+consumado",
    "CARENCIA_SOBREVINIENTE": _CARENCIA + r"sobrevinient",
}


def _contradicciones(conclusion: str, decision: Decision) -> list[str]:
    texto = " ".join(conclusion.lower().split())
    msgs: list[str] = []
    familias = (
        ("el resultado", decision.resultado, _FUTURO_RESULTADO),
        ("la decisión sustitutiva", decision.sustitutiva, _FUTURO_SUSTITUTIVA),
    )
    for nombre, decidido, patrones in familias:
        if not decidido:
            continue
        for otro, patron in patrones.items():
            if otro != decidido and any(
                not _excusada(texto, m.start()) and not (otro == "NEGAR" and decidido == "AMPARAR" and _negacion_parcial(texto, m))
                for m in re.finditer(_NO_PRECEDE + patron, texto)
            ):
                msgs.append(
                    f"{BLOQUEA}La conclusión anuncia {otro} como {nombre}, pero el juez decidió {decidido}; "
                    "lo que hizo el a quo se menciona en pasado."
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
            esperadas = ", ".join(f"«{_ETIQUETA_RAIZ.get(r, r.partition('(')[0])}…»" for r in raices)
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
