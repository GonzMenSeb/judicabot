from __future__ import annotations

import json
import math
import tempfile
import threading
import time
from pathlib import Path

from .clasificar import texto_cabecera
from .config import Config
from .ingest import EXTENSIONES, ingerir
from .jev import JevClient, RespuestaJev
from .jev_roles import ROLES_JEV, OpinionRol, rellenable, segunda_opinion
from .models import Doc, Ingesta

UMBRALES = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
CARPETA_PRIMERA = "01PrimeraInstancia"
PREFIJO_NUEVO = "nuevo:"


class _Medido:
    def __init__(self, cliente: JevClient) -> None:
        self._cliente = cliente
        self._lock = threading.Lock()
        self.latencias: list[float] = []
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.modelos: set[str] = set()

    def preguntar(self, estado: str | dict, preguntas: dict[str, dict], modelo: str) -> RespuestaJev:
        inicio = time.perf_counter()
        try:
            resp = self._cliente.preguntar(estado, preguntas, modelo)
        finally:
            with self._lock:
                self.latencias.append(time.perf_counter() - inicio)
        with self._lock:
            self.tokens_entrada += resp.tokens_entrada
            self.tokens_salida += resp.tokens_salida
            if resp.modelo:
                self.modelos.add(resp.modelo)
        return resp


def _razon(parte: int, total: int) -> float | None:
    return parte / total if total else None


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p * len(ordenados)) - 1)]


def _rol_verdad(rol: str) -> str:
    base = rol.removeprefix(PREFIJO_NUEVO)
    return base if rol.startswith(PREFIJO_NUEVO) and base in ROLES_JEV else rol


def _legible(archivo: str) -> bool:
    return Path(archivo).suffix.lower() in EXTENSIONES


def _emparejar(entradas: list[dict], docs: list[Doc]) -> tuple[dict[int, Doc], list[Doc]]:
    reglas = (
        lambda archivo, d: d.ruta == archivo,
        lambda archivo, d: archivo.endswith("/" + d.ruta) or d.ruta.endswith("/" + archivo),
        lambda archivo, d: Path(archivo).name == d.nombre,
    )
    libres = list(docs)
    pareja: dict[int, Doc] = {}
    for regla in reglas:
        for i, entrada in enumerate(entradas):
            if i in pareja:
                continue
            candidatos = [d for d in libres if regla(entrada["file"], d)]
            if len(candidatos) == 1:
                pareja[i] = candidatos[0]
                libres.remove(candidatos[0])
    return pareja, libres


def _fila(caso: str, entrada: dict, doc: Doc, opinion: OpinionRol) -> dict:
    return {
        "caso": caso,
        "archivo": entrada["file"],
        "verdad": entrada["role"],
        "codigo": doc.rol,
        "jev": opinion.rol,
        "confianza": opinion.confianza,
        "confianza_verdad": entrada.get("confidence"),
    }


