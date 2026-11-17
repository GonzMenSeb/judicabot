from __future__ import annotations

import copy
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Mapping

from tutela2 import fusion, lint
from tutela2.models import Ingesta

ARCHIVO = "ediciones.json"
LOG = "ediciones.jsonl"
VERSION = 1

log = logging.getLogger("tutela2.ediciones")

_SEPARADOR = re.compile(r"\n\s*\n")
_CITA = re.compile(r"\[\[CITA:\s*([^\]\s]+)\s*\]\]")
_IMAGEN = re.compile(r"\[\[IMAGEN([^\]]*)\]\]")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_ES = r"[^\S\n]"  # espacio que no es salto de línea: una ficha nunca cruza una línea en blanco (el límite entre párrafos)
_FICHA = re.compile(
    rf"⟦(?:cita{_ES}+([^\s⟦⟧]+)(?:{_ES}+·{_ES}*([^⟦⟧\n]*?))?|imagen(?:{_ES}*·{_ES}*([^⟦⟧\n]*?))?){_ES}*⟧"
)
_SUELTO = re.compile(r"\[\[|\]\]|⟦|⟧")
_FIJAS = {
    "apertura.antecedentes_hechos": "antecedentes",
    "apertura.sentencia_impugnada": "sentencia_impugnada",
    "apertura.impugnacion": "impugnacion",
    "consideraciones.procedibilidad": "consideraciones",
}
_CONTESTACION = re.compile(r"apertura\.contestaciones\.(0|[1-9][0-9]*)\.texto")
_BLOQUE = re.compile(r"consideraciones\.bloques\.(0|[1-9][0-9]*)\.(titulo|texto)")


def parrafos(texto: str | None) -> list[str]:
    """Partición de una pieza en párrafos, idéntica a la de render._prosa.

    Corta en líneas en blanco, colapsa los espacios internos (los saltos de línea simples pasan a ser un espacio)
    y descarta los párrafos vacíos. render._prosa recorre exactamente esta lista, así que el índice de un párrafo
    aquí es el `parrafo` de la `fuente` de sus bloques en la vista.
    """
    if not texto or not texto.strip():
        return []
    return [p for p in (" ".join(b.split()) for b in _SEPARADOR.split(texto.strip())) if p]


class ErrorEdicion(Exception):
    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


def normalizar(texto: str | None) -> str:
    return "\n\n".join(parrafos(texto))


def es_pieza(pieza: str) -> bool:
    return pieza in _FIJAS or bool(_CONTESTACION.fullmatch(pieza) or _BLOQUE.fullmatch(pieza))


def es_titulo(pieza: str) -> bool:
    return bool(_BLOQUE.fullmatch(pieza)) and pieza.endswith(".titulo")


def seccion_de(pieza: str) -> str:
    if pieza in _FIJAS:
        return _FIJAS[pieza]
    if _CONTESTACION.fullmatch(pieza):
        return "antecedentes"
    if _BLOQUE.fullmatch(pieza):
        return "consideraciones"
    raise ValueError(f"pieza desconocida: {pieza}")


def _partes(pieza: str, texto: str | None) -> list[str]:
    if es_titulo(pieza):
        linea = " ".join((texto or "").split())
        return [linea] if linea else []
    return parrafos(texto)


def _titulo(texto: Any) -> str | None:
    """Título de bloque en la forma con que se ancla: canónico y en una sola línea."""
    if not isinstance(texto, str):
        return None
    linea = " ".join(a_canonico(texto).split())
    return linea or None


def _seccion(valores: Mapping[str, Any], nombre: str) -> dict | None:
    seccion = valores.get(nombre)
    if hasattr(seccion, "model_dump"):
        seccion = seccion.model_dump()
    return seccion if isinstance(seccion, dict) else None


def _item(valores: Mapping[str, Any], nombre: str, lista: str, i: int) -> dict:
    elementos = (_seccion(valores, nombre) or {}).get(lista)
    if isinstance(elementos, list) and i < len(elementos) and isinstance(elementos[i], dict):
        return elementos[i]
    return {}


