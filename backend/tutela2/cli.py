from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from tutela2 import api, jev_bench
from tutela2.config import Config
from tutela2.jev import HttpJev

COMANDOS = (
    "config-default",
    "prompts-default",
    "nuevo",
    "revisar",
    "iniciar",
    "estado",
    "decidir",
    "continuar",
    "jev-bench",
)
RAIZ_REPO = Path(__file__).resolve().parents[2]


def _json(ruta: Path | None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta else None


def _jev_bench(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.referencia is None:
        parser.error("--referencia es obligatorio para jev-bench")
    if not (args.referencia / "analisis" / "ground_truth_1a.json").is_file():
        parser.error(f"No existe {args.referencia / 'analisis' / 'ground_truth_1a.json'}")
    salida = args.salida.resolve() if args.salida else None
    if salida is not None and (RAIZ_REPO / ".git").exists() and salida.is_relative_to(RAIZ_REPO):
        parser.error("--salida no puede estar dentro del repositorio: el informe contiene datos de los casos")
    clave = os.environ.get("JEV_API_KEY", "").strip()
    if not clave:
        parser.error("Falta la variable de entorno JEV_API_KEY (uv run --env-file ../.local.env tutela2 jev-bench ...)")
    cfg = Config()
    informe = jev_bench.correr(args.referencia, HttpJev(clave, cfg.jev.timeout_s), cfg, args.invertir)
    texto = jev_bench.informe_markdown(informe)
    if salida is None:
        print(texto, end="")
    else:
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text(texto, encoding="utf-8")
        print(f"Informe escrito en {salida}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutela2", description="Proyecto de fallos de tutela de segunda instancia")
    parser.add_argument("comando", choices=COMANDOS)
    parser.add_argument("--caso", type=Path, help="Carpeta del caso")
    parser.add_argument("--decision", type=Path, help="Archivo JSON con la decisión (solo para decidir)")
    parser.add_argument("--roles", type=Path, help="JSON {doc_id: rol} (solo para revisar)")
    parser.add_argument("--auto", type=Path, help="JSON con los datos del auto (solo para revisar)")
    parser.add_argument("--referencia", type=Path, help="Carpeta referencia/ (solo para jev-bench)")
    parser.add_argument("--invertir", action="store_true", help="Repite con las opciones en orden inverso (solo para jev-bench)")
    parser.add_argument("--salida", type=Path, help="Archivo del informe, fuera del repositorio (solo para jev-bench)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.comando == "jev-bench":
        return _jev_bench(parser, args)

    if args.comando == "config-default":
        resultado = api.config_default()
    elif args.comando == "prompts-default":
        resultado = api.prompts_default()
    else:
        if args.caso is None:
            parser.error("--caso es obligatorio para este comando")
        if args.comando == "decidir":
            if args.decision is None:
                parser.error("--decision es obligatorio para decidir")
            resultado = api.decidir(args.caso, json.loads(args.decision.read_text(encoding="utf-8")))
        elif args.comando == "revisar":
            resultado = api.revisar(args.caso, _json(args.roles), _json(args.auto))
        else:
            resultado = getattr(api, args.comando)(args.caso)

    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