def comparar(verdad: list[dict], ingestas: dict[str, Ingesta], opiniones: dict[str, list[OpinionRol]]) -> dict:
    pares: list[tuple[str, dict, Doc, OpinionRol | None]] = []
    sin_pareja: list[str] = []
    no_legibles: list[str] = []
    verdad_sin_pareja = 0
    for item in verdad:
        caso = item["case"]
        ing = ingestas.get(caso)
        docs = [d for d in ing.documentos if d.instancia == "1a"] if ing else []
        por_id = {o.doc_id: o for o in opiniones.get(caso, [])}
        pareja, libres = _emparejar(item["docs"], docs)
        for i, entrada in enumerate(item["docs"]):
            doc = pareja.get(i)
            if doc is None and not _legible(entrada["file"]):
                no_legibles.append(entrada["file"])
            elif doc is None:
                sin_pareja.append(entrada["file"])
                verdad_sin_pareja += 1
            else:
                pares.append((caso, entrada, doc, por_id.get(doc.doc_id)))
        sin_pareja += [d.ruta for d in libres]

    sin_opinion: dict[str, dict[str, int]] = {}
    for caso, _, doc, opinion in pares:
        cuenta = sin_opinion.setdefault(caso, {"sin_texto": 0, "sin_respuesta": 0})
        if opinion is None:
            cuenta["sin_respuesta" if texto_cabecera(doc).strip() else "sin_texto"] += 1

    rescates: list[dict] = []
    falsos_rellenos: list[dict] = []
    fuera_de_catalogo: list[dict] = []
    discrepancias: list[dict] = []
    for caso, entrada, doc, opinion in pares:
        if opinion is None:
            continue
        fila = _fila(caso, entrada, doc, opinion)
        if opinion.rol != doc.rol:
            discrepancias.append(fila)
        if rellenable(doc, opinion, ingestas[caso].documentos):
            verdad_n = _rol_verdad(entrada["role"])
            if opinion.rol == verdad_n:
                rescates.append(fila)
            else:
                falsos_rellenos.append(fila)
                if verdad_n not in ROLES_JEV:
                    fuera_de_catalogo.append(fila)

    n_docs = len(pares)
    con_jev = [(entrada, doc, opinion) for _, entrada, doc, opinion in pares if opinion is not None]
    por_umbral: dict[float, dict] = {}
    for umbral in UMBRALES:
        elegidas = [x for x in con_jev if x[2].confianza >= umbral]
        por_umbral[umbral] = {
            "cobertura": len(elegidas) / n_docs if n_docs else 0.0,
            "exactitud": _razon(sum(o.rol == _rol_verdad(e["role"]) for e, _, o in elegidas), len(elegidas)),
            "rescates": sum(f["confianza"] >= umbral for f in rescates),
            "falsos_rellenos": sum(f["confianza"] >= umbral for f in falsos_rellenos),
        }
    completo = verdad_sin_pareja == 0 and not any(c["sin_respuesta"] for c in sin_opinion.values())
    umbral_relleno = next(
        (u for u in UMBRALES if por_umbral[u]["falsos_rellenos"] == 0 and por_umbral[u]["rescates"] >= 1), None
    )
    return {
        "n_docs": n_docs,
        "n_con_jev": len(con_jev),
        "n_fuera_catalogo": sum(_rol_verdad(entrada["role"]) not in ROLES_JEV for _, entrada, _, _ in pares),
        "exactitud_codigo": _razon(sum(d.rol == _rol_verdad(e["role"]) for _, e, d, _ in pares), n_docs),
        "exactitud_codigo_en_jev": _razon(sum(d.rol == _rol_verdad(e["role"]) for e, d, _ in con_jev), len(con_jev)),
        "exactitud_jev": _razon(sum(o.rol == _rol_verdad(e["role"]) for e, _, o in con_jev), len(con_jev)),
        "por_umbral": por_umbral,
        "completo": completo,
        "umbral_relleno": umbral_relleno if completo else None,
        "rescates": rescates,
        "falsos_rellenos": falsos_rellenos,
        "fuera_de_catalogo": fuera_de_catalogo,
        "discrepancias": discrepancias,
        "sin_opinion": sin_opinion,
        "sin_pareja": sin_pareja,
        "no_legibles": no_legibles,
        "n_verdad_sin_pareja": verdad_sin_pareja,
    }


def _pasada(
    ingestas: dict[str, Ingesta], cliente: JevClient, cfg: Config, invertir: bool
) -> tuple[dict[str, list[OpinionRol]], list[str]]:
    opiniones: dict[str, list[OpinionRol]] = {}
    alertas: list[str] = []
    for caso, ing in ingestas.items():
        ops, avisos = segunda_opinion(ing.documentos, cliente, cfg, invertir)
        opiniones[caso] = ops
        alertas += [f"{caso}: {a}" for a in avisos]
    return opiniones, alertas


def _inversion(
    verdad: list[dict],
    ingestas: dict[str, Ingesta],
    directas: dict[str, list[OpinionRol]],
    invertidas: dict[str, list[OpinionRol]],
) -> dict:
    cambios: list[dict] = []
    comparables = 0
    for caso, ing in ingestas.items():
        rutas = {d.doc_id: d.ruta for d in ing.documentos}
        inversas = {o.doc_id: o for o in invertidas.get(caso, [])}
        for directa in directas.get(caso, []):
            inversa = inversas.get(directa.doc_id)
            if inversa is None:
                continue
            comparables += 1
            if inversa.rol != directa.rol:
                cambios.append(
                    {
                        "caso": caso,
                        "archivo": rutas[directa.doc_id],
                        "directo": directa.rol,
                        "invertido": inversa.rol,
                        "confianza_directo": directa.confianza,
                        "confianza_invertido": inversa.confianza,
                    }
                )
    return {
        "comparables": comparables,
        "cambian": len(cambios),
        "cambios": cambios,
        "exactitud_jev": comparar(verdad, ingestas, invertidas)["exactitud_jev"],
    }