def _ubicar(seccion: dict, pieza: str) -> tuple[dict, str] | None:
    if pieza in _FIJAS:
        return seccion, pieza.split(".")[1]
    if m := _CONTESTACION.fullmatch(pieza):
        lista, i, campo = seccion.get("contestaciones"), int(m[1]), "texto"
    elif m := _BLOQUE.fullmatch(pieza):
        lista, i, campo = seccion.get("bloques"), int(m[1]), m[2]
    else:
        return None
    if isinstance(lista, list) and i < len(lista) and isinstance(lista[i], dict):
        return lista[i], campo
    return None


def obtener(valores: Mapping[str, Any], pieza: str) -> str | None:
    if not es_pieza(pieza):
        return None
    seccion = _seccion(valores, pieza.split(".")[0])
    sitio = _ubicar(seccion, pieza) if seccion is not None else None
    if sitio is None:
        return None
    valor = sitio[0].get(sitio[1])
    return valor if isinstance(valor, str) else None


def fijar(valores: Mapping[str, Any], pieza: str, texto: str) -> dict:
    nombre = pieza.split(".")[0]
    seccion = copy.deepcopy(_seccion(valores, nombre))
    sitio = _ubicar(seccion, pieza) if seccion is not None else None
    if sitio is None:
        raise ErrorEdicion(404, f"No existe la pieza {pieza}.")
    sitio[0][sitio[1]] = texto
    return seccion


def catalogo(valores: Mapping[str, Any]) -> list[str]:
    contestaciones = (_seccion(valores, "apertura") or {}).get("contestaciones")
    bloques = (_seccion(valores, "consideraciones") or {}).get("bloques")
    piezas = [
        "apertura.antecedentes_hechos",
        *(f"apertura.contestaciones.{i}.texto" for i in range(len(contestaciones) if isinstance(contestaciones, list) else 0)),
        "apertura.sentencia_impugnada",
        "apertura.impugnacion",
        "consideraciones.procedibilidad",
        *(
            f"consideraciones.bloques.{i}.{campo}"
            for i in range(len(bloques) if isinstance(bloques, list) else 0)
            for campo in ("titulo", "texto")
        ),
    ]
    return [p for p in piezas if obtener(valores, p) is not None]


def etiqueta(pieza: str, valores: Mapping[str, Any], ancla: str | None = None, huerfana: bool = False) -> str:
    if pieza == "apertura.antecedentes_hechos":
        return "Antecedentes: hechos"
    if pieza == "apertura.sentencia_impugnada":
        return "La sentencia impugnada"
    if pieza == "apertura.impugnacion":
        return "La impugnación"
    if pieza == "consideraciones.procedibilidad":
        return "Consideraciones: procedibilidad"
    if m := _CONTESTACION.fullmatch(pieza):
        entidad = ancla or _item(valores, "apertura", "contestaciones", int(m[1])).get("entidad")
        return f"Antecedentes: contestación de {entidad}" if entidad else f"Antecedentes: contestación {int(m[1]) + 1}"
    if m := _BLOQUE.fullmatch(pieza):
        n = int(m[1]) + 1
        if huerfana and ancla:
            # Su índice ya no dice nada (el bloque se fue o la clave se movió): se nombra por el título al que estaba anclada.
            return f"Consideraciones: título del bloque «{ancla}»" if m[2] == "titulo" else f"Consideraciones: bloque «{ancla}»"
        if m[2] == "titulo":
            return f"Consideraciones: título del bloque {n}"
        titulo = " ".join(str(_item(valores, "consideraciones", "bloques", int(m[1])).get("titulo") or "").split())
        return f"Consideraciones: bloque {n} ({titulo})" if titulo else f"Consideraciones: bloque {n}"
    return pieza


def _ancla(valores: Mapping[str, Any], pieza: str) -> str | None:
    """Lo que identifica a la pieza aunque cambie de índice: la entidad de una contestación o el título (de la IA) de un bloque."""
    if m := _CONTESTACION.fullmatch(pieza):
        return _item(valores, "apertura", "contestaciones", int(m[1])).get("entidad")
    if m := _BLOQUE.fullmatch(pieza):
        return _titulo(_item(valores, "consideraciones", "bloques", int(m[1])).get("titulo"))
    return None


def mapa_citas(valores: Mapping[str, Any]) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for cita in valores.get("citas") or []:
        datos = cita.model_dump() if hasattr(cita, "model_dump") else cita
        if isinstance(datos, dict) and datos.get("id"):
            mapa[str(datos["id"])] = str(datos.get("sentencia_original") or "")
    return mapa


