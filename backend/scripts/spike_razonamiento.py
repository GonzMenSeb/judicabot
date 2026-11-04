from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SALIDA = Path(__file__).resolve().parent / "salida" / "spike_razonamiento.json"
BETA_UPDATES = "thinking-display-updates-2026-08-18"
NODO = "apertura"
DERIVADOS = {"text", "thinking", "signature", "input_json", "citation", "compaction"}
BLOQUES_CON_TEXTO = {"text", "thinking"}
MAX_TEXTO_BLOQUE = 6000

VARIANTES: dict[str, dict[str, Any]] = {
    "base": {
        "descripcion": "Igual que hoy: sin parámetro thinking (adaptativo por defecto, display omitido)",
        "thinking": None,
        "betas": [],
    },
    "resumen": {
        "descripcion": "thinking adaptativo con display=summarized",
        "thinking": {"type": "adaptive", "display": "summarized"},
        "betas": [],
    },
    "updates": {
        "descripcion": "thinking adaptativo con display=updates (beta; notas entre llamadas a herramientas)",
        "thinking": {"type": "adaptive", "display": "updates"},
        "betas": [BETA_UPDATES],
    },
}

SIN_CLAVE = """\
Falta la variable de entorno ANTHROPIC_API_KEY.

Este spike llama de verdad al modelo. Para correrlo:

  export ANTHROPIC_API_KEY=sk-ant-...
  cd backend
  uv run python scripts/spike_razonamiento.py --modelo claude-sonnet-5-5

Antes de gastar nada puede revisar lo que se enviaría con --solo-entrada (no requiere clave).
Resultados: backend/scripts/salida/spike_razonamiento.json
Instrucciones completas: docs/superpowers/specs/2026-11-03-spike-razonamiento.md
"""

ES = {"el", "la", "los", "las", "de", "del", "que", "y", "en", "un", "una", "es", "se", "por", "con", "para", "al", "lo", "su", "no"}
EN = {"the", "of", "and", "to", "in", "is", "that", "for", "with", "as", "on", "this", "are", "be", "it", "was", "not", "which", "from"}


class _Captura(Exception):
    def __init__(self, nodo: str, system: str, user: str, schema: type) -> None:
        super().__init__(nodo)
        self.nodo, self.system, self.user, self.schema = nodo, system, user, schema


class _Espia:
    def estructurado(self, nodo, system, user, schema, cfg):
        raise _Captura(nodo, system, user, schema)