def correr(referencia: Path, cliente: JevClient, cfg: Config, invertir: bool = False) -> dict:
    referencia = Path(referencia)
    verdad = json.loads((referencia / "analisis" / "ground_truth_1a.json").read_text(encoding="utf-8"))
    cfg_ingesta = cfg.model_copy(update={"jev": cfg.jev.model_copy(update={"modo": "apagado"})})
    medido = _Medido(cliente)
    ingestas: dict[str, Ingesta] = {}
    ausentes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jev-bench-") as tmp:
        for item in verdad:
            caso = item["case"]
            origen = referencia / "casos" / caso / CARPETA_PRIMERA
            if not origen.is_dir():
                ausentes.append(caso)
                continue
            carpeta = Path(tmp) / caso
            carpeta.mkdir()
            (carpeta / "insumos").symlink_to(origen.resolve(), target_is_directory=True)
            ingestas[caso] = ingerir(carpeta, cfg_ingesta)

    directas, alertas = _pasada(ingestas, medido, cfg, False)
    informe = comparar(verdad, ingestas, directas)
    inversion = None
    if invertir:
        invertidas, alertas_inv = _pasada(ingestas, medido, cfg, True)
        alertas += [f"(orden invertido) {a}" for a in alertas_inv]
        inversion = _inversion(verdad, ingestas, directas, invertidas)
    informe.update(
        casos_ausentes=ausentes,
        alertas=alertas,
        inversion=inversion,
        modelos=sorted(medido.modelos),
        latencia_s={
            "n": len(medido.latencias),
            "p50": _percentil(medido.latencias, 0.5),
            "p95": _percentil(medido.latencias, 0.95),
        },
        tokens={"entrada": medido.tokens_entrada, "salida": medido.tokens_salida},
    )
    return informe


def _pct(valor: float | None) -> str:
    return "n/d" if valor is None else f"{valor:.1%}"


def _seg(valor: float | None) -> str:
    return "n/d" if valor is None else f"{valor:.1f} s"


def _tabla_filas(filas: list[dict]) -> list[str]:
    if not filas:
        return ["Ninguno.", ""]
    lineas = ["| Caso | Archivo | Verdad (confianza) | Código | Jev | Confianza |", "|---|---|---|---|---|---|"]
    lineas += [
        f"| {f['caso']} | {f['archivo']} | {f['verdad']} ({f['confianza_verdad'] or 'n/d'}) | {f['codigo']} | "
        f"{f['jev']} | {f['confianza']:.2f} |"
        for f in filas
    ]
    return lineas + [""]