def _limpio(texto: str) -> str:
    return " ".join(texto.replace("⟦", " ").replace("⟧", " ").split())


def a_editable(texto: str, citas: Mapping[str, str]) -> str:
    def cita(m: re.Match[str]) -> str:
        sentencia = _limpio(citas.get(m[1]) or "")
        return f"⟦cita {m[1]} · {sentencia}⟧" if sentencia else f"⟦cita {m[1]}⟧"

    def imagen(m: re.Match[str]) -> str:
        desc = _limpio(m[1])
        return f"⟦imagen · {desc}⟧" if desc else "⟦imagen⟧"

    return _IMAGEN.sub(imagen, _CITA.sub(cita, texto))


def _editable(pieza: str, canonico: str | None, citas: Mapping[str, str]) -> str:
    """Forma editable y normalizada de una pieza.

    Primero se parte el texto canónico (la partición de render._prosa) y después se convierte cada párrafo, así
    una marca rota por una línea en blanco no se une en una ficha y los párrafos editables siguen siendo los de la vista.
    """
    return "\n\n".join(a_editable(p, citas) for p in _partes(pieza, canonico))


def a_canonico(texto: str) -> str:
    def marca(m: re.Match[str]) -> str:
        if m[1] is not None:
            return f"[[CITA:{m[1]}]]"
        desc = (m[3] or "").strip()
        return f"[[IMAGEN {desc}]]" if desc else "[[IMAGEN]]"

    return _FICHA.sub(marca, texto)


def _clave(m: re.Match[str]) -> tuple:
    return ("cita", m[1], m[2] or "") if m[1] is not None else ("imagen", m[3] or "")


def fichas(texto: str) -> Counter:
    return Counter(_clave(m) for m in _FICHA.finditer(texto))


def _tecleadas(texto: str) -> Counter:
    """Marcas [[CITA:id]] e [[IMAGEN desc]] completas que render reconocería en `texto` y que no salen de una ficha."""
    marcas: Counter = Counter()
    for p in parrafos(a_canonico(texto)):
        marcas.update(("cita", i) for i in _CITA.findall(p))
        marcas.update(("imagen", d.strip()) for d in _IMAGEN.findall(p))
    return marcas - Counter((f[0], f[1]) for f in fichas(texto).elements())


def _ficha_texto(ficha: tuple) -> str:
    if ficha[0] == "cita":
        return f"⟦cita {ficha[1]} · {ficha[2]}⟧" if ficha[2] else f"⟦cita {ficha[1]}⟧"
    return f"⟦imagen · {ficha[1]}⟧" if ficha[1] else "⟦imagen⟧"


def _fichas_de(trozo: list[str]) -> Counter:
    return fichas("\n\n".join(trozo))


def _oraciones_sin_cita(canonico: str) -> int:
    return sum(len(lint.jurisprudencia_sin_cita(p, "")) for p in parrafos(canonico))