class Registro:
    def __init__(self, t0: float) -> None:
        self.t0 = t0
        self.t_conexion: float | None = None
        self.t_message_start: float | None = None
        self.t_fin: float | None = None
        self.bloques: dict[int, dict[str, Any]] = {}
        self.por_tipo: dict[str, dict[str, Any]] = {}
        self.lineas: list[dict[str, Any]] = []
        self.derivados_ignorados = 0
        self.mensaje_inicial: dict[str, Any] = {}

    def t(self) -> float:
        return time.perf_counter() - self.t0

    def evento(self, ev: Any) -> None:
        tipo = getattr(ev, "type", type(ev).__name__)
        if tipo in DERIVADOS:
            self.derivados_ignorados += 1
            return
        t = self.t()
        indice = getattr(ev, "index", None)
        etiqueta = tipo
        chars = 0
        detalle = ""

        if tipo == "message_start":
            self.t_message_start = t
            msg = ev.message
            self.mensaje_inicial = {"modelo": getattr(msg, "model", None), "id": getattr(msg, "id", None)}
        elif tipo == "content_block_start":
            cb = ev.content_block
            btipo = getattr(cb, "type", "?")
            inicial = getattr(cb, "thinking", None) or getattr(cb, "text", None) or ""
            self.bloques[indice] = {
                "indice": indice,
                "tipo": btipo,
                "t_inicio": t,
                "t_primer_delta": None,
                "t_primer_delta_con_texto": None,
                "t_ultimo_delta": None,
                "t_fin": None,
                "n_deltas": 0,
                "n_deltas_con_texto": 0,
                "chars": len(inicial),
                "tipos_delta": {},
                "_tiempos": [],
                "_tamanos": [],
                "_texto": inicial if btipo in BLOQUES_CON_TEXTO else "",
            }
            if btipo not in BLOQUES_CON_TEXTO | {"redacted_thinking"}:
                try:
                    detalle = json.dumps(cb.model_dump(), ensure_ascii=False)[:400]
                    self.bloques[indice]["detalle"] = detalle
                except Exception:
                    detalle = ""
            etiqueta = f"content_block_start:{btipo}"
            detalle = detalle or btipo
        elif tipo == "content_block_delta":
            delta = ev.delta
            dtipo = getattr(delta, "type", "?")
            etiqueta = dtipo
            contenido = (
                getattr(delta, "thinking", None)
                or getattr(delta, "text", None)
                or getattr(delta, "partial_json", None)
                or getattr(delta, "signature", None)
                or ""
            )
            chars = len(contenido)
            b = self.bloques.setdefault(
                indice,
                {"indice": indice, "tipo": "?", "t_inicio": t, "t_primer_delta": None, "t_primer_delta_con_texto": None,
                 "t_ultimo_delta": None, "t_fin": None, "n_deltas": 0, "n_deltas_con_texto": 0, "chars": 0,
                 "tipos_delta": {}, "_tiempos": [], "_tamanos": [], "_texto": ""},
            )
            b["n_deltas"] += 1
            b["tipos_delta"][dtipo] = b["tipos_delta"].get(dtipo, 0) + 1
            b["t_primer_delta"] = b["t_primer_delta"] if b["t_primer_delta"] is not None else t
            b["t_ultimo_delta"] = t
            if chars and dtipo != "signature_delta":
                b["n_deltas_con_texto"] += 1
                b["chars"] += chars
                b["_tiempos"].append(t)
                b["_tamanos"].append(chars)
                if b["t_primer_delta_con_texto"] is None:
                    b["t_primer_delta_con_texto"] = t
                if dtipo in ("thinking_delta", "text_delta") and b["tipo"] in BLOQUES_CON_TEXTO:
                    if len(b["_texto"]) < MAX_TEXTO_BLOQUE:
                        b["_texto"] += contenido
        elif tipo == "content_block_stop":
            if indice in self.bloques:
                self.bloques[indice]["t_fin"] = t
        elif tipo == "message_delta":
            d = getattr(ev, "delta", None)
            detalle = f"stop_reason={getattr(d, 'stop_reason', None)}"
        elif tipo == "message_stop":
            self.t_fin = t

        fila = self.por_tipo.setdefault(etiqueta, {"n": 0, "primero": t, "ultimo": t, "chars": 0})
        fila["n"] += 1
        fila["ultimo"] = t
        fila["chars"] += chars

        if self.lineas and self.lineas[-1]["evento"] == etiqueta and self.lineas[-1]["indice"] == indice and etiqueta.endswith("_delta"):
            ult = self.lineas[-1]
            ult["hasta"] = t
            ult["n"] += 1
            ult["chars"] += chars
        else:
            self.lineas.append(
                {"t": t, "hasta": t, "evento": etiqueta, "indice": indice, "n": 1, "chars": chars, "detalle": detalle}
            )


def _idioma(texto: str) -> dict[str, Any]:
    palabras = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]+", texto.lower())
    es = sum(p in ES for p in palabras)
    en = sum(p in EN for p in palabras)
    if es + en < 5:
        probable = "indeterminado"
    elif es >= 1.5 * en:
        probable = "es"
    elif en >= 1.5 * es:
        probable = "en"
    else:
        probable = "mixto"
    return {"palabras": len(palabras), "marcas_es": es, "marcas_en": en, "probable": probable}


def _estadisticas(b: dict[str, Any]) -> dict[str, Any]:
    tiempos, tamanos = b.pop("_tiempos"), b.pop("_tamanos")
    texto = b.pop("_texto")
    huecos = [y - x for x, y in zip(tiempos, tiempos[1:])]
    b["huecos_mediana_s"] = round(statistics.median(huecos), 4) if huecos else None
    b["huecos_max_s"] = round(max(huecos), 4) if huecos else None
    b["delta_chars_mediana"] = statistics.median(tamanos) if tamanos else None
    b["delta_chars_max"] = max(tamanos) if tamanos else None
    b["parrafos"] = len([p for p in re.split(r"\n\s*\n", texto) if p.strip()]) if b["tipo"] == "thinking" else None
    b["_texto_bruto"] = texto
    return b