def informe_markdown(informe: dict) -> str:
    umbral = informe["umbral_relleno"]
    latencia = informe["latencia_s"]
    lineas = [
        "# Benchmark de roles de Jev",
        "",
        f"- Documentos emparejados con la verdad: {informe['n_docs']} (sin pareja: {len(informe['sin_pareja'])})",
        f"- Exactitud del código: {_pct(informe['exactitud_codigo'])}",
        f"- Documentos con opinión de Jev: {informe['n_con_jev']}",
        f"- Exactitud de Jev: {_pct(informe['exactitud_jev'])} "
        f"(el código, en esos mismos documentos: {_pct(informe['exactitud_codigo_en_jev'])})",
        f"- Documentos cuyo rol de la verdad no está en el catálogo de Jev: {informe['n_fuera_catalogo']}",
        f"- Archivos de la verdad que la ingesta no lee (no invalidan la corrida): {len(informe['no_legibles'])}",
        f"- Modelos de Jev: {', '.join(informe['modelos']) or 'n/d'}",
        f"- Latencia por petición: p50 {_seg(latencia['p50'])}, p95 {_seg(latencia['p95'])} ({latencia['n']} peticiones)",
        f"- Tokens: {informe['tokens']['entrada']} de entrada, {informe['tokens']['salida']} de salida",
    ]
    if informe["casos_ausentes"]:
        lineas.append(f"- Casos sin carpeta {CARPETA_PRIMERA}: {', '.join(informe['casos_ausentes'])}")
    lineas += ["", "## Decisión sobre `relleno`", "", "Regla: cero falsos rellenos y al menos un rescate en el umbral elegido."]
    if not informe["completo"]:
        sin_respuesta = sum(c["sin_respuesta"] for c in informe["sin_opinion"].values())
        lineas.append(
            "La corrida está incompleta, así que la regla no se puede certificar: "
            f"{len(informe['casos_ausentes'])} casos sin carpeta, "
            f"{informe['n_verdad_sin_pareja']} archivos de la verdad sin pareja, "
            f"{sin_respuesta} documentos con texto sin respuesta de Jev. "
            "Resuelve eso y repite; mientras tanto la recomendación es `sombra`."
        )
    elif umbral is None:
        lineas.append("Ningún umbral cumple la regla: la recomendación es `sombra`.")
    else:
        lineas.append(
            f"Umbral más bajo que la cumple: {umbral}. Con pocos casos es un indicio, no una garantía."
        )
    lineas += [
        "",
        "## Por umbral",
        "",
        "La cobertura es la fracción de los documentos emparejados sobre los que Jev dio una opinión con esa confianza o más.",
        "",
        "| Umbral | Cobertura | Exactitud | Rescates | Falsos rellenos |",
        "|---|---|---|---|---|",
    ]
    for u, fila in informe["por_umbral"].items():
        lineas.append(
            f"| {u} | {_pct(fila['cobertura'])} | {_pct(fila['exactitud'])} | {fila['rescates']} | {fila['falsos_rellenos']} |"
        )
    lineas += ["", "## Rescates", "", "El código dijo `otro` por falta de rasgos y Jev acertó.", ""]
    lineas += _tabla_filas(informe["rescates"])
    lineas += ["## Falsos rellenos", "", "El código dijo `otro` por falta de rasgos y Jev propone otro rol distinto de la verdad.", ""]
    lineas += _tabla_filas(informe["falsos_rellenos"])
    lineas += [
        "## Falsos rellenos sobre roles fuera del catálogo",
        "",
        "Parte de los falsos rellenos: el rol de la verdad no existe en el catálogo de Jev, así que ninguna propuesta puede acertar.",
        "",
    ]
    lineas += _tabla_filas(informe["fuera_de_catalogo"])
    lineas += ["## Discrepancias con el código", "", "Jev propone un rol distinto del que asignó el código.", ""]
    lineas += _tabla_filas(informe["discrepancias"])
    lineas += ["## Documentos sin opinión de Jev", ""]
    lineas += [
        f"- {caso}: {c['sin_texto']} sin texto, {c['sin_respuesta']} sin respuesta"
        for caso, c in informe["sin_opinion"].items()
        if c["sin_texto"] or c["sin_respuesta"]
    ] or ["Ninguno."]
    lineas += ["", "## Archivos sin pareja", ""]
    lineas += [f"- {a}" for a in informe["sin_pareja"]] or ["Ninguno."]
    lineas += ["", "## Archivos de la verdad que la ingesta no lee", ""]
    lineas += [f"- {a}" for a in informe["no_legibles"]] or ["Ninguno."]
    inversion = informe["inversion"]
    if inversion is not None:
        lineas += [
            "",
            "## Orden invertido",
            "",
            f"- Etiquetas que cambian: {inversion['cambian']} de {inversion['comparables']} comparables",
            f"- Exactitud de Jev con el orden invertido: {_pct(inversion['exactitud_jev'])}",
            "",
        ]
        if inversion["cambios"]:
            lineas += [
                "| Caso | Archivo | Directo | Invertido | Confianza directo | Confianza invertido |",
                "|---|---|---|---|---|---|",
            ]
            lineas += [
                f"| {c['caso']} | {c['archivo']} | {c['directo']} | {c['invertido']} | "
                f"{c['confianza_directo']:.2f} | {c['confianza_invertido']:.2f} |"
                for c in inversion["cambios"]
            ]
    if informe["alertas"]:
        lineas += ["", "## Alertas", ""] + [f"- {a}" for a in informe["alertas"]]
    return "\n".join(lineas) + "\n"