def validar(pieza: str, nuevo: str, referencia: str, crudo: str) -> list[str]:
    if not parrafos(nuevo):
        return ["La pieza no puede quedar vacía."]
    errores: list[str] = []
    if _CONTROL.search(nuevo):
        errores.append("El texto tiene caracteres de control que el documento Word no admite; bórrelos.")
    if es_titulo(pieza) and (re.search(r"[\r\n]", crudo) or "\n" in nuevo):
        errores.append("Un título ocupa una sola línea: no use saltos de línea.")
    # Solo cuenta lo nuevo respecto de la referencia: un resto mal formado que ya traía el texto de la IA no bloquea la pieza.
    nuevos = Counter(_SUELTO.findall(_FICHA.sub(" ", nuevo))) - Counter(_SUELTO.findall(_FICHA.sub(" ", referencia)))
    if nuevos["[["] or nuevos["]]"] or _tecleadas(nuevo) - _tecleadas(referencia):
        errores.append("No escriba [[ ni ]]: las citas y las imágenes solo existen como fichas ⟦…⟧ y no se pueden agregar.")
    if nuevos["⟦"] or nuevos["⟧"]:
        errores.append("Hay un ⟦ o un ⟧ suelto, o una ficha ⟦…⟧ alterada que no se puede leer; las fichas deben quedar tal como estaban.")
    antes, ahora = fichas(referencia), fichas(nuevo)
    faltan, sobran = antes - ahora, ahora - antes
    if faltan or sobran:
        partes = []
        if faltan:
            partes.append("faltan " + ", ".join(_ficha_texto(f) for f in faltan.elements()))
        if sobran:
            partes.append("sobran " + ", ".join(_ficha_texto(f) for f in sobran.elements()))
        errores.append("Las fichas ⟦…⟧ (citas e imágenes) no se pueden agregar, quitar ni cambiar: " + "; ".join(partes) + ".")
    if pieza.startswith("consideraciones."):
        canonico, canonico_ref = a_canonico(nuevo), a_canonico(referencia)
        completas, sin_anio = lint._menciones_sueltas(canonico)
        completas_ref, sin_anio_ref = lint._menciones_sueltas(canonico_ref)
        menciones = sorted(completas - completas_ref) + [f"{t}-{n:03d}" for t, n in sorted(sin_anio - sin_anio_ref)]
        if menciones:
            errores.append(
                "No se admite jurisprudencia nueva en las consideraciones fuera de una ficha de cita: "
                + ", ".join(menciones)
                + "."
            )
        if _oraciones_sin_cita(canonico) > _oraciones_sin_cita(canonico_ref):
            errores.append(
                "No se admiten oraciones nuevas que atribuyan una regla a «la jurisprudencia» sin una ficha de cita en la misma oración."
            )
    return errores


def avisos(pieza: str, canonico: str, canonico_ia: str, ing: Ingesta | None) -> list[str]:
    if es_titulo(pieza):
        return []
    campo = etiqueta(pieza, {})

    def correr(texto: str) -> list[str]:
        msgs = lint.lint_prosa(texto, campo) + lint.residuos(texto)
        if ing is not None and pieza.startswith("apertura."):
            msgs += lint.datos_ajenos(texto, ing)
        return msgs

    previos = set(correr(canonico_ia))
    return [m for m in dict.fromkeys(correr(canonico)) if m not in previos]


def _ingesta(valores: Mapping[str, Any]) -> Ingesta | None:
    try:
        return Ingesta.model_validate(valores.get("ingesta"))
    except Exception:
        return None


def _vacia() -> dict:
    return {"version": VERSION, "piezas": {}, "conflictos": {}}


def _capa_valida(capa: Any) -> bool:
    return (
        isinstance(capa, dict)
        and isinstance(capa.get("piezas"), dict)
        and isinstance(capa.get("conflictos"), dict)
        and all(
            isinstance(e, dict) and isinstance(e.get("ia"), str) and isinstance(e.get("texto"), str)
            for e in capa["piezas"].values()
        )
        and all(isinstance(c, dict) and isinstance(c.get("trozos"), list) for c in capa["conflictos"].values())
    )


def leer(caso_dir: Path | str) -> dict:
    ruta = Path(caso_dir) / ARCHIVO
    if not ruta.exists():
        return _vacia()
    try:
        capa = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        capa = None
    if not _capa_valida(capa):
        log.warning("%s está corrupto; se ignora la capa de ediciones", ruta)
        return _vacia()
    capa.setdefault("version", VERSION)
    for e in capa["piezas"].values():
        e.setdefault("consolidado", e["ia"])
        e.setdefault("ancla", None)
        e.setdefault("avisos", [])
    for c in capa["conflictos"].values():
        c.setdefault("ia", None)
        c.setdefault("huerfana", False)
    return capa