def _redondear(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _redondear(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_redondear(v) for v in x]
    return x


def construir_resultado(
    nombre: str, repeticion: int, parametros: dict, reg: Registro, final: Any, error: dict | None, schema: type, guardar_texto: bool
) -> dict[str, Any]:
    from tutela2.llm import _resumen_errores, _tokens

    bloques = [_estadisticas(b) for _, b in sorted(reg.bloques.items(), key=lambda kv: (kv[0] is None, kv[0]))]
    thinking = [b for b in bloques if b["tipo"] == "thinking"]
    textos = [b for b in bloques if b["tipo"] == "text"]
    texto_pensado = "\n\n".join(b["_texto_bruto"] for b in thinking)
    for b in bloques:
        bruto = b.pop("_texto_bruto")
        if b["tipo"] == "thinking" and guardar_texto:
            b["texto"] = bruto
            b["texto_truncado"] = b["chars"] > len(bruto)

    res: dict[str, Any] = {
        "variante": nombre,
        "repeticion": repeticion,
        "parametros": parametros,
        "ok": error is None,
        "error": error,
        "tiempos_s": {
            "conexion": reg.t_conexion,
            "message_start": reg.t_message_start,
            "primer_bloque_thinking": thinking[0]["t_inicio"] if thinking else None,
            "primer_thinking_con_texto": next((b["t_primer_delta_con_texto"] for b in thinking if b["t_primer_delta_con_texto"] is not None), None),
            "primer_text_delta": next((b["t_primer_delta"] for b in textos if b["t_primer_delta"] is not None), None),
            "total": reg.t_fin if reg.t_fin is not None else reg.t(),
        },
        "razonamiento": {
            "bloques": len(thinking),
            "chars": sum(b["chars"] for b in thinking),
            "visible": any(b["chars"] > 0 for b in thinking),
            "idioma": _idioma(texto_pensado) if texto_pensado else None,
        },
        "salida_texto": {"bloques": len(textos), "chars": sum(b["chars"] for b in textos)},
        "tipos_de_bloque": sorted({b["tipo"] for b in bloques}),
        "bloques": bloques,
        "eventos_por_tipo": reg.por_tipo,
        "lineas_de_tiempo": reg.lineas,
        "eventos_derivados_ignorados": reg.derivados_ignorados,
        "mensaje_inicial": reg.mensaje_inicial,
    }
    if final is not None:
        entrada, salida = _tokens(final)
        res["uso"] = {
            "tokens_entrada": entrada,
            "tokens_salida": salida,
            "usage": _a_dict(getattr(final, "usage", None)),
        }
        res["stop_reason"] = getattr(final, "stop_reason", None)
        res["modelo_efectivo"] = getattr(final, "model", None)
        res["request_id"] = getattr(final, "_request_id", None)
        if salida and res["tiempos_s"]["total"]:
            res["tiempos_s"]["s_por_1000_tokens_salida"] = res["tiempos_s"]["total"] / salida * 1000
        texto = "".join(b.text for b in final.content if getattr(b, "type", None) == "text")
        try:
            schema.model_validate_json(texto)
            res["esquema_valido"] = True
        except Exception as e:
            res["esquema_valido"] = False
            res["error_esquema"] = _resumen_errores(e) if hasattr(e, "errors") else str(e)[:500]
    return _redondear(res)


def _a_dict(x: Any) -> Any:
    if x is None:
        return None
    try:
        return x.model_dump()
    except Exception:
        return str(x)


def argumentos_api(cfg: Any, captura: _Captura, variante: dict, args: argparse.Namespace) -> tuple[dict, dict]:
    from anthropic.lib._parse._transform import to_json_output_format

    from tutela2.llm import BETA_FALLBACK
    from tutela2.config import RESPALDO_CLIENTE

    modelo = args.modelo or cfg.modelo_para(NODO)
    effort = args.effort or cfg.effort_para(NODO)
    api: dict[str, Any] = dict(
        model=modelo,
        max_tokens=args.max_tokens or cfg.llm.max_tokens,
        system=captura.system,
        messages=[{"role": "user", "content": captura.user}],
        output_config={"effort": effort, "format": to_json_output_format(captura.schema)},
        timeout=cfg.llm.timeout_s,
    )
    if variante["thinking"]:
        api["thinking"] = variante["thinking"]
    fallbacks = cfg.llm.fallbacks_default and not args.sin_fallbacks and modelo not in RESPALDO_CLIENTE
    betas = ([BETA_FALLBACK] if fallbacks else []) + variante["betas"]
    usa_beta = bool(betas)
    extra: dict[str, Any] = {}
    if usa_beta:
        extra["betas"] = betas
    if fallbacks:
        extra["fallbacks"] = "default"
    parametros = {
        "modelo": modelo,
        "effort": effort,
        "max_tokens": api["max_tokens"],
        "thinking": variante["thinking"],
        "endpoint": "beta.messages.stream" if usa_beta else "messages.stream",
        "betas": betas,
        "fallbacks": "default" if fallbacks else None,
        "timeout_s": cfg.llm.timeout_s,
        "max_retries": cfg.llm.max_retries,
    }
    return {"api": api, "extra": extra, "usa_beta": usa_beta}, parametros


def correr_variante(
    cliente: Any, nombre: str, repeticion: int, peticion: dict, parametros: dict, schema: type, guardar_texto: bool, mostrar: bool = True
) -> dict[str, Any]:
    t0 = time.perf_counter()
    reg = Registro(t0)
    final = None
    error = None
    try:
        api, extra = peticion["api"], peticion["extra"]
        manager = (
            cliente.beta.messages.stream(**api, **extra) if peticion["usa_beta"] else cliente.messages.stream(**api, **extra)
        )
        with manager as flujo:
            reg.t_conexion = reg.t()
            for ev in flujo:
                reg.evento(ev)
            final = flujo.get_final_message()
    except Exception as e:
        error = {
            "tipo": type(e).__name__,
            "status": getattr(e, "status_code", None),
            "mensaje": str(e)[:2000],
            "request_id": getattr(e, "request_id", None),
        }
    resultado = construir_resultado(nombre, repeticion, parametros, reg, final, error, schema, guardar_texto)
    if mostrar:
        imprimir_variante(resultado, guardar_texto)
    return resultado


def imprimir_variante(r: dict, guardar_texto: bool) -> None:
    p = r["parametros"]
    print(f"\n=== Variante {r['variante']} (repeticion {r['repeticion']}) ===")
    print(f"  {p['endpoint']}  modelo={p['modelo']}  effort={p['effort']}  thinking={json.dumps(p['thinking'])}  betas={p['betas']}")
    if r["error"]:
        print(f"  ERROR {r['error']['tipo']} (HTTP {r['error']['status']}): {r['error']['mensaje'][:400]}")
    print(f"  {'t(s)':>7} {'hasta(s)':>8}  {'evento':<34} {'bloque':>6} {'n':>5} {'chars':>7}  detalle")
    lineas = r["lineas_de_tiempo"]
    for fila in lineas[:80]:
        indice = "-" if fila["indice"] is None else fila["indice"]
        print(
            f"  {fila['t']:7.2f} {fila['hasta']:8.2f}  {fila['evento']:<34} {indice!s:>6} {fila['n']:>5} {fila['chars']:>7}  {fila['detalle'][:60]}"
        )
    if len(lineas) > 80:
        print(f"  ... {len(lineas) - 80} filas más (están en el JSON)")
    t = r["tiempos_s"]
    print(
        "  tiempos: conexion={conexion} message_start={message_start} primer_thinking_con_texto={primer_thinking_con_texto} "
        "primer_text={primer_text_delta} total={total}".format(**{k: _f(t.get(k)) for k in t})
    )
    rz = r["razonamiento"]
    print(f"  razonamiento: bloques={rz['bloques']} chars={rz['chars']} visible={rz['visible']} idioma={rz['idioma']}")
    if r.get("uso"):
        print(f"  tokens: entrada={r['uso']['tokens_entrada']} salida={r['uso']['tokens_salida']} stop_reason={r.get('stop_reason')}")
        print(f"  esquema AperturaLLM valido: {r.get('esquema_valido')} {r.get('error_esquema', '')}")
    if guardar_texto:
        for b in r["bloques"]:
            if b["tipo"] == "thinking" and b.get("texto"):
                print(f"  [thinking #{b['indice']}] {b['texto'][:300]!r}")


def _f(x: Any) -> str:
    return "-" if x is None else f"{x:.2f}"


def imprimir_resumen(resultados: list[dict]) -> None:
    print("\n=== Resumen ===")
    cab = f"{'variante':<9} {'rep':>3} {'ok':>3} {'bloq_th':>7} {'chars_th':>8} {'idioma':>8} {'1er_th(s)':>9} {'1er_txt(s)':>10} {'total(s)':>8} {'tok_sal':>7} {'esquema':>7}"
    print(cab)
    for r in resultados:
        t, rz = r["tiempos_s"], r["razonamiento"]
        print(
            f"{r['variante']:<9} {r['repeticion']:>3} {('si' if r['ok'] else 'NO'):>3} {rz['bloques']:>7} {rz['chars']:>8} "
            f"{(rz['idioma'] or {}).get('probable', '-'):>8} {_f(t.get('primer_thinking_con_texto')):>9} {_f(t.get('primer_text_delta')):>10} "
            f"{_f(t.get('total')):>8} {(r.get('uso') or {}).get('tokens_salida', '-')!s:>7} {r.get('esquema_valido', '-')!s:>7}"
        )


def preparar_entrada(args: argparse.Namespace, scratch: Path) -> tuple[Any, _Captura, str, bool]:
    from tutela2 import config as cfgmod
    from tutela2 import graph, ingest
    from tutela2.models import Ingesta

    if args.caso:
        carpeta = Path(args.caso).expanduser().resolve()
        archivo = carpeta / "caso.json"
        if not archivo.is_file():
            raise SystemExit(f"No existe {archivo}; cree el caso en la UI (o con 'tutela2 nuevo') antes de usar --caso.")
        cfg = cfgmod.cargar(carpeta)
        ing = Ingesta.model_validate_json(archivo.read_text(encoding="utf-8"))
        origen, sintetico = str(carpeta), False
    else:
        import caso_sintetico

        if not shutil.which("soffice"):
            raise SystemExit("El caso sintético necesita LibreOffice (soffice); instálelo o use --caso <carpeta de un caso ya creado>.")
        caso_sintetico.generar(scratch)
        caso_sintetico.preparar(scratch, "anthropic")
        cfg = cfgmod.cargar(scratch)
        cfg.cache_dir = str(scratch / "cache")
        ing = ingest.ingerir(scratch, cfg)
        origen, sintetico = "caso sintético (ficticio)", True
    if not ing.completo:
        print(f"Aviso: la ingesta está incompleta (faltan {ing.faltantes}); el prompt de apertura puede no ser representativo.", file=sys.stderr)
    estado = graph.estado_inicial(scratch, cfg, ing)
    try:
        graph.nodo_apertura(estado, cfg, _Espia())
    except _Captura as c:
        return cfg, c, origen, sintetico
    raise RuntimeError("No se pudo capturar el prompt de la etapa apertura.")


def escribir_json(ruta: Path, cabecera: dict, resultados: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({**cabecera, "resultados": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Spike: razonamiento (thinking) en streaming junto con salida estructurada, etapa apertura.")
    p.add_argument("--modelo", help="Por defecto, el modelo configurado (claude-sonnet-5-5)")
    p.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), help="Por defecto, el effort configurado hoy")
    p.add_argument("--max-tokens", type=int, dest="max_tokens", help="Por defecto, llm.max_tokens de la configuración")
    p.add_argument("--variantes", default="base,resumen", help=f"Lista separada por comas de {', '.join(VARIANTES)} (por defecto base,resumen)")
    p.add_argument("--repeticiones", type=int, default=1, help="Repeticiones por variante (la latencia de una sola llamada es solo indicativa)")
    p.add_argument("--caso", help="Carpeta de un caso ya creado (con caso.json) en vez del caso sintético")
    p.add_argument("--guardar-texto", action="store_true", help="Guardar el texto del razonamiento aun con --caso (puede contener datos del expediente)")
    p.add_argument("--sin-fallbacks", action="store_true", help="No usar fallbacks del servidor aunque la configuración los active")
    p.add_argument("--salida", type=Path, default=SALIDA, help=f"JSON de resultados (por defecto {SALIDA})")
    p.add_argument("--si", action="store_true", help="No pedir confirmacion antes de llamar al modelo")
    p.add_argument("--solo-entrada", action="store_true", help="Construir el prompt y mostrar tamaños y parámetros sin llamar al modelo (no requiere clave)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.solo_entrada and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print(SIN_CLAVE, file=sys.stderr)
        return 2
    nombres = [v.strip() for v in args.variantes.split(",") if v.strip()]
    desconocidas = [n for n in nombres if n not in VARIANTES]
    if desconocidas or not nombres:
        print(f"Variantes inválidas: {desconocidas or args.variantes}. Opciones: {', '.join(VARIANTES)}.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="spike_razonamiento_") as tmp:
        cfg, captura, origen, sintetico = preparar_entrada(args, Path(tmp))
    return ejecutar(args, cfg, captura, origen, sintetico, nombres)


def ejecutar(args: argparse.Namespace, cfg: Any, captura: _Captura, origen: str, sintetico: bool, nombres: list[str]) -> int:
    peticiones = {n: argumentos_api(cfg, captura, VARIANTES[n], args) for n in nombres}
    guardar_texto = args.guardar_texto or sintetico
    chars = len(captura.system) + len(captura.user)
    llamadas = len(nombres) * args.repeticiones
    print(f"Entrada: {origen}")
    print(f"Prompt de la etapa {NODO}: system={len(captura.system)} chars, user={len(captura.user)} chars (~{chars // 4} tokens estimados)")
    for n, (_, parametros) in peticiones.items():
        print(f"  {n}: {json.dumps(parametros, ensure_ascii=False)}")
    if args.solo_entrada:
        return 0

    modelo = next(iter(peticiones.values()))[1]["modelo"]
    print(
        f"\nSe llamará al modelo {modelo} {llamadas} vez/veces (variantes {nombres} x {args.repeticiones}), con un tope de "
        f"{next(iter(peticiones.values()))[1]['max_tokens']} tokens de salida por llamada (el razonamiento cuenta contra ese tope). "
        "El costo depende de la tarifa vigente del modelo."
    )
    if sintetico:
        print("Los documentos son ficticios, pero se envían a la API.")
    else:
        print("ATENCION: son documentos de un caso real y se enviarán a la API; revise las reglas de uso de IA de su despacho.")
        if not args.guardar_texto:
            print("El texto del razonamiento NO se guardará en el JSON (use --guardar-texto para incluirlo).")
    if not args.si:
        try:
            respuesta = input("¿Continuar? [s/N] ").strip().lower()
        except EOFError:
            respuesta = ""
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            return 1

    import anthropic

    cliente = anthropic.Anthropic().with_options(max_retries=cfg.llm.max_retries)
    cabecera = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sdk_anthropic": anthropic.__version__,
        "etapa": NODO,
        "origen": origen,
        "texto_razonamiento_guardado": guardar_texto,
        "entrada": {"system_chars": len(captura.system), "user_chars": len(captura.user), "tokens_estimados": chars // 4},
        "variantes": {n: VARIANTES[n]["descripcion"] for n in nombres},
    }
    resultados: list[dict] = []
    try:
        for repeticion in range(1, args.repeticiones + 1):
            for nombre in nombres:
                peticion, parametros = peticiones[nombre]
                resultados.append(
                    correr_variante(cliente, nombre, repeticion, peticion, parametros, captura.schema, guardar_texto)
                )
                escribir_json(args.salida, cabecera, resultados)
    except KeyboardInterrupt:
        print("\nInterrumpido; se conservan los resultados parciales.", file=sys.stderr)
    escribir_json(args.salida, cabecera, resultados)
    imprimir_resumen(resultados)
    print(f"\nResultados escritos en {args.salida}")
    return 0 if resultados and any(r["ok"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
