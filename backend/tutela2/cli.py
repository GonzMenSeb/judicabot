from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from tutela2 import api

COMANDOS = ("config-default", "prompts-default", "nuevo", "revisar", "iniciar", "estado", "decidir", "continuar")


def _json(ruta: Path | None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutela2", description="Proyecto de fallos de tutela de segunda instancia")
    parser.add_argument("comando", choices=COMANDOS)
    parser.add_argument("--caso", type=Path, help="Carpeta del caso")
    parser.add_argument("--decision", type=Path, help="Archivo JSON con la decisión (solo para decidir)")
    parser.add_argument("--roles", type=Path, help="JSON {doc_id: rol} (solo para revisar)")
    parser.add_argument("--auto", type=Path, help="JSON con los datos del auto (solo para revisar)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")

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