def guardar(caso_dir: Path | str, capa: dict) -> Path:
    ruta = Path(caso_dir) / ARCHIVO
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    try:
        temporal.write_text(json.dumps(capa, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, ruta)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise
    return ruta


def registrar(caso_dir: Path | str, accion: str, pieza: str, ia: str | None, texto: str | None) -> None:
    linea = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accion": accion,
        "pieza": pieza,
        "ia": ia,
        "texto": texto,
    }
    with (Path(caso_dir) / LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def hay_conflictos(caso_dir: Path | str) -> bool:
    return bool(leer(caso_dir)["conflictos"])


def aplicar(valores: Mapping[str, Any], capa: dict) -> dict:
    salida = dict(valores)
    for pieza, e in capa["piezas"].items():
        if pieza in capa["conflictos"] or obtener(salida, pieza) is None:
            continue
        ancla = e.get("ancla")
        # El ancla se lee de `valores` (la IA), no de `salida`: un título humano ya fijado no debe desanclar el texto de su bloque.
        if ancla is not None and _ancla(valores, pieza) not in _validas(capa, pieza, ancla):
            continue
        salida[pieza.split(".")[0]] = fijar(salida, pieza, a_canonico(e["texto"]))
    return salida


def _evento(accion: str, pieza: str, ia: str | None, texto: str | None) -> dict:
    return {"accion": accion, "pieza": pieza, "ia": ia, "texto": texto}


def _validas(capa: dict, pieza: str, ancla: str) -> set[str | None]:
    """Valores del ancla actual con los que la pieza sigue en su sitio.

    Para una contestación, solo su entidad. Para un bloque, además del título de la IA con que se ancló, los títulos de la
    entrada `.titulo` del mismo bloque (misma ancla): tras consolidar, el estado guarda el título humano y la IA puede
    conservarlo al rehacer; eso no debe dejar huérfanas las ediciones de ese bloque.
    """
    validas: set[str | None] = {ancla}
    if m := _BLOQUE.fullmatch(pieza):
        titulo = capa["piezas"].get(f"consideraciones.bloques.{m[1]}.titulo")
        if titulo is not None and titulo.get("ancla") == ancla:
            validas |= {_titulo(titulo.get(campo)) for campo in ("ia", "texto", "consolidado")} - {None}
    return validas


def _hermana(pieza: str) -> str | None:
    m = _BLOQUE.fullmatch(pieza)
    return f"consideraciones.bloques.{m[1]}.{'texto' if m[2] == 'titulo' else 'titulo'}" if m else None


def _ancla_nueva(valores: Mapping[str, Any], capa: dict, pieza: str) -> str | None:
    """Ancla de una entrada que se crea ahora.

    Un bloque cuyo otro campo ya tiene entrada hereda su ancla si el título actual sigue siendo "su sitio" para ella: tras
    consolidar un título humano H, el estado dice H, pero el bloque se identifica por el título de la IA con que se ancló.
    Sin esto `titulo` y `texto` divergían (A y H) y la siguiente consolidación dejaba huérfano el texto.
    """
    actual = _ancla(valores, pieza)
    hermana = _hermana(pieza)
    e = capa["piezas"].get(hermana) if hermana else None
    if e is not None and e.get("ancla") is not None and actual in _validas(capa, hermana, e["ancla"]):
        return e["ancla"]
    return actual


def _reanclar_grupo(
    capa: dict,
    patron: re.Pattern[str],
    actuales: list[str | None],
    clave: Callable[[int, str], str],
) -> set[str]:
    """Mueve las entradas ancladas de un grupo (contestaciones o bloques) al índice donde está hoy su ancla.

    Un sitio es (índice, campo): los dos campos de un bloque (`titulo`, `texto`) se mueven juntos porque comparten ancla.
    Devuelve las claves (ya movidas) de las piezas huérfanas: las que no hallaron su ancla en ningún índice libre.
    """

    def sitio(pieza: str) -> tuple[int, str]:
        m = patron.fullmatch(pieza)
        return int(m[1]), (m[2] if (m.lastindex or 0) >= 2 else "texto")

    anclas = {p: e["ancla"] for p, e in capa["piezas"].items() if patron.fullmatch(p) and e.get("ancla") is not None}
    anclados = {p: _validas(capa, p, ancla) for p, ancla in anclas.items()}
    destino: dict[str, str] = {}
    reclamadas = {sitio(p) for p in capa["piezas"] if p not in anclados and patron.fullmatch(p)}
    orden = sorted(anclados, key=sitio)
    # Primero el ancla exacta (el título de la IA con que se ancló), en su índice y luego en otro; solo después los
    # títulos humanos de su entrada `.titulo`. Así un título humano igual al de otro bloque no le quita el sitio a ese bloque.
    for coincide in (lambda p, actual: actual == anclas[p], lambda p, actual: actual in anclados[p]):
        for pieza in orden:
            i, campo = sitio(pieza)
            if pieza not in destino and i < len(actuales) and (i, campo) not in reclamadas and coincide(pieza, actuales[i]):
                destino[pieza] = pieza
                reclamadas.add((i, campo))
        for pieza in orden:
            if pieza in destino:
                continue
            _, campo = sitio(pieza)
            j = next((j for j, actual in enumerate(actuales) if (j, campo) not in reclamadas and coincide(pieza, actual)), None)
            if j is not None:
                destino[pieza] = clave(j, campo)
                reclamadas.add((j, campo))
    huerfanas = [p for p in anclados if p not in destino]
    ocupadas = set(destino.values()) | set(capa["piezas"]) | set(capa["conflictos"])
    n = len(actuales)
    final = dict(destino)
    for pieza in huerfanas:
        if pieza in destino.values():
            _, campo = sitio(pieza)
            while clave(n, campo) in ocupadas:
                n += 1
            final[pieza] = clave(n, campo)
            ocupadas.add(final[pieza])
        else:
            final[pieza] = pieza
    for seccion in ("piezas", "conflictos"):
        capa[seccion] = {final.get(k, k): v for k, v in capa[seccion].items()}
    return {final[p] for p in huerfanas}


def _reanclar(valores: Mapping[str, Any], capa: dict) -> set[str]:
    contestaciones = (_seccion(valores, "apertura") or {}).get("contestaciones")
    entidades = [c.get("entidad") if isinstance(c, dict) else None for c in contestaciones] if isinstance(contestaciones, list) else []
    bloques = (_seccion(valores, "consideraciones") or {}).get("bloques")
    titulos = [_titulo(b.get("titulo")) if isinstance(b, dict) else None for b in bloques] if isinstance(bloques, list) else []
    huerfanas = _reanclar_grupo(capa, _CONTESTACION, entidades, lambda j, _: f"apertura.contestaciones.{j}.texto")
    huerfanas |= _reanclar_grupo(capa, _BLOQUE, titulos, lambda j, campo: f"consideraciones.bloques.{j}.{campo}")
    return huerfanas


def _unir(trozo: list[str]) -> str:
    return "\n\n".join(trozo)


def sincronizar(valores: Mapping[str, Any], capa: dict) -> tuple[dict, list[dict]]:
    """Rebase de la capa sobre la salida actual de la IA (§7). Es idempotente.

    Una pasada puede borrar entradas (ya sincronizadas) y liberar el sitio que reclamaban; una huérfana que podía ocuparlo
    solo se movería en la pasada siguiente. Por eso se repite hasta que la capa no cambia, con un tope.
    """
    capa = copy.deepcopy(capa)
    eventos: list[dict] = []
    for _ in range(len(capa["piezas"]) + 2):
        if not capa["piezas"]:
            break
        antes = copy.deepcopy(capa)
        eventos += _sincronizar_pasada(valores, capa)
        if capa == antes:
            break
    return capa, eventos


def _sincronizar_pasada(valores: Mapping[str, Any], capa: dict) -> list[dict]:
    eventos: list[dict] = []
    huerfanas = _reanclar(valores, capa)
    mapa, ing = mapa_citas(valores), _ingesta(valores)
    piezas, conflictos = capa["piezas"], capa["conflictos"]
    for pieza, e in list(piezas.items()):
        actual = None if pieza in huerfanas else obtener(valores, pieza)
        if actual is None:
            if not conflictos.get(pieza, {}).get("huerfana"):
                conflictos[pieza] = {"ia": None, "huerfana": True, "trozos": []}
                eventos.append(_evento("conflicto", pieza, None, e["texto"]))
            continue
        u = _editable(pieza, actual, mapa)
        if pieza in conflictos and conflictos[pieza]["ia"] == u:
            continue
        if u in (e["consolidado"], e["texto"], e["ia"]):
            conflictos.pop(pieza, None)
            e["consolidado"] = u
            if e["texto"] == e["ia"] == u:
                del piezas[pieza]
            continue
        trozos = fusion.fusionar(_partes(pieza, e["ia"]), _partes(pieza, e["texto"]), _partes(pieza, u))
        if not fusion.hay_conflicto(trozos):
            m = _unir(fusion.resultado(trozos))
            if fichas(m) != fichas(u) or validar(pieza, m, u, m):
                trozos = fusion.escalar(trozos)
        if fusion.hay_conflicto(trozos):
            conflictos[pieza] = {"ia": u, "huerfana": False, "trozos": fusion.compactar(trozos)}
            eventos.append(_evento("conflicto", pieza, u, e["texto"]))
            continue
        m = _unir(fusion.resultado(trozos))
        conflictos.pop(pieza, None)
        if e["texto"] != e["ia"]:
            eventos.append(_evento("rebase", pieza, u, m))
        e.update(ia=u, consolidado=u, texto=m, avisos=avisos(pieza, a_canonico(m), a_canonico(u), ing))
        if m == u:
            del piezas[pieza]
    return eventos


def consolidar(valores: Mapping[str, Any], capa: dict) -> dict:
    if capa["conflictos"]:
        raise ErrorEdicion(409, "Hay conflictos de edición pendientes; resuélvalos antes de continuar.")
    if not capa["piezas"]:
        return {}
    aplicado = aplicar(valores, capa)
    cambios = {nombre: aplicado[nombre] for nombre in ("apertura", "consideraciones") if isinstance(aplicado.get(nombre), dict)}
    editadas = {seccion_de(p) for p, e in capa["piezas"].items() if e["texto"] != e["ia"]}
    cambios["ediciones_humanas"] = sorted(set(valores.get("ediciones_humanas") or []) | editadas)
    return cambios


def editar(valores: Mapping[str, Any], capa: dict, pieza: str, parrafo: int, original: str, texto: str) -> dict:
    capa = copy.deepcopy(capa)
    if pieza in capa["conflictos"]:
        raise ErrorEdicion(409, "La pieza tiene un conflicto pendiente; resuélvalo antes de editarla.")
    actual = obtener(valores, pieza)
    if actual is None:
        raise ErrorEdicion(404, f"No existe la pieza {pieza}.")
    u = _editable(pieza, actual, mapa_citas(valores))
    e = capa["piezas"].get(pieza)
    partes = _partes(pieza, e["texto"] if e else u)
    if not 0 <= parrafo < len(partes) or normalizar(original) != partes[parrafo]:
        raise ErrorEdicion(409, "El texto cambió; recargue el borrador.")
    nuevo = _unir(partes[:parrafo] + parrafos(texto) + partes[parrafo + 1 :])
    errores = validar(pieza, nuevo, u, texto)
    if errores:
        raise ErrorEdicion(422, " ".join(errores))
    nuevo = _FICHA.sub(lambda m: _ficha_texto(_clave(m)), nuevo)
    if e is None:
        e = {"ia": u, "texto": u, "consolidado": u, "ancla": _ancla_nueva(valores, capa, pieza), "avisos": []}
    e["texto"] = nuevo
    e["avisos"] = avisos(pieza, a_canonico(nuevo), a_canonico(e["ia"]), _ingesta(valores))
    if e["texto"] == e["ia"] == e["consolidado"]:
        capa["piezas"].pop(pieza, None)
    else:
        capa["piezas"][pieza] = e
    return capa


def restaurar(valores: Mapping[str, Any], capa: dict, pieza: str) -> dict:
    if not es_pieza(pieza):
        raise ErrorEdicion(404, f"No existe la pieza {pieza}.")
    capa = copy.deepcopy(capa)
    conflicto = capa["conflictos"].pop(pieza, None)
    e = capa["piezas"].get(pieza)
    if conflicto is not None and conflicto["huerfana"]:
        capa["piezas"].pop(pieza, None)
    elif conflicto is not None:
        if e is not None:
            e.update(ia=conflicto["ia"], texto=conflicto["ia"], avisos=[])
    elif e is not None:
        e.update(texto=e["ia"], avisos=[])
        if e["consolidado"] == e["ia"]:
            del capa["piezas"][pieza]
    return capa


def resolver(valores: Mapping[str, Any], capa: dict, pieza: str, elecciones: list[str]) -> dict:
    capa = copy.deepcopy(capa)
    conflicto = capa["conflictos"].get(pieza)
    if conflicto is None:
        raise ErrorEdicion(409, "La pieza no tiene un conflicto pendiente.")
    if conflicto["huerfana"]:
        raise ErrorEdicion(422, "La pieza ya no existe en el borrador; solo puede descartar su edición.")
    pendientes = [t for t in conflicto["trozos"] if t["tipo"] == "conflicto"]
    if len(elecciones) != len(pendientes) or any(x not in ("mio", "nuevo") for x in elecciones):
        raise ErrorEdicion(422, f"Debe elegir una versión para cada uno de los {len(pendientes)} conflictos.")
    for n, (trozo, lado) in enumerate(zip(pendientes, elecciones), 1):
        if lado == "mio" and _fichas_de(trozo["mio"]) != _fichas_de(trozo["nuevo"]):
            raise ErrorEdicion(422, f"En el conflicto {n} no puede conservar su versión: cambia las citas o imágenes del texto.")
    texto = _unir(fusion.resultado(conflicto["trozos"], elecciones))
    errores = validar(pieza, texto, conflicto["ia"], texto)
    if errores:
        raise ErrorEdicion(422, " ".join(errores))
    ia = conflicto["ia"]
    e = capa["piezas"].get(pieza) or {"ancla": _ancla_nueva(valores, capa, pieza)}
    e.update(
        ia=ia,
        consolidado=ia,
        texto=texto,
        avisos=avisos(pieza, a_canonico(texto), a_canonico(ia), _ingesta(valores)),
    )
    del capa["conflictos"][pieza]
    if texto == ia:
        capa["piezas"].pop(pieza, None)
    else:
        capa["piezas"][pieza] = e
    return capa


def _editados(pieza: str, ia: str, texto: str) -> list[int]:
    ops = SequenceMatcher(None, _partes(pieza, ia), _partes(pieza, texto), autojunk=False).get_opcodes()
    return [k for tag, _, _, j1, j2 in ops if tag in ("insert", "replace") for k in range(j1, j2)]


def _trozo_respuesta(trozo: dict) -> dict:
    if trozo["tipo"] == "ok":
        return {"tipo": "ok", "parrafos": trozo["parrafos"]}
    permitido = _fichas_de(trozo["mio"]) == _fichas_de(trozo["nuevo"])
    return {"tipo": "conflicto", "mio": trozo["mio"], "nuevo": trozo["nuevo"], "mio_permitido": permitido}


def respuesta(valores: Mapping[str, Any], capa: dict, editable: bool = True, motivo: str | None = None) -> dict:
    cuerpo: dict = {"editable": editable, "motivo": motivo, "piezas": {}, "conflictos": []}
    if not editable:
        return cuerpo
    mapa = mapa_citas(valores)
    orden = catalogo(valores)
    for pieza in orden:
        e, conflicto = capa["piezas"].get(pieza), capa["conflictos"].get(pieza)
        u = _editable(pieza, obtener(valores, pieza), mapa)
        modificada = False
        if conflicto is not None:
            texto, editados, avs = conflicto["ia"] if conflicto["ia"] is not None else u, [], []
        elif e is not None:
            texto, editados, avs = e["texto"], _editados(pieza, e["ia"], e["texto"]), list(e["avisos"])
            modificada = _partes(pieza, e["texto"]) != _partes(pieza, e["ia"])
        else:
            texto, editados, avs = u, [], []
        cuerpo["piezas"][pieza] = {"parrafos": _partes(pieza, texto), "editados": editados, "modificada": modificada, "avisos": avs}
    for pieza in sorted(capa["conflictos"], key=lambda p: orden.index(p) if p in orden else len(orden)):
        conflicto = capa["conflictos"][pieza]
        e = capa["piezas"].get(pieza) or {}
        huerfana = bool(conflicto["huerfana"])
        trozos = [_trozo_respuesta(t) for t in conflicto["trozos"]]
        if huerfana and e.get("texto"):
            # Solo se puede descartar: se muestra su texto para que el usuario pueda copiarlo antes.
            trozos = [{"tipo": "ok", "parrafos": _partes(pieza, e["texto"])}]
        cuerpo["conflictos"].append(
            {
                "pieza": pieza,
                "etiqueta": etiqueta(pieza, valores, e.get("ancla"), huerfana),
                "huerfana": huerfana,
                "trozos": trozos,
            }
        )
    return cuerpo
